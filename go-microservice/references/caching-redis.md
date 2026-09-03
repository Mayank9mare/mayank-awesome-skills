# Caching & Redis in Go

## Client choice

| Client | Use when |
|---|---|
| **rueidis** | **Default.** RESP3, client-side caching, auto-pipelining of concurrent commands. Fastest in practice. |
| **go-redis/v9** | Larger community, more examples, RESP3 via `Protocol: 3`. Safe, conventional choice. |
| redigo | Legacy only. |

**rueidis's catch:** client-side caching needs Redis ≥6.0 with RESP3 **and
`CLIENT TRACKING`**. Some managed providers don't support tracking (GCP Memorystore, some
ElastiCache configurations) and you get `ErrNoCache`. Verify against your actual Redis
before designing around `DoCache`. `rueidiscompat` gives a go-redis-shaped API for
migration.

```go
client, err := rueidis.NewClient(rueidis.ClientOption{
    InitAddress: []string{cfg.RedisAddr},
    // Timeouts are NOT optional. A command with no deadline against a stalled
    // Redis blocks the caller — and then the cache is the outage.
    ConnWriteTimeout: 2 * time.Second,
    Dialer:           net.Dialer{Timeout: 1 * time.Second},
    DisableCache:     cfg.RedisDisableClientCache, // for providers without CLIENT TRACKING
})
```

With go-redis:

```go
rdb := redis.NewClient(&redis.Options{
    Addr:            cfg.RedisAddr,
    DialTimeout:     1 * time.Second,
    ReadTimeout:     2 * time.Second,   // per-command
    WriteTimeout:    2 * time.Second,
    PoolSize:        10 * runtime.GOMAXPROCS(0),
    MinIdleConns:    5,
    PoolTimeout:     1 * time.Second,   // wait for a free conn, then fail fast
    ConnMaxIdleTime: 5 * time.Minute,
})
```

## Treat the cache as optional infrastructure

The single most valuable habit here. Every read and write wrapped so a Redis failure
degrades **performance**, not **availability**.

```go
func (s *Service) GetUser(ctx context.Context, id string) (*User, error) {
    key := "myservice:v1:user:" + id

    if u, err := s.cacheGet(ctx, key); err == nil && u != nil {
        return u, nil
    } else if err != nil && !errors.Is(err, ErrCacheMiss) {
        // Log and continue. A cache outage must not become an outage.
        slog.WarnContext(ctx, "cache read failed", "key", key, "error", err)
    }

    u, err := s.repo.GetUser(ctx, id)
    if err != nil {
        return nil, err
    }

    if err := s.cacheSet(ctx, key, u, 10*time.Minute); err != nil {
        slog.WarnContext(ctx, "cache write failed", "key", key, "error", err)
        // Still return the value — the request succeeds.
    }
    return u, nil
}
```

Give cache operations a **shorter timeout than the database call they're avoiding**. If
the cache takes longer than the source of truth, it's actively harmful.

## Key design

```
myservice:v1:user:{id}          # service : schema version : type : id
myservice:v1:user:{id}:perms
myservice:lock:nightly-recon
```

- **Prefix by service** so a shared Redis stays debuggable and per-service memory is
  measurable.
- **Version the prefix.** When a value's shape changes, bump `v1`→`v2` instead of writing
  a migration or flushing production.
- **Never `KEYS *` in production** — it's O(n) and blocks the single-threaded server. Use
  `SCAN` with a cursor.
- **Watch for hot keys.** One key every request needs serialises all traffic through one
  shard.

## TTL always

A cache without expiry is a second database with no schema, no backups, and entries that
outlive every deploy. Set a TTL on every write, even when you also invalidate explicitly
— the TTL is your backstop for the invalidation you forgot.

## Stampede (thundering herd)

When a hot key expires, every concurrent request misses at once and they all hit the
database simultaneously. At scale this is how an expiring cache key takes down a
database.

**Single flight** — the simplest effective fix. One goroutine does the work; the rest
wait for its result:

```go
import "golang.org/x/sync/singleflight"

type Service struct {
    sf singleflight.Group
    // ...
}

func (s *Service) GetUser(ctx context.Context, id string) (*User, error) {
    key := "user:" + id
    if u, err := s.cacheGet(ctx, key); err == nil && u != nil {
        return u, nil
    }

    // Concurrent callers for the same key share ONE database call.
    v, err, _ := s.sf.Do(key, func() (any, error) {
        u, err := s.repo.GetUser(ctx, id)
        if err != nil {
            return nil, err
        }
        _ = s.cacheSet(ctx, key, u, 10*time.Minute)
        return u, nil
    })
    if err != nil {
        return nil, err
    }
    return v.(*User), nil
}
```

Note `singleflight` dedupes **within one process**. Across N replicas you still get up to
N concurrent loads — usually fine, and far better than N × concurrency. For genuinely
expensive loads, add a short Redis lock.

Other approaches: **probabilistic early expiry** (refresh when a random draw says the
entry is near expiry, spreading refreshes over time) and **stale-while-revalidate**
(serve the stale value, refresh in the background). Both trade a little staleness for a
smooth load profile.

## Negative caching

If "not found" is a common outcome and you don't cache it, every request for a missing
key hits the database — a trivially easy scan-amplification attack, and a common source
of surprise load.

```go
// Cache the absence, with a SHORTER TTL than a positive result.
if errors.Is(err, ErrNotFound) {
    _ = s.cacheSetSentinel(ctx, key, 30*time.Second)
    return nil, ErrNotFound
}
```

Keep the negative TTL short so a newly created record becomes visible quickly.

## Serialisation

| Format | Use when |
|---|---|
| **JSON** | Default. Portable, debuggable with `redis-cli`, language-agnostic. |
| msgpack / protobuf | Size or CPU matters measurably, and only your service reads it. |
| `encoding/gob` | Avoid — Go-only and brittle across type changes. |

Whatever you choose, **treat a deserialisation failure as a miss**, not an error. Cached
data written by an older binary is a normal condition during a rolling deploy, not an
exception:

```go
var u User
if err := json.Unmarshal(raw, &u); err != nil {
    slog.WarnContext(ctx, "cache decode failed, treating as miss", "key", key)
    return nil, ErrCacheMiss     // fall through to the source of truth
}
```

## Distributed locks

Use one when exactly one instance may act: a scheduled job, a non-idempotent external
call, a one-shot migration.

```go
// redsync over one or more Redis instances
mutex := rs.NewMutex("myservice:lock:"+job,
    redsync.WithExpiry(60*time.Second),      // lease: a dead holder MUST expire
    redsync.WithTries(1),                    // for a cron job, don't queue — skip
)

if err := mutex.LockContext(ctx); err != nil {
    slog.InfoContext(ctx, "job already running elsewhere, skipping", "job", job)
    return nil
}
defer func() {
    if ok, err := mutex.UnlockContext(ctx); !ok || err != nil {
        slog.WarnContext(ctx, "failed to release lock", "job", job, "error", err)
    }
}()

return doWork(ctx)
```

Be honest about what this gives you:

- **A Redis lock is not a correctness guarantee.** Under replication failover you can get
  two holders (the Redlock debate — Kleppmann's critique is worth reading). Use it to
  **reduce duplicate work**, not to protect an invariant.
- **Always set a lease.** Without an expiry, a crashed holder wedges the key until a human
  deletes it.
- **Lease > worst-case work duration**, or the lock expires mid-job and a second worker
  starts. If you can't bound the duration, renew in a background goroutine — and stop
  renewing when the work finishes.
- **Make the guarded work idempotent anyway.** Assume the lock will occasionally fail.

For real mutual exclusion, use the database: a unique constraint, a conditional
`UPDATE ... WHERE version = $2`, or a fencing token.

## What not to put in Redis

- **Data you can't lose.** Default Redis config can lose recent writes on failover.
- **Large values.** Multi-MB entries cause latency spikes, saturate the network, and make
  `maxmemory` eviction unpredictable.
- **Anything needing transactional consistency with your database.** There's no two-phase
  commit; the cache *will* be briefly wrong. Design for it: short TTLs,
  invalidate-on-write, and accept staleness explicitly.
- **A durable queue.** `LPUSH`/`BRPOP` loses messages on failover. Streams are decent; a
  real broker is better. See messaging.md.

## Eviction and memory

Set `maxmemory` and a policy on the server, or Redis will OOM the box.

- **Pure cache → `allkeys-lru`** (or `allkeys-lfu`). Evicts something rather than failing
  writes.
- **`noeviction` is the default** and turns a full cache into *write errors* — correct for
  a datastore, wrong for a cache.
- Alert on **`evicted_keys`** (rising = undersized) and **hit ratio** (falling = your
  caching isn't working, or TTLs are too short).

## Checklist

- [ ] Dial and per-command timeouts set
- [ ] Pool sized; `PoolTimeout` set so callers fail fast rather than queue
- [ ] Every read and write wrapped — cache failure degrades performance, not availability
- [ ] Cache timeout shorter than the DB call it replaces
- [ ] TTL on every write
- [ ] Keys prefixed by service and schema version
- [ ] No `KEYS` in production — `SCAN` only
- [ ] Stampede protection on hot keys (singleflight, at minimum)
- [ ] Negative results cached with a short TTL if misses are common
- [ ] Deserialisation failure treated as a miss, not an error
- [ ] Locks have a lease; guarded work is idempotent anyway
- [ ] `maxmemory` + `allkeys-lru` for caches; alerts on evictions and hit ratio
