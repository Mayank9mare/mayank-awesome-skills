# Race Conditions Playbook

Race bugs do not fail loudly; they fail rarely. A race scenario that passes once has
told you nothing. This file is how to construct one so that a pass means something and a
failure is reproducible.

Three parts: **make the interleaving happen**, **assert something a race would break**,
**run it enough times to believe the answer**.

---

## 1. Find the races before testing them

Enumerate the concurrency surface from the feature's design, not from the code you
happen to have read:

| Question | The race it implies |
|---|---|
| What can two users do to the same entity at once? | Lost update / conflicting mutation |
| What can the system do to an entity while a user acts on it? | Timer vs. user action |
| Where does the feature read, decide, then write? | Check-then-act (TOCTOU) |
| Where can a callback arrive? | Callback-before-wait (early signal) |
| Which events for one entity are published from different producers? | Out-of-order delivery |
| What runs on more than one instance? | Duplicate consumer / double-processing |
| Where is there a lock? | Lock expiry mid-work; lock not covering the whole critical section |
| What is created "if not exists"? | Concurrent create → duplicate rows |
| What is a scheduled job? | Job overlapping its own previous run |

Every "yes" is a scenario. Write it down even if you cannot build it yet — an unbuilt
race scenario in the task file is a known gap; an unwritten one is a surprise in prod.

---

## 2. Construct the interleaving

### Simultaneous burst — the workhorse

Fire N requests whose windows genuinely overlap. Backgrounded curls started in a loop do
*not* overlap reliably — the process start cost dominates. Prepare everything first,
then release all of them on one signal:

```bash
# Barrier-released burst: N requests that actually start together
BURST_DIR=$(mktemp -d); GATE="$BURST_DIR/gate"
N={{n}}
for i in $(seq 1 "$N"); do
  (
    # everything expensive happens BEFORE the barrier
    payload=$(printf '{"ref":"%s","seq":%d}' "$RUN_ID" "$i")
    while [ ! -f "$GATE" ]; do :; done          # spin, not sleep — sub-ms release
    curl -sS -o "$BURST_DIR/out.$i" -w '%{http_code} %{time_starttransfer}\n' \
      -X POST "$URL" -H 'Content-Type: application/json' \
      -H "Idempotency-Key: $RUN_ID" -d "$payload" > "$BURST_DIR/code.$i" 2>&1
  ) &
done
sleep 0.3                                        # let all subshells reach the barrier
touch "$GATE"                                    # release
wait
echo "--- status codes ---"; cat "$BURST_DIR"/code.*
echo "--- bodies ---";       for f in "$BURST_DIR"/out.*; do head -c 300 "$f"; echo; done
```

Report the *distribution* of responses, not just whether any succeeded. `10× 201` on a
create that should be idempotent is the bug, even though every request "passed".

For heavier concurrency, prefer a load tool over shell:
```bash
# hey / vegeta / k6 — same idea, better timing resolution
hey -n 50 -c 50 -m POST -H "Idempotency-Key: $RUN_ID" -T application/json \
  -d '{{json}}' "$URL"
```

### Conflicting-pair race

Two *different* operations on one entity, released together. The most productive race in
practice — cancel vs. capture, approve vs. reject, delete vs. update.

```bash
GATE=$(mktemp -u)
( while [ ! -f "$GATE" ]; do :; done; curl -sS -w '\nA %{http_code}\n' -X POST "$URL/cancel"  -H "$AUTH" ) &
( while [ ! -f "$GATE" ]; do :; done; curl -sS -w '\nB %{http_code}\n' -X POST "$URL/capture" -H "$AUTH" ) &
sleep 0.3; touch "$GATE"; wait
```
Expected: exactly one succeeds, the other gets a clean conflict (409/412). Two successes
is a lost update. Two failures is a deadlock. Both are findings.

### Duplicate delivery

Publish the same event twice with the same payload. On buses with dedup, you must defeat
it deliberately — that is the point of the test, since the real world will deliver twice
after a broker restart:

```bash
# SQS FIFO: vary the dedup id, keep the body identical
for i in 1 2; do
  aws sqs send-message --queue-url "$Q" --region "$R" --message-body "$BODY" \
    --message-group-id "$RUN_ID" --message-deduplication-id "$RUN_ID-dup-$i"
done
# Kafka: same key, published twice — consumer must dedup, not the broker
# Pub/Sub: publish twice; message ids differ, payload identical
```

### Out-of-order delivery

Publish the *later* event first. Only meaningful where ordering is not guaranteed —
different partitions, different producers, or a retry that overtook the original.

```bash
publish "$EVENT_COMPLETED"      # arrives first
sleep 1
publish "$EVENT_STARTED"        # the one that logically came first
```
Assert: the entity does not regress to an earlier state, and the late-arriving earlier
event is ignored rather than applied.

### Early callback (callback before the wait exists)

The classic workflow race: the partner responds faster than the workflow can register
its wait state.

```bash
start_workflow &                 # do not wait for it
sleep 0.05                       # tune down until the callback wins
deliver_callback
wait
```
Assert: the callback is buffered or replayed, not dropped. A dropped early callback
shows up as a workflow that waits forever — check for a stuck RUNNING execution.

### Duplicate consumer / visibility-timeout expiry

Simulate two workers taking the same message by receiving it without acking and letting
the visibility timeout lapse:

```bash
# SQS: receive with a short visibility timeout, do not delete
aws sqs receive-message --queue-url "$Q" --region "$R" --visibility-timeout 1 \
  --query 'Messages[0].{h:ReceiptHandle,b:Body}'
sleep 2      # message becomes visible again while "worker 1" is still notionally working
# the real consumer now picks it up a second time
```
Assert exactly-once on the effect, not on the message.

### Check-then-act (TOCTOU)

Force the window between read and write: send request A, and time request B to land
after A has read but before A has written. Use the logs to find the real window — the
gap between the "loaded entity" and "saved entity" lines — then aim for its midpoint.

```bash
send_A &
sleep "$MIDPOINT"      # derived from observed timing, not guessed
send_B
wait
```

### Lock expiry mid-work

If the feature uses a distributed lock, test the case its TTL is shorter than the work:
inject a slow downstream (class 7) so the critical section outlives the lease, then send
a second request. Assert the second is blocked or the effect stays single. Check the
lock key's TTL directly via the `store: redis` adapter.

### Overlapping scheduled runs

Trigger the job while its previous run is still going. Assert the second run no-ops or
picks a disjoint work set — never that both process the same rows.

---

## 3. Assert something a race would break

Status codes are almost useless here — a race usually produces two happy responses and
one wrong database. Assert on **effects and cardinality**.

| Assertion | Written as | Catches |
|---|---|---|
| Exactly-once effect | `store.count(captures, order=X) == 1` | Duplicate side effect |
| No duplicate entity | `store.count(orders, idem_key=K) == 1` | Concurrent create |
| Terminal exclusivity | `status ∈ {CAPTURED, CANCELLED}` and not both recorded | Conflicting mutation |
| Monotonic state | status never appears earlier in the transition order than a previously observed one | Out-of-order regression |
| Version advanced once | `version == before + 1` after two racing writes | Lost update |
| Conservation | sum of ledger entries == expected total | Double-spend / partial write |
| No orphan | no `RUNNING` workflow, DLQ empty, no partial rows | Failed compensation |
| Response consistency | all N burst responses carry the same entity id | Idempotency key not honoured |
| Downstream call count | exactly one call to the partner in its logs/metrics | Duplicate external effect |

Two rules that make these reliable:

- **Read consistently.** DynamoDB assertions need `--consistent-read`; read replicas
  will happily show you a pre-race snapshot. Assert against the primary.
- **Assert the effect, not the acknowledgement.** "Both requests returned 200" is data;
  "there are two capture rows" is the finding.

Encode these as `## Invariants` in the task file so they run after *every* step of every
scenario. Most races are found by an invariant in a scenario that was testing something
else entirely.

---

## 4. Run it enough times

A race that reproduces 20% of the time passes four runs in a row often enough to be
believed. Rules:

- **Never accept a single green run for a class-5 scenario.** `--repeat 10` is the floor;
  20+ for anything touching money.
- **Report the ratio**, always: `7 PASS / 3 FAIL` is not "mostly passing", it is a
  confirmed race with a 30% reproduction rate.
- **Any failure across repeats fails the scenario.** Do not average, do not re-run to
  get a clean sheet.
- **A scenario that flips between passes and failures is more alarming than one that
  always fails** — always-fails is a plain bug; flapping is a race that will surface
  under production load.
- **Vary the timing between repeats.** Sweep the offset (0ms, 5ms, 20ms, 100ms) rather
  than repeating the identical interleaving — the window you missed is usually 15ms wide.
- **Widen the window when you cannot reproduce.** Slow the critical section deliberately
  (fault injection, a throttled downstream, a large payload) to open a gap wide enough
  to hit reliably. A race that only reproduces with a widened window is still a real
  race; note the technique in the report.

```bash
# offset sweep
for OFF in 0 0.005 0.02 0.1 0.25; do
  for TRY in $(seq 1 5); do
    run_pair_with_offset "$OFF"     # record RUN_ID, offset, result
  done
done
```

---

## 5. Report a race honestly

A race finding needs four things or it will be dismissed as flaky infrastructure:

1. **Reproduction rate** — "3/10 at 20ms offset", not "sometimes".
2. **The observed wrong state** — the query and its output, verbatim.
3. **The interleaving** — which requests, in what order, how far apart, with timestamps
   from the logs of both.
4. **The invariant violated** — named, so the fix has an acceptance criterion.

And say what it implies about the fix, since the shape of the race points at it: two
creates → unique constraint or idempotency key; lost update → optimistic locking with a
version check; duplicate effect → idempotent consumer with a dedup table; early callback
→ buffer the signal; out-of-order → sequence numbers with a monotonic guard.

Never file a race as "intermittent test failure". If the harness produced a wrong state,
the system produced a wrong state.
