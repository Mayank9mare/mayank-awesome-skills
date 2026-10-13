# Retention: Retrieval, Spacing, Flashcards, Reviews

Dunlosky et al.'s (2013) review of ten study techniques rated two as **high utility**:
**practice testing** (retrieval) and **distributed practice** (spacing). Interleaving,
elaborative interrogation ("why is this true?") and self-explanation are moderate. Re-reading,
highlighting and summarising are low, and they're what most people do. This skill is built
around the top of that list.

## Retrieval practice

Pulling information *out* strengthens it far more than putting it back in. Rules:

- **Recall before review.** At the start of any return session, ask *before* showing notes.
- **Generate, don't recognise.** Prefer free recall and short answers to multiple choice.
- **Feedback right away.** After each answer, say what was right, what was wrong, and the
  correct version.
- **Mix question kinds.** Recall ("what is…"), application ("compute / predict…"),
  explanation ("why…"), discrimination ("X or Y here, and why?").
- **Interleave.** Mix chunks and problem types in a review, not blocks of the same kind.
  Interleaving teaches *which* tool to use, the skill blocked practice never trains.
- **Walk the palace.** For mnemonic material, recall = walking the route aloud, forwards and
  then backwards, or "what's at locus 7?".

## Spacing schedule

Expanding intervals. A simple, robust ladder (close to SuperMemo/Anki defaults, rounded):

| Review # | Due after previous success |
|---|---|
| 1 | 1 day |
| 2 | 3 days |
| 3 | 7 days |
| 4 | 16 days |
| 5 | 35 days |
| 6 | 90 days |
| then | ~2.5× the previous interval |

- **Failed item** → back to 1 day. Its image or model probably needs rebuilding, not just
  re-drilling.
- **Hard but correct** → repeat the same interval rather than advancing.
- Track this **per item** (per flashcard or palace segment), not per topic.

## Writing flashcards

Follow Wozniak's **minimum information principle**: each card tests one atomic fact.

| Bad | Good |
|---|---|
| "Explain the CAP theorem" | "In CAP, during a network partition you must choose between ___ and ___." |
| "What are the SOLID principles?" (5 answers) | 5 cards, one per letter, *plus* one palace walk |
| "What does `OrderService` do?" | "Which service publishes `OrderPlaced`?" · "What does `OrderService` do when payment times out?" |

Card types to mix:
- **Cloze**: "Momentum is conserved when net ___ is zero."
- **Reverse pairs**: term → meaning *and* meaning → term.
- **Why cards**: "Why does a Strategy object get injected rather than created inside?"
- **Prediction cards**: "This loop runs on a 1M-item list with `list.remove()` inside. Complexity?"
- **Contrast cards**: "Strategy vs State: who decides when to switch?"
- **Image cards**: "Locus 4 of the *Auth Palace* (kitchen sink): what's there, and what does it encode?"

Keep answers short enough to check at a glance. Avoid sets ("list all 7…") unless backed by a
palace. Offer to export cards as an Anki-importable CSV (`front,back,tags`) if the learner
uses Anki.

## Return sessions: the review protocol

When a learning log exists:

1. **Read the log.** Find due items (`next review ≤ today`) and open misconceptions.
2. **Cold recall first**: "Before I show anything: walk me through the model of X." One
   question at a time.
3. **Run due cards**, interleaved. Grade each: ✅ easy / 🟡 hard / ❌ fail. Update the dates.
4. **Re-test misconceptions** with a fresh disguise of the original trap.
5. **Walk the palaces** that are due.
6. **Only then** add new material. Keep new material to about a third of the session if the
   review was heavy.
7. **Update the log**: dates, grades, rebuilt images, new cards.

## Session design

- **Short and frequent beats long and rare.** Twenty minutes over four days beats eighty
  minutes in one.
- **End on retrieval**, not on explanation.
- **Sleep consolidates.** For heavy memorising, a review the next morning is high value.
- **Metacognition.** At the end, ask "what's still fuzzy?" and log the answer as the next
  session's first target. Confidence ratings before answers expose over-confidence.
