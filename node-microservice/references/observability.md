# Observability in Node

## Logging: structured JSON to stdout, always

```js
// WRONG — unstructured, unqueryable, and on some streams synchronous.
// console.log's underlying write to a TTY is async, but piped to a file
// or through a process manager it can be sync — meaning every log line
// blocks the event loop until the write completes. At volume, that's
// your request latency, paid on every log call.
console.log(`user ${userId} placed order ${orderId} for ${amount}`);

// RIGHT — structured, machine-parseable, async, and carries fields
// your log platform can filter/aggregate on without a regex.
import pino from 'pino';
const logger = pino();
logger.info({ userId, orderId, amount }, 'order placed');
```

pino writes JSON to **stdout**, not to a file and not over the network
from inside the request path. The runtime (Docker, Kubernetes, systemd)
already collects stdout — that's the one log sink every deployment
platform gives you for free, with no extra code and no failure mode of
its own. A network transport (ship-to-Elasticsearch-directly, say) adds
a dependency to every request: if the log backend is slow or down, your
request now waits on it, or you've built a buffering/retry layer to avoid
that, which is a second distributed system you now maintain. Log to
stdout; let a sidecar or agent (Fluent Bit, Vector, the platform's log
driver) ship it. That process crashing doesn't take your service with it.

```js
// pino config for production: level from env, ISO timestamps (default
// is epoch ms, which is fine for machines, painful for humans grepping
// raw output during an incident)
const logger = pino({
  level: process.env.LOG_LEVEL ?? 'info',
  timestamp: pino.stdTimeFunctions.isoTime,
});
```

## Child loggers: context without repeating yourself

```js
// Attach request-scoped fields once; every subsequent .info/.warn/.error
// on the child carries them automatically.
function requestLogger(req) {
  return logger.child({ requestId: req.id, route: req.routerPath });
}

// in a handler
const log = requestLogger(req);
log.info({ userId }, 'processing order');   // includes requestId + route
log.warn({ retryCount: 3 }, 'downstream slow');
```

Child loggers compose — a service-level child (`{ service: 'orders' }`)
wrapping a request-level child (`{ requestId }`) wrapping a job-level
child (`{ jobId }`) — without any call site repeating the parent context.

## Redaction: what never goes in a log line

Tokens, passwords, card numbers, PII (email, phone, address, national ID),
and full auth request/response bodies never appear in logs — not "we'll
redact it later," not "just in staging." Logs get shipped, retained,
searched, and exported to third parties (log platforms, on-call tooling)
that never should have seen a card number in the first place, and a
breach of your log pipeline shouldn't be a breach of your customers' data.

```js
// RIGHT — pino's redact strips these paths from every log object,
// no matter which call site produced them, replacing values with '[Redacted]'
const logger = pino({
  redact: {
    paths: [
      'req.headers.authorization',
      'req.headers.cookie',
      '*.password',
      '*.token',
      '*.cardNumber',
      '*.ssn',
      'user.email',        // redact PII fields wholesale, don't allowlist by call site
    ],
    censor: '[Redacted]',
  },
});

logger.info({ user: { id: 1, email: 'a@b.com' }, token: 'abc123' }, 'login');
// -> {"user":{"id":1,"email":"[Redacted]"},"token":"[Redacted]", ...}
```

`redact` is enforced at the logger, not at each call site — that's the
point. A call site that forgets to scrub a field is a bug you'll ship;
a redact path list is a policy you write once and every future call site
inherits for free.

## Correlation IDs via AsyncLocalStorage

The problem: a module-level variable holding "the current request id"
does **not** survive concurrent requests. Node handles many requests
interleaved on one event loop — the instant any handler hits an `await`,
control can return to the loop and pick up a *different* request, and
that request's code will read whatever the module-level variable was
last set to. This isn't a crash. It's silent, and worse, it's
load-dependent: it works perfectly in local testing (one request at a
time) and misattributes request ids under concurrent production traffic,
where you'll see it as "logs for request A appearing inside request B's
trace" during an incident review, weeks after the code shipped.

```js
// WRONG — looks fine under a single manual test. Under concurrent load,
// requestB's handler can overwrite currentRequestId while requestA is
// still mid-flight (paused at an earlier await), and requestA's
// subsequent log lines report requestB's id.
let currentRequestId;

function middleware(req, res, next) {
  currentRequestId = req.id;
  next();
}

function logSomething(msg) {
  logger.info({ requestId: currentRequestId }, msg);   // wrong id, some fraction of the time
}
```

```js
// RIGHT — AsyncLocalStorage gives each async execution context its own
// isolated store. It survives every await, every callback, every
// microtask hop within that request's call chain, and never leaks into
// a concurrently-running request's context.
import { AsyncLocalStorage } from 'node:async_hooks';

export const requestContext = new AsyncLocalStorage();

// middleware: establish the store for the lifetime of this request
function requestContextMiddleware(req, res, next) {
  requestContext.run({ requestId: req.id }, () => next());
}

// pino mixin: runs on every log call, in every logger/child, and injects
// the current context's requestId automatically — no call site needs to
// remember to pass it
const logger = pino({
  mixin() {
    const ctx = requestContext.getStore();
    return ctx ? { requestId: ctx.requestId } : {};
  },
});

// any code anywhere in the request's call graph, however deep, gets the
// right id with zero plumbing
function deepInSomeService() {
  logger.info('doing work');   // automatically carries this request's requestId
}
```

This is the correct default for anything request-scoped: correlation
IDs, trace context, tenant/user id for row-level logging policy, feature
flags resolved once per request. Module-level mutable state for anything
per-request is a bug waiting on enough concurrent traffic to surface.

## Log levels: does it page?

| Level | Meaning | Pages someone? |
|---|---|---|
| `fatal` | Process is about to exit, can't continue | Yes — immediately |
| `error` | Operation failed, request/job failed, needs a human eventually | Depends on rate — one is a ticket, a spike is a page |
| `warn` | Degraded but recovered (retry succeeded, fallback used, slow query) | No — but should show up in a dashboard someone reviews |
| `info` | Normal operational events (request handled, job completed) | No |
| `debug` | Detail useful for local dev or a specific investigation | No — usually disabled in prod |
| `trace` | Line-by-line detail | No — almost never enabled outside active debugging |

Set the boundary explicitly: alerting rules should fire on `error`-rate
thresholds and `fatal` occurrences, not on `warn`. A service that logs
routine retries at `error` trains everyone to ignore error-level alerts,
which is how a real outage gets lost in the noise of "normal" errors.

## Log where you handle, return where you don't

```js
// WRONG — logs the error, then rethrows it. The caller catches it,
// logs it again, then rethrows again. The layer above that logs it a
// third time. One failure, three log lines, three stack traces, and an
// on-call engineer trying to figure out if these are three separate
// incidents or one.
async function chargeCard(orderId) {
  try {
    return await paymentGateway.charge(orderId);
  } catch (err) {
    logger.error({ err, orderId }, 'charge failed');
    throw err;   // rethrown — the next layer logs the same error again
  }
}
```

```js
// RIGHT — the layer that actually handles the error (makes a decision:
// retry, fall back, return a 4xx, mark the order failed) logs it once,
// there. Every layer that just propagates the error upward returns it
// without logging — it isn't the one handling it, so it isn't the one
// that should narrate it.
async function chargeCard(orderId) {
  return paymentGateway.charge(orderId);   // let it propagate, unlogged
}

async function processOrder(orderId) {
  try {
    return await chargeCard(orderId);
  } catch (err) {
    // this layer decides what happens next — that's "handling" it,
    // so this is where it gets logged, once, with the decision made
    logger.error({ err, orderId }, 'charge failed, marking order failed');
    await markOrderFailed(orderId);
    throw new OrderFailedError(orderId);
  }
}
```

The rule: if you catch an error only to add context and rethrow the same
failure unchanged, don't log at that layer — wrap the error with context
(`cause`) and let the layer that terminates the propagation (returns a
response, retries, gives up) do the one log call that matters.

## Metrics with prom-client

```js
import { Counter, Histogram, Gauge, register } from 'prom-client';

// Counter: monotonically increasing count of discrete events
const httpRequestsTotal = new Counter({
  name: 'http_requests_total',
  help: 'Total HTTP requests',
  labelNames: ['method', 'route', 'status_code'],
});

// Histogram: distribution of a value — this is how you get p50/p95/p99
// latency. Buckets MUST be sized to your SLO, not left at the defaults.
// prom-client's default buckets top out around 10s, built for
// "did this eventually finish," not for a service with a 200ms target —
// every request in a healthy 200ms-target service falls into the same
// bottom bucket, and your p95/p99 calculations lose all resolution.
const httpRequestDuration = new Histogram({
  name: 'http_request_duration_seconds',
  help: 'HTTP request duration',
  labelNames: ['method', 'route', 'status_code'],
  buckets: [0.01, 0.025, 0.05, 0.1, 0.15, 0.2, 0.3, 0.5, 1, 2, 5],   // matched to a 200ms SLO
});

// Gauge: a value that goes up and down — pool size, queue depth, active connections
const dbPoolActiveConnections = new Gauge({
  name: 'db_pool_active_connections',
  help: 'Active DB connections in the pool',
});
```

```js
// Fastify hook — record on every response, one place, can't be forgotten
// at a call site the way a manual metric.inc() scattered through handlers can be.
fastify.addHook('onResponse', (req, reply, done) => {
  const route = req.routerPath ?? 'unmatched';   // template, see below — never the raw path
  const labels = { method: req.method, route, status_code: reply.statusCode };
  httpRequestsTotal.inc(labels);
  httpRequestDuration.observe(labels, reply.getResponseTime() / 1000);
  done();
});
```

### Cardinality is the whole game

```js
// WRONG — raw path as a label. Every unique user id, order id, or UUID
// that appears in a URL becomes a distinct label value, and Prometheus
// allocates a new time series per unique label combination. A service
// handling a million distinct user ids creates a million time series
// for this one metric alone. This is how a metrics backend falls over —
// not from request volume, from label cardinality explosion.
httpRequestDuration.observe({ route: req.url }, duration);   // /users/48213, /users/91847, ...

// RIGHT — the route TEMPLATE, not the resolved path. Fastify/Express
// expose this as routerPath/route.path — bounded cardinality no matter
// how many distinct ids get requested.
httpRequestDuration.observe({ route: req.routerPath }, duration);   // /users/:id
```

Never put a user id, order id, session id, or any other high-cardinality
value into a label — not even "just for debugging," because there's no
way to remove a time series once it's been created without restarting
the scrape target's memory. If you need to correlate a specific request
to a specific slow trace, that's what tracing and log correlation ids
are for, not a metric label.

### RED method

For every service, track three things per route: **R**ate (requests/sec),
**E**rrors (error rate), **D**uration (latency distribution). That's the
`httpRequestsTotal` counter sliced by `status_code` for rate and errors,
and the `httpRequestDuration` histogram for duration — three metrics
cover the large majority of "is this service healthy" questions before
you reach for anything more specific.

### The cluster/multi-process gotcha

```js
// WRONG (silently) — if you run multiple worker processes (cluster
// module, PM2 cluster mode, or multiple pods scraped independently but
// you're assuming one aggregate), each worker's prom-client registry
// only knows about requests IT handled. Scraping one worker's /metrics
// gives you that worker's slice, not the process group's total — and if
// your scrape config happens to always hit worker 0, your dashboards
// quietly under-report every multi-worker deployment.
const register = require('prom-client').register;
app.get('/metrics', async (req, res) => {
  res.send(await register.metrics());   // only this worker's counters
});
```

```js
// RIGHT — AggregatorRegistry sums metrics across all cluster workers in
// the primary process before serving /metrics, so a single scrape
// reflects the whole process group.
import cluster from 'node:cluster';
import { AggregatorRegistry } from 'prom-client';

if (cluster.isPrimary) {
  const aggregatorRegistry = new AggregatorRegistry();
  app.get('/metrics', async (req, res) => {
    res.set('Content-Type', aggregatorRegistry.contentType);
    res.send(await aggregatorRegistry.clusterMetrics());
  });
}
```

If you're running one process per pod (the common Kubernetes pattern,
no `cluster` module) this doesn't apply — each pod reports its own view,
and your metrics backend (Prometheus with pod-level scraping, federated
up) is the aggregation layer instead. Know which model you're in;
"one worker under-reports" and "one pod over-reports because Prometheus
already sums across pods" are opposite mistakes from the same confusion.

## Tracing: OpenTelemetry Node SDK

```js
// RIGHT — auto-instrumentation covers HTTP, undici/fetch, most DB
// drivers, and Redis clients out of the box. This must be the FIRST
// thing that runs — before any instrumented module is imported —
// because instrumentation works by patching modules at require/import
// time; import order matters.
// tracing.js — imported first, e.g. via `node --import ./tracing.js app.js`
import { NodeSDK } from '@opentelemetry/sdk-node';
import { getNodeAutoInstrumentations } from '@opentelemetry/auto-instrumentations-node';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http';

const sdk = new NodeSDK({
  traceExporter: new OTLPTraceExporter({ url: process.env.OTEL_EXPORTER_URL }),
  instrumentations: [getNodeAutoInstrumentations()],
  serviceName: process.env.SERVICE_NAME,
});

sdk.start();
```

Run **one instrumentation layer**, not two. A hand-rolled tracing
middleware (manually creating spans, manually propagating `traceparent`
headers) layered on top of auto-instrumentation produces duplicate or
conflicting spans for the same operation, and debugging which layer
"owns" a given span becomes its own investigation. Pick auto-
instrumentation as the default; add manual spans only for business
operations the auto-instrumentation can't see (a multi-step workflow
inside one function), not for anything HTTP/DB/queue-shaped it already
covers.

## Health checks: liveness vs readiness

```js
// RIGHT — /healthz (liveness): process-local ONLY. Answers "is this
// process's event loop alive and able to respond at all" — nothing more.
fastify.get('/healthz', async () => ({ status: 'ok' }));
```

```js
// WRONG — checking the database (or any external dependency) from
// liveness. If the DB has a five-second blip, EVERY pod's liveness probe
// fails simultaneously, and the orchestrator restarts every pod at once —
// you've turned a five-second database blip into a full-service outage,
// with a cold-start cascade on top of it once pods come back and all hit
// the DB at once trying to reconnect.
fastify.get('/healthz', async () => {
  await db.query('SELECT 1');   // wrong probe entirely for this check
  return { status: 'ok' };
});
```

```js
// RIGHT — /readyz (readiness): checks dependencies, with a SHORT timeout,
// because a slow readiness check just delays the "not ready" signal past
// the point it was useful. Failing readiness removes the pod from the
// load balancer WITHOUT restarting it — traffic stops, the process keeps
// running, and it rejoins once the dependency recovers. This is the
// correct response to "the DB is having a blip."
fastify.get('/readyz', async (req, reply) => {
  try {
    await Promise.race([
      db.query('SELECT 1'),
      new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), 1000)),
    ]);
    return { status: 'ready' };
  } catch (err) {
    reply.code(503);
    return { status: 'not ready', reason: err.message };
  }
});
```

Liveness answers "should this process be killed and restarted." Readiness
answers "should this process receive traffic right now." Conflating them
is the single most common health-check mistake, and it's the one that
turns a minor dependency blip into a coordinated self-inflicted outage.

## Profiling

- **`--cpu-prof`**: `node --cpu-prof app.js` writes a `.cpuprofile` file
  on exit — load it in Chrome DevTools or `speedscope` to see where CPU
  time actually goes, instead of guessing from code review.
- **`--heapsnapshot-signal=SIGUSR2`**: start the process with this flag,
  then `kill -USR2 <pid>` in production to dump a heap snapshot on demand
  without restarting the process or attaching a debugger — the safe way
  to investigate a suspected memory leak on a live instance.
- **clinic** (`clinic doctor -- node app.js`): wraps the above into a
  guided flow with a visual report — a good first stop before hand-rolling
  a `--cpu-prof` session.
- **`--inspect` in production is a security problem, not a debugging
  convenience.** It opens a debugger protocol port with no authentication
  by default — anyone who can reach that port can read process memory,
  inject arbitrary code, and exfiltrate secrets held in memory (including
  ones your redaction rules would have hidden in logs). Use the signal-
  based snapshot and `--cpu-prof` mechanisms above instead; they don't
  require an open, unauthenticated debug port sitting on a running
  production process.

## Startup log line: resolved config, secrets redacted

```js
// RIGHT — log what the process actually resolved config to, once, at
// boot. This is the fastest way to answer "which value did prod actually
// use" during an incident, instead of re-deriving it from env var
// precedence rules in your head.
logger.info(
  {
    port: config.port,
    logLevel: config.logLevel,
    databaseHost: config.databaseUrl.hostname,   // host, not full URL with credentials
    featureFlags: config.featureFlags,
    nodeEnv: process.env.NODE_ENV,
    // never: config.databaseUrl (contains password), config.apiKeys, config.jwtSecret
  },
  'starting up with resolved configuration',
);
```

Same redaction discipline as request logging applies here — a startup
line that dumps the full parsed config object verbatim is how a database
password ends up in a log aggregator's search index for the life of your
retention policy.

## Checklist

- [ ] Logs are structured JSON via pino, written to stdout — no file transports, no network transport in the request path
- [ ] `console.log` is not used for anything that ships to prod
- [ ] Child loggers carry request/job context instead of repeating fields at every call site
- [ ] `redact` paths cover every token, password, card number, and PII field, enforced at the logger not the call site
- [ ] Correlation/request IDs flow through `AsyncLocalStorage`, not a module-level variable
- [ ] A pino `mixin` injects the current async context's request id automatically
- [ ] Log levels map to an explicit "does this page" policy, and alerting is wired to that policy
- [ ] Errors are logged once, at the layer that handles them — not logged-and-rethrown at every layer
- [ ] Counter/Histogram/Gauge are used for the right shape of metric; histogram buckets are sized to your actual SLO, not left at library defaults
- [ ] Metric labels are route templates and other bounded values — never raw paths, user ids, or other high-cardinality values
- [ ] RED (Rate, Errors, Duration) is covered for every route
- [ ] Multi-process metrics use `AggregatorRegistry` (cluster) or rely on the scrape layer's aggregation (per-pod) — and you know which model you're in
- [ ] OpenTelemetry auto-instrumentation is the one tracing layer — no duplicate manual span creation for what it already covers
- [ ] `/healthz` is process-local only; `/readyz` checks dependencies with a short timeout
- [ ] `--inspect` is never enabled in a production deployment
- [ ] A startup log line records resolved config with secrets redacted
