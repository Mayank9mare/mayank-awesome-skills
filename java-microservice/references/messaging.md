# Messaging in Java Microservices

## Delivery semantics: at-least-once is what you get

Every mainstream broker used from a Spring service — SQS, Kafka, RabbitMQ —
gives you **at-least-once** delivery in the default, sane configuration.
Exactly-once is either unavailable, or available only within narrow
transactional boundaries (Kafka's transactional producer/consumer, tied to a
single Kafka cluster) that most services don't actually operate inside.
**Assume every message can and eventually will be delivered more than once**
— on consumer crash after processing but before ack, on network partition
during ack, on redelivery after a visibility timeout, on rebalance. This is
not an edge case to defend against; it is the normal operating behavior of
the system.

The consequence: **idempotent consumers are mandatory, not optional.**
Processing the same message twice must produce the same end state as
processing it once.

### Idempotency keys and dedupe tables

```sql
CREATE TABLE processed_message (
    message_id   VARCHAR(100) PRIMARY KEY,
    processed_at TIMESTAMP NOT NULL DEFAULT now()
);
```

```java
@Transactional
public void handle(OrderMessage message) {
    // The INSERT itself is the concurrency-safe check — see below for why
    // a separate SELECT-then-INSERT is not safe.
    int inserted = jdbcClient.sql("""
            INSERT INTO processed_message (message_id) VALUES (:id)
            ON CONFLICT (message_id) DO NOTHING
            """)
            .param("id", message.messageId())
            .update();

    if (inserted == 0) {
        log.info("duplicate message {}, skipping", message.messageId());
        return;                      // already processed — this is success, not an error
    }

    applyOrder(message);             // same transaction as the dedupe insert
}
```

### "Check then insert" is not atomic

```java
// WRONG under concurrency:
if (!repo.existsById(message.messageId())) {   // (1) both consumers see "absent"
    repo.save(new ProcessedMessage(message.messageId()));  // (2) both insert
    applyOrder(message);                                    // (3) applied TWICE
}
```

Two consumers (or two redelivered copies of the same message processed
concurrently by different threads/instances) can both execute step (1) before
either reaches step (2) — there is a window between the read and the write
where the "does it exist" answer is stale. The fix is to make the **write**
itself the atomicity boundary: `INSERT ... ON CONFLICT DO NOTHING` (Postgres),
`INSERT IGNORE` (MySQL), or catch the unique-constraint violation from a plain
`INSERT` and treat it as "already handled." Never gate on a `SELECT` and then
act on it in a separate statement — that gap is exactly where duplicates slip
through under real concurrency.

## Spring Cloud AWS — SQS

> **Version note (Maven Central, 2026-08): `io.awspring.cloud:spring-cloud-aws-sqs` is
> at 4.1.0.** The 3.x → 4.x bump tracks the Spring Boot 3.x → 4.x move (Framework 7,
> Jakarta EE 11), so **match the major to your Boot major**: Boot 4.x → Spring Cloud AWS
> 4.x, Boot 3.x → 3.x. Mixing them produces classpath errors at startup, not at build
> time. The `@SqsListener` / `acknowledgementMode` shape documented below is the modern
> (3.x+) API and carries forward into 4.x; verify any 4.x-specific attribute additions
> against the release notes before relying on them.

```java
@Component
public class OrderMessageListener {

    @SqsListener(value = "${queues.orders}", acknowledgementMode = "ON_SUCCESS")
    public void handle(@NotBlank @Header(name = "X-Request-Id") String requestId,
                        @Valid @Payload OrderMessage message) {
        MDC.put("requestId", requestId);     // correlate logs across the call
        try {
            orderService.apply(message);
        } finally {
            MDC.remove("requestId");
        }
    }
}
```

Queue name comes from a property (`${queues.orders}`), **never hardcoded** —
the physical queue name differs across environments, and hardcoding it means
a config change requires a code change and redeploy instead of a property
override. `@Valid @Payload` runs bean validation on the deserialized message
body exactly like `@Valid @RequestBody` does on an HTTP request — a malformed
message fails validation instead of throwing a raw deserialization exception
three layers down, and (depending on your error handler) can be routed
straight to the DLQ instead of retried pointlessly. Pull correlation/trace IDs
out of `@Header` into MDC so log lines for a single message are correlatable
across services, the same as you'd propagate a request ID over HTTP.

### `acknowledgementMode`

| Value | Behavior | Redelivery implication |
|---|---|---|
| `ON_SUCCESS` (default) | Message is deleted from the queue only if the listener method returns without throwing | An exception (or the process dying) means the message is **not** deleted and becomes visible again after the visibility timeout — this is what you want for at-least-once processing |
| `ALWAYS` | Message is deleted regardless of whether the listener throws | Effectively at-most-once for that failure — only use this if failure means "not worth retrying," e.g. you've already routed unrecoverable errors somewhere else inside the method and don't want SQS-level retries on top |
| `MANUAL` | You control deletion explicitly via `Acknowledgement`/`Visibility` parameters injected into the method | Needed when the ack decision depends on more than "did an exception propagate" — e.g. partial batch success |

**current (Spring Cloud AWS 3.x):** `acknowledgementMode` is a String attribute
on `@SqsListener` as shown above.

**DEPRECATED (Spring Cloud AWS 2.x spelling):**

```java
// 2.x — replaced by acknowledgementMode in 3.x. If you see this in a codebase
// being upgraded, it's the signal the migration to 3.x's @SqsListener shape
// hasn't happened yet.
@SqsListener(value = "orders-queue", deletionPolicy = SqsMessageDeletionPolicy.ON_SUCCESS)
public void handle(OrderMessage message) { ... }
```

### Container factory, concurrency, and visibility timeout

```java
@Configuration
public class SqsConfig {

    @Bean
    SqsMessageListenerContainerFactory<Object> defaultSqsListenerContainerFactory(
            SqsAsyncClient sqsAsyncClient) {
        return SqsMessageListenerContainerFactory.builder()
                .configure(options -> options
                        .maxConcurrentMessages(10)   // upper bound on in-flight messages
                        .maxMessagesPerPoll(10)       // batch size per receive call
                        .pollTimeout(Duration.ofSeconds(10)))
                .sqsAsyncClient(sqsAsyncClient)
                .build();
    }
}
```

`maxConcurrentMessages` caps how many messages this listener processes at
once across the container; `maxMessagesPerPoll` caps how many come back in a
single SQS `ReceiveMessage` call (SQS's own hard ceiling is 10 per call).
Tune concurrency against downstream capacity (DB pool, dependent API rate
limits), not just "more is faster."

**Visibility timeout must comfortably exceed your worst-case processing
time.** SQS makes a received message invisible to other consumers for the
duration of the visibility timeout, expecting you to delete it before that
window closes. If processing legitimately takes longer than the timeout —
a slow downstream call, GC pause, thread starvation — the message becomes
visible again **while your original consumer is still working on it**. A
second consumer picks it up and starts processing the same message
concurrently with the first: not a hypothetical duplicate, an actively
running duplicate. Either raise the visibility timeout to comfortably exceed
p99 processing time, or extend it programmatically mid-processing for
long-running work, or break the work into smaller async steps so no single
receive needs a huge timeout.

## DLQ design

```json
{
  "deadLetterTargetArn": "arn:aws:sqs:region:account:myservice-orders-dlq",
  "maxReceiveCount": 5
}
```

`maxReceiveCount` is how many times a message can be received (i.e., fail to
be deleted) before SQS moves it to the configured DLQ instead of redelivering
it again. **A DLQ with no alarm on `ApproximateNumberOfMessagesVisible` is
just a silent trash can** — messages accumulate, nobody notices, and by the
time someone looks, days or weeks of failed orders/events are sitting there
unprocessed with no record of why anyone would have caught it earlier. Alarm
on the DLQ depth (even `> 0` for a queue that should normally be empty) and
route that alarm somewhere a human actually sees it.

Investigating a DLQ: **peek** messages (non-destructively, since receiving
doesn't delete) to inspect the payload and any diagnostic message
attributes your producer/consumer set (error class, stack trace excerpt,
original timestamp). Once the root cause is fixed, **redrive**: SQS's native
"start DLQ redrive" feature moves messages back to the source queue for
reprocessing, or move them by hand for smaller volumes.

**`maxReceiveCount = 1` means no retries at all** — the very first failure
sends the message straight to the DLQ, no second attempt. This is a common
misconfiguration: it looks like "one strike and you're out" protection but in
practice it means a single transient blip (a 500ms network hiccup, a brief DB
failover) permanently dead-letters a perfectly retriable message with zero
chance to self-heal. Set `maxReceiveCount` to something that tolerates
transient failure (3-5 is typical) and let the DLQ catch genuinely
unrecoverable messages, not every hiccup.

## Kafka (Spring Kafka)

```java
@KafkaListener(
        topics = "${topics.orders}",
        groupId = "${spring.application.name}",
        concurrency = "3")
public void handle(@Payload OrderMessage message,
                    @Header(KafkaHeaders.RECEIVED_KEY) String key,
                    Acknowledgment ack) {
    orderService.apply(message);
    ack.acknowledge();              // manual commit — only after successful processing
}
```

```yaml
spring:
  kafka:
    consumer:
      group-id: myservice
      enable-auto-commit: false          # manual AckMode below controls commits instead
      max-poll-records: 500
      properties:
        max.poll.interval.ms: 300000     # 5 min — see the rebalance trap below
    listener:
      ack-mode: manual                    # commit only when the listener calls ack.acknowledge()
    producer:
      acks: all                           # wait for all in-sync replicas to ack
      properties:
        enable.idempotence: true          # dedupes retried produce requests at the broker
```

### Consumer groups, partitions, and concurrency

All consumers sharing a `group-id` split the topic's partitions between them
— Kafka guarantees each partition is consumed by exactly one member of the
group at a time. This means **you cannot have more useful concurrent
consumers than partitions**: if a topic has 6 partitions and you run 10
consumer instances (or set `concurrency = 10` on one instance), 4 of them sit
completely idle. Partition count is your real concurrency ceiling — plan it
for the throughput and parallelism you need, since increasing partition count
later doesn't repartition existing data by key the way you'd want (existing
keys may land on different partitions than before, breaking ordering
assumptions for anything relying on it).

**Rebalancing**: whenever a consumer joins or leaves the group (deploy,
scale event, crash, or — critically — getting kicked for being slow, next
section), Kafka reassigns partitions across the remaining members, pausing
consumption for the group during the rebalance. Frequent rebalances (a
consumer that keeps getting evicted and rejoining) show up as a
throughput cliff, not a clean failure.

### `max.poll.interval.ms` vs slow processing — a classic outage

Kafka's consumer group protocol requires the client to call `poll()`
regularly to prove it's still alive; `max.poll.interval.ms` is the deadline.
**If processing the records from one `poll()` batch takes longer than this
interval, the broker considers the consumer dead and kicks it out of the
group** — even though the JVM is alive and actively working, just slow. The
partition gets reassigned to another member mid-processing, and when the
original consumer finally finishes and calls `poll()` again, it discovers
it's no longer a group member and has to rejoin (another rebalance). Worse,
if it then commits an offset for work it no longer "owns," you can get
duplicate processing across the old and new owner.

This is a genuinely common production outage shape: a downstream dependency
gets slow, batch processing time creeps past `max.poll.interval.ms`, the
consumer gets evicted, rebalances thrash, and throughput collapses exactly
when you most needed steady processing. Mitigate by keeping
`max.poll.records` small enough that a slow-but-not-broken batch still
finishes within the interval, moving genuinely slow work off the poll thread
(hand off to an async executor and commit offsets afterward, carefully — see
ordering caveats), and setting `max.poll.interval.ms` generously above your
measured p99 batch processing time, not the median.

### Manual commit and at-least-once

`enable-auto-commit: false` + `AckMode.MANUAL` (or `MANUAL_IMMEDIATE`) means
the offset only advances when your code explicitly acknowledges. If the
process crashes after processing but before acknowledging, the same record is
redelivered on restart — same at-least-once guarantee as SQS, same
requirement for idempotent handling. Auto-commit is the wrong default for
anything where losing or duplicating a message matters, because it commits
on a timer independent of whether your listener actually finished
successfully.

### Producer: idempotence + `acks=all`

`enable.idempotence=true` gives you exactly-once **per producer session, per
partition** at the broker level — retried produce requests (from network
blips) don't create duplicate records on the broker side. `acks=all` (paired
with a sane `min.insync.replicas` on the topic) means the produce call
doesn't return success until all in-sync replicas have the record, so a
broker failure right after doesn't lose it. Neither of these makes your
*consumer* exactly-once — that's still governed by consumer-side idempotent
handling — but skipping them on the producer side reintroduces
broker-level duplication and data-loss risk you don't need.

### Ordering: per-partition only

Kafka guarantees order **within a partition**, not across the topic. Records
with the same key land on the same partition (via the default partitioner)
and are delivered in the order they were produced; records with different
keys have no ordering guarantee relative to each other. If you need "all
events for order #123 processed in order," key by order ID — but understand
that's the *only* ordering guarantee you get, and increasing partition count
later can change which partition a key maps to.

## Retries & backoff

```java
@Bean
DefaultErrorHandler errorHandler() {
    var backoff = new ExponentialBackOffWithMaxRetries(5);
    backoff.setInitialInterval(500);
    backoff.setMultiplier(2.0);
    backoff.setMaxInterval(30_000);
    // Spring's backoff doesn't jitter by default — for genuine production use,
    // wrap or configure jitter (see below) to avoid synchronized retry storms.

    var handler = new DefaultErrorHandler(backoff);
    handler.addNotRetryableExceptions(ValidationException.class);  // straight to failure path
    return handler;
}
```

```java
@RetryableTopic(
        attempts = "4",
        backoff = @Backoff(delay = 1000, multiplier = 2.0, maxDelay = 30000),
        include = TransientDownstreamException.class,     // retry only these
        exclude = ValidationException.class,               // never retry these
        dltTopicSuffix = "-dlt")
@KafkaListener(topics = "${topics.orders}")
public void handle(OrderMessage message) { ... }
```

For SQS, there's no separate retry framework — the visibility timeout **is**
the retry mechanism. A failed message (not deleted) simply becomes visible
again after the timeout and gets redelivered; `maxReceiveCount` is your
attempt limit. If you want backoff *between* SQS retry attempts beyond what
the fixed visibility timeout gives you, you need to manage it yourself (e.g.
a per-message attempt counter in a message attribute, changing visibility
programmatically based on it).

**Exponential backoff with jitter is mandatory**, not a nice-to-have. Fixed-
interval retries (or backoff without randomization) synchronize: if a
downstream outage causes 1,000 consumers to fail simultaneously, they all
retry at exactly the same fixed delay, hit the recovering downstream
simultaneously again, fail again, and repeat in lockstep — a self-inflicted
thundering herd that can prevent the downstream from ever fully recovering.
Jitter (randomizing the actual delay within a range around the computed
backoff) spreads retries out in time so they don't all land on the same
millisecond.

**Distinguish retryable from non-retryable failures and route accordingly.**
A timeout, connection refused, or 5xx from a downstream service is
transient — retrying is the right move. A validation failure, a malformed
payload, or a 4xx from a downstream API is not going to succeed on attempt 6
just because it failed on attempt 1 — retrying it burns through your retry
budget and delays the message's arrival at the DLQ where a human can actually
look at it. Explicitly classify exceptions (as in `addNotRetryableExceptions`
/ `exclude` above) so non-retryable failures short-circuit straight to the
dead-letter path instead of exhausting retries pointlessly.

## Ordering & concurrency trade-off

| Mechanism | Ordering guarantee | Cost |
|---|---|---|
| SQS FIFO queue + `MessageGroupId` | Strict order within a message group | Only one in-flight message per group at a time — parallelism is bounded by the number of distinct groups |
| SQS standard queue | Best-effort, not guaranteed | Full parallelism, no ordering |
| Kafka partition key | Strict order within a partition | Parallelism bounded by partition count; can't exceed partition count with useful consumers |

Say it plainly: **ordering and parallelism are in tension.** The stronger the
ordering guarantee you need for a given key, the less you can parallelize
work for that key — a single `MessageGroupId`/partition is processed by
exactly one consumer at a time by design, because processing it out of order
on two consumers simultaneously would violate the guarantee you asked for.
Design your keying (message group ID, partition key) around the actual unit
that needs order — usually an entity ID (order, user, account) — so
unrelated entities parallelize freely while related events for the same
entity stay ordered.

## Outbox pattern

Publishing directly to a broker from inside a database transaction is
unsafe in both directions:

- **Publish, then the transaction rolls back**: a consumer can act on an
  event for a row that was never actually committed — it doesn't exist as
  far as the database is concerned, but a downstream service has already
  reacted to it.
- **Transaction commits, but the publish call fails or the process crashes
  between commit and publish**: the database change is real, but no event
  ever went out — nothing downstream ever finds out.

Either failure mode is a correctness bug, not a rare corner case — it's what
happens on the ordinary path of "the broker call and the DB commit are two
separate operations with no shared atomicity."

The fix: write the event into an **outbox table**, in the *same* database
transaction as the business change, then let a separate process publish it
after the transaction has durably committed.

```sql
CREATE TABLE outbox_event (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    aggregate_id VARCHAR(100) NOT NULL,     -- e.g. order id — for partition/group keying
    event_type   VARCHAR(100) NOT NULL,     -- e.g. "OrderPlaced"
    payload      JSONB NOT NULL,
    created_at   TIMESTAMP NOT NULL DEFAULT now(),
    published_at TIMESTAMP                  -- NULL until the poller publishes it
);
```

```java
@Transactional(rollbackFor = Exception.class)
public Order placeOrder(NewOrderRequest request) {
    Order order = repo.save(new Order(request));

    // Same transaction as the order write — either both commit or neither does.
    outboxRepo.save(OutboxEvent.of(order.getId(), "OrderPlaced", toPayload(order)));

    return order;
}
```

A separate poller (a scheduled job, or a CDC tool like Debezium reading the
outbox table's write-ahead log) picks up rows where `published_at IS NULL`,
publishes them to the broker, and marks them published — this publish step
is itself at-least-once (the poller can crash after publishing but before
marking published), which is exactly why the *consumer* idempotency from the
first section of this document is still required even with an outbox in
place. The outbox guarantees the event is never lost relative to the DB
state; it does not by itself guarantee exactly-once delivery to the consumer.

## Testing

**Testcontainers for the real broker**, not an in-memory fake:

```java
@Testcontainers
@SpringBootTest
class OrderListenerTest {

    @Container
    static LocalStackContainer localstack = new LocalStackContainer(
                DockerImageName.parse("localstack/localstack:3"))
            .withServices(LocalStackContainer.Service.SQS);

    @DynamicPropertySource
    static void awsProperties(DynamicPropertyRegistry registry) {
        registry.add("spring.cloud.aws.sqs.endpoint", localstack::getEndpoint);
        registry.add("spring.cloud.aws.credentials.access-key", () -> "test");
        registry.add("spring.cloud.aws.credentials.secret-key", () -> "test");
        registry.add("spring.cloud.aws.region.static", () -> "us-east-1");
    }
}
```

```java
@Testcontainers
@SpringBootTest
class OrderKafkaListenerTest {

    @Container
    static KafkaContainer kafka = new KafkaContainer(DockerImageName.parse("apache/kafka:3.8.0"));

    @DynamicPropertySource
    static void kafkaProperties(DynamicPropertyRegistry registry) {
        registry.add("spring.kafka.bootstrap-servers", kafka::getBootstrapServers);
    }
}
```

**Never `Thread.sleep()` to wait for async processing** — it's either too
short (flaky failures under load) or too long (a slow test suite that's
still fundamentally guessing). Use Awaitility to poll for the actual
condition:

```java
@Test
void processesOrderMessage() {
    sqsTemplate.send("orders-queue", new OrderMessage(orderId, ...));

    await().atMost(Duration.ofSeconds(10))
           .pollInterval(Duration.ofMillis(200))
           .untilAsserted(() -> {
               Order order = repo.findById(orderId).orElseThrow();
               assertThat(order.getStatus()).isEqualTo(OrderStatus.PLACED);
           });
}
```

`await().untilAsserted(...)` retries the assertion itself until it passes or
the timeout elapses, so the test finishes as soon as the condition is true
instead of always waiting the full fixed sleep duration — and it fails with
the real assertion error, not a generic "still absent after N seconds"
timeout message.

## Checklist

- [ ] Every message consumer is idempotent — reprocessing the same message produces the same end state
- [ ] Deduplication uses an atomic `INSERT ... ON CONFLICT` / unique constraint, never a separate SELECT-then-INSERT
- [ ] SQS queue names come from properties, never hardcoded
- [ ] `@SqsListener` uses `acknowledgementMode` (3.x), not the deprecated 2.x `deletionPolicy`/`SqsMessageDeletionPolicy`
- [ ] `@Valid @Payload` validates message bodies the same way request bodies are validated
- [ ] Correlation/request IDs pulled from `@Header` into MDC for log correlation
- [ ] SQS visibility timeout comfortably exceeds worst-case (p99, not median) processing time
- [ ] DLQ has an alarm on message count — not silently accumulating
- [ ] `maxReceiveCount` is high enough to tolerate transient failures (not `1`)
- [ ] Kafka `max.poll.interval.ms` is set generously above measured p99 batch processing time
- [ ] Kafka consumer concurrency doesn't exceed partition count
- [ ] Kafka producer has `enable.idempotence=true` and `acks=all`
- [ ] Manual ack/commit used for both SQS and Kafka where at-least-once matters — no reliance on timer-based auto-commit
- [ ] Retries use exponential backoff with jitter, not fixed intervals
- [ ] Non-retryable exceptions (validation, 4xx) are explicitly excluded from retry and routed to DLQ/DLT
- [ ] Ordering requirements are scoped to the smallest key that needs it (message group ID / partition key), not applied globally
- [ ] Any publish tied to a DB write goes through an outbox table in the same transaction, not a direct broker call inside the transaction
- [ ] Tests use Testcontainers (LocalStack for SQS, a real Kafka container) — no in-memory broker fakes
- [ ] Async test assertions use Awaitility's `untilAsserted`, never `Thread.sleep`
