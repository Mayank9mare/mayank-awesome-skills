// Package main is a production-shaped entry point for a Go HTTP service.
//
// Copy this as cmd/<service>/main.go and adapt. It deliberately demonstrates the
// things that cause incidents when omitted:
//
//   - config validated at boot (fail fast, not at 3am in a request path)
//   - every http.Server timeout set (an unconfigured server is slowloris-vulnerable)
//   - liveness vs readiness as SEPARATE checks
//   - graceful shutdown in the correct order, with a pre-stop drain delay
//   - run() error rather than logic in main(), so defers actually run
//   - panic recovery in middleware AND in every long-lived goroutine
//
// See the go-microservice skill's references/ for the reasoning behind each.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"net/http/pprof"
	"os"
	"os/signal"
	"runtime"
	"runtime/debug"
	"strconv"
	"sync/atomic"
	"syscall"
	"time"
)

// Injected at build time:
//
//	go build -ldflags="-X main.version=$(git describe --tags) -X main.commit=$(git rev-parse --short HEAD)"
var (
	version = "dev"
	commit  = "unknown"
)

func main() {
	// All real work happens in run() so that deferred cleanup runs. os.Exit
	// skips defers, so calling it from main() after opening resources leaks them
	// and loses buffered telemetry.
	if err := run(); err != nil {
		slog.Error("fatal", slog.String("error", err.Error()))
		os.Exit(1)
	}
}

// Config is the service's entire configuration surface. Keep it flat and small
// enough to read on one screen.
type Config struct {
	Addr             string
	AdminAddr        string
	LogLevel         slog.Level
	RequestTimeout   time.Duration
	PreShutdownDelay time.Duration
	ShutdownTimeout  time.Duration
}

// LoadConfig reads and VALIDATES configuration. A service that starts with bad
// config and fails on the first request is worse than one that refuses to start.
func LoadConfig() (*Config, error) {
	c := &Config{
		Addr:             envStr("ADDR", ":8080"),
		AdminAddr:        envStr("ADMIN_ADDR", ":9090"),
		RequestTimeout:   envDur("REQUEST_TIMEOUT", 3*time.Second),
		PreShutdownDelay: envDur("PRE_SHUTDOWN_DELAY", 3*time.Second),
		ShutdownTimeout:  envDur("SHUTDOWN_TIMEOUT", 20*time.Second),
		LogLevel:         slog.LevelInfo,
	}
	if lvl := os.Getenv("LOG_LEVEL"); lvl != "" {
		if err := c.LogLevel.UnmarshalText([]byte(lvl)); err != nil {
			return nil, fmt.Errorf("LOG_LEVEL %q: %w", lvl, err)
		}
	}
	// Cross-field checks the individual parsers can't express.
	if c.PreShutdownDelay+c.ShutdownTimeout > 28*time.Second {
		return nil, fmt.Errorf(
			"PRE_SHUTDOWN_DELAY (%s) + SHUTDOWN_TIMEOUT (%s) risks exceeding a 30s "+
				"terminationGracePeriodSeconds; SIGKILL would interrupt the drain",
			c.PreShutdownDelay, c.ShutdownTimeout)
	}
	return c, nil
}

// shuttingDown flips before the drain begins so /readyz starts failing while the
// server is still serving in-flight requests.
var shuttingDown atomic.Bool

func run() error {
	cfg, err := LoadConfig()
	if err != nil {
		return fmt.Errorf("config: %w", err)
	}

	logger := newLogger(cfg.LogLevel)
	slog.SetDefault(logger)

	// Log resolved config once. This answers "what was this pod actually running?"
	// in every incident. Never log secret values.
	logger.Info("starting",
		slog.String("version", version),
		slog.String("commit", commit),
		slog.String("go", runtime.Version()),
		slog.Int("gomaxprocs", runtime.GOMAXPROCS(0)), // 1.25+: cgroup-aware
		slog.String("gomemlimit", os.Getenv("GOMEMLIMIT")),
		slog.String("addr", cfg.Addr),
	)

	// SIGTERM is what an orchestrator sends. SIGKILL cannot be caught.
	ctx, stop := signal.NotifyContext(context.Background(),
		os.Interrupt, syscall.SIGTERM)
	defer stop()

	// --- dependencies -------------------------------------------------------
	// db, err := openDB(ctx, cfg); if err != nil { return err }; defer db.Close()
	// Construct outbound HTTP clients ONCE here and inject them. A per-request
	// client throws away connection pooling entirely.

	// --- admin server: metrics + pprof on a SEPARATE, non-public port --------
	adminSrv := &http.Server{
		Addr:              cfg.AdminAddr,
		Handler:           adminMux(),
		ReadHeaderTimeout: 5 * time.Second,
	}
	go func() {
		defer recoverPanic(logger, "admin-server")
		if err := adminSrv.ListenAndServe(); err != nil &&
			!errors.Is(err, http.ErrServerClosed) {
			logger.Error("admin server failed", slog.String("error", err.Error()))
		}
	}()

	// --- main server --------------------------------------------------------
	srv := &http.Server{
		Addr:    cfg.Addr,
		Handler: newRouter(logger, cfg),

		// Every one of these matters. &http.Server{Handler: mux} with no timeouts
		// is vulnerable to slow-client resource exhaustion by default.
		ReadHeaderTimeout: 5 * time.Second,  // slowloris guard — the critical one
		ReadTimeout:       15 * time.Second, // headers + body
		WriteTimeout:      30 * time.Second, // size for your slowest legit response
		IdleTimeout:       60 * time.Second, // idle keep-alives
		MaxHeaderBytes:    1 << 20,

		BaseContext: func(net.Listener) context.Context { return ctx },
	}

	errCh := make(chan error, 1)
	go func() {
		logger.Info("listening", slog.String("addr", cfg.Addr))
		// ErrServerClosed is the SUCCESS path of Shutdown — exclude it.
		if err := srv.ListenAndServe(); err != nil &&
			!errors.Is(err, http.ErrServerClosed) {
			errCh <- err
		}
	}()

	select {
	case err := <-errCh:
		return fmt.Errorf("serve: %w", err) // e.g. port already in use
	case <-ctx.Done():
		logger.Info("shutdown signal received")
	}

	// --- graceful shutdown, in order ----------------------------------------

	// 1. Fail readiness FIRST, then wait. Endpoint removal is eventually
	//    consistent, so requests keep arriving for a second or two after SIGTERM.
	//    Skipping this delay is the usual cause of 5xx on every deploy.
	shuttingDown.Store(true)
	logger.Info("readiness failing; waiting for load balancer to drain",
		slog.Duration("delay", cfg.PreShutdownDelay))
	select {
	case <-time.After(cfg.PreShutdownDelay):
	case <-time.After(cfg.PreShutdownDelay): // (single arm; kept simple)
	}

	// 2. Stop accepting, drain in-flight. Use a FRESH context: ctx is already
	//    cancelled, and passing it would abort the drain immediately.
	shutdownCtx, cancel := context.WithTimeout(context.Background(), cfg.ShutdownTimeout)
	defer cancel()

	if err := srv.Shutdown(shutdownCtx); err != nil {
		logger.Error("graceful shutdown timed out; forcing close",
			slog.String("error", err.Error()))
		_ = srv.Close()
	}
	_ = adminSrv.Shutdown(shutdownCtx)

	// 3. Stop background consumers here and wait for the in-flight message.
	// 4. Close pools/clients last — via the defers above.

	logger.Info("shutdown complete")
	return nil
}

func newLogger(level slog.Level) *slog.Logger {
	opts := &slog.HandlerOptions{Level: level, AddSource: true}

	var h slog.Handler
	if os.Getenv("ENV") == "local" {
		h = slog.NewTextHandler(os.Stdout, opts) // human-readable
	} else {
		h = slog.NewJSONHandler(os.Stdout, opts) // machine-parseable; stdout, not a file
	}
	return slog.New(h).With(
		slog.String("service", "myservice"),
		slog.String("version", version),
	)
}

func newRouter(logger *slog.Logger, cfg *Config) http.Handler {
	mux := http.NewServeMux()

	// LIVENESS: "is this process functioning?" It must NOT check dependencies.
	// If it pings the database, one DB blip restarts every pod simultaneously
	// and turns a transient blip into a full outage.
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok"))
	})

	// READINESS: "should I receive traffic right now?" Checks what you cannot
	// serve without, with a short timeout. Optional dependencies (e.g. a cache
	// you can bypass) must NOT fail readiness.
	mux.HandleFunc("GET /readyz", func(w http.ResponseWriter, r *http.Request) {
		if shuttingDown.Load() {
			http.Error(w, "shutting down", http.StatusServiceUnavailable)
			return
		}
		ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
		defer cancel()
		_ = ctx
		// if err := db.PingContext(ctx); err != nil { 503 }
		w.WriteHeader(http.StatusOK)
	})

	mux.HandleFunc("GET /version", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{
			"version": version, "commit": commit,
		})
	})

	// Go 1.22+ routing: method + single-segment wildcard, read via PathValue.
	mux.HandleFunc("GET /users/{id}", func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("id")
		if id == "" {
			writeError(w, http.StatusBadRequest, "invalid_request", "id is required")
			return
		}
		writeJSON(w, http.StatusOK, map[string]string{"id": id})
	})

	// Outermost first. Recover must be outside Logging so a panic is still logged
	// with its request context.
	return chain(mux,
		requestIDMiddleware,
		recoverMiddleware(logger),
		loggingMiddleware(logger),
		timeoutMiddleware(cfg.RequestTimeout),
	)
}

func adminMux() *http.ServeMux {
	mux := http.NewServeMux()
	// mux.Handle("GET /metrics", promhttp.Handler())

	// pprof leaks internals and can be used to DoS you — admin port ONLY.
	mux.HandleFunc("GET /debug/pprof/", pprof.Index)
	mux.HandleFunc("GET /debug/pprof/profile", pprof.Profile)
	mux.HandleFunc("GET /debug/pprof/heap", pprof.Handler("heap").ServeHTTP)
	mux.HandleFunc("GET /debug/pprof/goroutine", pprof.Handler("goroutine").ServeHTTP)
	return mux
}

// --- middleware -------------------------------------------------------------

type ctxKey int

const requestIDKey ctxKey = iota // unexported key type: nobody can collide with us

func RequestIDFrom(ctx context.Context) (string, bool) {
	id, ok := ctx.Value(requestIDKey).(string)
	return id, ok
}

type middleware func(http.Handler) http.Handler

func chain(h http.Handler, mws ...middleware) http.Handler {
	for i := len(mws) - 1; i >= 0; i-- { // reverse so mws[0] is outermost
		h = mws[i](h)
	}
	return h
}

func requestIDMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		id := r.Header.Get("X-Request-Id")
		if id == "" {
			id = strconv.FormatInt(time.Now().UnixNano(), 36) // use uuid in real code
		}
		w.Header().Set("X-Request-Id", id) // echo so clients can quote it
		next.ServeHTTP(w, r.WithContext(context.WithValue(r.Context(), requestIDKey, id)))
	})
}

func recoverMiddleware(logger *slog.Logger) middleware {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			defer func() {
				if rec := recover(); rec != nil {
					id, _ := RequestIDFrom(r.Context())
					logger.Error("panic recovered",
						slog.Any("panic", rec),
						slog.String("request_id", id),
						slog.String("path", r.URL.Path),
						slog.String("stack", string(debug.Stack())))
					writeError(w, http.StatusInternalServerError,
						"internal_error", "internal server error")
				}
			}()
			next.ServeHTTP(w, r)
		})
	}
}

func loggingMiddleware(logger *slog.Logger) middleware {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			start := time.Now()
			rec := &statusRecorder{ResponseWriter: w, status: http.StatusOK}
			next.ServeHTTP(rec, r)

			// r.Pattern (1.22+) is the route TEMPLATE — safe as a metric label.
			// r.URL.Path would be unbounded cardinality.
			route := r.Pattern
			if route == "" {
				route = "unmatched"
			}
			logger.LogAttrs(r.Context(), slog.LevelInfo, "request",
				slog.String("method", r.Method),
				slog.String("route", route),
				slog.Int("status", rec.status),
				slog.Duration("duration", time.Since(start)),
			)
		})
	}
}

func timeoutMiddleware(d time.Duration) middleware {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			ctx, cancel := context.WithTimeout(r.Context(), d)
			defer cancel()
			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}
}

// statusRecorder captures the status code for logging/metrics.
//
// Wrapping ResponseWriter is a classic source of subtle breakage: if you don't
// forward Flush/Hijack, streaming endpoints (SSE, websockets) silently stop
// working. Unwrap() lets http.ResponseController find the real writer.
type statusRecorder struct {
	http.ResponseWriter
	status      int
	wroteHeader bool
}

func (r *statusRecorder) WriteHeader(code int) {
	if r.wroteHeader {
		return // guard: a second WriteHeader panics
	}
	r.wroteHeader = true
	r.status = code
	r.ResponseWriter.WriteHeader(code)
}

func (r *statusRecorder) Unwrap() http.ResponseWriter { return r.ResponseWriter }

// --- helpers ----------------------------------------------------------------

type errorBody struct {
	Error struct {
		Code    string `json:"code"`
		Message string `json:"message"`
	} `json:"error"`
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func writeError(w http.ResponseWriter, status int, code, msg string) {
	var b errorBody
	b.Error.Code = code
	b.Error.Message = msg // never leak internal error text to clients
	writeJSON(w, status, b)
}

// recoverPanic guards a long-lived goroutine. An unrecovered panic in ANY
// goroutine kills the whole process, so every `go f()` needs this.
func recoverPanic(logger *slog.Logger, name string) {
	if rec := recover(); rec != nil {
		logger.Error("panic in goroutine",
			slog.String("goroutine", name),
			slog.Any("panic", rec),
			slog.String("stack", string(debug.Stack())))
	}
}

func envStr(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func envDur(key string, def time.Duration) time.Duration {
	if v := os.Getenv(key); v != "" {
		if d, err := time.ParseDuration(v); err == nil {
			return d
		}
	}
	return def
}
