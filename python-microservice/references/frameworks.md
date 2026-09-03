# Python web/service frameworks

Verified 2026-08. Versions come from the **PyPI JSON API** — registry facts, not blog
claims. Anything that could not be confirmed says so in place rather than being guessed.

## Comparison

| Framework | Version | Sync/async | DI | Validation | OpenAPI | Perf | Best fit |
|---|---|---|---|---|---|---|---|
Versions below are from the **PyPI JSON API as of 2026-08-01** — registry facts.

| Framework | Version | Sync/async | DI | Validation | OpenAPI | Perf | Best fit |
|---|---|---|---|---|---|---|---|
| **FastAPI** | **0.141.1** (**0.128.1+ required on Py 3.14**) | async-first, sync supported | `Annotated[X, Depends(f)]` | Pydantic v2 | Built-in | High | **Default** for new async APIs. Biggest ecosystem. |
| **Litestar** | **2.24.0** | async-first | Layered: app/router/controller/handler | msgspec (default) or Pydantic | Built-in | High (msgspec > Pydantic on hot paths) | Stricter architecture + faster serialisation. |
| **Django + DRF** | **Django 6.0.7** · **DRF 3.17.1** | sync-first, partial async | Django apps/settings + DRF serializers | DRF serializers | Add-on (drf-spectacular) | Medium–high | Admin, migrations, content-heavy apps. |
| **django-ninja** | **1.6.2** | async views | FastAPI-style `Annotated` | Pydantic v2 | Built-in | High at API layer | Django ORM/admin **+** FastAPI-shaped endpoints. |
| **Flask** | **3.1.3** | sync-first (WSGI) | Extensions | Manual/Marshmallow | Add-on | Medium | Small services, prototypes, maturity. |
| **Starlette** | **1.3.1** | async (raw ASGI) | None | None | None | High | Custom framework; ASGI primitives without opinions. |
| **Sanic** | **25.12.1** | async-first | Minimal | Manual | Add-on | High | Flask-like feel, native async speed. |
| **Quart** | **0.21.0** (2026-07 — **actively maintained**) | async (Flask-API-compatible) | Flask-style | Manual | Add-on | Med–high | Migrating Flask to real async. |
| **Falcon** | **4.3.1** | sync + async | Minimal, resource classes | Manual | None | High | Minimalism, max throughput per line. |
| **BlackSheep** | **2.6.3** | async | **Built-in DI container** | Pydantic/binders | Built-in | High | FastAPI-like DX, container-based DI. |
| **Robyn** | **0.88.0** | async (Rust core) | Minimal | Manual | None | Highest dispatch | Only when routing overhead is the real bottleneck. |
| **Tornado** | **6.5.7** (Gunicorn requires 6.5+ for CVE-2025-47287) | async (pre-asyncio design) | Minimal | Manual | None | Med–high | Long-lived connections; legacy codebases. |
| Bottle | **0.13.4** (2025-06) | sync | None | Manual | None | Low | Still released, but a single-file micro-framework with no async story. Fine for a tiny internal tool; not a service framework. |

## FastAPI

### Version floor on Python 3.14 — a real breakage

**FastAPI 0.128.1+ is required on Python 3.14.** PEP 649/749 made annotations lazily
evaluated, and FastAPI now inspects endpoint signatures via
`annotationlib.Format.FORWARDREF`. On older FastAPI, **any endpoint whose signature
references a `TYPE_CHECKING`-only import breaks**, because those names aren't
resolvable when the old code eagerly evaluates annotations. Upgrade the framework in
the same change as the interpreter.

### `Annotated` dependencies — the current idiom

```python
from typing import Annotated
from fastapi import Depends

# Define once, reuse everywhere.
DbDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]

@app.get("/items")
async def list_items(db: DbDep, user: CurrentUser) -> list[ItemOut]:
    ...
```

```python
# LEGACY style — still works, avoid in new code
async def list_items(db: AsyncSession = Depends(get_session)): ...
```

Why `Annotated` won: the old form overloads the parameter's **default value** to carry
DI metadata. That breaks tools reasoning about "does this parameter have a real
default" (mypy, IDEs), and it doesn't compose — you can't reuse `Depends(get_db)` as a
named alias without repeating the call. `Annotated[X, Depends(f)]` separates type from
injection metadata, is standard PEP 593 typing, stays mypy/pyright-clean (the outer
type is just `X`), and lets one alias serve the whole codebase.

### Lifespan — `on_event` is deprecated

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient(timeout=TIMEOUT)
    app.state.engine = create_async_engine(settings.database_url)
    try:
        yield                                  # app serves here
    finally:
        await app.state.http.aclose()          # cleanup runs even on error
        await app.state.engine.dispose()

app = FastAPI(lifespan=lifespan)
```

`@app.on_event("startup")` / `("shutdown")` are **DEPRECATED**. Beyond deprecation, the
lifespan generator is strictly better: startup and shutdown share one local scope (so
you can close exactly what you opened), and multiple lifespans compose via
`contextlib.AsyncExitStack` — `on_event` handlers can do neither.

### Routers, response models, status codes

```python
from fastapi import APIRouter, status

router = APIRouter(prefix="/items", tags=["items"])

@router.get("/{item_id}",
            response_model=ItemOut,
            response_model_exclude_none=True,
            status_code=status.HTTP_200_OK)
async def read_item(item_id: int, db: DbDep): ...

app.include_router(router)
```

`response_model` validates and filters the **outgoing** payload independently of the
return annotation — so you can return an ORM object and serialise only the declared
fields. That's also your defence against accidentally leaking a `password_hash`
column.

### `BackgroundTasks` — know the limits

```python
@app.post("/notify")
async def notify(tasks: BackgroundTasks):
    tasks.add_task(send_email, "user@example.com")
    return {"status": "queued"}
```

It runs **in-process, after the response, on the same worker**. Therefore:

- **Dies with the worker.** Crash, restart, deploy, OOM kill, `--max-requests`
  recycling — the task is simply gone. No persistence.
- **No retry**, no backoff, no dead-letter.
- **No cross-worker visibility.** With N workers there's no shared queue; the task
  runs wherever the request landed, and you can't inspect or cancel it.
- **Still consumes that worker's capacity** — deferred, not free.

Use it only for short, best-effort work where occasional loss is acceptable (an
analytics ping, a cache warm). Anything that must survive a deploy, needs retries, or
needs to be observable belongs in a task queue. See messaging.md.

### Error envelope

```python
class AppError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code, self.message, self.status_code = code, message, status_code

@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(status_code=exc.status_code,
                        content={"error": {"code": exc.code, "message": exc.message}})
```

Override FastAPI's `RequestValidationError` and `HTTPException` handlers too, or you
get a mix of your envelope and two framework-default shapes.

### Middleware vs dependencies

|  | Middleware | Dependencies |
|---|---|---|
| Runs | **Before routing**, around everything | **After routing**, per-endpoint |
| Knows the endpoint? | No — no path params, no matched route | Yes |
| Works on | Raw `Request`/`Response` | Typed request/response cycle |
| Errors | Hand-built `JSONResponse`; **no typed validation** tying it to your error schema | Raise → your `@app.exception_handler` → typed envelope free |
| Caching | n/a | Same dependency in one request tree resolves once |
| Use for | Request IDs, timing, CORS, gzip — uniform across all routes | Auth **and authorization** (needs the resource), DB sessions, route-specific validation |

That's the practical reason to prefer dependencies for anything route-aware: you get
the consistent error envelope for free.

### The performance mistakes that actually happen

1. **`async def` with blocking code inside.** Blocks the event loop for every
   concurrent request on that worker. A plain `def` endpoint runs in FastAPI's
   threadpool and is the *correct* choice for sync/blocking code. Don't add `async`
   as decoration.
2. **Creating an `httpx.AsyncClient` per request** — throws away connection pooling;
   TLS handshake on every call. Create once in lifespan. See http-clients.md.
3. **Sync DB driver (`psycopg2`) in an `async def`** — same event-loop block as #1,
   easy to miss because it still "works", just serialises everything.
4. **Unbounded Pydantic validation on huge payloads** — deeply nested or large-array
   bodies can dominate request latency. Always set a body size limit. The Rust core made
   *validation* much faster in v2, but **model construction can still be slower than v1**
   for deeply nested graphs — the cost has moved, not vanished. See below for what
   actually helps.

### Making Pydantic fast on big payloads

The Rust core's advantage only materialises if you let it do the work. In rough order of
leverage:

1. **Use `TypedDict` (or a plain dataclass) for nested leaf models** — the single biggest
   win, roughly **2.5× faster** than nested `BaseModel` in Pydantic's own benchmark. Every
   `BaseModel` subclass builds its own validator and serializer **at class-creation time**,
   even when it's only ever used *inside* another model and its own validator is never
   invoked. That cost is pure waste for leaf types.
2. **Prefer `Model.model_validate_json(raw)` over `json.loads()` + `model_validate()`** —
   the fused path keeps parsing in Rust instead of materialising Python objects in between.
   One 50k-item benchmark showed ~2× and more when the schema is complex.
3. **Instantiate `TypeAdapter` once and reuse it.** Creating one inside a function rebuilds
   the validator and serializer on **every call**.
4. **Avoid wrap validators** on hot paths — they force data to be materialised in Python
   mid-validation, defeating the point.
5. **`FailFast`** (v2.8+) on sequence types bails on the first bad item instead of
   validating a 10,000-element list to completion just to reject it.
6. Avoid giant non-discriminated unions (use a discriminator), `mode="before"` validators
   doing work the core already does, and **any I/O inside a validator**.

**Do not reach for `model_construct()` as an optimisation.** In v2 the gap versus
`__init__` has narrowed to the point that **`__init__` is sometimes faster** for simple
models — and `model_construct` performs *no validation at all*, so it will happily build an
invalid model. Its legitimate uses are: data already validated upstream, non-idempotent
validators, or validators with side effects you need to skip. Profile before assuming it
wins.

## Litestar

DI is **layered** — dependencies declare at app, router, controller, or handler level,
with lower layers overriding higher. That gives an explicit, inspectable scope rather
than FastAPI's flatter per-endpoint graph. Controllers group related handlers with
shared dependencies, guards, and middleware declared once.

**DTOs** are first-class for controlling in/out shapes decoupled from ORM/domain
models — like `response_model` but generalised to both directions and to arbitrary
backing types.

**msgspec** is the default serialisation backend (Pydantic supported too). It's a
C-extension built for speed and generally beats Pydantic v2 on validation hot paths,
at the cost of a smaller validator feature surface.

The **SQLAlchemy plugin** is a genuine differentiator: session-per-request, repository
patterns, and DTO generation from SQLAlchemy models with much less boilerplate than
wiring the equivalent by hand in FastAPI.

**Honest trade-off:** smaller ecosystem and community than FastAPI. You're buying
structure and speed; you're paying in the long tail of FastAPI-specific integrations
and answers.

## Django + DRF + django-ninja

**Where Django wins:** the ORM plus its migration system plus the auto-generated admin
is a fundamentally different offer from "validation and serialisation". Schema
evolution and an internal CRUD UI essentially for free has no free equivalent in
FastAPI/Litestar/Flask.

**Async Django, honestly.** Async views work. Django 6.0 continues landing async ORM
APIs incrementally. What still bites:

- Calling sync-only ORM code from an async view raises `SynchronousOnlyOperation` —
  wrap in `sync_to_async()`.
- **The middleware sandwich**: if *any* middleware in the chain is sync-only, Django
  bridges sync↔async with a thread-sensitive context, with measurable overhead. A
  fully-async request path only pays off if the **entire** chain — middleware, view,
  and ORM calls — is async-native.
- **Async transactions are still unsupported in Django 6.0.** There is no `aatomic()`.
  `transaction.atomic()` is sync-only, so **everything inside the block must be
  synchronous** — which also means `select_for_update` row locking and
  `transaction.on_commit` (the correct way to enqueue a Celery task after commit) are
  unavailable from async code. Ticket **#33882** is accepted and assigned but has no
  patch; the maintainers noted it needs more than `sync_to_async` wrappers.

  The circulating workaround — subclassing `Atomic` and wrapping `__enter__`/`__exit__`
  in `sync_to_async(thread_sensitive=True)` — is **reported to fail under high load**, and
  it forces the transaction body to be sync anyway, so async helpers can't be reused
  inside it. Don't build on it.

  **The practical structure**: keep the request handler async, do your reads async, then
  group all writes into one small `sync_to_async`-wrapped sync function at the end. Only
  that block is synchronous.

  Upgrade note: teams moving 5.x → 6.0 report that mixing sync and async calls — which
  Django 5 tolerated by silently running them synchronously — now surfaces as real
  sync-blocking errors. Budget time for that when upgrading an async Django service.

**django-ninja** is the pragmatic middle: keep Django's ORM/admin/migrations, get
FastAPI-shaped typed endpoints instead of DRF serializers/viewsets. Includes
`Annotated` params, async authenticators, `CursorPagination` (keyset), and streaming
responses (JSONL/SSE).

## Flask & Starlette

### Flask

```python
def create_app(config_object=None):
    app = Flask(__name__)
    app.config.from_object(config_object or "config.Default")
    from .views import bp
    app.register_blueprint(bp, url_prefix="/api")
    return app
```

The **app factory** (rather than a module-level `app = Flask(__name__)`) exists so you
can build differently-configured instances — essential for testing, and it avoids the
import-order circular-dependency knots a module-level singleton creates as a codebase
grows. **Blueprints** are Flask's route-splitting unit, analogous to `APIRouter`.

**The async caveat that matters:** Flask supports `async def` views, but Flask is
**WSGI**, not ASGI. An async view is run by spinning up an event loop per call inside a
sync worker — you do **not** get one-loop-serves-many-concurrent-requests behaviour.
It's useful for calling async libraries from sync Flask code; it is **not** a path to
ASGI throughput. If you need that, move to Quart (Flask-compatible API, ASGI-native)
rather than bolting `async def` onto WSGI Flask.

### Starlette

The raw ASGI toolkit under FastAPI — routing, middleware, requests/responses,
WebSockets, test client — without Pydantic validation or OpenAPI generation.
**Reached 1.0.0 stable in March 2026; currently 1.3.1** (PyPI, 2026-06). Now that it's
past 1.0, semver applies — a reason to be more comfortable depending on it directly than
in its long 0.x era.

```python
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.responses import JSONResponse

async def homepage(request):
    return JSONResponse({"hello": "world"})

app = Starlette(routes=[Route("/", homepage)])
```

Use it directly for a custom framework layer, tight middleware control, websocket-heavy
services, or an internal proxy where Pydantic/OpenAPI machinery is pure overhead.

## The rest, briefly

**Sanic** — async-first, Flask-shaped, historically uvloop-based speed focus. Still in
2026 ASGI compatibility matrices.

**Quart** — Flask-API-compatible and genuinely ASGI-native; the natural migration target
from Flask. Some 2023-era sources called it under-maintained; that's **out of date** —
0.21.0 shipped July 2026 (PyPI). It's a reasonable choice when you want Flask's API shape
with real async concurrency rather than Flask's WSGI-with-async-views compromise.

**Falcon** — deliberately minimal, WSGI and ASGI modes, resource-class routing. Max
throughput per line of framework code; you hand-roll more convenience.

**BlackSheep** — async, **built-in DI container**, first-class OpenAPI. FastAPI-like DX
with container-based registration instead of a `Depends()` graph.

**Robyn** — Rust core via PyO3. Ahead on raw routing throughput, but the gap narrows to
roughly **10%** on typical DB-bound CRUD, because the database round-trip dominates.
Choose it only when dispatch overhead is genuinely your bottleneck — it rarely is.

**Tornado** — predates asyncio-native design. Still a first-class Gunicorn worker class
(`eventlet` was dropped in favour of `gevent`/`gthread`/`tornado`), and Gunicorn now
requires **Tornado 6.5+** for the CVE-2025-47287 (request smuggling) fix. Good for
long-lived connections; not a common new-API choice.

**Granian** — **not a framework**: a Rust server (Hyper + Tokio) serving ASGI, WSGI, or
its own RSGI. See servers below.

## Servers & deployment

```sh
uvicorn app:app --workers 4 --loop uvloop --http httptools
```

- `--loop uvloop` — libuv-based loop, materially faster for I/O.
- `--http httptools` — C parser instead of pure-Python h11.

**`uvicorn.workers` is DEPRECATED.** The Gunicorn worker class moved to a separate
package:

```python
# OLD: gunicorn -k uvicorn.workers.UvicornWorker app:app
# NEW: pip install uvicorn-worker
from uvicorn_worker import UvicornWorker
```

### Gunicorn or plain uvicorn? Decide by deployment target

The 2026 answer is not "one is better" — it's that the right choice follows from where
you deploy:

| Target | Use | Why |
|---|---|---|
| **Kubernetes / ECS / Cloud Run** | **plain uvicorn, one process per container** | One-process-per-container is the container-native pattern. Let the orchestrator + HPA scale thin pods across nodes. Gunicorn's process manager duplicates what the orchestrator already does, and costs ~40 MB RSS per worker — disproportionate for a service under a couple hundred req/s. |
| **VM / bare metal** | **gunicorn + `uvicorn-worker`** behind nginx | You genuinely need a process supervisor: worker restarts, graceful reload, zero-downtime upgrades. Gunicorn is the battle-tested one. |
| Dense pods with a large shared model | gunicorn workers *inside* the pod | Only when a big in-memory model or sidecar overhead justifies fewer, fatter pods — and still run several pods for HA. |

Two details worth knowing:

- uvicorn's `--workers` uses **spawn**, not pre-fork, which is why it works on Windows —
  but also why `--preload`-style copy-on-write savings don't apply the same way.
- **Gunicorn's own native ASGI worker is still beta.** Gunicorn 26 ships a real ASGI
  compatibility suite (438/444 tests passing across Starlette/FastAPI/Litestar/Quart/
  Sanic/BlackSheep) and 134 new protocol tests, but the API and behaviour may still
  change. Keep using `uvicorn-worker` for production paths rather than Gunicorn's own
  ASGI worker.

**Gunicorn 26 (May 2026) breaking change: the `eventlet` worker class was dropped** —
eventlet is unmaintained. Migrate to `gevent`, `gthread` or `tornado`. Also: the fast
HTTP parser now needs `gunicorn_h1c >= 0.6.5`, and HTTP/1.1 request-target validation is
stricter per RFC 9112 (authority-form targets rejected outside CONNECT), which can reject
traffic a sloppy client previously got away with.

**Worker count.** `(2 × cores) + 1` is the classic Gunicorn rule for sync workloads.
For pure-async ASGI it's different: one async worker already multiplexes many
connections, so worker count is about multi-core utilisation and redundancy, not
concurrency — many async deployments run ≈ `cores`. Load-test rather than trusting
either formula.

**`--preload` + `gc.freeze()`.** Preload imports the app before forking, so workers
share memory copy-on-write. Then `gc.freeze()` (after imports, before fork) moves
existing objects to a permanent generation the cyclic collector skips — this avoids
re-scanning long-lived objects in every worker **and** prevents the refcount touching
of a GC pass from dirtying shared COW pages. Real RSS savings across many workers.

**Graceful shutdown.** Set `--timeout-graceful-shutdown` (uvicorn) /
`--graceful-timeout` (Gunicorn) from your slowest reasonable request, so in-flight
requests finish instead of being cut mid-response on deploy.

**The prometheus_client multiprocess gotcha.** With multiple workers each process keeps
its own metrics, so a naive setup reports nonsense (each scrape hits one random
worker). Fix: set `PROMETHEUS_MULTIPROC_DIR` **before any metric is created**, use
`MultiProcessCollector` to aggregate at scrape time, and call `mark_process_dead(pid)`
from Gunicorn's `child_exit` hook so dead workers' files don't skew aggregates forever.
Real limitations in this mode: **no custom collectors, no `Info`/`Enum` metrics, no
pushgateway, no `pid` label, no exemplars** — the model is file-based cross-process
aggregation and doesn't extend to those.

**Hypercorn** — ASGI with HTTP/3/QUIC and a Trio option; pick it for those specifically.

## Decision guide

- **FastAPI** — the default for new async APIs. Biggest ecosystem, best docs.
- **Litestar** — you want layered DI, DTOs and msgspec speed, and accept a smaller
  ecosystem.
- **Django + DRF** — admin, migrations, large CRUD/content surface. **django-ninja** if
  you want Django's ORM/admin with FastAPI-shaped endpoints.
- **Flask** — small/sync services and prototypes. **Quart** if you need the same API
  shape with real async.
- **Starlette** — ASGI primitives with no opinions.
- **Falcon / Sanic / BlackSheep** — minimalism / Flask-like async / built-in DI
  respectively.
- **Robyn** — only when routing overhead is measurably the bottleneck.
- **Tornado** — long-lived connections or an existing Tornado codebase.
- **Serving** — uvicorn + uvloop + httptools as the default; add Gunicorn's process
  manager (via `uvicorn-worker`) if you want its reload/health story; Granian for one
  Rust server across sync and async; Hypercorn for HTTP/3 or Trio.
