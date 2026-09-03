# Outbound HTTP in Java

## Which client

| Client | Status | Use when |
|---|---|---|
| **`RestClient`** (Spring 6.1+) | **Current default for synchronous calls** | New Spring code. Fluent API, blocking, works beautifully on virtual threads. |
| `WebClient` | Current, reactive | You genuinely need reactive streaming/backpressure, or you're in a WebFlux app. Sits *alongside* `RestClient`, not replaced by it. |
| `RestTemplate` | **DEPRECATED** in Spring Framework 7.1 / Boot 4.2; slated for **removal** in Spring 8 / Boot 5 | Existing code only, and plan the migration. Do not write new code against it. |
| `java.net.http.HttpClient` (JDK 11+) | Stable, dependency-free | Libraries, or services avoiding Spring. HTTP/2 built in. |
| Feign / Spring Cloud OpenFeign | Stable | Declarative interfaces across many endpoints. Adds a layer. |
| Apache HttpClient 5 / OkHttp | Stable | Fine-grained transport control; often the layer *under* the above. |

**With virtual threads, blocking clients are the simple correct answer.** The main
historical reason to use reactive `WebClient` — avoiding thread-per-request cost —
is largely gone. Prefer `RestClient` for new synchronous code.

## RestClient, configured properly

```java
@Configuration
public class UserClientConfig {

    @Bean
    RestClient userRestClient(RestClient.Builder builder) {
        // Timeouts live on the request factory, not the RestClient itself.
        var factory = new JdkClientHttpRequestFactory(
                HttpClient.newBuilder()
                        .connectTimeout(Duration.ofSeconds(2))      // TCP + TLS
                        .followRedirects(HttpClient.Redirect.NORMAL)
                        .build());
        factory.setReadTimeout(Duration.ofSeconds(5));               // response wait

        return builder
                .baseUrl("https://api.example.com")
                .requestFactory(factory)
                .defaultHeader(HttpHeaders.USER_AGENT, "myservice/1.0")
                .requestInterceptor(new CorrelationIdInterceptor())
                .build();
    }
}
```

`RestClient.Builder` injected from Spring Boot arrives **pre-instrumented** with
Micrometer observation (metrics + tracing) and any `RestClientCustomizer` beans.
Constructing `RestClient.create()` yourself silently loses that — always inject the
builder.

```java
@Service
public class UserClient {
    private final RestClient rest;

    UserClient(RestClient userRestClient) { this.rest = userRestClient; }

    public User getUser(String id) {
        return rest.get()
                .uri("/users/{id}", id)                  // templated: encodes the value
                .accept(MediaType.APPLICATION_JSON)
                .retrieve()
                .onStatus(HttpStatusCode::is4xxClientError, (req, res) -> {
                    if (res.getStatusCode().value() == 404) throw new UserNotFound(id);
                    throw new UpstreamBadRequest(res.getStatusCode());
                })
                .onStatus(HttpStatusCode::is5xxServerError, (req, res) -> {
                    throw new UpstreamUnavailable(res.getStatusCode());
                })
                .body(User.class);
    }
}
```

Always use `uri("/users/{id}", id)` rather than string concatenation — the template
form URL-encodes path variables and prevents injection of `../` or query separators.

Translate transport failures into **domain exceptions** at the client boundary so
callers never import `HttpStatusCode`.

## Never leave timeouts unset

An unconfigured `RestTemplate` or a raw `HttpClient` without `connectTimeout` waits
indefinitely. On platform threads, enough hung calls exhaust the pool and the
service stops serving while every health check passes. On virtual threads you won't
exhaust threads — but you'll pin connection-pool permits and pile up memory instead.

Two layers to set, always:
1. **connect timeout** — 1–3 s. If a TCP handshake takes longer, the host is down.
2. **read/response timeout** — from the dependency's real p99, not a guess.

For the JDK client, per-request duration is a request property:

```java
var request = HttpRequest.newBuilder(uri)
        .timeout(Duration.ofSeconds(5))     // total request timeout
        .GET().build();
```

## Connection pooling

Apache HttpClient 5's defaults are conservative and will throttle you:

```java
var connMgr = PoolingHttpClientConnectionManagerBuilder.create()
        .setMaxConnTotal(200)
        .setMaxConnPerRoute(100)     // DEFAULT IS 5 — the usual cause of
                                     // mystery latency under concurrency
        .setDefaultConnectionConfig(ConnectionConfig.custom()
                .setConnectTimeout(Timeout.ofSeconds(2))
                .setValidateAfterInactivity(TimeValue.ofSeconds(5))
                .build())
        .build();
```

Set `maxConnPerRoute` to your expected concurrency against that host. Add
`setValidateAfterInactivity` so a connection silently killed by an idle NLB is
revalidated rather than handed out dead.

The JDK `HttpClient` manages its own pool with no per-route knob — one more reason
to use it when you don't need the control.

### Virtual threads change pool sizing

10,000 virtual threads through a 100-connection pool means 9,900 waiting. Virtual
threads move the bottleneck to your pools; they don't remove it. Size pools to what
the *dependency* can absorb, and add an explicit `Semaphore` if you need to cap
concurrency independently.

## Resilience4j — and the decorator ordering trap

```java
// Order matters, and it's counter-intuitive. Decorators apply OUTSIDE-IN in the
// order listed, so the LAST one listed is the INNERMOST (closest to the call).
//
// Retry(CircuitBreaker(TimeLimiter(supplier)))  <-- what you almost always want
//
// Retry OUTSIDE breaker: each retry is recorded by the breaker and can trip it.
// Retry INSIDE breaker: the breaker sees one aggregate outcome per logical call
//   and retries continue even while the breaker is open — usually wrong.
var decorated = Decorators.ofSupplier(() -> userClient.getUser(id))
        .withCircuitBreaker(circuitBreaker)
        .withRetry(retry)               // listed after => wraps the breaker
        .withFallback(List.of(CallNotPermittedException.class), t -> cachedUser(id))
        .decorate();
```

Spring Boot annotation form:

```java
@Retry(name = "userService")
@CircuitBreaker(name = "userService", fallbackMethod = "getUserFallback")
public User getUser(String id) { ... }

// Fallback signature must match, plus the Throwable parameter.
private User getUserFallback(String id, Throwable t) {
    log.warn("falling back for {}", id, t);
    return cache.get(id);
}
```

### The ordering rules, precisely

**Annotation form.** The default aspect order, outermost → innermost, is:

```
Retry → CircuitBreaker → RateLimiter → TimeLimiter → Bulkhead → (your method)
```

So a retried call re-enters the breaker, rate limiter, time limiter and bulkhead on
every attempt — it does not just re-invoke the bare method. Override with properties
(**higher value = more outer**):

```properties
resilience4j.retry.retryAspectOrder=1
resilience4j.circuitbreaker.circuitBreakerAspectOrder=2
resilience4j.ratelimiter.rateLimiterAspectOrder=3
resilience4j.timelimiter.timeLimiterAspectOrder=4
resilience4j.bulkhead.bulkheadAspectOrder=5
```

**Functional `Decorators` form reads backwards.** Each `.with*()` wraps the result of
the previous one, so the **last** one added is the **outermost**:

```java
Supplier<String> decorated = Decorators.ofSupplier(this::callBackend)
        .withBulkhead(bulkhead)
        .withTimeLimiter(timeLimiter, scheduler)
        .withRateLimiter(rateLimiter)
        .withCircuitBreaker(circuitBreaker)
        .withRetry(retry)          // added last => outermost => retries everything above
        .decorate();
```

This reversal is the trap. Read the chain bottom-up to know your real nesting, and
assert the behaviour in a test rather than trusting the reading.

Two more ordering mistakes worth naming:

- **Don't put broad exceptions in a breaker's `recordExceptions`/`ignoreExceptions`.**
  An over-broad `ignoreExceptions` (e.g. `RuntimeException`) means the breaker never
  sees the failures it exists to trip on.
- **One breaker instance per downstream dependency.** Sharing one across unrelated
  calls means a single flaky dependency opens the circuit for healthy ones.

```yaml
resilience4j:
  circuitbreaker:
    instances:
      userService:
        slidingWindowType: COUNT_BASED
        slidingWindowSize: 50
        minimumNumberOfCalls: 20          # don't trip on 1-of-1
        failureRateThreshold: 50
        waitDurationInOpenState: 30s
        permittedNumberOfCallsInHalfOpenState: 3
        # 4xx means OUR request was wrong — not an unhealthy dependency
        ignoreExceptions:
          - com.example.UpstreamBadRequest
  retry:
    instances:
      userService:
        maxAttempts: 3
        waitDuration: 100ms
        enableExponentialBackoff: true
        exponentialBackoffMultiplier: 2
        enableRandomizedWait: true        # JITTER — do not omit
        retryExceptions:
          - java.io.IOException
          - java.util.concurrent.TimeoutException
```

Retry rules are language-independent: idempotent operations only, transient
failures only, capped attempts, jitter mandatory, exactly one retrying layer, honour
`Retry-After`.

## Interceptors for cross-cutting concerns

```java
public class CorrelationIdInterceptor implements ClientHttpRequestInterceptor {
    @Override
    public ClientHttpResponse intercept(HttpRequest req, byte[] body,
                                        ClientHttpRequestExecution ex) throws IOException {
        String cid = MDC.get("correlationId");
        if (cid != null) req.getHeaders().set("X-Correlation-Id", cid);
        return ex.execute(req, body);
    }
}
```

Propagating a correlation ID is what makes a distributed trace readable. If you use
Micrometer Tracing / OTel, `traceparent` propagation is automatic — but a
human-readable correlation ID in logs is still worth having.

## Checklist

- [ ] `RestClient` for new synchronous code; `RestClient.Builder` **injected**, not `create()`
- [ ] Connect timeout (1–3 s) AND read timeout (from measured p99) set
- [ ] `maxConnPerRoute` raised from the default (5 in Apache HC5)
- [ ] `validateAfterInactivity` set if behind an idle-killing load balancer
- [ ] URI templates (`{id}`) instead of string concatenation
- [ ] Non-2xx mapped to domain exceptions at the client boundary
- [ ] Retry outside breaker; jitter on; 4xx excluded from breaker failures
- [ ] Breaker has `minimumNumberOfCalls` so it can't trip on one bad call
- [ ] Fallback defined for the open-breaker path
- [ ] Correlation ID / trace context propagated
