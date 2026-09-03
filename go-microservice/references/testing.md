# Testing Go services

## Table-driven tests — the idiom

```go
func TestValidateEmail(t *testing.T) {
    tests := []struct {
        name    string
        input   string
        wantErr error
    }{
        {"valid", "user@example.com", nil},
        {"no at sign", "userexample.com", ErrInvalidEmail},
        {"empty", "", ErrInvalidEmail},
        {"unicode local part", "üser@example.com", nil},
    }

    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            t.Parallel()                 // safe: no shared mutable state
            err := ValidateEmail(tt.input)
            if !errors.Is(err, tt.wantErr) {
                t.Errorf("ValidateEmail(%q) = %v, want %v", tt.input, err, tt.wantErr)
            }
        })
    }
}
```

`t.Run` gives each case a name that appears in failures and can be selected with
`-run 'TestValidateEmail/empty'`. Since Go 1.22 the loop variable is per-iteration, so the
old `tt := tt` line is unnecessary (harmless if you keep it).

Compare errors with `errors.Is`, never string equality. Use `%q` in messages so
whitespace and empty strings are visible.

## testify: use it deliberately

`testify` reduces boilerplate, and the critique of it is real:
`assert.Equal(t, want, got)` reads less clearly than the explicit comparison, and its
`mock` package pulls you toward interaction-based tests that assert *how* code works
rather than *what* it produces.

Reasonable middle ground:
- `require.NoError(t, err)` for setup that must succeed (it stops the test — `assert`
  continues and you get a confusing cascade of nil-pointer failures).
- Plain `if got != want` for the actual assertion.
- `go-cmp` for structs and slices.

```go
if diff := cmp.Diff(want, got); diff != "" {
    t.Errorf("mismatch (-want +got):\n%s", diff)
}
```

`cmp.Diff` output is far more useful than "not equal" on a large struct. Use
`cmpopts.IgnoreFields` for generated IDs and timestamps rather than zeroing them by hand.

## Fakes over mocks

Go interfaces are small, so a hand-written fake is usually less work than generated mock
setup and produces clearer tests.

```go
type fakeUserRepo struct {
    users map[string]*User
    err   error            // inject a failure when you need one
}

func (f *fakeUserRepo) GetUser(_ context.Context, id string) (*User, error) {
    if f.err != nil {
        return nil, f.err
    }
    u, ok := f.users[id]
    if !ok {
        return nil, ErrNotFound
    }
    return u, nil
}
```

Reach for `gomock`/`mockery`/`moq` when an interface is wide, or when you genuinely need
to assert call ordering. **Define the interface in the consuming package**, not next to
the implementation — that's what keeps fakes small and honest.

## HTTP handlers with `httptest`

```go
func TestGetUserHandler(t *testing.T) {
    repo := &fakeUserRepo{users: map[string]*User{"u1": {ID: "u1", Email: "a@example.com"}}}
    mux := newRouter(repo)

    req := httptest.NewRequest(http.MethodGet, "/users/u1", nil)
    rec := httptest.NewRecorder()

    mux.ServeHTTP(rec, req)               // no network, no port, no flakiness

    if rec.Code != http.StatusOK {
        t.Fatalf("status = %d, want 200; body: %s", rec.Code, rec.Body.String())
    }
    var got User
    if err := json.NewDecoder(rec.Body).Decode(&got); err != nil {
        t.Fatalf("decode: %v", err)
    }
    if got.Email != "a@example.com" {
        t.Errorf("email = %q", got.Email)
    }
}
```

Test through the **router**, not the bare handler function — that way middleware,
path-parameter extraction and error mapping are covered too. Always include the response
body in status-mismatch failures; otherwise you get "status = 500, want 200" and no clue
why.

For outbound calls, `httptest.NewServer` gives you a real server whose URL you inject:

```go
srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
    w.WriteHeader(http.StatusServiceUnavailable)   // exercise the failure path
}))
defer srv.Close()

client := NewUserClient(srv.URL, srv.Client())
```

**Test your timeouts and retries by injecting delays and faults.** A timeout you never
exercised is a guess:

```go
srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
    time.Sleep(2 * time.Second)      // longer than the client's timeout
    w.WriteHeader(http.StatusOK)
}))
// assert the client returns a timeout error promptly, not after 2s
```

## `testing/synctest` — deterministic concurrency tests (1.25+)

Stable since Go 1.25. It runs a bubble of goroutines on a **fake clock** that jumps
forward when every goroutine is blocked. Timeout and retry logic becomes testable in
microseconds instead of real seconds.

```go
func TestRetryBackoff(t *testing.T) {
    synctest.Test(t, func(t *testing.T) {
        var attempts int
        err := withRetry(context.Background(), 3, func(ctx context.Context) error {
            attempts++
            return errTransient
        })
        // No real sleeping happened — the fake clock advanced instantly.
        if attempts != 3 {
            t.Errorf("attempts = %d, want 3", attempts)
        }
        if !errors.Is(err, errTransient) {
            t.Errorf("err = %v", err)
        }
    })
}
```

This replaces the old choice between slow tests (real sleeps) and untestable code
(injected clock interfaces everywhere). Use it for anything involving timeouts, retries,
tickers or backoff. Verify the exact API against your Go version's docs — it moved between
1.24 (experimental) and 1.25 (stable).

## Integration tests with testcontainers-go

Real dependencies find real bugs — dialect differences, constraint behaviour,
acknowledgement semantics — that a fake cannot.

```go
func setupPostgres(t *testing.T) *pgxpool.Pool {
    t.Helper()
    ctx := context.Background()

    container, err := postgres.Run(ctx, "postgres:17-alpine",
        postgres.WithDatabase("test"),
        postgres.WithUsername("test"),
        postgres.WithPassword("test"),
        testcontainers.WithWaitStrategy(
            wait.ForLog("database system is ready to accept connections").
                WithOccurrence(2).WithStartupTimeout(30*time.Second)),
    )
    if err != nil {
        t.Fatalf("start postgres: %v", err)
    }
    // t.Cleanup runs even if the test panics or fails early.
    t.Cleanup(func() { _ = container.Terminate(ctx) })

    dsn, err := container.ConnectionString(ctx, "sslmode=disable")
    if err != nil {
        t.Fatalf("connection string: %v", err)
    }
    pool, err := pgxpool.New(ctx, dsn)
    if err != nil {
        t.Fatalf("pool: %v", err)
    }
    t.Cleanup(pool.Close)

    runMigrations(t, dsn)      // the SAME migrations as production
    return pool
}
```

- **Run your real migrations**, not a hand-written test schema — otherwise the tests pass
  against a schema production doesn't have.
- **Share one container across a package** (`TestMain` + a package-level pool) and isolate
  per test with a transaction rollback or truncation. Starting a container per test makes a
  suite unbearably slow.
- Gate them behind `-short` so `go test -short ./...` stays fast:

```go
if testing.Short() {
    t.Skip("skipping integration test")
}
```

## Goroutine leaks

```go
func TestMain(m *testing.M) {
    goleak.VerifyTestMain(m)
}
```

Fails the suite if goroutines outlive it. Catches the classic leak: a goroutine blocked
forever on a channel that's never closed or a context never cancelled. Add
`goleak.IgnoreTopFunction(...)` for known-benign background goroutines from
dependencies — but investigate before ignoring.

## The race detector is not optional

```sh
go test -race -count=1 ./...
```

`-race` only finds races on code paths actually executed, so run it over the whole suite in
CI. `-count=1` defeats Go's test result caching when you want a genuine re-run. **A
detected race is a bug, not a flake** — do not retry it away.

## Fuzzing

```go
func FuzzParseConfig(f *testing.F) {
    f.Add([]byte(`{"port": 8080}`))          // seed corpus
    f.Fuzz(func(t *testing.T, data []byte) {
        // The property: never panic, whatever the input.
        _, _ = ParseConfig(data)
    })
}
```

```sh
go test -fuzz=FuzzParseConfig -fuzztime=60s ./internal/config
```

High value for parsers, decoders, and anything touching untrusted input. Failing inputs are
written to `testdata/fuzz/` and become permanent regression tests.

## Benchmarks

```go
func BenchmarkSerialize(b *testing.B) {
    payload := makePayload()
    b.ReportAllocs()
    for b.Loop() {                  // Go 1.24+: correct loop, no b.N arithmetic
        _, _ = json.Marshal(payload)
    }
}
```

`b.Loop()` (1.24+) is the current idiom — it prevents the compiler from optimising the
work away and removes the old `for i := 0; i < b.N; i++` boilerplate. Always
`b.ReportAllocs()`; allocation count is usually the more actionable number.

```sh
go test -bench=. -benchmem -count=10 ./... > new.txt
benchstat old.txt new.txt          # compare with statistical confidence
```

A single benchmark run is noise. `benchstat` over `-count=10` tells you whether a change
is real.

## Structuring for testability

- **Constructor injection.** `NewService(repo Repo, clock Clock)` is testable; a package
  global reaching for a database is not.
- **Interfaces defined by the consumer**, narrow — one or two methods. A wide interface
  forces a wide fake.
- **No `init()` side effects.** They run before tests can configure anything.
- **Inject the clock** if you're not on `synctest`: `type Clock interface { Now() time.Time }`.
- **`t.Helper()`** in every helper, so failures report the caller's line, not the helper's.
- **`t.Cleanup`** over `defer` in helpers — it runs after the test even if the helper
  returned long before.
- **`t.Setenv`** for env vars — it restores the old value and blocks `t.Parallel()`
  automatically (env is process-global, so parallelism would be a race).

## What not to test

- Getters, setters, and struct literals.
- The standard library or your dependencies.
- Mock-to-mock interactions that assert only that your mocks were called.
- Exact log strings (brittle; assert on behaviour, or on structured fields if it matters).

Coverage is a useful **floor** and a terrible **target** — 100% coverage of trivial code
while the retry path is untested is worse than 70% with the failure paths covered.

## Checklist

- [ ] Table-driven tests with `t.Run` subtests and `t.Parallel()` where safe
- [ ] `errors.Is`/`errors.As`, never string comparison
- [ ] `cmp.Diff` for structs; response body included in HTTP failure messages
- [ ] Handlers tested through the router so middleware is covered
- [ ] Timeouts and retries tested with injected delays/faults
- [ ] `testing/synctest` for time-dependent logic (1.25+)
- [ ] Integration tests use testcontainers + the real migrations
- [ ] One container per package, isolation per test; gated behind `-short`
- [ ] `goleak.VerifyTestMain` enabled
- [ ] `go test -race -count=1 ./...` in CI
- [ ] Fuzz targets for parsers and untrusted input
- [ ] `b.Loop()` + `b.ReportAllocs()`; `benchstat` over `-count=10`
- [ ] `t.Helper()`, `t.Cleanup`, `t.Setenv` used correctly
