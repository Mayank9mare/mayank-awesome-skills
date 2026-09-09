# {{Feature}} — Requirements

> Digested {{YYYY-MM-DD}} from {{n}} sources by `requirements-digest`.
> **Status: {{n}} blocking open questions** — see §6 before building.
> Unmarked statements come from a source. `[INFERRED]` and `[ASSUMPTION]` do not.

## 1. Summary

{{Three sentences: what this feature does, for whom, and why now. No marketing.}}

## 2. Scope

**In scope**
- {{...}}

**Out of scope**
- {{...}} — *(source, or "not stated; confirmed out by {{who}}")*

Explicit exclusions matter more than inclusions; they are what prevents the argument in
week six.

## 3. Sources

| # | Kind | Ref | Version / Updated | Authority | Read |
|---|---|---|---|---|---|
| S1 | BRD | {{./docs/X-BRD-v2.3.docx}} | 2026-07-14 | high | full |
| S2 | PRD | {{ADO Wiki /specs/x, rev 18}} | 2026-08-02 | high | full |
| S3 | Epic +{{n}} stories | {{ADO #4412 tree}} | 2026-09-01 | medium | full |
| S4 | Comments | {{ADO #4418, #4421}} | 2026-09-03 | medium | full |
| S5 | Notes | {{./notes/x.md}} | 2026-08-28 | low | full |

Authority order applied: {{BRD > PRD > epic > story > comment > chat}}.
Expected but not found: {{...}}.

## 4. Glossary

Only terms that were ambiguous or contradictory across sources.

| Term | Meaning here | Note |
|---|---|---|
| {{Order}} | {{...}} | {{S1 uses "transaction" for the same thing}} |

## 5. Requirements

`must` = required for release · `should` = expected, negotiable · `could` = optional
Status: `agreed` · `disputed` (see conflicts) · `open` (see questions) · `removed`

### 5.1 Functional

| ID | Requirement (EARS) | Source | Pri | Status | Tests |
|---|---|---|---|---|---|
| R-001 | When {{trigger}}, the {{system}} shall {{response}}. | S2 §3.1, S3 #4418 | must | agreed | T-001, T-002 |
| R-002 | While {{state}}, the {{system}} shall {{response}}. | S1 §4.2 | must | agreed | T-003 |
| R-003 | If {{trigger}}, then the {{system}} shall {{response}}. | S4 | should | disputed (C-01) | T-004 |

### 5.2 Business rules

| ID | Requirement (EARS) | Source | Pri | Status | Tests |
|---|---|---|---|---|---|

### 5.3 Data

{{Retention, PII, audit, migration.}}

### 5.4 Non-functional

| ID | Requirement (EARS) | Source | Pri | Status | Tests |
|---|---|---|---|---|---|
| R-0nn | The {{system}} shall respond within {{n}}ms at p95 under {{load}}. | {{S?}} | | | |

*Any NFR with no source is an open question, not a guess.*

### 5.5 Operational

{{Flags, rollout, rollback, observability, alerting.}}

## 6. Conflicts & Open Questions

### Blocking

| ID | Issue | Side A | Side B | Recommendation | Owner |
|---|---|---|---|---|---|
| C-01 | {{Retention period}} | "{{30 days}}" — S1 §4.2 | "{{60 days}}" — S2 §3.4 | {{Take S1: signed BRD outranks PRD, and it cites the compliance rule}} | {{who}} |

| ID | Question | Blocks | Owner |
|---|---|---|---|
| Q-01 | {{Is £100 inclusive at the threshold?}} | R-004, T-011 | {{who}} |

### Non-blocking

| ID | Question | Affects | Owner |
|---|---|---|---|

Blocking = a test cannot be written, or a wrong build results, until it is answered.

## 7. Assumptions

| ID | Assumption | Why needed | Risk if wrong |
|---|---|---|---|
| A-01 | `[ASSUMPTION]` {{...}} | {{no source addresses it}} | {{what breaks}} |

## 8. Test Cases

Classes follow the `qa` skill's scenario catalog.

| ID | Case | Covers | Class | Pri |
|---|---|---|---|---|
| T-001 | {{...}} | R-001 | 1 happy | must |
| T-004 | {{...}} | R-003 | 2 negative | must |
| T-011 | {{...}} | R-004 | 9 data-edges | should |

Expanded cases for anything non-obvious:

### T-0nn — {{name}}
Covers: {{R-nnn}} · Class: {{n}} · Source: {{S? §?}}
Preconditions: {{...}}
Steps: {{...}}
Expected:
- {{observable outcome}}
- {{and the absence that must hold}}

**Coverage note:** {{techniques used — boundary values, decision table, pairwise — and
what was deliberately left uncovered.}}

## 9. Traceability

**Source → Requirements** *(a source with no requirements means it was not really read)*

| Source | Requirements |
|---|---|
| S1 | R-002, R-005… |

**Requirement → Tests** *(a requirement with no test is untestable — raise it as a question)*

| Requirement | Tests | Classes covered |
|---|---|---|
| R-001 | T-001, T-002 | 1, 2 |

**Requirement → Tickets** *(where work is tracked)*

| Requirement | Ticket |
|---|---|
| R-001 | ADO #4418 |

## 10. Not Covered

- {{Sources not read, or read partially — name the sections}}
- {{Areas deliberately excluded from this digest}}
- {{Anything blocked pending an answer above}}

---

### Review gate

| Gate | Result |
|---|---|
| Attribution — every requirement sourced or marked | {{PASS/FAIL}} |
| Atomicity — no compound requirements | {{}} |
| Testability — every requirement has a test, no smell words | {{}} |
| Traceability — every source yielded requirements | {{}} |
| Conflict closure — every blocking conflict has a recommendation and owner | {{}} |
| Coverage — every requirement has a negative case | {{}} |
| Scope — nothing in §5 that §2 excludes | {{}} |
