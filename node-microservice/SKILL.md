---
name: node-microservice
description: Use when building, scaffolding, or reviewing a Node.js/TypeScript backend service or API — choosing between Express 5, Fastify 5, NestJS 11, Hono or Koa; Prisma 7/Drizzle/Kysely and connection pooling; Redis caching; BullMQ workers; undici and fetch timeouts; pino structured logging; AsyncLocalStorage correlation IDs; OpenTelemetry; Vitest/node:test; ESM vs CommonJS; Dockerfiles and graceful shutdown for Node. Also for "start a Node service", "fetch has no timeout", "Node service OOMKilled", "event loop blocked", "Prisma connection pool exhausted in serverless".
---

# Node.js Microservice

## Overview

A Node service is six things: **config**, an **HTTP surface**, **state** (DB + cache),
**async work**, **outbound calls**, and **operability**. Node's specific hazards are that
**one synchronous line blocks every concurrent request** (single-threaded event loop), and
that **`fetch()` has no default timeout** — so a hung dependency leaks handles until the
process dies.

Verified against the **npm registry and nodejs.org, 2026-08-01** — registry facts, not blog
claims: Node **24.18.1 "Krypton" LTS** (26.5.1 is current non-LTS; 22 "Jod" in maintenance) ·
TypeScript **7.0.2** · Fastify **5.11.0** · Express **5.2.1** · NestJS **11.1.28** ·
Hono **4.12.33** · Prisma **7.9.1** · Drizzle **0.45.2** · pino **10.3.1** ·
BullMQ **6.0.5** · undici **8.9.0** · Zod **4.4.3** · Vitest **4.1.10**.

## When to Use

- Starting a Node/TS service, or adding a route/worker to one
- Choosing a framework, ORM, cache, queue, or test runner
- Reviewing Node service code for production-readiness
- Diagnosing: event-loop blocking, memory growth, OOMKills, pool exhaustion in serverless,
  unhandled rejections crashing the process, ESM/CJS interop errors
- Containerising a Node service (including the PID-1 signal problem)

**Not for:** browser/React work (see `web-frontend`), or CLI tools.

## Step 0: Choose the framework

| If… | Use |
|---|---|
| Default for a new service | **Fastify 5** — schema-based validation *and* serialisation, fast, TS-friendly |
| Team knows Express; huge middleware ecosystem | **Express 5** — note v5 finally fixes async error handling |
| Large app, many teams, want enforced structure + DI | **NestJS 11** — the structure earns its cost above a certain size |
| Edge/Workers/Lambda, tiny cold start | **Hono** — Web-standard `Request`/`Response` |
| Existing Koa codebase | **Koa 3** |

**Fastify's real differentiator is JSON-schema serialisation** — it compiles a serialiser
from your response schema, which is both faster than `JSON.stringify` and prevents
accidentally leaking fields you didn't declare. That second property is a security feature.
Full comparison in references/frameworks.md.

## Quick Reference

| Task | Reach for | Detail |
|---|---|---|
| Framework | Fastify 5 (default) | references/frameworks.md |
| Runtime | **Node 24 LTS**; declare `engines.node` | references/language-runtime.md |
| Validation | **Zod 4** (or Fastify JSON schema) | references/frameworks.md |
| DB | **Prisma 7** or Drizzle; Kysely for pure SQL | references/persistence.md |
| Pooling in serverless | PgBouncer / RDS Proxy / Accelerate | references/persistence.md |
| Cache | ioredis, client reused | references/caching-redis.md |
| Jobs | **BullMQ 6** in a separate worker process | references/messaging.md |
| Outbound HTTP | **undici 8** + `AbortSignal.timeout()` | references/http-clients.md |
| Logging | **pino 10** → JSON on stdout | references/observability.md |
| Request context | **AsyncLocalStorage** | references/observability.md |
| Metrics/tracing | prom-client, OTel Node SDK | references/observability.md |
| Tests | **Vitest 4** or `node:test`; testcontainers | references/testing.md |
| Container | multi-stage, `node:24-slim`, **`--init`** | references/packaging-deploy.md |

## Bootstrap a new service

```
myservice/
  package.json               # "type": "module", engines.node pinned
  src/
    index.ts                 # bootstrap + graceful shutdown only
    config.ts                # Zod-validated env, parsed at import
    server.ts                # framework wiring, routes, error handler
    routes/
    services/                # business logic — no HTTP or SQL types
    repositories/            # DB access
    clients/                 # outbound HTTP
  test/
  Dockerfile
```

1. **`"type": "module"`** and **`engines.node: ">=24"`**. Decide ESM once — the mixed state is
   the top source of "works locally, breaks in CI".
2. **Zod-parse `process.env` at import** so a missing var crashes at boot, not on the first
   request that needs it.
3. One **undici `Agent`** and one DB pool, created once and injected.
4. `AsyncLocalStorage` for the request ID; pino child logger bound to it.
5. `/healthz` (liveness, process-local) and `/readyz` (readiness, checks deps).
6. **Graceful shutdown**: fail readiness → LB propagation delay → `server.close()` → drain →
   close pools.
7. `--init` (or dumb-init) in the container, because **Node as PID 1 doesn't reap zombies and
   mishandles signals**.

## The non-negotiables

1. **Every `fetch`/undici call has a timeout.** `fetch()` has **none** by default. Use
   `AbortSignal.timeout(ms)`. In real codebases this is the most-violated rule — one audit
   found 45 `fetch` calls and a single `AbortController`.
2. **Never block the event loop.** No sync crypto, no sync `fs` in a request path, no
   CPU-bound loops. Offload to `worker_threads`.
3. **Config validated at boot.** Fail fast.
4. **One client per process**, created at startup — never per request. A per-request client
   discards connection pooling entirely.
5. **`AsyncLocalStorage` for request context.** A module-level variable does **not** survive
   `await` — it will silently serve one request's ID to another.
6. **Handle `unhandledRejection`.** Modern Node **crashes the process** by default. Know
   whether you want that (usually yes — but log it first).
7. **`--max-old-space-size` below the container limit.** V8 otherwise sizes the heap from the
   host and gets OOMKilled.
8. **`--init` in the container.** Node as PID 1 leaves zombies and mishandles SIGTERM.
9. **Idempotent queue consumers.** BullMQ retries; at-least-once is what you get.
10. **Liveness must not check dependencies.** One DB blip otherwise restarts every pod and
    turns a blip into an outage.

## Reference Map

| File | Read when |
|---|---|
| references/language-runtime.md | Node versions, event loop, workers, ESM/CJS, memory, AsyncLocalStorage, TS 7 |
| references/frameworks.md | Framework comparison and depth; Express 5 changes; validation |
| references/persistence.md | Prisma/Drizzle/Kysely, pooling (incl. serverless), transactions, migrations |
| references/caching-redis.md | Client config, cache-aside, stampede, locks, eviction |
| references/messaging.md | BullMQ, SQS/Kafka, idempotency, DLQ, worker shutdown |
| references/http-clients.md | **fetch timeouts**, undici, retries, breakers, pooling |
| references/observability.md | pino, AsyncLocalStorage IDs, metrics, OTel, health endpoints |
| references/testing.md | Vitest/node:test, testcontainers, HTTP tests, mocking |
| references/packaging-deploy.md | package.json, Docker, PID 1, graceful shutdown, config |

## Common Mistakes

| Mistake | Why it hurts | Fix |
|---|---|---|
| `fetch(url)` with no signal | **No default timeout** — hangs forever, leaks the handle | `AbortSignal.timeout(5000)` |
| `axios` and `fetch` in one codebase | Two timeout stories, two error shapes, two interceptor mechanisms | Pick one — undici in Node |
| Client created per request | Discards connection pooling; TLS handshake every call | Construct once, inject |
| Module-level "current request" variable | Silently leaks context across concurrent requests | `AsyncLocalStorage` |
| Sync work in a handler | Blocks **every** concurrent request | `worker_threads` / async APIs |
| No `engines.node` | npm won't warn; prod silently differs from local | Declare it |
| ESM/CJS decided per-file | Import errors that only appear in CI | `"type": "module"` project-wide |
| Prisma default pool in Lambda | Each invocation opens a pool → Postgres exhausted | PgBouncer/RDS Proxy/Accelerate |
| No `--max-old-space-size` | V8 sizes from the host, not the cgroup → OOMKill | Set below the container limit |
| Node as PID 1 without `--init` | Zombies accumulate; SIGTERM mishandled | `--init` or dumb-init |
| `console.log` in production | Unstructured, unqueryable, sync on some streams | pino, JSON to stdout |
| Migrations from app startup | N replicas race the same migration | Separate job/step |
| Liveness probe hitting the DB | One blip restarts every pod at once | Liveness = process-local only |
| Raw path in a metric label | Unbounded cardinality kills Prometheus | Route template |
| Zod majors split across repos | Schemas can't be shared across services | Align majors org-wide |
