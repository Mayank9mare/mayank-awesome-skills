# Remember With Me

The main workflow. The learner says **what** they want to remember and gives **whatever pictures
they already have**: all of them, some, half an idea, or none. Claude keeps theirs, fills the gaps
with pictures built by the notebook's rules ([notes.md](notes.md)), and then gets the learner to
the point where they can recall it cold.

Triggers: "help me remember…", "I need to learn…", "make this stick", a list with some pictures
already written next to it, or "here's what I have so far…".

## Input: anything goes

The learner might send:

```
Planets in order. Mercury: a thermometer exploding. Venus: ?. Earth: my globe.
Mars: a Mars bar. Then Jupiter, Saturn, Uranus, Neptune, no ideas. Also Jupiter has 95 moons.
```

Accept any format: a list, a paragraph, a pasted document, a photo of notes, a number, a set of
people. Don't ask them to reformat it.

## Step 1: Understand what it is

- **Is there meaning to learn first?** If it's a concept (a law, a pattern, how something works),
  check understanding before encoding. Ask one or two questions, or hand off to `learn-anything`.
  Mnemonics hold facts; they don't create understanding.
- **Split it into items**: the smallest pieces that must come back (names, numbers, steps, words).
- **Pick the structure** by the shape of the data (the SKILL.md table): linking for a short list,
  a palace for anything long or important, the number code for digits, the football method for
  pairs, names-and-faces for people, the Ross layer for documents and exact wording.
- **Pick the place.** Use a palace from the learner's `palaces.md`. If none is free, ask once:
  "Which place do you know really well: your home, your office, your school?" Then lay out its
  loci clockwise from the immediate left. More than ~20 items means one room per group.

## Step 2: Keep their pictures, exactly

- **Their picture wins.** Use it word for word. Don't "improve" it silently.
- **Half a picture** ("Venus: something with a mirror") → keep their core idea and add only what
  it needs to work: an interaction with the locus or the next item, and some movement.
- **Check theirs against the notebook rule**, and if there's a problem say so in one line,
  offer a fix, and keep theirs unless they accept:
  - A number word must decode correctly (`memgym.py decode <word>`).
  - A picture that doesn't interact with anything (a globe *sitting* on the table) gets a
    suggested action ("the globe spins off the table and rolls into…").
  - A picture that collides with one of their standing images (e.g. reusing *hen*, which is 2)
    gets flagged.

## Step 3: Fill the gaps, the notebook's way

For every missing picture, build one that is:
1. **From their own systems first.** Their 00–99 images for numbers (95 = Goofy), their card
   images, their pegs, their palace, their standing images, the people they know. Personal
   assets beat generic ones.
2. **Concrete**: something you can see and touch. Abstract words become things by sound or
   symbol (Uranus → "your anus" if they're fine with crude, or a *urn* full of *ice* if not).
3. **Vivid and emotionally engaging**: a sense (smell, sound, texture) or a feeling (gross,
   funny, painful).
4. **Interacting** with the locus and/or the next item. Something *happens*.
5. **Unusual**: exaggerated size, wrong material, impossible motion.
6. **One sentence.** Short enough to see in two seconds.

Mark every picture Claude made with **(mine)** so the learner can swap it. Self-made pictures
stick better, so invite swaps without pushing.

## Step 4: Show the memory plan

One table, then a short walk-through.

| # | Locus / link | Item | Picture | Whose |
|---|---|---|---|---|
| 1 | front door | Mercury | A thermometer explodes on the doormat, spraying silver beads | yours |
| 2 | coat hooks | Venus | Venus de Milo hangs from the hook by her missing arms, admiring herself in a hand mirror | yours + mine |
| 3 | hall mirror | Earth | Your globe smashes through the mirror and rolls down the hall | yours + mine |
| 4 | radiator | Mars | A giant Mars bar melts over the radiator, sticky and hot | yours |
| 5 ✋ | kitchen door | Jupiter | **Goofy** (95) juggles 95 tiny moons in the doorway, dropping them everywhere | mine |
| 6 | fridge | Saturn | Saturn's rings are stuck round the fridge like a hula hoop, spinning | mine |
| 7 | oven | Uranus | An urn full of ice cracks open in the hot oven, steam hissing | mine |
| 8 | sink | Neptune | A trident (Neptune's) jabs up out of the plughole, spraying water | mine |

**Walk-through:** narrate the route once in the second person, present tense, two lines a stop
at most: "You open the front door and a thermometer explodes on the mat…". Ask them to *see* each
one for two seconds.

## Step 5: Test straight away

1. **Forwards**: "Walk me through it." One stop at a time; don't prompt unless they're stuck.
2. **Backwards**: from the last locus to the first.
3. **Random access**: "What's at the 5th stop?" (the ✋ marker), "Which planet is on the oven?"
4. **Any miss** means that picture was weak. Offer to rebuild it: ideally *they* make it this time
   (that's the strongest fix), or offer 2–3 alternatives to choose from.

## Step 6: Save and schedule

Write it to `~/.hyperthymesia/vault/<topic>.md` (templates/vault-topic.md): the table above,
including the **Whose** column, plus `due:` dates for today, +1d, +3d, +7d, +21d and +60d. Claim the
loci in `palaces.md` so the palace isn't reused by accident. Suggest one booster (draw it, or say
it aloud as you walk it). Tell them when the next review is, and that "what's due?" picks it up.

## Changing things later

- "Change 6" / "I don't like the Saturn one" → offer 2–3 alternatives, or take theirs. Update the
  vault file.
- "Add Pluto" → extend from the last locus (or a new room), same rules.
- "I forgot 3 again" → rebuild it bigger and stranger, made by them, and reset its review dates.
- New information about the same topic goes in the same palace, in a new room.

## Rules

- Never replace a learner's picture without asking.
- Never mark Claude's pictures as theirs.
- Never invent facts. If unsure of something being memorised (a date, a figure), check it or say so.
  A vivid picture of a wrong fact is worse than nothing.
- Keep crude or violent pictures opt-in.
- Follow the notebook rule: no methods that conflict with the notes; number words must decode.
