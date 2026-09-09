---
name: requirements-digest
description: Digest scattered requirements — an ADO wiki page and its work item tree, a PRD, a BRD, loose .md and .docx files, Confluence or Notion pages, ticket comments — into one precise requirements.md with EARS-formatted atomic requirements, surfaced conflicts and blocking open questions, derived test cases, and bidirectional traceability to every source. Also emits a ready-to-run qa task file. Use when requirements live in more than one place, before build or before QA, or when asked "what are we actually building" / "what do we need to test".
user-invocable: true
---

# Requirements Digest

Requirements are never in one place. A BRD says 30 days, the PRD says 60, and a comment
on an ADO ticket says "PM confirmed 45". The job is not to summarise all three — it is
to produce one document where each statement is atomic, testable, attributed to its
source, and where that contradiction is a **blocking open question**, not an average.

Two outputs:
- `requirements.md` — the digest (requirements, conflicts, tests, traceability)
- `qa/tasks/{feature}.md` — a task file for the `qa` skill, so requirements become
  executable E2E scenarios

## When to Use

- `/requirements-digest {feature}` — digest everything findable about a feature
- Before build: "what are we actually building here"
- Before QA: "what do we need to test"
- After a scope change: re-run to get a diff of what moved
- When onboarding onto a feature whose context is spread across a dozen artifacts

**Not for:** writing a PRD from scratch (use `to-prd`), designing the solution (use
`tech-design-doc`), or interrogating a plan you already hold in your head (use
`grill-me`). This skill reads what exists and reconciles it.

## Usage

```
/requirements-digest {feature}            — discover sources, digest, write both outputs
/requirements-digest {feature} sources    — discovery only: list what was found, ask what's missing
/requirements-digest {feature} conflicts  — conflicts and open questions only
/requirements-digest {feature} tests      — regenerate the test matrix from an existing requirements.md
/requirements-digest {feature} refresh    — re-run against updated sources, output a change diff
```

Flags: `--source {ref}` (add a source explicitly — repeatable), `--out {path}` (default
`docs/requirements/{feature}.md`), `--no-qa` (skip the qa task file), `--strict` (never
infer — every gap stays an open question).

## Architecture

```
SKILL.md                    ← the method (this file)
references/
  connectors.md             ← pulling from ADO, local files (.md/.docx/.pdf), Confluence, Jira, Notion, Drive, GitHub, URLs
  ears.md                   ← EARS syntax, requirement smells, the quality gate
  test-derivation.md        ← requirement → test cases, mechanically
templates/
  requirements.md           ← the output shape
examples/
  checkout-digest.md        ← a worked digest — the quality bar for an output
```

## Sources: Any Mix

Two things are orthogonal — **what a source is** and **where it lives**. One system
usually holds several sources: an ADO project alone contributes wiki pages, an epic, its
story tree, comments on each, revision history, and attachments. A source set is any
combination:

- ADO only — wiki page + work item tree + comments + attached spec
- ADO + loose files — the tickets plus a `PRD.docx` and three `.md` notes on disk
- No ticket system at all — a folder of documents and a Confluence space

| Source kind | Where it typically lives | Usually holds |
|---|---|---|
| BRD | `.docx`/`.pdf` on disk, Confluence, ADO Wiki | Business rules, SLAs, commercial constraints, compliance, "why" |
| PRD | ADO Wiki, Confluence, Notion, Google Docs, `.md` | User-facing behaviour, scope, success metrics, "what" |
| Epic / feature ticket | ADO Boards, Jira, GitHub, Linear | Scope boundaries, links to the children holding the detail |
| Story / task tickets | same | The real acceptance criteria, usually as a checklist |
| Ticket **comments** | same | Decisions that never made it back into the PRD — mine these hard |
| Ticket **revisions** | same | What changed and when; catches silent scope creep |
| Attachments | on the ticket or page | Spreadsheets of rules, mocks, partner API contracts |
| Design doc / RFC | `.md` in-repo, Confluence, Drive | Constraints, chosen approach, rejected options |
| Wiki page | ADO Wiki, Confluence | Glossary, process rules, existing behaviour |
| Mocks | Figma, images in a doc | States the text omits — empty, error, loading, truncation |
| Threads | Slack, email, ticket discussion | Verbal decisions — lowest authority, but they explain conflicts |
| The code | the repo | What it actually does today, when a requirement says "as today" |

`references/connectors.md` has the retrieval commands per system, including reading
`.docx`, `.pdf` and `.xlsx` off disk — none of which `cat` can open.

## The Non-Negotiable Rule

**Every line in the output traces to a source, or is explicitly marked.**

| Marker | Meaning |
|---|---|
| *(none)* | Stated in a source. The source ref is mandatory. |
| `[INFERRED]` | Follows logically from sources but nobody wrote it. Must also appear as an open question. |
| `[ASSUMPTION]` | Filled a gap to keep the document usable. Must also appear in Assumptions with its risk. |

Never write an unmarked requirement that no source states. A digest that quietly invents
requirements is worse than the scattered sources it replaced, because it looks
authoritative. Under `--strict`, `[ASSUMPTION]` is not allowed — gaps stay gaps.

## Step 1: Discover Sources

Ask the user what they have, then go looking for what they forgot. Cast wide before
narrowing — the ticket nobody mentioned usually has the real acceptance criteria in a
comment, and the `.docx` nobody opened has the business rules.

Enumerate exhaustively per connector: for a ticket tree, walk epic → features → stories
→ tasks → bugs plus every `Related`/`Duplicate`/`Blocks` link; for a wiki, the page *and
its children*; for a folder, every document, not just the ones with obvious names.
`references/connectors.md` has the WIQL/JQL and file-discovery recipes.

Report what you found and what you expected but did not find, then confirm before
continuing:

```
## Sources for {feature}
| # | Kind | Ref | Version / Updated | Authority |
|---|---|---|---|---|
| S1 | BRD | ./docs/Payments-BRD-v2.3.docx | 2026-07-14 | high |
| S2 | PRD | ADO Wiki /specs/checkout (rev 18) | 2026-08-02 | high |
| S3 | Epic + 9 stories | ADO #4412 tree | 2026-09-01 | medium |
| S4 | Comments | ADO #4418, #4421 | 2026-09-03 | medium |
| S5 | Notes | ./notes/checkout-sync.md | 2026-08-28 | low |

Expected but not found: NFR/perf targets, error-message copy, analytics events.
```

**Authority order** must be declared, because it decides what a conflict defaults to.
Default, overridable per project: signed BRD > PRD > epic > story > comment > chat.
**Recency beats authority only when the later source explicitly supersedes the earlier
one** — otherwise it is a conflict, not an update.

## Step 2: Extract Atomic Requirements

### Reading order

Order matters. Read for the **frame** first, then the detail, or you will not recognise
what is significant when you meet it.

1. **BRD / business sources** — the constraints and the "why". Establishes what is
   non-negotiable and where the compliance edges are.
2. **PRD / spec** — the intended behaviour, and the vocabulary the rest will use.
3. **Epic / feature ticket** — the scope boundary as the team actually agreed it.
4. **Stories and tasks** — the concrete acceptance criteria.
5. **Comments and revisions** — the amendments. Read these *last*, against everything
   above, because their whole value is contradicting it.
6. **Code** — only when a source says "as today" and you must find out what today is.

A decision found in a comment at step 5 that contradicts step 2 is the single most
valuable thing this skill produces. You cannot spot it if you read the comments first.

### Working at scale

An epic with sixty descendants will not fit in one pass. Do not skim to compensate —
skimming loses acceptance criteria, which is the only part that matters. Stage it:

1. **Enumerate first, read second.** Get the full source list (ids, titles, types) in one
   query so you know the denominator before spending context on any single item.
2. **Extract per source into a working file**, not into context. After reading each
   source, append its extracted requirements to a scratch file — one block per source
   with `S{n}`, the verbatim quotes, and draft requirement text. Then move on. Use the
   session scratchpad directory, not the repo.
3. **Never re-read a source.** The working file is the record. If something is missing
   from it, that is a note to re-read *that one source*, not all of them.
4. **Merge and deduplicate at the end**, from the working file — this is where the same
   rule stated in three sources collapses into one `R-nnn` with three refs, and where
   near-duplicates surface as conflicts.
5. **Report progress** as you go for large sets (`read 23/61`), so an interrupted run can
   be resumed rather than restarted.

Batch retrieval where the connector allows it (`wit_work_item get_batch`, `jira_search`
with fields) — but batch the *fetch*, never the *reading*. Ten tickets fetched at once
still need ten careful reads.

### Extracting

Read every source in full. Do not skim to a summary — acceptance criteria hide in
checklists, table cells, screenshot captions, spreadsheet rows and comment threads.

For each statement of required behaviour, emit one **atomic** requirement:

- **One requirement, one behaviour.** "The system shall validate the address and send a
  confirmation email" is two. Split on every "and", "also", "as well as".
- **Rewrite into EARS** — see `references/ears.md`. The six patterns (`ubiquitous`,
  `While`, `When`, `Where`, `If-Then`, complex) force a single reading and make the test
  cases fall out mechanically.
- **Strip the smells.** "fast", "intuitive", "seamless", "robust", "as appropriate",
  "etc.", "should be able to" — each becomes either a measurable value from a source, or
  an open question. Never silently pick a number.
- **Deduplicate across sources.** The same rule in the BRD, the PRD and a ticket is *one*
  requirement with three source refs. Near-duplicates that differ in detail are a
  conflict, not a duplicate.
- **Assign a stable ID.** `R-001`, `R-002`… IDs are permanent. On `refresh` an existing
  requirement keeps its ID even if reworded; a removed one becomes `status: removed`
  rather than vanishing, so downstream test and ticket references never dangle.

Classify each: `functional` | `business-rule` | `data` | `nfr` | `ux` | `compliance` |
`operational`, with `priority` (must/should/could, from the source) and `status`
(agreed / disputed / open / removed).

## Step 3: Detect Conflicts and Gaps

The step that justifies the document. Run every check; report everything found.

**Conflicts** — two sources cannot both be satisfied:

| Kind | What to look for |
|---|---|
| Value | Different numbers for the same thing (30 vs 60 days, 3 vs 5 retries) |
| Behavioural | Different outcomes for the same trigger |
| Scope | One source includes what another excludes |
| Terminology | Same word, two meanings — or two words, one meaning |
| Temporal | A later source contradicts an earlier one without saying it supersedes it |
| Silent | A ticket comment decided something the PRD still contradicts |

Each gets `C-01`, both sides quoted **verbatim** with source refs, an authority-based
recommendation, and a **blocking** flag — blocking if you cannot write a test without
resolving it.

**Gaps** — a standing checklist, because the gap nobody notices is the one no source
mentions at all:

- Every trigger: what happens on the unhappy path? (each `When` needs an `If-Then`)
- Every input: validation rules, limits, required vs optional
- Every state: who may transition it, and what is forbidden
- Every list: pagination, ordering, empty state
- Every external call: timeout, retry, failure behaviour
- Every write: idempotency, concurrency, ordering
- Permissions: which roles, and cross-tenant behaviour
- Data: retention, PII handling, audit trail
- NFRs: latency, throughput, availability targets
- Migration: what happens to data and flows that exist today
- Rollout: flag, staged, rollback — and behaviour with the flag off
- Observability: what must be logged, alerted, measured

Each gap becomes `Q-01` with the question, who can answer it, and what it blocks. A gap
you filled anyway is an `[ASSUMPTION]`, listed with its risk.

## Step 4: Derive Test Cases

Every requirement gets at least one test case, or it is not verifiable and goes back to
Step 3 as an open question. That rule is why requirements are written in EARS: each
pattern maps to a specific set of cases.

| EARS clause | Test cases it demands |
|---|---|
| `When <trigger>` | Trigger fires → response; trigger absent → no response |
| `While <state>` | In state → behaviour; out of state → different behaviour; transition boundary |
| `If <trigger> then` | The unwanted condition, handled; and that no side effect leaked |
| `Where <feature>` | Feature on; feature off; toggled mid-flight |
| Any value or range | min−1, min, max, max+1, and one typical |
| Any enumeration | Each value, plus an unknown value |

Then apply the design techniques — equivalence partitioning, boundary values, decision
tables for rule combinations, state-transition for lifecycles, pairwise where the
combinatorics explode — and tag each case with a class from the `qa` skill's
`references/scenario-catalog.md` (happy / negative / authz / idempotency / races /
timeouts / failure / lifecycle / data-edges) so the two skills line up. Details in
`references/test-derivation.md`.

Each case: `T-001`, the requirement(s) it covers, class, priority, preconditions, steps,
expected result — precise enough for someone who never read the sources to run it.

## Step 5: Write the Outputs

### `requirements.md`

From `templates/requirements.md`; `examples/checkout-digest.md` is a worked output at
the expected quality bar. Section order is deliberate: a reader who stops after
two minutes should have hit the scope and the blocking questions.

1. **Summary** — the feature in three sentences
2. **Scope** — in / out, both explicit. "Out" prevents the argument later.
3. **Sources** — the Step 1 table, with versions
4. **Glossary** — only terms whose meaning was ambiguous across sources
5. **Requirements** — `R-nnn`, EARS, source refs, priority, status
6. **Conflicts & Open Questions** — blocking first, with owners
7. **Assumptions** — each with its risk if wrong
8. **Test Cases** — `T-nnn`, grouped by class
9. **Traceability** — `source → R → T`, both directions
10. **Not Covered** — what this document deliberately does not answer

Keep it dense. Tables over prose, no restating the PRD's narrative, no paragraph that
does not change what someone builds or tests. A digest longer than the sum of its
sources has failed.

### `qa/tasks/{feature}.md`

Pre-fill the `qa` skill's task file from what the digest already established:

- **Feature Model** — entry points, external effects, wait points, states, concurrency
  surface all fall out of the requirements
- **Invariants** — from business rules and every exactly-once effect
- **Scenarios** — the `T-nnn` cases grouped into the nine classes, each carrying its
  `R-nnn` back-reference

Leave environment, adapters and action templates as `{{TODO}}` — those are stack facts
this skill cannot know. Say so in the handoff rather than inventing hosts.

## Step 6: Review Gate

Check the document against itself before handing it over:

| Gate | Fails if |
|---|---|
| Attribution | Any unmarked requirement without a source ref |
| Atomicity | Any requirement whose "and" joins two behaviours |
| Testability | Any requirement with no `T-nnn`, or containing a smell word |
| Traceability | Any source with zero extracted requirements (did you actually read it?) |
| Conflict closure | Any blocking conflict without a recommendation and an owner |
| Coverage | Any requirement with no negative test case |
| Scope | Anything in Requirements that Scope says is out |

Report the gate results with the document, then state plainly what is still blocked and
who must answer it. The value of this document is as much in its open questions as in
its requirements.

## Refresh and Drift

`refresh` re-reads the sources and reports a **diff**, not a new document: requirements
added, reworded, removed, newly conflicting; test cases now orphaned; open questions
since answered. IDs are stable across refreshes, so a ticket or test plan referencing
`R-014` keeps pointing at the same thing.

Record the source versions you digested. Without them a refresh cannot tell what changed,
and the document silently rots.

The diff is the output — lead with it, and only rewrite the document underneath:

```
## Refresh: {feature} — 2026-09-10 (last digested 2026-08-14)

Sources changed: S2 rev 18 → rev 24, S3 +3 stories, S1 unchanged.

### Added
- R-021  When a partial refund is requested, the checkout service shall …  [S3 #4470]

### Reworded (same intent, ID kept)
- R-008  "within 30 seconds" → "within 15 seconds"  [S2 §3.4 rev 24]
         ⚠ T-014 asserts 30s and is now wrong.

### Removed
- R-013  status: removed — dropped from scope in S2 rev 22.
         ⚠ ADO #4431 still implements it. T-009, T-010 now orphaned.

### Newly conflicting
- C-04   R-008 (15s) vs S1 §4.2 (30s SLA) — BLOCKING.

### Questions since answered
- Q-02   Resolved in S3 #4470 comment: £100 threshold is inclusive. → R-004 updated.

### Still blocking: C-01, C-04
```

Flag every downstream consequence — a reworded requirement whose test now asserts the old
value, an orphaned test, a removed requirement someone is still building. Those are the
findings; the rewritten document is just bookkeeping.

## Writing Back to Sources

The open questions are worth more in the tracker than in a file nobody opens. Offer to
push them back — **always ask first, and show the exact text before posting**:

- Post each blocking `Q-nn` as a comment on the ticket it blocks, or on the epic when it
  spans several
- Raise a ticket per unresolved conflict, tagged for the owner you identified
- Attach or link the digest to the epic so the team reads one document
- Update a ticket's acceptance criteria field with the EARS rewrite — **only** on explicit
  per-ticket approval, since it overwrites someone else's words

Never write to a source without permission, never edit a source document in place, and
never close or re-scope a ticket. This skill reads and reconciles; changing the sources is
the team's call, and a digest that silently rewrote its own inputs would destroy the
traceability that makes it trustworthy.

## Degenerate Cases

| Situation | Do this |
|---|---|
| One source only | Still worth running — the value shifts entirely to smells, gaps and untestable statements. Say plainly that no cross-source conflicts were possible. |
| No written sources, only a conversation | Stop and say so. Use `to-prd` or `grill-me` to create a source first; there is nothing to digest. |
| Sources disagree on priority | The conflict is the finding. Record the highest priority claimed, mark `disputed`, and name both sources. |
| A source is unreadable (locked, binary, dead link) | List it in Sources with `read: failed` and in "Not Covered". Never imply it was digested. |
| Sources are stale (nothing updated in months) | Flag it prominently — a digest of an abandoned spec looks authoritative and is not. Ask what supersedes it. |
| Requirements written as solutions ("add a Kafka topic") | Extract the behaviour behind it and log the mechanism as a constraint with its source. |

## Related Skills

| Skill | Relationship |
|---|---|
| `qa` | Consumes the emitted task file; shares the nine scenario classes |
| `atlassian` | Connector for Jira issues and Confluence pages |
| `ubiquitous-language` | Use when the glossary reveals real terminology conflict |
| `grill-me` | Use on the open questions when the stakeholder is available |
| `tech-design-doc` | Downstream — designs the solution to these requirements |
| `to-prd` | Upstream — writes a PRD when there is none to digest |
