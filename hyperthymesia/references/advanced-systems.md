# Advanced Systems

The infrastructure built once and used forever. Everything here uses **one number code**, the one
from Derren Brown's *Tricks of the Mind* (brown-system.md §4):

| 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
|---|---|---|---|---|---|---|---|---|---|
| z / s | l | n | m | r | f / v | b / p | t | ch / sh / j | g |

Fillers are **vowels, h and y only**. Any other letter changes the number. Check every word you
invent with `memgym.py decode <word>`.

**Build gradually**: the 00–99 list first (a week of drilling), then cards, then the rest as
needed. Each learner keeps their own version in `~/.hyperthymesia/systems/`, seeded from the
tables below.

## 1. The 00–99 images

Built from the reference notebook (0–52) and completed with the same method (53–99). (An early draft had *notch* for 28
and *match* for 38: both hide a *t*, so they encode 278 and 378. That's the classic filler mistake.)

**Single digits:** 0 zoo · 1 ale · 2 hen · 3 ham · 4 whore · 5 hive · 6 bee · 7 tea · 8 shoe · 9 goo

| # | Code | Image | # | Code | Image | # | Code | Image |
|---|---|---|---|---|---|---|---|---|
| 10 | l-s | lice | 25 | n-f | knife | 40 | r-z | rose |
| 11 | l-l | lily | 26 | n-b | nob / nab | 41 | r-l | role |
| 12 | l-n | line | 27 | n-t | knight | 42 | r-n | rain |
| 13 | l-m | lime | 28 | n-sh | Nash | 43 | r-m | ram |
| 14 | l-r | lorry / lure | 29 | n-g | nog | 44 | r-r | roar |
| 15 | l-f | life / leaf | 30 | m-s | maze / mass | 45 | r-v | rave |
| 16 | l-p | lip | 31 | m-l | mole | 46 | r-p | rap |
| 17 | l-t | lit | 32 | m-n | man | 47 | r-t | root / rat |
| 18 | l-sh | lash | 33 | m-m | mum | 48 | r-sh | rash |
| 19 | l-g | leg | 34 | m-r | more / merry | 49 | r-g | rag |
| 20 | n-z | nose | 35 | m-f | mf | 50 | f-s | fuse |
| 21 | n-l | nail | 36 | m-p | map | 51 | f-l | fall |
| 22 | n-n | noon / nanny | 37 | m-t | mat | 52 | f-n | fan |
| 23 | n-m | name | 38 | m-sh | mesh | | | |
| 24 | n-r | Nero | 39 | m-g | **mug** (Brown's own) | | | |

**53–99** (84 chair, 85 shave and 86 shop are from Brown's football example; the rest follow the same rule and were each checked with `decode`):

| # | Code | Image | # | Code | Image | # | Code | Image |
|---|---|---|---|---|---|---|---|---|
| 53 | f-m | foam | 69 | b-g | bag | 85 | sh-f | shave |
| 54 | f-r | fire | 70 | t-s | toes | 86 | sh-b | shop |
| 55 | f-f | fife | 71 | t-l | tail | 87 | sh-t | jet |
| 56 | f-b | fob | 72 | t-n | tin | 88 | sh-sh | choo-choo |
| 57 | f-t | feet | 73 | t-m | tomb | 89 | sh-g | jug |
| 58 | f-sh | fish | 74 | t-r | tyre | 90 | g-s | goose |
| 59 | f-g | fig | 75 | t-f | toffee | 91 | g-l | gull |
| 60 | b-s | bus | 76 | t-b | tub | 92 | g-n | gun |
| 61 | b-l | ball | 77 | t-t | tattoo | 93 | g-m | gum |
| 62 | b-n | bone | 78 | t-sh | Taj | 94 | g-r | gear |
| 63 | b-m | bomb | 79 | t-g | toga | 95 | g-f | Goofy |
| 64 | b-r | bear | 80 | sh-s | chess | 96 | g-b | guppy |
| 65 | b-f | beef | 81 | sh-l | shell | 97 | g-t | goat |
| 66 | b-b | baby | 82 | sh-n | chain | 98 | g-sh | gash |
| 67 | b-t | bat | 83 | sh-m | jam | 99 | g-g | Gaga / gag |
| 68 | b-sh | bush | 84 | sh-r | chair |  |  |  |

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

From the reference notebook:

| | ♠ Spades | ♥ Hearts | ♦ Diamonds | ♣ Clubs |
|---|---|---|---|---|
| **A** | Grim Reaper | a big love heart | a big sparkly diamond | a big club |
| **2** | sun | lovers (two hearts) | Don | can |
| **3** | Sam (a friend) / sum | home | Dom | cam |
| **4** | sore | hair | door | car |
| **5** | safe | hoof | dove | cough |
| **6** | sob | hoop | DB (Derren Brown) | cab |
| **7** | soot | hat | dot | cat |
| **8** | sash | hedge | dish | cash |
| **9** | ciggy | hag | dog | cog |
| **10** | sissy | hose | dizzy | kiss |
| **J** | boy digging / Beelzebub | Cupid | diamond thief | young boy athlete |
| **Q** | housekeeper | bride | the Queen | brothel madam |
| **K** | gardener / Dante (Lucifer) | bridegroom | the old jeweller | bouncer / cad |

One deliberate exception: 2♥ *lovers* is chosen for its meaning. A stronger picture is worth
bending the code for, as long as it never changes.

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
