# Go routers, RPC & the library landscape

Verified 2026-08. Tags: **[stable]** / **[experimental]** / **[unmaintained]**.
Versions come from **proxy.golang.org** — registry facts, not blog claims. Anything that
could not be confirmed says so in place rather than being guessed.

## Routers

Versions below are from **proxy.golang.org as of 2026-08-01** — registry facts, not
blog claims. Check `go list -m -u <module>` for anything newer.

| Name | Version (released) | `net/http` compatible? | Perf | Middleware ecosystem | Choose when |
|---|---|---|---|---|---|
| **stdlib `net/http` + `ServeMux`** | ships with Go 1.26 | **yes — it is the standard** | high | any `func(http.Handler) http.Handler` | **Default for new services.** No dependency, no lock-in. |
| **chi** | **v5.3.1** (2026-07) | yes, idiomatic | high | large, all stdlib-shaped | You want groups/sub-routers without a framework's opinions. |
| **gin** | **v1.12.0** (2026-02) | **no** — custom `gin.Context` | high | largest, but gin-specific | Batteries-included binding/validation/rendering, and you accept the non-stdlib signature. |
| **echo** | **v4.15.4** (2026-06) | **no** — custom `echo.Context` | high | broad, echo-specific | Same niche as gin, different API taste; built-in autocert. |
| **fiber** | **v3.4.0** (2026-07) | **NO — fasthttp, not net/http** | very high in microbenchmarks | fiber-only | Raw throughput on a narrow service, accepting ecosystem loss. |
| **gorilla/mux** | **v1.8.1 — last release 2023-10** | yes | moderate (regex routing) | any stdlib | Legacy codebases only. See the maintenance note below. |
| **httprouter** | v1.3.0 (2019, dormant) | yes | high (radix tree) | none of its own | Rarely a first choice now. |

All three of chi, gin, echo and fiber shipped releases within the last six months, so
"is it maintained?" is not a differentiator between them — choose on handler signature
and ecosystem compatibility instead.

**The 2026 framing:** Go 1.22's method + wildcard routing closed most of the gap that
justified third-party routers. What remains differentiating is *ergonomics*
(binding/validation helpers) or *raw throughput* — not routing capability.

### stdlib ServeMux (1.22+)

```go
mux := http.NewServeMux()
mux.HandleFunc("GET /items/{id}", func(w http.ResponseWriter, r *http.Request) {
    id := r.PathValue("id")
    ...
})
```

Pattern syntax:
- `"GET /items/{id}"` — optional method prefix; omit it to match any method.
- `{id}` — single-segment wildcard, read with `r.PathValue("id")`.
- `{path...}` — trailing multi-segment wildcard (catch-alls, static files, proxying).
- `{$}` — anchors an exact match: `"/items/{$}"` matches `/items/` only.
- **Precedence is by specificity, not registration order.** A literal beats a wildcard
  at the same position; the more specific pattern wins. So there is no
  ordering/shadowing footgun — registration order is irrelevant to matching.

Middleware needs no framework:

```go
type Middleware func(http.Handler) http.Handler

func Chain(h http.Handler, mws ...Middleware) http.Handler {
    for i := len(mws) - 1; i >= 0; i-- {   // reverse: first listed = outermost
        h = mws[i](h)
    }
    return h
}

handler := Chain(mux, RequestID, Logging, Recover, Metrics)
```

### `http.Server` timeouts — an unconfigured server is a bug

| Field | Start with | Why it exists |
|---|---|---|
| `ReadHeaderTimeout` | 3–5 s | Bounds **header** reading specifically. Set this even if `ReadTimeout` is set — it stops slow-header attacks without penalising legitimately slow body uploads. If both are unset, Go applies **no timeout at all**. |
| `ReadTimeout` | 5–15 s | Caps total request read (headers + body). Without it a client can trickle bytes forever — slowloris. |
| `WriteTimeout` | 10–30 s | Bounds end-of-read to end-of-write. Protects against slow-reading clients. Size generously or you truncate large/streaming responses. |
| `IdleTimeout` | 60–120 s | Bounds idle keep-alive connections. Without it, idle-but-open connections exhaust file descriptors. |
| `MaxHeaderBytes` | 1 MB default usually fine | Caps header size against memory-exhaustion abuse. |

`&http.Server{Handler: mux}` with no timeouts is a **popular-but-wrong pattern**. At
absolute minimum set `ReadHeaderTimeout`.

### chi

Fully stdlib-shaped: middleware is `func(http.Handler) http.Handler`, handlers are
`http.HandlerFunc`. Sub-routers via `r.Route(...)`, mounting via `r.Mount(...)`, plus a
`middleware` sub-package that is itself just stdlib middleware. Nothing chi-specific
leaks into handler code — which is exactly why adopting *or dropping* chi is cheap.

### gin / echo

Both centre on a custom context (`gin.Context`, `echo.Context`) bundling
request/response/params/KV store, with built-in binding + `go-playground/validator`
tags (`binding:"required"`).

**The ergonomic cost is real:** handlers are `func(c *gin.Context)`, not
`func(w http.ResponseWriter, r *http.Request)`, so stdlib `http.Handler` middleware —
including much OTel instrumentation and many auth libraries — needs an adapter shim.
Both still run on `net/http` underneath, so only the handler signature is affected,
not the transport.

### fiber — say this part out loud

**Fiber is built on `fasthttp`, not `net/http`.** That's a different transport
implementation, not a different API over the same one.

- Handlers are `func(c *fiber.Ctx) error`. There is no `http.Handler` in the path.
- **The entire net/http middleware ecosystem does not apply** — including most
  OpenTelemetry instrumentation (built against `http.Handler`/`http.RoundTripper`) and
  many OAuth2/JWT middlewares.
- fasthttp is **HTTP/1.1-only** (no HTTP/2). Some older sources claim otherwise; the
  weight of technical evidence says no HTTP/2. Flagged rather than asserted.
- **A correctness hazard**: fasthttp pools and reuses request/response objects. Holding
  a `fiber.Ctx` (or the underlying request) past the handler's return — e.g. passing it
  into a goroutine — can read data mutated by a *later* request. Copy what you need out.
- Fiber ships an `Adaptor` package to bridge net/http handlers. Its existence *is* the
  evidence of incompatibility.

The cost compounds: every observability/auth library needs a fiber-specific fork or a
shim you write. For a fleet standardising on OTel, that's recurring, not one-time.

### gorilla/mux

Archived by its original Google maintainers **Dec 9 2022**, then **revived** by
volunteer maintainers mid-2023; unarchived, **v1.8.1** released.

**The revival produced no further releases.** v1.8.1 dates from **2023-10-18** — nearly
three years with no tagged release as of 2026-08 (per proxy.golang.org). Read that as
"stable and quiet" rather than "actively developed": no CVE response cadence has been
demonstrated, and no new features are arriving.

Verdict: fine to leave in an existing codebase; **do not adopt it fresh**. Everything
people reached for gorilla/mux to get — named path parameters, method-based routing —
is now in the stdlib `ServeMux`, with no dependency and no maintenance question.

## Full frameworks & codegen

Bigger commitments than a router. Weigh lock-in against the niche.

- **Huma** — OpenAPI/JSON-Schema-first, RFC 7807 errors, reflection precomputed at
  startup. Sits *on top of* chi/gin/echo/stdlib rather than replacing them → **low
  lock-in**; leaving costs you the generated OpenAPI/validation glue, not your handlers.
- **Goa** — design-first Go DSL generating HTTP + gRPC transport, client SDKs and docs.
  **Higher lock-in**: the DSL becomes the source of truth.
- **encore.dev** — "infrastructure from code": provisions DBs/queues from annotations,
  built-in tracing and service discovery. **Highest lock-in** — as much a platform as a
  framework.
- **go-zero** — HTTP *or* gRPC per service (deliberately not hybrid), `.api` DSL +
  codegen, built-in discovery/load-balancing/circuit-breaking/adaptive shedding.
  **Moderate–high lock-in.**
- **Kratos** — HTTP+gRPC hybrid from one service definition; batteries-included
  (logging, config, metrics). **Moderate lock-in.**
- **go-micro** — pluggable transport/broker/registry microservice framework. Historically
  popular, and its ownership/hosting has moved more than once; **check current
  maintenance before adopting.** Most of what it provided (discovery, load balancing) is
  now handled by the platform layer — a service mesh or Kubernetes — rather than in-process.
- **Buffalo** — Rails-inspired full-stack web framework (scaffolding, asset pipeline,
  ORM). A different niche from everything else here: monolithic web apps, not APIs.

Reach for this category only when codegen saves more than it costs. For one API
surface, Huma or Goa are the low-lock-in options; go-zero/Kratos/encore justify
themselves at "dozens of services" scale.

## gRPC & RPC

### grpc-go

Actively maintained, imported by 270k+ projects, released as recently as **Jul 30 2026**
(pkg.go.dev/google.golang.org/grpc).

- **Interceptors**: `grpc.ChainUnaryInterceptor(...)` / `ChainStreamInterceptor(...)`.
  First listed is outermost, last is closest to the handler — same onion model as HTTP
  middleware.
- **Deadlines propagate automatically** through `context.Context` across the call chain.
  Always derive downstream calls from the incoming RPC context, never
  `context.Background()`.
- **Health checking** (`grpc.health.v1`): `health.NewServer()` +
  `grpc_health_v1.RegisterHealthServer(...)`. The API now includes a `List` method
  alongside `Check`. Kubernetes 1.24+ supports gRPC health probes natively — which
  matters because a TCP port check passes on a "zombie pod" whose logic has deadlocked
  but whose socket is still open.
- **Reflection** (`google.golang.org/grpc/reflection`) lets `grpcurl` and Postman
  introspect services without local `.proto` files. Register it alongside health.
- **Keepalive vs health checking** — different layers: keepalive is *connection*-level
  (HTTP/2 PING), health is *service*-level. A connection can be alive while the service
  is degraded, which is why you run both.
  **Production pitfall**: aggressive `MaxConnectionAge` (often set to force DNS
  re-resolution) kills connections mid-RPC. Fix by raising `MaxConnectionAgeGrace` so
  in-flight RPCs drain. Nasty to diagnose — the error appears on the *client*, the cause
  is a *server* setting.

### buf

- `buf lint` — style/consistency rules on `.proto` before you're committed to a wire
  format.
- `buf generate` — declarative codegen from `buf.gen.yaml`, replacing ad-hoc `protoc`.
- `buf breaking` — diffs against a git ref or the registry and **fails CI on
  wire-incompatible changes**. This is the main defence against silently breaking
  clients.
- **buf.build registry** — a schema registry, so consumers don't vendor `.proto` by hand.
- **protovalidate** — successor to the legacy `protoc-gen-validate`. Rules are **CEL**
  expressions in field options, evaluated at **runtime** — no stale generated validators.

Toolchain versions (2026-08): **buf CLI v1.72.0**, **`google.golang.org/protobuf`
v1.36.11**, **`protoc-gen-go-grpc` v1.6.2**, **`protovalidate` v1.2.0** — note
protovalidate is past 1.0, so it's a stable API, not the experimental successor it was.

```yaml
# buf.gen.yaml — v2 config. Prefer remote plugins so every developer and CI runner
# generates with the SAME plugin version; `local:` uses whatever happens to be on
# that machine's PATH, which is how two engineers get different generated code.
version: v2
plugins:
  - remote: buf.build/protocolbuffers/go:v1.36.11
    out: gen/go
    opt: paths=source_relative
  - remote: buf.build/grpc/go:v1.6.2
    out: gen/go
    opt: paths=source_relative
```

```sh
buf lint                      # style rules before the wire format is set in stone
buf breaking --against '.git#branch=main'    # CI gate: fail on wire-incompatible change
buf generate
```

With protovalidate you don't generate a validator at all — rules are CEL expressions in
field options, evaluated at runtime by the `protovalidate` library, so there is no
`protoc-gen-validate` plugin entry and no stale generated validators to drift.

### ConnectRPC vs grpc-gateway

**ConnectRPC** serves gRPC, gRPC-Web and its own Connect protocol from one server,
generated from the same `.proto`:

- Works natively over **HTTP/1.1** (raw gRPC needs HTTP/2) — so it runs behind older
  load balancers and some serverless platforms without translation.
- **Browser support with no proxy.** Raw gRPC can't be called from a browser (trailers/
  framing), so classic gRPC-Web needed an Envoy-style translating proxy. Connect speaks
  gRPC-Web natively and removes that hop.
- Handlers **are `http.Handler`s**, so stdlib middleware composes normally.

**grpc-gateway** takes the opposite approach: generates a reverse proxy translating
REST/JSON into gRPC calls against your existing gRPC server — an extra component to run.

For new services wanting browser + HTTP/1.1 support with least operational surface:
ConnectRPC. For adding a REST facade to an existing gRPC-only service without touching
it: grpc-gateway.

**gqlgen** — **v0.17.94** (2026-07), actively released. The schema-first GraphQL standard
for Go: write SDL, it generates type-safe resolver interfaces, you implement them. Note
it is still on a `v0.x` line despite years of production use — the API is stable in
practice, but read release notes before minor bumps.

## Library cheat sheet

### SQL

- **`database/sql`** — stdlib driver-agnostic interface; pooling and prepared statements
  built in. Everything below wraps it or replaces it.
- **pgx v5** — **the recommended Postgres driver.** *Native mode* (`pgxpool.Pool`) uses
  the binary wire protocol and exposes Postgres-only features (LISTEN/NOTIFY, COPY,
  custom types). *stdlib mode* (`pgx/v5/stdlib`) implements `database/sql/driver` so
  libraries expecting `*sql.DB` still work. Prefer over **lib/pq**
  **[unmaintained]** — frozen, contributions not merged.
- **sqlx** — thin `database/sql` extension: `StructScan`, named params. Good middle
  ground: less boilerplate, no ORM, no codegen.
- **sqlc** — **SQL-first codegen.** Write `schema.sql` + `query.sql` with
  `-- name: GetUser :one` annotations, run `sqlc generate`, call fully-typed generated
  functions. No runtime reflection, no query DSL. SQL stays reviewable and
  `EXPLAIN`-able while call sites stay typed. Very popular for good reason.
- **GORM** — most popular full ORM. Real pitfalls: runtime reflection degrades
  performance at scale; convention magic (auto-pluralised tables, implicit soft-delete
  via `DeletedAt`, preloading behaviour) produces surprising **N+1** patterns unless
  associations are explicitly preloaded; `AutoMigrate` is convenient in dev and risky
  unreviewed against production.
- **ent** — schema-as-Go-code generating a compile-time-safe query builder and graph
  traversal. Middle ground between GORM's reflection and sqlc's raw SQL.
- **squirrel** — query *builder* for genuinely dynamic SQL (optional WHERE clauses) that
  sqlc's static model doesn't fit.
- **bun** — **v1.2.18** (2026-02). A lighter ORM/query-builder positioned against GORM
  with less reflection-heavy internals. Actively maintained; smaller community than GORM.

Verified versions (proxy.golang.org, 2026-08): **pgx v5.10.0**, **sqlc** and **ent**
active, **bun v1.2.18**.

**Pool tuning:**

```go
db.SetMaxOpenConns(25)                  // total (in-use + idle)
db.SetMaxIdleConns(25)                  // keep warm; ≈ MaxOpenConns avoids churn
db.SetConnMaxLifetime(30 * time.Minute) // recycle even if healthy
db.SetConnMaxIdleTime(5 * time.Minute)  // trim the pool after a spike
```

Size `MaxOpenConns` as *(database's max_connections ÷ number of replicas)*, with
headroom — not arbitrarily high. Each server-side connection costs real memory, and many
replicas with big pools will exhaust the database. `ConnMaxLifetime` smooths
load-balancer/pooler rebalancing and stops all connections going stale at once.

### Migrations

**golang-migrate** (most widely used, plain up/down SQL) · **goose** (SQL *and*
Go-function migrations — useful for data migrations needing app logic) · **atlas**
(declarative desired-state, computes the diff — Terraform's model for schemas) ·
**tern** (pgx-native, Postgres-only). No 2026 head-to-head verified; positioning only.

### Redis

- **rueidis** **[stable]** — RESP3 client under the official `redis/` org. Client-side
  caching via `DoCache()` with an explicit client TTL (it sends `PTTL` so it can't cache
  beyond the server key's life), and **auto-pipelining** of concurrent commands for free
  throughput. Requires Redis ≥6.0 with RESP3 + `CLIENT TRACKING` — **this breaks on
  managed providers without `CLIENT TRACKING`** (GCP Memorystore, some ElastiCache
  configs), surfacing as `ErrNoCache`. Ships `rueidiscompat` for go-redis-shaped
  migration.
- **go-redis/v9** **[stable]** — **v9.21.0** (2026-06). RESP3 via `Protocol: 3`, larger
  community, newer opt-in client-side caching that has historically lagged rueidis's.
- **redigo** — **v1.9.3** (2025-10). Still maintained, just quiet; superseded for new
  work by the two above.

Verified (2026-08): **rueidis v1.0.76** (2026-06), **go-redis v9.21.0** (2026-06).
Both actively released — pick on features, not maintenance risk.
- **redsync** — Redlock across independent instances. **Why naive `SETNX` is unsafe:**
  no protection against clock drift, GC pauses, or partitions letting a holder believe
  it still owns an expired lock. Redlock itself is **contested** (Kleppmann's critique).
  No Redis lock substitutes for a DB-backed lock with fencing tokens when correctness
  under partition matters.

### Kafka

- **franz-go** **[stable]** — **v1.21.5** (2026-07). Feature-complete, fastest in
  benchmarks, pure Go, current KIP support (cooperative-sticky, KIP-881 rack awareness).
  **Recommended for new pure-Go projects.**
- **IBM/sarama** **[stable]** — most widely deployed historically, pure Go, lags newer
  KIPs.
- **segmentio/kafka-go** — **v0.4.51** (2026-04). Simpler API, also lags KIPs.
- **confluent-kafka-go** — CGO wrapper over librdkafka: maximum feature parity, but
  **CGO_ENABLED=0 is not an option**, which collides with scratch/distroless images.

### Job queues

- **River** **[stable]** — Postgres-backed, `SELECT … FOR UPDATE SKIP LOCKED`, pgx
  binary protocol, `LISTEN`/`NOTIFY` for low-latency wakeups, `COPY FROM` for bulk
  insert. **The key property: jobs are inserted in the same transaction as your data**,
  so a committed transaction can never lose its job — an outbox for free, and the main
  differentiator from Redis-backed queues. Non-Go producers can enqueue (jobs are just
  rows). Author-reported ~10k jobs/s (self-reported).
- **Asynq** **[stable]** — **v0.26.0** (2026-02). Redis-backed, established, with a web
  UI. Trade-off: no Postgres dependency, but you lose transactional enqueue unless you
  build an outbox yourself. Release cadence is slower than River's.
- **RabbitMQ** — **`amqp091-go` v1.13.0** (2026-07), **actively maintained** and the
  official successor to the unmaintained `streadway/amqp`. Use it, not streadway.
- **NATS** (+JetStream for persistence), **machinery** — lighter pub/sub and a
  multi-backend task library respectively.

Release activity (2026-08): **River v0.42.0** shipped 2026-07-31 — very active.
**Asynq v0.26.0** 2026-02. That gap is worth knowing if you care about responsiveness
to issues.

### AWS SDK Go v2

**v1.43.3** (2026-07-31) — actively released. Shape:

```go
cfg, err := config.LoadDefaultConfig(ctx,          // env → shared config → IMDS chain
    config.WithRegion(region),
    config.WithRetryMaxAttempts(3),
)
client := sqs.NewFromConfig(cfg)
```

SQS long polling sets `WaitTimeSeconds` (max 20) on `ReceiveMessageInput` to cut empty
polls and latency. The retryer is pluggable via the `aws.Retryer` interface —
`retry.NewStandard()` or **adaptive** mode, which adds client-side rate limiting when it
sees throttling. Prefer adaptive for high-throughput consumers.

### Config

| Library | Version (2026-08) | Verdict |
|---|---|---|
| **koanf** | **v2.3.5** (2026-05) | **Recommended.** Composable multi-source (env, file, flags), light dependency tree. |
| `caarlos0/env` | active | Simplest tag-based env→struct binding. Good default for 12-factor services. |
| viper | active | Most features (live reload, many formats), heaviest deps, global-state-leaning. |
| `kelseyhightower/envconfig` | **v1.4.0 — 2019-05** | **Effectively dormant** (7 years, no release). Widely copied in tutorials. Prefer koanf or caarlos0/env for new code. |
| cleanenv | active | env + YAML/JSON with validation tags. |

Regardless of library: **validate config at boot and fail fast**. Discovering a missing
value deep in a request path at 3am is the failure mode you're preventing.

### Dependency injection

- **Manual wiring** — explicit constructors assembled in `main.go`. **The idiomatic
  default.** No reflection, no codegen, and the whole graph is readable as straight-line
  code.
- **google/wire** **[stable, mature/low-activity]** — **v0.7.0** (2025-08). Compile-time
  codegen; graph resolved and type-checked at build time, generated code is plain
  readable Go. Justified when hand-wiring `main.go` gets unwieldy but you still want
  compile-time safety. The slow cadence reflects a finished tool, not an abandoned one.
- **uber/fx + dig** **[active]** — **fx v1.24.0** (2025-05). Runtime reflection container
  (`dig`) plus lifecycle and modular composition (`fx`). Justified for plugin-style
  modularity and a uniform start/stop bootstrap across many services. Cost: wiring errors
  surface at **startup**, not compile time, and resolution is a layer you trust rather
  than read.

### Validation

**go-playground/validator** — **v10.30.3** (2026-05), struct tags, most widely used,
pairs with gin/echo binding · **protovalidate** — CEL, runtime-evaluated, the right
choice when the model is already protobuf · **ozzo-validation** — fluent code-based
rules, better than tags for complex/conditional logic.

### Resilience

| Library | Version (2026-08) | Use for |
|---|---|---|
| **`golang.org/x/time/rate`** | tracks x/time | Token-bucket rate limiting. The standard answer; no third-party needed. |
| **failsafe-go** | **v0.9.6** (2026-02) | Retries, circuit breakers, rate limiting, timeouts **and hedging** in one composable API. Prefer when you need more than one policy. |
| **sony/gobreaker** | **v1.0.0** (2024-04) | A single, simple circuit breaker. v1.0.0 is stable-and-finished rather than abandoned — small, correct, unchanged. |
| cenkalti/backoff · avast/retry-go | active | Backoff/retry only. |

Note the ordering trap that applies to any of these: **retry outside the breaker**, or
retries keep firing while the breaker is open. See http-clients.md.

### Observability

**Default to `log/slog`.** Stdlib, structured, pluggable handlers, under the compatibility
promise; it has made logrus/apex/log15 obsolete for new work. Its rough edge: **no
built-in `context.Context` propagation**, so request-scoped fields need a small helper
(see observability.md) or the OTel slog bridge. `slog.Group` nests related attributes.

**zap** **[stable]** — highest throughput for genuinely hot paths; dual API
(zero-alloc `Logger` + `SugaredLogger`); `zapcore.Core` composes encode/filter
pipelines. Rough edges: the global-logger pattern (`zap.L()`) makes tests awkward if
overused, and no custom levels beyond the built-ins.

**zerolog** **[stable]** — benchmarks fastest (zero-alloc builder API), but **its
slog-compatibility bridge is measurably slower than its native API** — if you adopt it
for speed, use native calls.

Bottom line: slog by default; zap/zerolog only after **measuring** logging as a
bottleneck.

Also: **OpenTelemetry-Go + `otelhttp`** (the ecosystem fiber can't use without shims),
**prometheus/client_golang**, **`net/http/pprof`** (internal port only — it leaks
internals and enables resource-exhaustion probing), and **Pyroscope** (now part of
Grafana) or **Parca** for continuous profiling — always-on sampling retained over time,
so you can diff a regression against last week's deploy instead of trying to reproduce
it. Either works; Pyroscope has the larger ecosystem via Grafana.

### Testing

- **testify** — most widely used. The argument *against* over-reliance:
  `assert.Equal` can obscure what's checked versus plain
  `if got != want { t.Fatalf(...) }`, and its `mock` package encourages
  interaction-based testing that many consider less idiomatic than simple
  interface fakes. The critique is about over-reliance, not soundness.
- **httptest** — stdlib `NewRecorder()`/`NewServer()`; usually sufficient with no
  third-party help.
- **testcontainers-go** — **v0.43.0** (2026-06). Real Postgres/Redis/Kafka in integration
  tests, avoiding mock-drift. (Note: the *Java* Testcontainers went 2.x; the Go module is
  still on a `v0.x` line.)
- **gomock / mockery / moq** — interface mock generators; largely team preference.
- **`go test -fuzz`** — stdlib fuzzing (1.18+), high value for parsers and untrusted
  input.
- **goleak** — asserts no goroutines outlive a test. Catches the classic leak: a
  goroutine blocked on a channel that's never closed or a context never cancelled.
- **`testing/synctest`** — stable in 1.25; virtual time for deterministic concurrency
  tests. See testing.md.

### Linting — golangci-lint

Default set: `errcheck`, `govet`, `ineffassign`, `staticcheck`, `unused`. Worth adding:

| Linter | Catches |
|---|---|
| **errcheck** | Unchecked error returns — the most common correctness gap in Go. |
| **staticcheck** | Broad static analysis. Note **`gosimple` and `stylecheck` are now merged into staticcheck** — don't configure them separately. |
| **revive** | Style/convention; faster, configurable replacement for deprecated `golint`. |
| **gosec** | Hardcoded credentials, weak crypto, SQL injection patterns. |
| **bodyclose** | Unclosed `http.Response.Body`. One published case study found **11 leak sites** by enabling this alone. |
| **sqlclosecheck** | Unclosed `*sql.Rows`/`*sql.Stmt` — a direct cause of pool exhaustion. |
| **noctx** | HTTP requests built without a context (`http.Get` instead of `NewRequestWithContext`) — i.e. uncancellable calls. |
| **wrapcheck** | Errors from external packages returned unwrapped. **Conflicts with `errorlint`** in some configs (golangci-lint issue #2238) — verify they compose. |
| **gocritic** | Assorted bug/style patterns (inefficient concatenation, redundant conversions). |

**Upgrade gotcha:** golangci-lint **v2 changed the config schema** — `linters-settings:`
became `linters.settings:`, and enable/disable lists moved under the `linters:` key.
This is the usual cause of "my config silently stopped working".

## Project layout

- **`cmd/` + `internal/` is the dominant convention.** `cmd/<binary>/main.go` per entry
  point, kept minimal (parse config, wire, run). `internal/` for everything not
  importable by other modules — **the compiler enforces this**, it's a language feature,
  not a convention.
- **`golang-standards/project-layout` is NOT official and is actively contested.** Say
  so plainly: it's the most-linked and most-argued-with Go structure resource. It carries
  more apparent authority than an unofficial community repo warrants, and several of its
  directories (`pkg/`, `api/`, `configs/`) are widely criticised as ceremony at typical
  service size.
- **`pkg/` is justified rarely** — when a repo genuinely exports a library for *other*
  repos to import, so `pkg/` means "public API for external consumers". Adding it out of
  habit in a single-service repo is the popular-but-wrong pattern.
- **Hexagonal/clean architecture**: ports-and-adapters maps fine onto Go interfaces and
  earns its keep when infrastructure is genuinely swappable. But Go's own idioms —
  small interfaces **defined by the consumer**, "accept interfaces, return structs" —
  already deliver most of the benefit without four mirrored layer directories. Correct
  sizing is *"introduce the interface where you have, or clearly will have, a second
  real implementation"* — not "always four layers regardless of size."
