# Memory Techniques

Mnemonics are for **arbitrary** information, things that can't be derived from a model: names,
numbers, orders, vocabulary, exact formula shapes, which service sits behind which queue. They
work on one principle, which Derren Brown puts at the centre of the memory chapter in *Tricks of
the Mind* (2006): **memory is association**. You remember new things by locking them onto
things you already know, and the lock holds best when it is vivid and visual.

The evidence is strong. In Dresler et al. (2017, *Neuron*), ordinary people trained in the
method of loci for about six weeks more than doubled their word-list recall, kept most of the gain
four months later, and their brain connectivity shifted towards that of memory champions. These
are trained skills, not talents.

## The image rules

An image is the unit of every technique below. A weak image means a forgotten item. Make each
image (Brown's guidance and the classical *Rhetorica ad Herennium* agree on all of these):

1. **Concrete.** You can't picture "justice". You can picture a judge's gavel. Turn
   abstractions into objects (see Substitute words).
2. **Exaggerated.** Huge, tiny, millions of them. A 40-foot pencil, not a pencil.
3. **Absurd.** Ordinary is forgettable. The bizarreness effect works through distinctiveness,
   so each image must stand out from its neighbours, not just be weird.
4. **In motion.** Things crashing, melting, exploding, dancing. Action beats still life.
5. **Interacting.** The two things being linked must *do something to each other*: the
   elephant sits on the teapot, not elephant-next-to-teapot (Bower's interactive-imagery
   finding).
6. **Multi-sensory.** Smell the burning rubber, hear the crunch, feel the cold.
7. **Personal and emotional.** Funny, disgusting, embarrassing, involving people you know.
   Crude and violent images stick hardest. Use them only if the learner is comfortable.
8. **Held for a beat.** Actually see it for 2–3 seconds. Rushing the visualisation is the
   most common failure.

**Co-create.** Offer an image, then ask: "Make it weirder, or make it yours: what would *you*
see?" A self-generated image beats a supplied one (the generation effect).

## Substitute words — making the abstract concrete

Before anything can be pictured, convert it into an image:

- **Sound-alike:** *Kubernetes* → "cube-er-net-eez" → an ice **cube** caught in a fishing
  **net**, **sneezing**. *Avogadro* → an **avocado** riding a **dragon**.
- **Symbol:** *entropy* → a teenager's messy bedroom. *Recursion* → a mirror facing a mirror.
  *Mutex* → a single bathroom key on a giant wooden paddle.
- **Literal part:** *Observer pattern* → a giant eyeball on a stalk. *Kafka* → a cockroach
  (Kafka's *Metamorphosis*).
- **Person:** a known person standing for a concept (Newton for gravity, Ada Lovelace for
  computing).

Keep a **standing image** for recurring concepts in the learning log, so "cache" is always the
same treasure chest. A consistent visual vocabulary makes later palaces fast to build.

## 1. The linking system (chain)

**For:** short-to-medium ordered lists (5–20 items) when you don't have a palace ready.

Link item 1 to item 2 in one interacting image, then 2 to 3, then 3 to 4, and so on. Each image
holds only two items. Recall by starting from the first and letting each image hand you the
next.

> HTTP request lifecycle: **DNS → TCP → TLS → request → server → response**
> A giant **phone book** (DNS) slams shut on a **TCP** **taxi** (*T*axi *C*ab *P*ulling away).
> The taxi drives into a wall of **padlocks** (TLS) that burst open. Out of the padlocks flies
> a **letter** (request) that lands in a **waiter's** (server's) tray. The waiter throws a
> **boomerang** (response) back.

Weakness: break one link and the rest of the chain is lost. Tie the first item to the topic
itself ("the HTTP lifecycle starts with a phone book") so you can always find the start.

## 2. Method of loci / memory palace

**For:** long ordered lists, hierarchies, whole architectures, speeches, proofs as sequences of
steps. The strongest general-purpose technique.

**Build the palace:**
1. Pick a place the learner knows cold: their home, commute, office, school, a video game map.
2. Choose a **fixed route** through it (always clockwise, say: front door → hall mirror →
   coat rack → kitchen sink → fridge → …).
3. List 10–20 distinct **loci** (stations) along it. Distinct matters: five similar doors
   blur. Write the route in the learning log.
4. Walk it mentally twice before using it, forwards and backwards.

**Place the items:** put one image per locus, interacting with the locus itself: the item
smashes the mirror or is frozen into the fridge. For dense information, put 2–3 linked
images per locus.

**Recall:** walk the route. Each locus prompts its image.

**Tips:**
- **One palace per topic** (or per room per subtopic), to avoid ghosting from old images. A
  palace can be reused after its contents are reviewed into long-term memory.
- **Every fifth locus gets a marker** (a golden hand at #5, a dime at #10), giving random access.
- **Hierarchies map onto buildings:** building = system, floor = layer, room = container or
  service, objects in the room = components. See domain-playbooks.md for codebases.
- **Virtual palaces** (a game map, a film set, the learner's own codebase directory tree,
  imagined vividly) work once they're familiar.

## 3. Peg systems — random access by number

**For:** numbered lists where you need "what's #7?" without walking the route; laws and
principles that are referenced by number.

**Rhyme pegs (1–10):** 1 bun · 2 shoe · 3 tree · 4 door · 5 hive · 6 sticks · 7 heaven ·
8 gate · 9 wine · 10 hen.

**Shape pegs (1–10):** 1 candle · 2 swan · 3 handcuffs · 4 sailboat · 5 hook · 6 golf club ·
7 cliff edge · 8 snowman · 9 balloon on a string · 10 bat and ball.

Link item *n* to peg *n* with an interacting image.

> SOLID — **3** is Liskov Substitution: a **tree** (3) whose branches are being swapped out
> for identical branches by a lisping lizard ("Liskov"), and the tree doesn't notice.

For more than 10, use the Major system below to build 100 pegs.

## 4. The Major system (phonetic number code)

**For:** numbers, such as constants, dates, port numbers, error codes, phone numbers, PINs,
line numbers, and for building 100+ pegs. Brown uses a number-to-consonant code like this for
long digit strings and card memorisation.

| Digit | Sound | Hook to remember it |
|---|---|---|
| 0 | s, z | **z**ero starts with z |
| 1 | t, d, (th) | t has one downstroke |
| 2 | n | n has two downstrokes |
| 3 | m | m has three downstrokes |
| 4 | r | fou**r** ends in r |
| 5 | l | L is the Roman 50; a hand's thumb + fingers make an L |
| 6 | j, sh, ch, soft g | a reversed j looks like 6 |
| 7 | k, hard c, hard g, q | a K is made of two 7s |
| 8 | f, v | a cursive f looks like 8 |
| 9 | p, b | p is a mirrored 9 |

Vowels and w, h, y are free fillers. It's about **sounds**, not spelling ("phone" = f-n = 82).

Encode digits by grouping them into words, then picturing the words:
- `443` (HTTPS port) → r-r-m → "**rare ham**". A bloody rare ham wearing a padlock.
- `6.022 × 10²³` (Avogadro) → 6-0-2-2 / 2-3 → "**chosen on**", "**name**". An avocado-dragon
  (Avogadro) is **chosen** by a crowd, tears off a **name**-tag.
- `9.81 m/s²` → 9-8-1 → "**beefed**". A falling side of **beef**, fattened up mid-air.

**Build a 00–99 peg list** once (00 sauce, 01 suit, 02 sun, 03 sum… 10 toes, 11 tot, 12 tin, …
99 pipe) and the learner has 100 pegs and a ready-made number vocabulary forever. Offer this as
a side project for anyone memorising lots of numbers.

**PAO (person–action–object):** advanced. Every 2-digit number gets a person, an action and an
object, so a 6-digit number becomes one scene (person of the first pair, action of the second,
object of the third). Only worth it for heavy numeric memorising.

## 5. Names and faces

Brown's routine, generalised:
1. **Really hear the name.** Repeat it back and use it once in the conversation.
2. **Turn the name into an image** with a substitute word (Taylor → a tailor's tape measure,
   Priya → "pre-owned car", Smith → a blacksmith's anvil).
3. **Pick a striking feature** of the face (big eyebrows, a mole, distinctive glasses), the
   first thing you notice.
4. **Link the image to the feature, interacting:** a tiny blacksmith hammering on those
   eyebrows.
5. Review at the end of the meeting, and again that evening.

For a codebase or org, the same works for **service owners**, **teams**, and **service names ↔
responsibilities**.

## 6. Vocabulary and term ↔ meaning pairs (keyword method)

Atkinson's keyword method, well supported for language learning:
1. Find a sound-alike **keyword** in the learner's language for the foreign or new term.
2. Link the keyword to the **meaning** in an interacting image.

> Spanish *pato* (duck) → "pot-oh" → a duck sitting in a cooking **pot**, saying "oh!".
> *Idempotent* → "I-dem-potent" → **I**, the same **potent** potion drunk twice, with the same
> effect, no stronger.

Then retire the mnemonic through spaced retrieval. Once recall is automatic, the image fades
by itself, as it should.

## 7. Formulas and equations

Order of preference:
1. **Derive it.** If it can be reconstructed from a model in under 30s (kinematic equations
   from the definition of acceleration, the quadratic formula by completing the square), teach
   the derivation and drill *that*.
2. **Dimensional sanity.** Teach checking units: they catch most misremembered formulas.
3. **Shape image** for what remains: E = mc² → Einstein (E) pouring **milk** (m) into a
   **cup** (c) that's **squared** off into a box. Place formula images in a palace per chapter.
4. **Story for the structure**: for long formulas, a short scene where each term enters in
   order.

## 8. Acronyms and acrostics

Fast and good enough for short fixed lists: SOLID, ACID, "Please Do Not Throw Sausage Pizza
Away" (OSI layers, bottom-up). Weak for long lists or anything needing meaning. Make the
acrostic sentence vivid, and picture it.

## Choosing quickly

```
Is it derivable from a model in <30s?        → don't mnemonicise; teach the derivation
Is it a number?                              → Major system → image → (palace if many)
Is it a pair (term↔meaning, name↔face)?      → substitute word + interacting link
Is it an ordered list ≤ 7?                   → linking chain or acrostic
Is it an ordered list > 7, or a hierarchy?   → memory palace
Do you need "item #n" directly?              → pegs
```

## Pitfalls

- **Encoding before understanding.** Memorising a formula you don't understand produces
  confident misuse. Model first, mnemonic second.
- **Weak images.** If the learner can't recall an item, the image wasn't vivid or interacting
  enough. Rebuild it rather than re-drilling it.
- **Palace interference.** Reusing a palace too soon causes ghost images. Use a fresh route.
- **No review.** A palace decays like everything else. It needs spaced walks (retention.md).
- **Forcing it.** Some learners don't visualise strongly (aphantasia exists). Fall back on
  verbal links, sound-alike stories, spatial-but-not-visual loci ("it's *in* the fridge"),
  and retrieval practice, which works for everyone.
