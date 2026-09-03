# Queues, streams & background work in Go

## Choosing

| Need | Use |
|---|---|
| Background jobs, already on Postgres | **River** — transactional enqueue, no extra broker |
| Background jobs, Redis available | Asynq |
| Event streaming, high throughput, replay | **franz-go** (Kafka) |
| Cloud-native queue, minimal ops | AWS SDK Go v2 + SQS |
| Lightweight pub/sub, request-reply | NATS (JetStream for persistence) |
| Classic broker, complex routing | RabbitMQ (`amqp091-go`) |

**River's key property**: jobs are rows inserted **in the same transaction as your
business data**. If the transaction commits, the job exists; if it rolls back, so does the
job. That's an outbox for free, and it's the strongest reason to prefer a
Postgres-backed queue when you're already on Postgres.

## At-least-once is the only delivery you get

Every broker worth using guarantees *at least* once. Therefore **idempotent consumers are
mandatory, not a nice-to-have.** Any handler that isn't idempotent will eventually
double-charge someone.

### Check-then-insert is not atomic

This is the bug that ships most often:

```go
// BROKEN under concurrency. Two consumers process a redelivered message
// simultaneously: both SELECT and see nothing, both INSERT.
// Real production incidents look exactly like this.
existing, err := q.FindByExternalID(ctx, msg.ID)
if err == nil && existing != nil {
    return nil                  // already processed
}
return q.Insert(ctx, msg)
```

```go
// CORRECT: let the database enforce uniqueness atomically.
// Requires: UNIQUE constraint on external_id.
const stmt = `
    INSERT INTO processed_messages (external_id, processed_at)
    VALUES ($1, now())
    ON CONFLICT (external_id) DO NOTHING`

res, err := tx.Exec(ctx, stmt, msg.ID)
if err != nil {
    return fmt.Errorf("dedupe insert: %w", err)
}
if res.RowsAffected() == 0 {
    return nil          // someone else already handled it. Ack and move on.
}
return doWork(ctx, tx, msg)     // same transaction as the dedupe row
```

The dedupe insert and the work must be in **one transaction**, or you can record "done"
and then fail the work (or vice versa).

Other idempotency strategies, in rough order of preference:

1. **Natural idempotency** — the operation is a set-to-value, not an increment. `UPDATE
   balance SET x = 100` is replay-safe; `x = x + 10` is not.
2. **Unique constraint on a business key** — the above.
3. **Idempotency key from the producer**, stored with a unique constraint.
4. **Conditional update with a version/state guard** —
   `UPDATE orders SET state='shipped' WHERE id=$1 AND state='paid'`; zero rows affected
   means someone beat you to it.

## SQS consumer

```go
func runConsumer(ctx context.Context, client *sqs.Client, queueURL string) error {
    for {
        // Long polling: one call waits up to 20s for a message instead of
        // returning empty immediately. Cuts both API cost and latency.
        out, err := client.ReceiveMessage(ctx, &sqs.ReceiveMessageInput{
            QueueUrl:            &queueURL,
            MaxNumberOfMessages: 10,
            WaitTimeSeconds:     20,
            VisibilityTimeout:   60,
            MessageAttributeNames: []string{"All"},
        })
        if err != nil {
            if ctx.Err() != nil {
                return nil          // shutdown, not a failure
            }
            slog.ErrorContext(ctx, "receive failed", "error", err)
            // Back off, or a persistent error becomes a hot spin loop.
            select {
            case <-time.After(time.Second):
            case <-ctx.Done():
                return nil
            }
            continue
        }

        for _, m := range out.Messages {
            // Give each message a budget SHORTER than the visibility timeout,
            // so we finish (or give up) before the message is redelivered.
            mctx, cancel := context.WithTimeout(ctx, 45*time.Second)
            if err := handle(mctx, m); err != nil {
                cancel()
                // Do NOT delete. Let the visibility timeout expire so it's
                // redelivered, and eventually lands in the DLQ.
                slog.ErrorContext(ctx, "handler failed",
                    "message_id", aws.ToString(m.MessageId), "error", err)
                continue
            }
            cancel()

            if _, err := client.DeleteMessage(ctx, &sqs.DeleteMessageInput{
                QueueUrl:      &queueURL,
                ReceiptHandle: m.ReceiptHandle,
            }); err != nil {
                // Delete failed after successful work → the message WILL be
                // redelivered. This is exactly why handlers must be idempotent.
                slog.ErrorContext(ctx, "delete failed", "error", err)
            }
        }
    }
}
```

### The visibility timeout trap

If processing takes **longer** than the visibility timeout, SQS redelivers the message
**while you are still working on it**. Now two workers process the same message
concurrently — and if the work isn't idempotent, you've duplicated it.

Rules:
- Set `VisibilityTimeout` > p99 processing time, with margin.
- Give the handler context a timeout **below** the visibility timeout.
- For genuinely long work, extend the visibility periodically
  (`ChangeMessageVisibility`) or move the work to a queue designed for it.

### Graceful shutdown of a consumer

The consumer loop takes the shutdown context, so `ReceiveMessage` returns on cancel and
the loop exits. Stop consumers **after** draining HTTP, and let the in-flight message
finish — see packaging-deploy.md for the full ordering.

## Kafka with franz-go

```go
cl, err := kgo.NewClient(
    kgo.SeedBrokers(cfg.Brokers...),
    kgo.ConsumerGroup("myservice"),
    kgo.ConsumeTopics("orders"),
    // Manual commit = at-least-once. Auto-commit can advance the offset for a
    // record you haven't finished processing, which is at-MOST-once and will
    // silently lose work on a crash.
    kgo.DisableAutoCommit(),
    kgo.FetchMaxBytes(10 << 20),
)

for {
    fetches := cl.PollRecords(ctx, 500)
    if fetches.IsClientClosed() || ctx.Err() != nil {
        return nil
    }
    fetches.EachError(func(t string, p int32, err error) {
        slog.ErrorContext(ctx, "fetch error", "topic", t, "partition", p, "error", err)
    })

    var failed bool
    fetches.EachRecord(func(r *kgo.Record) {
        if err := handle(ctx, r); err != nil {
            failed = true
        }
    })
    if failed {
        continue      // don't commit; the batch is redelivered
    }
    if err := cl.CommitUncommittedOffsets(ctx); err != nil {
        slog.ErrorContext(ctx, "commit failed", "error", err)
    }
}
```

Things that cause real outages:

- **`max.poll.interval.ms` vs slow processing.** If the gap between polls exceeds it, the
  broker decides you're dead and **rebalances the group**. Your work is redelivered
  elsewhere while you're still doing it, and the group thrashes. Fix by processing faster,
  polling smaller batches, or raising the interval deliberately.
- **Partitions cap useful parallelism.** 4 partitions means at most 4 useful consumers in
  a group; a 5th sits idle. Scale partitions, not just replicas.
- **Ordering is per-partition only.** Same key → same partition → ordered. Across
  partitions there is no ordering, ever.
- **Producer durability**: `acks=all` plus the idempotent producer, or you can lose
  records on leader failover.
- **Rebalances are not free.** Frequent rebalancing (from slow processing, short
  timeouts, or churning replicas) can stall consumption entirely.

## Retries and backoff

```go
// Exponential backoff with FULL JITTER. Jitter is mandatory: without it, every
// consumer that failed at the same instant retries at the same instant and
// finishes off a dependency that was recovering.
backoff := min(base<<attempt, maxBackoff)
sleep := time.Duration(rand.Int64N(int64(backoff)))
```

Classify failures before retrying:

| Failure | Action |
|---|---|
| Timeout, connection refused, 5xx, throttled | **Retry** with backoff + jitter |
| Validation error, malformed payload, 4xx | **Do not retry** — send straight to the DLQ |
| Poison message (fails deterministically) | DLQ immediately; retrying burns capacity forever |

Retrying a non-retryable failure is worse than useless: it delays the DLQ, consumes
throughput, and buries the real error behind N identical log lines.

## Dead letter queues

Configure a redrive policy so messages that fail repeatedly move to a DLQ instead of
cycling forever.

- **`maxReceiveCount` is the number of *receives*, not retries.** `maxReceiveCount=1`
  means a single transient blip sends the message straight to the DLQ with **no retry at
  all** — often not what was intended. 3–5 is a more usual choice.
- **A DLQ with no alarm is useless.** Alert on `ApproximateNumberOfMessagesVisible > 0`.
  A silent DLQ is just a place where data goes to be forgotten.
- **Keep a redrive path.** You need a documented way to inspect messages, fix the cause,
  and replay them — and replay is only safe because your consumers are idempotent.
- Log enough context on the failure that a DLQ message is diagnosable without a repro.

## The outbox pattern

**Never publish to a broker inside a database transaction.**

Two ways it breaks:
1. You publish, then the transaction rolls back. The message describes something that
   never happened.
2. You publish before commit, and the consumer reads the row **before it exists**.
   Intermittent, load-dependent, and miserable to debug.

```sql
CREATE TABLE outbox (
    id            BIGSERIAL PRIMARY KEY,
    aggregate_id  TEXT        NOT NULL,
    topic         TEXT        NOT NULL,
    payload       JSONB       NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at  TIMESTAMPTZ
);
CREATE INDEX outbox_unpublished ON outbox (id) WHERE published_at IS NULL;
```

```go
// In the SAME transaction as the business write. Atomic by construction.
err := store.InTx(ctx, func(tx pgx.Tx) error {
    if err := insertOrder(ctx, tx, order); err != nil {
        return err
    }
    return insertOutbox(ctx, tx, "orders", order)
})
```

A separate publisher polls unpublished rows (`FOR UPDATE SKIP LOCKED`), publishes, and
marks them sent. Publishing may happen more than once — which is fine, because consumers
are idempotent. Alternatively use CDC (Debezium) to tail the WAL.

**With River this is built in**: the job insert *is* the transactional write, so there's
no separate outbox table to maintain.

## Worker deployment

- **Run workers as a separate deployment** from the HTTP service. Different scaling
  profile, different failure modes, and you don't want a queue backlog to compete with
  request handling for CPU.
- **Bound concurrency.** `errgroup.SetLimit`, or a fixed worker count. Unbounded workers
  against a dependency is a self-inflicted DoS.
- **Expose readiness/liveness for workers too** — a wedged consumer that still answers
  liveness looks healthy forever. Consider a "last successful poll" freshness check.
- **Metrics that matter**: queue depth, oldest-message age (the best single signal of
  consumer health), processing duration, failure rate, DLQ depth. Alert on **oldest
  message age**, not just depth — a slowly draining queue and a stalled one look the same
  by depth alone.

## Testing

```go
// Real broker via testcontainers-go beats a mock: it exercises serialisation,
// acknowledgement semantics, and redelivery — where the actual bugs live.
container, err := localstack.Run(ctx, "localstack/localstack:latest")
```

Test explicitly:
- **The redelivery path** — process the same message twice and assert one effect.
- **A poison message** goes to the DLQ rather than cycling.
- **Visibility-timeout expiry** during slow processing.
- **Graceful shutdown** mid-message doesn't lose or duplicate work.

Use a polling assertion helper with a timeout rather than `time.Sleep` — sleeps are
simultaneously flaky and slow.

## Checklist

- [ ] Handlers idempotent — via natural idempotency, a unique constraint, or a guarded update
- [ ] Dedupe and work in the **same** transaction
- [ ] No check-then-insert; `ON CONFLICT DO NOTHING` instead
- [ ] Long polling enabled (SQS `WaitTimeSeconds=20`)
- [ ] Handler timeout **below** the visibility timeout
- [ ] Visibility timeout above p99 processing, with margin
- [ ] Kafka: manual commit, poll interval vs processing time understood, partitions ≥ consumers
- [ ] Retries: classified, capped, jittered
- [ ] Non-retryable failures go straight to the DLQ
- [ ] `maxReceiveCount` ≥ 3 (1 means no retries at all)
- [ ] **DLQ has an alarm** and a documented redrive path
- [ ] Outbox (or River) instead of publishing inside a transaction
- [ ] Consumers exit cleanly on context cancellation
- [ ] Alert on **oldest message age**, not only queue depth
