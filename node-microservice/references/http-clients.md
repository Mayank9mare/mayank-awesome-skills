# HTTP clients in Node

## The single most common production incident in Node services

**`fetch()` has no default timeout.** Not a short one, not a generous
one — none. A downstream service that stops responding (not errors —
just never answers) turns your call into a promise that never resolves,
and every concurrent request piling up behind it holds its own memory,
its own event-loop bookkeeping, and often a database connection or two,
until something else finally kills the process.

This isn't theoretical. A recent audit across four production repos found
`fetch()` called 45 times total, with exactly **one** `AbortController` in
use anywhere. The other 44 call sites would hang indefinitely against a
hung downstream. The same audit found `fetch` and `axios` mixed within a
single codebase — two different timeout defaults, two different retry
behaviors, two different error shapes to handle, often in the same file.

```js
// WRONG — this is the default state of nearly every fetch() call in the wild.
// If example.com never responds, this await never resolves. No timeout,
// no error, just a request that hangs forever and a caller that hangs with it.
async function getUser(id) {
  const res = await fetch(`https://example.com/users/${id}`);
  return res.json();
}

// RIGHT — every outbound fetch gets an explicit timeout, no exceptions
async function getUser(id) {
  const res = await fetch(`https://example.com/users/${id}`, {
    signal: AbortSignal.timeout(5000),   // aborts and rejects after 5s, no manual controller needed
  });
  if (!res.ok) throw new Error(`upstream ${res.status}`);
  return res.json();
}
```

`AbortSignal.timeout(ms)` is the modern, correct default — it's built into
the platform (Node 18+), needs no manual `setTimeout`/`clearTimeout`
bookkeeping, and composes with other signals via `AbortSignal.any()`:

```js
// Combine a per-call timeout with a caller-supplied cancellation signal
// (e.g. the incoming request's own abort, propagated downstream)
async function getUser(id, { signal } = {}) {
  const combined = AbortSignal.any([
    AbortSignal.timeout(5000),
    ...(signal ? [signal] : []),
  ]);
  const res = await fetch(`https://example.com/users/${id}`, { signal: combined });
  if (!res.ok) throw new Error(`upstream ${res.status}`);
  return res.json();
}
```

If you must support environments without `AbortSignal.any` (very old
runtimes only — not a concern on Node 24), fall back to a manual
`AbortController` wired to both a timer and the parent signal. On any
current Node LTS, there's no reason to.

## undici: the client Node's `fetch` is actually built on

Node's global `fetch` is undici under the hood. For anything beyond
default behavior — connection pooling tuning, custom timeouts at the
socket level, proxy support — reach for undici directly rather than
layering a third-party client on top of a `fetch` that's already undici
underneath it:

```js
import { Agent, fetch, setGlobalDispatcher } from 'undici';

const agent = new Agent({
  connect: { timeout: 2000 },       // TCP+TLS handshake timeout
  headersTimeout: 5000,             // time to receive response headers
  bodyTimeout: 10000,               // time to receive the full response body
  keepAliveTimeout: 30000,          // how long an idle connection stays in the pool
  connections: 50,                  // max connections per origin, pooled and reused
});

setGlobalDispatcher(agent);   // applies to every global fetch() call in the process
```

Per-origin `Agent` pooling is why undici outperforms axios for high-volume
outbound traffic in Node: axios (built on Node's older `http`/`https`
modules by default) doesn't give you this level of connection-pool control
without dropping into `http.Agent` configuration yourself, and mixing
axios's `http.Agent` tuning with a separately-tuned `fetch`/undici `Agent`
in the same service means tuning two independent connection pools instead
of one. Pick one HTTP client library per service — the real-world failure
mode isn't "axios is bad," it's running both simultaneously with neither
one tuned, or tuned inconsistently.

| | undici / `fetch` | axios |
|---|---|---|
| Timeout control | `AbortSignal.timeout`, `Agent` headers/body/connect timeouts | `timeout` option (covers total request only, not TCP/headers separately) |
| Connection pooling | `Agent` with per-origin tuning, built for Node's event loop | `http.Agent`/`https.Agent`, same underlying Node primitives but less integrated |
| Interceptors | Manual (`RoundTripper`-equivalent via a wrapping function) | Built-in interceptor chain |
| Bundle/runtime weight | Built into Node — zero extra dependency for basic use | Extra dependency, but small |
| Browser + Node parity | `fetch` API works in both | Works in both, historically why teams picked it pre-`fetch` |

Axios remains a fine choice for teams already standardized on it,
especially for its interceptor ergonomics. The problem is never the
library — it's two libraries in one codebase with two different timeout
defaults, or a fetch call with no timeout because nobody thought to add
one for something this "simple."

## Retries: idempotent and transient only

```js
// WRONG — retries everything, including a 400 (client error, will never
// succeed no matter how many times you retry) and a non-idempotent POST
// that might have already succeeded server-side on the "failed" attempt
async function callWithRetry(url, options) {
  for (let i = 0; i < 5; i++) {
    try {
      return await fetch(url, options);
    } catch {
      // retry immediately, no backoff, no check on method or status
    }
  }
}
```

```js
// RIGHT — retry only transient failures, only on safe methods, capped,
// with full-jitter backoff, honoring Retry-After when present
async function fetchWithRetry(url, options = {}, maxAttempts = 4) {
  const idempotent = ['GET', 'HEAD', 'PUT', 'DELETE'].includes(options.method ?? 'GET');

  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    let res;
    try {
      res = await fetch(url, { ...options, signal: AbortSignal.timeout(5000) });
    } catch (err) {
      if (attempt === maxAttempts) throw err;
      await sleep(backoffMs(attempt));
      continue;
    }

    if (res.ok) return res;
    if (!idempotent) return res;              // never blindly retry a POST/PATCH
    if (![429, 502, 503, 504].includes(res.status)) return res;   // not a transient failure
    if (attempt === maxAttempts) return res;

    const retryAfter = res.headers.get('retry-after');
    await sleep(retryAfter ? Number(retryAfter) * 1000 : backoffMs(attempt));
  }
}

function backoffMs(attempt) {
  const base = Math.min(1000 * 2 ** attempt, 10_000);   // exponential, capped
  return Math.random() * base;                            // full jitter — avoids synchronized retry storms
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
```

Rules, in order of how often they're violated:

- Cap attempts. Unbounded retry loops are a self-inflicted denial-of-service
  against whatever you're calling.
- Only retry safe/idempotent methods automatically. A POST that creates a
  resource might have succeeded on the attempt that appeared to fail (the
  response was lost, not the request) — retrying blindly can create the
  resource twice. If a POST must be retryable, give it an `Idempotency-Key`
  header the server can deduplicate on, and only then treat it as safe to
  retry.
- Only retry transient status codes (429, 502, 503, 504) and network-level
  failures — never a 4xx that isn't 429. A 400 will be a 400 again.
- Honor `Retry-After` when the server sends one — it knows its own recovery
  time better than your guess does.
- Retry in exactly one layer of the call stack. If both your HTTP client
  wrapper and the caller retry independently, a transient failure fans out
  into `attempts_outer × attempts_inner` actual requests against the
  downstream — precisely the pile-on you were trying to avoid.

## Circuit breaker

Retries handle a single flaky call; a circuit breaker handles a
*consistently* failing dependency — stop calling it for a while so your
own service doesn't spend all its capacity waiting on timeouts against
something that's already down, and so the downstream gets a chance to
recover without a continuous retry storm from every caller.

```js
import CircuitBreaker from 'opossum';

const breaker = new CircuitBreaker(
  (id) => fetchWithRetry(`https://example.com/users/${id}`),
  {
    timeout: 5000,               // if the call takes longer than this, count it as a failure
    errorThresholdPercentage: 50, // trip open once 50% of recent calls fail
    volumeThreshold: 20,          // ...but only after at least 20 calls, so one bad blip doesn't trip it
    resetTimeout: 30_000,         // stay open 30s before trying a single test request (half-open)
  },
);

breaker.on('open', () => logger.warn('circuit open: user-service'));
breaker.on('halfOpen', () => logger.info('circuit half-open: user-service'));
breaker.on('close', () => logger.info('circuit closed: user-service'));

breaker.fallback(() => ({ id: null, degraded: true }));   // always have a fallback

async function getUser(id) {
  return breaker.fire(id);
}
```

- One breaker instance per *dependency*, not one global breaker — a failing
  payments API shouldn't trip the breaker guarding an unrelated search API.
- Don't count 4xx responses as breaker failures (same reasoning as
  retries) — a breaker that trips because clients are sending bad requests
  is measuring the wrong thing.
- Log every state transition; a breaker stuck open silently is a
  "why is this feature broken" incident days later, not an alert now.
- Always define a fallback (a cached value, a degraded response, a queued
  retry-later) — a breaker with no fallback just converts a slow failure
  into a fast one, which is an improvement, but not a fix.

## Never one client per request

```js
// WRONG — undici Agent (or an axios instance) created per call. Defeats
// connection pooling entirely: every request pays a fresh TCP+TLS handshake,
// and under load this alone can dominate latency more than the actual
// downstream response time.
async function getUser(id) {
  const agent = new Agent({ connections: 10 });
  return fetch(`https://example.com/users/${id}`, { dispatcher: agent });
}

// RIGHT — one Agent/client per origin, constructed once at module scope,
// reused for the life of the process
const userServiceAgent = new Agent({
  connect: { timeout: 2000 },
  keepAliveTimeout: 30000,
  connections: 50,
});

async function getUser(id) {
  return fetch(`https://example.com/users/${id}`, { dispatcher: userServiceAgent });
}
```

Same rule as the DB pool and the Redis client elsewhere in this skill:
expensive, reusable resources get created once and shared, not
reconstructed per call. An HTTP client's connection pool is exactly that
kind of resource.

## Propagating trace headers

A retried, circuit-broken, timeout-bounded call is still invisible in your
tracing if it doesn't carry the calling request's trace context downstream:

```js
async function callDownstream(url, options, ctx) {
  return fetch(url, {
    ...options,
    headers: {
      ...options.headers,
      'traceparent': ctx.traceparent,   // W3C Trace Context — propagate, don't regenerate
      'x-request-id': ctx.requestId,
    },
    signal: AbortSignal.timeout(5000),
  });
}
```

If you're using the OpenTelemetry Node SDK with undici's built-in
instrumentation (see observability.md), this propagation happens
automatically for every `fetch`/undici call in the process — one more
reason to standardize on undici/`fetch` rather than hand-rolling equivalent
plumbing around a second HTTP client library that the auto-instrumentation
doesn't cover as cleanly.

## Checklist

- [ ] Every `fetch()`/HTTP call has an explicit timeout — `AbortSignal.timeout()` at minimum, no exceptions
- [ ] Caller-supplied cancellation signals are combined via `AbortSignal.any()`, not dropped
- [ ] One HTTP client library standardized per service — not `fetch` and `axios` coexisting untuned
- [ ] Connection pooling (`undici.Agent` or equivalent) tuned per origin: connect/headers/body timeouts, `keepAliveTimeout`
- [ ] Retries limited to idempotent methods and transient status codes (429/502/503/504), capped, with full-jitter backoff
- [ ] `Retry-After` respected when present
- [ ] Retries happen in exactly one layer of the call stack
- [ ] A circuit breaker exists per external dependency, with a defined fallback and logged state transitions
- [ ] HTTP clients/agents are constructed once per process, never per request
- [ ] Trace context (`traceparent` or equivalent) propagates on every outbound call
