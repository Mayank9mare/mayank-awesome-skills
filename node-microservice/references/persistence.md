# Data access in Node

## Prisma vs Drizzle vs Kysely vs TypeORM

| | Prisma 7.9.1 | Drizzle 0.45.2 | Kysely 0.29.4 | TypeORM |
|---|---|---|---|---|
| Model | Schema file -> generated client | SQL-first, TS schema = source of truth | Pure type-safe query builder | Decorator-based entities (ORM-classic) |
| Codegen | Yes — `prisma generate` required | No — schema is plain TS, no build step | No | Reflection metadata (decorators), no separate codegen |
| Runtime size | Heavier (generated client + engine) | Minimal — thin wrapper over the driver | Minimal | Heavier |
| Migrations | Built-in, opinionated (`prisma migrate`) | `drizzle-kit` — SQL-based, you review the diff | Bring your own (not its job) | Built-in, less predictable diffing |
| Query flexibility | High-level API; raw SQL escape hatch exists but is second-class | SQL-shaped API — if you know SQL, you already know Drizzle | Full SQL expressiveness, fully typed | High-level API, raw SQL escape hatch |
| Type safety | Generated types, very good DX | Inferred from schema, excellent | Best-in-class (it's a query builder, not an abstraction) | Decorator types, weaker inference |
| Best fit | Teams wanting a managed, batteries-included experience | Teams wanting SQL-level control with type safety, smaller footprint | Teams who want to write real SQL but typed | Legacy codebases already on it (avoid for new projects) |

**Prisma** trades runtime weight and a generation step for the smoothest
DX: autocomplete follows your schema, migrations are managed, and the
query API reads close to your data model. The cost is a real one — every
deploy needs `prisma generate` to be current with your schema (see below),
and its query engine historically ran as a separate process/binary (Rust
engine), adding startup latency and image size versus a pure-JS driver
wrapper. Prisma 7 continues narrowing this gap but it's still the heaviest
option here.

**Drizzle** is SQL-first: you write something that looks like SQL in
TypeScript, and it infers types from your schema definition with zero
codegen step. Smaller runtime, faster cold starts, and — because there's no
generated client — no "did I forget to regenerate" class of bug. The
tradeoff is a less opinionated migration/tooling story; you own more of the
process.

**Kysely** doesn't pretend to be an ORM — it's a fully-typed SQL query
builder. If your team is comfortable writing SQL and wants the compiler to
catch typos in column names and type mismatches in joins, this is the
purest expression of that. No object mapping magic, no hidden N+1 queries
from lazy-loaded relations — you see exactly the query you wrote.

**TypeORM** is the decorator-based, Hibernate-style ORM. It predates the
current generation of TS-first tools and carries their era's tradeoffs:
weaker type inference, less predictable migration generation, and known
rough edges around relations and change-tracking. Don't start new projects
on it; if you're maintaining one, know that migrating off is a real project,
not a drop-in swap.

## Connection pooling — the serverless problem

Every DB connection is a real OS-level resource, held on the Postgres side
whether or not it's doing anything (`~5–10MB` server-side memory per
connection). A traditional long-running server opens one pool at boot and
reuses it for the life of the process — fine, bounded, predictable.

**Serverless breaks this assumption.** Each Lambda/Cloud Function invocation
can spin up a fresh execution environment, and each one that creates its own
pool leaves connections open (or, worse, opens a new one per invocation if
you're not careful about reuse across warm starts). Under concurrent load,
N concurrent invocations can mean N pools × pool-size connections — easily
exhausting Postgres's `max_connections` (often 100–500) in seconds.

```js
// WRONG in a serverless handler — a fresh pool per cold start, and if this
// runs per-invocation instead of module-scope, per invocation too
export const handler = async (event) => {
  const pool = new Pool({ connectionString, max: 10 });   // new pool every call
  const result = await pool.query('SELECT ...');
  await pool.end();
  return result;
};

// RIGHT — pool created once at module scope, reused across warm invocations
const pool = new Pool({ connectionString, max: 5 });   // small max; you'll have MANY instances

export const handler = async (event) => {
  return pool.query('SELECT ...');   // reuses connections across warm starts
};
```

Even with module-scope reuse, the fundamental math doesn't work at scale:
1000 concurrent Lambda instances × `max: 5` = 5000 potential connections
against a database that tops out far lower. The real fix is a layer between
your functions and Postgres that multiplexes many logical connections onto
few physical ones:

| Solution | How it works | Notes |
|---|---|---|
| PgBouncer | Standalone connection pooler, transaction/session/statement pooling modes | Self-hosted or managed; transaction mode breaks session-level features (advisory locks, `SET` outside a transaction) |
| Prisma Accelerate | Prisma's managed connection pooling + global query cache | Vendor-hosted, Prisma-specific, adds a network hop |
| RDS Proxy (or cloud-equivalent) | Managed pooler in front of the managed DB | No self-hosting, integrates with IAM auth, adds its own latency |

Pick one before you scale past "a handful of instances," not after your
database starts refusing connections during a traffic spike. For a
traditional long-running Node service (not serverless), a single well-sized
pool per process is usually enough — the serverless multiplication problem
is specific to per-invocation execution models.

## Transactions and the interactive-transaction timeout trap

Prisma's `$transaction([...])` (the array form, "batch") sends all
operations in one round trip and is safe by default. `$transaction(async (tx)
=> { ... })` (the callback form, "interactive") holds a real database
transaction open for the *duration of your callback*, including any `await`
inside it that isn't a DB call:

```js
// WRONG — an external HTTP call inside an interactive transaction holds a
// DB connection and lock for as long as that call takes. A slow or hung
// downstream service now blocks your connection pool.
await prisma.$transaction(async (tx) => {
  const order = await tx.order.create({ data: orderData });
  await paymentGateway.charge(order.total);   // network call inside the transaction!
  await tx.order.update({ where: { id: order.id }, data: { status: 'PAID' } });
});

// RIGHT — do the external call first, keep the transaction to DB work only
const charge = await paymentGateway.charge(orderData.total);
await prisma.$transaction(async (tx) => {
  const order = await tx.order.create({ data: { ...orderData, chargeId: charge.id } });
  await tx.order.update({ where: { id: order.id }, data: { status: 'PAID' } });
});
```

Prisma's interactive transactions have a default timeout (5s) specifically
to catch this class of bug — a transaction that runs too long gets killed
rather than holding a connection forever. Raise the timeout only if you've
confirmed the work inside genuinely needs it and is DB-only; never raise it
to paper over an external call you forgot to move outside.

## N+1 with Prisma: `include` vs `select`

The classic N+1 (one query for the list, then one query per item for a
relation) is easy to introduce with any ORM's lazy-relation convenience.
Prisma doesn't lazy-load by default (you must opt in with `include`/`select`),
which prevents the *accidental* form, but doesn't prevent the manual one:

```js
// WRONG — N+1: one query for users, then one query per user for orders
const users = await prisma.user.findMany();
for (const user of users) {
  user.orders = await prisma.order.findMany({ where: { userId: user.id } });
}

// RIGHT — one query, relation fetched via a JOIN (or Prisma's batched query)
const users = await prisma.user.findMany({
  include: { orders: true },
});
```

`include` fetches full related rows; `select` lets you shape exactly which
columns come back — on both the base model and nested relations — which
matters for payload size and for the same "don't leak fields you didn't mean
to" concern as Fastify's response schemas:

```js
const users = await prisma.user.findMany({
  select: {
    id: true,
    email: true,
    orders: { select: { id: true, total: true } },   // no full order rows, no passwordHash anywhere
  },
});
```

Prefer `select` over `include` by default for anything crossing a service
boundary (an API response) — it forces you to be explicit about what leaves
the process.

## Migrations

**Never run migrations from application startup with N replicas.** If your
migration logic lives in `app.listen()`'s startup path, every replica that
boots races to run it. Best case: they serialize on a lock and waste time.
Worst case: two replicas run conflicting DDL concurrently and corrupt schema
state, or a rolling deploy has replicas on the *old* schema still serving
traffic while a new replica alters a column out from under them.

```js
// WRONG — every pod that starts tries to migrate
async function main() {
  await prisma.$executeRaw`...migration...`;   // or migrate.latest() etc.
  app.listen(port);
}

// RIGHT — migrations run once, as a separate step, before the new version
// of the app is allowed to receive traffic (a CI/CD pipeline step, an init
// container, or a dedicated migration job — not the app's own boot path)
```

**Expand-contract for rolling deploys.** During a rolling deploy, old and new
code run simultaneously against the same database for some window. A
migration that renames or drops a column breaks the old code that's still
querying it. The safe pattern is always additive-first:

1. **Expand**: add the new column/table, nullable or defaulted; deploy code
   that writes to *both* old and new.
2. **Backfill**: populate the new column for existing rows.
3. **Migrate reads**: deploy code that reads from the new column, still
   writing both.
4. **Contract**: once all replicas are on the new code and backfill is
   confirmed complete, deploy code that stops touching the old column, then
   drop it in a later migration.

Skipping straight to "rename the column" in one migration + one deploy is
the single most common cause of a rolling deploy taking down write traffic
for the minutes it takes replicas to cycle.

## `prisma generate` in CI/Docker

The generated Prisma client is derived from `schema.prisma` at build time —
if it's stale relative to your schema, you get runtime errors on fields that
"should" exist. This bites people specifically in Docker multi-stage builds
where `node_modules` gets cached/copied without re-running generate:

```dockerfile
# WRONG — copies node_modules from a cache layer that doesn't know about a
# schema change made after that layer was cached; the copied client is stale
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

# RIGHT — schema copied before generate runs, and generate runs after every
# dependency install, so the client always matches the current schema
COPY package*.json ./
RUN npm ci
COPY prisma ./prisma
RUN npx prisma generate
COPY . .
RUN npm run build
```

Also run `prisma generate` as an explicit CI step before tests, not just
before the build — a test suite running against a stale client passes
locally and fails against the real schema in a way that's hard to reproduce.

## Checklist

- [ ] ORM/query-builder choice matches team's SQL comfort and how much
      generated-code weight you're willing to carry
- [ ] Connection pool sized for the deployment model (long-running process
      vs serverless-per-invocation) — not copy-pasted from a tutorial
- [ ] A pooler (PgBouncer/Accelerate/RDS Proxy equivalent) sits in front of
      Postgres for any serverless or high-replica-count deployment
- [ ] No network/external calls inside an interactive transaction callback
- [ ] Interactive transaction timeouts left at a sane default, not raised to
      hide a slow call that should've been moved outside
- [ ] `select`/explicit field projection used at API boundaries instead of
      `include`-everything
- [ ] No manual per-row relation fetches inside a loop (N+1)
- [ ] Migrations run as a distinct pipeline step, never from app startup
      with multiple replicas racing
- [ ] Schema changes that affect columns in-flight use expand-contract
      across the rolling deploy window
- [ ] `prisma generate` (or equivalent codegen) runs after every dependency
      install and schema change, in both CI and the Docker build
