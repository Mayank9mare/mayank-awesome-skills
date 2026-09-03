# Choosing a Node web framework

## Comparison

| Framework | Version | Perf tier | Validation story | DI | TS support | Ecosystem | Best fit |
|---|---|---|---|---|---|---|---|
| Express | 5.2.1 | Baseline | None built-in (middleware: zod/joi by hand) | None | Community types, works fine | Enormous | Simple APIs, teams who know it, legacy migration |
| Fastify | 5.11.0 | High | Schema-first (JSON Schema/TypeBox/Zod), auto-serialization | Plugin-based (`fastify-plugin`), not a full container | First-class, schema-driven inference | Large, quality plugins | APIs where validation + throughput both matter |
| NestJS | 11.1.28 | Mid (Express/Fastify under the hood) | `class-validator`/`class-transformer` via pipes, or Zod | Full DI container, modules | Built around TS from the ground up | Large, "enterprise" leaning | Large teams, long-lived services, many contributors |
| Hono | 4.12.33 | Very high | Middleware-based (`@hono/zod-validator`, etc.) | None | Excellent, minimal runtime overhead | Growing fast | Edge/serverless, Workers, small footprint services |
| Koa | 3.2.1 | High | None built-in | None | Decent | Mature, smaller than Express's | Middleware-centric minimalism, async/await-native design |
| Elysia | latest | Very high (Bun-optimized) | Built-in, end-to-end type inference | None | Best-in-class (type inference from schema to client) | Bun-centric, smaller on Node | Bun runtimes; less mature on Node |
| Nitro | latest | High | Framework-agnostic (h3-based) | None | Good | Nuxt/unjs ecosystem | Universal server (works across Node/Deno/Workers/Bun) |

Perf tier is relative and about framework overhead specifically — routing,
middleware dispatch, serialization — not "how fast can Node go." All of these
handle thousands of req/s per instance for typical JSON APIs; framework choice
matters more for developer ergonomics, validation cost, and team fit than for
raw throughput at moderate load. It starts to matter at the tail (p99) under
serialization-heavy or very-high-QPS workloads, which is exactly where Fastify
and Hono pull ahead — their serialization paths are compiled/optimized rather
than generic `JSON.stringify`.

## Express 5

Express 5 (finally, after years of Express 4) fixes several long-standing
sharp edges:

**Async error handling now works.** In Express 4, a rejected promise inside
a handler was silently swallowed unless you manually caught it and called
`next(err)`:

```js
// Express 4 — WRONG, and it fails silently. The rejection never reaches
// your error middleware; the request just hangs or the process eventually
// crashes on an unrelated unhandledRejection.
app.get('/users/:id', async (req, res) => {
  const user = await db.getUser(req.params.id);   // if this rejects...
  res.json(user);                                    // ...nothing catches it
});

// Express 4 — the workaround everyone wrote
app.get('/users/:id', async (req, res, next) => {
  try {
    const user = await db.getUser(req.params.id);
    res.json(user);
  } catch (err) {
    next(err);
  }
});
```

```js
// Express 5 — RIGHT. Rejected promises returned from a handler or
// middleware are automatically forwarded to next(err). No wrapper needed.
app.get('/users/:id', async (req, res) => {
  const user = await db.getUser(req.params.id);   // rejection -> error middleware, automatically
  res.json(user);
});
```

You can delete every `catch (err) { next(err) }` wrapper in an Express 5
codebase — that's not a style choice, it's dead code now.

**`path-to-regexp` changes.** Express 5 upgraded its router to a newer
`path-to-regexp` with stricter, less ambiguous syntax. Wildcard behavior
changed (`*` must now be named, e.g. `/files/*splat` instead of a bare
`/files/*`), and some previously-tolerated malformed patterns now throw at
route-registration time instead of behaving unpredictably at request time.
Audit any dynamic route strings built from user input or config before
upgrading — this is the change most likely to break a migration silently.

**Removed methods**: `app.del()` (use `app.delete()`), `req.param()` (use
`req.params`/`req.query`/`req.body` explicitly — `req.param()` searched all
three, which was a source of parameter-pollution bugs), and several
`res.send()` overload forms that encouraged type confusion. If a migration
guide flags a removed method and your linter doesn't catch it, `grep` for
it explicitly before shipping.

Express 5 still has **no built-in validation or schema layer** — it's
deliberately minimal. Every non-trivial Express service ends up hand-rolling
or importing Zod/Joi validation middleware. That's fine, but it's a real cost
compared to Fastify's built-in story, and it's the most common source of
inconsistent validation across endpoints in a large Express codebase (every
route author makes slightly different choices about what "invalid" means).

## Fastify

Fastify's real differentiator isn't routing speed — it's **schema-driven
validation and serialization**. You declare a JSON Schema (or a TypeBox/Zod
schema Fastify compiles to one) for both input and output, and Fastify:

1. Validates the request against it *before* your handler runs — bad input
   never reaches your business logic.
2. Compiles a fast serializer from the response schema, so
   `JSON.stringify`-equivalent output is faster than generic serialization
   AND guarantees you never accidentally leak a field you didn't declare.

```js
import Fastify from 'fastify';

const app = Fastify({ logger: true });

const userSchema = {
  type: 'object',
  properties: {
    id: { type: 'string' },
    email: { type: 'string' },
    // passwordHash deliberately NOT declared here — even if the object
    // returned from your DB layer has it, the compiled serializer drops
    // any field not in the schema. This is a real security property,
    // not just a performance one.
  },
  required: ['id', 'email'],
};

app.get('/users/:id', {
  schema: {
    params: { type: 'object', properties: { id: { type: 'string' } } },
    response: { 200: userSchema },
  },
}, async (req, reply) => {
  return db.getUser(req.params.id);   // extra fields on this object are silently stripped
});
```

Plugins are Fastify's DI-adjacent mechanism — not a full container like
Nest's, but `fastify-plugin` encapsulation gives you controlled scoping of
decorators, hooks, and dependencies per plugin tree, which is usually enough
without the overhead of a real container.

## NestJS

Nest brings Angular-style architecture to the backend: modules, decorators,
dependency injection, and a full lifecycle (guards, interceptors, pipes,
exception filters). It runs on Express or Fastify underneath — you choose
the adapter — so its "performance" is really the underlying framework's,
minus a thin decoration overhead.

```ts
@Injectable()
export class UsersService {
  constructor(private readonly db: DatabaseService) {}   // constructor injection

  async findOne(id: string): Promise<User> {
    return this.db.user.findUniqueOrThrow({ where: { id } });
  }
}

@Controller('users')
export class UsersController {
  constructor(private readonly users: UsersService) {}

  @Get(':id')
  @UseGuards(AuthGuard)
  findOne(@Param('id') id: string) {
    return this.users.findOne(id);
  }
}
```

**When the structure earns its cost**: Nest's ceremony (modules, providers,
decorators, a build step, a steeper onboarding curve) pays for itself when a
service has enough surface area and enough contributors that consistency
matters more than velocity — a team of 15+ people, dozens of endpoints,
long service lifetime, need for testable seams everywhere (guards/pipes
give you clean interception points for auth/validation/logging without
scattering `if` statements through handlers).

**When it doesn't**: a service with 3 endpoints and one owner does not need
a DI container. The ceremony becomes pure overhead — more files, more
boilerplate, more places a newcomer has to look before finding the actual
logic. Don't reach for Nest by default; reach for it when the org-scale
problem it solves (many hands, one codebase, need for enforced structure)
is the actual problem you have.

## Hono

Hono is a minimal, extremely fast web framework built with edge runtimes in
mind (Cloudflare Workers, Deno, Bun) but runs fine on Node too. Its core is
a router with almost no framework tax — good for latency-sensitive services
and cold-start-sensitive serverless deployments.

```ts
import { Hono } from 'hono';
import { zValidator } from '@hono/zod-validator';
import { z } from 'zod';

const app = new Hono();

app.get(
  '/users/:id',
  zValidator('param', z.object({ id: z.string().uuid() })),
  async (c) => {
    const { id } = c.req.valid('param');
    return c.json(await db.getUser(id));
  },
);

export default app;   // works as-is on Workers; wrap with @hono/node-server for Node
```

Use Hono when you're deploying to an edge/Workers runtime (where Express
doesn't run at all — no Node APIs), or on Node when you want framework
overhead close to zero and don't need Fastify's serialization compiler or
Nest's DI. It's less battle-tested than Express/Fastify for large,
long-lived Node services, but the gap is closing fast.

## Koa

Koa is Express's spiritual successor from the same original team — smaller
core, async/await-native middleware (`ctx` object instead of `req, res, next`),
no bundled middleware (routing, body parsing — all opt-in via separate
packages). It never displaced Express in mindshare but remains a solid,
mature choice if you want middleware composition without Express's
callback-era API surface and don't need Fastify's schema story.

```js
const Koa = require('koa');
const app = new Koa();

app.use(async (ctx, next) => {
  const start = Date.now();
  await next();                                  // await, not a callback — real control flow
  ctx.set('X-Response-Time', `${Date.now() - start}ms`);
});

app.use(async (ctx) => {
  ctx.body = { hello: 'world' };
});
```

## Elysia and Nitro (brief)

**Elysia** targets Bun specifically — its performance story and end-to-end
type inference (client types derived automatically from server route
definitions, no codegen step) are best realized under Bun's runtime. It runs
on Node too, but you lose some of the Bun-specific optimizations; evaluate it
if you're already committed to Bun, less so as a Node-first choice today.

**Nitro** (from the unjs/Nuxt ecosystem) is a universal server toolkit built
on `h3` — it targets "write once, deploy to Node, Deno, Workers, or a
serverless function" more than it targets "best Node framework." Consider it
if deployment-target flexibility matters more than framework-specific
features.

## Decision guidance

| If you need... | Pick |
|---|---|
| Fastest path for a team that already knows it, huge middleware ecosystem | Express 5 |
| Best perf/validation ratio for a JSON API, schema-enforced responses | Fastify |
| Enforced structure across a large team, long service lifetime, testable DI | NestJS |
| Edge/Workers deployment, or minimal framework overhead on Node | Hono |
| Middleware-centric minimalism, mature async design, no bundled opinions | Koa |
| Bun-first project with end-to-end type inference | Elysia |
| Deploy-target-agnostic universal server | Nitro |

Don't default to Express out of habit if the service is API-heavy and
validation-correctness matters — Fastify's schema enforcement removes a whole
class of "we forgot to validate this field" incidents for a modest learning
curve. Don't default to Nest for a small service — the DI ceremony is a real
cost, not a free architectural upgrade.

## Checklist

- [ ] Framework choice matches team size/lifetime, not just familiarity
- [ ] Validation happens at the framework boundary (schema, pipe, or
      middleware), not scattered `if (!req.body.x)` checks in handlers
- [ ] If on Express 5, migrated `req.param()`/`app.del()` usages and audited
      wildcard route patterns against the new `path-to-regexp`
- [ ] If on Express, confirmed async handlers don't need manual
      `try/catch -> next(err)` wrappers anymore (Express 5) — or confirmed
      they DO still need them (Express 4, not yet upgraded)
- [ ] If on Fastify, response schemas declared for anything returning
      DB-shaped objects (serialization-time field stripping as a security
      control, not just a perf one)
- [ ] If on Nest, module boundaries reflect actual bounded contexts, not
      just "one module per database table"
- [ ] If targeting an edge/Workers runtime, confirmed the framework has no
      Node-API dependency that breaks there
- [ ] One framework per service — no half-migrated Express-to-Fastify
      codebases left in a permanent split state
