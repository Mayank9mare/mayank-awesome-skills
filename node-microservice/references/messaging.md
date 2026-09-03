# Messaging and background work in Node

## The one thing to internalize first

A message queue delivering a job and your database committing a row are
**two separate systems with no shared transaction**. Every design mistake
in this file is a variation of forgetting that fact — either dropping a
job that should have survived, or processing the same job twice because
"exactly once" isn't a thing queues actually give you.

## BullMQ (Redis-backed)

BullMQ is the standard choice for Redis-backed job queues in Node. A queue
producer enqueues jobs; one or more workers (usually a separate process
from your web server — see below) consume them.

```js
import { Queue, Worker } from 'bullmq';

const connection = { host: 'redis.internal', port: 6379 };

const emailQueue = new Queue('email', { connection });

await emailQueue.add(
  'welcome-email',
  { userId: user.id },
  {
    attempts: 5,
    backoff: { type: 'exponential', delay: 2000 },   // 2s, 4s, 8s, 16s, 32s
    removeOnComplete: { age: 3600, count: 1000 },    // don't let Redis grow unbounded
    removeOnFail: { age: 86400 },                     // keep failures longer, for inspection
  },
);
```

```js
const worker = new Worker(
  'email',
  async (job) => {
    await sendEmail(job.data.userId);   // throw to trigger a retry per the `attempts`/`backoff` above
  },
  {
    connection,
    concurrency: 10,   // how many jobs THIS worker process runs in parallel
  },
);

worker.on('failed', (job, err) => {
  logger.error({ jobId: job?.id, err }, 'job failed permanently');
});
```

Key knobs and why they matter:

- **`attempts` + `backoff`** — without both, a transient failure (a
  downstream 503) either never retries (no `attempts`) or retries instantly
  in a tight loop, hammering an already-struggling dependency (`attempts`
  with no `backoff`). BullMQ's `backoff.type: 'exponential'` doesn't add
  jitter itself — for high-volume queues where many jobs fail at once
  (a downstream outage), consider a custom backoff function that adds
  jitter, for the same thundering-herd reason retries need jitter anywhere
  else.
- **`removeOnComplete`/`removeOnFail`** — BullMQ keeps completed/failed job
  data in Redis by default until you tell it otherwise. On a busy queue
  this is a silent, steadily growing memory leak in Redis. Always bound it.
- **`concurrency`** — per-worker-process parallelism. Total throughput is
  `concurrency × number of worker processes/replicas`. Tune concurrency to
  the job's bottleneck (CPU-bound jobs want low concurrency close to core
  count; I/O-bound jobs waiting on network calls can go much higher).
- **Repeatable jobs** (`{ repeat: { pattern: '0 * * * *' } }`, cron syntax)
  replace a separate cron daemon for in-app scheduled work — but the
  schedule lives in Redis, so a Redis flush silently deletes your
  "recurring" jobs. Don't treat repeatable jobs as your only source of
  truth for critical schedules without monitoring that they're still firing.

## A Redis-backed queue is not transactional with your database

```js
// WRONG — if the process crashes between the DB write and the enqueue call,
// the order exists but the confirmation email never gets queued. No error,
// no retry, just a silently missing side effect.
async function placeOrder(data) {
  const order = await db.order.create({ data });
  await emailQueue.add('order-confirmation', { orderId: order.id });
  return order;
}
```

This is the classic dual-write problem: two independent systems, one
logical operation, no atomicity between them. The fix is the **outbox
pattern** — write the "intent to enqueue" in the *same database
transaction* as the business data, then a separate process reads
outbox rows and actually enqueues them (retrying that step is safe because
it's idempotent — see below):

```js
// RIGHT — the outbox row is committed atomically with the order, in the
// same DB transaction. If the transaction commits, the outbox row exists
// and WILL eventually be picked up. If it rolls back, neither exists.
async function placeOrder(data) {
  return db.$transaction(async (tx) => {
    const order = await tx.order.create({ data });
    await tx.outbox.create({
      data: { type: 'order-confirmation', payload: { orderId: order.id } },
    });
    return order;
  });
}

// A separate poller (or a CDC/logical-replication pipeline) reads
// unpublished outbox rows and enqueues them, marking each as published
// only after the enqueue call succeeds.
async function publishOutbox() {
  const rows = await db.outbox.findMany({ where: { publishedAt: null }, take: 100 });
  for (const row of rows) {
    await emailQueue.add(row.type, row.payload);
    await db.outbox.update({ where: { id: row.id }, data: { publishedAt: new Date() } });
  }
}
```

The outbox poller can crash between enqueueing and marking published —
that's fine, because it just re-enqueues on the next pass, and the consumer
is idempotent anyway. The property you've bought is: **the business write
and the "we intend to send a message" write are atomic together**, even
though the actual message delivery is not.

## SQS and Kafka in Node

SQS (via the AWS SDK) and Kafka (via `kafkajs`) show up when you're
integrating with infra outside a single Redis instance, need durability
guarantees Redis-backed queues don't provide, or need Kafka's
ordered-partition/consumer-group/replay semantics.

```js
// kafkajs consumer skeleton
const consumer = kafka.consumer({ groupId: 'myservice-order-events' });
await consumer.connect();
await consumer.subscribe({ topic: 'orders', fromBeginning: false });

await consumer.run({
  eachMessage: async ({ message }) => {
    const event = JSON.parse(message.value.toString());
    await handleOrderEvent(event);   // must be idempotent — see below
  },
});
```

Whichever transport you use, the delivery guarantee you actually get in
practice is **at-least-once** — a message can and will be redelivered
(consumer crash after processing but before ack, network partition during
ack, a rebalance, a retry after a timeout that the original attempt
actually completed). "Exactly-once" marketing on any of these systems
describes narrow conditions (single-partition Kafka transactions,
specific SDK configurations) that don't survive contact with a real
multi-service architecture. Design every consumer as if redelivery is
certain, because it is.

## Idempotent consumers are mandatory, not optional

```js
// WRONG — check-then-insert is not atomic. Two concurrent deliveries of the
// same message (a real scenario under at-least-once delivery) can both pass
// the existence check before either has inserted, and both proceed to
// charge the customer twice.
async function handlePaymentEvent(event) {
  const existing = await db.payment.findUnique({ where: { eventId: event.id } });
  if (existing) return;   // "already processed" — but this check just raced
  await chargeCustomer(event);
  await db.payment.create({ data: { eventId: event.id, ...event } });
}

// RIGHT — push the uniqueness check into the database itself with a unique
// constraint on eventId, and let a duplicate insert fail loudly and safely
// instead of racing in application code.
async function handlePaymentEvent(event) {
  try {
    await db.payment.create({ data: { eventId: event.id, ...event } });
  } catch (err) {
    if (isUniqueConstraintViolation(err)) {
      return;   // we've seen this event before — safe no-op
    }
    throw err;
  }
  await chargeCustomer(event);
}
```

Or, in raw SQL terms, the same idea as `INSERT ... ON CONFLICT (event_id) DO
NOTHING` — let the database's unique index be the single source of truth
for "have we seen this before," because it's the only actor in this system
that can make that check atomic. Every consumer that has a side effect
(charging money, sending an email, decrementing inventory) needs this
pattern or an equivalent one (natural idempotency keys, conditional
writes) — "we'll just be careful not to double-process" is not a strategy
that survives a production incident.

## Dead-letter queues, and alarming on them

A job that fails every retry attempt shouldn't vanish — it should land
somewhere a human finds out about it.

```js
const emailQueue = new Queue('email', {
  connection,
  defaultJobOptions: {
    attempts: 5,
    backoff: { type: 'exponential', delay: 2000 },
  },
});

worker.on('failed', async (job, err) => {
  if (job.attemptsMade >= job.opts.attempts) {
    await deadLetterQueue.add('failed-email', { originalJob: job.data, error: err.message });
  }
});
```

For SQS, configure a redrive policy pointing at a real DLQ, not just a
`maxReceiveCount` with nowhere for the message to go. Either way, **a DLQ
with no alarm attached is just a message graveyard nobody visits** — wire
a CloudWatch alarm (or equivalent) on `ApproximateNumberOfMessagesVisible >
0` for the DLQ, or a periodic check on BullMQ's dead-letter queue depth, so
"a job is permanently failing" becomes a page, not a discovery three weeks
later when a customer complains.

## Graceful worker shutdown

A worker killed mid-job (deploy, autoscaling scale-down, spot instance
reclaim) either finishes cleanly or leaves a half-processed job that a
naive at-least-once redelivery will retry from scratch — which is fine
*only if the job is idempotent and safely retryable from the start*, which
is exactly the property the earlier sections buy you. But you still want a
clean shutdown path so in-flight jobs get a chance to finish rather than
being killed at an arbitrary instruction boundary:

```js
async function shutdown() {
  logger.info('shutting down worker');
  await worker.close();   // stops taking new jobs, waits for active jobs to finish (up to a timeout)
  await connection.quit();
  process.exit(0);
}

process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);
```

Pair this with an orchestrator-level grace period (`terminationGracePeriodSeconds`
in Kubernetes, for example) long enough for your longest normal job to
finish — if the grace period is shorter than a typical job, you're just
guaranteeing every deploy kills jobs mid-flight instead of preventing it.

## Worker as a separate process from the web server

```js
// WRONG — the worker runs inside the same process as the HTTP server.
// A CPU-heavy or long-running job blocks the event loop, and a slow job
// degrades request latency for completely unrelated web traffic. Scaling
// web replicas to handle more HTTP load also scales (and duplicates) your
// job concurrency, with no independent control over either.
app.listen(3000);
new Worker('email', processEmail, { connection });

// RIGHT — two separate entrypoints/processes, deployed and scaled
// independently
// server.js
app.listen(3000);

// worker.js — its own process, its own deployment, its own scaling policy
const worker = new Worker('email', processEmail, { connection, concurrency: 10 });
```

Running both in one process is a reasonable shortcut in early development,
but production services should split them: different resource profiles
(the web tier wants low-latency, high-concurrency I/O; a worker tier might
want fewer, CPU-heavier processes), different scaling triggers (queue depth
vs request rate), and a slow worker no longer able to starve the HTTP event
loop of the process actually serving users.

## Checklist

- [ ] Every job has `attempts` + a backoff strategy — never unlimited-instant-retry or no-retry
- [ ] `removeOnComplete`/`removeOnFail` (or equivalent) bounded so the queue backend doesn't grow unbounded
- [ ] `concurrency` tuned to the job's actual bottleneck (CPU vs I/O bound)
- [ ] No dual-write between the DB and the queue without an outbox (or equivalent transactional-enqueue pattern)
- [ ] Every consumer with a side effect is idempotent via a DB-level uniqueness constraint, not an application-level check-then-act
- [ ] A dead-letter queue exists for permanently-failed jobs, and it has an alarm attached
- [ ] Workers handle SIGTERM by stopping new work and draining in-flight jobs before exit
- [ ] Orchestrator grace period is longer than the typical job duration
- [ ] Worker processes are deployed and scaled separately from the web server, not co-located in the same process
