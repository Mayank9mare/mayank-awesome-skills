# {Feature} — Review Guide

**Branch:** `{feature/branch}` → `{main}` · **Diff:** {+N / −M} lines across {K} files ·
**Tests:** {count} passing · **Updated:** {YYYY-MM-DD}

## TL;DR (read this first)

{3–5 plain-English sentences. What the feature does, the shape of the change, and the one thing
you most need to look at. Example: "Adds a V2 order flow behind `orders.v2.enabled`. A new
controller endpoint writes a PENDING order and publishes an event; a new worker calls the
partner. V1 is untouched. The riskiest part is the after-commit event publish in step 3."}

## How to review in ~{N} minutes

Read the files **in this order**. It follows the request through the system, so each file only
uses things you've already seen. ⭐ = spend most of your time here.

| # | File | What it does (simple words) | What to check | Size |
|---|---|---|---|---|
| 1 | [V12__orders.sql](../../src/main/resources/db/migration/V12__orders.sql) | Creates the `orders` table | Indexes, nullability, unique key | +30 |
| 2 | [OrderStatus.java](../../src/.../OrderStatus.java) | The statuses an order can be in | Matches flow.md state machine | +15 |
| 3 ⭐ | [OrderManager.java](../../src/.../OrderManager.java) | The brain: validates, prices, saves, publishes | Transaction boundary (L60–90); idempotency (L64) | +140 |
| 4 | [OrderController.java](../../src/.../OrderController.java) | HTTP door into the feature | Status codes match flow.md exits | +60 |
| 5 | [OrderWorker.java](../../src/.../OrderWorker.java) | Background job that calls the partner | What happens on exception | +80 |
| 6 | [OrderManagerTest.java](../../src/test/.../OrderManagerTest.java) | Tests for #3 | Error paths covered, not just happy path | +210 |

Skip or skim: {generated files, renames, trivial DTOs: list them so the reviewer doesn't waste time}.

## The change, file by file

### 3. [OrderManager.java](../../src/.../OrderManager.java) ⭐

**In simple words:** {what this file does, as you'd explain it to a teammate.}

**Why it's built this way:** {link the decisions: see [D2](decision.md#d2-...), [D4](decision.md#d4-...).}

**Look closely at:**
- [L60–L90](../../src/.../OrderManager.java#L60-L90): everything here is one transaction; the event is published *after* commit.
- [L64](../../src/.../OrderManager.java#L64): idempotency check. What if two requests race?

```java
// the 5–15 most important lines, if they help
```

- [ ] **VERIFY** {a correctness point the reviewer must confirm}
- [ ] **QUESTION** {a design point open for discussion}

## How the pieces connect

See [flow.md](flow.md) for the full entrypoint → exit walk and diagrams.

## Things to decide together

Decisions marked *Proposed* in [decision.md](decision.md) that need your call:
- [D6](decision.md#d6-...): {one line}

## Known issues

Open bugs from [bugs.md](bugs.md):

| ID | Severity | One line | Blocks merge? |
|---|---|---|---|
| B3 | MEDIUM | Poison message leaves order PENDING | No (follow-up) |

## How to verify locally

```bash
{exact commands: build, run tests, start app, curl the endpoint}
```
