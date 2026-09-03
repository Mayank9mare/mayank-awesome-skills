# Observability in Go

Three signals plus two endpoints. Logs tell you *what happened*, metrics tell you
*how often and how bad*, traces tell you *where the time went*. Health endpoints
tell the orchestrator whether to send you traffic.

## Logging: `log/slog`

`log/slog` (1.21+) is in the standard library and is the default answer. Reach for
`zap` or `zerolog` only if you've measured allocation in logging as a real
bottleneck (they're zero-alloc; `slog` is merely cheap).

```go
func newLogger(env string) *slog.Logger {
    opts := &slog.HandlerOptions{
        Level:     slog.LevelInfo,
        AddSource: true,           // file:line — worth the small cost
    }
    var h slog.Handler
    if env == "local" {
        h = slog.NewTextHandler(os.Stdout, opts)     // human-readable
    } else {
        h = slog.NewJSONHandler(os.Stdout, opts)     // machine-parseable
    }
    // Attributes attached here appear on EVERY line — how you identify the
    // emitter in an aggregated log store.
    return slog.New(h).With(
        slog.String("service", "myservice"),
        slog.String("version", version),
    )
}
```

**Log to stdout, as JSON, in production.** Not to a file — the container runtime
collects stdout. Not to a network sink from inside the process — that's a
dependency that can block your request path.

### Structured means key-value, not a formatted sentence

```go
// WRONG: unqueryable. You cannot alert on a substring, and cardinality is hidden.
log.Printf("user %s failed payment %s: %v", userID, paymentID, err)

// RIGHT: every field is a queryable dimension.
logger.ErrorContext(ctx, "payment failed",
    slog.String("user_id", userID),
    slog.String("payment_id", paymentID),
    slog.String("error", err.Error()),
)
```

Use the `...Context` variants (`InfoContext`, `ErrorContext`) so a context-aware
handler can pull trace IDs automatically.

### Correlation IDs via a context-aware handler

The point of a correlation ID is joining every line from one request. Threading a
logger through every function signature is tedious; put the ID in the context and
teach the handler to read it.

```go
type ctxHandler struct{ slog.Handler }

func (h ctxHandler) Handle(ctx context.Context, r slog.Record) error {
    if id, ok := RequestIDFrom(ctx); ok {
        r.AddAttrs(slog.String("request_id", id))
    }
    // If you use OTel, attach trace/span IDs so logs and traces join up.
    if sc := trace.SpanContextFromContext(ctx); sc.IsValid() {
        r.AddAttrs(
            slog.String("trace_id", sc.TraceID().String()),
            slog.String("span_id", sc.SpanID().String()),
        )
    }
    return h.Handler.Handle(ctx, r)
}

logger := slog.New(ctxHandler{slog.NewJSONHandler(os.Stdout, opts)})
```

### Middleware that generates the ID

```go
func RequestID(next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        // Trust an inbound ID from your own edge/mesh; generate otherwise.
        id := r.Header.Get("X-Request-Id")
        if id == "" {
            id = uuid.NewString()
        }
        ctx := WithRequestID(r.Context(), id)
        w.Header().Set("X-Request-Id", id)   // echo it so clients can report it
        next.ServeHTTP(w, r.WithContext(ctx))
    })
}
```

### What never goes in a log

Passwords, tokens, API keys, full card numbers, OTPs, government IDs, raw request
bodies of auth endpoints. Redact at the logging boundary — don't rely on everyone
remembering. A `LogValue()` method makes a type self-redacting:

```go
type Card struct{ Number, CVV string }

// slog calls LogValue() instead of serialising the struct.
func (c Card) LogValue() slog.Value {
    return slog.StringValue("Card(****" + last4(c.Number) + ")")
}
```

### Levels, used consistently

| Level | Meaning | Paged? |
|---|---|---|
| `Error` | This request/job failed and a human may need to act | Maybe (via rate) |
| `Warn` | Degraded but handled — retry succeeded, fallback used, breaker opened | No, but trend it |
| `Info` | Lifecycle + one line per significant business event | No |
| `Debug` | Developer detail, off in production | No |

Don't log an error *and* return it — the caller will log it too, and you get the
same failure three times at three layers. **Log where you handle, return where you
don't.**

## Metrics: Prometheus

```go
var (
    httpRequests = promauto.NewCounterVec(prometheus.CounterOpts{
        Name: "http_requests_total",
        Help: "Total HTTP requests.",
    }, []string{"method", "route", "status"})   // route = TEMPLATE, not raw path

    httpDuration = promauto.NewHistogramVec(prometheus.HistogramOpts{
        Name: "http_request_duration_seconds",
        Help: "HTTP request latency.",
        // Explicit buckets matched to your SLO. The defaults top out at 10s
        // which is useless for a service with a 200ms target.
        Buckets: []float64{.005, .01, .025, .05, .1, .25, .5, 1, 2.5, 5},
    }, []string{"method", "route"})

    inFlight = promauto.NewGauge(prometheus.GaugeOpts{
        Name: "http_requests_in_flight",
        Help: "Requests currently being served.",
    })
)
```

### Cardinality is the whole game

Every distinct label-value combination is a separate time series. Put a user ID or a
raw URL path in a label and you will take down your metrics backend.

```go
// CATASTROPHIC: unbounded label values
httpRequests.WithLabelValues(r.Method, r.URL.Path, status).Inc()   // /users/12345

// CORRECT: the route template — bounded by the number of routes you wrote
httpRequests.WithLabelValues(r.Method, "/users/{id}", status).Inc()
```

Rules: labels must be **bounded and low-cardinality** (method, route template,
status class, dependency name). Never user IDs, request IDs, emails, timestamps,
raw paths, or error messages. Keep total series per metric in the hundreds.

### The four every service should expose

1. **Request rate** by route + status — traffic and error ratio.
2. **Latency histogram** by route — p50/p95/p99 via `histogram_quantile`.
3. **In-flight gauge** — saturation.
4. **Dependency call** rate + latency + errors, by dependency name.

That's the RED method (Rate, Errors, Duration) and it answers most incidents.
Add business metrics (orders placed, payments declined by reason) — those catch
failures that look healthy at the HTTP layer.

```go
func Metrics(next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        inFlight.Inc()
        defer inFlight.Dec()

        rec := &statusRecorder{ResponseWriter: w, status: http.StatusOK}
        start := time.Now()
        next.ServeHTTP(rec, r)

        // Go 1.22+: the matched pattern, already a template. No manual mapping.
        route := r.Pattern
        if route == "" {
            route = "unmatched"     // never fall back to r.URL.Path
        }
        httpDuration.WithLabelValues(r.Method, route).Observe(time.Since(start).Seconds())
        httpRequests.WithLabelValues(r.Method, route, strconv.Itoa(rec.status)).Inc()
    })
}

type statusRecorder struct {
    http.ResponseWriter
    status      int
    wroteHeader bool
}

func (r *statusRecorder) WriteHeader(c int) {
    if r.wroteHeader {
        return                  // guard: double WriteHeader panics
    }
    r.wroteHeader = true
    r.status = c
    r.ResponseWriter.WriteHeader(c)
}

// Preserve optional interfaces the wrapped writer may implement, or you break
// streaming and hijacking (SSE, websockets) silently.
func (r *statusRecorder) Flush() {
    if f, ok := r.ResponseWriter.(http.Flusher); ok {
        f.Flush()
    }
}
func (r *statusRecorder) Unwrap() http.ResponseWriter { return r.ResponseWriter }
```

Wrapping `http.ResponseWriter` is the classic source of subtle breakage — if you
don't forward `Flush`/`Hijack`/`ReadFrom`, streaming endpoints stop working. Expose
`Unwrap()` so `http.ResponseController` (1.20+) can find the real writer.

Expose on a **separate port** so `/metrics` isn't publicly reachable:

```go
go func() {
    mux := http.NewServeMux()
    mux.Handle("/metrics", promhttp.Handler())
    mux.HandleFunc("/debug/pprof/", pprof.Index)      // admin port only!
    _ = http.ListenAndServe(":9090", mux)
}()
```

## Tracing: OpenTelemetry

```go
func initTracer(ctx context.Context) (func(context.Context) error, error) {
    exp, err := otlptracegrpc.New(ctx)     // endpoint from OTEL_EXPORTER_OTLP_ENDPOINT
    if err != nil {
        return nil, err
    }
    tp := sdktrace.NewTracerProvider(
        sdktrace.WithBatcher(exp),          // batch: never export inline
        sdktrace.WithResource(resource.NewWithAttributes(
            semconv.SchemaURL,
            semconv.ServiceName("myservice"),
            semconv.ServiceVersion(version),
        )),
        // Sample: 100% of traces at scale is expensive and rarely needed.
        // ParentBased respects an upstream decision so a trace isn't half-sampled.
        sdktrace.WithSampler(sdktrace.ParentBased(sdktrace.TraceIDRatioBased(0.1))),
    )
    otel.SetTracerProvider(tp)
    otel.SetTextMapPropagator(propagation.NewCompositeTextMapPropagator(
        propagation.TraceContext{},         // W3C traceparent
        propagation.Baggage{},
    ))
    return tp.Shutdown, nil     // MUST be called on shutdown or you lose the tail
}
```

Instrument the edges and let context propagate:

```go
handler = otelhttp.NewHandler(mux, "myservice")                  // inbound
client := &http.Client{Transport: otelhttp.NewTransport(nil)}    // outbound
```

Manual spans for meaningful internal work only — one span per function is noise:

```go
ctx, span := tracer.Start(ctx, "settle-payment",
    trace.WithAttributes(attribute.String("payment.method", method)))
defer span.End()

if err != nil {
    span.RecordError(err)
    span.SetStatus(codes.Error, "settlement failed")   // makes it findable
}
```

Attributes on spans can be higher-cardinality than metric labels (they're not time
series) — a payment ID on a span is fine and useful. Still never put secrets there.

## Health endpoints — liveness ≠ readiness

Conflating these causes cascading restarts.

```go
// LIVENESS: "is this process functioning?" Must NOT check dependencies.
// If it checks the DB and the DB blips, Kubernetes restarts every pod at once,
// turning a dependency blip into a full outage.
mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
    w.WriteHeader(http.StatusOK)
    _, _ = w.Write([]byte("ok"))
})

// READINESS: "should I receive traffic right now?" Checks what you cannot serve
// without, with a short timeout.
mux.HandleFunc("GET /readyz", func(w http.ResponseWriter, r *http.Request) {
    ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
    defer cancel()

    if shuttingDown.Load() {
        http.Error(w, "shutting down", http.StatusServiceUnavailable)
        return
    }
    if err := db.PingContext(ctx); err != nil {
        http.Error(w, "db unavailable", http.StatusServiceUnavailable)
        return
    }
    w.WriteHeader(http.StatusOK)
})
```

- Liveness: process-local only. Fails ⇒ restart me.
- Readiness: essential dependencies, short timeout. Fails ⇒ stop routing to me.
- **Optional dependencies must not fail readiness.** If the cache is down but you
  can still serve from the database, you are ready. (Disabling a health check
  altogether, however, hides real outages — reflect reality, just weight it right.)
- Flip readiness to failing **before** shutdown begins, so load balancers drain you
  before connections close.

## Profiling

`net/http/pprof` on the **admin port only** — it exposes goroutine stacks and can
be used to DoS you.

```sh
go tool pprof http://localhost:9090/debug/pprof/profile?seconds=30   # CPU
go tool pprof http://localhost:9090/debug/pprof/heap                 # live heap
go tool pprof http://localhost:9090/debug/pprof/allocs               # all allocs
curl localhost:9090/debug/pprof/goroutine?debug=2                    # all stacks
go tool trace <(curl -s localhost:9090/debug/pprof/trace?seconds=5)  # scheduler
```

`goroutine?debug=2` is the fastest way to answer "why is it stuck" — you get every
goroutine's stack, and a leak or deadlock is usually visible immediately.

For always-on production profiling use continuous profiling (Pyroscope, Parca) or
the 1.25 `runtime/trace` **Flight Recorder**, which keeps a rolling in-memory trace
you snapshot when something goes wrong.

## Startup log line

Log resolved configuration once at boot — with secrets redacted. It answers "what
was this pod actually running?" during every incident.

```go
logger.Info("starting",
    slog.String("version", version),
    slog.String("commit", commit),
    slog.Int("gomaxprocs", runtime.GOMAXPROCS(0)),
    slog.String("gomemlimit", os.Getenv("GOMEMLIMIT")),
    slog.String("addr", cfg.Addr),
    slog.Duration("db_timeout", cfg.DBTimeout),
)
```
