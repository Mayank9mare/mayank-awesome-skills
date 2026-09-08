---
name: qa
description: Stack-agnostic E2E QA automation. Derives a full scenario set for a feature — happy path, negatives, idempotency, concurrency and race conditions, timeouts and retries, failure injection, lifecycle edges — then executes each scenario step-by-step against a real environment and reports pass/fail with evidence. All environment specifics (workflow engine, event bus, datastore, object store, logs, CI) come from a per-feature task file, never from this skill.
user-invocable: true
---

# E2E QA Automation

A feature is not "tested" because the happy path returned 200. It is tested when you
know what it does under a duplicate callback, two concurrent writers, a downstream
timeout, an out-of-order event, and a cancel that lands mid-flight.

This skill is the **harness and the method**. It knows nothing about your stack.
Everything specific — hosts, workflow engine, queues, database, object storage, log
platform, CI, credentials — is declared in a task file at `tasks/{feature}.md`, and the
concrete commands for each declared adapter type live in `references/adapters.md`.

## When to Use

- `/qa {feature}` — list the feature's scenarios and coverage gaps
- `/qa {feature} {scenario}` — run one scenario
- `/qa {feature} all` — run every scenario, in dependency order
- `/qa {feature} races` — run only the concurrency/race class
- `/qa {feature} preflight` — environment checks only
- `/qa {feature} plan` — derive scenarios for a feature that has no task file yet
- Validating a deployment before promoting it
- Reproducing a suspected race or ordering bug under controlled conditions

**Not for:** unit/integration tests inside a repo (use `tdd`), or diagnosing a live
incident (use `troubleshooter`). This drives a deployed environment from outside.

## Usage

```
/qa {feature}                  — list scenarios + coverage matrix
/qa {feature} preflight        — preflight only
/qa {feature} {scenario}       — one scenario
/qa {feature} {class}          — one class (happy|negative|authz|idempotency|races|timeouts|failure|lifecycle)
/qa {feature} all              — everything
/qa {feature} plan             — derive scenarios, write/extend the task file
```

Flags: `--repeat N` (rerun each scenario N times; required for race classes),
`--auto` (no prompts, abort on first failure), `--keep` (skip teardown, leave data for
inspection), `--env {name}` (select an environment block from the task file).

## Architecture

```
SKILL.md                       ← generic framework (this file). No vendor names in the flow.
references/
  adapters.md                  ← concrete commands per adapter type (workflow, queue, store, object, logs, ci)
  scenario-catalog.md          ← the nine scenario classes and how to derive them for any feature
  race-conditions.md           ← concurrency playbook: interleavings, injection, exactly-once assertions
templates/
  task-template.md             ← blank task file to copy
tasks/
  {feature}.md                 ← ALL specifics for one feature
  example-order-checkout.md    ← worked example (Temporal + Pub/Sub + Postgres + GCS)
```

The rule: **if a string names a vendor, a host, an ARN, a queue, a table, a job or a
region, it belongs in the task file.** This file and the scenario/race references stay
portable.

## The Adapter Model

The harness only ever talks to a feature through **probes**. A probe is an abstract
capability; the task file binds each probe to an adapter *type*, and
`references/adapters.md` supplies the command for that type.

| Probe | Question it answers | Example adapter types |
|---|---|---|
| `health` | Is the service under test up? | http-endpoint, k8s-readiness, tcp |
| `api` | What does the service say the state is? | http/rest, graphql, grpc |
| `workflow` | Where is the orchestration, and did it fail? | sfn, temporal, cadence, airflow, camunda, argo, none |
| `queue` | Are events flowing, and is anything in the DLQ? | sqs, pubsub, kafka, rabbitmq, eventbridge, nats, none |
| `store` | What does the durable state actually look like? | mysql, postgres, dynamodb, spanner, bigquery, firestore, mongodb |
| `object` | Was the artifact written? | s3, gcs, azure-blob, none |
| `logs` | What did the code say while doing it? | loki, cloudwatch, gcp-logging, elasticsearch, datadog, splunk |
| `metric` | Did counters/latency move as expected? | prometheus, cloudwatch-metrics, gcp-monitoring, none |
| `ci` | Is the code under test actually deployed? | jenkins, github-actions, gitlab-ci, argocd, none |

Any probe the task file does not declare is **skipped, not failed** — a feature with no
workflow engine simply has no `workflow` probe, and nothing in this skill breaks.

Every adapter declaration carries its own config keys. Look the type up in
`references/adapters.md` for the exact commands and the config keys it expects.

## Step 1: Resolve the Task File

Read `tasks/{feature}.md` (checking both the skill directory and
`~/.claude/skills/qa/tasks/`). If it does not exist, list what does, and offer
`/qa {feature} plan` — which reads `references/scenario-catalog.md`, interviews the user
about the feature, and writes a task file from `templates/task-template.md`.

From the task file, load: the selected `## Environment` block, the `## Adapters` table,
`## Invariants`, `## Scenarios`, `## Action Templates`, `## Expected States`,
`## Fixtures`, `## Cleanup`, `## Troubleshooting`.

**Env safety classification.** Every environment block declares `tier: local | dev |
stage | prod`. On a `prod` tier: no writes, no event injection, no cleanup, no CI
triggers — read-only probes only, unless the user explicitly authorizes each write in
this session. Refuse silently-destructive behaviour; say what you are skipping.

## Step 2: Preflight

Preflight is derived from the declared adapters, not hardcoded. For each adapter in the
task file's `## Adapters` table, run its reachability check from
`references/adapters.md`. Then run whatever the task file's `## Preflight` section adds.

```
## Preflight: {feature} @ {env} (tier: stage)
| Check | Adapter | Status | Details |
|---|---|---|---|
| Service health | http-endpoint | PASS | 200, build 2f9c1a |
| Deployed revision | github-actions | WARN | HEAD is 3 commits ahead of deployed |
| Workflow engine | temporal | PASS | namespace reachable, 1 open execution |
| Event bus | pubsub | PASS | subscription exists, DLQ empty |
| Datastore | postgres | PASS | connected, read-only user |
| Logs | loki | PASS | 12 lines in last 5m |
| Fixtures | — | FAIL | test tenant `qa-tenant-1` not found |
```

Any FAIL blocks scenario execution unless the user overrides. WARN is reported and
continues.

## Step 3: Derive the Scenario Set

Before running anything, check coverage. Read `references/scenario-catalog.md` and map
the task file's scenarios onto the nine classes. Report the matrix and name the gaps —
missing coverage is a finding, not silence:

```
## Coverage: {feature}
| Class | Scenarios | Status |
|---|---|---|
| 1 happy | checkout-basic, checkout-with-coupon | covered |
| 2 negative | bad-payload, missing-idem-key | covered |
| 3 authz | — | GAP |
| 4 idempotency | duplicate-submit | covered |
| 5 races | concurrent-submit, late-callback | covered |
| 6 timeouts | — | GAP |
| 7 failure-injection | payment-5xx | covered |
| 8 lifecycle | cancel-mid-flight | covered |
| 9 data-edges | — | GAP |
```

On `/qa {feature} all`, run every covered scenario and list the gaps in the final
report. Offer to draft scenarios for the gaps.

## Step 4: Execute a Scenario

Each scenario is a list of steps. A step is: **arrange → act → settle → assert →
record**.

### 4a. Arrange

Generate a fresh correlation identity for the run — every scenario run gets a unique
`RUN_ID` that appears in generated IDs, request headers, and log queries, so runs never
collide and evidence is always attributable:

```bash
RUN_ID="qa-$(date +%s)-$RANDOM"
```

Apply the task file's `## Fixtures` (seed data, test tenant, feature flags) and, if the
task file declares `## Cleanup`, run Step 4f's gate *before* the first step.

### 4b. Act

Execute the step's action — a named block from the task file's `## Action Templates`
with `{{PLACEHOLDER}}` substitution from: prior step outputs (chain forward), fixtures,
`RUN_ID`-derived values, user-supplied values.

Actions are not only HTTP calls. A step's action may be an event injection (publish to
the bus to simulate a partner webhook, a callback, a timer fire), a workflow signal, a
clock advance, a fault injection, or a concurrent burst — see `references/adapters.md`
for the per-type command and `references/race-conditions.md` for the burst patterns.

Always capture the status code and body, and extract chained values explicitly:

```bash
RESP=$(curl -sS -w '\n%{http_code}' --connect-timeout 10 --max-time 30 {{ARGS}})
CODE=$(printf '%s' "$RESP" | tail -1); BODY=$(printf '%s' "$RESP" | sed '$d')
```

### 4c. Settle

Async systems need a settle window before assertions are meaningful. **Poll, do not
sleep blindly**: re-run the cheapest discriminating probe until it matches or the budget
expires. The task file gives each step a `settle` budget (default 30s, poll every 2s).
Record the actual settle time — a step that used to settle in 2s and now takes 25s is a
finding even when it passes.

### 4d. Assert

Run the step's declared assertions. Assertion kinds:

| Kind | Meaning |
|---|---|
| `equals` | A probe field matches an expected value |
| `contains` | A collection contains an expected element (e.g. a timeline event) |
| `absent` | Something must NOT exist (no error logs, no DLQ message, no duplicate row) |
| `count` | An exact cardinality — the backbone of exactly-once assertions |
| `state` | The workflow/execution is in an expected state, and not FAILED/TIMED_OUT |
| `within` | The step completed inside a latency budget |
| `unchanged` | A value that must not have moved (balance, counter, version) |

Always run, on every step, regardless of what the step declares:

1. **Error sweep** — `logs` probe filtered to error level AND `RUN_ID`. Any hit fails
   the step and the log lines go in the report.
2. **Workflow liveness** — if a `workflow` adapter is declared: execution is not
   FAILED / TIMED_OUT / TERMINATED, and has advanced since the previous step.
3. **DLQ sweep** — if a `queue` adapter is declared: DLQ depth is still zero.
4. **Invariants** — every invariant in the task file's `## Invariants` section. These
   are the assertions that catch races: "exactly one order row per idempotency key",
   "balance never negative", "status never moves backwards", "at most one workflow
   execution per subject". Invariants are checked after *every* step of *every*
   scenario, not just the race ones.

### 4e. Record

Store per step: status, wall duration, settle time, extracted IDs, probe evidence, and
the exact commands run. Evidence is what makes a QA report actionable — a failing step
must carry the request, the response, and the log/probe output that proved it wrong.

On failure: in interactive mode ask **retry / skip / continue / abort / investigate**
(investigate = dump all probes at their current state). In `--auto` mode, abort the
scenario and report. Either way run teardown unless `--keep`.

### 4f. Cleanup and Teardown

Cleanup removes data a prior run left behind; teardown removes what this run created.

**Never run a destructive operation without explicit permission.** Show the user exactly
what will be deleted — adapter, target (table/bucket/queue), filter predicate, and a
counted dry run — then ask via AskUserQuestion. If denied, continue and warn that
uniqueness assertions may fail on leftover data. On `prod` tier, do not offer it at all.

Prefer teardown that is naturally scoped: because everything the run created carries
`RUN_ID`, the predicate is always `... WHERE ref LIKE 'qa-{RUN_ID}%'`.

## Step 5: Report

```
## QA Report: {feature} / {scenario} @ {env}
**Result: FAIL at step 4**  ·  **Duration 1m12s**  ·  **Run qa-1757370000-4821**

| # | Step | Status | Wall | Settle | Notes |
|---|---|---|---|---|---|
| 1 | create order | PASS | 0.4s | — | orderId=88213 |
| 2 | inject payment callback | PASS | 0.2s | 3.1s | |
| 3 | duplicate callback (replay) | PASS | 0.2s | 2.8s | ignored as expected |
| 4 | concurrent cancel + capture | FAIL | 4.1s | 30s (budget) | 2 capture rows, expected 1 |

### Failures
- **Step 4 — invariant `exactly-one-capture` violated.** `SELECT count(*) … = 2`.
  Both requests read version 7 before either wrote. Suggests a missing optimistic-lock
  or unique constraint on (order_id, capture_ref).
  - Evidence: `logs` 12 lines around T+2.1s, both threads entering `capturePayment`.

### Invariant status
| Invariant | Result |
|---|---|
| exactly-one-capture | FAIL (step 4) |
| status-never-regresses | PASS |
| dlq-empty | PASS |

### Coverage gaps for this feature
- class 3 authz — no scenarios
- class 6 timeouts — no scenarios

### Flake signal (--repeat 5)
- concurrent-cancel-capture: 3 PASS / 2 FAIL → non-deterministic, treat as a real race.
```

Race-class scenarios are only meaningful in aggregate: a single green run proves
nothing. Always report the pass ratio across repeats, and treat *any* failure across
repeats as a failure of the scenario.

## Extensive by Default

"Run the tests" for a feature means all nine classes, not the happy path. When the user
asks for a feature to be tested and the task file only has happy-path scenarios, say so
and offer to derive the rest — a QA pass that only proves the feature works when nothing
goes wrong has not tested the feature. `references/scenario-catalog.md` has the
derivation questions per class; `references/race-conditions.md` has the concurrency ones.

## Safety Rules

- **Tier gates everything.** `prod` is read-only by default; every write needs explicit
  per-action authorization in the session.
- **SELECT only** on stores unless the user approves a write, and always with a `LIMIT`.
- **Never publish to a production event bus** or trigger a production deploy.
- **Never echo secrets.** Credentials come from a secret manager or env at use time and
  are never printed, logged, or written into the report.
- **Credential expiry is yours to handle.** If the task file declares a refresh command,
  run it yourself on an auth error rather than asking; fall back to asking the user to
  run it via `!` only if it needs interactive input (MFA).
- **Fault injection stays inside the blast radius the task file declares.** Never
  degrade a shared dependency to test one feature.

## Task File Format

Copy `templates/task-template.md`. Required sections:

```markdown
## Environment          — one block per env; each declares tier + hosts + IDs
## Adapters             — probe → adapter type → config keys
## Credentials          — how to obtain/refresh (commands, not values)
## Deploy               — optional: how to get code under test deployed
## Preflight            — feature-specific checks beyond adapter reachability
## Fixtures             — seed data, test tenants, flags to set
## Invariants           — assertions checked after EVERY step
## Scenarios            — grouped by class; each a step table
## Action Templates     — named, parameterised commands (HTTP, events, signals, faults)
## Expected States      — per step: API state, workflow state, store state, log patterns
## Cleanup              — scoped, reversible, permission-gated
## Troubleshooting      — feature-specific failure patterns
```

See `tasks/example-order-checkout.md` for a fully worked example on a
Temporal + Pub/Sub + Postgres + GCS stack, deliberately not the stack this skill was
first written against.

## Generic Failure Patterns

Vendor-specific decoding lives in `references/adapters.md`. These hold anywhere:

| Symptom | Likely cause |
|---|---|
| Action 2xx, state never changes | Consumer not running, or event went to a different subscription |
| Action 2xx, DLQ grows | Consumer throwing on the payload — check the error sweep |
| Workflow stuck in a wait state | Nothing delivered the awaited signal/callback; injection targeted the wrong queue |
| Passes alone, fails in `all` | Shared fixture or leftover data — teardown is not scoped by `RUN_ID` |
| Passes on retry, fails first time | Settle budget too short, or a genuine race — rerun with `--repeat` |
| Duplicate rows / double side effect | Missing idempotency key or unique constraint (class 4/5) |
| Status regresses | Concurrent writers with last-write-wins, no version check |
| Works on stage, not on prod-like data | Data-shape edge (class 9) — volume, unicode, timezone, null |
