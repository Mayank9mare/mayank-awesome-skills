"""Production-shaped FastAPI entry point.

Copy to src/myservice/main.py and adapt. This deliberately demonstrates the things
that cause incidents when omitted:

  * config validated at import (fail fast, not at 3am in a request path)
  * lifespan creating the httpx client and DB engine ONCE, closing both on exit
  * liveness vs readiness as SEPARATE checks
  * correlation IDs via contextvars (the only mechanism that survives `await`)
  * one error envelope, including overrides of the framework's own handlers
  * Pydantic schemas separate from ORM models

See the python-microservice skill's references/ for the reasoning behind each.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import logging.config
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

import httpx
from fastapi import Depends, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------


class Settings(BaseSettings):
    """Typed, validated configuration.

    Instantiated at import time below, so a missing or malformed variable
    crashes the process at startup rather than surfacing as a 500 on some
    unlucky request hours later.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="MYSERVICE_",
        extra="forbid",  # a typo'd env var is an error, not silently ignored
    )

    env: str = "local"
    log_level: str = "INFO"

    database_url: str  # no default -> required
    db_pool_size: int = Field(default=10, ge=1, le=100)
    db_max_overflow: int = Field(default=5, ge=0)

    upstream_base_url: str = "https://api.example.com"
    upstream_connect_timeout: float = Field(default=2.0, gt=0)
    upstream_read_timeout: float = Field(default=5.0, gt=0)

    request_timeout: float = Field(default=10.0, gt=0)


settings = Settings()  # raises at import if the environment is wrong

# --------------------------------------------------------------------------
# Logging + correlation IDs
# --------------------------------------------------------------------------

# A ContextVar is the async-correct mechanism. A threading.local does NOT work:
# many requests share one thread and interleave at every `await`, so they would
# overwrite each other's value. ContextVars are copied into tasks created from
# the current context, which is what makes this correct under asyncio.
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)


class RequestIDFilter(logging.Filter):
    """Injects the current request id into every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def configure_logging(level: str, env: str) -> None:
    """Configure logging ONCE, from the entrypoint.

    Never call logging.basicConfig() in library or module code -- it hijacks the
    application's configuration. Also note uvicorn ships its own loggers; we
    attach our handler to them so lines aren't duplicated or lost.
    """
    fmt = (
        "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"
        if env == "local"
        # In production prefer a JSON formatter (structlog or python-json-logger)
        else '{"ts":"%(asctime)s","level":"%(levelname)s",'
        '"request_id":"%(request_id)s","logger":"%(name)s","msg":"%(message)s"}'
    )
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {"request_id": {"()": RequestIDFilter}},
            "formatters": {"default": {"format": fmt}},
            "handlers": {
                "stdout": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",  # stdout, never a file
                    "formatter": "default",
                    "filters": ["request_id"],
                }
            },
            "root": {"handlers": ["stdout"], "level": level},
            "loggers": {
                "uvicorn": {"handlers": ["stdout"], "level": level, "propagate": False},
                "uvicorn.access": {
                    "handlers": ["stdout"],
                    "level": level,
                    "propagate": False,
                },
            },
        }
    )


configure_logging(settings.log_level, settings.env)
log = logging.getLogger("myservice")

# --------------------------------------------------------------------------
# Lifespan: create expensive things once
# --------------------------------------------------------------------------

_shutting_down = False


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create shared resources once; close them on shutdown.

    This replaces @app.on_event("startup"/"shutdown"), which is DEPRECATED.
    A single generator also means startup and shutdown share one local scope,
    so you can only close what you actually opened.
    """
    global _shutting_down

    # ONE client per process. A per-request AsyncClient throws away connection
    # pooling entirely -- a fresh TCP+TLS handshake on every outbound call.
    app.state.http = httpx.AsyncClient(
        base_url=settings.upstream_base_url,
        # Four separate budgets, not one. `read` is an INACTIVITY timeout, so
        # for a hard wall-clock ceiling wrap the call in asyncio.timeout().
        timeout=httpx.Timeout(
            connect=settings.upstream_connect_timeout,
            read=settings.upstream_read_timeout,
            write=settings.upstream_read_timeout,
            pool=1.0,
        ),
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        headers={"user-agent": "myservice/1.0"},
    )

    # engine = create_async_engine(
    #     settings.database_url,
    #     pool_size=settings.db_pool_size,
    #     max_overflow=settings.db_max_overflow,
    #     pool_pre_ping=True,
    # )
    # app.state.sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    log.info(
        "starting env=%s pool_size=%d upstream=%s",
        settings.env,
        settings.db_pool_size,
        settings.upstream_base_url,
    )
    try:
        yield
    finally:
        # Fail readiness first so load balancers stop routing to us, then close.
        _shutting_down = True
        await app.state.http.aclose()
        # await engine.dispose()
        log.info("shutdown complete")


app = FastAPI(
    title="myservice",
    lifespan=lifespan,
    # Hide schema docs in production if the service isn't public.
    docs_url="/docs" if settings.env == "local" else None,
)

# --------------------------------------------------------------------------
# Middleware
# --------------------------------------------------------------------------


@app.middleware("http")
async def request_context(request: Request, call_next: Any) -> Any:
    """Assign a request id, expose it on the response, and bound the request."""
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex
    token = request_id_var.set(rid)
    try:
        # A server-side ceiling so one slow handler can't pin a worker forever.
        async with asyncio.timeout(settings.request_timeout):
            response = await call_next(request)
    except TimeoutError:
        log.warning("request timed out path=%s", request.url.path)
        response = JSONResponse(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            content={"error": {"code": "timeout", "message": "request timed out"}},
        )
    finally:
        request_id_var.reset(token)

    response.headers["x-request-id"] = rid
    return response


# --------------------------------------------------------------------------
# Errors: one envelope, everywhere
# --------------------------------------------------------------------------


class AppError(Exception):
    """Domain error carrying a stable machine-readable code."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _envelope(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, **extra}}


@app.exception_handler(AppError)
async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(exc.status_code, _envelope(exc.code, exc.message))


# Override the framework's OWN handlers too, or you ship three different error
# shapes and clients have to special-case each one.
@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        _envelope("validation_error", "request validation failed", details=exc.errors()),
    )


@app.exception_handler(StarletteHTTPException)
async def handle_http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(exc.status_code, _envelope("http_error", str(exc.detail)))


@app.exception_handler(Exception)
async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
    # Log the traceback; return an opaque message. Never leak internals.
    log.exception("unhandled exception path=%s", request.url.path)
    return JSONResponse(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        _envelope("internal_error", "internal server error"),
    )


# --------------------------------------------------------------------------
# Schemas -- kept separate from ORM models on purpose
# --------------------------------------------------------------------------


class UserOut(BaseModel):
    """Response schema.

    Separate from the ORM model so a new database column (password_hash,
    internal_notes) is never serialised to clients just because it was added.
    """

    model_config = ConfigDict(from_attributes=True)  # build from an ORM object

    id: str
    email: str


# --------------------------------------------------------------------------
# Dependencies
# --------------------------------------------------------------------------


async def get_http(request: Request) -> httpx.AsyncClient:
    return request.app.state.http


# The modern idiom: Annotated[T, Depends(...)] as a reusable alias.
# The legacy `client: httpx.AsyncClient = Depends(get_http)` form overloads the
# parameter DEFAULT to carry DI metadata, which confuses type checkers and
# cannot be aliased.
HttpDep = Annotated[httpx.AsyncClient, Depends(get_http)]

# async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
#     async with request.app.state.sessionmaker() as session:
#         yield session
# SessionDep = Annotated[AsyncSession, Depends(get_session)]


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    """Liveness: is this process functioning?

    Must NOT check dependencies. If it pings the database, one DB blip restarts
    every pod simultaneously and turns a transient blip into a full outage.
    """
    return {"status": "ok"}


@app.get("/readyz", include_in_schema=False)
async def readyz() -> JSONResponse:
    """Readiness: should I receive traffic right now?

    Checks only what we cannot serve without, with a short timeout. Optional
    dependencies (a cache we can bypass) must not fail readiness.
    """
    if _shutting_down:
        return JSONResponse(
            status.HTTP_503_SERVICE_UNAVAILABLE, {"status": "shutting_down"}
        )
    # async with asyncio.timeout(2):
    #     await session.execute(text("SELECT 1"))
    return JSONResponse(status.HTTP_200_OK, {"status": "ready"})


@app.get("/users/{user_id}", response_model=UserOut)
async def get_user(user_id: str, http: HttpDep) -> UserOut:
    """Fetch a user from the upstream service."""
    resp = await http.get(f"/users/{user_id}")
    if resp.status_code == status.HTTP_404_NOT_FOUND:
        raise AppError("user_not_found", f"no user with id {user_id}", 404)
    resp.raise_for_status()  # httpx does NOT raise on 4xx/5xx by default
    return UserOut.model_validate(resp.json())


if __name__ == "__main__":
    # Production runs uvicorn/granian from the container CMD, not this block.
    import uvicorn

    uvicorn.run("myservice.main:app", host="0.0.0.0", port=8080, reload=True)  # noqa: S104
