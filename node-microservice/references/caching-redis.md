# Redis caching in Node

## ioredis vs node-redis

| | ioredis | node-redis (`redis`) |
|---|---|---|
| Cluster support | Excellent, mature | Good, improved a lot in v4+ |
| API style | Callback-era-shaped but promise-based, very complete command coverage | Modern promise-native, closer to raw Redis command names |
| Pipelining/transactions | `.pipeline()`/`.multi()`, very ergonomic | `.multi()`, also solid |
| Reconnection | Built-in, highly configurable retry strategy | Built-in, configurable |
| Sentinel support | Yes, first-class | Yes |
| Community/maturity | Long track record, widely deployed | Official client, actively developed, closing the gap |

Both are production-grade. ioredis has the longer track record for
cluster/sentinel-heavy deployments; node-redis is the "official" client and
has closed most historical gaps. Pick one and standardize — the actual
failure mode in most codebases isn't picking the wrong one, it's using
*both* inconsistently across services, or worse, constructing a new client
per request (see below).

## The client: created once, reused, tuned for failure

```js
// WRONG — a new connection per request. Exhausts Redis's connection limit
// under load, and pays connection-setup latency on every single call.
async function getCached(key) {
  const client = new Redis(process.env.REDIS_URL);
  const value = await client.get(key);
  client.disconnect();
  return value;
}

// RIGHT — one client, module-scope, connected once, reused for the life
// of the process
import Redis from 'ioredis';

const redis = new Redis(process.env.REDIS_URL, {
  connectTimeout: 2000,        // fail fast if Redis is unreachable at boot
  commandTimeout: 1000,        // no single command hangs the caller forever
  maxRetriesPerRequest: 2,     // give up quickly per-command rather than queueing forever
  enableOfflineQueue: true,    // queue commands briefly during a reconnect instead of erroring immediately
  retryStrategy(times) {
    if (times > 10) return null;               // stop retrying, surface as down
    return Math.min(times * 100, 2000);        // backoff, capped
  },
});

redis.on('error', (err) => logger.error({ err }, 'redis connection error'));

export default redis;
```

`enableOfflineQueue: true` is the right default for most services: a
transient Redis blip during a reconnect gets absorbed rather than instantly
failing every in-flight cache read. But it must be paired with
`maxRetriesPerRequest` and `commandTimeout` — an unbounded offline queue
during a *sustained* outage becomes an unbounded memory leak of queued
commands that will eventually all time out anyway. Bound both directions.

## Cache-aside, wrapped so Redis failure degrades performance, not availability

The cardinal rule: **Redis is an optimization, not a dependency your
request path can go down with.** If Redis is unreachable, the request
should fall through to the source of truth and simply be slower — never
throw, never 500.

```js
// WRONG — a cache failure becomes a request failure
async function getUser(id) {
  const cached = await redis.get(`user:${id}`);   // throws if Redis is down
  if (cached) return JSON.parse(cached);
  const user = await db.user.findUnique({ where: { id } });
  await redis.set(`user:${id}`, JSON.stringify(user), 'EX', 300);
  return user;
}

// RIGHT — every Redis operation is wrapped; failure just skips the cache
async function safeGet(key) {
  try {
    return await redis.get(key);
  } catch (err) {
    logger.warn({ err, key }, 'cache read failed, falling through');
    return null;
  }
}

async function safeSet(key, value, ttlSeconds) {
  try {
    await redis.set(key, value, 'EX', ttlSeconds);
  } catch (err) {
    logger.warn({ err, key }, 'cache write failed, ignoring');
  }
}

async function getUser(id) {
  const cached = await safeGet(`user:v2:${id}`);
  if (cached) return JSON.parse(cached);

  const user = await db.user.findUnique({ where: { id } });
  if (user) await safeSet(`user:v2:${id}`, JSON.stringify(user), 300);
  return user;
}
```

Every cache read and write in the codebase should go through wrappers like
these — never a raw `redis.get`/`redis.set` call inline in business logic.
The one place this doesn't apply is when Redis *is* your source of truth
(rate limiters, distributed locks, session stores with no fallback) — there,
a Redis failure legitimately should fail the operation, but that's a
deliberate architectural choice, not the default.

## Key design

Prefix every key with service name and a schema version:

```
myservice:v2:user:1234
myservice:v2:session:abcd-ef01
```

The version segment is what saves you when the *shape* of a cached value
changes — bump `v1` to `v2` and old cached entries simply become
cache-misses (never read, eventually evicted) instead of getting deserialized
into a mismatched shape and crashing the reader. Cheaper than a flush, and
safe across a rolling deploy where old and new code briefly coexist.

## TTL, always

Every cached value gets an expiration. No exceptions, even for data that
"never changes" — because eventually something you were sure would never
change, changes, and a key with no TTL is a leak that also serves stale
data forever.

```js
await redis.set(key, value, 'EX', 300);          // ioredis: EX = seconds
// or, if you must set then TTL separately:
await redis.set(key, value);
await redis.expire(key, 300);                     // never leave this step out
```

## Stampede protection: single-flight via a promise map

When a hot key expires, many concurrent requests can all miss the cache at
once and all hammer the database simultaneously to recompute the same
value — a "stampede." Guard it in-process with a map of in-flight promises
so concurrent callers on the same instance share one recomputation:

```js
const inflight = new Map();   // key -> Promise

async function getWithSingleFlight(key, ttlSeconds, compute) {
  const cached = await safeGet(key);
  if (cached) return JSON.parse(cached);

  // Someone on this instance is already recomputing this key — wait on it
  // instead of starting a second, redundant computation.
  if (inflight.has(key)) return inflight.get(key);

  const promise = (async () => {
    try {
      const value = await compute();
      if (value !== null && value !== undefined) {
        await safeSet(key, JSON.stringify(value), ttlSeconds);
      }
      return value;
    } finally {
      inflight.delete(key);   // always clear, success or failure
    }
  })();

  inflight.set(key, promise);
  return promise;
}

// usage
const product = await getWithSingleFlight(
  `myservice:v1:product:${id}`,
  300,
  () => db.product.findUnique({ where: { id } }),
);
```

This only protects within a single process — across N replicas you still
get N concurrent recomputations on a stampede. For a hot-enough key that
matters, add a short Redis-based lock (see below) around the compute step,
or use a "refresh slightly before expiry" strategy so keys rarely fully
expire under load.

## Negative caching

Caching the *absence* of a value prevents repeated expensive lookups for
things that don't exist (a common enumeration/scraping attack vector, and
just plain wasteful for legitimate 404s):

```js
async function getUser(id) {
  const cached = await safeGet(`user:v2:${id}`);
  if (cached === NEGATIVE_SENTINEL) return null;    // cached "doesn't exist"
  if (cached) return JSON.parse(cached);

  const user = await db.user.findUnique({ where: { id } });
  if (!user) {
    await safeSet(`user:v2:${id}`, NEGATIVE_SENTINEL, 60);   // shorter TTL than positive hits
    return null;
  }
  await safeSet(`user:v2:${id}`, JSON.stringify(user), 300);
  return user;
}
```

Use a shorter TTL for negative entries than positive ones — a legitimately
created resource shouldn't stay invisible for as long as a real cache hit
is allowed to stay fresh.

## Distributed locks — and their honest limits

A Redis lock (`SET key value NX PX ttl`, released by a script that checks
the value matches before deleting) can coordinate "only one instance should
do this right now" for cheap, low-stakes work — deduplicating a cron job
across replicas, single-flighting a stampede across the fleet.

```js
async function withLock(key, ttlMs, fn) {
  const token = crypto.randomUUID();
  const acquired = await redis.set(key, token, 'PX', ttlMs, 'NX');
  if (!acquired) return null;   // someone else holds it; caller decides what to do

  try {
    return await fn();
  } finally {
    // Only delete if we still hold it — a Lua script makes check-and-delete atomic
    await redis.eval(
      `if redis.call("get", KEYS[1]) == ARGV[1] then return redis.call("del", KEYS[1]) else return 0 end`,
      1, key, token,
    );
  }
}
```

**Be honest about what this does and doesn't guarantee.** It is not a
correctness primitive for anything where a violated mutual exclusion causes
real damage (double-charging a payment, double-shipping an order). Clock
drift, GC pauses, and network partitions can all cause a lock holder to
believe it still holds a lock after its TTL expired and someone else
acquired it. If you need real distributed correctness, use a database
transaction / unique constraint, not a Redis lock — Redis locks are for
*efficiency* (avoid redundant work), not *correctness* (prevent conflicting
work).

## `SCAN`, not `KEYS`

`KEYS *` walks the entire keyspace synchronously and blocks Redis (a
single-threaded server) for the duration — on a keyspace of any real size,
this is a self-inflicted outage.

```js
// WRONG — blocks the Redis event loop for every other client while it runs
const keys = await redis.keys('myservice:v2:session:*');

// RIGHT — SCAN walks the keyspace incrementally with a cursor, never
// blocking for more than a fraction of a millisecond per call
async function scanKeys(pattern) {
  const found = [];
  let cursor = '0';
  do {
    const [next, keys] = await redis.scan(cursor, 'MATCH', pattern, 'COUNT', 100);
    found.push(...keys);
    cursor = next;
  } while (cursor !== '0');
  return found;
}
```

Never run `KEYS` against a production instance, including "just this once
for debugging" — it's exactly the kind of one-off that takes down a shared
Redis cluster during an incident you're trying to resolve.

## Eviction policy

Set `maxmemory` and an eviction policy explicitly — the default
(`noeviction`) makes Redis start *rejecting writes* once memory fills up,
which for a cache-aside pattern turns into every write silently failing (if
you followed the safe-wrapper pattern above) or throwing (if you didn't).

For a pure cache workload, `allkeys-lru` or `allkeys-lfu` is almost always
right — evict the least-recently/frequently-used key regardless of TTL when
memory pressure hits, rather than refusing new writes. Reserve
`volatile-*` policies (only evict keys with a TTL set) for a mixed
workload where some keys in the same instance are *not* disposable cache
entries — and prefer a separate Redis instance/logical DB for anything
that isn't a cache, so the eviction policy for the cache doesn't have to
compromise for non-cache data sharing the same keyspace.

## Checklist

- [ ] One client per process, constructed once, never per-request
- [ ] `connectTimeout`/`commandTimeout`/`maxRetriesPerRequest` all set —
      no operation can hang the caller indefinitely
- [ ] Every cache read/write wrapped so a Redis failure degrades to a
      cache miss, never an exception that fails the request
- [ ] Keys prefixed with service name + schema version
- [ ] Every key has a TTL — no exceptions
- [ ] Stampede protection (single-flight, or refresh-before-expiry) on any
      hot key whose recomputation is expensive
- [ ] Negative caching used for lookups that can legitimately miss, with a
      shorter TTL than positive entries
- [ ] Distributed locks used only for efficiency (dedup/avoid redundant
      work), never as a correctness guarantee for money-moving operations
- [ ] No `KEYS` in any code path that can run against production — `SCAN` only
- [ ] `maxmemory` + an explicit eviction policy set, not left at the
      reject-writes default
