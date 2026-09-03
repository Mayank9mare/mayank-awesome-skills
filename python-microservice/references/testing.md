# Testing

## Layout & config

Mirror `src/` under `tests/` — a reader finds `tests/billing/test_invoice.py` for
`src/myservice/billing/invoice.py` without guessing.

```
src/myservice/
    billing/invoice.py
    users/models.py
tests/
    billing/test_invoice.py
    users/test_models.py
    conftest.py            # fixtures shared by the whole suite
    billing/conftest.py     # fixtures scoped to billing/ only
```

`conftest.py` files are visible to everything at or below their directory —
put a fixture at the narrowest `conftest.py` that needs it. A fixture every
test needs (an event loop policy, a test settings object) goes at the root; a
fixture only the billing tests need lives in `tests/billing/conftest.py` so
unrelated tests don't even know it exists.

```toml
# pyproject.toml
[tool.pytest.ini_options]
minversion = "8.0"
testpaths = ["tests"]
asyncio_mode = "auto"                    # no @pytest.mark.asyncio needed per-test
filterwarnings = ["error::DeprecationWarning"]  # catch deprecations before they break a release
addopts = "--strict-markers --strict-config"    # typo'd marker names fail loudly, not silently
```

## pytest essentials

**Fixture scopes** — `function` (default, fresh every test), `module` (once
per file), `session` (once per whole run). Pick the narrowest scope the setup
cost allows.

```python
# WRONG — session-scoped MUTABLE state. Test A appends to the list, test B
# runs later in the same session and inherits A's leftovers. Pass/fail now
# depends on execution order — the worst kind of flaky.
@pytest.fixture(scope="session")
def shared_cache():
    return {}   # a dict every test in the run shares and mutates

# RIGHT — session-scoped for expensive, IMMUTABLE or reset-per-use setup;
# function-scoped for anything a test mutates.
@pytest.fixture(scope="session")
def db_engine():
    engine = create_engine(TEST_DATABASE_URL)   # expensive: one per session
    yield engine
    engine.dispose()

@pytest.fixture()
def db_session(db_engine):
    with Session(db_engine) as session:          # cheap, fresh per test
        yield session
        session.rollback()
```

`@pytest.mark.parametrize` for input/output tables instead of copy-pasted test
functions:

```python
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("10.00", Decimal("10.00")),
        ("-5.50", Decimal("-5.50")),
        pytest.param("", None, id="empty-string"),
    ],
)
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == expected
```

Custom markers (`@pytest.mark.slow`, `@pytest.mark.integration`) registered in
`pyproject.toml` so `--strict-markers` catches typos instead of silently
running zero tests:

```toml
[tool.pytest.ini_options]
markers = [
    "slow: takes more than a second, excluded from the default fast run",
    "integration: needs a real DB/broker, run in a separate CI stage",
]
```

`-x` stops at first failure; `--ff` reruns last failures first — the
inner-loop combo for fixing a red suite: `pytest -x --ff`.

`pytest-xdist` (`pytest -n auto`) parallelizes across processes for wall-clock
speed. What breaks under it:

- **Shared DB state** — two workers hitting the same test database concurrently
  race on the same rows/tables unless each worker gets its own schema/database
  (`pytest-xdist` exposes a worker ID you can suffix a DB name with).
- **Ordering assumptions** — a suite that silently depended on test A running
  before test B (shared fixture leaking state, a module-level counter) breaks
  the instant tests are distributed across workers in a different order.
- **Global singletons** — anything patched at module import time process-wide
  needs to be per-worker-safe; xdist workers are separate processes so this is
  usually fine, but shared *external* resources (one Redis instance, one test
  DB) are not.

## Async tests

`pytest-asyncio` with `asyncio_mode = "auto"` (set above) runs any `async def
test_*` without a per-test decorator. The alternative, `anyio`'s pytest
plugin, is worth it if the codebase already depends on `anyio` for
backend-agnostic async code (it can run the same test under both asyncio and
trio backends) — pick one project-wide, mixing both plugins in one suite is a
support headache for no benefit.

> **pytest-asyncio 1.x (current: 1.4.0) — `asyncio_mode = "auto"` is unchanged, but the
> `event_loop` fixture is REMOVED.** That's the hard break coming from the 0.x line.
> - Anywhere a fixture took `event_loop` as an argument, drop it and use
>   `asyncio.get_running_loop()` inside the fixture instead.
> - `pytest.mark.asyncio(scope=…)` → **`pytest.mark.asyncio(loop_scope=…)`**.
> - On async fixtures, set both explicitly and make them match:
>   `@pytest_asyncio.fixture(loop_scope="module", scope="module")`.
> - If every async fixture shares one loop scope, set
>   `asyncio_default_fixture_loop_scope` in config instead of annotating each one — and
>   set it to `"function"` even if that's the default, to silence the deprecation warning.
> - Scoped loops are now created **once per scope** rather than possibly several times,
>   which speeds up collection in large suites.
>
> If your suite *re-implemented* `event_loop` (rather than just requesting it), follow the
> official v0.21 migration path: work outward from the deepest nesting level, recording
> each fixture's scope, then set matching `loop_scope` values.

**Event-loop-scope pitfall**: a fixture's scope and the event loop's scope are
two different things, and mismatching them is a common source of confusing
`RuntimeError: Event loop is closed` or "attached to a different loop"
failures.

```python
# WRONG — session-scoped async fixture, but the default event loop is
# function-scoped. The fixture's connection is created on loop #1; by the time
# test #2 runs on loop #2, the connection belongs to a closed loop.
@pytest.fixture(scope="session")
async def redis_client():
    client = redis.asyncio.Redis()
    yield client
    await client.aclose()

# RIGHT — match fixture scope to loop scope explicitly (pytest-asyncio's
# loop_scope marker/fixture option), or just keep the fixture function-scoped
# unless you've deliberately made the loop session-scoped too.
@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def redis_client():
    client = redis.asyncio.Redis()
    yield client
    await client.aclose()
```

If in doubt, keep both at `function` scope — the mismatch only shows up once
you start optimizing for setup cost, and it's a subtle enough failure mode
that it's not worth the risk without a real motivating slowdown.

## API tests in-process with `ASGITransport`

The current idiom: point an `httpx.AsyncClient` directly at the ASGI app, no
network socket, no running server process.

```python
import httpx

async def test_get_item():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/items/1")
    assert r.status_code == 200
```

**`ASGITransport` does not run the ASGI lifespan.** Startup/shutdown events —
the DB engine created in your `lifespan()`, the shared `httpx.AsyncClient` from
`http-clients.md` — never fire. A test that hits an endpoint depending on
`app.state.db` fails with an `AttributeError` that has nothing to do with the
endpoint's actual logic, and the failure is genuinely confusing the first time
you hit it because the code "looks right."

Fix: drive the lifespan yourself, either manually or with `asgi-lifespan`:

```python
from asgi_lifespan import LifespanManager

async def test_get_item():
    async with LifespanManager(app):                      # runs startup, then shutdown on exit
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get("/items/1")
    assert r.status_code == 200
```

```python
# Manual equivalent, no extra dependency:
async def test_get_item():
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get("/items/1")
```

A fixture wrapping this once means every test just asks for a ready `client`:

```python
@pytest_asyncio.fixture()
async def client():
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
```

**Contrast with `TestClient`** (`starlette.testclient.TestClient` /
`fastapi.testclient.TestClient`) — synchronous, wraps an internal portal to run
the async app from sync test code, and **does** run the lifespan for you via
its own context manager (`with TestClient(app) as client:`). Convenient for
sync test suites; the async-native `ASGITransport` path above is preferred
when the rest of the suite is already async, to avoid mixing sync and async
call styles in the same test file.

## Dependency overrides

FastAPI's dependency injection is designed to be overridden in tests — swap a
real DB session for a test one, a real auth dependency for a fake authenticated
user, without touching the endpoint code:

```python
async def override_get_session():
    async with test_session_factory() as session:
        yield session

@pytest.fixture()
def client_with_overrides():
    app.dependency_overrides[get_session] = override_get_session
    yield TestClient(app)
    app.dependency_overrides.clear()    # ALWAYS clear — leaked overrides poison later tests
```

An override left in `app.dependency_overrides` after a test finishes applies to
**every subsequent test in the process**, including ones that never asked for
it — a classic cause of "this test fails only when run after that other test."
Clear overrides in fixture teardown unconditionally, not just on the happy
path — use `yield` + cleanup, not a bare assignment, so it still runs if the
test itself raises.

## DB tests

**Use a real Postgres via testcontainers-python. Never SQLite as a
stand-in.** SQLite is a different dialect: it's dynamically typed (a column
declared `INTEGER` happily stores a string), enforces foreign keys only if you
remember to `PRAGMA foreign_keys=ON`, has different `UPSERT`/window-function
support, and different transaction/locking semantics (whole-database lock vs.
row-level). Tests green against SQLite regularly fail against the Postgres the
service actually runs in production — a `NOT NULL` violation, a type coercion,
a `SELECT ... FOR UPDATE` that no-ops — and these are exactly the
dialect-sensitive bugs that testing is supposed to catch before they escape.

```python
from testcontainers.postgres import PostgresContainer

@pytest.fixture(scope="session")
def postgres_container():
    with PostgresContainer("postgres:16-alpine") as container:
        yield container   # a real, disposable Postgres, torn down at session end

@pytest.fixture(scope="session")
def db_engine(postgres_container):
    engine = create_async_engine(postgres_container.get_connection_url())
    yield engine
```

**Transaction-rollback-per-test** — wrap each test in a transaction, roll it
back at the end. Fast (no schema teardown/recreate), but every test shares one
connection/transaction tree, which is subtle when the code under test opens
its *own* nested transaction or savepoint — a naive outer-transaction wrapper
can't see writes as "committed" mid-test the way production code expects, so
code that explicitly commits or relies on a separate connection observing its
writes needs a savepoint-aware fixture (SQLAlchemy's `session.begin_nested()`
pattern), not a plain outer rollback.

```python
@pytest.fixture()
async def db_session(db_engine):
    async with db_engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(bind=conn)
        yield session
        await trans.rollback()    # undo everything the test did, regardless of outcome
```

**Truncate-per-test** — let each test commit normally, truncate all tables
between tests. Slower (a truncate round-trip per test, sometimes per table),
but no ambiguity about nested transactions or what "committed" means inside
the test — the semantics match production exactly. Reach for this when the
rollback approach's savepoint subtlety causes more confusion than the extra
latency costs, e.g. suites that specifically test transactional behavior.

## Mocking HTTP

**respx** for `httpx` — mocks at the transport level, so it works whether the
code awaits with `AsyncClient` or calls sync:

```python
import respx
import httpx

@respx.mock
async def test_get_user_not_found():
    respx.get("https://api.example.com/users/1").mock(
        return_value=httpx.Response(404, json={"detail": "not found"}),
    )
    with pytest.raises(UserNotFound):
        await user_client.get_user("1")
```

**`responses`** for the `requests` library — same idea, registers URL patterns
and canned responses, intercepts at the adapter level.

**vcrpy** — records real HTTP interactions to a "cassette" file on first run,
replays them on subsequent runs. Useful for capturing a genuinely complex
third-party response shape once. The staleness risk is real: a cassette
recorded against a partner API six months ago silently diverges from what that
API returns today, and the test keeps passing against a fixture that no longer
reflects reality — schedule cassette re-recording, don't let it become
permanent fossilized state.

**Test timeouts and retries by injecting delays/faults**, not by hoping the
happy path exercises them:

```python
@respx.mock
async def test_retries_on_timeout_then_succeeds():
    route = respx.get("https://api.example.com/users/1")
    route.side_effect = [httpx.TimeoutException("boom"), httpx.Response(200, json={"id": 1})]
    user = await user_client.get_user("1")     # exercises the @retry from http-clients.md
    assert route.call_count == 2
```

An untested timeout/retry path is a guess about what happens under real
failure, not a verified behavior — the majority of retry logic bugs (retrying
non-idempotent calls, missing jitter, off-by-one attempt counts) are invisible
until the dependency actually degrades in production.

## Time & randomness

Inject a clock instead of patching `datetime.now`/`time.time` globally where
the code structure allows it — a `now: Callable[[], datetime]` parameter with
a default of `datetime.now` is trivially fakeable in a test without any
patching machinery, and doesn't affect code that doesn't take the parameter.

Where the code already calls the global directly (third-party code, or a large
surface you're not going to refactor), `freezegun` or `time-machine` patch it
for the duration of a test:

```python
import time_machine

@time_machine.travel("2026-01-01 12:00:00")
def test_expires_at_new_year():
    assert token_expires_at() == datetime(2026, 1, 1, 12, 5, 0)
```

`time-machine` is generally preferred over `freezegun` now — it patches at the
C level (`time.time`, `time.monotonic`, etc.) rather than by monkeypatching
Python-level references, which means it also correctly affects C-extension
code and is meaningfully faster.

## Factories

Prefer `factory-boy` or plain builder functions over one giant shared fixture
object that every test mutates a bit:

```python
class UserFactory(factory.Factory):
    class Meta:
        model = User

    id = factory.Sequence(lambda n: f"u_{n}")
    email = factory.LazyAttribute(lambda o: f"{o.id}@example.com")
    is_active = True

def test_inactive_user_cannot_login():
    user = UserFactory(is_active=False)   # override just what THIS test cares about
    assert not can_login(user)
```

A shared fixture (`@pytest.fixture def sample_user(): return User(...)`) that
several tests import and then each mutate a field on invites **inter-test
coupling**: test A's mutation is invisible to test B unless the fixture is
function-scoped and freshly constructed every time, and even then, a reader of
test B has to go find the fixture definition to know what "sample_user"
actually contains. A factory call with explicit overrides is self-documenting
at the call site.

## Property-based testing

`hypothesis` generates inputs instead of you enumerating them by hand —
disproportionately valuable for parsers, serializers, and validators, where the
interesting bugs are at boundaries a human wouldn't think to write by hand.

```python
from hypothesis import given, strategies as st

@given(st.text())
def test_parse_then_serialize_roundtrips(s):
    # Whatever parse() accepts, serialize(parse(x)) should reproduce x's meaning.
    # Hypothesis will find the empty string, unicode edge cases, whitespace-only
    # input, etc. — the exact cases a hand-written parametrize list misses.
    parsed = parse_amount(s) if is_valid_amount(s) else None
    if parsed is not None:
        assert parse_amount(serialize_amount(parsed)) == parsed
```

Hypothesis shrinks a failing case to the smallest input that still fails —
the bug report it hands you is already minimal.

## Coverage

`pytest --cov=myservice --cov-report=term-missing --cov-fail-under=80` is a
**floor**, not a target. It fails CI if coverage regresses below a line, which
catches "someone added a feature with zero tests." It does not, and cannot,
measure whether the tests that exist assert anything meaningful.

100% coverage as an explicit goal actively produces bad tests: to hit the last
few percent, people write tests that execute a line without asserting
anything about its behavior (a test that calls a function and checks it
doesn't raise, nothing more), which pads the number while adding no protection
against regressions. Chase coverage on code that matters — business logic,
edge cases, error paths — and accept that some lines (a `__repr__`, a defensive
`else: raise AssertionError("unreachable")`) aren't worth dedicated tests.

## What NOT to test

- **Pydantic validating its own types** — `field: int` rejecting a non-numeric
  string is pydantic's test suite's job, not yours. Test *your* validators
  (`@field_validator`) and your custom constraints, not the library's.
- **Framework wiring** — that FastAPI calls your route handler when the path
  matches, that a dependency with `Depends()` gets resolved — this is
  integration-tested implicitly every time any endpoint test runs; a dedicated
  test asserting "the router routes" tests the framework, not your code.
- **Mock-to-mock interactions** — a test that mocks every collaborator of the
  unit under test and then asserts the mocks were called in a certain order is
  testing that your mental model of the interaction matches itself; it breaks
  on refactors that change nothing observable and passes when the real
  collaborators would fail. Prefer testing observable behavior (return value,
  raised exception, state change) over call-sequence assertions on mocks.

## Checklist

- [ ] `tests/` mirrors `src/`; fixtures scoped to the narrowest `conftest.py` that needs them
- [ ] No mutable shared state in module/session-scoped fixtures
- [ ] `asyncio_mode = "auto"` set; async fixture/loop scopes matched deliberately
- [ ] API tests use `ASGITransport` + lifespan run explicitly (or `TestClient` if sync)
- [ ] `app.dependency_overrides` cleared in fixture teardown, unconditionally
- [ ] DB tests run against real Postgres via testcontainers, never SQLite
- [ ] Rollback-per-test vs truncate-per-test chosen deliberately, savepoint subtlety understood
- [ ] HTTP mocked with respx/responses; vcrpy cassettes have a re-recording plan
- [ ] Timeout/retry paths are exercised with injected faults, not assumed
- [ ] Clock injected or patched with time-machine, not left to real wall-clock time
- [ ] Test data built with factories/builders, not shared mutated fixture objects
- [ ] Hypothesis used for parsers/serializers/validators
- [ ] Coverage gate (`--cov-fail-under`) enforced as a floor, not chased to 100%
- [ ] No tests asserting framework/library behavior or mock-call-sequences in isolation
