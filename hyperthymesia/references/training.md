# Training Program

The evidence: in Dresler et al. (2017, *Neuron*), people with no mnemonic experience trained in
the method of loci for 30 minutes a day over ~6 weeks (40 days). Their word-list recall more than
doubled, approached that of memory athletes, and largely held four months later. Maguire et al.
(2003) found that top memorisers have ordinary brain structure and ordinary intelligence; what
sets them apart is that they use spatial (loci) strategies. **Superior memory is a trained
skill.**

## The drills (`scripts/memgym.py`)

| Drill | Command | Trains | Format |
|---|---|---|---|
| Classic list | `gen classic` | Brown's 20-word linking exercise (do this first) | Recall in order, then backwards |
| Numbers | `gen numbers 40` | 00–99 images, speed | Memorise digits, then recall in order |
| Binary | `gen binary 60` | Binary → octal → images | Same |
| Cards | `gen cards 52` | Card system + palace | Recall order, e.g. `KS 10H 3D` |
| Words | `gen words 20` | Linking / loci with concrete nouns | Recall in order |
| Names | `gen names 10` | Names ↔ faces/features (Jane) | Cued recall: "the pilot with freckles" |
| Spoken numbers | `gen spoken 20` | Encoding at a forced pace | Claude reads one digit per second; you can't re-read |
| Dates | `gen dates 10` | Doomsday algorithm | Weekday for each date, timed |

Flow: `gen` → you memorise while timing yourself → `quiz <id>` → you answer → `check <id> <answer>`
→ `show <id>` for the full key. `log` shows history and personal bests (the largest perfect drill
per type). Scoring reports total correct **and** the perfect run from the start; competitions
score the run, because one error breaks a chain.

Honour system: the items stay in terminal scrollback, so clear or scroll the screen before
recalling. Claude should never repeat the items while quizzing.

## Six-week plan (~30 min/day)

| Week | Focus | Daily |
|---|---|---|
| 1 | Foundations | Brown's classic 20-word list by linking (day 1), then by loci. Build 2 palaces (20 loci each, clockwise from the immediate left, a marker every 5). Learn the number code and 0–9 images, then 10–49. Names drill ×1. |
| 2 | Numbers | Finish 00–99 (check each new word with `decode`); drill both directions. Brown's long-number story method on a 20-digit number. Numbers drill (20 → 40). Words 20–30. Start nightly daily-recall. |
| 3 | Cards | Learn the 52 card images (13/day + review). Cards drill 13 → 26. Doomsday: learn the method, 5 dates/day. |
| 4 | Speed | Timed drills. Numbers 40 under 5 min; cards 52 untimed → timed. Build 2 more palaces. |
| 5 | Real life | Encode one real thing per day (a document section, a meeting, a list). Names at real events. |
| 6 | Consolidate | Mixed drills; review every vault item; test a 4-week-old palace cold. Set personal targets. |

After six weeks: 10–15 minutes daily keeps it sharp. Memory sports (e.g. Memory League
formats) are a good motivator for anyone who enjoys competing.

## Coaching rules (for Claude)

- **One variable at a time.** Increase the count *or* reduce the time, never both.
- **Accuracy before speed.** Only speed up once a drill is ≥ 95% at the current size.
- **Diagnose misses.** After `check`, ask *which image* failed: was it weak (rebuild it), placed
  at a bad locus (fix the palace), or never formed (slow down)? Log patterns in the training log.
- **Track both kinds of error**: forgotten items (encoding failure) and transposed items (loci
  too similar → make loci more distinct).
- **Celebrate personal bests, factually.** "40-digit perfect run, up from 24 last week."
- **Rest matters.** Sleep consolidates. Hard drills before bed, review in the morning.

## Benchmarks (rough, for orientation)

| Level | Numbers in 5 min | Shuffled deck | Words in 5 min |
|---|---|---|---|
| Untrained | ~10–15 digits (span ~7) | — | ~10–15 |
| After 6 weeks | 40–80 | Full deck in 5–15 min | 30–50 |
| Serious hobbyist | 150+ | Under 2 min | 60+ |
| World class | Hundreds | Under ~20 s | 100+ |

Compare against yourself, not the world. The log is the scoreboard.
