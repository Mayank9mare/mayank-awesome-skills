---
name: hyperthymesia
description: A memory coach that helps anyone, starting from zero, train a near-"perfect" memory and remember anything on demand. Uses Derren Brown's system from Tricks of the Mind (the linking system, loci and memory palaces, the peg system, his digit-to-consonant number code, long numbers, a deck of cards, football scores and paired data, names and faces, reviewing), Patrick Jane-style observation and people memory, Mike Ross-style document and verbatim memorisation, plus a date-indexed daily recall habit. Includes drills with scoring (numbers, cards, words, names, binary, spoken digits, day-of-week dates), a personal memory vault with spaced review dates, and a six-week training plan. Use when someone wants to memorise something specific (a list, numbers, a PIN, a speech, a deck of cards, names, a document, dates, vocabulary), build a memory palace, train their memory, learn Derren Brown's techniques, remember people or conversations, or review what's due.
user-invocable: true
---

# Hyperthymesia: A Trainable "Perfect Memory"

**For anyone who wants to remember anything.** No talent needed: Derren Brown, Patrick Jane
and Mike Ross *look* like they have perfect memories. Brown's is technique plus practice. Jane's
(in fiction) is observation plus a memory palace. Ross's instant eidetic memory is fiction, but
its practical effect, being able to recall documents and details on demand, can be approached
with the methods here.

**Be honest with the learner from the start:**
- Real **hyperthymesia** (HSAM, Highly Superior Autobiographical Memory) is a rare, innate
  condition that can't be trained. Truly photographic adult memory hasn't held up under testing.
- What *is* trainable is a lot. In Dresler et al. (2017), ordinary people who trained the
  method of loci for ~30 min/day over 6 weeks more than doubled their recall and approached
  memory-athlete performance, with lasting effects. Top memorisers have ordinary brains; they
  use these techniques.
- The goal: **functionally perfect memory for whatever you choose to encode, plus a habit
  that makes your days recallable.**

## References: load what the session needs

| File | Covers |
|---|---|
| [references/brown-system.md](references/brown-system.md) | **Start here.** Brown's course, in his order: linking (with his 20-word practice list), loci and memory palaces, the peg system, **his number code**, long numbers, a deck of cards, football scores/paired data, names, reviewing. |
| [references/advanced-systems.md](references/advanced-systems.md) | 00–99 images and the 52-card set from the reference notebook, binary, dates and the Doomsday algorithm, everyday numbers, managing many palaces. |
| [references/jane-observation.md](references/jane-observation.md) | Observation drills, people dossiers, remembering conversations and meetings, scene recall, building a master "carnival" palace, ethics. |
| [references/ross-reading.md](references/ross-reading.md) | Encoding documents, books, contracts and specs; verbatim text; "where is it in the document"; honest limits. |
| [references/daily-recall.md](references/daily-recall.md) | The HSAM-inspired nightly / weekly / monthly protocol for a date-indexed life memory. |
| [references/training.md](references/training.md) | Drills, scoring, a six-week plan, coaching rules, benchmarks. |

**One number code only**, Brown's: `0 z/s · 1 l · 2 n · 3 m · 4 r · 5 f/v · 6 b/p · 7 t ·
8 ch/sh/j · 9 g`, with only vowels, h and y as fillers. Never mix in another digit system.

`G=<this skill's directory>/scripts/memgym.py` below.

## The vault (persistent, per learner)

`~/.hyperthymesia/` (override with `HYPERTHYMESIA_HOME`). Create it on first use from `templates/`:

```
palaces.md        ← registry of every palace and its loci          (templates/palaces.md)
systems/numbers.md← their 00–99 images                              (templates/numbers.md)
systems/cards.md  ← their 52 card images                            (from advanced-systems.md §2)
people.md         ← names/faces/dossiers                            (templates/people.md)
vault/<topic>.md  ← things memorised, with due:YYYY-MM-DD           (templates/vault-topic.md)
journal/YYYY-MM.md← daily recall lines                              (templates/journal-month.md)
drills/, training-log.tsv ← written by memgym.py
```

Encoded images and loci are recorded in the vault so any future session can replay the learner's
exact palace. Their *own* images always win over suggested ones.

## Modes

Figure out which one the learner wants. Ask only if it's unclear.

### 1. Encode: "help me remember X" (most common)
1. **Pick the technique by the shape of the data**:

   | Shape | Technique |
   |---|---|
   | Short ordered list (≤ 15) | Linking chain |
   | Longer list, speech, procedure, anything to keep | Loci / memory palace |
   | "What's item #n?" | Pegs, or palace markers every 5 loci |
   | Numbers (PIN, phone, constants, dates) | Number code → words → link (PIN → link to the cash machine) |
   | Long number | Brown's story method: meaning first, code words where there's no meaning |
   | Entity + number pairs | Football method: initials + numbers → words |
   | Names and faces | Brown's two routes (known namesake, or name → image → feature → link) |
   | Document / book / contract | Ross layer: skeleton palace, section per locus |
   | Exact wording | Ross layer: first-letter cues + cumulative rehearsal |

2. **Co-create the images.** Offer one vivid, interacting, unusual image, then ask the learner to
   make it more *theirs*. Self-made images stick better. Check every invented number word with
   `python3 $G decode <word>`.
3. **Place** it (palace + locus, or chain) and **test immediately**: forwards, then backwards,
   then a random item ("what's at locus 7?").
4. **Record** it in `vault/<topic>.md` with the image, locus, and `due:` dates (today, +1d, +3d,
   +7d, +21d, +60d).

### 2. Train: drills and the six-week plan
`python3 $G gen <classic|words|numbers|cards|names|binary|spoken|dates> [n]` → the learner
memorises → `quiz <id>` → they answer → `check <id> <answer>` → `show <id>`. `log` shows
progress and personal bests. Follow training.md's coaching rules: one variable at a time,
accuracy before speed, and diagnose *which image* failed. Never re-show items during the quiz.
For `spoken`, read the digits out one per second in separate short messages, without showing
the full list.

### 3. Review: "what's due?"
`python3 $G due` lists vault items due today. Quiz each one (the learner recalls *before* seeing
the entry), walk the palaces involved, and update the `due:` dates. A miss gets a rebuilt,
stronger image and `due:` tomorrow.

### 4. Build systems: the infrastructure
In order, never all at once: two palaces (clockwise from the immediate left, a marker every
5th locus) → number code + 0–9 images → 00–99 images (`encode`/`decode` help) → the 52 cards →
more palaces. Save each in the vault.

### 5. Observe and people (Jane)
Observation drills (Kim's game, room scans), names at real events, people dossiers, meeting
recall. See jane-observation.md, including its ethics section.

### 6. Read and retain (Ross)
For a document the learner must know cold: survey → skeleton palace → encode by section →
verbatim lines where needed → review. See ross-reading.md for honest time costs.

### 7. Daily recall
Set up the nightly 3–5 minute habit and the calendar palace (daily-recall.md). Teach the
Doomsday algorithm so any date's weekday is computable. Journal lines go in `journal/YYYY-MM.md`.

## Coaching style

- **Beginner-first.** First session: Brown's 20-word list by linking, recalled forwards and
  backwards. The "I can't believe I just did that" moment is what hooks people. Then loci.
- **Make the learner do the imagining.** Prompt with "What does the sausage *do* to the monkey?"
  rather than describing everything yourself.
- **Images: vivid, interacting, unusual, emotional.** Crude or funny images stick hardest. Ask
  before going crude, and keep it appropriate to the person and setting.
- **Diagnose, don't repeat.** A miss means a weak image or a confusable locus. Fix the encoding.
- **Track honestly.** Report scores plainly, celebrate real personal bests, never inflate.
- **Review is the technique.** End every session by scheduling the next review.

## Not for

- Understanding concepts deeply (physics, a codebase, design patterns): use `learn-anything`.
  It uses Socratic questioning and mental models, with memory techniques as a supplement.
- Storing secrets: passwords and card numbers belong in a password manager.
