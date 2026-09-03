# Go language & runtime for services

Verified against go.dev release notes, 2026-08. Current: **Go 1.26** (Feb 2026,
patches through 1.26.3). Previous stable: 1.25.

## Version cheat sheet — what landed and why you care

| Ver | Change | Why it matters for a service |
|---|---|---|
| 1.26 | **Green Tea GC is now the default** | Lower GC overhead (10–40% in the experimental phase) with no code change. Previously `GOEXPERIMENT=greenteagc`. |
| 1.26 | `new(expr)` takes an expression | Deletes the `func ptr[T any](v T) *T` helper every codebase wrote. `p := new(42)`, `q := new(cfg.Timeout)`. |
| 1.26 | Generic types may self-reference in their own type-param list | Enables `type Node[T any, S ~[]Node[T, S]] ...`-shaped APIs. |
| 1.26 | cgo overhead −~30%; small-object alloc −up to 30% | Expect ~1% real-world win on alloc-heavy code — not a reason to skip pooling. |
| 1.26 | `crypto/hpke` (RFC 9180, incl. post-quantum hybrid KEMs), `crypto/mlkem/mlkemtest`, `testing/cryptotest` | Standard-library HPKE instead of a third-party dep. |
| 1.26 | `GOEXPERIMENT=simd` → `simd/archsimd` (**amd64-only, API unstable**) | Do not build on it yet. |
| 1.26 | experimental `runtime/secret` | Watch it; not production guidance yet. |
| 1.25 | **Container-aware `GOMAXPROCS`** | See below — the single most important operational change in years. |
| 1.25 | `testing/synctest` **stable** | Deterministic concurrency tests with virtual time. See testing.md. |
| 1.25 | `runtime/trace` Flight Recorder | Continuous trace, snapshot only when something goes wrong. |
| 1.25 | `encoding/json/v2` behind `GOEXPERIMENT=jsonv2` | Faster decode. Experimental — don't ship on it. |
| 1.25 | `AddCleanup` runs concurrently; `GODEBUG=checkfinalizers=1` | Finds finalizer/cleanup bugs. |
| 1.24 | Generic type aliases; `testing.B.Loop`; `os.Root` | `B.Loop` is the correct benchmark loop now (see testing.md). `os.Root` for directory-confined FS access — good for path-traversal safety. |
| 1.23 | `range` over func (iterators), `iter` package | Write `iter.Seq[T]` producers instead of exposing slices or channels. |
| 1.22 | **Per-iteration loop variable scoping** | Killed the single most common Go bug: capturing the loop var in a goroutine/closure. Requires `go >= 1.22` in `go.mod` to take effect. |
| 1.22 | `net/http.ServeMux` method + wildcard patterns | The stdlib router became genuinely usable. See frameworks.md. |
| 1.22 | `math/rand/v2` | `rand.N`, no global seeding ritual. |
| 1.21 | `log/slog`, `min`/`max`/`clear`, `slices`/`maps` | `slog` is the default logging answer now. See observability.md. |

Notes: Go 1.26 is the last release supporting macOS 12 and needs Go 1.24.6+ to
bootstrap. `freebsd/riscv64` is marked broken.

## Container-aware GOMAXPROCS (1.25+) — read this before tuning anything

Before 1.25, `GOMAXPROCS` defaulted to `runtime.NumCPU()` — the *host's* logical
CPUs — so a pod limited to 2 CPUs on a 64-core node still spun up 64 OS threads
worth of parallelism, causing aggressive cgroup throttling and terrible tail
latency. Everyone imported `uber-go/automaxprocs` to fix it.

Since 1.25, on Linux the runtime reads the **cgroup CPU bandwidth limit** and
uses it when it's lower than the logical CPU count, re-reading periodically if
limits change.

```go
// Nothing to do. This is the default. Just make sure go.mod says go >= 1.25.
```

Critical details:

- It reads the **CPU *limit***, not the **CPU *request***. In Kubernetes, a pod
  with `requests.cpu: 1` and no limit gets **no** adjustment — behaviour is
  unchanged from older Go. If you rely on this, set limits.
- Setting `GOMAXPROCS` via env var or calling `runtime.GOMAXPROCS()` **disables
  both** the cgroup-awareness and the periodic re-read. Don't set it "just in case".
- Opt out entirely: `GODEBUG=containermaxprocs=0`.
- `runtime.SetDefaultGOMAXPROCS()` re-applies the default logic if you need to.

**Therefore: delete `uber-go/automaxprocs`** from any service on Go ≥ 1.25. It is
now redundant, and recommending it is a stale-advice tell.

Fractional limits round up to at least 1 — a `cpu: 0.5` pod still gets
`GOMAXPROCS=1`, so a single goroutine can still saturate its quota and get
throttled. Fractional CPU limits and latency-sensitive Go services are a bad mix
regardless of the runtime's help.

## GOMEMLIMIT — the other half of container correctness

`GOGC` (default 100) is *relative*: collect when the heap doubles since the last
GC. That's ratio-based and knows nothing about your pod's memory limit, so a
sudden live-heap increase can blow past the cgroup limit and get you
**OOMKilled** before the next GC.

`GOMEMLIMIT` (1.19+) is a **soft** limit on total runtime-managed memory. As the
total approaches it, the GC runs more aggressively — trading CPU to avoid death.

```sh
# Leave headroom for non-heap memory: goroutine stacks, mmap'd files, cgo
# allocations, and the runtime itself are outside the Go heap but inside the cgroup.
# ~85-90% of the container limit is the usual starting point.
GOMEMLIMIT=1800MiB   # for a pod with limits.memory: 2Gi
```

Guidance:

- Set `GOMEMLIMIT` on **every** containerised service. It is the cheapest
  OOMKill-prevention available.
- It is a *soft* limit — the runtime will exceed it rather than fail an allocation.
  It buys you GC pressure, not a guarantee.
- The pathological case: live heap genuinely larger than `GOMEMLIMIT` sends the GC
  into a **death spiral**, burning ~100% CPU collecting continuously. Guard with a
  floor — keep `GOGC` on (don't set `GOGC=off`) so you get normal behaviour until
  the limit actually matters.
- For a memory-heavy service, `GOGC=off` + `GOMEMLIMIT` is a legitimate pattern:
  never collect on ratio, only collect under memory pressure. Use it deliberately,
  with monitoring on GC CPU fraction.

## The scheduler, in the amount you need

G-M-P: **G**oroutine (the work), **M** machine/OS thread (the executor),
**P** processor (a scheduling context; `GOMAXPROCS` sets how many). Each P owns a
local run queue of Gs; there's a global queue and work-stealing between Ps.

Consequences worth knowing:

- Goroutines start with a small (~2–8KB) stack that grows by copying. Hundreds of
  thousands of goroutines is normal and fine — this is why "goroutine per request"
  is idiomatic in Go and "thread per request" wasn't in older Java.
- A blocking **syscall** detaches its M from the P so other goroutines keep
  running; the runtime spins up/reuses another M. This is why blocking I/O doesn't
  wreck throughput.
- **cgo calls and tight non-preemptible loops** are the exceptions: they occupy an
  M and, historically, could delay scheduling. Since 1.14 the scheduler is
  asynchronously preemptible via signals, so pure-Go tight loops no longer wedge
  the scheduler.
- `runtime.Gosched()` is almost never the right answer. If you reach for it,
  you're working around a design problem.

## Profile-guided optimisation (PGO)

Real, cheap, and underused. Collect a CPU profile from production, commit it as
`default.pgo` next to `main`, and the compiler uses it for inlining and
devirtualisation decisions on the next build.

```sh
# 1. grab a profile from a representative production instance
curl -o cpu.pprof "http://localhost:6060/debug/pprof/profile?seconds=60"

# 2. commit it as default.pgo in the main package's directory
mv cpu.pprof ./cmd/myservice/default.pgo

# 3. build — go picks up default.pgo automatically, no flags needed
go build ./cmd/myservice
```

Typical reported wins are ~2–7% CPU. Refresh the profile periodically; a very
stale profile is mildly counterproductive, not catastrophic. Worth it for any
service where CPU is the constraint.

## Concurrency: the rules that prevent incidents

### Context is the spine

Every function that does I/O or can block takes `ctx context.Context` as its
**first** parameter. Never store a context in a struct field. Never pass `nil` —
use `context.TODO()` if you genuinely don't have one yet.

```go
func (s *Service) Fetch(ctx context.Context, id string) (*Thing, error) {
    ctx, cancel := context.WithTimeout(ctx, 2*time.Second)
    defer cancel()  // ALWAYS. Not calling cancel leaks the timer until it fires.
    return s.repo.Get(ctx, id)
}
```

`context.WithValue` is for request-scoped metadata that crosses API boundaries
(request ID, auth subject, trace span) — **not** for passing optional arguments.
Use an unexported key type so nobody can collide with you:

```go
type ctxKey int
const requestIDKey ctxKey = iota
```

### errgroup for concurrent work with errors

```go
g, ctx := errgroup.WithContext(ctx)
g.SetLimit(8)  // bound the fan-out; unbounded fan-out is how you DoS a dependency

results := make([]Result, len(ids))
for i, id := range ids {
    i, id := i, id  // unnecessary on go>=1.22, harmless, and clear
    g.Go(func() error {
        r, err := fetch(ctx, id)
        if err != nil {
            return fmt.Errorf("fetch %s: %w", id, err)
        }
        results[i] = r  // safe: each goroutine writes a distinct index
        return nil
    })
}
if err := g.Wait(); err != nil {
    return nil, err  // first non-nil error; ctx was cancelled for the rest
}
```

`errgroup.WithContext` cancels the shared ctx on the first error, so siblings stop
early. `SetLimit` is the difference between a fan-out and an outage.

### Goroutine leaks — the shapes to recognise

A leaked goroutine holds its stack and everything it references, forever.

1. **Send on a channel nobody will receive from.** Producer blocks forever.
2. **Receive from a channel nobody will close.** Consumer blocks forever.
3. **Goroutine ignoring ctx cancellation.** Always `select` on `ctx.Done()` in any
   loop that can block.
4. **`time.After` in a hot loop** — the timer isn't collectable until it fires.
   Use `time.NewTimer` + `defer timer.Stop()`, or `context.WithTimeout`.
5. **Fire-and-forget with no lifecycle owner.** Every `go f()` should have a clear
   answer to "who waits for this, and how does it stop?"

Detect them in tests with `go.uber.org/goleak`:

```go
func TestMain(m *testing.M) { goleak.VerifyTestMain(m) }
```

And in production: alert on the `go_goroutines` metric trending monotonically up.

### Channel axioms

- The **sender** closes; never the receiver. Closing a channel you don't own is a
  panic waiting to happen.
- Send on a closed channel **panics**. Receive from a closed channel yields the
  zero value immediately — use `v, ok := <-ch` to distinguish.
- A `nil` channel blocks forever on both send and receive. Occasionally useful:
  set a case's channel to `nil` to disable that `select` arm.
- Unbuffered = synchronous handoff. Buffered = a bounded queue, which means you
  must think about what happens when it's full.
- Prefer returning `iter.Seq[T]` (1.23+) over a channel for pure iteration —
  no goroutine, no cancellation problem.

### Mutex vs channel

Channels for *transferring ownership* and *coordinating*. Mutexes for *protecting
a field*. A `sync.Mutex` guarding a map is simpler and faster than a goroutine
owning it behind a channel; don't be clever.

`sync.Map` only wins under a specific profile — mostly-read, disjoint key sets per
goroutine. A plain `map` + `RWMutex` is the default. `sync.Pool` is for reducing
allocation of large short-lived buffers, and it can drop entries at any GC.

Use the typed atomics (`atomic.Int64`, `atomic.Bool`, `atomic.Pointer[T]`, 1.19+)
rather than the old `atomic.AddInt64(&x, 1)` free functions — they can't be
misused by accident.

### Always run the race detector

```sh
go test -race ./...
```

It only finds races on code paths actually executed, so run it over your real test
suite in CI. A race detected is a bug, not a flake.

## Errors

```go
// Sentinel for expected, checkable conditions.
var ErrNotFound = errors.New("not found")

// Typed error when the caller needs detail.
type ValidationError struct{ Field, Reason string }
func (e *ValidationError) Error() string {
    return fmt.Sprintf("field %s: %s", e.Field, e.Reason)
}

// Wrap with %w to preserve the chain; add context, don't replace it.
if err := s.repo.Get(ctx, id); err != nil {
    return fmt.Errorf("get user %s: %w", id, err)
}

// Inspect by identity or by type — never by string matching.
if errors.Is(err, ErrNotFound) { ... }

var ve *ValidationError
if errors.As(err, &ve) { log.Warn("bad field", "field", ve.Field) }
```

Rules:

- Wrap with `%w` when the caller may want to inspect the cause; use `%v` when you
  are deliberately opaquing it (e.g. not leaking an internal error to a client).
- Add context that the caller doesn't already have. `fmt.Errorf("get user: %w")`
  inside a function called `GetUser` is noise.
- **Never** `strings.Contains(err.Error(), "not found")`. That's an API contract
  made of sand.
- `errors.Join` for accumulating independent failures (e.g. validating many fields).
- **Panic** only for programmer error (impossible state, nil dependency at
  construction). Never for expected failures. Recover at the top of a request
  handler and at the top of any goroutine you spawn — an unrecovered panic in
  *any* goroutine kills the whole process.

```go
// Every long-lived goroutine needs this, or one bad message takes down the pod.
go func() {
    defer func() {
        if r := recover(); r != nil {
            logger.Error("panic in worker", "panic", r, "stack", string(debug.Stack()))
        }
    }()
    worker(ctx)
}()
```

## Escape analysis & allocation, briefly

`go build -gcflags='-m'` tells you what escapes to the heap. Worth a look when
optimising a hot path, ignorable otherwise. The usual causes: returning a pointer
to a local, storing into an `interface{}`, closure capture, and anything the
compiler can't prove doesn't outlive the frame.

Practical wins, in order of payoff:
1. Preallocate slices/maps with a known size: `make([]T, 0, n)`.
2. Reuse buffers via `sync.Pool` for large, short-lived, hot-path allocations.
3. Pass small structs by value; pointers aren't automatically cheaper.
4. Avoid `fmt.Sprintf` in hot paths — it boxes into `interface{}` and allocates.

Measure first: `go test -bench=. -benchmem`, then `pprof`. Do not guess.

## GODEBUG knobs worth knowing

| Setting | Use |
|---|---|
| `GODEBUG=containermaxprocs=0` | Disable 1.25 cgroup-aware GOMAXPROCS |
| `GODEBUG=checkfinalizers=1` | Find finalizer/cleanup mistakes (1.25+) |
| `GODEBUG=gctrace=1` | One line per GC to stderr — quick GC sanity check |
| `GODEBUG=schedtrace=1000` | Scheduler state every 1s; deep debugging only |
| `GODEBUG=inittrace=1` | Per-package init cost — good for slow startup |
| `GOEXPERIMENT=jsonv2` | Opt into `encoding/json/v2` (1.25+, experimental) |

`GODEBUG` also carries **compatibility** settings: when a Go release changes
behaviour, the old behaviour usually stays reachable via a `GODEBUG` key keyed to
the `go` line in your `go.mod`. That's why bumping the `go` directive can change
runtime behaviour even with no code edits — read the release notes when you bump it.
