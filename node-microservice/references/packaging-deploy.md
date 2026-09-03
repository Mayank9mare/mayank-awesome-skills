# Packaging and deploying a Node microservice

## package.json anatomy

```json
{
  "name": "myservice",
  "version": "1.4.0",
  "type": "module",
  "engines": {
    "node": ">=24.18.0 <25"
  },
  "exports": {
    ".": "./src/index.js",
    "./client": "./src/client.js"
  },
  "files": ["src", "dist"],
  "scripts": {
    "build": "tsc -p tsconfig.json",
    "start": "node dist/index.js",
    "dev": "node --watch src/index.js",
    "test": "vitest run",
    "test:integration": "vitest run --config vitest.integration.config.js",
    "lint": "eslint ."
  }
}
```

**`engines.node` — declare it.** An audit across four production repos
found it declared in exactly one. Without it, `npm install` gives no
warning at all when someone runs it on a different major version, and
"works on my machine" quietly becomes "works on whichever Node happens
to be on whichever machine" — the exact gap that lets local-vs-prod
version drift go undetected until a runtime behavior difference (a
`fetch` default, a V8 flag default, a native addon ABI mismatch) shows
up only in one environment. It costs one line:

```json
"engines": { "node": ">=24.18.0 <25" }
```

Pair it with `npm config set engine-strict true` (or `.npmrc` with
`engine-strict=true`) if you want it enforced rather than advisory —
plain `engines` alone only warns.

**`"type": "module"` — pick one, deliberately, per repo.** The same
audit found ESM and CommonJS split across repos with no consistent
rule for which got which. Both work; inconsistency across a fleet of
services is the actual cost — every engineer has to re-check which
module system this particular repo uses before writing an import, and
tooling (bundlers, test runners, some older middleware) sometimes needs
different config per mode. Default to ESM (`"type": "module"`) for new
services on Node 24 — the ecosystem has largely finished its ESM
migration, top-level `await` is available, and `node --import` hooks
(used for OpenTelemetry bootstrapping, see observability.md) are
cleaner under ESM.

**`exports`** — the modern replacement for `main`, and it's an actual
access-control boundary, not just a convenience: only paths listed in
`exports` are importable by consumers; everything else in the package
is unreachable via `import 'myservice/internal/whatever'` even if the
file physically exists on disk. Use it deliberately for anything meant
to be a library with a public surface.

**`files`** — the allowlist of what `npm pack`/`npm publish` includes.
Without it, npm falls back to `.gitignore` semantics, and it's easy to
accidentally ship `test/`, `.env.example`, or build scratch directories
into a published package.

## Package manager: npm vs pnpm vs yarn vs bun

| | npm | pnpm | yarn (berry) | bun |
|---|---|---|---|---|
| Install speed | Baseline | Fastest for repeated installs (content-addressable store, hard links) | Fast (PnP mode skips `node_modules` entirely, or classic mode is npm-like) | Fastest cold install; also a runtime, not just a package manager |
| Disk usage | One copy per project | One physical copy shared via hard links across projects — big win in a monorepo or many-services fleet | PnP avoids `node_modules` duplication entirely | Similar to npm unless using its own cache tuning |
| Lockfile | `package-lock.json` | `pnpm-lock.yaml` | `yarn.lock` | `bun.lock` |
| Monorepo/workspaces | Supported, basic | Best-in-class workspace support, purpose-built for it | Supported | Supported, newer |
| Ecosystem compatibility | Universal — every tool assumes npm exists | High, occasional native-module/hoisting edge cases | High | Newest — occasional gaps with native addons or npm-specific assumptions |

Any of these is a defensible choice; the actual failure mode is **no
enforced discipline** — a lockfile that isn't committed, or is committed
but not what CI actually installs from. Two rules regardless of which
tool:

```bash
# WRONG in CI — `install` can modify the lockfile (resolve new ranges,
# add missing entries) if package.json and the lockfile have drifted
# even slightly. CI silently installing something other than what's
# committed is how "works in CI, different bug in prod" happens.
npm install

# RIGHT in CI — `ci` refuses to run if package.json and package-lock.json
# are out of sync, and always installs the exact locked versions,
# deterministically, deleting node_modules first for a clean slate.
npm ci
```

```bash
# Production image / production install: skip devDependencies entirely.
# Smaller image, smaller attack surface, and it's a mechanical check
# that nothing in your runtime code accidentally imports a devDependency
# that happens to be present locally but won't be in the built image.
npm ci --omit=dev
```

## Multi-stage Dockerfile

```dockerfile
# syntax=docker/dockerfile:1
FROM node:24.18.1-slim AS deps
WORKDIR /app

# Copy ONLY the manifests first. Docker caches layers by instruction +
# input hash — as long as package.json/package-lock.json are unchanged,
# this layer (and the expensive `npm ci` below) is reused from cache even
# when application source changes on every commit. Copy source before
# this and you invalidate the dependency-install cache on every single
# code change, turning a 2-second cached layer into a multi-minute
# reinstall on every build.
COPY package.json package-lock.json ./
RUN npm ci --omit=dev

FROM node:24.18.1-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci                      # full deps, including dev, for the build step
COPY . .
RUN npm run build               # e.g. tsc — produces ./dist

FROM node:24.18.1-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production

# non-root user — a container running as root that gets compromised via
# a dependency RCE hands the attacker root inside the container, which is
# one privilege-escalation step closer to root on the host than it needs
# to be. node:*-slim images ship a `node` user (uid 1000) for exactly this.
USER node

COPY --from=deps /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
COPY package.json ./

# dumb-init as PID 1: see the "Node as PID 1" section below for why this
# line isn't optional. --init is the Docker-native equivalent if you'd
# rather not add a dependency for it.
ENTRYPOINT ["node", "--max-old-space-size=460", "dist/index.js"]
```

```bash
# Equivalent without adding dumb-init to the image — Docker's own init:
docker run --init myservice:latest
```

### `node:24-slim` vs `alpine`

| | `node:24-slim` (Debian-based) | `node:24-alpine` (musl-based) |
|---|---|---|
| Image size | Larger than alpine, smaller than the full `node:24` image | Smallest |
| glibc vs musl | glibc — same libc as most CI runners and most prebuilt native binaries target | musl — a different libc; prebuilt native addons (`.node` files compiled against glibc) don't load |
| Native modules (`bcrypt`, `sharp`, driver bindings with native code) | Just work — prebuilt binaries download and load normally | Either recompile from source at image-build time (slower build, needs build toolchain in the image) or fail to load outright with a cryptic "invalid ELF header" or symbol-not-found error at runtime |
| Recommendation | **Default choice** — the size savings from alpine rarely justify debugging a native-module failure discovered after ship | Advanced option only, when you've verified every dependency (including transitive ones) has no native code, or you're deliberately compiling from source and have accepted that build cost |

The musl-vs-glibc gap is the actual reason "alpine is smaller, why not
always use it" is the wrong default: it's not a straightforward size/
speed tradeoff, it's a compatibility cliff that a dependency upgrade
(gaining a transitive native dependency you didn't have last month) can
walk you off with zero warning until the container fails to start.

**Distroless** (`gcr.io/distroless/nodejs24`) is the advanced option
past slim: no shell, no package manager, no `apt`, nothing but the Node
runtime and your app — smallest attack surface, but debugging inside a
running container (`kubectl exec` into a shell) is no longer possible,
which is a real cost during an incident. Reach for it once your image
build and runtime are stable enough that you don't need shell access
for troubleshooting; start with slim.

### Node as PID 1

```dockerfile
# WRONG — node running directly as PID 1 in the container.
ENTRYPOINT ["node", "dist/index.js"]
```

Two independent consequences, both real:

1. **Zombie process reaping.** PID 1 has special responsibilities in
   Unix — it must reap zombie (exited-but-not-yet-collected) child
   processes. Node doesn't do this. If your app or any dependency spawns
   child processes (a subprocess call, a native addon that forks
   internally), those children become zombies that accumulate and are
   never cleaned up, because Node-as-PID-1 never calls `wait()` on them.

2. **Signal handling.** PID 1 receives `SIGTERM` directly from Docker/
   Kubernetes on shutdown, but process signal defaults inside a
   container differ from a normal shell-launched process — Node as PID 1
   does not automatically forward signals to child processes, and some
   signal-default behaviors that a normal init process would have
   simply don't apply. The practical result: a graceful-shutdown
   `SIGTERM` handler (see below) may not fire the way you'd expect,
   or child processes spawned by your app never see the signal at all
   and get hard-killed instead of shutting down cleanly.

```dockerfile
# RIGHT — dumb-init (or tini) as PID 1: forwards signals correctly to
# the actual Node process and reaps zombies, at the cost of one tiny
# static binary.
FROM node:24.18.1-slim
RUN apt-get update && apt-get install -y dumb-init && rm -rf /var/lib/apt/lists/*
ENTRYPOINT ["dumb-init", "--", "node", "dist/index.js"]
```

```bash
# RIGHT (no image change needed) — Docker's built-in init, tini under
# the hood, achieves the same thing at the `docker run`/orchestrator level:
docker run --init myservice:latest
```

Kubernetes doesn't have a direct `--init` equivalent at the pod spec
level; use the `dumb-init`-in-image approach there, or a minimal init
container/sidecar pattern if your platform provides one.

## `NODE_ENV=production`

Sets the convention most frameworks and libraries key off of: Express
disables verbose error pages and enables view caching, many logging
libraries change default verbosity, and `npm ci --omit=dev`-installed
packages that check `NODE_ENV` at runtime (rare, but some do) behave
differently. It is not a security boundary and not a substitute for
your own `config.isProduction` checks driven by an explicit config
value — but leaving it unset in a production image is a real, common
bug (frameworks defaulting to development-mode behavior, verbose stack
traces in error responses) for a one-line fix.

## `--max-old-space-size` below the container limit

```dockerfile
# WRONG — no flag set. V8 sizes its default heap ceiling from the HOST
# machine's total memory, which it can see even inside a container,
# not from the container's memory limit. On a host with 64GB of RAM,
# V8 may default to a multi-GB heap ceiling even though the container's
# cgroup limit caps it at 512MB. V8 doesn't find out it's "almost out of
# memory" until the OS OOM-killer has already killed the container —
# there's no graceful GC pressure response, just a hard kill with exit
# code 137 and often no application-level error at all to explain why.
ENTRYPOINT ["node", "dist/index.js"]
```

```dockerfile
# RIGHT — worked example: container memory limit is 512Mi (set in the
# Kubernetes pod spec or --memory on docker run). Reserve headroom for
# non-heap V8 overhead (code cache, stack space) and the Node runtime
# itself (buffers, native module memory) — as a starting rule of thumb,
# set max-old-space-size to roughly 80% of the container limit and
# validate under real load, adjusting from there:
#   512Mi container limit × 0.8 ≈ 410MB → round down for margin → 400MB
ENTRYPOINT ["node", "--max-old-space-size=400", "dist/index.js"]
```

```yaml
# Kubernetes pod spec — the limit this flag must stay under
resources:
  limits:
    memory: "512Mi"
  requests:
    memory: "512Mi"
```

With the flag set correctly, V8 responds to heap pressure the way it's
designed to — more aggressive GC, and if truly out of memory, a
catchable `FATAL ERROR: Reached heap limit` your process can at least
attempt to log before dying — instead of an untraceable, unexplained
`137`/OOMKilled from outside the process with zero application-level
signal about what happened.

## Graceful shutdown

```js
// RIGHT — the full drain sequence, in order, and the order is not
// arbitrary. Skipping or reordering steps is the actual cause of the
// "every deploy causes a burst of 5xx" pattern most teams have seen and
// shrugged off as "just how deploys are."
let shuttingDown = false;

process.on('SIGTERM', async () => {
  if (shuttingDown) return;
  shuttingDown = true;
  logger.info('SIGTERM received, starting graceful shutdown');

  // 1. Fail readiness FIRST, before touching anything else. The load
  //    balancer's endpoint removal is EVENTUALLY consistent — it takes
  //    some number of seconds for every LB/proxy/service-mesh sidecar in
  //    the path to notice this pod failed its readiness check and stop
  //    routing to it. Requests keep arriving during that window no
  //    matter what you do next. This propagation delay, not anything
  //    about your app's shutdown code, is the actual, most common cause
  //    of 5xx bursts on deploy — the pod is gone or draining before
  //    every caller has heard about it.
  isReady = false;   // your /readyz handler now returns 503

  // 2. Wait out that propagation window BEFORE doing anything disruptive.
  //    This is dead time on purpose — matched to your LB's known
  //    propagation delay (check your specific LB/mesh's health-check
  //    interval × unhealthy-threshold), not a guess.
  await sleep(5000);

  // 3. Stop accepting new connections. server.close() lets already-
  //    in-flight requests finish; it does NOT accept new ones from this
  //    point on.
  server.close();

  // 4. Drain in-flight work — wait for currently-executing requests/jobs
  //    to actually finish, up to a bounded timeout so a single hung
  //    request can't block shutdown forever.
  await drainInFlightRequests({ timeoutMs: 10_000 });

  // 5. Stop consuming from queues — no new jobs pulled, so nothing new
  //    starts that you'd then have to drain too.
  await queueConsumer.stop();

  // 6. Close DB/Redis connections LAST — only after every consumer of
  //    them (steps 3-5) has actually finished using them.
  await dbPool.end();
  await redisClient.quit();

  logger.info('graceful shutdown complete');
  process.exit(0);
});
```

`server.close()` vs `server.closeAllConnections()`: `close()` is the
graceful one — stops accepting new connections, waits for in-flight
requests on existing keep-alive connections to complete, then the
`close` event fires. `closeAllConnections()` is the immediate, un-
graceful one — force-closes every connection, in-flight or not, right
now. Use `close()` for the drain step above; reach for
`closeAllConnections()` only as a hard-timeout fallback if drain step 4
doesn't complete within its bound and you need the process to actually
exit rather than hang.

```yaml
# Kubernetes: terminationGracePeriodSeconds must exceed your OWN shutdown
# budget (steps 2-6 above summed), or Kubernetes sends SIGKILL before
# your handler finishes step 6 — an unclean kill mid-drain, which is the
# exact outcome graceful shutdown exists to prevent.
spec:
  terminationGracePeriodSeconds: 30   # must be >= (5s LB wait + 10s drain + queue-stop + close time)
```

If your shutdown budget is 20 seconds and `terminationGracePeriodSeconds`
is the Kubernetes default of 30, you're fine; if you *increase* the
shutdown budget (a longer LB-propagation wait, a longer drain timeout)
without raising this value to match, you silently reintroduce the
SIGKILL-mid-drain problem you just fixed.

## Config validated at boot

```js
// RIGHT — Zod schema parsed once, at import time, before anything else
// in the app runs. A missing or malformed env var crashes the process
// immediately at startup with a clear validation error naming the exact
// field — not three requests later when the code finally reaches the
// line that reads process.env.SOME_VAR and gets undefined, and not as a
// silently-wrong default that only misbehaves under a specific runtime
// condition nobody hit in the deploy's first five minutes of traffic.
import { z } from 'zod';

const configSchema = z.object({
  PORT: z.coerce.number().int().positive().default(3000),
  DATABASE_URL: z.string().url(),
  LOG_LEVEL: z.enum(['debug', 'info', 'warn', 'error']).default('info'),
  JWT_SECRET: z.string().min(32),
  NODE_ENV: z.enum(['development', 'production', 'test']).default('development'),
});

// parsed at import — this throws and crashes the process on load if
// anything is missing/invalid, which is the point: fail at boot, in
// the deploy pipeline's own health check, not in prod traffic
export const config = configSchema.parse(process.env);
```

Crashing fast at boot on bad config is strictly better than the
alternative every time: a container orchestrator's own health checks
catch a boot-time crash before it ever receives real traffic, whereas a
runtime failure from a bad config value discovered mid-request is a
customer-facing incident instead of a failed deploy that never went
live.

## Secrets never baked into the image

```dockerfile
# WRONG — even if this layer is later removed, the secret is present in
# an earlier image layer's history and extractable from the image
# artifact itself (`docker history`, or just pulling and inspecting the
# layer). Anyone with pull access to the image has the secret, full stop,
# regardless of what the final running container's filesystem looks like.
ARG DATABASE_PASSWORD
ENV DATABASE_PASSWORD=$DATABASE_PASSWORD
```

Secrets belong in the orchestrator's secret mechanism (Kubernetes
`Secret` mounted as an env var or file, AWS Secrets Manager/Parameter
Store fetched at startup, Vault) — injected at container *run* time, not
baked into the image at *build* time. The image itself should be safe to
push to a registry that a wider set of people/systems can pull from than
should ever see the secret's value.

## Dependency scanning

```bash
# npm audit — checks the lockfile's exact resolved versions against
# known-vulnerability databases. Run in CI, not just locally, so a new
# CVE disclosed against an already-locked dependency version gets caught
# on the next CI run, not whenever someone happens to run it by hand.
npm audit --omit=dev --audit-level=high
```

Lockfile-based scanning (npm audit, Snyk, Dependabot alerts, Grype
against the built image) is checking what you actually ship — the exact
resolved version tree in the lockfile — which is why `npm ci` (installs
exactly what's locked) matters here too: a scan that runs against a
freshly-`npm install`-resolved tree can differ from what's actually
deployed if the lockfile had drifted, silently checking the wrong thing.

## Checklist

- [ ] `engines.node` is declared and matches the Dockerfile's base image version
- [ ] `"type": "module"` (or explicit CommonJS) is a deliberate, consistent choice across the fleet, not repo-by-repo accident
- [ ] `exports` map defines the actual public surface; `files` allowlists what gets published
- [ ] CI runs `npm ci` (or the pnpm/yarn/bun equivalent), never `install`
- [ ] Production install uses `--omit=dev`
- [ ] Dockerfile copies manifests and installs dependencies BEFORE copying source, so the dependency layer caches
- [ ] Base image is `node:24-slim` by default; alpine only after verifying no native-module/musl incompatibility
- [ ] Container runs as a non-root user
- [ ] PID 1 is `dumb-init`/`tini`/`docker run --init`, never Node directly
- [ ] `NODE_ENV=production` is set in the runtime image
- [ ] `--max-old-space-size` is set explicitly, below the container's memory limit with real headroom
- [ ] SIGTERM handler fails readiness first, waits out LB propagation, THEN stops accepting connections, drains in-flight work, stops queue consumers, and closes DB/Redis last — in that order
- [ ] `terminationGracePeriodSeconds` exceeds the full shutdown sequence's worst-case duration
- [ ] Config is parsed through a Zod schema at import time, so a missing/invalid var crashes at boot, not mid-request
- [ ] No secret is ever baked into an image layer, ARG, or ENV at build time
- [ ] `npm audit` (or equivalent) runs against the lockfile in CI, not just locally
