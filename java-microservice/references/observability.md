# Observability

Three pillars, one correlation key. Logs tell you what happened, metrics tell you
how much/how often, traces tell you where the time went across services — and a
request ID (or trace ID) stitched through all three is what lets you jump from a
metric spike to the exact logs and spans that explain it.

## 1. Structured logging — JSON to stdout

Log to **stdout**, never to a file. The container runtime (Docker log driver,
Kubernetes' kubelet, your log shipper's sidecar) already collects stdout/stderr and
ships it off-box. A `FileAppender` adds disk I/O and rotation you now own; a
network appender (sending straight to your log backend from inside the request
path) is worse — it's a dependency that can block or throw, and a slow log
backend should never slow down or fail a request.

Emit JSON in production so your log backend can index fields without a fragile
regex parser. Use `logstash-logback-encoder` (widely supported) or an ECS-layout
encoder if your backend is Elastic-flavored. Keep plain text for local dev — nobody
wants to read JSON in a terminal.

```xml
<!-- logback-spring.xml -->
<configuration>
    <springProfile name="local,test">
        <appender name="CONSOLE" class="ch.qos.logback.core.ConsoleAppender">
            <encoder>
                <pattern>%d{HH:mm:ss.SSS} %-5level [%thread] %logger{36} - %msg [%X{requestId}]%n</pattern>
            </encoder>
        </appender>
        <root level="INFO">
            <appender-ref ref="CONSOLE"/>
        </root>
    </springProfile>

    <springProfile name="!local &amp; !test">
        <appender name="JSON" class="ch.qos.logback.core.ConsoleAppender">
            <encoder class="net.logstash.logback.encoder.LogstashEncoder">
                <includeMdcKeyName>requestId</includeMdcKeyName>
                <includeMdcKeyName>traceId</includeMdcKeyName>
                <includeMdcKeyName>spanId</includeMdcKeyName>
                <customFields>{"service":"myservice"}</customFields>
            </encoder>
        </appender>
        <root level="INFO">
            <appender-ref ref="JSON"/>
        </root>
    </springProfile>
</configuration>
```

Two profile branches, one config file, no environment-specific jar. The
`includeMdcKeyName` allowlist is deliberate — dumping the *entire* MDC into every
log line is how an accidental `MDC.put("password", ...)` upstream becomes a
permanent, indexed, searchable leak.

## 2. MDC correlation IDs

A filter (or `HandlerInterceptor`) that reads an inbound `X-Request-Id`, generates
one if absent, puts it in MDC for the duration of the request, and echoes it back
in the response header so the caller can quote it in a support ticket:

```java
@Component
public class RequestIdFilter extends OncePerRequestFilter {

    private static final String HEADER = "X-Request-Id";

    @Override
    protected void doFilterInternal(HttpServletRequest req, HttpServletResponse res,
                                     FilterChain chain) throws ServletException, IOException {
        String requestId = req.getHeader(HEADER);
        if (requestId == null || requestId.isBlank()) {
            requestId = UUID.randomUUID().toString();
        }
        MDC.put("requestId", requestId);
        res.setHeader(HEADER, requestId);
        try {
            chain.doFilter(req, res);
        } finally {
            MDC.clear();   // NOT optional — see below
        }
    }
}
```

**Why the `finally` is load-bearing.** `MDC` is backed by a `ThreadLocal`. On a
platform-thread pool (the classic Tomcat/servlet model), threads are reused across
unrelated requests. If you don't clear MDC, a value set for request A is still
sitting in that thread when it picks up request B — every log line B emits before
it overwrites the key gets stamped with A's request ID. This is a real, maddening
class of bug: logs that correlate an error with the *wrong* request, discovered
only under load when the thread pool is actually recycling threads fast enough for
it to matter. `MDC.clear()` (or scoped `MDC.remove(key)` per key you set) in a
`finally` is the fix, and it must run even when the chain throws.

**Virtual threads change the blast radius, not the correctness rule.** A virtual
thread is (usually) one-shot per request — it's not pooled and reused the way a
platform thread is, so the leak-into-next-request scenario mostly doesn't arise.
But "mostly doesn't arise" is not "clear becomes optional": carrier-thread pinning,
thread-pool-backed executors you still use elsewhere, and simple defensive
correctness all argue for clearing regardless of execution model.

**The modern alternative is `ScopedValue`** (finalized in Java 25, JEP 506).
Unlike `ThreadLocal`, a `ScopedValue` is bound for the dynamic extent of a
`ScopedValue.where(...).run(...)` call and is automatically and immutably unbound
when that call returns — there is no `clear()` to forget, and no mutable `set()`
to leak across contexts. It's also cheaper on virtual threads because it doesn't
need per-thread mutable storage.

```java
private static final ScopedValue<String> REQUEST_ID = ScopedValue.newInstance();

ScopedValue.where(REQUEST_ID, requestId).run(() -> {
    chain.doFilter(req, res);   // REQUEST_ID.get() is valid anywhere in this call tree
});
// unbound automatically here — no finally needed
```

Logback's MDC integration doesn't read `ScopedValue` natively yet, so most services
still bridge: read `REQUEST_ID.get()` and `MDC.put` it at the point you need it in
a log pattern. Track this as one to simplify as ecosystem support catches up.

## 3. What never goes in a log

Passwords, access/refresh tokens, API keys, full card numbers, CVVs, OTPs, and any
raw PII (name+DOB+address combinations, government IDs) must never reach a log
line — logs are typically retained far longer than the data-retention policy
allows for that data, and they're readable by a much wider audience (anyone with
log-backend access) than the systems that legitimately hold the data.

Redact at the source, not by hoping nobody logs the wrong field:

```java
public record CardPaymentRequest(String cardNumber, String cvv, BigDecimal amount) {
    @Override
    public String toString() {
        return "CardPaymentRequest[cardNumber=%s, cvv=***, amount=%s]"
                .formatted(mask(cardNumber), amount);
    }

    private static String mask(String pan) {
        return pan.length() > 4 ? "*".repeat(pan.length() - 4) + pan.substring(pan.length() - 4) : "****";
    }
}
```

Overriding `toString()` on the DTO means redaction travels with the object — it's
correct wherever the object is logged, including a stray `log.debug(request)`
someone adds later. For JSON logging, a Logback/Jackson converter that regexes
common patterns (`"password"\s*:\s*"[^"]*"`) as a second line of defense catches
what raw string concatenation misses, but treat it as a backstop, not the primary
control. Never log full request/response bodies for auth or payment endpoints —
log a summary (user ID, outcome, latency) instead.

## 4. Log levels, used consistently

| Level | Means | Pages someone | Example |
|---|---|---|---|
| **ERROR** | The operation failed and a human likely needs to act — data loss risk, unhandled exception, dependency permanently unavailable. | Yes (if alerted on) | Payment provider returned 500 after all retries exhausted. |
| **WARN** | Degraded but handled — a fallback fired, a retry succeeded on attempt 2, a deprecated API path was hit. | No, but reviewed | Circuit breaker opened for `userService`. |
| **INFO** | Business-significant events at normal operation — request completed, order placed, job started/finished. | No | `Order 4471 placed, total=42.00`. |
| **DEBUG** | Diagnostic detail useful when actively investigating — intermediate values, branch taken. Off in production by default; enabled per-logger when needed. | No | `Cache miss for key=user:441, fetching from DB`. |

**Log where you handle, return where you don't.** If a method catches an
exception, decides what to do about it, and recovers — that's where you log,
because that's the one place with full context on both the failure and the
resolution. If a method catches an exception only to rethrow it (wrapped or not),
do not log there too:

```java
// ANTI-PATTERN: log-and-rethrow
try {
    orderRepository.save(order);
} catch (DataAccessException e) {
    log.error("Failed to save order", e);   // logged here...
    throw new OrderPersistenceException(e); // ...and rethrown
}
// ...caller catches OrderPersistenceException, logs it AGAIN...
// ...global @ExceptionHandler catches it, logs it a THIRD time.
```

Three log lines, one failure, three different stack traces pointing at three
different layers — and an on-call engineer now has to figure out whether that's
one incident or three. Pick exactly one layer to log at: usually the boundary that
either fully handles the error (retries it, falls back, returns a clean response)
or the outermost handler that turns it into an HTTP response. Everything in
between should just propagate.

## 5. Micrometer metrics

Inject `MeterRegistry`, don't construct one — Spring Boot wires the registry to
your configured backend (Prometheus, CloudWatch, whatever) and Actuator endpoint.

```java
@Service
public class OrderService {
    private final Counter ordersPlaced;
    private final Timer orderProcessingTime;

    OrderService(MeterRegistry registry) {
        this.ordersPlaced = Counter.builder("orders.placed")
                .description("Total orders placed")
                .tag("channel", "web")
                .register(registry);
        this.orderProcessingTime = Timer.builder("orders.processing.time")
                .publishPercentileHistogram()   // needed for Prometheus histogram_quantile()
                .register(registry);
    }

    public void placeOrder(Order order) {
        orderProcessingTime.record(() -> {
            // ... business logic ...
            ordersPlaced.increment();
        });
    }
}
```

Four instrument types cover almost everything:

| Type | Use for | Example |
|---|---|---|
| `Counter` | Monotonic totals | requests served, orders placed, errors thrown |
| `Timer` | Duration + count of an operation | request latency, DB call duration |
| `Gauge` | A value that goes up and down | queue depth, active connections, cache size |
| `DistributionSummary` | Distribution of a non-time value | payload size, batch size, items per order |

`@Timed` (from `micrometer-core`, needs `@EnableAspectJAutoProxy` or Spring Boot's
auto-config) times a whole method declaratively — useful for a quick per-endpoint
timer without threading a `Timer` through the class, but for anything you need
fine control over (custom tags per outcome, conditional recording) use the
programmatic API above.

### Cardinality is the whole game

Every unique combination of tag values is a **separate time series** stored,
indexed, and paid for by your metrics backend. A counter with a `userId` tag on a
service with a million users doesn't create one metric — it creates a million.
Multiply by a few tags each with high cardinality and you can generate a
cardinality explosion that makes the backend slow to query, expensive to store,
or (Prometheus especially) simply falls over from too many active series.

```java
// ANTI-PATTERN — cardinality explosion
timer.tags("userId", userId, "path", request.getRequestURI()).record(...);
//          ^^^^^^ unbounded: one series per user, forever
//                              ^^^^ unbounded: /orders/4471 and /orders/4472
//                                    are different tag values, not the same route

// CORRECT — bounded tag values
timer.tags("route", "/orders/{id}", "outcome", "success").record(...);
//          ^^^^^ the route TEMPLATE, not the resolved path — bounded by your
//                 number of endpoints, not your number of orders
```

Rule of thumb: a tag's value set should be small and known in advance (HTTP
method, status class, route template, region, outcome). Never tag with a user ID,
request ID, session ID, raw path, email, or any other value with effectively
unbounded cardinality. Spring's `@HttpExchange`/MVC auto-instrumentation already
uses the route template for you — don't override it with the raw URI.

### The RED method — the four metrics every service needs

- **Rate** — requests per second, by route and method.
- **Errors** — error rate, by route and status class (`4xx`/`5xx`), as a ratio of
  rate so you can alert on percentage, not raw count.
- **Duration** — latency distribution (p50/p95/p99), by route.

Spring Boot's `WebMvcMetricsFilter`/`ObservationFilter` gives you all three for
free on every endpoint via `http.server.requests` — verify it's enabled before
building custom timers that duplicate it. Add **business metrics** on top: orders
placed, payments failed by reason code (bounded reason enum, not raw exception
message), signups completed. RED tells you the service is healthy; business
metrics tell you the service is doing its job.

```yaml
management:
  metrics:
    distribution:
      percentiles-histogram:
        http.server.requests: true   # exposes _bucket series for histogram_quantile()
      percentiles:
        http.server.requests: 0.5, 0.95, 0.99   # client-side percentiles, cheap but not aggregatable
```

Client-side percentiles (`percentiles`) are computed per-instance and can't be
correctly averaged across instances. Histogram buckets (`percentiles-histogram`)
cost more series but aggregate correctly across every instance behind a
`histogram_quantile()` in Prometheus. Use histograms for anything you'll alert on
fleet-wide.

## 6. Actuator — health, split correctly

```yaml
management:
  endpoints:
    web:
      exposure:
        include: health, info, prometheus   # explicit allowlist — NOT "*"
  endpoint:
    health:
      probes:
        enabled: true   # activates /actuator/health/liveness and /readiness groups
  server:
    port: 9001   # management port SEPARATE from the app port
```

**Exposing every Actuator endpoint (`include: "*"`) on the public app port is a
mistake.** `/actuator/env`, `/actuator/heapdump`, `/actuator/threaddump` leak
config (including secret-adjacent values), memory contents, and thread state to
anyone who can reach the port. Put management endpoints on a separate port bound
only to internal/cluster traffic, and allowlist exactly the endpoints you use.

**Liveness and readiness answer different questions, and conflating them causes
outages:**

- **Liveness** (`/actuator/health/liveness`): "is this JVM process fundamentally
  broken and should Kubernetes kill and restart it?" This must check *only*
  process-internal state (deadlock detection, JVM health) — **never a downstream
  dependency**. If liveness checks the database and the database has a two-minute
  blip, every pod fails liveness simultaneously, Kubernetes restarts the entire
  fleet, and a transient dependency blip becomes a total self-inflicted outage —
  restarting has done nothing to fix a database that was never the pod's fault.
- **Readiness** (`/actuator/health/readiness`): "can this pod currently serve
  traffic?" This is exactly where dependency checks belong — if the DB or a
  critical downstream is unreachable, fail readiness so the load balancer stops
  routing to this pod, without killing the process. The pod comes back into
  rotation automatically once the dependency recovers.

```java
@Component
public class DownstreamHealthIndicator implements HealthIndicator {

    private final RestClient client;

    @Override
    public Health health() {
        try {
            client.get().uri("/health").retrieve().toBodilessEntity();
            return Health.up().build();
        } catch (Exception e) {
            // Detail here, not in liveness/readiness contract — just up/down for the probe.
            return Health.down(e).withDetail("dependency", "payment-gateway").build();
        }
    }
}
```

Register a custom `HealthIndicator` under the `readiness` group explicitly (via
`management.endpoint.health.group.readiness.include=readinessState,downstream`)
— by default custom indicators land in the aggregate `/actuator/health`, not
automatically in the readiness group.

## 7. Tracing

**OTel Java agent** (`-javaagent:opentelemetry-javaagent.jar`) instruments Spring
MVC, JDBC, HTTP clients, and dozens of other libraries with **zero code change** —
attach it at the JVM command line and spans appear. Use it as the default; it's
the lowest-effort path to full request-tree visibility.

**Micrometer Observation / manual spans** are for the gaps the agent doesn't
reach — a custom async boundary, a business operation you want as its own named
span regardless of the underlying library:

```java
@Service
public class PricingService {
    private final ObservationRegistry registry;

    public Price calculate(Order order) {
        return Observation.createNotStarted("pricing.calculate", registry)
                .lowCardinalityKeyValue("currency", order.currency())
                .highCardinalityKeyValue("orderId", order.id())   // fine on a SPAN — not a metric
                .observe(() -> doCalculate(order));
    }
}
```

**Span attributes tolerate high cardinality that metric tags cannot** — a span is
one record per request, not an aggregated time series, so `orderId` as a span
attribute costs nothing extra per unique value. The one rule that doesn't relax:
still no secrets in span attributes. They're stored and queried just like logs.

**Propagation** happens via the W3C `traceparent` header, carrying trace ID, span
ID, and sampling decision across service boundaries — both the OTel agent and
Micrometer Tracing handle this automatically for instrumented HTTP clients/servers.
If you hand-roll an HTTP call with a bare socket or an uninstrumented client, the
chain breaks there and that hop becomes an unlinked, orphaned trace.

**Sampling.** 100% sampling (`AlwaysOn`) is honest but expensive at real
traffic — every request generates and ships spans, which costs money at the
tracing backend and a small but nonzero amount of latency per request.
`ParentBased(TraceIdRatioBased(0.1))` is the standard shape: if a parent already
decided to sample, honor that decision (keeps a trace complete end-to-end); if
this service is the entry point, sample at a ratio (10% here). Tune the ratio to
what your trace backend and budget can sustain, and consider always sampling
error traces regardless of ratio (tail-based sampling, if your backend supports
it) so failures aren't the thing you dropped.

**Correlate logs and traces** by putting `traceId`/`spanId` into MDC (Micrometer
Tracing does this automatically when `micrometer-tracing-bridge-otel` is on the
classpath) so a log line and a span for the same request share a key you can
pivot on in your log/trace backend UI.

## 8. JFR and diagnostics

**Always-on JFR, bounded.** Java Flight Recorder overhead is low enough (typically
1-2%) to run continuously in production, and a bounded recording means the data
for an incident already exists by the time you're asked to look — no "turn it on
and wait for it to reproduce."

```
-XX:StartFlightRecording=disk=true,maxsize=250m,maxage=24h,filename=/var/log/app/recording.jfr
```

`jcmd` for on-demand control without a restart:

```bash
# Dump the current in-memory buffer to disk right now, without stopping the recording.
jcmd <pid> JFR.dump filename=/var/log/app/incident.jfr

# Start a short, more detailed profile for active investigation.
jcmd <pid> JFR.start name=investigate settings=profile duration=120s filename=/var/log/app/investigate.jfr

# Heap dump — expensive (pauses the JVM briefly, and the file is often gigabytes) but
# definitive for a suspected leak.
jcmd <pid> GC.heap_dump /var/log/app/heap.hprof
```

Read a recording without a GUI via `jfr view`:

```bash
jfr view hot-methods recording.jfr
jfr view gc-configuration recording.jfr
jfr print --events jdk.ExecutionSample recording.jfr
```

**Virtual-thread-specific events** matter once you're on Project Loom in
production. `jdk.VirtualThreadPinned` fires when a virtual thread is pinned to
its carrier — usually from a `synchronized` block or native frame — and pinning
under load is exactly how you silently lose the scalability virtual threads were
supposed to give you. Enable it explicitly (it's off by default in the default
recording template) and check for it whenever virtual-thread throughput looks
worse than expected:

```
-XX:StartFlightRecording=settings=profile,jdk.VirtualThreadPinned#enabled=true,jdk.VirtualThreadPinned#stackTrace=true
```

## 9. Log the resolved config at startup

One INFO line at boot, after config binding and validation, listing the resolved
values that matter for this run — profile, key pool sizes, feature flags,
upstream base URLs — with secrets redacted:

```java
@Component
public class StartupConfigLogger {
    private static final Logger log = LoggerFactory.getLogger(StartupConfigLogger.class);

    @EventListener(ApplicationReadyEvent.class)
    void logStartupConfig(MyServiceProperties props, Environment env) {
        log.info("Started myservice: profile={} dbPoolSize={} featureFlagX={} upstreamBaseUrl={}",
                String.join(",", env.getActiveProfiles()),
                props.dbPoolSize(),
                props.featureFlagX(),
                props.upstream().baseUrl());
        // Never: props.upstream().apiKey() — redact anything secret-shaped, even here.
    }
}
```

This line answers "what was this pod actually running?" in every incident —
which profile, which flag values, which pool size — without needing to SSH in or
cross-reference a deploy manifest. It's cheap to add and is consistently the
first thing worth grepping for when a specific pod behaves differently from its
siblings.

## Checklist

- [ ] JSON logs to stdout in non-local profiles; plain text for local dev
- [ ] No `FileAppender` or network appender in the request path
- [ ] Request-ID filter sets MDC, echoes response header, clears MDC in `finally`
- [ ] `ScopedValue` considered for new code as the leak-proof alternative to MDC
- [ ] No passwords/tokens/PANs/OTPs/PII in any log line — redacted at the DTO, not by convention
- [ ] Log levels used consistently; no log-and-rethrow producing duplicate failure records
- [ ] `MeterRegistry` injected, not constructed; RED metrics + business metrics present
- [ ] No unbounded tags (user ID, request ID, raw path) on any metric — route templates only
- [ ] Percentile histograms enabled for anything alerted on fleet-wide
- [ ] Liveness checks process health only; readiness checks dependencies
- [ ] Management port separated from app port; endpoint exposure explicitly allowlisted
- [ ] Tracing propagation verified across every outbound call, including hand-rolled ones
- [ ] Sampling ratio set deliberately, not left at 100% or default
- [ ] Trace/span IDs present in MDC for log-trace correlation
- [ ] Always-on bounded JFR recording running in production
- [ ] Startup log line with resolved config, secrets redacted
