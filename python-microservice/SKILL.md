---
name: python-microservice
description: Use when building, scaffolding, or reviewing a Python backend service or API — choosing between FastAPI, Litestar, Django/DRF, django-ninja, Flask, Starlette or FastMCP for MCP servers; SQLAlchemy 2.0 async sessions and Alembic; Pydantic v2 and pydantic-settings; Redis caching; Celery/arq/Dramatiq workers; httpx timeouts; uvicorn/gunicorn/granian worker config; uv packaging; structlog and OpenTelemetry; pytest-asyncio and testcontainers; Dockerfiles for Python. Also for "start a Python service", "build an MCP server", "why is my FastAPI slow", "blocking the event loop", "async SQLAlchemy setup".
---

# Python Microservice

## Overview

A Python service is six things: **config**, an **HTTP surface**, **state** (DB +
cache), **async work**, **outbound calls**, and **operability**. Python's specific
hazard is that the wrong call in the wrong place silently destroys concurrency — one
blocking line in an `async def` stalls every request on that worker, and nothing warns
you. Most of this skill is about staying on the correct side of that line.

Verified against **Python 3.14** and **FastAPI 0.141.x** as of 2026-08. Library versions
throughout come from the PyPI registry, not from blog posts.

## When to Use

- Starting a new Python service, or adding an endpoint/worker/MCP tool
- Choosing a framework, ORM, cache, task queue, or server
- Reviewing Python service code for production-readiness
- Building an **MCP server** (FastMCP) — see references/fastmcp.md
- Diagnosing: "fast locally, slow under load", event-loop stalls, connection-pool
  exhaustion, N+1 queries, memory growth across workers, wrong Prometheus numbers
- Containerising a Python service, or moving one to Python 3.13/3.14

**Not for:** data pipelines, notebooks, ML training, or scripts.

## Step 0: Choose the framework

| If… | Use |
|---|---|
| Default, new async API | **FastAPI** — biggest ecosystem, auto OpenAPI, Pydantic v2 |
| Want layered DI, DTOs, msgspec speed | **Litestar** |
| Need admin, migrations, big CRUD surface | **Django + DRF** |
| Want Django's ORM/admin but FastAPI-shaped endpoints | **django-ninja** |
| Small/sync service, prototype | **Flask** (**Quart** if you need real async) |
| ASGI primitives, no opinions | **Starlette** (1.0 stable) |
| Building an **MCP server** for LLM tools | **FastMCP** (standalone `fastmcp`) |

On **Python 3.14 you need FastAPI ≥ 0.128.1** — PEP 649 changed annotation evaluation,
and older FastAPI breaks on endpoints with `TYPE_CHECKING`-only imports in their
signatures. Upgrade both together. Full comparison in references/frameworks.md.

## Quick Reference

| Task | Reach for | Detail |
|---|---|---|
| Framework | FastAPI (default) | references/frameworks.md |
| MCP server | **standalone `fastmcp`**, `streamable-http` | references/fastmcp.md |
| Packaging | **uv** (`uv sync`/`uv lock`/`uv run`) | references/packaging-deploy.md |
| Config | **pydantic-settings**, validated at import | references/packaging-deploy.md |
| DB | **SQLAlchemy 2.0** async + Alembic | references/persistence.md |
| Driver | asyncpg (via SQLAlchemy) or psycopg3 | references/persistence.md |
| Cache | redis-py (async), explicit TTLs | references/caching-redis.md |
| Background work | Celery, arq, Dramatiq, TaskIQ | references/messaging.md |
| Outbound HTTP | **httpx**, client reused, explicit `Timeout` | references/http-clients.md |
| Server | uvicorn + uvloop + httptools; granian | references/packaging-deploy.md |
| Logging | structlog or stdlib dictConfig → JSON | references/observability.md |
| Metrics | prometheus_client (**multiprocess mode!**) | references/observability.md |
| Tests | pytest, `asyncio_mode=auto`, httpx `ASGITransport` | references/testing.md |
| Lint/format | **ruff** (replaces black+isort+flake8), mypy/pyright | references/packaging-deploy.md |
| Container | multi-stage + uv, **slim not alpine** | references/packaging-deploy.md |

## Bootstrap a new service

```
myservice/
  pyproject.toml             # uv-managed, PEP 621
  uv.lock                    # committed
  src/myservice/
    __init__.py
    main.py                  # app factory + lifespan
    config.py                # pydantic-settings, validated
    api/                     # routers
    services/                # business logic — no HTTP/ORM types
    repositories/            # DB access
    clients/                 # outbound HTTP
    models.py                # SQLAlchemy models
    schemas.py               # Pydantic request/response models
  migrations/                # Alembic
  tests/
  Dockerfile
```

1. `uv init` + `uv add fastapi uvicorn[standard] sqlalchemy[asyncio] asyncpg pydantic-settings`
2. **`Settings(BaseSettings)`** instantiated at import — a missing env var must fail at
   startup, not at 3am in a request path.
3. **`lifespan`** context manager creating the httpx client and DB engine once, closing
   both on shutdown. Never `@app.on_event` (deprecated).
4. Keep **models** (SQLAlchemy) and **schemas** (Pydantic) separate — returning ORM
   objects directly is how `password_hash` leaks.
5. `Annotated[Session, Depends(get_session)]` type aliases, not `= Depends(...)`.
6. Exception handlers for one error envelope; override the framework's defaults too.
7. `/healthz` (liveness) and `/readyz` (readiness) — different checks.
8. `ruff check` + `ruff format` + `mypy` in CI.

## The non-negotiables

1. **Never block the event loop.** No `requests`, `time.sleep`, sync DB driver, or CPU
   loop inside `async def`. Use the async equivalent, or `asyncio.to_thread`, or declare
   the handler plain `def` so the framework runs it in a threadpool.
2. **Every HTTP call has an explicit timeout.** `requests` defaults to *waiting
   forever*. httpx defaults to 5 s — better, still be explicit with
   `Timeout(connect=, read=, write=, pool=)`.
3. **One httpx client per process**, created in lifespan, reused. Per-request clients
   throw away connection pooling entirely.
4. **Config validated at startup** via pydantic-settings. Fail fast.
5. **`asyncio.TaskGroup`, not `gather`.** `gather`'s defaults leave siblings running
   unsupervised on failure, or hide exceptions in the results list.
6. **Hold references to background tasks.** A bare `asyncio.create_task(...)` can be
   garbage-collected mid-flight and silently never finish.
7. **Separate Pydantic schemas from ORM models**, and set `response_model`.
8. **Sessions are per-request**, never global, never shared across tasks.
9. **prometheus_client needs multiprocess mode** with multiple workers, or your metrics
   are one random worker's view.
10. **Re-raise `CancelledError`.** Swallowing it breaks graceful shutdown.

## Reference Map

| File | Read when |
|---|---|
| references/language-runtime.md | Version features, free-threading/GIL, asyncio patterns, typing, profiling |
| references/frameworks.md | Framework choice, FastAPI depth, servers, worker counts |
| references/fastmcp.md | Building an MCP server: tools, transports, auth, testing |
| references/persistence.md | SQLAlchemy 2.0 async, pools, N+1, Alembic |
| references/caching-redis.md | redis-py async, cache patterns, stampede, locks |
| references/messaging.md | Celery/arq/Dramatiq, idempotency, retries, DLQ |
| references/http-clients.md | httpx timeouts, reuse, retries, breakers |
| references/observability.md | structlog, contextvars correlation IDs, OTel, metrics |
| references/testing.md | pytest-asyncio, ASGITransport, respx, testcontainers |
| references/packaging-deploy.md | uv, Dockerfile, ruff/mypy, servers, graceful shutdown |

## Common Mistakes

| Mistake | Why it hurts | Fix |
|---|---|---|
| `requests` / `time.sleep` in `async def` | Blocks **every** concurrent request on that worker | Async equivalent, `asyncio.to_thread`, or plain `def` |
| `async def` on a handler whose body is all sync | Same event-loop block, self-inflicted | Declare it `def` — the framework threadpools it |
| `httpx.AsyncClient()` per request | No pooling; TLS handshake every call | One client in lifespan |
| No `timeout=` on `requests` | Waits forever | Always pass it (or use httpx) |
| `raise_for_status()` not called | httpx doesn't raise on 4xx/5xx by default | Call it; map to domain errors |
| `asyncio.gather` for concurrent work | Siblings unsupervised on failure; hidden exceptions | `asyncio.TaskGroup` |
| Bare `asyncio.create_task(...)` | Weakly referenced — can be GC'd mid-flight | Keep a strong reference set |
| Catching `CancelledError` without re-raising | Breaks shutdown | `raise` after cleanup |
| `@app.on_event("startup")` | Deprecated; can't share state with shutdown | `lifespan` context manager |
| Mutable default argument (`items=[]`) | Shared across all calls, forever | `items=None` then default inside |
| Bare `except:` / broad `except Exception` | Swallows `KeyboardInterrupt`, `SystemExit`, your bugs | Catch what you expect |
| Returning ORM objects from endpoints | Leaks columns like `password_hash` | Separate Pydantic schemas + `response_model` |
| `BackgroundTasks` for important work | Dies with the worker, no retry, no visibility | Use a task queue |
| Celery task enqueued inside a DB transaction | Worker may run before commit → reads stale/absent row | Enqueue after commit, or use an outbox |
| `logging.basicConfig()` in library/module code | Hijacks the app's logging config | Configure once, in the entrypoint |
| prometheus_client with N workers, no multiproc | Each scrape hits one random worker | `PROMETHEUS_MULTIPROC_DIR` + `MultiProcessCollector` |
| alpine base image | musl forces slow source builds of wheels | `python:3.x-slim` |
| Module-level DB connect / network call | Breaks testing, fork, and `--preload` | Do it in lifespan |
| `sys._is_gil_enabled()` never checked on a free-threaded build | A non-thread-safe C extension **silently re-enables the GIL** | Assert and log it at boot |
