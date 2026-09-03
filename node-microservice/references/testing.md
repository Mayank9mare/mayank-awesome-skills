# Testing Node microservices

## Runner choice

| | Vitest 4 | Jest | `node:test` |
|---|---|---|---|
| Speed (cold start) | Fast — esbuild/Vite transform, no separate transpile step | Slower — Babel/ts-jest transform pass adds real seconds on a large suite | Fastest — no transform, native to the runtime |
| ESM support | Native, first-class | Historically painful; modern versions work but config is finicky (`extensionsToTreatAsEsm`, `transform` overrides) | Native, first-class — it's Node |
| Config burden | Low — sensible defaults, one config file | High — `transform`, `moduleNameMapper`, `testEnvironment`, more as the project grows | Minimal — almost no config surface exists |
| Watch mode | Fast, smart re-runs (Vite's module graph) | Works, slower re-run cycle | Basic (`--watch` flag), no dependency-graph awareness |
| Mocking | `vi.mock`, `vi.fn`, `vi.useFakeTimers` — full-featured | `jest.mock`, mature and heavily documented | Minimal built-in — lean on `node:test`'s `mock` module, less ergonomic |
| Ecosystem/plugins | Growing fast, most Jest-era tooling has a Vitest equivalent | Largest — most tutorials, most Stack Overflow answers, most framework integrations | Smallest — no snapshot testing, no built-in coverage reporting without pairing `c8` |
| Coverage | Built-in (`v8` provider) | Built-in (`--coverage`) | Requires `node --test --experimental-test-coverage` or external `c8` |

Default to **Vitest** for new services: ESM works without fighting the
config, startup is fast enough that a large suite in watch mode stays
usable, and mocking/coverage/snapshots are all first-party. Reach for
`node:test` when you want literally zero test-framework dependency (a
tiny library, a script) and don't need snapshot testing. Jest remains
correct for an existing large Jest codebase — rewriting a mature test
suite onto a new runner for its own sake is a cost with no user-facing
payoff; migrate opportunistically (new files on the new runner) rather
than in one sweep.

## Test pyramid, sized for a service

```
        /\
       /  \      a handful — full request through a real deployed
      / E2E\     environment, slow, brittle, run pre-release only
     /------\
    /        \   dozens — HTTP boundary in, real Postgres/Redis via
   /Integration\  testcontainers, no mocked DB, run on every PR
  /--------------\
 /                \  hundreds — pure functions and injected
/   Unit tests      \ dependencies, no I/O, run on every save
----------------------
```

Most of your test count and most of your test *runs* (watch mode, every
commit) should be unit tests — they're the ones fast enough to run
continuously. Integration tests validate the boundary where unit tests
lie to you (a mocked DB call that doesn't actually mean the SQL is
valid). E2E is a smoke test that a wired-together deployment starts up
and answers requests — not where you re-verify business logic already
covered lower down.

## Unit tests: constructor injection makes them trivial

```js
// WRONG — the class reaches out and constructs its own dependency.
// Testing this means either hitting a real database (slow, needs
// network, needs test data setup/teardown) or monkey-patching the db
// module's exports, which breaks the moment the import path changes.
class OrderService {
  async getOrder(id) {
    const db = require('./db');   // constructed internally, invisible to the caller
    return db.query('SELECT * FROM orders WHERE id = $1', [id]);
  }
}
```

```js
// RIGHT — the dependency is a constructor argument. The test passes a
// fake; production wiring passes the real pool. No monkey-patching, no
// module-mock gymnastics, and the test reads as plainly as the code.
class OrderService {
  constructor(db) {
    this.db = db;
  }

  async getOrder(id) {
    return this.db.query('SELECT * FROM orders WHERE id = $1', [id]);
  }
}

// test
import { describe, it, expect, vi } from 'vitest';

describe('OrderService', () => {
  it('fetches an order by id', async () => {
    const fakeDb = { query: vi.fn().mockResolvedValue({ rows: [{ id: 1 }] }) };
    const service = new OrderService(fakeDb);

    const result = await service.getOrder(1);

    expect(fakeDb.query).toHaveBeenCalledWith('SELECT * FROM orders WHERE id = $1', [1]);
    expect(result.rows[0].id).toBe(1);
  });
});

// production wiring, elsewhere, once
const service = new OrderService(realPgPool);
```

The dependency-injection payoff isn't stylistic — it's that the class
under test has no hidden way to reach the outside world, so "what does
this test actually exercise" has one obvious answer.

## Integration tests: real Postgres/Redis via testcontainers

```js
// WRONG — sqlite as a stand-in for Postgres because it's in-process and
// fast. This looks like an integration test and passes reliably, then a
// query using a Postgres-only feature (JSONB operators, `ON CONFLICT ...
// DO UPDATE`, window functions, a CHECK constraint's exact enforcement
// timing inside a transaction) behaves differently or not at all under
// sqlite's dialect. The dialect gap is exactly the class of bug an
// integration test exists to catch, and this setup guarantees it
// escapes to prod instead, because the test suite never exercised the
// real database's actual behavior.
import Database from 'better-sqlite3';
const db = new Database(':memory:');   // not Postgres — different dialect, different guarantees

// RIGHT — testcontainers-node spins up the real database in Docker.
// Slower per-run than sqlite, but it's testing the actual dialect,
// actual constraint semantics, and actual transaction isolation you'll
// run in production.
import { PostgreSqlContainer } from '@testcontainers/postgresql';
import { beforeAll, afterAll, describe, it, expect } from 'vitest';

describe('OrderRepository (integration)', () => {
  let container;
  let pool;

  // one container per FILE/SUITE, not per test — starting a container
  // takes real seconds; doing it per-test turns a suite into a
  // multi-minute crawl, and CI cost scales with test count for no benefit
  beforeAll(async () => {
    container = await new PostgreSqlContainer('postgres:17-alpine').start();
    pool = new Pool({ connectionString: container.getConnectionUri() });
    await pool.query(readFileSync('./schema.sql', 'utf8'));   // migrate once per suite
  }, 60_000);   // container startup needs a longer timeout than the default

  afterAll(async () => {
    await pool.end();
    await container.stop();
  });

  it('inserts and retrieves an order', async () => {
    const repo = new OrderRepository(pool);
    const order = await repo.create({ userId: 1, total: 4200 });
    expect((await repo.findById(order.id)).total).toBe(4200);
  });
});
```

Same pattern for Redis: `@testcontainers/redis` gives you a real Redis
instance with real `EXPIRE`/`WATCH`/pub-sub semantics that an in-memory
JS map pretending to be a cache will never reproduce faithfully.

Tag slow/integration tests separately so the fast unit suite stays fast
in the everyday inner loop:

```js
// vitest.config.js — split by directory, or tag with vitest's `describe.concurrent`
// grouping, or a naming convention (`*.integration.test.js`) filtered via CLI:
// `vitest run src/**/*.test.js`        — unit only, runs on every save
// `vitest run src/**/*.integration.test.js` — integration, runs on PR/CI, not on every save
```

## In-process HTTP tests: no socket, no port, no flakiness

```js
// WRONG — actually binding to a port for every test run. Ties tests to
// port availability (flaky in parallel CI runners), needs a real network
// round trip per request, and needs explicit server teardown or the
// process hangs after the suite finishes.
const server = app.listen(3000);
const res = await fetch('http://localhost:3000/orders/1');

// RIGHT — fastify.inject() dispatches the request through the framework's
// routing and handler pipeline directly, in-process, no socket involved.
// Faster, and immune to "port already in use" flakiness entirely.
const res = await app.inject({ method: 'GET', url: '/orders/1' });
expect(res.statusCode).toBe(200);
expect(res.json()).toEqual({ id: 1, total: 4200 });
```

```js
// Express doesn't have an inject() equivalent, but supertest gives you
// the same "no real port bound" property by passing the app instance
// directly and letting supertest manage an ephemeral in-memory listener.
import request from 'supertest';

const res = await request(app).get('/orders/1');
expect(res.status).toBe(200);
```

## Outbound stubbing: MSW and undici MockAgent

```js
// RIGHT — undici MockAgent intercepts at the dispatcher level, so it
// works for both undici calls and Node's global fetch() (which is
// undici underneath). No need to restructure the code under test to
// accept an injected client just to make it testable.
import { MockAgent, setGlobalDispatcher } from 'undici';

const mockAgent = new MockAgent();
setGlobalDispatcher(mockAgent);
mockAgent.disableNetConnect();   // fail loudly on any real network call that slips through

const mockPool = mockAgent.get('https://example.com');
mockPool.intercept({ path: '/users/1', method: 'GET' }).reply(200, { id: 1, name: 'a' });

const res = await fetch('https://example.com/users/1');
expect(await res.json()).toEqual({ id: 1, name: 'a' });
```

```js
// RIGHT — and explicitly test the failure paths, not just the happy
// path. An untested timeout is a guess about what your code does under
// a slow dependency — you don't actually know until you inject the
// delay and watch it happen.
mockPool.intercept({ path: '/users/2', method: 'GET' })
  .reply(200, { id: 2 })
  .delay(10_000);   // longer than the client's configured timeout

await expect(getUser(2)).rejects.toThrow(/timeout|abort/i);

// and the retry path — force a transient failure, assert the retry fires
// and eventually succeeds, and assert it does NOT retry a 400
mockPool.intercept({ path: '/users/3', method: 'GET' }).reply(503).times(2);
mockPool.intercept({ path: '/users/3', method: 'GET' }).reply(200, { id: 3 });
const result = await fetchWithRetry('https://example.com/users/3');
expect(result.status).toBe(200);   // succeeded on the 3rd attempt
```

MSW (`msw`) is the alternative when you want the same request
interception at a higher level, shareable between Node tests and browser/
Storybook mocking with one set of handler definitions — pick it when
the mocks need to be reused outside the Node test suite, and MockAgent
when they don't.

## Fake timers and their traps

```js
// RIGHT — fake timers let you assert "retry waited ~2s" without the
// test actually taking 2s wall-clock time.
import { vi, beforeEach, afterEach, it, expect } from 'vitest';

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());   // ALWAYS restore — leaking fake timers into
                                        // the next test is a classic cross-test
                                        // flakiness source, see isolation below

it('retries after backoff', async () => {
  const promise = fetchWithRetry(url);
  await vi.advanceTimersByTimeAsync(2000);   // async variant — lets pending
                                              // microtasks/promises resolve
                                              // between timer advances, unlike
                                              // the sync advanceTimersByTime,
                                              // which can advance past a timer
                                              // whose callback hasn't been
                                              // scheduled as a promise yet
  await promise;
});
```

The trap: fake timers replace `setTimeout`/`setInterval` globally for
the test file. Anything relying on real elapsed time — a library doing
its own internal scheduling, `Date.now()` if you also faked that and
forgot a code path depends on real wall-clock delta — behaves
differently under fake timers than in prod. Fake timers are for testing
*your* timing logic (backoff, debounce, TTL expiry), not a substitute
for integration testing something with real time-based external
behavior.

## Test isolation and parallelism

| Breaks under parallel/concurrent runs | Why |
|---|---|
| Shared DB state across tests | Test A inserts a row test B's `SELECT COUNT(*)` didn't expect — order-dependent tests are actually state-dependent tests wearing a disguise |
| Fixed ports (`app.listen(3000)`) | Two test files racing for the same port — one binds, the other's `EADDRINUSE` fails, non-deterministically depending on scheduling |
| Fake timers left un-restored | Next test file in the same worker inherits faked time, silently, until something times out for no visible reason |
| Global mutable singletons (module-level cache, in-memory counter) | Same class of bug as the `AsyncLocalStorage` case in observability.md — one test's mutation is visible to a concurrently running test |
| Assuming test execution order | Vitest/Jest can and do reorder or parallelize by default; "test 2 depends on state test 1 left behind" is a hidden coupling that a runner upgrade or a `--shard` CI split will break |

Fix: each test (or at minimum each file, if you accept file-level
sharing) gets its own transaction rolled back at the end, its own
container instance or its own logical DB/schema, and its own port
(`listen(0)` for an OS-assigned free port, or `inject()`/`supertest`
which needs no port at all).

## Snapshot tests: when they help, when they rot

```js
// helps — a large, stable, generated structure (a rendered email
// template, a complex serialized API response shape) where asserting
// field-by-field is tedious and the value of the test is "did this
// change unexpectedly"
expect(renderInvoiceEmail(invoice)).toMatchSnapshot();
```

Snapshots rot when the snapshotted value changes legitimately and often
— every change becomes a reflexive `--update` with nobody actually
reading the diff, at which point the test verifies nothing except that
someone ran the update command. Use snapshots for genuinely large,
rarely-and-deliberately-changed output; use explicit field assertions
for anything that changes as part of normal feature work, where you
*want* the diff to force a human to look at exactly what changed.

## Coverage: a floor, not a target

Coverage tells you what code never ran during the suite — it says
nothing about whether the assertions on the code that *did* run are any
good. A test that calls a function and asserts nothing about the result
scores full coverage on that function and validates zero behavior.
Treat a coverage threshold (`80%`, whatever your team picks) as a CI
gate against *regressions* in coverage — new code shipped genuinely
untested — not as a target to chase for its own sake by writing
assertion-free tests against uncovered lines.

## What NOT to test

- Framework internals (Fastify's own routing logic, Prisma's own query
  builder correctness) — that's the framework's test suite's job, not
  yours.
- Getters/setters and pure pass-through wrappers with no logic.
- Third-party library behavior — mock the library at your boundary and
  test that your code calls it correctly, don't re-verify the library
  itself works.
- Implementation details that aren't part of the public contract (private
  helper function's exact internal branching) — test through the public
  API so refactoring the internals doesn't force a rewrite of the test.
- Anything already covered at a lower, faster level — don't re-assert
  a unit-tested validation rule again at the E2E layer; assert instead
  that the E2E flow reaches the point where that validation would apply.

## Checklist

- [ ] Vitest is the default runner for new services; `node:test` for zero-dependency libraries; Jest only for existing Jest codebases
- [ ] The suite is weighted toward unit tests; integration and E2E shrink as you go up the pyramid
- [ ] Dependencies are constructor-injected so unit tests pass fakes with no module-mocking
- [ ] Integration tests use testcontainers-node against real Postgres/Redis — never sqlite standing in for Postgres
- [ ] One container per file/suite, not per test
- [ ] Slow/integration tests are tagged or path-separated so the fast suite stays fast in the everyday loop
- [ ] HTTP tests use `fastify.inject()` or `supertest` — no bound sockets, no port flakiness
- [ ] Outbound calls are stubbed with MSW or undici `MockAgent`, with real network connect disabled
- [ ] Timeout and retry logic is explicitly tested by injecting delays and transient failures — not assumed to work
- [ ] Fake timers are always restored (`afterEach`) and never leak into the next test
- [ ] Tests don't depend on execution order, shared DB state, or fixed ports
- [ ] Snapshots are reserved for large, rarely-changing output — not a substitute for explicit assertions on everyday logic
- [ ] Coverage is enforced as a regression floor, not chased as a target
