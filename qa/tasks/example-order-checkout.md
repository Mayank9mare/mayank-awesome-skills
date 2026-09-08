# order-checkout — QA Task File (worked example)

An illustrative task file on a **Temporal + Pub/Sub + Postgres + GCS + GitHub Actions**
stack, deliberately not the stack the framework was first written against. Copy the
shape, not the values.

## Feature Model

- **Entry points:** `POST /v1/orders` (customer), `payment.callback` Pub/Sub topic
  (payment partner relay), `order-reminder` scheduled workflow timer, admin cancel.
- **External effects:** `orders` row, `captures` row, one capture call to the payment
  partner, one `order.confirmed` message published, one invoice PDF written to GCS, one
  confirmation email. **Six effects → six exactly-once assertions.**
- **Wait points:** waiting for payment callback (up to 15m); waiting for fulfilment ack
  (up to 24h).
- **States:** `CREATED → AWAITING_PAYMENT → CAPTURED → CONFIRMED → FULFILLED`, with
  `CANCELLED` reachable from any non-terminal state, `FAILED` from capture.
- **Concurrency surface:** customer cancel vs. payment callback; duplicate partner
  callback; two checkout submits with one idempotency key; reminder timer firing as the
  callback lands; two fulfilment workers on one message.

## Environment

### stage
```
tier:          stage
base_url:      https://orders.stage.example.internal
gcp_project:   acme-stage
temporal_ns:   orders-stage
test_tenant:   qa-tenant-1
test_tenant_b: qa-tenant-2        # required for class 3
test_user:     qa-buyer@example.test
```

### prod
```
tier:          prod               # read-only; no injection, no cleanup
base_url:      https://orders.example.com
```

## Adapters

| Probe | Type | Config |
|---|---|---|
| health | http-endpoint | url=$base_url/healthz |
| api | http | base_url=$base_url, auth_cmd=`gcloud auth print-identity-token` |
| workflow | temporal | address=temporal.stage.example.internal:7233, namespace=orders-stage, workflow_type=OrderCheckoutWorkflow |
| queue | pubsub | project=acme-stage, topic=payment-callbacks, subscription=orders-payment-sub, dlq_subscription=orders-payment-dlq-sub |
| store | postgres | host=db.stage.example.internal, port=5432, db=orders, user=qa_ro, password_cmd=see Credentials |
| object | gcs | bucket=acme-stage-invoices, prefix=invoices/, project=acme-stage |
| logs | gcp-logging | project=acme-stage, resource_filter=`resource.labels.container_name="orders-api"` |
| metric | prometheus | url=https://prom.stage.example.internal |
| ci | github-actions | repo=acme/orders, workflow=deploy-stage.yml |

## Credentials

```
api_token:     gcloud auth print-identity-token
db_password:   gcloud secrets versions access latest --secret=orders-qa-ro --project=acme-stage
cloud_refresh: gcloud auth application-default login --no-launch-browser
```

## Preflight

1. Deployed revision matches the commit under test — `gh api repos/acme/orders/deployments --jq '.[0].sha'`
2. Both QA tenants exist and are distinct
3. Payment partner sandbox reachable — `GET $base_url/v1/_internal/partner-ping` → 200
4. Feature flag `checkout_v2` on for `qa-tenant-1`
5. DLQ subscription drained before starting

## Fixtures

| Name | Creates | Teardown |
|---|---|---|
| `order-awaiting-payment` | order via `create-order`, stops before callback | rows scoped `ref LIKE 'qa-$RUN_ID%'` |
| `order-captured` | above + `inject-payment-callback` | as above + GCS objects under `invoices/$RUN_ID*` |
| `tenant-pair` | two orders, one per tenant | as above |

## Invariants

| Name | Assertion |
|---|---|
| `one-order-per-idem-key` | `SELECT count(*) FROM orders WHERE idem_key=$RUN_ID` == 1 |
| `one-capture-per-order` | `SELECT count(*) FROM captures WHERE order_id=$ORDER_ID` == 1 |
| `one-invoice-object` | GCS objects matching `invoices/$RUN_ID*` == 1, generation count == 1 |
| `one-partner-capture-call` | partner log lines matching `capture $RUN_ID` == 1 |
| `status-never-regresses` | observed status index never decreases across steps |
| `no-negative-balance` | `SELECT count(*) FROM ledger WHERE balance < 0` == 0 |
| `dlq-empty` | `orders-payment-dlq-sub` undelivered == 0 |
| `no-orphan-workflow` | no `Running` execution once status is terminal |

## Scenarios

### happy/checkout-basic
Class: 1 · Setup: none

| # | Step | Action | Settle | Assert |
|---|---|---|---|---|
| 1 | create order | `create-order` | poll api 15s | api.status=AWAITING_PAYMENT; store.count(orders,idem=$RUN_ID)=1; workflow.state=AwaitingPayment |
| 2 | payment callback | `inject-payment-callback` | poll api 30s | api.status=CAPTURED; store.count(captures)=1 |
| 3 | invoice written | — | poll object 20s | object.count(invoices/$RUN_ID*)=1 |
| 4 | confirmation published | — | poll logs 15s | logs.contains("order.confirmed $RUN_ID"); queue.dlq=0 |
| 5 | terminal | — | poll api 20s | api.status=CONFIRMED; workflow.status=Completed; invariants.all |

### negative/missing-idempotency-key
Class: 2

| # | Step | Action | Settle | Assert |
|---|---|---|---|---|
| 1 | submit without key | `create-order --no-idem-key` | — | api.code=400; store.count(orders,ref=$RUN_ID)=0; workflow.count=0; queue.depth unchanged |

### authz/cross-tenant-read
Class: 3 · Setup: `tenant-pair`

| # | Step | Action | Settle | Assert |
|---|---|---|---|---|
| 1 | tenant A reads B's order | `get-order --as tenant-b-token --id $ORDER_A` | — | api.code=404 (not 403 — 403 leaks existence) |
| 2 | tenant A cancels B's order | `cancel-order --as tenant-b-token --id $ORDER_A` | poll store 10s | api.code=404; store: order A status unchanged |

### idempotency/duplicate-callback-late
Class: 4 · Repeat: 3 · Setup: `order-captured`

| # | Step | Action | Settle | Assert |
|---|---|---|---|---|
| 1 | replay callback after completion | `inject-payment-callback` (identical body) | poll 20s | api.status=CONFIRMED (unchanged) |
| 2 | no second effect | — | — | invariants.one-capture-per-order; invariants.one-invoice-object; invariants.one-partner-capture-call |

### races/concurrent-submit
Class: 5 · Repeat: 10

| # | Step | Action | Settle | Assert |
|---|---|---|---|---|
| 1 | 10 identical submits, one idem key | `burst:[create-order ×10]` | poll api 20s | all 10 responses carry the same order id |
| 2 | single entity | — | — | invariants.one-order-per-idem-key; workflow.count(by $RUN_ID)=1 |

### races/cancel-vs-callback
Class: 5 · Repeat: 20 · Offsets: 0, 5ms, 20ms, 100ms · Setup: `order-awaiting-payment`

| # | Step | Action | Settle | Assert |
|---|---|---|---|---|
| 1 | cancel and callback together | `burst:[cancel-order, inject-payment-callback]` | poll api 30s | api.status ∈ {CANCELLED, CAPTURED} — exactly one |
| 2 | effects match the outcome | — | — | if CANCELLED: captures=0, invoices=0, no partner capture call. if CAPTURED: each == 1 |
| 3 | no debris | — | — | invariants.all; workflow.status ∈ {Completed, Cancelled}; queue.dlq=0 |

**This is the scenario that matters most for this feature.** A CANCELLED order with a
capture row means the customer was charged for a cancelled order.

### races/early-callback
Class: 5 · Repeat: 15

| # | Step | Action | Settle | Assert |
|---|---|---|---|---|
| 1 | start checkout, do not wait | `create-order &` | — | — |
| 2 | callback within 50ms | `inject-payment-callback` | poll api 45s | api.status=CAPTURED |
| 3 | not stuck | — | — | workflow.status != Running; logs.errors=absent |

### timeouts/payment-callback-never-arrives
Class: 6 · Setup: `order-awaiting-payment`

| # | Step | Action | Settle | Assert |
|---|---|---|---|---|
| 1 | wait past the 15m deadline | — | poll workflow 16m | workflow.status=Completed (timeout path), api.status=FAILED |
| 2 | known terminal state | — | — | no Running execution; captures=0; customer-facing status is FAILED, not AWAITING_PAYMENT |

### failure/partner-5xx-then-recover
Class: 7 · Blast radius: payment partner sandbox only

| # | Step | Action | Settle | Assert |
|---|---|---|---|---|
| 1 | force partner 5xx | `partner-fault --mode 500 --count 2` | — | — |
| 2 | create + callback | `create-order`, `inject-payment-callback` | poll api 60s | api.status=CAPTURED after retries |
| 3 | retried, not duplicated | — | — | invariants.one-capture-per-order; metric `partner_calls_total` delta == 3 (2 failed + 1 ok) |

### lifecycle/cancel-after-fulfilled
Class: 8 · Setup: `order-captured`, advanced to FULFILLED

| # | Step | Action | Settle | Assert |
|---|---|---|---|---|
| 1 | cancel a fulfilled order | `cancel-order` | — | api.code=409; store: status still FULFILLED; no refund row |

### data-edges/unicode-and-boundaries
Class: 9

| # | Step | Action | Settle | Assert |
|---|---|---|---|---|
| 1 | emoji + RTL name, 512-char address | `create-order --fixture unicode-max` | poll api 15s | api 201; store round-trips bytes exactly; invoice PDF renders |
| 2 | zero-value order | `create-order --amount 0` | — | api.code=400 |
| 3 | DST-transition delivery date | `create-order --deliver 2026-03-29T02:30:00+01:00` | poll api 15s | stored instant matches, no off-by-one-hour |

## Action Templates

### create-order
```bash
curl -sS -w '\n%{http_code}' --connect-timeout 10 --max-time 30 \
  -X POST "$BASE_URL/v1/orders" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H 'Content-Type: application/json' \
  -H "X-Tenant: ${TENANT:-qa-tenant-1}" \
  -H "Idempotency-Key: $RUN_ID" \
  -d '{"ref":"'"$RUN_ID"'","sku":"SKU-1","qty":1,"amount":{"value":1999,"currency":"EUR"}}'
```
Extract: `ORDER_ID=$(jq -r '.id')`

### inject-payment-callback
```bash
gcloud pubsub topics publish payment-callbacks --project acme-stage \
  --message "$(jq -nc --arg r "$RUN_ID" --arg o "$ORDER_ID" \
    '{event:"payment.captured",order_id:$o,ref:$r,amount:{value:1999,currency:"EUR"},partner_ref:("p-"+$r)}')" \
  --attribute="run_id=$RUN_ID"
```

### cancel-order
```bash
curl -sS -w '\n%{http_code}' -X POST "$BASE_URL/v1/orders/$ORDER_ID/cancel" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "X-Tenant: ${TENANT:-qa-tenant-1}" -H "Idempotency-Key: $RUN_ID-cancel"
```

### partner-fault
```bash
curl -sS -X POST "$BASE_URL/v1/_internal/partner-sandbox/fault" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -d '{"mode":"{{mode}}","count":{{count}},"scope":"run:'"$RUN_ID"'"}'
```
Scoped to this run — never degrade the shared sandbox for everyone.

### burst
See the barrier pattern in `references/race-conditions.md`. Offsets come from the
scenario's `Offsets:` line.

## Expected States

| Step | api.status | workflow state | store | logs |
|---|---|---|---|---|
| after create | AWAITING_PAYMENT | AwaitingPaymentSignal | 1 order, 0 captures | `order created ref=$RUN_ID` |
| after callback | CAPTURED | CapturingPayment → WritingInvoice | 1 order, 1 capture | `capture ok ref=$RUN_ID` |
| after invoice | CONFIRMED | Completed | 1 order, 1 capture | `order.confirmed ref=$RUN_ID` |
| after cancel (pre-capture) | CANCELLED | Cancelled | 1 order, 0 captures | `cancelled ref=$RUN_ID` |

## Cleanup

Permission-gated, dry run first, always scoped by run prefix.

```sql
-- 1. show the user this count first
SELECT count(*) FROM orders WHERE idem_key LIKE 'qa-%' AND created_at < now() - interval '1 day';
-- 2. only after approval
DELETE FROM captures WHERE order_id IN (SELECT id FROM orders WHERE idem_key LIKE 'qa-%' AND created_at < now() - interval '1 day');
DELETE FROM orders   WHERE idem_key LIKE 'qa-%' AND created_at < now() - interval '1 day';
```
```bash
gcloud storage rm "gs://acme-stage-invoices/invoices/qa-*"          # approval required
temporal workflow terminate --query "WorkflowId STARTS_WITH 'qa-'" --reason "qa cleanup" \
  --namespace orders-stage                                          # approval required
```

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Callback published, status never moves | Published to the topic but the subscription filter excludes `run_id` attributes | Check subscription filter; publish without the attribute |
| Workflow stuck `AwaitingPaymentSignal` | Early-callback race — signal arrived before the wait registered | Reproduce with `races/early-callback`; fix is signal buffering |
| Two capture rows | `captures` has no unique constraint on `(order_id, partner_ref)` | The `races/cancel-vs-callback` finding |
| 401 mid-run | Identity token expired (1h) | `gcloud auth print-identity-token` is re-run per action template; refresh ADC if it fails |
| Invoice missing but status CONFIRMED | GCS write is fire-and-forget, not awaited by the workflow | Real bug — confirm before invoice write is an ordering defect |
