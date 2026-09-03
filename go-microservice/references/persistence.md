# SQL persistence in Go

## Choosing the layer

| Approach | Use when |
|---|---|
| **pgx v5 + sqlc** | **Default for Postgres.** Write SQL, get typed Go. No reflection, no DSL. |
| pgx v5 native (`pgxpool`) | You need Postgres-specific features: `COPY`, `LISTEN/NOTIFY`, custom types. |
| `database/sql` + sqlx | Small surface, want `StructScan` and named params without codegen. |
| **ent** | Want compile-time-safe query building and graph traversal without writing SQL. |
| GORM | Team already knows it, or you want `AutoMigrate` in a prototype. Read the pitfalls. |
| squirrel | Genuinely dynamic SQL (optional WHERE clauses) that static codegen can't express. |

**Do not use `lib/pq`** — unmaintained. Use pgx.

## sqlc: the workflow

```sql
-- query.sql
-- name: GetUser :one
SELECT id, email, created_at FROM users WHERE id = $1;

-- name: ListActiveUsers :many
SELECT id, email FROM users
WHERE active = true AND created_at > $1
ORDER BY created_at DESC
LIMIT $2;

-- name: CreateUser :one
INSERT INTO users (email) VALUES ($1) RETURNING id, email, created_at;
```

```yaml
# sqlc.yaml
version: "2"
sql:
  - engine: postgresql
    schema: "migrations"          # point at your migration files
    queries: "query.sql"
    gen:
      go:
        package: "store"
        out: "internal/store"
        sql_package: "pgx/v5"     # generate pgx-native, not database/sql
        emit_pointers_for_null_types: true
```

`sqlc generate` produces typed methods whose return structs match the query's **actual
columns**. Change the SQL, regenerate, and the compiler shows you every call site that
must change. This is the property that makes it worth adopting: schema drift becomes a
build error instead of a runtime panic.

Run `sqlc generate` in CI and fail if the output differs from what's committed —
otherwise generated code silently goes stale.

## Pool configuration

```go
func openDB(ctx context.Context, cfg *Config) (*pgxpool.Pool, error) {
    pc, err := pgxpool.ParseConfig(cfg.DatabaseURL)
    if err != nil {
        return nil, fmt.Errorf("parse database url: %w", err)
    }

    pc.MaxConns = int32(cfg.DBMaxConns)          // total
    pc.MinConns = int32(cfg.DBMinConns)          // keep warm
    pc.MaxConnLifetime = 30 * time.Minute        // recycle even if healthy
    pc.MaxConnIdleTime = 5 * time.Minute         // trim after a spike
    pc.HealthCheckPeriod = 1 * time.Minute

    pool, err := pgxpool.NewWithConfig(ctx, pc)
    if err != nil {
        return nil, fmt.Errorf("create pool: %w", err)
    }

    // Fail fast at boot rather than on the first request.
    pingCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
    defer cancel()
    if err := pool.Ping(pingCtx); err != nil {
        pool.Close()
        return nil, fmt.Errorf("ping database: %w", err)
    }
    return pool, nil
}
```

With `database/sql`:

```go
db.SetMaxOpenConns(25)
db.SetMaxIdleConns(25)                   // ≈ MaxOpenConns avoids churn
db.SetConnMaxLifetime(30 * time.Minute)
db.SetConnMaxIdleTime(5 * time.Minute)
```

### Sizing

The constraint is the **database**, not your service. Work backwards:

```
per-instance MaxConns  ≈  (DB max_connections × 0.8)  /  number of instances
```

Leave headroom for migrations, admin sessions, and replicas you forgot about. Each
Postgres connection is a backend process with real memory cost; 50 replicas × a pool of
50 is 2,500 connections and a dead database.

Behind **pgbouncer in transaction mode**, disable prepared-statement caching or use
`pgx`'s simple protocol — cached prepared statements break when the pooler hands you a
different backend. This is a classic "works in staging, fails in prod" bug.

**`MaxConnLifetime` must be shorter** than any idle timeout in front of the database
(pooler, NLB), or you'll hand out connections the far end has already closed.

## Context and cancellation

Every query takes a context. When the client disconnects, the query is cancelled and the
connection is returned — this is one of Go's genuine advantages, and it only works if you
propagate the context.

```go
func (s *Store) GetUser(ctx context.Context, id string) (*User, error) {
    ctx, cancel := context.WithTimeout(ctx, 2*time.Second)
    defer cancel()

    row := s.pool.QueryRow(ctx, `SELECT id, email FROM users WHERE id = $1`, id)

    var u User
    if err := row.Scan(&u.ID, &u.Email); err != nil {
        if errors.Is(err, pgx.ErrNoRows) {
            return nil, ErrNotFound          // domain error, not a driver error
        }
        return nil, fmt.Errorf("get user %s: %w", id, err)
    }
    return &u, nil
}
```

Translate `pgx.ErrNoRows` / `sql.ErrNoRows` into a domain error at the store boundary.
Callers shouldn't import the driver to know a row was missing.

## Transactions

```go
// Pass a function so commit/rollback can't be forgotten.
func (s *Store) InTx(ctx context.Context, fn func(pgx.Tx) error) error {
    tx, err := s.pool.Begin(ctx)
    if err != nil {
        return fmt.Errorf("begin: %w", err)
    }
    // Rollback after Commit is a no-op, so this is safe and covers every
    // early return AND panic path.
    defer func() { _ = tx.Rollback(ctx) }()

    if err := fn(tx); err != nil {
        return err
    }
    if err := tx.Commit(ctx); err != nil {
        return fmt.Errorf("commit: %w", err)
    }
    return nil
}
```

Rules:

- **Keep transactions short.** No HTTP calls, no queue publishes, no sleeps inside one.
  An open transaction holds locks and a connection; a slow external call inside one is
  how you get lock pileups and pool exhaustion at the same time.
- **Never publish to a queue inside a transaction** and assume ordering — the consumer
  can read before you commit. Use the **outbox pattern**: insert the message into a table
  in the same transaction, and have a separate process publish it.
- Set an explicit isolation level when you depend on it; the default is
  `READ COMMITTED` in Postgres, which does *not* prevent lost updates.
- For "read then conditionally write", use a single atomic statement
  (`UPDATE … WHERE version = $2`, or `INSERT … ON CONFLICT`) instead of
  SELECT-then-INSERT. **A non-atomic check-then-insert under concurrency is a real,
  frequently-shipped bug** — two requests both see "not present" and both insert.

## Avoiding N+1

```go
// N+1: one query for orders, then one per order. 100 orders = 101 round trips.
for _, o := range orders {
    items, _ := store.ItemsByOrder(ctx, o.ID)
    o.Items = items
}

// One query, grouped in Go.
rows, _ := store.ItemsByOrderIDs(ctx, orderIDs)   // ... WHERE order_id = ANY($1)
byOrder := make(map[string][]Item, len(orderIDs))
for _, it := range rows {
    byOrder[it.OrderID] = append(byOrder[it.OrderID], it)
}
```

Go has no lazy loading, so N+1 is always explicit in the code — which makes it easier to
spot than in an ORM, and just as easy to write. Watch for it in loops.

## Migrations

Keep them **versioned, forward-only, and separate from application startup**.

```
migrations/
  0001_create_users.up.sql
  0001_create_users.down.sql
  0002_add_users_email_index.up.sql
```

```sh
migrate -path ./migrations -database "$DATABASE_URL" up
```

- **Do not run migrations from the app's normal startup path.** With N replicas starting
  simultaneously you get N concurrent migrators racing. Use a Kubernetes Job, an init
  container with a leader, or a separate deploy step.
- **Every migration must be backwards-compatible with the currently running code**, since
  during a rolling deploy both versions run at once. Adding a `NOT NULL` column with no
  default breaks the old version immediately.
- The safe expand/contract sequence: add nullable column → deploy code writing both →
  backfill → make it non-null → deploy code reading only the new column → drop the old.
- Use `CREATE INDEX CONCURRENTLY` in Postgres for large tables; a plain `CREATE INDEX`
  takes a write lock. Note it can't run inside a transaction, which some tools wrap by
  default.

## Health checks

```go
// Readiness only. Short timeout. Liveness must NOT check the database —
// see observability.md.
func (s *Store) Ping(ctx context.Context) error {
    ctx, cancel := context.WithTimeout(ctx, 2*time.Second)
    defer cancel()
    return s.pool.Ping(ctx)
}
```

Export pool stats as metrics — `pool.Stat()` gives acquired/idle/total counts. Saturation
of the pool is a leading indicator of user-visible latency, and it's invisible without
this.

## GORM pitfalls, if you must

- **Runtime reflection** for mapping and query building — measurably slower at scale
  than sqlc or raw SQL.
- **Convention magic**: auto-pluralised table names, implicit soft-delete via
  `DeletedAt` (so `Find` silently filters rows, and a "missing" row may just be
  soft-deleted), and preload behaviour that produces surprise N+1s unless associations
  are explicitly preloaded.
- **`AutoMigrate`** is convenient in dev and dangerous in production — it will happily
  make schema changes nobody reviewed. Use real migration files.
- Errors: `errors.Is(err, gorm.ErrRecordNotFound)`, not a nil check.

## Checklist

- [ ] pgx (not lib/pq); sqlc for typed queries
- [ ] `sqlc generate` verified in CI
- [ ] Pool sized from the DB's limit ÷ replica count, with headroom
- [ ] `MaxConnLifetime` < any upstream idle timeout
- [ ] Prepared statements disabled behind pgbouncer transaction mode
- [ ] `Ping` at boot — fail fast
- [ ] Context on every query, with a timeout
- [ ] `ErrNoRows` translated to a domain error
- [ ] Transactions short; no external calls inside; outbox for queue publishes
- [ ] Atomic upserts instead of check-then-insert
- [ ] Migrations run as a separate step, not from app startup
- [ ] Migrations backwards-compatible for rolling deploys
- [ ] Pool stats exported as metrics
