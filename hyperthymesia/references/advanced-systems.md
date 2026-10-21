# Advanced Systems

The infrastructure built once and used forever. Everything here uses **one number code**, the one
from Derren Brown's *Tricks of the Mind* (brown-system.md §4):

| 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
|---|---|---|---|---|---|---|---|---|---|
| z / s | l | n | m | r | f / v | b / p | t | ch / sh / j | g |

Fillers are **vowels, h and y only**. Any other letter changes the number. Check every word you
invent with `memgym.py decode <word>`.

**Build gradually**: the 00–99 list first (a week of drilling), then cards, then the rest as
needed. Each learner keeps their own version in `~/.hyperthymesia/systems/`, seeded from
[notes.md](notes.md).

## 1. The 00–99 images

The full list (0–9, 10–99) lives in **[notes.md](notes.md)**, the single source of truth. Don't
copy it here. `python3 scripts/memgym.py encode <number>` shows the picture for any number, and
`python3 scripts/memgym.py notes-check` confirms every word decodes correctly.

**Rules for choosing images:**
- **Objects or people you can see and touch** beat abstract words ("knight" beats "night").
- **One image per number, forever.** Changing them later causes interference.
- **Distinct across the table**: avoid two animals that look alike, or two similar tools.
- Spelling doesn't matter; **sound** does ("knife" = n-f, since the k is silent; "lily" = l-l).

**Training the list:** 10 minutes a day, both directions (number → image, image → number),
until each comes back in under a second. Then `memgym.py gen numbers 40` exercises it in context.

## 2. The 52-card images

**Rule:** suit initial (**S**pades, **H**earts, **D**iamonds, **C**lubs) + the rank's code
letter. Ace = 1 (l), 10 = 0 (z/s). 9♥ → H-g → **hag**; 6♠ → S-b → **sob**.
**Aces** are a big version of the suit symbol. **Court cards are characters**, because "J" would
clash with j = 8, and each suit gets a theme.

The full 52-card set, including the allowed exceptions, lives in **[notes.md](notes.md)**.

**Suit themes for the courts:** Spades = death and digging · Hearts = love and weddings ·
Diamonds = wealth and jewels · Clubs = sport and nightlife.

Note how the notebook avoids clashes with the single-digit images: 3♥ is *home*, not *ham*
(ham = 3); 4♥ is *hair*, not *whore* (whore = 4); 5♥ is *hoof*, not *hive* (hive = 5). Keep card
images distinct from number images.

Learn: one suit a day (13 images), flipping cards and saying the image. Then
`memgym.py gen cards 13` → 26 → 52.

## 3. Binary

Read binary in 3-bit groups → a digit 0–7 (`101` = 5), then pair the digits into 00–99 images.
`101 110 001 011` → 5 6 1 3 → 56 and 13 → their images. Practise: `memgym.py gen binary 60`.

## 4. Dates

**Historical dates (event + date):** the event becomes an image; the year (and month/day if
needed) becomes 00–99 images, all in one scene. *Moon landing, 1969*: 19 = l-g → **leg**,
69 = b-g → a **bag**. An astronaut steps onto the Moon with one **leg** stuck in a **bag**.

**Day of the week for any date (the Doomsday algorithm, Conway).** A classic "human calendar"
feat, and the backbone of date-indexed life memory (daily-recall.md).

1. **Century anchor**: 1800s Fri · 1900s Wed · 2000s Tue · 2100s Sun.
2. **The year's doomsday**: for the last two digits `yy`: `a = yy ÷ 12` (integer), `b = yy mod 12`,
   `c = b ÷ 4` (integer). Doomsday = anchor + `(a + b + c)` mod 7.
3. **These dates always fall on the doomsday**: 4/4, 6/6, 8/8, 10/10, 12/12, 9/5 and 5/9,
   7/11 and 11/7 ("working 9-to-5 at the 7-11"), the last day of February, 3/14 (Pi Day),
   and Jan 3 (Jan 4 in leap years).
4. Count from the nearest doomsday date to the target, mod 7.

*Example: 20 July 1969.* Anchor Wed. yy = 69 → a = 5, b = 9, c = 2 → 16 mod 7 = 2 → Wed + 2
= **Fri** is 1969's doomsday. 7/11 is a Friday; 20 July = 11 + 9 → Fri + 9 = Fri + 2 = **Sunday**. ✔

Practise: `memgym.py gen dates 10`, and `memgym.py weekday YYYY-MM-DD <guess>` to check one.
Target: under 10 seconds per date after a couple of weeks.

## 5. Everyday numbers

- **PINs**: Brown's method: code → word/phrase → link to the *cash machine* (1743 → "Light Room").
- **Phone numbers**: the person's name image + 00–99 images at one locus, or a short story
  in Brown's long-number style.
- **Card numbers and IDs**: 4-digit groups → 2 images per group → a 4-locus mini palace.
  (A password manager is still the right home for secrets; memorise only what you'd otherwise
  write down insecurely.)
- **Paired data** (scores, prices, KPIs): Brown's football method: initials + numbers → words.
- **Parking spot, hotel room, gate**: one image placed at the place itself (on the room door).

## 6. Managing many palaces

- **Registry**: `palaces.md`, with every palace, its loci in clockwise order from the immediate
  left, markers at every 5th locus, and what it holds now.
- **Permanent vs scratch** (Brown): tasks and speeches go in loci you let fade and reuse;
  information you want to keep goes in designated buildings that are never reused.
- **Palace per domain**: one building per subject, with rooms as subtopics, linked by imaginary
  doors, stairwells and hallways into one sprawling palace.
- **Expansion**: when you're somewhere suitable (a museum, a park, a theatre, a friend's home),
  walk a fixed route, photograph it, return a few times, and add it to the registry that evening.
- **Capacity**: interference, not space, is the limit. Keep loci distinct and re-walk palaces
  now and then.
