/**
 * Production-shaped Fastify service entry point.
 *
 * Copy to src/index.ts and adapt. It demonstrates the things that cause incidents
 * when omitted:
 *
 *   - config Zod-parsed at import, so a missing var crashes at boot
 *   - AsyncLocalStorage request context (the only thing that survives `await`)
 *   - one undici Agent + one DB pool, created once
 *   - liveness vs readiness as SEPARATE checks
 *   - graceful shutdown in the correct order, with a pre-stop drain delay
 *   - every outbound call with a timeout — fetch has none by default
 *
 * See the node-microservice skill's references/ for the reasoning behind each.
 */

import { AsyncLocalStorage } from "node:async_hooks";
import { randomUUID } from "node:crypto";
import Fastify, { type FastifyInstance } from "fastify";
import { Agent, request as undiciRequest } from "undici";
import pino from "pino";
import { z } from "zod";

// ---------------------------------------------------------------------------
// Config — parsed at import. A bad env crashes the process at startup rather
// than surfacing as a 500 on whichever request first needs the missing value.
// ---------------------------------------------------------------------------

const ConfigSchema = z.object({
  NODE_ENV: z.enum(["development", "test", "production"]).default("development"),
  PORT: z.coerce.number().int().positive().default(8080),
  LOG_LEVEL: z.enum(["fatal", "error", "warn", "info", "debug", "trace"]).default("info"),

  DATABASE_URL: z.string().url(),                     // no default => required
  DB_POOL_MAX: z.coerce.number().int().min(1).max(100).default(10),

  UPSTREAM_BASE_URL: z.string().url(),
  UPSTREAM_TIMEOUT_MS: z.coerce.number().int().positive().default(5_000),

  // Endpoint removal is eventually consistent: requests keep arriving for a
  // second or two AFTER SIGTERM. Skipping this delay is the usual cause of
  // 5xx on every deploy.
  PRE_SHUTDOWN_DELAY_MS: z.coerce.number().int().min(0).default(3_000),
  SHUTDOWN_TIMEOUT_MS: z.coerce.number().int().positive().default(20_000),
});

const config = ConfigSchema.parse(process.env);

// ---------------------------------------------------------------------------
// Request context via AsyncLocalStorage
//
// A module-level `let currentRequestId` does NOT survive an `await`: many
// requests share one thread and interleave at every suspension point, so they
// overwrite each other's value. The bug is silent and load-dependent — you get
// one request's ID attached to another's logs. ALS is the only correct mechanism.
// ---------------------------------------------------------------------------

type RequestContext = { requestId: string };
const als = new AsyncLocalStorage<RequestContext>();

export const currentRequestId = (): string => als.getStore()?.requestId ?? "-";

const logger = pino({
  level: config.LOG_LEVEL,
  // Structured JSON to stdout. Never a file (the runtime collects stdout) and
  // never a network transport in the request path (that's a dependency that
  // can block your handler).
  ...(config.NODE_ENV === "development"
    ? { transport: { target: "pino-pretty" } }
    : {}),
  // Injected into every line automatically — no threading a logger through
  // every function signature.
  mixin: () => ({ requestId: currentRequestId() }),
  redact: {
    paths: [
      "req.headers.authorization",
      "req.headers.cookie",
      'req.headers["x-api-key"]',
      "*.password",
      "*.token",
      "*.cardNumber",
    ],
    censor: "[REDACTED]",
  },
  base: { service: "myservice", version: process.env.APP_VERSION ?? "dev" },
});

// ---------------------------------------------------------------------------
// Shared clients — constructed ONCE. A per-request client throws away
// connection pooling entirely: a fresh TCP + TLS handshake on every call.
// ---------------------------------------------------------------------------

const httpAgent = new Agent({
  connect: { timeout: 2_000 },      // TCP + TLS
  headersTimeout: 5_000,            // time to first byte of the response
  bodyTimeout: 10_000,              // stall detection while streaming the body
  keepAliveTimeout: 30_000,
  connections: 64,                  // per-origin pool size
});

/** Outbound call with a hard deadline. `fetch()` has NO default timeout. */
export async function callUpstream(path: string, signal?: AbortSignal): Promise<unknown> {
  // AbortSignal.any lets a caller's cancellation AND our own deadline both apply.
  const timeout = AbortSignal.timeout(config.UPSTREAM_TIMEOUT_MS);
  const combined = signal ? AbortSignal.any([signal, timeout]) : timeout;

  const res = await undiciRequest(`${config.UPSTREAM_BASE_URL}${path}`, {
    dispatcher: httpAgent,
    signal: combined,
    headers: { "x-request-id": currentRequestId() },   // propagate for tracing
  });

  if (res.statusCode >= 400) {
    // Bound the read: a misbehaving upstream must not stream you a gigabyte
    // of error text.
    const body = (await res.body.text()).slice(0, 2_000);
    throw new UpstreamError(res.statusCode, body);
  }
  return res.body.json();
}

class UpstreamError extends Error {
  constructor(readonly status: number, readonly body: string) {
    super(`upstream returned ${status}`);
    this.name = "UpstreamError";
  }
}

// ---------------------------------------------------------------------------
// Server
// ---------------------------------------------------------------------------

let shuttingDown = false;

function buildServer(): FastifyInstance {
  const app = Fastify({
    loggerInstance: logger,
    // Fastify generates one if absent; trust an inbound id only from your own edge.
    genReqId: (req) => (req.headers["x-request-id"] as string) ?? randomUUID(),
    requestIdHeader: "x-request-id",
    bodyLimit: 1_048_576,             // 1 MB — reject oversized bodies early
    disableRequestLogging: false,
  });

  // Bind the ALS store for the whole request lifecycle.
  app.addHook("onRequest", (req, reply, done) => {
    reply.header("x-request-id", req.id);
    als.run({ requestId: String(req.id) }, done);
  });

  // LIVENESS: "is this process functioning?" It must NOT touch dependencies.
  // If it pings the DB, one DB blip restarts every pod simultaneously and turns
  // a transient blip into a full outage.
  app.get("/healthz", async () => ({ status: "ok" }));

  // READINESS: "should I get traffic right now?" Checks only what we cannot
  // serve without, with a short timeout. Optional deps (a bypassable cache)
  // must not fail readiness.
  app.get("/readyz", async (_req, reply) => {
    if (shuttingDown) return reply.code(503).send({ status: "shutting_down" });
    try {
      await db.query("SELECT 1", { timeout: 2_000 });
      return { status: "ready" };
    } catch (err) {
      app.log.warn({ err }, "readiness check failed");
      return reply.code(503).send({ status: "db_unavailable" });
    }
  });

  // Fastify response schemas are worth using for more than validation: it
  // compiles a serialiser, which is faster than JSON.stringify AND prevents
  // leaking fields you did not declare.
  app.get(
    "/users/:id",
    {
      schema: {
        params: { type: "object", required: ["id"], properties: { id: { type: "string" } } },
        response: {
          200: {
            type: "object",
            properties: { id: { type: "string" }, email: { type: "string" } },
          },
        },
      },
    },
    async (req) => {
      const { id } = req.params as { id: string };
      return userService.get(id);
    },
  );

  // One error envelope for the whole service.
  app.setErrorHandler((err, req, reply) => {
    const status = err.statusCode ?? 500;
    if (status >= 500) req.log.error({ err }, "request failed");
    else req.log.warn({ err }, "request rejected");

    reply.code(status).send({
      error: {
        code: status >= 500 ? "internal_error" : (err.code ?? "bad_request"),
        // Never leak an internal message to a client on a 5xx.
        message: status >= 500 ? "internal server error" : err.message,
        requestId: req.id,
      },
    });
  });

  return app;
}

// ---------------------------------------------------------------------------
// Bootstrap + graceful shutdown
// ---------------------------------------------------------------------------

async function main(): Promise<void> {
  const app = buildServer();

  // Modern Node CRASHES on an unhandled rejection. Log it first so the crash is
  // diagnosable, then let it die — a process in an unknown state should not serve.
  process.on("unhandledRejection", (reason) => {
    logger.fatal({ reason }, "unhandled rejection — exiting");
    process.exit(1);
  });
  process.on("uncaughtException", (err) => {
    logger.fatal({ err }, "uncaught exception — exiting");
    process.exit(1);
  });

  await app.listen({ port: config.PORT, host: "0.0.0.0" });
  logger.info(
    { port: config.PORT, env: config.NODE_ENV, heapLimitMb: heapLimitMb() },
    "listening",
  );

  const shutdown = async (signal: string): Promise<void> => {
    if (shuttingDown) return;
    shuttingDown = true;
    logger.info({ signal }, "shutdown starting");

    // 1. Readiness already failing (flag above). Wait for the load balancer to
    //    notice before we stop accepting — this is the deliberate part.
    await sleep(config.PRE_SHUTDOWN_DELAY_MS);

    const timer = setTimeout(() => {
      logger.error("graceful shutdown timed out — forcing exit");
      process.exit(1);
    }, config.SHUTDOWN_TIMEOUT_MS);
    timer.unref();

    try {
      await app.close();          // 2. stop accepting, drain in-flight
      await stopWorkers();        // 3. finish the current job, stop consuming
      await db.end();             // 4. close pools LAST — in-flight work needs them
      await httpAgent.close();
      logger.info("shutdown complete");
      process.exit(0);
    } catch (err) {
      logger.error({ err }, "error during shutdown");
      process.exit(1);
    }
  };

  for (const sig of ["SIGTERM", "SIGINT"] as const) {
    process.on(sig, () => void shutdown(sig));
  }
}

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));
const heapLimitMb = () =>
  Math.round(require("node:v8").getHeapStatistics().heap_size_limit / 1024 / 1024);

void main();
