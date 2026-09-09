# Example Digest

A worked output for a fictional `checkout` feature, digested from five sources: a `.docx`
BRD, an ADO wiki PRD, an ADO epic with nine stories, two ticket comment threads, and a
loose `.md` note. Abridged — enough requirements to show the shape, the conflicts, and
how a decision-table gap becomes an open question.

The point of this file is the **quality bar**, not the content: notice that every
requirement is one behaviour in EARS with a source ref, every conflict quotes both sides
verbatim, and every guess is marked.

---

# Checkout — Requirements

> Digested 2026-09-10 from 5 sources by `requirements-digest`.
> **Status: 2 blocking open questions (C-01, Q-01)** — see §6 before building.
> Unmarked statements come from a source. `[INFERRED]` and `[ASSUMPTION]` do not.

## 1. Summary

Customers submit an order, pay through a third-party partner, and receive an invoice.
Replaces the v1 checkout, which cannot support partial refunds or multi-currency.
Targeted at EU tenants first; US is explicitly out of scope for this release.

## 2. Scope

**In scope**
- Single-currency order submission and payment capture (S1 §2, S2 §1.1)
- Invoice generation and delivery (S2 §4)
- Customer-initiated cancellation before capture (S3 #4418)

**Out of scope**
- Partial refunds — *deferred to Q1, S2 §1.2*
- Multi-currency baskets — *S1 §2.1, "single currency per order"*
- Guest checkout — *not stated in any source; confirmed out by the PM in S4*

## 3. Sources

| # | Kind | Ref | Version / Updated | Authority | Read |
|---|---|---|---|---|---|
| S1 | BRD | ./docs/Payments-BRD-v2.3.docx | 2026-07-14 | high | full |
| S2 | PRD | ADO Wiki /specs/checkout (rev 18) | 2026-08-02 | high | full |
| S3 | Epic + 9 stories | ADO #4412 tree | 2026-09-01 | medium | full |
| S4 | Comments | ADO #4418, #4421 | 2026-09-03 | medium | full |
| S5 | Notes | ./notes/checkout-sync.md | 2026-08-28 | low | full |

Authority order applied: signed BRD > PRD > epic > story > comment > chat.
Expected but not found: latency/throughput targets, error-message copy, analytics events.

## 4. Glossary

| Term | Meaning here | Note |
|---|---|---|
| Order | The customer's purchase record, from submission to fulfilment | S1 calls this a "transaction"; S2 and the tickets say "order". Standardised on "order". |
| Capture | Taking payment against an authorised amount | S5 uses "charge" interchangeably — same thing |

## 5. Requirements

### 5.1 Functional

| ID | Requirement (EARS) | Source | Pri | Status | Tests |
|---|---|---|---|---|---|
| R-001 | When a customer submits an order with a valid basket, the checkout service shall create the order in AWAITING_PAYMENT. | S2 §3.1, S3 #4415 | must | agreed | T-001, T-002 |
| R-002 | When a `payment.captured` event is received for an order in AWAITING_PAYMENT, the checkout service shall transition the order to CAPTURED. | S2 §3.3, S3 #4418 | must | agreed | T-003, T-004 |
| R-003 | If a `payment.captured` event is received for an order not in AWAITING_PAYMENT, then the checkout service shall ignore the event and record an audit entry. | S4 (#4418 comment, 2026-09-03) | must | agreed | T-005, T-006 |
| R-004 | While an order is in CREATED or AWAITING_PAYMENT, when the owning customer requests cancellation, the checkout service shall transition the order to CANCELLED and release the stock reservation. | S3 #4418 | must | agreed | T-007, T-008 |
| R-005 | If a cancellation is requested for an order in CAPTURED or later, then the checkout service shall reject it with 409 ORDER_NOT_CANCELLABLE. | S3 #4418 | must | agreed | T-009 |
| R-006 | When an order reaches CAPTURED, the checkout service shall generate exactly one invoice document. | S2 §4.1 | must | agreed | T-010, T-011 |
| R-007 | If the payment partner does not respond within 15 seconds, then the checkout service shall fail the order with PARTNER_TIMEOUT and release the reservation. | S2 §3.4 | must | **disputed (C-01)** | T-012 |

### 5.2 Business rules

| ID | Requirement (EARS) | Source | Pri | Status | Tests |
|---|---|---|---|---|---|
| R-008 | Where the tenant has free-shipping enabled, when the basket total is at or above £50, the checkout service shall apply zero shipping cost. | S1 §3.1 | must | **open (Q-01)** | T-013, T-014 |
| R-009 | The checkout service shall retain order records for 30 days after fulfilment. | S1 §4.2 | must | **disputed (C-02)** | T-015 |

### 5.4 Non-functional

| ID | Requirement (EARS) | Source | Pri | Status | Tests |
|---|---|---|---|---|---|
| R-010 | `[INFERRED]` The checkout service shall respond to order submission within a stated p95 latency budget. | — | must | **open (Q-02)** | — |

*R-010 has no source. No number has been invented; Q-02 asks for one.*

## 6. Conflicts & Open Questions

### Blocking

| ID | Issue | Side A | Side B | Recommendation | Owner |
|---|---|---|---|---|---|
| C-01 | Partner timeout | "the partner has **30 seconds** to respond" — S1 §4.4 | "fail the order after **15 seconds**" — S2 §3.4 | Take S1 (30s): the signed BRD outranks the PRD, and S1 cites the partner's contractual SLA. But S2 is more recent — confirm rather than assume. | Payments PM |

| ID | Question | Blocks | Owner |
|---|---|---|---|
| Q-01 | Is £50 inclusive at the free-shipping threshold? S1 §3.1 says "over £50"; the worked example in S1 Appendix B shows a £50.00 basket getting free shipping. | R-008, T-013, T-014 | Business analyst |

### Non-blocking

| ID | Question | Affects | Owner |
|---|---|---|---|
| C-02 | Retention: S1 §4.2 says 30 days; S5 records "PM confirmed 45 days" on 2026-08-28. A note is the weakest source and does not supersede a signed BRD — but it is the most recent statement. | R-009 | Compliance |
| Q-02 | No latency target exists in any source. What is the p95 budget for order submission? | R-010 | Payments PM |
| Q-03 | What happens to an order whose tenant is offboarded mid-flight? No source addresses it. | — | Payments PM |

## 7. Assumptions

| ID | Assumption | Why needed | Risk if wrong |
|---|---|---|---|
| A-01 | `[ASSUMPTION]` Invoice delivery failure does not block the order reaching CONFIRMED. | S2 §4 describes generation and delivery but never says whether delivery is on the critical path. | If wrong, orders would stall on an email outage — a availability defect, not a data one. |

## 8. Test Cases

| ID | Case | Covers | Class | Pri |
|---|---|---|---|---|
| T-001 | Submit valid basket → order in AWAITING_PAYMENT | R-001 | 1 happy | must |
| T-002 | Submit with empty basket → 400, no order row | R-001 | 2 negative | must |
| T-004 | `payment.captured` delivered twice → one capture, one invoice | R-002, R-006 | 4 idempotency | must |
| T-006 | `payment.captured` for a CANCELLED order → ignored, audit entry, no capture | R-003 | 8 lifecycle | must |
| T-008 | Cancel and capture arrive simultaneously → exactly one wins, no orphan effect | R-004, R-002 | 5 races | must |
| T-011 | Two `payment.captured` events race → exactly one invoice object | R-006 | 5 races | must |
| T-012 | Partner silent past the timeout → order FAILED, reservation released | R-007 | 6 timeouts | must |
| T-013 | Basket at £49.99 → shipping charged | R-008 | 9 data-edges | must |
| T-014 | Basket at exactly £50.00 → **blocked on Q-01** | R-008 | 9 data-edges | must |

**Coverage note:** boundary values applied to the £50 threshold (T-013/T-014); a decision
table over (member × basket ≥ £50 × coupon) produced one unfillable cell — coupon plus
sub-threshold basket — raised as Q-01's sibling. Race cases (T-008, T-011) come from the
two wait points in R-002 and R-004. No pairwise reduction was needed at this size.

## 9. Traceability

**Source → Requirements**

| Source | Requirements |
|---|---|
| S1 | R-008, R-009, and C-01 side A |
| S2 | R-001, R-002, R-006, R-007 |
| S3 | R-001, R-002, R-004, R-005 |
| S4 | R-003 *(a comment-only requirement — it exists in no spec)* |
| S5 | C-02 only |

**Requirement → Tests**

| Requirement | Tests | Classes |
|---|---|---|
| R-001 | T-001, T-002 | 1, 2 |
| R-002 | T-003, T-004, T-008 | 1, 4, 5 |
| R-010 | — | **none — untestable until Q-02 is answered** |

## 10. Not Covered

- Latency, throughput and availability targets — no source states any (Q-02)
- Error-message copy — expected in S2, absent
- Analytics events — mentioned in S5 as "TBD"
- US-market behaviour — out of scope per §2

---

### Review gate

| Gate | Result |
|---|---|
| Attribution — every requirement sourced or marked | PASS |
| Atomicity — no compound requirements | PASS |
| Testability — every requirement has a test, no smell words | **FAIL — R-010 has no test (Q-02)** |
| Traceability — every source yielded requirements | PASS |
| Conflict closure — every blocking conflict has a recommendation and owner | PASS |
| Coverage — every requirement has a negative case | **FAIL — R-009 has no negative case** |
| Scope — nothing in §5 that §2 excludes | PASS |

**Blocked on:** C-01 (partner timeout) and Q-01 (threshold inclusivity). Both change test
expectations, so QA should not start on R-007 or R-008 until answered.
