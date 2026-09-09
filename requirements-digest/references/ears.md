# EARS and the Quality Gate

EARS — Easy Approach to Requirements Syntax (Mavin et al., Rolls-Royce, IEEE RE'09) —
constrains a requirement to a fixed clause order and a handful of keywords. Two payoffs:
a sentence has one reading, and the test cases fall out of the clauses mechanically.

Rule of composition: **zero or many preconditions, zero or one trigger, one system name,
one or many responses.**

---

## The six patterns

### Ubiquitous — always true
```
The <system> shall <response>.
```
> The checkout service shall record an audit entry for every state change.

No keyword. If you are tempted to write "always" or "at all times", you have written a
ubiquitous requirement; drop the adverb.

### State-driven — true while a condition holds
```
While <precondition>, the <system> shall <response>.
```
> While the order is in AWAITING_PAYMENT, the checkout service shall reject modification
> requests with 409.

Tests: in-state, out-of-state, and both transition boundaries.

### Event-driven — triggered by something happening
```
When <trigger>, the <system> shall <response>.
```
> When a payment.captured event is received, the checkout service shall transition the
> order to CAPTURED.

The most common pattern, and the most common source of gaps: **every `When` needs a
matching `If-Then`** for the case where the trigger arrives wrongly, twice, late, or not
at all.

### Optional feature — true only where a feature exists
```
Where <feature is included>, the <system> shall <response>.
```
> Where express delivery is enabled for the tenant, the checkout service shall offer the
> next-day option.

Tests: on, off, and toggled mid-flight. The "off" case is the one that ships broken.

### Unwanted behaviour — the undesired situation
```
If <trigger>, then the <system> shall <response>.
```
> If the payment partner does not respond within 15 seconds, then the checkout service
> shall fail the order with reason PARTNER_TIMEOUT and release the reservation.

Where most missing requirements live. Sources describe the happy path; the `If-Then`
requirements are what you must go and ask for.

### Complex — combined, in this clause order
```
While <precondition>, when <trigger>, the <system> shall <response>.
```
> While the order is in AWAITING_PAYMENT, when a cancel request is received, the checkout
> service shall transition the order to CANCELLED and release the reservation.

Clause order is not stylistic — it encodes the temporal logic. Preconditions precede
triggers, always.

---

## Rewriting into EARS

| Original | Problem | Rewritten |
|---|---|---|
| "Orders should be processed quickly." | No trigger, no measure, no system | `When an order is submitted, the checkout service shall return a response within 500ms at p95.` [value needs a source] |
| "The system handles payment failures gracefully." | "Gracefully" is untestable | `If the payment partner returns a decline, then the checkout service shall set the order to FAILED and notify the customer within 1 minute.` |
| "Users can cancel their orders." | Which users, which states? | `While the order is in CREATED or AWAITING_PAYMENT, when the owning customer requests cancellation, the checkout service shall transition the order to CANCELLED.` |
| "Validate the address and send a confirmation." | Two behaviours | Two requirements, one each. |
| "Support up to 1000 concurrent users." | Support meaning what? | `The checkout service shall sustain 1000 concurrent checkout sessions at p95 latency under 800ms.` |

Rewriting rules:
1. Name a **specific** system or component, never "the system" if a component is meant.
2. Use **shall** for requirements. "Should"/"may" mean optional — if a source used them,
   record the priority as `should`/`could`, do not promote it to `shall` silently.
3. **Active voice with a named actor.** "The order is cancelled" hides who cancels it.
4. One response per clause unless the responses are genuinely atomic together.
5. Keep the source's own domain terms. Renaming them breaks traceability and starts a
   terminology conflict — if the sources disagree on a term, that belongs in the glossary.

---

## Requirement smells

Every one of these must be resolved to a value from a source, or raised as an open
question. **Never invent the number.**

**Vague qualities:** fast, quick, slow, efficient, scalable, robust, reliable, secure,
intuitive, user-friendly, seamless, smooth, simple, clean, modern, appropriate, adequate,
reasonable, sufficient, optimal, best, minimal, flexible

**Unbounded quantities:** many, few, several, some, most, large, small, high, low,
frequent, occasional, significant, normal, typical, usually, generally

**Escape hatches:** etc., and so on, and/or, as needed, as appropriate, if necessary,
where possible, to be determined, TBD, similar to, based on, handled accordingly

**Weak modality:** should be able to, could, might, may want to, ideally, preferably,
try to, aim to, support, handle, manage, process, deal with

**Ambiguous scope:** all, any, every, none — when the set is not defined; "the user"
when there are several roles; "the data" when there are several entities

**Hidden compounds:** and, also, as well as, in addition, plus, along with — each usually
joins two requirements

**Unverifiable comparatives:** better, faster, improved, enhanced, more, less, reduced —
than what, measured how?

A useful test for any candidate requirement: *could two competent engineers build
different things from this sentence and both be right?* If yes, it is not a requirement
yet.

---

## Quality gate

Per requirement:

| Check | Fails if |
|---|---|
| Atomic | Contains a hidden compound — two behaviours in one line |
| Unambiguous | Contains a smell word, or admits two readings |
| Testable | No observable outcome, or no `T-nnn` derived from it |
| Traceable | No source ref, and not marked `[INFERRED]`/`[ASSUMPTION]` |
| Necessary | Nothing breaks if removed — then it is not a requirement |
| Implementation-free | Names a mechanism where a behaviour was meant (see below) |
| Consistent | Contradicts another requirement without being logged as a conflict |
| Bounded | A value with no unit, or a range with no ends |

**Implementation-free** is worth care: "the service shall store orders in PostgreSQL" is
a design decision, not a requirement, unless a source states it as a constraint. If a
source *does* mandate it, keep it and classify it `operational` with its rationale — a
constraint is a legitimate requirement; an assumed mechanism is not.

Across the whole set:

| Check | Fails if |
|---|---|
| Complete | A trigger has no unwanted-behaviour counterpart |
| Non-overlapping | Two requirements cover the same behaviour (merge them) |
| Consistent terminology | The same concept has two names, or one name covers two concepts |
| Prioritised | Any `must` that no source justifies as a must |
| Bounded set | Requirements that describe a different feature — move them out of scope |

---

## INVEST, for requirements that will become tickets

When the digest feeds a backlog, check each requirement is **I**ndependent,
**N**egotiable, **V**aluable, **E**stimable, **S**mall, **T**estable. EARS gives you
Testable and mostly Small; the rest is judgement. Requirements that fail Estimable are
usually hiding an open question — surface it rather than splitting the requirement to
look tidy.
