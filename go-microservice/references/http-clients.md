# Outbound HTTP in Go

The single most common production incident in a microservice fleet is a slow
dependency exhausting the caller's resources. Everything here exists to prevent
that.

## Never use `http.DefaultClient`

`http.Get`, `http.Post`, and `http.DefaultClient` have **no timeout**. A hung
server means a goroutine (and a connection) blocked forever. Under load, that's
resource exhaustion and cascading failure.

```go
// WRONG — no timeout, shared global, default transport tuning
resp, err := http.Get(url)

// RIGHT — one configured client, constructed once, reused everywhere
func NewHTTPClient() *http.Client {
    return &http.Client{
        Timeout: 10 * time.Second,   // whole-request ceiling: dial+TLS+headers+body
        Transport: &http.Transport{
            // Connection pool. Defaults are hostile for a service that talks to
            // one or two backends: MaxIdleConnsPerHost defaults to 2, so under
            // concurrency you constantly dial new connections.
            MaxIdleConns:        100,
            MaxIdleConnsPerHost: 100,   // set == your expected concurrency per host
            MaxConnsPerHost:     200,   // hard cap; 0 = unlimited
            IdleConnTimeout:     90 * time.Second,

            DialContext: (&net.Dialer{
                Timeout:   2 * time.Second,   // TCP connect
                KeepAlive: 30 * time.Second,
            }).DialContext,

            TLSHandshakeTimeout:   2 * time.Second,
            ExpectContinueTimeout: 1 * time.Second,
            ResponseHeaderTimeout: 5 * time.Second,  // time to FIRST byte of response
            ForceAttemptHTTP2:     true,
        },
    }
}
```

### The two-layer timeout model

`http.Client.Timeout` is a blunt ceiling on the entire exchange, including reading
the body. Per-request deadlines belong in the **context**, because they compose
with the caller's remaining budget:

```go
func (c *Client) GetUser(ctx context.Context, id string) (*User, error) {
    // Inherits the caller's deadline; shortens it if ours is tighter.
    ctx, cancel := context.WithTimeout(ctx, 2*time.Second)
    defer cancel()

    req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.base+"/users/"+id, nil)
    if err != nil {
        return nil, fmt.Errorf("build request: %w", err)
    }
    req.Header.Set("Accept", "application/json")

    resp, err := c.hc.Do(req)
    if err != nil {
        return nil, fmt.Errorf("get user %s: %w", id, err)   // includes ctx deadline errors
    }
    defer resp.Body.Close()        // ALWAYS. Leaking bodies leaks connections.

    if resp.StatusCode != http.StatusOK {
        // Read a bounded amount so the connection can be reused, and so a
        // misbehaving server can't feed you a gigabyte of error text.
        b, _ := io.ReadAll(io.LimitReader(resp.Body, 4<<10))
        return nil, fmt.Errorf("get user %s: status %d: %s", id, resp.StatusCode, b)
    }

    var u User
    if err := json.NewDecoder(resp.Body).Decode(&u); err != nil {
        return nil, fmt.Errorf("decode user: %w", err)
    }
    return &u, nil
}
```

### Two rules people get wrong

**1. Always close the body, even on error paths where you don't read it.** An
unclosed body holds its connection out of the pool permanently. `bodyclose` and
`sqlclosecheck` in golangci-lint catch this class of bug — enable them.

**2. Drain before closing if you want connection reuse.** `net/http` only returns
a connection to the pool if the body was read to EOF. If you abandon a body early,
the connection is closed instead. When you deliberately discard:

```go
_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 64<<10))
resp.Body.Close()
```

For large or untrusted responses, prefer closing early over draining megabytes —
the connection is cheaper to re-establish than the bandwidth is to waste.

## Timeout budgets

Give each hop a budget smaller than its caller's, so the innermost call fails
before the outermost gives up. Otherwise the client times out while your service
keeps working on a response nobody will read.

```
inbound request deadline      3000ms   (set by server middleware)
  ├─ dependency A               800ms
  ├─ dependency B               800ms   (concurrent with A via errgroup)
  └─ DB query                   500ms
     ── slack for serialisation/GC ~900ms
```

Propagate the deadline downstream. If you're calling a service you own, pass the
remaining budget as a header (or rely on gRPC deadline propagation, which does it
for you) so the callee can give up early rather than doing doomed work.

## Retries

Retry only what is **safe** and **worth** retrying.

Safe: idempotent methods (GET, HEAD, PUT, DELETE) and anything you've made
idempotent with a key. **POST is not safe to retry** unless the endpoint accepts
an idempotency key — a retried payment is a real incident.

Worth it: transient failures — connection refused/reset, timeouts, 429, 502, 503,
504. **Not** 400/401/403/404/422; retrying a validation error just wastes budget.

```go
// Exponential backoff with FULL JITTER. Jitter is not optional: without it,
// every client that failed at the same instant retries at the same instant,
// and you have a synchronised thundering herd against a service that is
// already unwell.
func withRetry(ctx context.Context, attempts int, f func(context.Context) error) error {
    const base = 100 * time.Millisecond
    var err error
    for i := range attempts {
        if err = f(ctx); err == nil {
            return nil
        }
        if !retryable(err) || i == attempts-1 {
            return err
        }
        backoff := min(base<<i, 2*time.Second)
        sleep := time.Duration(rand.Int64N(int64(backoff)))   // full jitter
        select {
        case <-time.After(sleep):
        case <-ctx.Done():
            return errors.Join(err, ctx.Err())   // respect the caller's deadline
        }
    }
    return err
}
```

Rules:
- **Cap total attempts** (3 is usually right) and **respect the context deadline** —
  a retry loop that outlives its budget is a bug.
- **Honour `Retry-After`** on 429/503 when present.
- **Never retry in more than one layer.** Retries multiply: 3 at the client × 3 in
  a proxy × 3 in a sidecar = 27 requests from one call. Pick one layer and disable
  the rest.
- Add a `Idempotency-Key` header for POSTs you must retry, and make the server
  deduplicate on it.

## Circuit breaker

Retries help with blips. They make sustained outages worse. A breaker stops
sending traffic to a dependency that is clearly down, failing fast instead of
queueing.

```go
// sony/gobreaker — small, dependency-free, well understood
var cb = gobreaker.NewCircuitBreaker(gobreaker.Settings{
    Name:        "user-service",
    MaxRequests: 3,                // probes allowed in half-open
    Interval:    60 * time.Second, // window for clearing counts when closed
    Timeout:     30 * time.Second, // open → half-open after this
    ReadyToTrip: func(c gobreaker.Counts) bool {
        // Require volume before tripping: 1 failure out of 1 request is noise.
        return c.Requests >= 20 &&
            float64(c.TotalFailures)/float64(c.Requests) >= 0.5
    },
    OnStateChange: func(name string, from, to gobreaker.State) {
        slog.Warn("breaker state change", "name", name, "from", from.String(), "to", to.String())
    },
})

body, err := cb.Execute(func() (any, error) { return c.GetUser(ctx, id) })
```

Notes:
- **One breaker per dependency**, not one per process. A shared breaker lets a
  broken dependency block healthy ones.
- Don't count 4xx client errors as breaker failures — they mean *your request* was
  wrong, not that the dependency is unhealthy.
- Always log/emit state changes. A breaker that opens silently is an outage you
  find out about from users.
- Have a fallback: cached value, degraded response, or a clean 503. An open breaker
  should produce a *deliberate* answer.

## Rate limiting outbound calls

When a dependency publishes a quota, respect it client-side rather than discovering
it via 429s.

```go
// golang.org/x/time/rate — token bucket
lim := rate.NewLimiter(rate.Limit(100), 20)   // 100 rps sustained, burst 20

if err := lim.Wait(ctx); err != nil {   // blocks, or returns on ctx cancellation
    return err
}
```

Combine with a `semaphore` (or `errgroup.SetLimit`) to bound *concurrency* as well
as *rate* — they're different failure modes.

## Instrumentation

Wrap the transport once so every call is traced and measured:

```go
import "go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"

client := &http.Client{
    Timeout:   10 * time.Second,
    Transport: otelhttp.NewTransport(baseTransport),   // spans + context propagation
}
```

A `RoundTripper` is the right seam for cross-cutting concerns — auth headers,
retries, logging, metrics — because it sees every request including redirects:

```go
type authTransport struct {
    base  http.RoundTripper
    token func() string
}

func (t *authTransport) RoundTrip(r *http.Request) (*http.Response, error) {
    // Clone: never mutate the caller's request. It may be retried or reused.
    r2 := r.Clone(r.Context())
    r2.Header.Set("Authorization", "Bearer "+t.token())
    return t.base.RoundTrip(r2)
}
```

Metrics worth emitting per dependency: request count by status class, duration
histogram, in-flight gauge, and breaker state. Those four answer "is my dependency
slow, broken, or overwhelmed?"

## Client-construction checklist

- [ ] Client constructed **once** and injected — never per request (per-request
      clients defeat connection pooling entirely)
- [ ] `Timeout` set on the client
- [ ] `MaxIdleConnsPerHost` raised from the default of 2
- [ ] Per-call `context.WithTimeout` from the caller's budget
- [ ] `defer resp.Body.Close()` on every path
- [ ] Non-2xx handled explicitly with a bounded body read
- [ ] Retries only for idempotent + transient, capped, jittered, single-layer
- [ ] Breaker per dependency with volume threshold and logged state changes
- [ ] Transport wrapped for tracing/metrics
