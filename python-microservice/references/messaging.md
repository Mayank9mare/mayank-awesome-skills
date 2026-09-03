# Async Messaging and Background Work

## Choosing

| Library | Async-native | Broker | Verdict |
|---|---|---|---|
| **Celery** | No (thread-pool workers by default) | Redis, RabbitMQ, SQS | Most mature, most features (Beat, canvas/chaining, result backends). Heavy, and its process model fights native `async def` tasks. |
| **arq** | Yes | Redis only | Light, async-native, minimal config. Good default for a Redis-only stack that doesn't need Celery's feature surface. |
| **Dramatiq** | No (sync workers) | Redis, RabbitMQ | Simpler mental model than Celery — fewer knobs, fewer surprises. No Beat equivalent built in. |
| **TaskIQ** | Yes | Pluggable (Redis, RabbitMQ, Kafka, NATS) | Async-native like arq but broker-agnostic; younger ecosystem. |
| **APScheduler** | Yes (asyncio executor) | **None — in-process, not a distributed queue** | For "run this every 5 minutes inside this one process." Does not survive a restart mid-schedule, does not coordinate across replicas — running it on N replicas fires the job N times. |
| **RQ** | No | Redis only | Simple, Celery-lite. Fewer features than Celery, easier to reason about. |
| **Temporal** | Yes (SDK) | Its own server | Durable workflow orchestration — models multi-step, long-running business processes with automatic state persistence and replay. Different problem than "run this job in the background"; consider it when a task queue's retry/state model stops being enough. |

Plus raw consumers where the "queue" is a managed service you're integrating
with directly rather than picking a Python-side task library: **SQS
consumers** and **Kafka consumers** (§5, §6).

Default guidance: if you're already on Redis and want the smallest footprint
for async tasks, start with **arq**. If you need Celery's ecosystem (Beat
schedules, chaining, existing operational familiarity), use Celery but budget
time for its idempotency and transaction pitfalls (§3). Reach for Temporal
only when the workflow itself — not just an individual task — has meaningful
multi-step state that must survive crashes and restarts.

## At-least-once delivery means idempotent consumers are mandatory

Every queueing system in this document delivers **at least once**, not exactly
once — a consumer that dies after processing a message but before
acknowledging it *will* see that message again. This is not an edge case to
handle defensively; it is the normal operating contract. A consumer that isn't
idempotent will eventually double-process a message, and "eventually" tends to
arrive during a deploy, an autoscale event, or a network blip — the exact
moments you can least afford a duplicate side effect.

The standard fix is an idempotency key plus a dedupe table with a unique
constraint:

```python
class ProcessedMessage(Base):
    __tablename__ = "processed_messages"
    idempotency_key: Mapped[str] = mapped_column(primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(server_default=func.now())
```

**Check-then-insert is not atomic**, for the same reason it wasn't atomic for
the upsert case in `persistence.md` §6: two workers can both `SELECT` and both
see "not present," both proceed, and one fails or — worse — both succeed and
you've double-processed anyway. Let the database's unique constraint be the
actual guard:

```python
from sqlalchemy.exc import IntegrityError

async def process_once(db: AsyncSession, idempotency_key: str, payload: dict) -> bool:
    try:
        async with db.begin():
            db.add(ProcessedMessage(idempotency_key=idempotency_key))
            await do_the_actual_work(db, payload)
        return True                      # first time seeing this key
    except IntegrityError:
        # unique constraint violation — another worker (or a redelivery)
        # already claimed this key. Not an error, just a no-op.
        return False
```

The `INSERT` and the constraint check happen as one atomic database operation;
there's no window for a second worker to slip through, unlike a
`SELECT`-then-`INSERT` pair.

## Celery

**Broker**: Redis (simpler ops, no ack persistence guarantees as strong as a
real message broker) vs RabbitMQ (proper AMQP semantics, more operational
weight) vs SQS (managed, no broker to run, but slower and with SQS's own
quirks — see §5). Pick Redis for low-stakes tasks where losing a queued task on
a broker crash is tolerable; RabbitMQ or SQS when it isn't.

```python
from celery import Celery

app = Celery("myservice", broker="redis://localhost:6379/1")

app.conf.update(
    task_acks_late=True,          # ack AFTER the task finishes, not on receipt
    worker_prefetch_multiplier=1, # see below — default of 4 starves long tasks
    task_time_limit=300,          # hard kill after 5 min
    task_soft_time_limit=270,     # SoftTimeLimitExceeded raised first — task can clean up
    result_backend=None,          # see below — you often don't need one
)


@app.task(
    bind=True,
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,     # exponential backoff between retries
    retry_jitter=True,      # jitter — mandatory, see messaging.md §7
    max_retries=5,
)
def send_receipt_email(self, order_id: int) -> None:
    ...
```

**`acks_late=True`**: the broker only marks the task done once the worker
finishes it, not the instant the worker picks it up. This is what makes
retries meaningful after a crash — if the worker process dies mid-task, the
broker still has it as unacked and redelivers it to another worker. The direct
consequence: **the task will be redelivered and re-run after any worker
crash mid-task, so it must be idempotent** (§2) or the redelivery duplicates
whatever side effect it already performed once.

**`prefetch_multiplier`**: how many tasks a worker process pulls off the queue
ahead of finishing its current one. The default is 4 — fine for many small,
fast tasks (keeps the worker fed), but it means a worker holding 4 long tasks
prefetched will sit on 3 of them, unstarted, doing nothing, while a *different*
idle worker could have picked them up — the classic "one slow task starves the
others" pattern in a queue with mixed task durations. For queues with
long-running or highly variable-duration tasks, set `prefetch_multiplier=1` so
a worker only holds what it's actively running.

**Result backends**: storing a task's return value needs a backend (Redis,
DB, RPC). If nothing ever calls `.get()` on the `AsyncResult`, you're paying
write cost (and often unbounded result-storage growth) for a result nobody
reads. Skip the backend (`result_backend=None` or simply don't configure one)
for fire-and-forget tasks — most background jobs.

**`task_time_limit`/`soft_time_limit`**: a hard limit kills the worker process
outright (`SIGKILL`); a soft limit raises `SoftTimeLimitExceeded` inside the
task first, giving it a chance to clean up before the hard limit lands. Set
both — a runaway task should never be able to hang a worker forever.

**Beat** runs scheduled tasks (cron-like) from a single dedicated process —
run exactly one Beat process per deployment (it's not designed for multiple
schedulers racing to fire the same job), separate from the worker pool that
actually executes tasks.

### The single most important Celery lesson: a task is not a transaction

```python
# WRONG — delay() fires inside an open transaction. Two ways this breaks:
#
# 1. A worker (possibly on another host) can pick up the task and query the
#    order BEFORE this transaction commits — the row doesn't exist yet from
#    the worker's point of view, or exists in a half-written state.
# 2. Something later in this same transaction raises, the transaction rolls
#    back, but the task already fired — now you're sending a receipt email
#    for an order that, as far as the database is concerned, was never created.
async def create_order(db: AsyncSession, data: OrderIn) -> Order:
    async with db.begin():
        order = Order(**data.model_dump())
        db.add(order)
        await db.flush()                      # order.id now exists locally...
        send_receipt_email.delay(order.id)     # ...but NOT necessarily committed yet
    return order


# RIGHT — enqueue only after the transaction has actually committed.
async def create_order(db: AsyncSession, data: OrderIn) -> Order:
    async with db.begin():
        order = Order(**data.model_dump())
        db.add(order)
        await db.flush()
    # transaction committed by the time `async with` exits successfully —
    # now it's safe for a worker to see this row
    send_receipt_email.delay(order.id)
    return order
```

Django gives you `transaction.on_commit(lambda: send_receipt_email.delay(order.id))`
to register the enqueue as a post-commit hook declaratively, inside the
transactional code, without having to restructure control flow around
`async with`. Outside Django, get the same guarantee either by moving the
`.delay()` call to after the `async with db.begin()` block exits (as above),
or — for stronger guarantees when the enqueue itself must not be lost even if
the process crashes between commit and publish — the **outbox pattern** (§8):
write an "outbox" row in the *same* transaction as the order, and a separate
relay process reads committed outbox rows and publishes them.

## arq / Dramatiq / TaskIQ

**arq** — async-native, Redis only, minimal ceremony:

```python
from arq import create_pool
from arq.connections import RedisSettings

async def send_receipt(ctx, order_id: int) -> None:
    ...   # ctx carries the redis pool, job metadata

class WorkerSettings:
    functions = [send_receipt]
    redis_settings = RedisSettings.from_dsn("redis://localhost:6379/1")
    max_jobs = 10
    job_timeout = 300

# enqueue from the app
redis = await create_pool(WorkerSettings.redis_settings)
await redis.enqueue_job("send_receipt", order.id)
```

Beats Celery when: your stack is already async end-to-end (FastAPI + async
SQLAlchemy) and you don't want a thread-pool-based worker model running
alongside an async web tier, or you don't need Celery's broader broker/feature
surface.

**Dramatiq** — deliberately smaller surface than Celery, sync workers:

```python
import dramatiq
from dramatiq.brokers.redis import RedisBroker

dramatiq.set_broker(RedisBroker(url="redis://localhost:6379/1"))

@dramatiq.actor(max_retries=5, min_backoff=1000, max_backoff=60000)
def send_receipt_email(order_id: int) -> None:
    ...
```

Beats Celery when: you want Celery-like task semantics with far fewer
configuration knobs and are willing to give up Beat-style scheduling and some
of Celery's ecosystem.

**TaskIQ** — async-native like arq, but broker-pluggable rather than
Redis-only:

```python
from taskiq_redis import ListQueueBroker

broker = ListQueueBroker(url="redis://localhost:6379/1")

@broker.task
async def send_receipt_email(order_id: int) -> None:
    ...

await send_receipt_email.kiq(order.id)   # "kick" the task
```

Beats arq when: you want async-native tasks but need a broker other than
Redis (RabbitMQ, Kafka, NATS) without switching your whole task-library
paradigm.

## SQS consumer

```python
import aioboto3   # boto3 itself is sync — see below

async def consume(queue_url: str) -> None:
    session = aioboto3.Session()
    async with session.client("sqs") as sqs:
        while True:
            resp = await sqs.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=20,          # long polling — cuts empty-poll cost and latency
                VisibilityTimeout=60,        # must exceed your actual processing time
                AttributeNames=["ApproximateReceiveCount"],
            )
            messages = resp.get("Messages", [])
            if not messages:
                continue

            for msg in messages:
                await handle_message(msg)   # idempotent — see §2

            # batch delete only what succeeded — never delete on receipt
            await sqs.delete_message_batch(
                QueueUrl=queue_url,
                Entries=[{"Id": m["MessageId"], "ReceiptHandle": m["ReceiptHandle"]} for m in messages],
            )
```

**Long polling** (`WaitTimeSeconds=20`, the max) means `receive_message` blocks
up to 20s waiting for a message instead of returning empty immediately — far
fewer empty API calls than short polling, at essentially no added latency for
a busy queue.

**Visibility timeout vs processing time**: SQS hides a received message from
other consumers for `VisibilityTimeout` seconds, expecting you to delete it
once done. **If your processing takes longer than the visibility timeout, SQS
makes the message visible again while you're still working on it** — a second
consumer picks it up and starts processing the same message concurrently with
the first. Either set the timeout comfortably above your p99 processing time,
or call `change_message_visibility` to extend it for a specific message when
you know a job is going to run long.

**DLQ with `maxReceiveCount`**: configure a redrive policy so that after N
failed receives (delivered but never deleted — meaning processing kept
failing) SQS automatically moves the message to a dead-letter queue instead of
retrying it forever. Without a DLQ, a permanently-failing message (bad
payload, a bug) gets redelivered indefinitely, consuming worker capacity on
every poll cycle for a message that will never succeed.

**boto3 is sync.** Calling it directly inside `async def` blocks the event
loop for the duration of the network call — every other coroutine on that
loop stalls. Use `aioboto3`/`aiobotocore` (a real async client, shown above)
or, if you're stuck with plain `boto3`, wrap each call in
`await asyncio.to_thread(sqs.receive_message, ...)` to push it off the event
loop onto a thread.

## Kafka

`aiokafka` (async-native) or `confluent-kafka` (librdkafka bindings, sync API —
wrap in `asyncio.to_thread` for an async service, but often faster and more
production-hardened).

```python
from aiokafka import AIOKafkaConsumer

async def consume() -> None:
    consumer = AIOKafkaConsumer(
        "orders.created",
        bootstrap_servers="localhost:9092",
        group_id="myservice-order-processor",
        enable_auto_commit=False,          # manual commit — see below
        max_poll_interval_ms=300_000,      # see below
    )
    await consumer.start()
    try:
        async for msg in consumer:
            await handle_message(msg.value)   # idempotent — see §2
            await consumer.commit()            # only after successful processing
    finally:
        await consumer.stop()
```

**Consumer groups** distribute a topic's partitions across the group's
consumers — each partition is read by exactly one consumer in the group at a
time. This is also the ceiling on your parallelism: a topic with 6 partitions
can be usefully consumed by at most 6 concurrent consumers in one group; a 7th
sits idle.

**Manual commit for at-least-once**: auto-commit acknowledges offsets on a
timer regardless of whether you actually finished processing — a crash after
an auto-commit but before you're done with that batch means those messages
are gone from your perspective, never to be redelivered (that's at-most-once,
usually not what you want). Committing manually, only after successful
processing, gives you the standard at-least-once guarantee: a crash before
commit means the message is redelivered.

**`max_poll_interval_ms` vs slow processing**: Kafka's group coordinator
expects a consumer to call `poll()` at least this often to prove it's alive.
If your per-message (or per-batch) processing takes longer than
`max_poll_interval_ms`, the coordinator ejects you from the group and
reassigns your partitions to someone else — while you're still processing,
mid-batch. This is a classic, hard-to-diagnose outage: processing looks
"stuck," but the real cause is that it was simply slower than the poll
interval, and the fix is either raising the interval or reducing per-poll
batch size so each processing cycle finishes faster.

**Ordering is per-partition only.** Kafka guarantees message order within a
single partition, not across the topic. If two messages must be processed in
order relative to each other, they must share a partition key (commonly the
entity ID they concern) — otherwise Kafka is free to deliver them to different
consumers in any relative order.

## Retries and dead-letter queues

**Exponential backoff with jitter is mandatory**, not a nice-to-have. Without
jitter, every consumer that failed at the same moment (a shared dependency
blip) retries at the same moment again, and again — a synchronized retry storm
that can prevent the dependency from ever recovering, because every retry wave
arrives as a spike instead of a spread.

```python
import random

def backoff_seconds(attempt: int, base: float = 1.0, cap: float = 60.0) -> float:
    exp = min(cap, base * (2 ** attempt))
    return random.uniform(0, exp)     # full jitter — spreads retries across the window, not just adds noise
```

**Distinguish retryable from non-retryable failures.** A timeout, a 503, a
connection reset — worth retrying, the dependency might recover. A validation
error, a 400, a malformed payload — retrying changes nothing; the same input
produces the same failure every time. Sending non-retryable failures straight
to the DLQ (instead of burning through `max_retries` first) gets them to a
human faster and stops them from occupying retry slots that a genuinely
transient failure could use.

**A DLQ with no alarm is a message graveyard nobody visits.** Messages landing
in a dead-letter queue represent work that silently didn't happen — alert on
DLQ depth (even "> 0" is a reasonable starting alarm for a low-volume queue),
and have an actual runbook for draining it, not just a place messages go to be
forgotten.

## Outbox pattern

The general fix for "I need to atomically (a) change my database and (b)
notify something outside the database" — since a DB transaction and a message
broker publish can never be one atomic operation across two separate systems.

```python
class Outbox(Base):
    __tablename__ = "outbox"
    id: Mapped[int] = mapped_column(primary_key=True)
    topic: Mapped[str] = mapped_column()
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(default=None)
```

```python
async def create_order(db: AsyncSession, data: OrderIn) -> Order:
    async with db.begin():
        order = Order(**data.model_dump())
        db.add(order)
        await db.flush()
        # same transaction, same atomicity as the order row itself —
        # this INSERT either commits with the order or rolls back with it
        db.add(Outbox(topic="orders.created", payload={"order_id": order.id}))
    return order
```

A separate relay process (a polling loop, or `LISTEN`/`NOTIFY` on Postgres,
or a CDC tool like Debezium reading the WAL) reads unpublished outbox rows and
publishes them to the real broker, marking them published only after a
confirmed send. The order row and the "please tell everyone about this order"
row are created atomically together — there is no window where the order
exists but the notification was lost, or the notification fired but the order
doesn't exist. The relay itself must retry publishing idempotently (the
message might get published, the mark-as-published update might fail, and the
relay retries — meaning the broker side must also assume at-least-once, same
as everything else in this document).

## Worker deployment

Run workers as a **separate process/deployment from the web app** — different
scaling profile (CPU/memory-bound task processing vs request-latency-bound web
serving), different health checks, different failure blast radius. A worker
OOM should not take down the API.

**Graceful shutdown**: on a deploy or scale-down signal, stop *accepting* new
tasks but let the current task finish before the process exits. Killing a
worker mid-task (SIGKILL, or a shutdown timeout too short for the longest
task) relies entirely on redelivery-and-idempotency (§2) to make the work
happen eventually — better, but a graceful drain avoids the redelivery in the
first place.

**Don't put real background work in FastAPI's `BackgroundTasks`.** It runs
in-process, after the response is sent, in the same worker that served the
request — it has no retry, no persistence, and it dies with the web worker.
Fine for "fire off a low-stakes analytics ping I don't care about losing."
Wrong for anything that must actually happen: emailing a receipt, charging a
card, updating a downstream system. Those belong in a real task queue with
acknowledgment and redelivery.

## Testing

```python
# Celery
app.conf.task_always_eager = True    # tasks run synchronously, in-process, no broker
```

`task_always_eager` (and arq's/Dramatiq's equivalents) is convenient for unit
tests of task *logic*, but it is not a substitute for integration testing the
real path: it doesn't serialize/deserialize the task arguments (so a task that
only breaks because an argument doesn't survive JSON/pickle round-tripping
passes in eager mode and fails in production), and it never exercises the
actual broker (connection handling, retry/redelivery behavior, `acks_late`
semantics).

For that, use **testcontainers** to spin up a real Redis/RabbitMQ/Kafka
instance for integration tests — slower than eager mode, but it catches the
class of bug eager mode is structurally unable to see.

## Checklist

- [ ] Every consumer/task is idempotent — dedupe via unique constraint, not check-then-insert
- [ ] Celery: `acks_late=True`, `prefetch_multiplier` sized for task duration mix
- [ ] Celery: result backend only configured for tasks whose result someone reads
- [ ] Task enqueue happens after the enclosing DB transaction commits — never inside it
- [ ] Outbox pattern used where the enqueue itself must not be lost on a crash
- [ ] SQS: long polling enabled, visibility timeout exceeds real processing time
- [ ] SQS: DLQ configured with `maxReceiveCount`; boto3 calls off the event loop
- [ ] Kafka: manual commit after successful processing; `max_poll_interval_ms` sized for real batch duration
- [ ] Retries: exponential backoff with jitter, capped attempts
- [ ] Non-retryable failures routed straight to DLQ, not retried to exhaustion
- [ ] DLQ has an alarm and an actual runbook
- [ ] Workers deployed and scaled separately from the web app; graceful shutdown drains in-flight work
- [ ] No durable business logic relies on `BackgroundTasks`
- [ ] Tests cover both eager/in-process task logic and a real broker via testcontainers
