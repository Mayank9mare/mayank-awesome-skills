---
name: go-microservice
description: Use when building, scaffolding, or reviewing a Go backend service or HTTP/gRPC API — choosing between stdlib net/http, chi, gin, echo, fiber, ConnectRPC or gRPC; wiring Postgres/MySQL with pgx, sqlc, GORM or ent; Redis caching and distributed locks; SQS/Kafka consumers; graceful shutdown; GOMAXPROCS/GOMEMLIMIT container tuning; goroutine leaks; log/slog structured logging; OpenTelemetry; Dockerfiles for Go; project layout with cmd/ and internal/. Also for "start a Go service", "add an endpoint", "why is my Go service leaking goroutines", "Go service is getting OOMKilled".
---

# Go Microservice

## Overview

A Go service is six things: **config**, an **HTTP/RPC surface**, **state** (DB +
cache), **async work**, **outbound calls**, and **operability**. Get those right and
the rest is business logic. Go's defaults are safe for CLIs and unsafe for servers —
most of this skill is about the settings nobody sets until an incident forces them to.

Verified against Go **1.26** (current, Feb 2026) as of 2026-08. Library versions
throughout come from `proxy.golang.org`, not from blog posts — check
`go list -m -u <module>` for anything newer.

## When to Use

- Starting a new Go service, or adding an endpoint/consumer to an existing one
- Choosing a router, database layer, cache client, or queue library
- Reviewing Go service code for production-readiness
- Diagnosing: goroutine leaks, OOMKills, CPU throttling, dropped requests on deploy,
  connection-pool exhaustion, "slow under load but fine locally"
- Containerising a Go service, or tuning it for Kubernetes

**Not for:** CLI tools (much of this is irrelevant), library design, or non-service Go.

## Step 0: Choose the HTTP layer

| If… | Use |
|---|---|
| Default, no strong reason otherwise | **stdlib `net/http` + `ServeMux`** (1.22+ routing is genuinely enough) |
| You want groups/sub-routers, still stdlib-shaped | **chi** |
| You want built-in binding/validation/rendering and accept a non-stdlib handler signature | **gin** or **echo** |
| Browser clients, or HTTP/1.1-only infrastructure, from `.proto` | **ConnectRPC** |
| Service-to-service, typed contracts, streaming | **gRPC** (+ buf) |
| Raw throughput on a narrow service, accepting ecosystem loss | **fiber** — read the warning in references/frameworks.md first |

Since Go 1.22 the stdlib does method + wildcard routing. **Start there** and add a
router only when you feel the absence. Full comparison, and fiber's `net/http`
incompatibility, in references/frameworks.md.

## Quick Reference

| Task | Reach for | Detail |
|---|---|---|
| Router | stdlib `ServeMux`, chi | references/frameworks.md |
| Postgres | **pgx v5**, + **sqlc** for typed queries | references/persistence.md |
| Migrations | golang-migrate, goose, atlas | references/persistence.md |
| Redis | **rueidis** (or go-redis/v9) | references/caching-redis.md |
| Kafka | **franz-go** | references/messaging.md |
| Job queue | **River** (Postgres, transactional enqueue) | references/messaging.md |
| Outbound HTTP | `http.Client` with **every** timeout set | references/http-clients.md |
| Logging | **`log/slog`**, JSON to stdout | references/observability.md |
| Metrics/tracing | prometheus/client_golang, OTel + `otelhttp` | references/observability.md |
| Config | envconfig/koanf → validate at boot | references/packaging-deploy.md |
| DI | **manual wiring**; wire if it gets big; fx for lifecycle | references/frameworks.md |
| Tests | table-driven, `httptest`, testcontainers-go, `testing/synctest` | references/testing.md |
| Lint | golangci-lint + errcheck, bodyclose, sqlclosecheck, noctx | references/frameworks.md |
| Container | multi-stage → `distroless/static:nonroot` | references/packaging-deploy.md |

## Bootstrap a new service

```
myservice/
  cmd/myservice/main.go      # entry point: parse config, wire, run. Keep it thin.
  internal/
    config/                  # typed config, validated at boot
    http/                    # handlers, middleware, router
    service/                 # business logic — no HTTP or SQL types here
    store/                   # DB access (sqlc output or repositories)
    client/                  # outbound HTTP/gRPC clients
  migrations/
  Dockerfile
  Makefile
```

1. `go mod init <module>` — set the `go` directive to **1.25+** so you get
   container-aware `GOMAXPROCS`.
2. **Config struct + `LoadConfig()` that fails fast** on missing/invalid values.
3. `run() error` called from `main()` — *not* logic in `main`, because `os.Exit` skips
   deferred cleanup.
4. `http.Server` with **all** timeouts set (`ReadHeaderTimeout` at minimum).
5. `/healthz` (liveness, process-local) and `/readyz` (readiness, checks dependencies).
6. Middleware: request ID → structured logging → metrics → panic recovery.
7. **Graceful shutdown** with the correct drain order — copy it from
   references/packaging-deploy.md, don't improvise.
8. `GOMEMLIMIT` ≈ 90% of the container memory limit.

## The non-negotiables

These cause incidents when skipped. Everything else is preference.

1. **Every `http.Server` timeout set.** `&http.Server{Handler: mux}` with no timeouts
   is vulnerable to slowloris by default. `ReadHeaderTimeout` is the bare minimum.
2. **Every outbound call has a timeout.** `http.DefaultClient` has none. A hung
   dependency with no timeout is how one service's slowness becomes your outage.
3. **`context.Context` first parameter on anything that blocks**, propagated, never
   stored in a struct. Every `WithTimeout` gets `defer cancel()`.
4. **Graceful shutdown, in order**: fail readiness → wait for LB propagation → stop
   accepting → drain in-flight → stop consumers → close resources.
5. **`GOMEMLIMIT` set** on every containerised service. `GOGC` is ratio-based and knows
   nothing about your cgroup limit — this is the cheapest OOMKill prevention available.
6. **Structured logs to stdout as JSON, with a request ID.** Never a formatted
   sentence; never secrets.
7. **`recover()` in every long-lived goroutine.** An unrecovered panic in *any*
   goroutine kills the whole process.
8. **Bounded fan-out.** `errgroup.SetLimit`, or a semaphore. Unbounded concurrency
   against a dependency is a self-inflicted DoS.
9. **Consumers are idempotent.** At-least-once delivery is the only kind you get.
10. **`go test -race` in CI.** A detected race is a bug, not a flake.

## Reference Map

| File | Read when |
|---|---|
| references/language-runtime.md | Version features, GC, GOMAXPROCS/GOMEMLIMIT, goroutine leaks, errors, PGO |
| references/frameworks.md | Choosing a router/RPC/library; project layout; linting |
| references/persistence.md | SQL driver, sqlc/ORM choice, pool tuning, transactions, migrations |
| references/caching-redis.md | Cache client, patterns, TTLs, distributed locks |
| references/messaging.md | Queue/stream consumers, idempotency, retries, DLQs |
| references/http-clients.md | Outbound calls: timeouts, retries, breakers, pooling |
| references/observability.md | slog, metrics + cardinality, OTel, health endpoints, pprof |
| references/testing.md | Table-driven tests, testcontainers, synctest, goleak |
| references/packaging-deploy.md | Graceful shutdown, Dockerfile, config, Kubernetes |

## Common Mistakes

| Mistake | Why it hurts | Fix |
|---|---|---|
| `http.Get` / `http.DefaultClient` | No timeout — waits forever | Construct a client with `Timeout` + tuned transport |
| `&http.Server{Handler: mux}` | No timeouts; slowloris-vulnerable | Set all five timeout fields |
| Not closing `resp.Body` | Leaks the connection permanently | `defer resp.Body.Close()`; enable `bodyclose` |
| `MaxIdleConnsPerHost` left at 2 | New TCP+TLS per call under load | Raise to expected concurrency |
| `uber-go/automaxprocs` on Go ≥1.25 | Redundant — the runtime does this now | Delete it |
| No `GOMEMLIMIT` | GC ignores the cgroup limit → OOMKill | Set ≈90% of the memory limit |
| Only `requests.cpu`, no limit | Go 1.25 reads the **limit**, not requests | Set CPU limits (avoid fractional for latency-sensitive) |
| `err = err` / ignored errors | Silently swallowed failures — a real bug found in production framework code | Enable `errcheck`; return or log, never both |
| Raw path in a metric label | Unbounded cardinality kills Prometheus | Use `r.Pattern` (the route template) |
| Goroutine with no lifecycle owner | Leak: holds its stack forever | Every `go f()` answers "who waits, how does it stop?" |
| `time.After` in a hot loop | Timer uncollectable until it fires | `time.NewTimer` + `defer Stop()`, or context |
| `strings.Contains(err.Error(), …)` | API contract made of sand | `errors.Is` / `errors.As` |
| Two libraries both calling a global setter (e.g. `SetGlobalTracer`) | Last one silently wins; the other's data vanishes | One tracing/metrics stack per process |
| `pkg/` by habit | Ceremony; `internal/` is compiler-enforced | Use `internal/` unless exporting to other repos |
| Wrapping `ResponseWriter` without forwarding `Flush`/`Hijack` | Silently breaks SSE/websockets | Implement `Unwrap()`; forward optional interfaces |
