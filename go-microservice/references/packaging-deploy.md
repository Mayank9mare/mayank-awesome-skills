# Building, containerising & shutting down a Go service

## Graceful shutdown — the canonical pattern

Getting this wrong means dropped requests, lost messages, and half-written data on
every single deploy. It's the highest-value 40 lines in the service.

**Order matters**: stop accepting new work → drain in-flight → stop background
consumers → close resources. Reverse that and in-flight requests find a closed
database.

```go
func main() {
    if err := run(); err != nil {
        slog.Error("fatal", slog.String("error", err.Error()))
        os.Exit(1)
    }
}

func run() error {
    // NotifyContext cancels ctx on SIGINT/SIGTERM. SIGTERM is what Kubernetes
    // sends; SIGKILL (after terminationGracePeriodSeconds) cannot be caught.
    ctx, stop := signal.NotifyContext(context.Background(),
        os.Interrupt, syscall.SIGTERM)
    defer stop()

    cfg, err := LoadConfig()          // validate config BEFORE opening anything
    if err != nil {
        return fmt.Errorf("config: %w", err)
    }

    db, err := openDB(ctx, cfg)
    if err != nil {
        return fmt.Errorf("db: %w", err)
    }
    defer db.Close()

    srv := &http.Server{
        Addr:              cfg.Addr,
        Handler:           newRouter(db),
        ReadHeaderTimeout: 5 * time.Second,   // slowloris guard — always set
        ReadTimeout:       15 * time.Second,
        WriteTimeout:      30 * time.Second,
        IdleTimeout:       60 * time.Second,
        MaxHeaderBytes:    1 << 20,
        BaseContext:       func(net.Listener) context.Context { return ctx },
    }

    // Serve in the background so main can wait on ctx.
    errCh := make(chan error, 1)
    go func() {
        slog.Info("listening", slog.String("addr", cfg.Addr))
        if err := srv.ListenAndServe(); err != nil &&
            !errors.Is(err, http.ErrServerClosed) {
            errCh <- err            // real failure, e.g. port in use
        }
    }()

    // Background consumers get the same ctx and must return when it's cancelled.
    consumers, cctx := errgroup.WithContext(ctx)
    consumers.Go(func() error { return runQueueConsumer(cctx, db) })

    select {
    case err := <-errCh:
        return fmt.Errorf("serve: %w", err)
    case <-ctx.Done():
        slog.Info("shutdown signal received")
    }

    // 1. Fail readiness FIRST so load balancers stop sending new requests.
    //    Give them time to notice — this sleep is deliberate and necessary,
    //    because endpoint propagation is eventually consistent.
    shuttingDown.Store(true)
    time.Sleep(cfg.PreShutdownDelay)          // typically 2-5s

    // 2. Stop accepting, drain in-flight. Budget must be < the orchestrator's
    //    grace period, or you get SIGKILLed mid-drain.
    shutdownCtx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
    defer cancel()

    if err := srv.Shutdown(shutdownCtx); err != nil {
        slog.Error("graceful shutdown timed out; forcing close",
            slog.String("error", err.Error()))
        _ = srv.Close()      // hard close whatever is left
    }

    // 3. Now stop consumers and wait for the current message to finish.
    if err := consumers.Wait(); err != nil && !errors.Is(err, context.Canceled) {
        slog.Error("consumer error", slog.String("error", err.Error()))
    }

    // 4. Resources close last, via the defers above.
    slog.Info("shutdown complete")
    return nil
}
```

Key points:

- `srv.Shutdown` returns `http.ErrServerClosed` from `ListenAndServe` — that's the
  *success* path, so it must be excluded from error handling.
- **`Shutdown` does not wait for hijacked or WebSocket connections.** Track and
  close those yourself.
- The `PreShutdownDelay` is not superstition: Kubernetes removes the pod from
  Endpoints asynchronously, so requests keep arriving for a second or two after
  SIGTERM. Skipping this is the usual cause of "5xx on every deploy".
- Set the shutdown budget below `terminationGracePeriodSeconds` (default 30s).
- Prefer `run() error` over doing work in `main()` — `os.Exit` skips deferred calls,
  so anything that must flush (trace exporter, log buffer) needs the defer to
  actually run.

## Dockerfile

```dockerfile
# ---- build stage -------------------------------------------------------------
FROM golang:1.26 AS build
WORKDIR /src

# Copy manifests first: this layer is cached until dependencies change.
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download

COPY . .
ARG VERSION=dev
ARG COMMIT=unknown
# CGO_ENABLED=0 -> a static binary that runs in scratch/distroless.
# -trimpath     -> strips local paths, making builds reproducible.
# -s -w         -> drop symbol table and DWARF; smaller binary, no debuginfo.
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=linux go build \
      -trimpath \
      -ldflags="-s -w -X main.version=${VERSION} -X main.commit=${COMMIT}" \
      -o /out/app ./cmd/myservice

# ---- runtime stage -----------------------------------------------------------
FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/app /app
# CA certs come with distroless/static; with `scratch` you must copy them or
# every HTTPS call fails with x509: certificate signed by unknown authority.
USER nonroot:nonroot
EXPOSE 8080
ENTRYPOINT ["/app"]
```

### Base image choice

| Base | Size | Notes |
|---|---|---|
| **`distroless/static:nonroot`** | ~2 MB | **Default.** CA certs, tzdata, `/etc/passwd`, non-root user. No shell — good for security, means healthchecks must not use `sh`. |
| `scratch` | 0 | Absolute minimum. You must add CA certs and tzdata yourself. |
| `alpine` | ~7 MB | Has a shell for debugging. **musl, not glibc** — only safe with `CGO_ENABLED=0`. With CGO you hit DNS resolver differences and subtle breakage. |
| `debian:*-slim` | ~80 MB | When you genuinely need glibc + CGO. |

**The CGO/musl trap:** with `CGO_ENABLED=1`, Go uses the system DNS resolver. On
Alpine that's musl, which historically mishandles some DNS edge cases (large
responses, multiple search domains). With `CGO_ENABLED=0`, Go uses its pure-Go
resolver and the problem disappears. Keep CGO off unless you need it (SQLite, some
crypto/ML bindings).

### Healthcheck in a shell-less image

`HEALTHCHECK CMD curl ...` fails in distroless — there's no curl and no shell. Use
the orchestrator's HTTP probe instead (`httpGet` in Kubernetes), or compile a tiny
health subcommand into your own binary:

```dockerfile
HEALTHCHECK --interval=10s --timeout=2s CMD ["/app", "healthcheck"]
```

## Version stamping

Either inject with `-ldflags -X` (above), or read what the toolchain already
recorded:

```go
import "runtime/debug"

func buildInfo() (rev string, dirty bool) {
    bi, ok := debug.ReadBuildInfo()
    if !ok {
        return "unknown", false
    }
    for _, s := range bi.Settings {
        switch s.Key {
        case "vcs.revision":
            rev = s.Value
        case "vcs.modified":
            dirty = s.Value == "true"
        }
    }
    return rev, dirty
}
```

`ReadBuildInfo` needs the build to happen inside the VCS checkout (not from a
tarball) and is disabled by `-buildvcs=false`. Expose version + commit on a
`/version` endpoint and in the startup log line — it's the first question in any
incident.

## Config: validate at boot, fail fast

A service that starts with bad config and fails on the first request is worse than
one that refuses to start.

```go
type Config struct {
    Addr             string        `env:"ADDR" envDefault:":8080"`
    DatabaseURL      string        `env:"DATABASE_URL,required"`
    DBMaxOpenConns   int           `env:"DB_MAX_OPEN_CONNS" envDefault:"25"`
    RequestTimeout   time.Duration `env:"REQUEST_TIMEOUT" envDefault:"3s"`
    PreShutdownDelay time.Duration `env:"PRE_SHUTDOWN_DELAY" envDefault:"3s"`
    LogLevel         slog.Level    `env:"LOG_LEVEL" envDefault:"info"`
}

func LoadConfig() (*Config, error) {
    var c Config
    if err := env.Parse(&c); err != nil {      // caarlos0/env, or envconfig/koanf
        return nil, err
    }
    // Cross-field checks the tags can't express.
    if c.DBMaxOpenConns < 1 {
        return nil, fmt.Errorf("DB_MAX_OPEN_CONNS must be >= 1, got %d", c.DBMaxOpenConns)
    }
    if c.PreShutdownDelay > 15*time.Second {
        return nil, fmt.Errorf("PRE_SHUTDOWN_DELAY %s risks exceeding the grace period",
            c.PreShutdownDelay)
    }
    return &c, nil
}
```

Rules: env vars (12-factor), `required` on anything without a safe default,
typed fields (`time.Duration`, not `int` seconds), and **never log secret values**.
Prefer a flat struct over deeply nested config files — a service's config should
fit on one screen.

## Kubernetes essentials that interact with the runtime

```yaml
resources:
  requests: { cpu: "500m", memory: "512Mi" }
  limits:   { cpu: "2",    memory: "1Gi" }     # Go 1.25+ reads the CPU LIMIT
env:
  - name: GOMEMLIMIT
    value: "900MiB"                            # ~90% of the memory limit
terminationGracePeriodSeconds: 30              # > your shutdown budget
readinessProbe:
  httpGet: { path: /readyz, port: 8080 }
  periodSeconds: 5
livenessProbe:
  httpGet: { path: /healthz, port: 8080 }
  periodSeconds: 10
  failureThreshold: 3
```

- Go 1.25+ derives `GOMAXPROCS` from the **CPU limit**, not the request. If you set
  only requests, you get no adjustment.
- Set `GOMEMLIMIT` — the GC otherwise has no idea about the cgroup limit.
- **Avoid fractional CPU limits** for latency-sensitive Go services; throttling
  produces confusing tail latency that looks like application slowness.
- Grace period must exceed pre-shutdown delay + drain budget.

## Security & supply chain

```sh
govulncheck ./...                  # known CVEs in your dependency graph
go mod verify                      # checksums match go.sum
go mod tidy -diff                  # CI gate: fails if go.mod/go.sum are stale
```

Run `govulncheck` in CI — unlike a generic scanner it uses call-graph analysis, so
it reports only vulnerabilities you actually reach. Combine with Dependabot/Renovate
for upgrades, pin the builder image by digest for reproducibility, and generate an
SBOM if your org requires one.

Never bake secrets into the image. Inject at runtime (env from a secret store,
mounted file, or workload identity).

## Makefile worth having

```makefile
VERSION ?= $(shell git describe --tags --always --dirty)
COMMIT  ?= $(shell git rev-parse --short HEAD)

.PHONY: build test lint vuln docker
build:
	CGO_ENABLED=0 go build -trimpath \
	  -ldflags="-s -w -X main.version=$(VERSION) -X main.commit=$(COMMIT)" \
	  -o bin/app ./cmd/myservice

test:                       ## race detector on by default; it finds real bugs
	go test -race -count=1 ./...

lint:
	golangci-lint run ./...

vuln:
	govulncheck ./...

docker:
	docker build --build-arg VERSION=$(VERSION) --build-arg COMMIT=$(COMMIT) -t myservice:$(VERSION) .
```

`-count=1` defeats Go's test caching when you want a genuine re-run.
