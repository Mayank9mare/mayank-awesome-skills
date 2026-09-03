# Caching with Redis

## Client

`redis.asyncio` (part of `redis-py`) is the async client. **`aioredis` is
DEPRECATED** — its maintainers merged the project into `redis-py` in 2022, and
new work should import `redis.asyncio` directly, not the standalone `aioredis`
package, which no longer receives updates.

```python
import redis.asyncio as redis

# hiredis extra: swaps the pure-Python protocol parser for the C one.
# pip install redis[hiredis] — meaningfully cuts CPU on high-throughput services.
pool = redis.ConnectionPool.from_url(
    "redis://localhost:6379/0",
    max_connections=50,
    socket_timeout=2.0,           # read/write timeout on an established connection
    socket_connect_timeout=1.0,   # separate, shorter timeout for establishing the connection
    decode_responses=True,        # get str back, not bytes — set once, project-wide
)
```

**`socket_timeout` and `socket_connect_timeout` must be set explicitly.**
Without them, a command against a stalled or network-partitioned Redis blocks
the calling coroutine indefinitely. The moment that happens, Redis — which you
almost certainly added to make things *faster* — becomes the reason the whole
request pipeline is hung. A cache is only a strict improvement over "no cache"
if a slow cache can never be slower than skipping it.

Create the pool once at startup, reuse it everywhere, close it on shutdown —
the exact same lifespan pattern as the httpx client:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = redis.Redis(connection_pool=pool)
    try:
        yield
    finally:
        await app.state.redis.aclose()

app = FastAPI(lifespan=lifespan)
```

## Cache-aside — wrap every call so Redis failures degrade, not outage

This is the single most valuable habit in this document. A cache-aside read
that lets a Redis exception propagate has turned an optional optimization into
a hard dependency — Redis flaking now takes your service down even though the
database it's caching is perfectly healthy.

```python
import logging

logger = logging.getLogger(__name__)


async def get_user(redis_client: redis.Redis, db: AsyncSession, user_id: int) -> User:
    key = f"myservice:v1:user:{user_id}"

    # READ: a Redis failure here should look exactly like a cache miss —
    # fall through to the DB, don't fail the request.
    try:
        cached = await redis_client.get(key)
        if cached is not None:
            return User.model_validate_json(cached)
    except redis.RedisError:
        logger.warning("redis read failed, falling back to db", extra={"key": key})

    user = await load_user_from_db(db, user_id)

    # WRITE: a Redis failure here should not fail the request either —
    # the caller already has their answer, populating the cache is a bonus.
    try:
        await redis_client.set(key, user.model_dump_json(), ex=300)
    except redis.RedisError:
        logger.warning("redis write failed, continuing without cache", extra={"key": key})

    return user
```

Every read and write against the cache goes through this shape: try, catch
`redis.RedisError` specifically, log, and fall back to "as if the cache didn't
exist." The database becomes slower under a Redis outage; it does not become
unreachable.

## Key design

```
myservice:v1:user:{id}
^^^^^^^^^ ^^ ^^^^^^^^^^
service   ver  entity+id
```

- **Prefix per service** (`myservice:`) — Redis is frequently shared across
  services in the same cluster/namespace; without a prefix, two services'
  keyspaces collide.
- **A version segment** (`v1:`) — when the *shape* of what you cache changes
  (new field, different serialization), bump to `v2:` instead of running a
  `FLUSHDB` or hoping every consumer handles both shapes gracefully during
  rollout. Old `v1:` keys simply expire on their existing TTL and are never
  read again.

**Never `KEYS *` in production.** `KEYS` is O(n) over the entire keyspace and
Redis is single-threaded — a `KEYS` scan over a few million keys blocks every
other client for the duration. Use `SCAN`, which walks the keyspace in
bounded-cost increments and never blocks the server:

```python
# WRONG — O(n), blocks Redis for the full scan
keys = await redis_client.keys("myservice:v1:user:*")

# RIGHT — cursor-based, bounded cost per call, non-blocking
async for key in redis_client.scan_iter(match="myservice:v1:user:*", count=100):
    ...
```

## TTL, always

A cache entry with no expiry is a second database — except it has no schema
migration story, no backup, and no consistency guarantee with the source of
truth. Every key you write should carry an explicit `ex=`/`px=`. If a value
truly needs to live forever, that's a statement that it belongs in the primary
datastore, not in Redis.

```python
await redis_client.set(key, value, ex=300)   # 5 minutes, not "however long until someone notices"
```

## Stampede / thundering herd

When one hot key expires, every request that was relying on it misses
simultaneously and all of them hit the database at once — for a sufficiently
hot key, this can look like a self-inflicted DDoS on your own DB, all
triggered by one TTL tick.

**Single-flight with a per-key lock** — only one coroutine actually queries
the DB; the rest wait for it and reuse its result:

```python
import asyncio

_locks: dict[str, asyncio.Lock] = {}   # process-local; see Redis lock below for multi-process

async def get_with_singleflight(redis_client: redis.Redis, db: AsyncSession, key: str, uid: int) -> User:
    cached = await redis_client.get(key)
    if cached is not None:
        return User.model_validate_json(cached)

    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        # re-check: another task in this process may have already refilled it
        # while we were waiting for the lock
        cached = await redis_client.get(key)
        if cached is not None:
            return User.model_validate_json(cached)

        user = await load_user_from_db(db, uid)
        await redis_client.set(key, user.model_dump_json(), ex=300)
        return user
```

`asyncio.Lock` only dedupes within one process — fine for a single replica,
insufficient across N replicas all missing at once. For that, use a Redis
lock (§8) around the refill instead, so only one replica in the whole fleet
refills a given key.

Other mitigations, often combined:

- **Probabilistic early expiry** — recompute slightly before the real TTL,
  with randomized jitter per request, so the herd never forms in the first
  place because no two clients agree on exactly when the key is "expired".
- **Stale-while-revalidate** — serve the expired value immediately while one
  request refreshes it in the background; everyone else gets a slightly stale
  but fast answer instead of piling onto the DB.

## Negative caching

If "not found" is a common, repeatable outcome (a lookup by a typo'd ID, a
not-yet-provisioned account), and you don't cache the miss, every request for
that same missing key goes all the way to the database, every time, forever.
Cache a sentinel with a short TTL:

```python
_MISSING = "__MISSING__"

async def get_user_or_none(redis_client: redis.Redis, db: AsyncSession, uid: int) -> User | None:
    key = f"myservice:v1:user:{uid}"
    cached = await redis_client.get(key)
    if cached == _MISSING:
        return None                          # negative cache hit — no DB call
    if cached is not None:
        return User.model_validate_json(cached)

    user = await load_user_from_db(db, uid)
    if user is None:
        await redis_client.set(key, _MISSING, ex=60)   # short TTL — don't hide a fix for long
        return None

    await redis_client.set(key, user.model_dump_json(), ex=300)
    return user
```

Keep the negative TTL shorter than the positive one — a "not found" that gets
fixed (the record gets created) should stop being wrong quickly.

## Serialization

| Format | Speed | Portability | Safety |
|---|---|---|---|
| JSON (`json`, or Pydantic's `model_dump_json`) | Moderate | Cross-language, human-readable in `redis-cli` | Safe |
| `msgspec` / `orjson` | Fast | JSON-compatible on the wire | Safe |
| **`pickle`** | Fast | Python-only | **Never for untrusted or shared data** |

`pickle.loads` on attacker-controlled or otherwise untrusted bytes is arbitrary
code execution — deserializing a crafted pickle payload can run arbitrary
Python during unpickling, not after. If anything other than your own service
can write to that Redis keyspace (another service, a client, an operator
running `redis-cli` by hand), pickle is a remote-code-execution vector, full
stop. Default to JSON for anything crossing a trust or process boundary; reach
for `msgspec`/`orjson` when profiling shows serialization cost actually
matters; reach for `pickle` only for same-process, same-trust-boundary,
never-touched-by-a-human data, and even then think twice.

## Distributed locks

```python
async def refresh_hot_report(redis_client: redis.Redis, db: AsyncSession) -> None:
    lock = redis_client.lock("myservice:v1:lock:hot-report", timeout=30, blocking_timeout=5)
    acquired = await lock.acquire()
    if not acquired:
        return   # someone else is already refreshing it — that's fine, skip

    try:
        await do_expensive_refresh(db)
    finally:
        await lock.release()
```

Be honest about what this buys you. A Redis lock is **not** a correctness
guarantee under node failure or failover — this is the substance of the
long-running Redlock debate (Redis's own author proposed Redlock for
multi-node safety; distributed-systems researchers, notably Martin Kleppmann,
showed scenarios — clock jumps, GC pauses, network partitions — where even
Redlock allows two clients to simultaneously believe they hold the same lock).
Use a Redis lock to **reduce duplicate work** — don't run the same expensive
refresh five times because five requests raced to be first. Do not use it to
protect an invariant that must never be violated (e.g. "only one process may
ever debit this account") — that belongs in the database, via a transaction
and a row lock or a unique constraint.

Always set a lease/timeout (`timeout=30` above). Without one, a holder that
crashes or gets OOM-killed while holding the lock wedges that key forever —
every future acquire attempt blocks or fails until an operator manually
deletes the lock key. And because the lock is only reducing duplicate work,
not enforcing correctness, make the guarded operation idempotent anyway — if
the lease expires mid-operation and a second process starts the same work,
running it twice must be safe, not just unlikely.

## What not to put in Redis

- **Unrecoverable session state** with no tested persistence path. If Redis
  restarts (maxmemory eviction, a bad deploy, a failover) and that's the only
  copy of "is this user logged in," you've built a session store with no
  backup plan.
- **Large values.** A multi-megabyte value blocks the single-threaded server
  for the duration of the read/write and causes unpredictable memory
  pressure — Redis is built for many small, fast operations, not as a blob
  store.
- **Anything requiring transactional consistency with the primary database.**
  Redis transactions (`MULTI`/`EXEC`) don't span into Postgres/MySQL. If a
  cache write must succeed or fail atomically with a DB write, that's not a
  cache-aside problem, it's a distributed-transaction problem, and the honest
  answer is usually "make Redis a derived, rebuildable view, not a source of
  truth."
- **A durable queue.** Plain `LPUSH`/`BRPOP` loses in-flight messages on a
  failover — there's no acknowledgment, no redelivery, no persistence
  guarantee beyond Redis's own (optional, lossy-under-crash) persistence.
  Redis **Streams** with consumer groups are considerably better (they do have
  acks and redelivery), but if you're reaching for "durable, at-least-once,
  survives-a-crash" semantics, a real broker (SQS, Kafka, RabbitMQ — see
  `messaging.md`) is a better foundation than reimplementing one on top of a
  cache.

## Eviction and memory

```
maxmemory 2gb
maxmemory-policy allkeys-lru
```

For a pure cache, `allkeys-lru` (or `allkeys-lfu`) is almost always right —
when memory fills up, evict the least-recently-used key to make room for new
writes. The default policy, **`noeviction`, turns a full cache into write
errors**: once `maxmemory` is hit, `SET` commands start failing outright
instead of evicting old data, which — because of the cache-aside error
handling in §2 — degrades your service in the write path exactly the way a
Redis outage would, just self-inflicted by capacity rather than by an actual
failure.

Alert on:

- **`evicted_keys`** rising — a non-zero, growing count means you're
  under-provisioned for your working set; either raise `maxmemory` or shorten
  TTLs.
- **Hit ratio** dropping — `keyspace_hits / (keyspace_hits + keyspace_misses)`.
  A sustained drop means the cache stopped doing its job (undersized, TTLs too
  short, a key-design change fragmented what used to be a hot key) well before
  anyone would notice from latency alone.

## Checklist

- [ ] `redis.asyncio` (redis-py) — not the deprecated standalone `aioredis`
- [ ] `hiredis` extra installed for the C parser
- [ ] `ConnectionPool` created once at startup, closed on shutdown
- [ ] `socket_timeout` and `socket_connect_timeout` set explicitly
- [ ] Every cache read/write wrapped in try/except `redis.RedisError`, falling back to the source of truth
- [ ] Keys namespaced: `service:version:entity:id`
- [ ] `SCAN`/`scan_iter`, never `KEYS *`, in any code path that can run in production
- [ ] Every key has a TTL — no un-expiring cache entries
- [ ] Stampede protection on hot keys (single-flight lock, early expiry, or stale-while-revalidate)
- [ ] Negative caching for common "not found" lookups, with a short TTL
- [ ] No `pickle` for anything not fully same-process, same-trust-boundary
- [ ] Distributed locks have a timeout/lease; guarded work is idempotent regardless
- [ ] `maxmemory` + `allkeys-lru`/`allkeys-lfu` set — not left on default `noeviction`
- [ ] Alerts on `evicted_keys` and cache hit ratio
