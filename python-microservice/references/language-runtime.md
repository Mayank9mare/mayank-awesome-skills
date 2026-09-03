# Python language & runtime for services

Verified 2026-08. Current: **Python 3.14**. Free-threading is **officially
supported** (not experimental) in 3.14 via PEP 779 — but is **not** the default
build.

## Version cheat sheet

| Ver | Change | Why it matters for a service |
|---|---|---|
| 3.15 (Oct 2026 target) | **PEP 810 explicit lazy imports** — `lazy import json`, `lazy from pathlib import Path` | Startup-time and memory win for heavy import graphs. **NOT in 3.14** — first appeared in 3.15.0a7. Tooling (mypy/ruff/isort) still catching up. |
| **3.14** (Oct 2025) | **Free-threading officially SUPPORTED** (PEP 779, Phase II) — separate build, `python3.14t` | See below. Supported ≠ default ≠ always faster. |
| 3.14 | **PEP 649/749: deferred annotation evaluation — SHIPPED** | Annotations computed lazily on first access, not at def time. Forward refs work unquoted. `from __future__ import annotations` now largely unnecessary. New `annotationlib` module. **See the breakage note below.** |
| 3.14 | **PEP 750 t-strings — SHIPPED** | `Template` with `.strings`/`.interpolations` instead of an eagerly-concatenated `str`. Enables safe-by-construction SQL/HTML/shell escaping — the "sanitise before interpolation" pattern f-strings cannot express. |
| 3.14 | PEP 734 multiple interpreters | Subinterpreters get a public API. See below. |
| 3.13 | Free-threaded build (experimental), JIT (experimental), new REPL | 3.13t was the trial run; 3.14t is the supported one. |
| 3.12 | PEP 695 type-param syntax; PEP 684 per-interpreter GIL; f-string grammar (PEP 701) | `def f[T](x: T) -> T` and `type Alias = ...`. Per-interpreter GIL underpins subinterpreters. |
| 3.11 | ~10–60% faster; `TaskGroup`, `ExceptionGroup`/`except*`; `tomllib`; `Self` | **`asyncio.TaskGroup` is the modern replacement for `gather`.** Big free perf win — 3.11 is the practical floor for new services. |

**Floor recommendation:** target 3.12+ for new services; 3.11 is the minimum worth
starting on. Pin the minor version in your image — don't float.

### PEP 649 runtime-introspection breakage (bites frameworks, not type checkers)

Static checkers never evaluated annotations, so mypy/pyright are unaffected. Tools
that introspect annotations **at runtime** — which includes web frameworks reading
endpoint signatures — needed updating.

Concretely: FastAPI required 0.128.1+ to use `annotationlib.Format.FORWARDREF` when
inspecting endpoint signatures. On older FastAPI running on 3.14, **any endpoint
whose signature references a `TYPE_CHECKING`-only import is broken**. If you move a
service to 3.14, upgrade the framework in the same change and test signature-heavy
endpoints.

`from __future__ import annotations` still works on 3.14 (it switches that module
back to PEP 563 string annotations) and CPython has committed to keeping it at
least until 3.13 goes EOL in Oct 2029 — so there's no urgency to strip it, but no
reason to add it in new 3.14+ code either.

## Free-threading (no-GIL): the honest assessment

PEP 703 laid out three phases. PEP 779 (accepted 2025-06-16) moved free-threading
from *experimental* to *officially supported* in **3.14** — Phase II. Phase III
(free-threaded becomes the default, GIL build retired) has **no committed version**
and depends on ecosystem adoption. Don't plan around it.

```sh
python3.14t            # the free-threaded binary — note the `t` suffix
```

```python
import sys
# ALWAYS check this at startup if you believe you're running free-threaded.
print(sys._is_gil_enabled())   # False == actually free-threaded
```

### The footgun that will bite you

Importing a C extension that has **not** declared itself thread-safe causes CPython
to **silently re-enable the GIL for the entire process**. Your threads keep
running — they just stop running in parallel. No error, no warning in normal
operation. You think you're scaling on cores and you aren't.

So: assert `sys._is_gil_enabled() is False` at boot in any service that depends on
free-threading, and log it. Don't infer it from the binary name.

### Cost and benefit

- Single-thread performance penalty is **~5–10%** on 3.14 (PEP 779 capped the
  acceptable regression at 15%; the gap closed from 3.13's worse showing).
- Memory overhead capped around **20%** above GIL builds.
- The specializing interpreter is **re-enabled** in 3.14t (it was disabled in 3.13t),
  which is where much of that improvement came from.
- C extensions need recompiling against the new ABI. Pure Python benefits immediately.

### The decision rule for a web service

**For a typical I/O-bound ASGI service, free-threading is usually NOT the win.**
Process-per-core plus `asyncio` already uses all your cores, has a decade of
library support, and gives you crash isolation between workers. Free-threading buys
you nothing there and costs you 5–10% single-thread throughput plus ecosystem risk.

Free-threading *is* interesting when:
- You have genuinely CPU-bound work in-process that you currently push to
  `ProcessPoolExecutor`, and the IPC serialisation cost dominates.
- You need a large shared in-memory data structure that's painful to replicate
  per-process (a big cache, a loaded model).
- You're memory-constrained and per-process interpreter overhead × N workers is the
  problem.

Otherwise: multiple processes, one event loop each.

## The concurrency decision, made simple

| Workload | Use | Why |
|---|---|---|
| I/O-bound (HTTP, DB, queues) | **`asyncio`** on one process per core | Thousands of concurrent waits, one thread, no GIL contention. The default for services. |
| I/O-bound but the library is sync-only | Threads (`asyncio.to_thread`, `ThreadPoolExecutor`) | GIL is released during I/O syscalls, so threads genuinely overlap. |
| CPU-bound | `ProcessPoolExecutor`, or a separate worker service | Sidesteps the GIL entirely. Also consider pushing the work to a native library (NumPy/Polars) that releases the GIL. |
| CPU-bound + huge shared state | Free-threaded build, measured | Only after proving IPC cost is the bottleneck. |
| Mixed / long jobs | A task queue (Celery/arq/Dramatiq) | Get it out of the request path. See messaging.md. |

The GIL blocks **bytecode execution**, not I/O. A thread waiting on a socket has
released it. This is why threads work fine for I/O and never for CPU.

## asyncio: the patterns that matter

### TaskGroup over gather

```python
import asyncio

# MODERN (3.11+). Structured: if one child fails, siblings are cancelled and
# the exception propagates as an ExceptionGroup. Nothing is orphaned.
async def fetch_all(ids: list[str]) -> list[Result]:
    results: dict[str, Result] = {}
    async with asyncio.TaskGroup() as tg:
        for i in ids:
            tg.create_task(fetch_one(i, results))
    return [results[i] for i in ids]

# Handle partial failure explicitly:
try:
    await fetch_all(ids)
except* TimeoutError as eg:
    log.warning("timeouts: %d", len(eg.exceptions))
except* ValueError as eg:
    ...
```

`asyncio.gather(*tasks)` is legacy for new code. Its defaults are hostile: on
exception, the other tasks keep running unsupervised; with
`return_exceptions=True`, failures silently become return values you must remember
to inspect. `TaskGroup` makes the correct behaviour the default.

### Timeouts

```python
async with asyncio.timeout(5):        # 3.11+, the readable form
    await something()

# also: asyncio.timeout_at(loop.time() + 5)
```

Note this cancels the inner task — it does **not** magically make a blocking call
return. A `time.sleep()` inside will not be interrupted.

### The fire-and-forget bug

```python
# BROKEN: the event loop keeps only a weak reference. The task can be
# garbage-collected mid-flight and simply never finish. Silent, intermittent.
asyncio.create_task(background_work())

# CORRECT: hold a strong reference until it completes.
_background: set[asyncio.Task] = set()

def spawn(coro) -> None:
    t = asyncio.create_task(coro)
    _background.add(t)
    t.add_done_callback(_background.discard)
```

Better still: don't fire-and-forget in a request handler. Use a task queue, or a
`TaskGroup` owned by the application lifespan.

### Cancellation discipline

`CancelledError` inherits from `BaseException` (since 3.8), so `except Exception`
won't swallow it — good. But never catch it and continue:

```python
try:
    await work()
except asyncio.CancelledError:
    await cleanup()          # do your cleanup
    raise                    # then ALWAYS re-raise. Swallowing breaks shutdown.
```

Use `finally` for cleanup and `asyncio.shield()` only when an operation genuinely
must not be interrupted (rare — and it doesn't protect the caller from being
cancelled).

### Blocking in async — the cardinal sin

One blocking call in an `async def` stalls **every** concurrent request on that
worker, because they all share one thread.

```python
@app.get("/bad")
async def bad():
    time.sleep(1)                    # blocks the whole event loop
    return requests.get(url).json()  # so does this: `requests` is sync

@app.get("/good")
async def good():
    await asyncio.sleep(1)
    async with httpx.AsyncClient() as c:      # see http-clients.md re: reuse
        return (await c.get(url)).json()

# Sync-only library you can't replace:
result = await asyncio.to_thread(legacy_blocking_call, arg)
```

Common offenders: `requests`, `time.sleep`, sync DB drivers (`psycopg2`), `open()`
on slow storage, `subprocess.run`, CPU-heavy loops, and sync `boto3`.

Detect it:
- Run with `PYTHONASYNCIODEBUG=1` — logs callbacks that take too long.
- `loop.set_debug(True)` plus `loop.slow_callback_duration = 0.1`.
- The `blockbuster` library fails tests when a blocking call happens in a coroutine.

**In FastAPI specifically:** a `def` (non-async) endpoint runs in a threadpool and
is *safe* for blocking code; an `async def` endpoint is not. If your handler is
sync-blocking, declaring it `def` is correct — don't add `async` for decoration.

### uvloop

Drop-in faster event loop (2–4× on some benchmarks). `uvicorn --loop uvloop`.
Not available on Windows. Low-risk, free.

## Typing that earns its keep

```python
# PEP 695 (3.12+): compact generics
def first[T](xs: list[T]) -> T | None:
    return xs[0] if xs else None

type UserId = str          # a real type alias, not a variable

# Protocol: structural typing. Depend on shape, not inheritance —
# this is how you keep layers decoupled without ABCs.
from typing import Protocol

class UserRepo(Protocol):
    async def get(self, uid: UserId) -> User | None: ...

# Annotated: attach metadata (validation, DI) to a type
from typing import Annotated
Port = Annotated[int, Field(ge=1, le=65535)]
```

Run a type checker in CI. `mypy --strict` or pyright in strict mode; adopt
incrementally with per-module overrides rather than a repo-wide `ignore_errors`.
The highest-value settings if you can't do full strict:
`disallow_untyped_defs`, `warn_return_any`, `no_implicit_optional`,
`warn_unused_ignores`.

## Memory & performance

- **`__slots__`** on hot, numerous classes removes the per-instance `__dict__` —
  meaningful memory win for millions of objects.
- Model-class cost, roughly: `msgspec` < `dataclass`/`attrs` < Pydantic v2
  (Rust core) << Pydantic v1. Validate at the edges with Pydantic; use plain
  dataclasses or `msgspec.Struct` for internal hot-path structures.
- **`gc.freeze()` before forking** — with a pre-fork server (gunicorn `--preload`),
  call `gc.freeze()` after imports so the parent's objects move out of GC's view
  and stay shared copy-on-write instead of being dirtied by the first collection.
  Real RSS savings across many workers.
- Generational GC tuning (`gc.set_threshold`) is rarely worth it; measure first.
- Profiling: **py-spy** (sampling, attaches to a running process, no code change —
  the first tool to reach for in production), **memray** for allocations,
  `tracemalloc` for a quick in-process snapshot.

```sh
py-spy top --pid 1              # what's hot, right now, in prod
py-spy dump --pid 1             # stack of every thread — great for "why is it stuck"
```

## The JIT

Copy-and-patch JIT (PEP 744), introduced experimental in 3.13 and still experimental in
3.14. **It is OFF by default.** Opt in with the `PYTHON_JIT=1` environment variable, or a
build compiled with `--enable-experimental-jit`. Present in the official
Windows/macOS binaries, still labelled experimental.

Some later blog posts claim a 3.14 point release turned it on by default. **Treat that as
unverified** — it contradicts the official experimental/opt-in framing, and no CPython
release note confirms the flip. Check `sysconfig` on your actual build rather than
believing either claim.

Reported gains cluster around 10–30% on CPU-bound hot paths *after warmup* and
approximately nothing for I/O-bound service work — which is most service work. Those are
benchmark-blog figures, not CPython-official. **Don't plan capacity around it.**

JIT + free-threading together: sources disagree on whether they're mutually exclusive or
merely un-co-optimised (one reports ~8–12% added per-thread overhead when combined).
Treat the combination as an open question, not a strategy.

## Interpreter-level parallelism alternatives

- **Subinterpreters** — PEP 684 gave each interpreter its own GIL (3.12), and
  **PEP 734 shipped the public API in 3.14**, with
  `concurrent.futures.InterpreterPoolExecutor` as the high-level entry point.
  Isolated interpreters in one process, each with its own GIL: lighter than
  processes, better isolated than threads. C-extension support and library
  ecosystem are still thin — treat as emerging, not a default.
- Multiple OS processes remain the boring, correct answer for CPU parallelism.

## Anti-patterns to refuse

```python
# Mutable default argument — shared across ALL calls, forever.
def add(x, items=[]):        # WRONG
def add(x, items=None):      # right
    items = [] if items is None else items

# Bare/broad except — swallows KeyboardInterrupt, SystemExit, and your bugs.
try: ...
except:              # WRONG
except Exception:    # acceptable at a boundary, if you log and re-raise or handle
except ValueError:   # better: name what you expect

# Sync I/O in async — see above.

# Module-level side effects (DB connect, network call at import time) — breaks
# testing, breaks fork, breaks `--preload`. Use a lifespan/startup hook.

# logging.basicConfig() inside a library or module — hijacks the application's
# logging config. Configure logging once, in the entrypoint. See observability.md.
```
