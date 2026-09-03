# Caching & Redis in Java

## Client: Lettuce vs Jedis

**Use Lettuce.** It is the Spring Boot default, netty-based, non-blocking, and a
single connection is safe to share across threads. Jedis connections are blocking
and exclusive, so every concurrent operation needs its own pooled connection —
which becomes a hard bottleneck exactly when you add virtual threads (thousands of
threads contending for a pool of 8).

Only choose Jedis for a legacy codebase already built on it. If you see
`JedisConnectionFactory` in a service you're modernising, migrating to Lettuce is
usually a small change with a real concurrency payoff.

```yaml
spring:
  data:
    redis:
      host: ${REDIS_HOST:localhost}
      port: ${REDIS_PORT:6379}
      timeout: 2s              # command timeout — NOT optional
      connect-timeout: 1s
      lettuce:
        pool:
          enabled: true
          max-active: 16       # only relevant if you use pooling with Lettuce
          max-idle: 8
          min-idle: 2
          max-wait: 500ms      # fail fast rather than queue forever
      # cluster:
      #   nodes: host1:6379,host2:6379
```

Set `timeout` explicitly. A Redis command with no timeout, on a Redis that has
stalled, blocks the caller indefinitely — the cache becomes the outage.

## Always set serializers explicitly

Spring's default is `JdkSerializationRedisSerializer`, which writes opaque Java
binary. Consequences: nothing else (no CLI, no other language, no dashboard) can
read your cache, and adding a field to a class can make every existing entry
undeserialisable.

```java
@Configuration
public class RedisConfig {

    @Bean
    RedisTemplate<String, Object> redisTemplate(RedisConnectionFactory cf,
                                                ObjectMapper baseMapper) {
        // Copy the app's mapper so cache serialisation can't be changed by
        // unrelated web-layer mapper tweaks — and vice versa.
        ObjectMapper mapper = baseMapper.copy()
                .registerModule(new JavaTimeModule())
                .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);

        var template = new RedisTemplate<String, Object>();
        template.setConnectionFactory(cf);
        template.setKeySerializer(new StringRedisSerializer());
        template.setHashKeySerializer(new StringRedisSerializer());
        template.setValueSerializer(new GenericJackson2JsonRedisSerializer(mapper));
        template.setHashValueSerializer(new GenericJackson2JsonRedisSerializer(mapper));
        template.afterPropertiesSet();
        return template;
    }
}
```

`GenericJackson2JsonRedisSerializer` embeds the class name so it can round-trip
polymorphic values. That's convenient but couples cache entries to your package
names — renaming or moving a class invalidates entries. For long-lived caches
prefer `Jackson2JsonRedisSerializer<>(MyDto.class)` per type, with an explicit
versioned key prefix.

**Never enable Jackson default typing on data you don't fully control** — it's a
deserialisation gadget vector.

## Declarative caching

```java
@Configuration
@EnableCaching
public class CacheConfig {

    @Bean
    RedisCacheManager cacheManager(RedisConnectionFactory cf, ObjectMapper mapper) {
        var defaults = RedisCacheConfiguration.defaultCacheConfig()
                .entryTtl(Duration.ofMinutes(10))          // a TTL is MANDATORY
                .disableCachingNullValues()                // usually right; see below
                .prefixCacheNameWith("myservice:v1:")      // versioned: lets you
                                                           // invalidate a whole
                                                           // generation on deploy
                .serializeKeysWith(SerializationPair.fromSerializer(
                        new StringRedisSerializer()))
                .serializeValuesWith(SerializationPair.fromSerializer(
                        new GenericJackson2JsonRedisSerializer(mapper)));

        // Per-cache TTLs: reference data lives long, volatile data doesn't.
        var perCache = Map.of(
                "users",   defaults.entryTtl(Duration.ofMinutes(5)),
                "configs", defaults.entryTtl(Duration.ofHours(6)));

        return RedisCacheManager.builder(cf)
                .cacheDefaults(defaults)
                .withInitialCacheConfigurations(perCache)
                .transactionAware()      // only write cache after the TX commits
                .build();
    }
}
```

```java
@Service
public class UserService {

    @Cacheable(cacheNames = "users", key = "#id", unless = "#result == null")
    public User getUser(String id) { return repo.findById(id).orElse(null); }

    @CachePut(cacheNames = "users", key = "#user.id")
    public User update(User user) { return repo.save(user); }

    @CacheEvict(cacheNames = "users", key = "#id")
    public void delete(String id) { repo.deleteById(id); }
}
```

### The self-invocation trap

`@Cacheable` works via a proxy. Calling a cached method **from inside the same
class** bypasses the proxy entirely and the cache never applies.

```java
public User getUser(String id) { ... }          // @Cacheable

public List<User> getMany(List<String> ids) {
    return ids.stream().map(this::getUser).toList();   // NOT CACHED. this. = no proxy.
}
```

Fix by moving the cached method to another bean, or self-injecting the proxy
(`@Lazy` self-reference). The same trap applies to `@Transactional` and `@Async`.

### Other caching gotchas

- **`disableCachingNullValues()` + a miss-heavy key space = cache stampede.** If
  "not found" is common and you don't cache it, every request for a missing key
  hits the database. Either cache a sentinel/empty value with a short TTL, or add a
  negative-lookup guard.
- **`transactionAware()`** stops you caching a value that a rolled-back transaction
  never actually wrote.
- **TTL always.** A cache without expiry is a second database with no schema and no
  backups — and stale entries outlive every deploy.
- **Version your key prefix** (`myservice:v1:`). When a value's shape changes, bump
  to `v2` instead of writing a migration or flushing production.
- `@Cacheable` caches exceptions? No — it doesn't cache them, so a failing
  dependency is retried on every call. Add a breaker if that matters.

## Cache-aside, written out

The declarative annotations cover most cases; write it manually when you need
control over stampedes or partial failure.

```java
public User getUser(String id) {
    String key = "myservice:v1:user:" + id;
    try {
        User cached = (User) redis.opsForValue().get(key);
        if (cached != null) return cached;
    } catch (RuntimeException e) {
        // A cache outage must NOT become an application outage. Log and fall
        // through to the source of truth.
        log.warn("cache read failed for {}", key, e);
    }

    User fresh = repo.findById(id).orElseThrow(() -> new UserNotFound(id));

    try {
        redis.opsForValue().set(key, fresh, Duration.ofMinutes(10));
    } catch (RuntimeException e) {
        log.warn("cache write failed for {}", key, e);   // still return the value
    }
    return fresh;
}
```

**Treat the cache as optional infrastructure.** Every read and write wrapped so a
Redis failure degrades performance, not availability. This is the single most
valuable caching habit.

## Distributed locks with Redisson

Use a lock when exactly one instance may act — a scheduled job, a
non-idempotent external call, a one-shot migration.

```java
public void runExclusively(String jobName, Runnable work) {
    RLock lock = redisson.getLock("myservice:lock:" + jobName);
    boolean acquired = false;
    try {
        // waitTime: how long to wait to acquire. leaseTime: auto-release deadline.
        // A lease is ESSENTIAL — if this JVM dies holding the lock, the key must
        // still expire or the job is wedged until someone deletes it by hand.
        acquired = lock.tryLock(5, 60, TimeUnit.SECONDS);
        if (!acquired) {
            log.info("{} already running elsewhere, skipping", jobName);
            return;
        }
        work.run();
    } catch (InterruptedException e) {
        Thread.currentThread().interrupt();          // restore the flag, always
        throw new IllegalStateException("interrupted acquiring " + jobName, e);
    } finally {
        // isHeldByCurrentThread guards against unlocking a lock whose lease
        // already expired and was re-acquired by another node.
        if (acquired && lock.isHeldByCurrentThread()) lock.unlock();
    }
}
```

Honest limitations:

- **A Redis lock is not a correctness guarantee.** With replication failover you can
  get two holders (the Redlock debate). Use it to *reduce duplicate work*, not to
  protect an invariant. For real mutual exclusion use a database constraint,
  conditional update, or a fencing token.
- **Choose `leaseTime` > worst-case work duration**, or the lock expires mid-job and
  a second node starts. Redisson's watchdog (used when `leaseTime` is omitted)
  renews automatically — but then a hung JVM holds it until the watchdog stops.
- Make the guarded work **idempotent anyway**. Assume the lock will occasionally fail.

## Key design

```
myservice:v1:user:{id}            # service : schema version : type : identifier
myservice:v1:user:{id}:perms
myservice:lock:nightly-recon
```

- Prefix by service so a shared Redis stays debuggable and you can measure per-service
  memory with `--bigkeys`.
- Include a schema version to invalidate a generation without `FLUSHDB`.
- **Never `KEYS *` in production** — it's O(n) and blocks the single-threaded
  server. Use `SCAN` with a cursor.
- Watch for hot keys: one key holding a value every request needs serialises all
  traffic through one shard.

## What not to put in Redis

- **Session state you can't lose**, unless persistence is configured and you've
  tested failover. Redis default config can lose recent writes.
- **Large values.** Multi-MB entries cause latency spikes and network saturation;
  they also make `maxmemory` eviction unpredictable.
- **Anything requiring transactional consistency with your database.** There is no
  two-phase commit here — the cache will be briefly wrong. Design for that
  (short TTLs, invalidate-on-write, accept staleness explicitly).
- **A queue, if you need delivery guarantees.** Redis Streams are decent; plain
  `LPUSH`/`BRPOP` loses messages on failover. Use a real broker for durable work.

## Eviction and memory

Set `maxmemory` and an eviction policy on the server, or Redis will happily OOM the
box. For a pure cache, `allkeys-lru` (or `allkeys-lfu`) is right — it evicts
something rather than failing writes. `noeviction` (the default) turns a full cache
into write errors, which is correct for a queue/store but wrong for a cache. Alert
on `evicted_keys` and hit ratio.
