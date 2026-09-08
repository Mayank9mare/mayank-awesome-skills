# Scenario Catalog

Nine classes. A feature is covered when every class has either scenarios or a written
reason it does not apply. Use this file to *derive* scenarios — the questions under each
class are meant to be asked about the specific feature, and the answers become steps.

Read this before `/qa {feature} plan`, and whenever a coverage matrix shows a GAP.

---

## How to derive scenarios for a feature

Before writing any scenario, establish five things. Everything else follows from them.

1. **Entry points** — every way the feature can be started (API, event, cron, retry,
   admin action, replay).
2. **External effects** — everything the feature changes that outlives the request:
   rows, files, messages published, money moved, notifications sent, third-party calls.
   *Each external effect needs an exactly-once assertion.*
3. **Wait points** — everywhere the feature pauses for something it does not control:
   a callback, a human, a timer, a partner. *Each wait point is a race and a timeout
   scenario.*
4. **State machine** — the legal states and transitions. *Each illegal transition is a
   negative scenario; "never goes backwards" is an invariant.*
5. **Concurrency surface** — what two actors can touch simultaneously. *Each is a race
   scenario.* See `race-conditions.md`.

Write these into the task file's header. They are the justification for the scenario
list, and they make the gaps obvious.

---

## Class 1 — Happy path

The feature does what it says, end to end, on clean state.

Derive by asking: what are the distinct *successful* routes through the state machine?
Each branch that reaches a terminal success state is its own scenario — not one scenario
with conditionals.

- The primary flow, every step asserted at every layer (api, workflow, store, object, logs)
- Each successful variant (with/without optional inputs, each eligible product type,
  each supported channel)
- The minimal-input flow — only required fields
- The maximal-input flow — every optional field populated

Assert on more than the final state: the *intermediate* states matter, because a flow
that reaches the right end state through the wrong path will break the moment someone
adds a step.

## Class 2 — Negative / validation

The feature rejects what it should, cleanly, without side effects.

- Missing required field, wrong type, out-of-range value, malformed JSON
- Unknown enum value; empty array where one element is required
- Payload over the size limit
- Unknown or already-terminal entity id
- Illegal state transition (cancel an already-shipped order, approve twice)
- Referential violation (child for a parent that does not exist)

**The assertion that matters is `absent`:** a rejected request must leave *no* trace —
no row, no message, no workflow started, no partial write. Check the store and the bus
after every negative, not just the status code.

## Class 3 — Authorization and tenancy

- No credentials; expired credentials; malformed token
- Valid credentials, insufficient role/scope
- Cross-tenant read: tenant A requests tenant B's entity → 404, not 403 (403 leaks
  existence)
- Cross-tenant write: tenant A mutates tenant B's entity
- Object storage: signed URL from one tenant used against another's key
- Field-level: a low-privilege role that can read the entity but not a restricted field

Cross-tenant tests need two fixtures. If the task file has only one test tenant, that is
itself the finding.

## Class 4 — Idempotency and replay

At-least-once delivery is the norm. Anything that can be delivered once can be delivered
twice, in any order, at any distance in time.

- Same request, same idempotency key, twice → one effect, both responses identical
- Same request, *different* idempotency key → two effects (proves the key is real, not
  the request hash)
- Same key, *different* body → rejected (409), not silently accepted
- Duplicate event delivered immediately after the first
- Duplicate delivered after the workflow completed (late duplicate)
- Full replay of the event stream from the start
- Retry after a client timeout where the server actually succeeded

The invariant across this whole class: **count(external effect) == 1**. Assert it on
every effect enumerated in derivation step 2, not just the obvious one.

## Class 5 — Concurrency and races

The class this framework exists for. See `race-conditions.md` for construction,
injection and assertion technique. Summary of what belongs here:

- Two identical creates in flight simultaneously
- Two conflicting mutations on one entity (cancel vs. capture, approve vs. reject)
- Callback arriving before the code that awaits it has registered the wait
- Two events for one entity arriving out of order
- Consumer processing the same message on two workers (visibility timeout expiry)
- Reader observing an in-progress multi-step write (partial state visible)
- Distributed lock contention and lock expiry mid-work
- Concurrent scaling: N parallel runs of the whole happy path

Race scenarios are **only** valid with `--repeat` — a single pass proves nothing.

## Class 6 — Timeouts, retries and backoff

Every wait point from derivation step 3, twice: once where the awaited thing is late,
once where it never comes.

- Downstream responds just inside its timeout → success
- Downstream responds just outside → the declared timeout behaviour (retry? fail? compensate?)
- Downstream never responds → workflow reaches its timeout state, not a stuck execution
- Retries: assert the *count* of downstream calls, and that backoff actually spaced them
- Retry budget exhausted → terminal failure state, and the DLQ or failure queue gets it
- The workflow's own deadline expiring while a step is mid-flight
- A timer/reminder firing after the entity already reached a terminal state

Assert that a timeout leaves the system in a *known* state. "Stuck RUNNING forever" is
the most common real-world failure this class catches.

## Class 7 — Failure injection and recovery

Break a dependency on purpose, inside the blast radius the task file declares.

- Downstream returns 5xx, then recovers → does the feature retry and converge?
- Downstream returns a malformed body / wrong content type
- Downstream returns a business error (declined, not-eligible) vs. a technical error —
  they must be handled differently
- The store rejects the write (constraint violation, deadlock)
- The bus is unavailable when the feature tries to publish → is the write rolled back,
  or is there an outbox?
- The worker dies mid-step (kill the consumer, or terminate the execution) → on restart,
  does it resume or duplicate?
- Poison message → lands in DLQ, does not block the queue
- Compensation/rollback path actually runs and actually undoes the effect

The most valuable assertion here is on the *compensating* effect: after a mid-flight
failure, is the partial state cleaned up, or is there an orphan?

## Class 8 — Lifecycle edges

- Cancel before start, mid-flight, after a terminal state
- Modify while in flight
- Two lifecycle actions racing (belongs to class 5 too — run it in both)
- Resume/retry a failed run — does it start clean or double up?
- Terminal-state immutability: every mutating endpoint against a completed entity
- Expiry/TTL: the entity ages out mid-flow
- Superseded: a newer request for the same subject arrives while an older one is running

## Class 9 — Data shape and volume edges

- Unicode, emoji, RTL text, and very long strings in every user-supplied field
- Names/addresses with quotes, backslashes, newlines (also an injection check)
- Numeric extremes: zero, negative, max int, high-precision decimals, currency rounding
- Timezone edges: DST transition, UTC midnight, leap day, a client in +14:00
- Empty collections and single-element collections where the code expects many
- Large payloads: the biggest legal input, and the batch at its maximum size
- Null vs. absent vs. empty string — three different things that are often conflated
- Pagination boundaries: exactly one page, exactly one over, and a cursor reused after
  the underlying data changed

---

## Turning a class into steps

Each scenario is a step table. A good step declares what it does, how long to wait, and
what must be true after — nothing more:

```markdown
### races/concurrent-capture-cancel
Class: 5 · Repeat: 10 · Tier: stage+
Setup: fixtures.order-awaiting-capture

| # | Step | Action | Settle | Assert |
|---|---|---|---|---|
| 1 | create order | `create-order` | poll api 15s | api.status=AWAITING_CAPTURE; store.count(orders,ref)=1 |
| 2 | fire capture+cancel together | `burst:[capture-order,cancel-order]` | poll api 30s | api.status in {CAPTURED,CANCELLED} |
| 3 | assert single effect | — | — | store.count(captures,order)=1; store.count(refunds,order)=0; invariants.all |
| 4 | assert no orphan | — | — | queue.dlq=0; workflow.state!=RUNNING; logs.errors=absent |
```

Rules for steps:
- One observable action per step. A step doing two things cannot report which failed.
- Every step asserts something. A step with no assertion is not a test.
- The last step of every scenario asserts the invariants and the absence of debris
  (DLQ empty, no errors, no orphaned workflow).
- Prefer `poll` over a fixed wait — record the settle time as data.

## Prioritising when you cannot run everything

Order by blast radius of the effect, not by ease of testing:

1. Anything that moves money, sends an external message, or writes to a partner
2. Anything with a wait point (races and timeouts cluster here)
3. Anything with two writers
4. State transitions
5. Validation

Classes 4, 5, 6 and 7 catch the bugs that reach production; class 1 and 2 catch the bugs
that never leave the branch. If time is short, that is the argument for spending it here.
