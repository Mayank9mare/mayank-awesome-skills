---
name: java-microservice
description: Use when building, scaffolding, or reviewing a Java/JVM backend service or REST API — choosing between Spring Boot, Micronaut, Quarkus, Helidon, Vert.x, Javalin or Ktor; Gradle/Maven multi-module setup; JPA/Hibernate and HikariCP tuning; Redis caching with Lettuce/Jedis/Redisson; SQS/Kafka listeners; virtual threads and Loom; GC and JVM container flags; RestClient/WebClient; Resilience4j; Micrometer and OpenTelemetry; Testcontainers. Also for "start a Java service", "migrate to Spring Boot 4", "upgrade to Java 25", "enable virtual threads", "JVM is getting OOMKilled", annotation questions.
---

# Java Microservice

## Overview

A Java service is six things: **config**, an **HTTP surface**, **state** (DB + cache),
**async work**, **outbound calls**, and **operability**. On the JVM the framework
supplies most of the plumbing, so the work is choosing the framework, then tuning the
runtime — the JVM's defaults were designed for long-lived servers on dedicated hardware,
not for containers.

Verified against **Java 25 LTS** (GA 2025-09-16) and **Spring Boot 4.1.0** as of 2026-08.
Library versions throughout come from Maven Central, not from blog posts. Note **no
Spring Boot release is LTS** — every minor gets ~12 months of OSS support on a 6-month
cadence, so plan an annual minor upgrade.

## When to Use

- Starting a new JVM service, or adding an endpoint/listener to an existing one
- Choosing a framework, persistence layer, cache client, or resilience library
- Reviewing Java service code for production-readiness
- Migrating: Boot 2.7 → 3.x/4.x, Java 17 → 21/25, `javax` → `jakarta`
- Enabling virtual threads, or diagnosing pinning
- Diagnosing: OOMKills, long GC pauses, pool exhaustion, slow startup, thread starvation
- Containerising a JVM service or tuning it for Kubernetes

**Not for:** Android, desktop, or non-service JVM work.

## Step 0: Choose the framework

| If… | Use |
|---|---|
| Default, no strong reason otherwise | **Spring Boot 4.1** — ecosystem, docs and hiring pool usually win |
| Kubernetes with tight memory/cold-start budgets; want the best native footprint | **Quarkus 3.38** |
| AWS Lambda / serverless specifically; want least runtime magic | **Micronaut 5.x** (compile-time DI) |
| Virtual-thread-first blocking model as a deliberate design choice | **Helidon 4 SE** (Níma) |
| Infrastructure software — proxy, gateway, broker | **Vert.x** |
| Tiny API; conventions would be pure overhead | **Javalin** |
| Kotlin end-to-end, server + client on one idiom | **Ktor** |

Startup/memory differences are real but rarely decisive for a long-running service —
startup is a one-time cost. Choose on ecosystem and constraints, not benchmark tables.
Full comparison, Boot 4 migration breaks, and benchmark caveats in
references/frameworks.md.

## Quick Reference

| Task | Reach for | Detail |
|---|---|---|
| Framework | Spring Boot 4.1 (default) | references/frameworks.md |
| gRPC | **`spring-boot-grpc-server/-client/-test`** (first-class in Boot 4.1) | references/frameworks.md |
| Build | Gradle (Kotlin DSL + version catalogs) or Maven + BOM | references/frameworks.md |
| Outbound HTTP | **`RestClient`** (`RestTemplate` is deprecated) | references/http-clients.md |
| Resilience | Resilience4j — mind the decorator order | references/http-clients.md |
| Persistence | Spring Data JPA / Hibernate; HikariCP tuned | references/persistence.md |
| Migrations | Flyway or Liquibase | references/persistence.md |
| Cache | Redis via **Lettuce** (not Jedis); Redisson for locks | references/caching-redis.md |
| Queues | Spring Cloud AWS **4.x** `@SqsListener`, Spring Kafka | references/messaging.md |
| Config | `@ConfigurationProperties` records, validated | references/packaging-deploy.md |
| Virtual threads | `spring.threads.virtual.enabled=true` | references/language-runtime.md |
| Logging | Logback → JSON on stdout, MDC correlation ID | references/observability.md |
| Metrics/tracing | Micrometer + Actuator; OTel agent | references/observability.md |
| Tests | JUnit 5, AssertJ, **`@MockitoBean`**, Testcontainers | references/testing.md |
| Container | `MaxRAMPercentage`, not `-Xmx` | references/packaging-deploy.md |

## Bootstrap a new service

Two-module Gradle split is a good default — it makes the domain layer's independence
structural rather than aspirational:

```
myservice/
  settings.gradle          # include ':myservice-domain', ':myservice-service'
  build.gradle             # cross-project config only
  domain/                  # entities, value objects, ports. No web/framework deps.
  service/                 # controllers, config, adapters, main class
  Dockerfile
```

```groovy
// settings.gradle
rootProject.name = 'myservice'
include(':myservice-domain')
include(':myservice-service')
project(":myservice-domain").projectDir  = file('domain')
project(":myservice-service").projectDir = file('service')
```

1. Java **25**, Spring Boot **4.0.x**, dependencies via the BOM/platform (one version
   source — never mix plugin and starter versions).
2. `@ConfigurationProperties` **records** with `jakarta.validation` annotations, so bad
   config fails at startup rather than in a request.
3. **Constructor injection** everywhere. No `@Autowired` fields.
4. `@ControllerAdvice` with one error envelope and an error-code enum.
5. Actuator: `/actuator/health/liveness` and `/health/readiness` (they are different —
   see observability.md).
6. HikariCP + explicit timeouts; `maxLifetime` **below** the DB/LB idle timeout.
7. `spring.threads.virtual.enabled=true` — but first replace any fixed pool that was
   acting as a concurrency limiter with an explicit `Semaphore`.
8. `-XX:MaxRAMPercentage=75` (never `-Xmx` in a container).

## The non-negotiables

1. **Never `-Xmx` in a container.** Use `-XX:MaxRAMPercentage=75`. A fixed heap ignores
   the pod's actual limit.
2. **Every outbound call has a connect *and* read timeout.** An unconfigured
   `RestTemplate`/`HttpClient` waits forever, exhausts the pool, and takes the service
   down while health checks pass.
3. **Constructor injection, final fields.** Field `@Autowired` hides cyclic
   dependencies, defeats immutability, and needs reflection to test.
4. **Config validated at startup.** `@ConfigurationProperties` + `@Validated`, not 83
   scattered `@Value`s.
5. **Name the transaction boundary.** `@Transactional` at the service method that must
   be atomic — not sprinkled, not absent. Beware self-invocation: an internal call
   bypasses the proxy and the annotation does nothing.
6. **Liveness ≠ readiness.** Liveness must not check dependencies, or one DB blip
   restarts every pod at once and turns a blip into an outage.
7. **`maxLifetime` < the shortest idle timeout** in front of the DB, or you hand out
   dead connections.
8. **Idempotent consumers**, `@Valid @Payload` on messages, explicit acknowledgement
   mode, DLQ configured.
9. **Structured JSON logs on stdout with an MDC correlation ID.** Never secrets.
10. **`-XX:+ExitOnOutOfMemoryError` + `HeapDumpOnOutOfMemoryError`.** A limping
    post-OOM JVM serves errors while looking alive; better to die and be restarted.

## Reference Map

| File | Read when |
|---|---|
| references/language-runtime.md | Java 25 features, virtual threads/pinning, GC choice, container flags, JFR |
| references/frameworks.md | Framework choice, Boot 4 migration, Jakarta/MicroProfile, build tooling |
| references/persistence.md | JPA/Hibernate, HikariCP sizing, N+1, transactions, migrations |
| references/caching-redis.md | Lettuce vs Jedis, serializers, `@Cacheable` traps, Redisson locks |
| references/messaging.md | SQS/Kafka listeners, acknowledgement modes, idempotency, DLQ |
| references/http-clients.md | RestClient, timeouts, pooling, Resilience4j ordering |
| references/observability.md | Logback JSON, MDC, Micrometer, Actuator, OTel |
| references/testing.md | JUnit 5, slices, `@MockitoBean`, Testcontainers, WireMock |
| references/packaging-deploy.md | JVM flags, Dockerfile, CDS/AOT, graceful shutdown, Kubernetes |

## Common Mistakes

Several of these are drawn from real production services — they are the mistakes that
actually get made, not hypotheticals.

| Mistake | Why it hurts | Fix |
|---|---|---|
| `-Xmx` in a container | Ignores the cgroup limit | `-XX:MaxRAMPercentage=75` |
| `@Autowired` on fields (seen 33× in one service) | Hides cycles, unmockable without reflection, mutable | Constructor injection, `final` fields |
| Dozens of scattered `@Value` (83 in one service) | Untyped, unvalidated, untestable config | `@ConfigurationProperties` records |
| `@Transactional` almost nowhere (2 uses in a JPA service) | Multi-write operations aren't atomic | Name the boundary at the service method |
| Calling a `@Transactional`/`@Cacheable`/`@Async` method from the same class | Proxy bypassed — **annotation silently does nothing** | Move to another bean, or self-inject the proxy |
| `@Data` on a JPA entity | `equals`/`hashCode` over all fields → `LazyInitializationException`, broken hashing pre-persist | Explicit `equals`/`hashCode` on the ID only |
| Java 21/25 but no `spring.threads.virtual.enabled` | Paying for platform threads after doing the migration | Enable it — after replacing pool-as-limiter with `Semaphore` |
| Swapping in virtual threads without resizing pools | 10k threads queueing on 10 connections | Virtual threads *move* the bottleneck to your pools |
| Default Redis serializer | Opaque JDK-binary blobs; break on class change | Set `GenericJackson2JsonRedisSerializer` explicitly |
| `@Cacheable` with no TTL | A second database with no schema and no backups | TTL always; version the key prefix |
| Cache failure propagating | Cache outage becomes an application outage | Wrap reads/writes; log and fall through |
| Retry *inside* the circuit breaker | Retries continue while the breaker is open | Retry **outside** breaker; verify the order |
| No `minimumNumberOfCalls` on a breaker | Trips on 1-of-1 failure | Require volume (e.g. 20) before tripping |
| `@MockBean` on Boot 4 | **Removed** — fails to compile | `@MockitoBean` |
| Mixing Boot plugin/starter versions (2.6.5 + 2.7.17 + 3.2.2 seen in one build) | Undefined behaviour at runtime | One version via the BOM/platform |
| Liveness probe that checks the database | One DB blip restarts every pod | Liveness = process-local only |
| `@SneakyThrows` | Hides checked exceptions from callers | Handle or declare |
| Two APM/tracing stacks both setting a global tracer | Last registered silently wins; other's spans vanish | One tracing stack per process |
