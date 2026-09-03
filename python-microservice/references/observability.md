# Observability

## Logging: structured, to stdout, configured once

Two viable stacks. Both emit JSON lines to **stdout** — never to files. The
platform (Kubernetes, systemd, a PaaS) owns log shipping; a service that writes
to disk is a service that fills its own disk.

**stdlib `logging` via `dictConfig`** — zero extra dependencies, fine for most
services:

```python
import logging.config

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,   # True kills uvicorn/gunicorn's own loggers
    "formatters": {
        "json": {
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        },
    },
    "handlers": {
        "default": {
            "class": "logging.StreamHandler",   # stdout, not a file handler
            "formatter": "json",
        },
    },
    "root": {"handlers": ["default"], "level": "INFO"},
    "loggers": {
        # Quiet the access log's own formatting; let it flow through "default"
        # instead of duplicating with uvicorn's built-in console formatter.
        "uvicorn.access": {"handlers": ["default"], "level": "INFO", "propagate": False},
        "uvicorn.error": {"handlers": ["default"], "level": "INFO", "propagate": False},
    },
}

logging.config.dictConfig(LOGGING_CONFIG)
```

**structlog** — richer processor chain, better for services with heavy
cross-cutting context (request IDs, tenant IDs, trace IDs):

```python
import logging
import structlog

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,       # pulls in bound contextvars (below)
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,           # renders exc_info into a field
        structlog.processors.JSONRenderer(),             # last processor: emits JSON
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    logger_factory=structlog.stdlib.LoggerFactory(),     # routes through stdlib logging
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger("myservice")
logger.info("order placed", order_id=order.id, amount=order.total)
# -> {"event": "order placed", "order_id": "o_123", "amount": 4200, "level": "info", "timestamp": "..."}
```

### `logging.basicConfig()` in library code is wrong

```python
# WRONG — inside myservice/billing/client.py
import logging
logging.basicConfig(level=logging.DEBUG)   # hijacks the ROOT logger for the whole process
logger = logging.getLogger(__name__)
```

`basicConfig()` attaches a handler to the root logger **the first time it's
called, and is a no-op every time after** — so whichever module imports first
wins, silently, and every other module's log level/format/destination is
whatever that first caller wanted. This is invisible until two modules disagree
and you get double-formatted or missing lines in production.

```python
# RIGHT — library/module code only ever does this:
logger = logging.getLogger(__name__)   # no configuration, just a named logger

# Configuration happens exactly once, in the entrypoint (main.py / asgi.py),
# before the app is constructed.
```

### uvicorn and gunicorn have their own loggers

Run `uvicorn app:app` with no config and you get uvicorn's colored console
formatter fighting your JSON formatter, or duplicate lines because uvicorn's
loggers propagate to root *and* have their own handler. Fix it explicitly:

```python
# Either disable uvicorn's own logging config entirely...
# uvicorn app:app --log-config logging.json --no-use-colors
# ...or, if you call dictConfig yourself, set disable_existing_loggers=False
# and explicitly redirect uvicorn.access / uvicorn.error (shown above) so they
# go through YOUR handler/formatter instead of stacking their own.
```

With gunicorn, `--logger-class` and `--access-logfile -` (stdout) plus the same
`dictConfig` applied in `on_starting` avoids the same duplication.

## Correlation IDs with `contextvars`

A request needs one ID that appears on every log line it touches, across every
`await`, every downstream call, every task spawned mid-request — so you can
`grep request_id=abc123` and see the whole story.

**Why `threading.local` does not work here**: it's keyed by OS thread. An async
app runs many concurrent requests on the *same* thread inside one event loop,
interleaved at every `await`. Thread-local state set by request A is visible to
request B's coroutine running on the same thread a microsecond later — request
IDs would leak across requests. `contextvars.ContextVar` is keyed by *execution
context*, not thread: each `Task` gets a **copy** of the context active when it
was created, so concurrent tasks on the same thread each see their own value,
and the value correctly follows a single request through every `await` inside
it.

```python
import contextvars
import uuid

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
```

Middleware: read the inbound header if present (trust it only from your own
edge/gateway), else generate one, bind it, echo it back:

```python
from starlette.middleware.base import BaseHTTPMiddleware

class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        rid = request.headers.get("x-request-id") or str(uuid.uuid4())
        token = request_id_var.set(rid)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)   # always reset — don't leak into the next task on reuse
        response.headers["x-request-id"] = rid
        return response
```

Inject it into every record — a `logging.Filter` for stdlib, or a processor for
structlog:

```python
class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True

logging.getLogger().addFilter(RequestIdFilter())
```

```python
# structlog equivalent — bind once per request, merge_contextvars (above) does the rest
def bind_request_id(rid: str) -> None:
    structlog.contextvars.bind_contextvars(request_id=rid)
```

### Why this propagates into tasks "for free"

`asyncio.create_task()` (and `TaskGroup`) captures a **copy of the current
context** at creation time and runs the new task inside that copy. Anything
bound to a `ContextVar` before you spawn a task — the request ID, a tenant ID,
a span context — is automatically visible inside that task without passing it
as an argument. This is the entire mechanism that makes contextvars the
async-correct analog of thread-locals: propagation is structural, tied to the
call graph of task creation, not to which OS thread happens to run the code.

## What never goes in a log

Passwords, access/refresh tokens, API keys, full card numbers, OTPs, PII
(email, phone, government IDs) beyond an opaque user ID, raw request/response
bodies of auth endpoints. A `logger.info("login attempt", extra={"payload":
body})` on a login handler is a card-number-in-plaintext-logs incident waiting
to happen — assume every log line ends up in a search index with broad
read access.

```python
REDACT_KEYS = {"password", "token", "authorization", "otp", "card_number", "cvv"}

def redact_processor(logger, method_name, event_dict):
    for key in list(event_dict):
        if key.lower() in REDACT_KEYS:
            event_dict[key] = "***"
    return event_dict

# add to the structlog processor chain BEFORE JSONRenderer
structlog.configure(processors=[..., redact_processor, structlog.processors.JSONRenderer()])
```

For stdlib, do the equivalent in a `logging.Filter`, and — more importantly —
never pass raw request bodies into `extra=` on auth-adjacent handlers in the
first place. Redaction-as-a-filter is a safety net, not the primary control.

## Levels, used consistently

| Level | Meaning | Pages someone? |
|---|---|---|
| `ERROR` | Request/operation failed; needs a human eventually | Yes, if sustained/on-call scoped |
| `WARNING` | Degraded but handled — retry succeeded, fallback used, deprecated input | No, but worth dashboards |
| `INFO` | Normal operation milestones — request completed, job started, config loaded | No |
| `DEBUG` | Payload-level detail, only useful mid-investigation | No, usually disabled in prod |

**Log where you handle, return where you don't.** If a function catches an
exception, decides what to do about it, and continues, that's where it belongs
in the log — once. If it can't fully handle the error, it should re-raise (or
raise a translated exception) and let a higher layer log it. Doing both —
`logger.exception(...)` and then `raise` — at three nested layers produces
three log lines for one failure, each with a slightly different stack trace
tail, and turns every real incident into an archaeology exercise over
duplicate noise.

```python
# WRONG — logged at every layer that touches it, plus finally raised
def repo_call():
    try:
        ...
    except DBError as e:
        logger.exception("db failed")     # logged here...
        raise

def service_call():
    try:
        repo_call()
    except DBError as e:
        logger.exception("service failed")  # ...and here...
        raise

def handler():
    try:
        service_call()
    except DBError as e:
        logger.exception("handler failed")  # ...and here. Same failure, 3 log lines.
        raise

# RIGHT — log exactly once, at the layer that actually handles it
def repo_call():
    ...   # let it raise, no logging, no swallowing

def service_call():
    ...   # translate to a domain exception if useful, still don't log

def handler():
    try:
        service_call()
    except DomainError:
        logger.exception("request failed")   # the ONE layer with enough context to act
        return error_response()
```

## Metrics with `prometheus_client`

```python
from prometheus_client import Counter, Histogram, Gauge

REQUESTS = Counter(
    "http_requests_total", "Total HTTP requests",
    labelnames=["method", "route", "status_class"],
)

# Buckets matched to the SLO, not the library default (which tops out at 10s —
# useless if your p99 target is 200ms; every real observation lands in the last
# bucket and the histogram tells you nothing).
LATENCY = Histogram(
    "http_request_duration_seconds", "Request duration",
    labelnames=["method", "route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.15, 0.2, 0.3, 0.5, 1.0, 2.5, 5.0),
)

IN_FLIGHT = Gauge("http_requests_in_flight", "Requests currently being served")
```

### Cardinality is the whole game

Every distinct combination of label values is a **separate time series**
stored, scraped, and queried forever until the series goes stale. A label with
1,000 possible values multiplies every metric using it by 1,000 series.

```python
# WRONG — user_id and raw path are unbounded. Millions of series, one per user
# per unique URL ever hit. Prometheus either falls over or you silently lose data
# to a cardinality limit.
REQUESTS.labels(method=request.method, route=request.url.path, status_class="2xx").inc()

# RIGHT — the route TEMPLATE, not the interpolated path. "/users/{id}" is one
# series regardless of how many distinct ids are requested.
REQUESTS.labels(method=request.method, route=request.scope["route"].path, status_class="2xx").inc()
```

Never label with: user IDs, request IDs, session tokens, raw free-text, IP
addresses, or anything else with high or unbounded cardinality. If you need
that granularity, it belongs in a trace span attribute or a log field, not a
metric label.

### The multiprocess gotcha, in detail

Gunicorn with N worker processes means N independent Python processes, each
with its own `prometheus_client` registry in memory. Scrape one worker over
HTTP and you get *that worker's* counters only — a random, incomplete slice of
the fleet, not the aggregate. This is silent: the endpoint returns valid
metrics, they're just wrong.

Fix, in order:

```python
# 1. Set BEFORE any metric object is created — module import order matters.
#    Typically set in the container/pod env, not in application code.
import os
os.environ["PROMETHEUS_MULTIPROC_DIR"] = "/tmp/prometheus_multiproc"
# each worker writes its counters to files here; a collector reads them all back.

from prometheus_client import multiprocess, CollectorRegistry, generate_latest

def metrics_endpoint():
    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry)   # merges every worker's files
    return generate_latest(registry)
```

```python
# 2. Clean up a worker's files when it dies, or its LAST-WRITTEN values persist
#    forever as stale "ghost" series merged into every future scrape.
def child_exit(server, worker):
    multiprocess.mark_process_dead(worker.pid)

# gunicorn.conf.py
# child_exit = child_exit   # gunicorn calls this automatically on worker exit
```

**Real limitations in multiprocess mode** — not bugs, structural constraints of
file-based aggregation across processes:

- No custom `Collector` classes — only the built-in metric types round-trip
  through the file format.
- No `Info` or `Enum` metric types — not supported in multiprocess mode at all.
- No pushgateway integration.
- No `pid` label on the merged output — by design, since the whole point is to
  present one fleet-wide view, not per-process detail.
- No exemplars (trace-ID-on-metric-sample linking) — the file format doesn't
  carry them.

If you run a single process per container (common in Kubernetes, where the pod
*is* your scaling unit and you run one worker per pod), skip all of this —
plain in-memory `prometheus_client` is correct and simpler.

## RED method

For every route: **R**ate (`REQUESTS` counter), **E**rrors (same counter,
labeled by status class), **D**uration (`LATENCY` histogram) — plus an
in-flight gauge to see saturation before it shows up in latency.

```python
@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    route = request.scope.get("route")
    route_template = route.path if route else "unmatched"
    IN_FLIGHT.inc()
    start = time.monotonic()
    try:
        response = await call_next(request)
        status_class = f"{response.status_code // 100}xx"
        return response
    finally:
        LATENCY.labels(request.method, route_template).observe(time.monotonic() - start)
        REQUESTS.labels(request.method, route_template, status_class).inc()
        IN_FLIGHT.dec()
```

RED tells you the HTTP layer is healthy. It does **not** tell you the business
logic is correct — a payment endpoint can return `200` for a payment that
silently failed downstream. Pair RED with business metrics: `payments_processed_total`,
`payments_failed_total{reason=}`, `queue_depth`, `stale_data_seconds`. These
catch the failures that look perfectly healthy at the HTTP layer.

## OpenTelemetry

**Auto-instrumentation** — zero code changes, wraps the process:

```bash
opentelemetry-instrument \
    --traces_exporter otlp \
    --metrics_exporter otlp \
    uvicorn app:app
```

Instruments whatever's installed and importable: `opentelemetry-instrumentation-fastapi`,
`-sqlalchemy`, `-httpx`, `-redis`, etc. Good default for getting traces without
touching application code; less control over span naming/attributes.

**Manual SDK** — when you need specific spans, custom attributes, or
instrumentation auto-instrument doesn't cover:

```python
from opentelemetry import trace

tracer = trace.get_tracer("myservice")

async def process_order(order_id: str) -> None:
    with tracer.start_as_current_span("process_order") as span:
        span.set_attribute("order.id", order_id)          # fine — trace attributes
        span.set_attribute("order.item_count", len(items))  # aren't a metrics time
        ...                                                 # series, so higher
                                                              # cardinality is OK...
        # ...but the "no secrets" rule from logging still applies. Never put a
        # token, password, or card number in a span attribute either.
```

### Sampling

```python
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

# ParentBased: if a parent span already decided to sample, honor that decision
# (keeps a distributed trace whole instead of half-sampled). Otherwise fall
# back to a ratio for root spans.
sampler = ParentBased(root=TraceIdRatioBased(0.1))   # sample 10% of new traces
```

100% sampling is the default temptation and it's expensive: every span is
serialized, exported, stored, and indexed by the backend, and at real traffic
volumes this materially adds CPU/network overhead and a real bill. Start low
(1-10%), sample errors at a higher rate via a tail-sampling policy if your
backend supports it, and always sample 100% of spans in non-prod.

### Correlating logs and traces

Put the active trace/span IDs into every log line so a log line and a trace
are one click apart:

```python
span = trace.get_current_span()
ctx = span.get_span_context()
logger.info("processing", extra={
    "trace_id": format(ctx.trace_id, "032x"),
    "span_id": format(ctx.span_id, "016x"),
})
```

`opentelemetry-instrumentation-logging` does this automatically if you'd rather
not wire it by hand.

## Health endpoints

Two endpoints, two different questions, and conflating them is the single most
common outage-amplifier in this list.

```python
@app.get("/healthz")
async def liveness():
    # Is THIS PROCESS alive and able to serve traffic at all? Process-local only.
    # No DB, no downstream calls, no I/O. If this handler can execute, return 200.
    return {"status": "ok"}

@app.get("/readyz")
async def readiness(request: Request):
    # Are ESSENTIAL dependencies reachable RIGHT NOW? Short timeout, only the
    # deps this instance cannot function without.
    try:
        async with asyncio.timeout(1.0):
            await request.app.state.db.execute("SELECT 1")
    except (TimeoutError, OSError):
        return JSONResponse({"status": "not ready"}, status_code=503)
    return {"status": "ready"}
```

**Why liveness must never check the database**: liveness failures trigger a
**restart** (Kubernetes kills and reschedules the container). If liveness
checks the DB and the DB has a two-minute blip, every single pod's liveness
probe fails simultaneously, the orchestrator restarts the entire fleet at once,
and a two-minute database blip becomes a full-service outage with a cold-start
stampede on top. Liveness answers "is the process wedged" — a deadlock, an
unresponsive event loop — nothing external.

**Readiness failures don't restart anything** — they pull the instance out of
the load balancer's rotation until it passes again. This is the correct place
to check the DB, because the blast radius is "traffic stops routing here,"
not "the container dies."

**Optional dependencies must not fail readiness.** If a feature-flag service or
a non-critical cache is down, degrade that feature — don't take the whole
instance out of rotation for a dependency the core request path doesn't need.

**Flip readiness to failing before shutdown, not after.** On `SIGTERM`, the
first thing that happens is `/readyz` starts returning 503 — before you stop
accepting connections, before you close pools. Load balancers poll readiness
periodically and take a moment to notice and stop routing (see
`packaging-deploy.md` for the full drain sequence); if you close the socket
first, requests already in flight to the old endpoint get connection-refused
instead of served-then-drained.

## Profiling in production

- **py-spy** — attaches to a *running* process with **no code change and no
  restart**, sampling the C stack of the interpreter. `py-spy dump --pid
  <pid>` is the fastest way to answer "why is this request stuck" — it prints
  every thread's current Python stack trace in under a second, no
  instrumentation needed ahead of time. `py-spy top --pid <pid>` gives a live
  `top`-style view of which functions are hot right now. Both work through
  cgroup/namespace boundaries with the right permissions, so they're usable
  against a container from the host or a debug sidecar.
- **memray** — allocation profiler; use it when RSS keeps climbing and you need
  to know which call site is holding the memory, not just that "something
  leaks." Produces flamegraphs of allocations, not just CPU time.
- **Sentry** (or an equivalent APM's error tracker) — catches and groups
  exceptions with full context (stack, request, user-scoped breadcrumbs)
  automatically; complements logs/traces rather than replacing them, since it's
  optimized for "what broke and how often," not "what happened in this one
  request."

## Instrumenting LLM calls (OTel GenAI conventions)

If your service calls an LLM, the token spend and latency belong in the same telemetry as
everything else — not in a vendor dashboard nobody correlates with your traces.

**The standard is OpenTelemetry's GenAI semantic conventions.** Baseline attributes:

| Attribute | Meaning |
|---|---|
| `gen_ai.operation.name` | `chat`, `embeddings`, … |
| `gen_ai.request.model` | the model actually invoked |
| `gen_ai.usage.input_tokens` | prompt tokens |
| `gen_ai.usage.output_tokens` | completion tokens |

Emitting those four turns cost into a normal metric you can alert on and break down by
route, and makes "which endpoint is burning our token budget" a query rather than an
investigation.

**Status: still pre-stable/experimental**, even though major vendors have adopted them
(Datadog supports them natively from OTel v1.37+). GenAI attributes have moved out of the
core semconv registry into a dedicated GenAI conventions repo. Set
`OTEL_SEMCONV_STABILITY_OPT_IN` to dual-emit legacy and new attribute names during a
transition rather than cutting over blind.

**Instrumentation options:**
- **OpenLLMetry** (Traceloop, Apache 2.0) — the dominant OTel-native layer; pre-built
  instrumentations for OpenAI/Anthropic/Cohere/Pinecone/LangChain and exports to any OTLP
  backend. Keeps you vendor-neutral.
- **Langfuse / Helicone / LangSmith** — better LLM-specific UX, proprietary pipeline.
  Fine, but you're accepting lock-in for the ergonomics.

Two rules that matter more than the tooling choice:

1. **Instrument at ONE layer.** Auto-instrumentation *plus* a framework's built-in
   observability *plus* manual spans produces duplicated, double-counted spans that are
   worse than either alone.
2. **Put prompts and completions in span *events*, never attributes.** Attributes have
   size limits and are indexed — a prompt in an attribute means PII in your index and
   truncated telemetry. Better still, log a hash or a redacted summary and keep the raw
   text out of telemetry entirely.

## Checklist

- [ ] Logging configured exactly once, in the entrypoint — no `basicConfig()` in library code
- [ ] JSON logs to stdout, never to a file
- [ ] uvicorn/gunicorn loggers integrated, not fighting your formatter (no dupes, no drops)
- [ ] Request ID via `contextvars`, bound in middleware, injected into every log record
- [ ] Redaction processor/filter for secrets; no raw auth payloads logged, ever
- [ ] Log levels used consistently; logged exactly once, at the layer that handles it
- [ ] Histogram buckets sized to the actual SLO, not left at library defaults
- [ ] No unbounded-cardinality labels (user ID, raw path, IP) on any metric
- [ ] `PROMETHEUS_MULTIPROC_DIR` set before any metric object is created, if multi-worker
- [ ] `child_exit` calls `mark_process_dead` in multiprocess mode
- [ ] RED metrics per route, plus business metrics that catch logic failures
- [ ] Tracing sampled sensibly (not 100% in prod); trace/span IDs correlated into logs
- [ ] `/healthz` is process-local only; `/readyz` checks essential deps with a short timeout
- [ ] Readiness flips to failing before shutdown begins draining
- [ ] `py-spy`, `memray` available in the toolbox for live production debugging
