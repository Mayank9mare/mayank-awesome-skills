# {Feature} — Bugs

Every bug found while building this feature: during coding, tests, review passes, or by you.
Fixed bugs stay here (struck through) as an audit trail. IDs never get reused.

## Summary

| ID | Severity | Bug | Status | Found | Fixed in |
|---|---|---|---|---|---|
| B1 | HIGH | {one line} | 🔴 OPEN | step 4 · test | — |
| ~~B2~~ | ~~MEDIUM~~ | ~~{one line}~~ | ✅ FIXED | review pass 1 | step 6 |
| B3 | LOW | {one line} | ⏸️ DEFERRED | you | follow-up ticket {link} |
| B4 | LOW | {one line} | 🚫 WON'T FIX | step 7 | — (see D7) |

Severity: **HIGH** = data loss, wrong result, security, blocks testing/release · **MEDIUM** =
breaks an edge case or error path · **LOW** = minor or cosmetic.

---

## 🔴 Open

### B1. {Title: the symptom, not the cause}

- **Severity:** HIGH · **Found:** {YYYY-MM-DD}, step {N}, by {test / review / you / runtime}
- **Where:** [OrderWorker.java#L52](../../src/.../OrderWorker.java#L52)
- **Symptom:** {What goes wrong, observable from outside}
- **Repro:** {Minimal steps, input, or failing test name}
- **Root cause:** {Why. Or "unknown, investigating: {hypotheses}"}
- **Proposed fix:** {Concrete change}
- **Flow impact:** {Which exit in flow.md is affected, e.g. X5}

---

## ✅ Fixed

### ~~B2. {Title}~~

- **Severity:** MEDIUM · **Found:** {date}, review pass 1 · **Fixed:** {date}, step {N}
- **Where:** [OrderManager.java#L64](../../src/.../OrderManager.java#L64)
- **Root cause:** {one or two lines}
- **Fix:** {what changed}, in [OrderManager.java#L64-L70](../../src/.../OrderManager.java#L64-L70)
- **Regression test:** [OrderManagerTest#shouldReturnExistingWhenSameIdempotencyKey](../../src/test/.../OrderManagerTest.java#L120)

---

## ⏸️ Deferred / 🚫 Won't fix

### B3. {Title}
- **Why not now:** {reason, plus a link to a decision or ticket}
