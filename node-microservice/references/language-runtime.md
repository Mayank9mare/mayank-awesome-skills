# The Node runtime

## Which version

| Version | Codename | Status | Notes |
|---|---|---|---|
| 24.18.1 | Krypton | **LTS** (target this) | `require(esm)`, permission model stable, native TS strip |
| 26.5.1 | — | Current | New features land here first; not for production services |
| 22.x | Jod | Maintenance | Security fixes only; migrate off it |
| 18.x / 20.x | — | EOL / EOL soon | Do not start new services here |

Target **24.18.1 LTS**. Pin it in `.nvmrc`, `package.json#engines`, and your
Dockerfile's `FROM` line — three places, one number, or they drift.

```json
// package.json
{
  "engines": { "node": ">=24.18 <25" }
}
```

`engines` doesn't block installs by default — it's advisory unless you run
`npm ci --engine-strict` or a preinstall check. Set it anyway; it's the first
place a new hire looks, and CI can enforce it even if npm won't.

## The event loop

Node is single-threaded for JS execution, backed by libuv for I/O. One loop,
six phases, repeating:

```
   ┌───────────────────────┐
┌─>│           timers          │  setTimeout/setInterval callbacks whose delay elapsed
│  ├───────────────────────┤
│  │     pending callbacks     │  I/O callbacks deferred from the previous loop
│  ├───────────────────────┤
│  │       idle, prepare       │  internal use
│  ├───────────────────────┤
│  │           poll            │  fetch new I/O events; execute I/O callbacks
│  ├───────────────────────┤
│  │           check           │  setImmediate callbacks
│  ├───────────────────────┤
│  │     close callbacks       │  socket.on('close', ...), etc.
│  └───────────────────────┘
└──────────────────────────┘
```

**Microtasks vs macrotasks**: Promise `.then`/`.catch`/`.finally` callbacks and
`queueMicrotask` are microtasks. They drain completely — every one queued, plus
every one queued *during* that draining — before the loop moves to the next
phase or the next macrotask (`setTimeout`, `setImmediate`, I/O callback). This
is why a promise chain that keeps re-scheduling itself can starve timers
indefinitely; it's a real production bug shape, not a trivia fact.

```js
setTimeout(() => console.log('timeout'), 0);
Promise.resolve().then(() => console.log('promise'));
console.log('sync');
// sync, promise, timeout — every time
```

### Why a synchronous loop blocks everything

There is one thread running your JS. A `while` loop, a synchronous
`JSON.parse` on a 50MB payload, `crypto.pbkdf2Sync`, a regex with catastrophic
backtracking — any of these hold the thread, and *every other request your
process is handling stalls*, including health checks. This is the single
biggest architectural difference from a thread-per-request runtime: one bad
request can take down a whole process's throughput, not just its own.

```js
// WRONG — synchronous CPU work in a request handler blocks the entire process
app.get('/hash', (req, res) => {
  const hash = crypto.pbkdf2Sync(req.query.pw, salt, 600_000, 64, 'sha512');
  res.json({ hash: hash.toString('hex') });
});

// RIGHT — offload to a worker thread, keep the event loop free
app.get('/hash', async (req, res) => {
  const hash = await hashPool.run({ pw: req.query.pw });
  res.json({ hash: hash.toString('hex') });
});
```

Never trust "it's just a for-loop, it'll be fast." Under load, milliseconds of
blocking per request multiply into seconds of added tail latency for everyone
queued behind it.

## worker_threads vs child_process vs cluster

| Mechanism | Shares memory? | Use for |
|---|---|---|
| `worker_threads` | Yes (via `SharedArrayBuffer`/transfer) | CPU-bound work that needs to stay in-process: hashing, image resize, parsing |
| `child_process` | No (separate process, IPC) | Running another program, isolating a crash-prone dependency, different runtime/language |
| `cluster` | No (separate processes, shared listen socket) | Scaling a web server across CPU cores on one machine |

`worker_threads` is the right tool for CPU-bound work you want *inside* your
service's lifecycle — it's cheaper than a process (no new V8 isolate startup
cost is avoidable, but no separate event loop bootstrap of an OS process,
either), and `MessagePort`/`SharedArrayBuffer` let you move data without
serializing through IPC.

```js
// worker-pool.js — use piscina in real code; this shows the primitive
import { Worker } from 'node:worker_threads';
import os from 'node:os';

const pool = Array.from({ length: os.availableParallelism() }, () =>
  new Worker(new URL('./hash-worker.js', import.meta.url)),
);

// prefer a maintained pool library (piscina) over hand-rolling round-robin
// dispatch + backpressure + worker-crash recovery yourself
```

`cluster` scales HTTP throughput across cores by forking N processes that
share a listening socket (the OS round-robins accepted connections). It does
NOT share memory — no shared in-process cache, no shared rate-limiter state.
Every clustered process needs its own DB pool, which multiplies your total
connection count by worker count; account for that in pool sizing (see
`persistence.md`). Prefer letting your orchestrator (Kubernetes) scale
*replicas* over hand-rolling `cluster`, unless you're optimizing single-VM
throughput without an orchestrator in front.

`child_process.spawn`/`exec`/`fork` is for running something that isn't "more
of your own event loop" — a subprocess, a CLI tool, a legacy script. `fork()`
is a specialization that also gives you an IPC channel to a child Node
process; it predates `worker_threads` and has higher per-instance overhead.

## CPU-bound work in Node

The honest answer: Node is bad at CPU-bound work, on purpose — it's built for
I/O concurrency, not compute parallelism. Options, in order of preference:

1. **Push it to a language built for it** — a Rust/Go sidecar, a native
   addon, or a call to a service that already does this well.
2. **`worker_threads` pool** for moderate CPU work you want to keep in Node
   (JSON transforms, crypto, image thumbnailing).
3. **Chunk it and yield** — for work you can't move, break it into pieces and
   yield to the event loop (`setImmediate` between chunks) so it doesn't
   starve other requests. This doesn't make the work faster; it makes the
   *service* more responsive while the work happens.

Never reach for a bigger instance to fix CPU-bound blocking — that treats the
symptom. The fix is architectural: get compute off the request thread.

## Streams and backpressure

Streams let you process data without holding all of it in memory —
critical for large file uploads/downloads, request/response bodies, and
proxying. **Backpressure** is the mechanism that keeps a fast producer from
overrunning a slow consumer.

```js
// WRONG — reads the whole file into memory before writing anything
const data = await fs.readFile('big.csv');
await fs.writeFile('out.csv', transform(data));

// RIGHT — constant memory regardless of file size; write.write() return
// value signals backpressure and pipeline() handles it (and cleans up on
// error, which manual .pipe() chains famously don't)
import { pipeline } from 'node:stream/promises';
import { createReadStream, createWriteStream } from 'node:fs';
import { Transform } from 'node:stream';

await pipeline(
  createReadStream('big.csv'),
  new Transform({
    transform(chunk, enc, cb) { cb(null, transformChunk(chunk)); },
  }),
  createWriteStream('out.csv'),
);
```

If you write to a stream manually, respect the return value of `.write()`:
`false` means the internal buffer is full — stop writing and wait for
`'drain'`. Ignoring this is the most common cause of a Node process's memory
climbing unboundedly while proxying large payloads.

## AsyncLocalStorage for request context

You need per-request context (request ID, user, trace span) accessible deep
in a call stack without threading it through every function signature. A
module-level variable **cannot** do this correctly, because Node interleaves
requests on one thread:

```js
// WRONG — module-level variable. Request B overwrites it before request A's
// awaited work resumes, because both are running "concurrently" on one thread.
let currentRequestId;

app.use((req, res, next) => {
  currentRequestId = req.headers['x-request-id'];   // race: B can overwrite this
  next();
});

async function logSomething() {
  await someAsyncWork();               // <- event loop can run request B's
  console.log(currentRequestId);       //    handler here, mutating the variable
}
```

`AsyncLocalStorage` fixes this by binding a context object to the *async
execution chain* — every `await`, `.then`, `setTimeout`, and callback spawned
within `run()` sees the same context, and it's isolated from other concurrent
chains automatically:

```js
// context.js
import { AsyncLocalStorage } from 'node:async_hooks';
export const requestContext = new AsyncLocalStorage();

// middleware.js
app.use((req, res, next) => {
  const ctx = { requestId: req.headers['x-request-id'] ?? crypto.randomUUID() };
  requestContext.run(ctx, () => next());   // everything inside next()'s async chain gets ctx
});

// anywhere.js — no parameter threading needed
function logSomething(msg) {
  const ctx = requestContext.getStore();
  logger.info({ requestId: ctx?.requestId }, msg);
}
```

This is the mechanism `pino`'s correlation-ID pattern and most Node APM
libraries build on (see `observability.md`). There is a per-call overhead
(context propagation isn't free), but it's small relative to I/O latency in a
typical service — measure before rejecting it on performance grounds.

## Memory

Node's default V8 old-space heap limit was historically ~1.5–2GB regardless
of container size. Modern Node (18+) auto-detects available memory better,
but **you should still set it explicitly** — the failure mode of not doing so
is a container OOM-killed by the orchestrator with no heap dump, no graceful
shutdown, no log line, just `137`.

```dockerfile
# Must be below the container memory limit, with headroom for:
# - V8's own overhead beyond old-space (new space, code space, external buffers)
# - non-heap memory: Buffers, native addons, thread stacks
# Rule of thumb: old-space = ~75% of container limit.
ENV NODE_OPTIONS="--max-old-space-size=1536"
# for a container limited to 2048Mi
```

If you set it *above* the container limit, V8 happily grows the heap until
the kernel OOM-kills the process — which looks identical to a real memory
leak in your metrics, wasting a debugging session. If you don't set it at
all, V8 guesses based on total host memory, which in a container is often
wrong (it may see the *node's* memory, not the container's cgroup limit).

**Diagnosing leaks**: take heap snapshots under load and diff them.

```bash
node --inspect=0.0.0.0:9229 server.js
# then, from Chrome DevTools -> Memory tab -> attach to remote target,
# or programmatically:
node -e "require('v8').writeHeapSnapshot()"
```

Never expose `--inspect` on a public interface in production — it's an
unauthenticated debugger with full process access. Bind to localhost and
tunnel, or gate behind a sidecar that requires auth.

## Unhandled rejections and uncaught exceptions

**This changed and it matters**: since Node 15, an unhandled promise
rejection's default behavior is to **crash the process** (`--unhandled-
rejections=strict`, now default). Older code that relied on rejections being
silently logged will now take the whole service down on the first
un-caught rejection. This is the right default — a rejection nobody's
handling means your program's state is unknown — but it means you must
audit for it, not opt into it.

```js
// This crashes the process on modern Node if getUserAsync rejects and
// nothing downstream has a .catch or try/catch around the await.
async function handler(req, res) {
  const user = getUserAsync(req.params.id);   // missing `await` — returns a Promise
  res.json(user);                               // sends a Promise, not the data
}
```

Belt-and-suspenders top-level handlers, but treat them as a last resort for
logging + fast, clean exit — never as a substitute for handling errors at
the call site:

```js
process.on('unhandledRejection', (reason, promise) => {
  logger.fatal({ reason }, 'unhandled rejection');
  // Give in-flight logs/metrics a moment to flush, then die. Do NOT try to
  // "recover" and keep serving — the process is in an unknown state.
  process.exitCode = 1;
  shutdownGracefully();
});

process.on('uncaughtException', (err, origin) => {
  logger.fatal({ err, origin }, 'uncaught exception');
  process.exitCode = 1;
  shutdownGracefully();
});
```

An orchestrator that restarts the process (Kubernetes, systemd) turns a crash
into a blip. A process that "handles" the exception and limps on is worse —
you now have live traffic hitting undefined behavior.

## ESM vs CommonJS

| | CommonJS | ESM |
|---|---|---|
| Syntax | `require()` / `module.exports` | `import` / `export` |
| Loading | Synchronous | Asynchronous (supports top-level `await`) |
| `package.json` | default, or `"type": "commonjs"` | `"type": "module"` |
| File override | `.cjs` | `.mjs` |
| `__dirname`/`__filename` | Available | Not available — see below |
| Tree-shaking | No (dynamic requires) | Yes (static analysis) |

Real repos are split on this — some fully ESM, some fully CJS, some dual-
publishing. Pick ESM for anything new; the ecosystem has largely moved, and
top-level `await` alone removes a category of async-bootstrap boilerplate.

**`__dirname` in ESM**: it doesn't exist, because ESM modules don't have the
same module-wrapper CJS does. Reconstruct it from `import.meta.url`:

```js
// ESM equivalent of __dirname / __filename
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
```

**Dual packages** (publishing both CJS and ESM from one package) are a
maintenance tax — you need a build step, a correct `exports` map with
`"import"`/`"require"` conditions, and testing for both. Avoid unless you're
publishing a widely-consumed library; for an internal service, pick one
module system and stop debating it.

**`require(esm)`**: as of Node 22+, `require()` can load synchronous ESM
modules directly (no more mandatory `import()` dance for consuming an ESM
dependency from CJS) — this closed one of the most annoying gaps in the
ecosystem. It does not make ESM importable if the module has top-level
`await` or other genuinely async initialization; those still need dynamic
`import()`.

## Testing, env files, and the permission model

**`node:test`** is a real, capable built-in test runner — no dependency, no
config file needed for the basics:

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('adds two numbers', () => {
  assert.equal(add(2, 3), 5);
});
```

```bash
node --test                    # runs **/*.test.js by default
node --test --watch            # rerun on change
node --test --test-reporter=spec
```

It's fine for small services and libraries. For anything with real assertion
ergonomics needs, mocking, or snapshot testing at scale, most teams still
reach for Vitest (see `testing.md`) — but know that the built-in option
exists and removes a dependency for simple cases.

**`--env-file`** loads `.env` without a `dotenv` dependency:

```bash
node --env-file=.env server.js
node --env-file=.env --env-file=.env.local server.js   # later file wins on conflict
```

Good for local dev. In production, prefer real secret injection (see
`packaging-deploy.md`) — a `.env` file in a container image is a secret leak
waiting to happen.

**Permission model** — **experimental since Node 20, stable in the 24 LTS line**, with the
flag simplified from `--experimental-permission` to **`--permission`**. That rename is the
practical gotcha: a script copied from a Node 20/22-era article uses the old flag and fails
with an unknown-option error. It restricts filesystem/network/child-process access at the
process level — genuinely useful for reducing blast radius when running less-trusted code
(build plugins, user-supplied scripts) inside a Node process:

```bash
node --permission --allow-fs-read=/app/data --allow-fs-write=/app/logs server.js
```

It is not a sandbox against a fully malicious actor with code execution —
treat it as defense-in-depth, not a substitute for process isolation
(containers, VMs) when running genuinely untrusted code.

## TypeScript 7 and native type stripping

**TypeScript 7** is the Go-port compiler — a from-scratch reimplementation of
`tsc` in Go, not incremental optimization of the existing checker. Reported
speedups are large (commonly 5–10x on cold builds, more on `--watch` and
language-server responsiveness) because it's a different execution model:
native compiled code with real parallelism, versus single-threaded JS.

Before migrating a project:
- **Plugin compatibility** — anything hooking `ts.Program`, custom
  transformers, or `ttypescript`-style plugins needs to be verified against
  the new compiler; the public type-checking API surface is not guaranteed
  identical everywhere.
- **Build tool integration** — confirm your bundler/test-runner's TS
  integration (ts-loader-equivalents, `tsx`, `ts-node` successors) has
  shipped support; the ecosystem catches up on a lag.
- **Editor tooling** — VS Code's TS language service needs a compatible
  version; mismatched `tsc` vs editor versions produce confusing "works in
  CI, red squiggles locally" splits.
- **Diagnostics text/format** — error message wording and some diagnostic
  codes can differ; anything that parses `tsc` output (CI annotations,
  custom lint glue) should be re-tested.

Separately, and orthogonally: Node itself (from 22.6+, stabilizing through 24)
can run `.ts` files directly via **type stripping** — it erases type
annotations without doing full type-checking, and only for TS syntax that
maps to a direct JS erasure (no `enum`, no experimental decorators, no
`namespace` unless configured).

```bash
node server.ts   # works if server.ts uses only "erasable" TS syntax
```

This is not a replacement for `tsc --noEmit` in CI — type-stripping doesn't
check types, it just deletes the annotations at parse time so V8 can run
the rest. Use it for fast local iteration; keep real type-checking as a
required CI step regardless of which compiler produces it.

## Checklist

- [ ] Node version pinned identically in `.nvmrc`, `package.json#engines`,
      and the Dockerfile base image
- [ ] No synchronous CPU-heavy calls (`*Sync`, tight loops, naive regex) in
      request-handling code paths
- [ ] CPU-bound work offloaded to `worker_threads` (pooled, not ad hoc) or
      an external service
- [ ] Large payloads processed as streams, not buffered fully into memory
- [ ] Request-scoped context uses `AsyncLocalStorage`, not a module-level
      variable
- [ ] `--max-old-space-size` set explicitly, below the container memory
      limit with headroom
- [ ] `--inspect` never exposed on a non-localhost interface in production
- [ ] `unhandledRejection`/`uncaughtException` handlers log and exit — they
      do not attempt to "recover" and keep serving
- [ ] One module system chosen (ESM preferred for new code) — no accidental
      dual-package complexity
- [ ] `.env` files used for local dev only, never baked into a production
      image
- [ ] TS build tooling verified against TypeScript 7 before migrating
      (plugins, bundler integration, editor version)
