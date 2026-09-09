# Test Derivation

Turning requirements into test cases mechanically, so coverage is a property of the
method rather than of how thorough someone felt that day.

Three passes: **from the EARS clauses**, **from the data**, **from the nine classes**.
Then prune.

---

## Pass 1 — from the EARS clauses

Each clause type demands specific cases. This pass alone gives a defensible baseline.

### `When <trigger>, the system shall <response>`
| Case | Why |
|---|---|
| Trigger occurs → response happens | The requirement itself |
| Trigger does not occur → response does not happen | Catches unconditional execution |
| Trigger occurs twice | Idempotency — usually unstated, always needed |
| Trigger occurs in an unexpected state | Reveals a missing `While` precondition |
| Trigger malformed / partial | The `If-Then` the sources forgot |

### `While <precondition>, the system shall <response>`
| Case | Why |
|---|---|
| In state → behaviour holds | The requirement itself |
| Not in state → behaviour does not hold | Precondition is real, not decorative |
| State entered while operation in flight | Boundary — where races live |
| State exited while operation in flight | Same, other direction |

### `If <trigger>, then the system shall <response>`
| Case | Why |
|---|---|
| Unwanted condition occurs → handled as specified | The requirement itself |
| No partial side effect remains | The half-failure is the real bug |
| Condition occurs repeatedly | Retry storms, alert floods |
| Condition clears → recovery | Recovery is rarely specified; ask |

### `Where <feature included>, the system shall <response>`
| Case | Why |
|---|---|
| Feature on → behaviour present | The requirement itself |
| Feature off → behaviour absent, nothing breaks | The case that ships broken |
| Toggled mid-flight | In-flight work under a changing flag |

### Ubiquitous
| Case | Why |
|---|---|
| Holds on the primary path | The requirement itself |
| Holds on every error path | "Always" includes failures — usually untested |

---

## Pass 2 — from the data

Applied to every value, range, enumeration and collection mentioned in a requirement.

**Equivalence partitioning** — one representative per class of input treated the same
way. Do not test five valid values; test one valid, and each *distinct* invalid reason.

**Boundary values** — for any range `[min, max]`: `min−1`, `min`, `min+1`, typical,
`max−1`, `max`, `max+1`. Off-by-one is the most common defect a requirement document
can prevent, and the boundary is where a source's ambiguity shows: "orders over £100"
never says whether £100 itself qualifies. **That ambiguity is an open question, not a
test you guess at.**

**Enumerations** — every value, plus one unknown value, plus null/absent.

**Collections** — empty, exactly one, many, maximum allowed, one over maximum. Plus
ordering and pagination boundaries where a requirement mentions a list.

**Decision tables** — when a rule combines conditions, tabulate them rather than writing
prose. Each row is a test case, and empty cells expose the combinations no source covers:

| # | Member? | Basket ≥ £50 | Coupon | → Shipping |
|---|---|---|---|---|
| 1 | yes | yes | none | free |
| 2 | yes | no | none | £3.99 |
| 3 | no | yes | none | free |
| 4 | no | no | none | £4.99 |
| 5 | yes | no | SHIP10 | **? — no source states this** |

Row 5 is the finding. A decision table's value is the cells you cannot fill.

**State transition** — for any lifecycle, build the full state × event matrix. Legal
transitions are positive cases; **every illegal cell is a negative case**, and most
requirement documents specify none of them.

**Pairwise** — when combinations explode (5 payment methods × 4 countries × 3 tiers ×
2 flags = 120), cover all *pairs* rather than all combinations; ~20 cases catch the vast
majority of interaction defects. Say in the document that you used pairwise, so nobody
believes coverage is exhaustive.

---

## Pass 3 — from the nine classes

Cross-check against the `qa` skill's `references/scenario-catalog.md`. Every requirement
gets tagged with the classes it touches, and any class with no case for a requirement
that plainly needs one is a gap:

| Class | Ask of each requirement |
|---|---|
| 1 happy | Does the primary route have a case? |
| 2 negative | What invalid input reaches this, and is the rejection side-effect-free? |
| 3 authz | Which roles may trigger this? What does another tenant see? |
| 4 idempotency | What if this happens twice? |
| 5 races | What if two actors do this at once? |
| 6 timeouts | What if the thing it waits for is late, or never comes? |
| 7 failure | What if a dependency fails midway — is the partial state cleaned up? |
| 8 lifecycle | What if the entity is cancelled, expired, or already terminal? |
| 9 data-edges | Unicode, extremes, timezones, nulls, volume |

Classes 4–8 are where requirement documents are thinnest, and where production defects
come from. **A class with no case for a requirement that obviously needs one is an open
question (`Q-nn`) about the requirement, not just a missing test.** That is the main way
this pass improves the requirements rather than only the test list.

---

## Writing a case

```markdown
### T-014 — Cancel is rejected once the order is captured
Covers: R-008, R-019 · Class: 8 lifecycle · Priority: must · Source: S1 §4.2, ADO #4418
Preconditions: order in CAPTURED, requested by the owning customer
Steps:
  1. POST /v1/orders/{id}/cancel
Expected:
  - HTTP 409, error code ORDER_NOT_CANCELLABLE
  - Order status remains CAPTURED
  - No refund record created
  - Audit entry recorded for the rejected attempt (R-019)
```

Rules:
- **Expected results are observable and specific.** "Handled correctly" is not an
  expected result.
- **Assert the absence too.** Most defects are an extra effect, not a missing one — no
  refund row, no email, no second message.
- **One case, one purpose.** A case asserting five unrelated things cannot report which
  one failed.
- **Every case names the `R-nnn` it covers.** A case covering nothing is scope creep; a
  requirement covered by nothing is untestable — both are gate failures.

---

## Prune

Coverage is not case count. Remove:
- Cases that differ only in a value inside the same equivalence class
- Cases for combinations the decision table shows are equivalent
- Cases asserting framework behaviour rather than the requirement
- Duplicate cases arriving from different requirements — merge and let it cover both

Then state coverage honestly: which requirements have cases, at what class depth, and
what was deliberately left uncovered. **A test matrix that claims completeness it does
not have is worse than a short one that names its gaps.**
