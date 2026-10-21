# The Patrick Jane Layer: Observation, People, Scenes

Patrick Jane (*The Mentalist*) seems to remember everything about everyone. Look closely and
his "memory" is mostly **observation**. He notices what others don't, then files it in a
memory palace built from the carnival he grew up in, and he even teaches a colleague to build
one for an undercover job. The fiction exaggerates the results, but both halves are real skills:

> **You cannot remember what you never encoded, and you cannot encode what you never noticed.**

Most "bad memory" is bad attention. This layer trains the input side.

## 1. Observation drills

**Kim's game** (from Kipling's *Kim*; long used in scouting and military observation training):
- 10–20 objects on a table, 60 seconds to look, cover them, list them. Add "what moved?" and
  "what's missing?" variants. Claude can run this verbally with `memgym.py gen words 15`
  as the object list.
- Progress: more objects, less time, then details (colour, position, count).

**Room scan.** In a new room, do a deliberate sweep in a fixed order: entrance → exits →
people (hands, shoes, what they're holding) → anything out of place. Then close your eyes and
describe it. Do it in every café for a week and it becomes automatic.

**The "what changed?" habit.** Each day, notice one thing different on your commute, at the
office, or in a person (a new haircut, a different bag, a mood). Noticing change is noticing
detail.

**Detail-to-image conversion.** Observation and memory join when each noticed detail becomes
an image placed somewhere: the nervous man's chewed pen becomes a giant pen gnawing at the
door locus of the room.

## 2. People dossiers

Jane always knows who someone is, what they said, and what they care about. Build that
deliberately, kept in `~/.hyperthymesia/people.md`, privately and respectfully (see Ethics).

For each person worth remembering:

| Field | How to encode |
|---|---|
| Name | Substitute-word image linked to their anchor face feature (brown-system.md §8) |
| Where / when met | Put the person at that place in your mind; the place is the locus |
| Role, connections | Props in the scene: a stethoscope, a child holding their hand |
| What they care about | Their "action" in the scene: the dog-lover is walking ten dogs |
| Things they told you | One image per fact, attached to their body (hat = job news, hands = hobby) |
| Follow-ups | What to ask next time (the job interview, the marathon) |

After a meeting or party, spend 3 minutes walking the room: who stood where, their name images,
one fact each. Add the important ones to people.md with `due:` review dates. Before seeing
them again, run their dossier.

## 3. Conversations and meetings

- **Anchor topics to the room.** As the meeting moves topic, attach each key point to an
  object in the room you're in (the whiteboard holds the deadline, the window holds the budget
  figure). Afterwards, walk the room. The room is a ready-made palace.
- **Numbers and names said aloud**: encode them in the moment (number-code image + where it was said).
- **Commitments**: a "promise" image per action item, placed on the person who owns it.
- **After**: 2-minute walk-through, then 3 lines in the vault if it matters.

## 4. Scenes and "reconstruction"

Jane reconstructs scenes he never saw. That's fiction plus inference. Real memory is
**reconstructive**: recall is rebuilt each time, confidence doesn't guarantee accuracy, and
leading questions can implant false details (Loftus's misinformation research). So:
- When recalling a scene, keep **observed** separate from **inferred**. Say "I saw X" versus
  "so probably Y".
- Encode a scene *while you're in it* (room scan + anchor images). That's what makes it recallable.
- Write down important observations soon after. A memory you rehearse wrongly gets stronger
  wrongly.

## 5. The carnival palace: build a master palace

Jane's palace is a place he knows at a level of detail no ordinary building has. Build yours:
1. Pick the richest place of your life: a childhood home, a school, a grandparent's house, a
   town centre.
2. Walk it slowly in your mind and list 30–100 loci, room by room, in a fixed route.
3. Add one new detail per locus (a sound, a smell) until each feels vivid.
4. Give it **districts** for life domains: the kitchen for work systems, the garden for people,
   the attic for languages, and so on.
5. Register it in `palaces.md` as permanent. This becomes your "mind palace".

## Ethics

This layer is for remembering people well (names, what matters to them, what you promised),
not for profiling or manipulating them. Keep dossiers factual and kind, store them only
locally, and leave out anything sensitive someone shared in confidence that you don't need.
Jane's cold-reading tricks for deceiving people are not part of this skill.
