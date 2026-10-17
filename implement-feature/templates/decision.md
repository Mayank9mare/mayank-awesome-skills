# {Feature} — Decisions

Every non-trivial choice made while building this feature: what was chosen, what was rejected,
and what we're trading away. Newest at the bottom. Decisions are never deleted. A reversed
decision is marked **Superseded by Dn** and a new entry explains why.

## Index

| ID | Decision | Status | Date |
|---|---|---|---|
| D1 | {one-line summary} | Accepted | {YYYY-MM-DD} |
| ~~D2~~ | ~~{summary}~~ | Superseded by D5 | {YYYY-MM-DD} |

---

## D1. {Decision title, phrased as the choice made}

**Status:** Accepted | Proposed (needs your call) | Superseded by D{n}
**Date:** {YYYY-MM-DD} · **Step:** {step number / phase}
**Decided by:** Claude (default) | You | Spec

### Context
{The problem in 2–4 sentences. What forced a choice here? What constraints apply: existing
conventions, deadlines, performance, team ownership?}

### Options considered

| Option | Pros | Cons |
|---|---|---|
| **A. {chosen}** | {pro}; {pro} | {con} |
| B. {alternative} | {pro} | {con}; {con} |
| C. {alternative} | {pro} | {con} |

### Decision
{Option A, and the one-sentence reason it wins.}

### Trade-offs accepted
- {What we give up by not choosing B/C, stated plainly, e.g. "an extra DB read per request
  (~2ms) in exchange for no cache-invalidation logic".}

### Consequences
- **Code:** {files/modules this shapes, as links: [OrderManager.java](../../src/.../OrderManager.java)}
- **Ops / config:** {new flags, queues, migrations, if any}
- **Follow-ups:** {anything this defers}

### Revisit if
{The condition that would make this the wrong choice, e.g. "traffic > 1k rps",
"partner adds webhooks", "we need multi-region".}
