# Outbound HTTP in Python

## The default-timeout trap

Know what each library does when you say nothing:

| Library | Default timeout | Verdict |
|---|---|---|
| `requests` | **None — waits forever** | Never omit `timeout=`. |
| `urllib` / `http.client` | **None** | Same. |
| `aiohttp` | 5 min total (`ClientTimeout(total=300)`) | Present but far too long. |
| **`httpx`** | **5 s on all phases** | Sane default, still be explicit. |

A hung dependency with no timeout means a worker blocked forever. Enough of those
and the service is down while every health check passes.

## httpx is the default choice

Sync and async in one API, HTTP/2, connection pooling, a real timeout model.

```python
import httpx

# Timeout is FOUR separate budgets, not one. Set them deliberately.
TIMEOUT = httpx.Timeout(
    connect=2.0,   # TCP + TLS handshake
    read=5.0,      # gap between bytes once connected — NOT total response time
    write=5.0,     # sending the request body
    pool=1.0,      # waiting for a free connection from the pool
)

LIMITS = httpx.Limits(
    max_connections=100,             # total across all hosts
    max_keepalive_connections=20,    # kept warm
    keepalive_expiry=30.0,
)
```

Note `read` is an **inactivity** timeout, not a total-duration cap. A server
trickling one byte every 4 seconds never trips a 5 s read timeout. For a hard
ceiling, wrap the call:

```python
async with asyncio.timeout(10):        # true wall-clock ceiling
    r = await client.get(url)
```

## Reuse the client — this is the #1 mistake

Creating a client per request throws away the connection pool: a fresh TCP + TLS
handshake every call, plus socket churn. It can be an order of magnitude slower.

```python
# WRONG — new pool, new handshake, every single request
@app.get("/bad")
async def bad():
    async with httpx.AsyncClient() as c:      # <-- per-request client
        return (await c.get(url)).json()

# RIGHT — one client for the process lifetime, tied to the app lifespan
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient(
        timeout=TIMEOUT,
        limits=LIMITS,
        headers={"user-agent": "myservice/1.0"},
        base_url="https://api.example.com",   # then call c.get("/users/1")
    )
    try:
        yield
    finally:
        await app.state.http.aclose()          # close on shutdown, always

app = FastAPI(lifespan=lifespan)

@app.get("/good")
async def good(request: Request):
    r = await request.app.state.http.get("/users/1")
    r.raise_for_status()
    return r.json()
```

Better still, wrap it in a typed client class and inject that — handlers shouldn't
know about HTTP.

```python
class UserClient:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    async def get_user(self, uid: str) -> User:
        r = await self._http.get(f"/users/{uid}")
        if r.status_code == 404:
            raise UserNotFound(uid)          # domain error, not an HTTP detail
        r.raise_for_status()
        return User.model_validate(r.json())
```

## Error handling

```python
try:
    r = await client.get(url)
    r.raise_for_status()
except httpx.TimeoutException as e:          # connect/read/write/pool timeouts
    raise UpstreamTimeout(str(e)) from e
except httpx.HTTPStatusError as e:
    # e.response is available — inspect status, don't blanket-retry
    if e.response.status_code < 500:
        raise UpstreamBadRequest(e.response.text[:500]) from e
    raise UpstreamUnavailable() from e
except httpx.RequestError as e:              # DNS, connection refused, TLS
    raise UpstreamUnavailable(str(e)) from e
```

`raise_for_status()` does nothing unless you call it — httpx does **not** raise on
4xx/5xx by default. Translate transport errors into domain errors at the client
boundary so callers never import `httpx`.

## Retries

```python
from tenacity import (retry, stop_after_attempt, wait_exponential_jitter,
                      retry_if_exception_type)

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=0.1, max=2.0),   # jitter is mandatory
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
    reraise=True,
)
async def fetch(client: httpx.AsyncClient, url: str) -> httpx.Response:
    r = await client.get(url)
    if r.status_code >= 500 or r.status_code == 429:
        r.raise_for_status()      # make it retryable
    return r
```

Rules — same as any language:

- Retry **idempotent** operations only. A retried POST can double-charge someone.
  If you must retry a POST, send an `Idempotency-Key` and have the server dedupe.
- Retry **transient** failures only: timeouts, connection errors, 429, 502, 503,
  504. Never 400/401/403/404/422.
- **Full jitter, always.** Without it, all clients that failed together retry
  together and finish off the recovering dependency.
- **Cap attempts** (3) and stay inside the caller's deadline.
- **Retry in exactly one layer.** Client × proxy × sidecar retries multiply.
- Honour `Retry-After` when present.

httpx's built-in `transport=httpx.AsyncHTTPTransport(retries=3)` retries **connection
attempts only**, not failed responses. It's not a substitute for the above.

## Circuit breaker

```python
# purgatory / aiobreaker / pybreaker — or a small hand-rolled one.
# The important properties: per-dependency, volume threshold, logged transitions.
breaker = CircuitBreaker(
    fail_max=10,                 # trip after 10 failures...
    reset_timeout=30,            # ...retry a probe after 30s
    exclude=[UpstreamBadRequest],  # 4xx means WE were wrong; not a breaker failure
)
```

One breaker per dependency. Log every state change — a breaker that opens silently
is an outage you learn about from users. Always have a defined fallback: cached
value, degraded response, or a clean 503.

## Concurrency and bounding fan-out

```python
# Bound concurrency against a dependency. An unbounded fan-out is a DoS
# you wrote yourself.
sem = asyncio.Semaphore(10)

async def fetch_one(client, uid):
    async with sem:
        return await client.get(f"/users/{uid}")

async def fetch_many(client, uids):
    results = {}
    async with asyncio.TaskGroup() as tg:      # structured: failure cancels siblings
        tasks = {uid: tg.create_task(fetch_one(client, uid)) for uid in uids}
    return {uid: t.result() for uid, t in tasks.items()}
```

## Instrumentation

```python
# Auto-instrument httpx for tracing (spans + W3C traceparent propagation)
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
HTTPXClientInstrumentor().instrument()
```

For custom cross-cutting behaviour, use an **event hook** or a custom transport:

```python
async def log_response(response: httpx.Response) -> None:
    logger.info("upstream call",
                extra={"url": str(response.request.url),
                       "status": response.status_code,
                       "elapsed_ms": response.elapsed.total_seconds() * 1000})

client = httpx.AsyncClient(event_hooks={"response": [log_response]})
```

Emit per dependency: request count by status class, duration histogram, in-flight
gauge, breaker state.

## Other clients

- **`aiohttp`** — mature, async-only, slightly faster in some benchmarks. Its
  `ClientSession` must also be created once and reused (and closed on shutdown).
  Default 5-minute timeout is too long; set `ClientTimeout` explicitly.
- **`requests`** — sync only, no HTTP/2, in maintenance mode. Fine in scripts and
  sync workers. **Never** in an async handler. Always pass `timeout=`. Reuse a
  `Session` for pooling.
- **`niquests`** — a `requests`-compatible fork with HTTP/2+3 and async. Useful as
  a drop-in upgrade path for a large `requests` codebase.
- **`boto3`** is sync — in an async service, wrap calls in `asyncio.to_thread`, or
  use `aioboto3`/`aiobotocore`. And set `botocore.config.Config(connect_timeout=,
  read_timeout=, retries={"max_attempts": ...})`; boto3's defaults are generous.

## Checklist

- [ ] One client per process, created in lifespan, closed on shutdown
- [ ] Explicit `httpx.Timeout(connect=, read=, write=, pool=)`
- [ ] A wall-clock ceiling (`asyncio.timeout`) where total duration matters
- [ ] `httpx.Limits` tuned to expected concurrency
- [ ] `raise_for_status()` called; transport errors mapped to domain errors
- [ ] Retries: idempotent + transient only, capped, jittered, single-layer
- [ ] Breaker per dependency, transitions logged, fallback defined
- [ ] Fan-out bounded by a semaphore
- [ ] Tracing instrumented; per-dependency metrics emitted
- [ ] No `requests` (or any sync client) inside an `async def`
