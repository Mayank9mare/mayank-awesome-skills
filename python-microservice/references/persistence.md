# Persistence

## Choosing a data layer

| Library | Style | Async | Verdict |
|---|---|---|---|
| **SQLAlchemy 2.0** | Full ORM + Core, `select()` style | Yes (`asyncpg`/`asyncmy` driver) | **Default choice.** Mature, explicit, scales from raw SQL to full ORM. |
| SQLModel | SQLAlchemy + Pydantic fusion | Yes | One model class for DB row *and* API schema. Convenient until they diverge — see below. |
| Tortoise ORM | Django-style async ORM | Yes | Pleasant API, smaller ecosystem, weaker migration tooling than Alembic. |
| asyncpg (raw) | Driver, no ORM | Yes | Fastest path to Postgres. No abstraction — you write and maintain every query string. |
| psycopg3 | Driver, sync + async | Yes | Modern successor to psycopg2. Good if you want driver-level control without asyncpg's Postgres-only lock-in. |
| Piccolo | Async ORM + admin UI | Yes | Batteries-included (migrations, admin), smaller community, steeper lock-in. |
| Prisma Python | Schema-first, codegen client | Yes | Excellent DX if you already run Prisma elsewhere; adds a Node-based codegen step to a Python build. |
| Django ORM | Full ORM, sync-first | Partial | Only if you're already inside Django. Async support exists but the ORM's roots are sync; don't adopt it standalone for a new async microservice. |

**SQLAlchemy 2.0 is the default** for the same reason httpx is the default HTTP
client: one API that covers the 90% case (typed models, migrations via Alembic,
async drivers) without foreclosing the 10% case (raw SQL via `text()`, Core
constructs for bulk operations).

**SQLModel's real caveat**: it makes one class serve as both the SQLAlchemy table
definition and the Pydantic validation schema. This is comfortable for CRUD
demos and actively fights you the moment the two need to diverge — and they
always eventually diverge. A `User` table has a `password_hash` column that must
never appear in an API response; an API `UserCreate` schema needs a `password`
field that doesn't exist as a column at all. SQLModel makes you bolt on
`exclude`/response-model gymnastics to undo the coupling it started with. Keep
persistence models and API schemas as two separate classes from day one (see
§8) and this problem never exists.

## SQLAlchemy 2.0 style — not the legacy `Query` API

SQLAlchemy 1.x code used `session.query(User).filter(...)`. That's legacy style,
still supported, and you should not write new code in it. 2.0 style uses
`select()` uniformly for Core and ORM:

```python
from sqlalchemy import select

# WRONG — legacy 1.x Query API. Works, but not what you should write today.
user = session.query(User).filter(User.id == uid).first()

# RIGHT — 2.0 select() style, works identically for sync and async sessions
stmt = select(User).where(User.id == uid)
result = await session.execute(stmt)
user = result.scalar_one_or_none()
```

Declarative models use `Mapped[]` type annotations and `mapped_column()` instead
of the old `Column(...)` class-attribute style — this gets you real type checking
on model attributes:

```python
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    total: Mapped[Decimal] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(default="pending")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # nullable via Optional, not a separate kwarg dance
    cancelled_at: Mapped[datetime | None] = mapped_column(default=None)

    items: Mapped[list["OrderItem"]] = relationship(back_populates="order")


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    sku: Mapped[str] = mapped_column()
    quantity: Mapped[int] = mapped_column(default=1)

    order: Mapped["Order"] = relationship(back_populates="items")
```

`Mapped[str]` is `NOT NULL` by inference; `Mapped[str | None]` is nullable. No
more forgetting `nullable=False` — the type annotation *is* the constraint
declaration, and your type checker enforces it too.

## Async engine + session

```python
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine, AsyncSession

engine = create_async_engine(
    "postgresql+asyncpg://user:pass@localhost/myservice",
    pool_size=10,
    max_overflow=5,
    pool_pre_ping=True,     # cheap SELECT 1 before handing out a pooled conn
    pool_recycle=1800,      # recycle before the DB or LB drops idle conns
)

# expire_on_commit=False is not a style preference — it's load-bearing.
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
```

**Why `expire_on_commit=False` matters**: SQLAlchemy's default
(`expire_on_commit=True`) marks every loaded attribute "expired" the instant you
commit, so the *next* access re-fetches it from the DB — a safety feature in
sync code, where that re-fetch just runs another query on the same thread. In
async code the re-fetch needs to run inside the event loop's greenlet context,
and touching an expired attribute after commit, outside of an `await`, raises:

```
sqlalchemy.exc.MissingGreenlet: greenlet_spawn has not been called; can't call
await_only() here. Was IO attempted in an unexpected place?
```

This is one of the most confusing errors newcomers to async SQLAlchemy hit,
and it usually looks unrelated to the real cause — code like
`return OrderOut.model_validate(order)` *after* `await session.commit()`, where
`model_validate` touches `order.total` and that attribute is expired. Setting
`expire_on_commit=False` on the sessionmaker turns this off globally, which is
what you want for a request-scoped async session: read what you already have,
don't silently re-query.

**Session-per-request** via a FastAPI dependency, `async with` for guaranteed
close:

```python
from fastapi import Depends
from typing import Annotated, AsyncIterator


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
        # no commit here — see §6, commit is the handler's job, not the dependency's


DbSession = Annotated[AsyncSession, Depends(get_session)]


@app.get("/orders/{order_id}")
async def get_order(order_id: int, db: DbSession) -> OrderOut:
    order = await db.get(Order, order_id)
    return OrderOut.model_validate(order)
```

**A session is not thread/task-safe.** Never hand the same `AsyncSession`
instance to two concurrently-running coroutines (e.g. inside an
`asyncio.gather` or `TaskGroup`). SQLAlchemy's async session has internal state
tied to a single logical unit of work; concurrent use corrupts it in ways that
surface as baffling, intermittent errors far from the actual bug. One session
per request, one request's work runs through it sequentially. If you must fan
out concurrent DB work, give each concurrent task its own session.

## N+1 and lazy loading

In sync SQLAlchemy, touching an unloaded relationship silently issues another
query — the classic N+1: list 50 orders, touch `order.items` on each, get 51
queries. **In async SQLAlchemy, implicit lazy loading doesn't silently
query — it raises `MissingGreenlet`.** This looks like a limitation. It's
actually a feature: it turns a silent performance bug into a loud, immediate
crash during development, instead of a slow endpoint discovered in production
under load.

Fix it by loading what you need, explicitly, in the original query:

```python
from sqlalchemy.orm import selectinload, joinedload

# selectinload — separate SELECT ... WHERE id IN (...) for the relationship.
# Safe with LIMIT/OFFSET on the parent query — the parent result set is exactly
# what you asked for, the children come in a second round-trip.
stmt = select(Order).options(selectinload(Order.items)).limit(20)

# joinedload — single query via LEFT OUTER JOIN.
# Fewer round-trips, but for a one-to-many it duplicates the parent row once
# per child — and it BREAKS LIMIT/OFFSET on the parent, because the limit
# applies to the joined row count, not the number of distinct orders.
stmt = select(Order).options(joinedload(Order.items))  # do not combine with .limit()
```

| | `selectinload` | `joinedload` |
|---|---|---|
| Round trips | 2 (parent, then children by IN) | 1 |
| Row duplication | None | Duplicates parent per child row |
| Safe with `LIMIT`/pagination on parent | Yes | **No** |
| Best for | One-to-many, paginated lists | Many-to-one / one-to-one, small fixed sets |

Rule of thumb: `selectinload` for collections you're paginating, `joinedload`
for a single required parent-side object (e.g. `Order.customer`) where there's
no row multiplication risk.

Catch accidental lazy loads in tests before they hit production:

```python
from sqlalchemy.orm import raiseload

# In test fixtures: any relationship access that wasn't explicitly eager-loaded
# raises immediately, instead of passing in dev (where it "works", just slowly)
# and only failing under async production load.
stmt = select(Order).options(raiseload("*"))
```

## Pool configuration

```python
engine = create_async_engine(
    dsn,
    pool_size=10,          # steady-state connections kept open
    max_overflow=5,        # extra connections allowed under burst, then released
    pool_pre_ping=True,    # validate a pooled conn with SELECT 1 before use
    pool_recycle=1800,     # force-recycle conns older than this (seconds)
    pool_timeout=30,       # how long to wait for a free conn before erroring
)
```

**Sizing is a multiplication problem, not a single number.** Each gunicorn/
uvicorn *worker process* creates its own engine and therefore its own pool —
pools are not shared across processes. `pool_size=20` with 4 workers is 80
connections from a single replica, and with 3 replicas that's 240 connections
against the database. Size from the database backward:

```
max_connections_on_db ÷ (replica_count × worker_count_per_replica) = safe pool_size (+ small max_overflow)
```

Forgetting this — setting a "reasonable-looking" `pool_size=20` without
checking replica × worker count — is a very common outage: a routine autoscale
event that doubles replica count silently doubles total connection demand and
the database starts rejecting connections at exactly the moment you needed
more capacity.

**pgbouncer in transaction pooling mode breaks prepared statements.** asyncpg
(and psycopg in some modes) prepares statements server-side and caches them by
name; pgbouncer transaction mode hands out a different backend connection per
transaction, so a prepared statement created on one backend doesn't exist on
the next one you're routed to. The failure looks like intermittent
`prepared statement "..." does not exist` errors that seem to come from
nowhere. Fix by disabling the statement cache for asyncpg, or disabling
SQLAlchemy's connection pool entirely and letting pgbouncer be the only pool:

```python
# asyncpg: disable prepared statement caching when behind pgbouncer transaction mode
engine = create_async_engine(
    dsn,
    connect_args={"statement_cache_size": 0, "prepared_statement_cache_size": 0},
    poolclass=NullPool,   # let pgbouncer do the pooling; don't pool twice
)
```

## Transactions

```python
async def transfer(db: AsyncSession, from_id: int, to_id: int, amount: Decimal) -> None:
    async with db.begin():                 # commits on success, rolls back on exception
        from_acct = await db.get(Account, from_id, with_for_update=True)
        to_acct = await db.get(Account, to_id, with_for_update=True)
        from_acct.balance -= amount
        to_acct.balance += amount
    # transaction is closed here — commit already happened
```

Keep transactions short: acquire what you need, mutate, commit. **Never do an
HTTP call or enqueue a Celery/arq task inside an open transaction.** Both
failure directions are real:

- The task fires and a worker picks it up *before* your transaction commits —
  the worker looks up a row that, from its point of view, doesn't exist yet.
- The task fires, then something later in the same transaction fails and rolls
  back — now you've told the outside world about a database change that never
  actually happened.

Enqueue after commit, or use the outbox pattern (see `messaging.md` §8) —
write the "please send this" row in the same transaction as the data change,
and a separate relay process publishes it only after that transaction is
durably committed.

**Atomic upserts instead of check-then-insert.** The naive pattern has a race:

```python
# WRONG — two concurrent requests for the same key both see "absent",
# both proceed to INSERT, one gets a UniqueViolation. Racy by construction:
# there's a gap between the SELECT and the INSERT where another request
# can slip in.
existing = await db.scalar(select(Setting).where(Setting.key == key))
if existing is None:
    db.add(Setting(key=key, value=value))
    await db.commit()

# RIGHT — one atomic statement. The database itself resolves the race;
# there is no window between "check" and "act" for another request to enter.
from sqlalchemy.dialects.postgresql import insert as pg_insert

stmt = (
    pg_insert(Setting)
    .values(key=key, value=value)
    .on_conflict_do_nothing(index_elements=["key"])
)
await db.execute(stmt)
await db.commit()
```

## Alembic

Async projects need an async `env.py`. The shape:

```python
# migrations/env.py
import asyncio
from sqlalchemy.ext.asyncio import async_engine_from_config

def run_migrations_online() -> None:
    connectable = async_engine_from_config(config.get_section(config.config_ini_section))

    async def do_run() -> None:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)   # bridge back to sync Alembic API
        await connectable.dispose()

    asyncio.run(do_run())
```

**Autogenerate is a draft, not a migration.** `alembic revision --autogenerate`
reliably catches new/dropped tables and columns, but it misses or mishandles:

- Server-side `default=`/`server_default` changes on existing columns
- Some type narrowing/widening (e.g. `VARCHAR(50)` → `VARCHAR(20)` needs a
  manual data-truncation decision Alembic won't make for you)
- Index and constraint **renames** — these show up as a drop + create of a
  differently-named index, which is often fine but occasionally means a brief
  window with no index at all
- Check constraints and some Postgres-specific types

Always open and read the generated migration before running it. Autogenerate
is a starting point for a human, not a source of truth.

**Never run migrations from application startup with N replicas.** If your
lifespan hook runs `alembic upgrade head`, every one of your N replicas races
to run it on boot — concurrent `ALTER TABLE`s against the same table, migration
locks colliding, or (worse) two replicas both deciding they're the one to add
a column. Migrations are a deploy-pipeline step, run exactly once, before the
new replicas start serving traffic.

**Expand-contract for rolling deploys** — you cannot atomically swap both the
schema and the code across a fleet that's rolling one replica at a time; for
any window during the rollout, old and new code run against the same schema
simultaneously. Split every breaking schema change into steps that are each
individually safe for *both* code versions:

1. **Expand**: add the new column/table, nullable or with a default. Old code
   ignores it; nothing breaks.
2. **Backfill**: populate the new column for existing rows (batched, off
   peak).
3. **Deploy new code** that writes to both old and new columns (dual-write),
   or reads from new with a fallback to old.
4. **Deploy again**, now reading/writing only the new column. At this point
   every replica is running code that no longer needs the old column.
5. **Contract**: drop the old column in a later migration, once you're certain
   no replica anywhere (including any slow rollback path) still needs it.

Never combine "add column" and "drop old column" in the same migration for a
rolling deploy — that's exactly the atomic swap that doesn't exist.

## Pydantic vs ORM models — keep them separate

Returning an ORM object directly from a FastAPI handler is how a `password_hash`
column, an internal `is_admin` flag, or a foreign `tenant_id` ends up in a JSON
response — the ORM model has every column, and nothing forces you to filter it
per-endpoint.

```python
class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)   # allow building from an ORM instance, not just a dict

    id: int
    email: str
    display_name: str
    # password_hash deliberately absent — it can't leak if the schema doesn't have the field


@app.get("/users/{uid}")
async def get_user(uid: int, db: DbSession) -> UserOut:
    user = await db.get(User, uid)          # ORM object — has password_hash, everything
    return UserOut.model_validate(user)     # explicit allow-list via the schema's fields
```

The ORM model describes what's *in the database*. The Pydantic schema describes
what's *allowed to leave the process*. Collapsing them (see SQLModel's caveat,
§1) collapses that boundary too.

## Checklist

- [ ] 2.0-style `select()` everywhere; no legacy `session.query(...)`
- [ ] Declarative models use `Mapped[]` / `mapped_column()`, not bare `Column`
- [ ] `async_sessionmaker(expire_on_commit=False)` — not the default
- [ ] Session created per-request via a dependency, closed with `async with`
- [ ] No session instance shared across concurrent tasks/coroutines
- [ ] Eager-loading (`selectinload`/`joinedload`) chosen deliberately per relationship; `raiseload("*")` in tests
- [ ] Pool size calculated as `db_max_connections ÷ (replicas × workers)`, not guessed
- [ ] `pool_pre_ping=True`, sane `pool_recycle`
- [ ] pgbouncer transaction mode → `NullPool` or statement cache disabled
- [ ] Transactions are short; no HTTP calls or task enqueues inside one
- [ ] Upserts use `ON CONFLICT`, not check-then-insert
- [ ] Alembic migrations reviewed by hand after autogenerate, run in deploy pipeline (not app startup)
- [ ] Breaking schema changes use expand-contract across the rolling deploy
- [ ] API schemas are separate classes from ORM models, built via `from_attributes=True`
