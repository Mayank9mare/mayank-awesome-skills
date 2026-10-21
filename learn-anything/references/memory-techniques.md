# Memory Techniques

Mnemonics are for **arbitrary** information, things that can't be derived from a model: names,
numbers, orders, exact formula shapes, which service sits behind which queue.

**The memory system lives in the `hyperthymesia` skill** (Derren Brown's *Tricks of the Mind*
method, built from the reference notebook). Use it for every technique below; don't teach a
second version here. If that skill isn't installed, its files are in the same repo under
`hyperthymesia/references/`.

## The method, in one screen

**Three rules for every picture** (Brown): **vivid and emotionally engaging**, the elements
**interact**, and it's **unusual, not normal**. Abstract things become concrete by sound or
symbol first (a name becomes an object: Mike → microphone).

| Shape of the data | Technique (see `hyperthymesia/references/brown-system.md`) |
|---|---|
| Short ordered list | **Linking**: each item interacts with the next |
| Long list, steps, a talk, a hierarchy | **Loci / memory palace**: clockwise from your immediate left, a marker every 5th locus |
| "What's item #n?" | **Pegs**: 1 bun · 2 shoe · 3 tree · 4 door · 5 hive · 6 sticks · 7 heaven · 8 gate · 9 line · 10 hen, or palace markers |
| Numbers, dates, constants, ports, PINs | **Brown's number code**: 0 z/s · 1 l · 2 n · 3 m · 4 r · 5 f/v · 6 b/p · 7 t · 8 ch/sh/j · 9 g, fillers vowels/h/y only, with the fixed 00–99 images in `hyperthymesia/references/advanced-systems.md` |
| Long numbers | Brown's story method: meaning first, code words where there's none |
| Term ↔ meaning, name ↔ face, foreign word ↔ translation | Brown's names method: turn the term into a picture, then link it to the meaning or feature |
| Paired data (entity + number) | Brown's football method: initials + number code → one scene |

Check any invented number word with `python3 <hyperthymesia>/scripts/memgym.py decode <word>`.
Record palaces and images in the learning log so a later session can replay them.

## Only in this skill (not in the notes, no overlap)

### Formulas: derive before you memorise
1. **Derive it.** If it can be rebuilt from a model in under 30 seconds (kinematics from the
   definition of acceleration, the quadratic formula by completing the square), teach the
   derivation and drill *that*.
2. **Check the units.** Dimensional analysis catches most misremembered formulas.
3. Only what's left gets a picture, placed in a palace with Brown's method.

### Acronyms and acrostics
Fast and good enough for short fixed lists (SOLID, ACID, OSI layers). They're weak for long
lists or anything that needs meaning. If you use one, make the sentence vivid and picture it.

### If the learner can't visualise
Some people don't form mental images (aphantasia). Fall back on verbal links and sound-alike
stories, spatial-but-not-visual loci ("it's *in* the fridge"), and retrieval practice, which
works for everyone.

## Pitfalls

- **Encoding before understanding.** A memorised formula you don't understand produces
  confident misuse. Model first, mnemonic second.
- **Weak images.** A miss means the picture wasn't vivid or interacting enough. Rebuild it
  rather than re-drilling it.
- **Palace interference.** Reusing a palace too soon causes ghost images. Use a fresh route.
- **No review.** Everything decays without spaced recall (retention.md).
