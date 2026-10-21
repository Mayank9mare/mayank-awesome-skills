#!/usr/bin/env python3
"""memgym.py: memory-athlete drills, scoring, progress log, and review due-dates.

Stdlib only. State lives in ~/.hyperthymesia (override with HYPERTHYMESIA_HOME).

  gen <kind> [n]     create a drill and print the items to memorise
                     kinds: numbers, binary, cards, words, names, dates, spoken
  quiz <id>          print the recall prompt (cues only, never the answers)
  check <id> <answer...>   score an answer, log it, and show the diff
  show <id>          reveal the items (after checking)
  log [kind]         progress table and personal bests
  due [--days N]     vault items whose `due:YYYY-MM-DD` is on or before today (+N days)
  weekday <date>     check a day-of-week answer (Doomsday practice)
  decode <word...>   digits a word encodes in Brown's number code (catches stray code letters)
  encode <number>    split a number into pairs with their code letters and notebook images
  notes-check        validate references/notes.md: every number and card word must decode to its
                     number, no number with two pictures, no picture used twice (exit 1 on conflict)

Number code (Derren Brown, Tricks of the Mind): 0 z/s · 1 l · 2 n · 3 m · 4 r · 5 f/v ·
6 b/p · 7 t · 8 ch/sh/j · 9 g. Fillers: vowels, h, y (and w).

Answers: numbers/binary as digits (spaces ignored); cards as tokens like `KS 10H 3D AC`
(suits S H D C); words and names as comma- or space-separated words; dates as weekday
names in order.
"""
import json
import os
import random
import re
import sys
from datetime import date, datetime, timedelta

HOME = os.path.expanduser(os.environ.get("HYPERTHYMESIA_HOME", "~/.hyperthymesia"))
DRILLS = os.path.join(HOME, "drills")
LOG = os.path.join(HOME, "training-log.tsv")

WORDS = """anchor apple arrow axe baby balloon banana barrel basket bat bathtub beard bee bell
bicycle blanket boat bone book boot bottle bow bowl box bracelet bread brick bridge broom
bubble bucket bull butterfly button cactus cage cake camel camera candle cannon canoe car
carpet carrot castle cat chain chair cheese cherry chimney clock cloud clown coat coconut
coffin comb compass cookie corn cow crab crown crystal cup curtain daisy desk diamond dice
dog doll dolphin donkey door dragon drum duck eagle egg elephant envelope eraser feather
fence fire fish flag flute fork fountain fox frog ghost giraffe glove goat guitar hammer
hammock harp hat helmet honey horn horse hose igloo iron jacket jar jellyfish kangaroo
kettle key kite knife ladder lamp lemon lighthouse lion lobster lock magnet map mask
mattress medal mermaid microphone mirror monkey moon mop motorcycle mountain mouse
mushroom nail necklace needle nest net octopus onion orange owl paddle paint pan panda
parachute parrot peach pear pencil penguin piano pie pig pillow pineapple pipe pirate
pizza planet plate pumpkin puppet pyramid rabbit radio rainbow rake rat ring robot rocket
rope rose sail sandwich saw scarf scissors shark sheep shell shoe shovel skateboard
skeleton snail snake snowman sock sofa spider spoon squirrel stamp star statue sword
syringe table teapot telescope tent tiger toaster toilet tomato tooth torch tractor train
trampoline tree trophy trumpet tulip turtle umbrella unicorn vase violin volcano wagon
wall wand watch waterfall whale wheel whistle wig windmill witch wolf worm zebra zipper""".split()

FIRST = """Aarav Abena Adrian Aiko Alejandro Amara Ananya Anders Aniket Bea Bilal Boris
Camila Chen Chidi Clara Dario Deepa Dmitri Elif Elena Emeka Esme Farah Felix Gita Grace
Hamza Hana Hugo Ines Ivan Jaya Jonas Kai Kavya Kenji Lars Leila Lucas Mahmoud Maya Mei
Mateo Nadia Nikhil Noor Olga Omar Priya Quinn Rafael Rania Ravi Rosa Sanjay Sara Sven
Tariq Thea Tomas Uma Vera Wei Yara Yusuf Zara Zoe""".split()
LAST = """Abbott Banerjee Becker Bianchi Brennan Castillo Chandra Cohen Dalton Diaz Dubois
Eriksen Farouk Fischer Gallagher Garcia Haddad Hoffman Ivanova Jensen Kapoor Kato Kowalski
Lambert Larsen Lopez Mahler Mendes Moreau Nakamura Novak Okafor Olsen Patel Petrov Quinlan
Reyes Rossi Sato Schmidt Sharma Silva Singh Sorensen Tanaka Thornton Varga Walsh Weber
Yilmaz Zhang""".split()
JOBS = """pilot dentist baker architect beekeeper chef firefighter florist geologist
jeweller lawyer librarian locksmith marine-biologist nurse painter pharmacist plumber
podcaster sculptor surgeon tailor teacher translator vet violinist welder""".split()
FEATURES = """curly-red-hair round-glasses bushy-eyebrows a-scar-on-the-chin freckles
a-shaved-head a-long-grey-beard dimples a-gap-in-the-front-teeth a-nose-ring big-ears
a-bright-yellow-scarf a-bow-tie heavy-eyeliner a-handlebar-moustache a-silver-earring
a-baseball-cap very-tall-and-thin a-loud-laugh a-tattoo-of-a-rose a-cast-on-one-arm
braided-hair a-cowboy-hat tiny-reading-glasses""".split()

CLASSIC = ("telephone sausage monkey button book cabbage glass mouse stomach cardboard ferry "
           "christmas athlete key wigwam baby kiwi bed paintbrush walnut").split()

CODE = {"z": "0", "s": "0", "l": "1", "n": "2", "m": "3", "r": "4", "f": "5", "v": "5",
        "b": "6", "p": "6", "t": "7", "j": "8", "g": "9"}
FILLERS = set("aeiouhyw")
# Images from the reference notebook (single digits + the 00–99 entries it contains).
NOTEBOOK = {"0": "zoo", "1": "ale", "2": "hen", "3": "ham", "4": "whore", "5": "hive",
            "6": "bee", "7": "tea", "8": "shoe", "9": "goo", "10": "lice", "11": "lily",
            "12": "line", "13": "lime", "14": "lorry", "15": "life", "16": "lip", "17": "lit",
            "18": "lash", "19": "leg", "20": "nose", "21": "nail", "22": "noon", "23": "name",
            "24": "Nero", "25": "knife", "26": "nob", "27": "knight", "29": "nog", "31": "mole",
            "32": "man", "33": "mum", "36": "map", "37": "mat", "39": "mug", "40": "rose",
            "41": "role", "42": "rain", "43": "ram", "44": "roar", "47": "root", "48": "rash",
            "50": "fuse", "52": "fan", "30": "maze", "34": "more", "45": "rave", "46": "rap", "51": "fall", "35": "mf", "49": "rag", "28": "Nash", "38": "mesh", "53": "foam", "54": "fire", "55": "fife", "56": "fob", "57": "feet", "58": "fish", "59": "fig", "60": "bus", "61": "ball", "62": "bone", "63": "bomb", "64": "bear", "65": "beef", "66": "baby", "67": "bat", "68": "bush", "69": "bag", "70": "toes", "71": "tail", "72": "tin", "73": "tomb", "74": "tyre", "75": "toffee", "76": "tub", "77": "tattoo", "78": "Taj", "79": "toga", "80": "chess", "81": "shell", "82": "chain", "83": "jam", "87": "jet", "88": "choo-choo", "89": "jug", "90": "goose", "91": "gull", "92": "gun", "93": "gum", "94": "gear", "95": "Goofy", "96": "guppy", "97": "goat", "98": "gash", "99": "Gaga / gag", "84": "chair", "85": "shave", "86": "shop"}
NOTES_PATH = os.environ.get("HYPERTHYMESIA_NOTES") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "references", "notes.md")
SOUND = {"cough": "coff", "laugh": "laf", "rough": "ruff", "tough": "tuff", "enough": "enuff"}
RANKS_ALL = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]


def _clean(cell):
    """Display text of a notes cell: drop marks, bold, and '(not …)' asides."""
    c = re.sub(r"[✔✎*]", "", cell)
    c = re.sub(r"\(not [^)]*\)", "", c)
    return re.sub(r"\s+", " ", c).strip()


def _alternatives(cell):
    """Words to decode for a cell: each ' / ' alternative, parentheticals removed."""
    base = re.sub(r"\([^)]*\)", "", _clean(cell))
    return [a.strip() for a in base.split("/") if a.strip()]


def load_notes(path=NOTES_PATH):
    """Parse notes.md → (numbers {"0".."99": [(image, line)]}, cards {"9H": (image, line)}, exceptions set).
    Numbers keep every occurrence so duplicates and disagreements can be reported."""
    nums, cards, exc = {}, {}, set()
    if not os.path.exists(path):
        return nums, cards, exc
    section = ""
    suits = None
    for ln, line in enumerate(open(path, encoding="utf-8"), 1):
        if line.startswith("#"):
            section = line.strip("# \n").lower()
            suits = None
            continue
        if section == "single digits":
            for d, w in re.findall(r"(?:^|·)\s*(\d)\s+([^·\n]+)", line):
                nums.setdefault(d, []).append((_clean(w), ln))
        if not line.startswith("|") or re.match(r"^\|[\s|:-]+\|$", line.strip()):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if section.startswith("double digits"):
            for i in range(0, len(cells) - 1, 2):
                if re.fullmatch(r"\d{2}", cells[i]) and _clean(cells[i + 1]):
                    nums.setdefault(cells[i], []).append((_clean(cells[i + 1]), ln))
        elif section.startswith("53"):
            m = re.fullmatch(r"\*\*(\d)_\*\*", cells[0])
            if m:
                for u, c in enumerate(cells[1:11]):
                    if _clean(c):
                        nums.setdefault(m.group(1) + str(u), []).append((_clean(c), ln))
        elif section.startswith("memorising a deck"):
            if "♠" in line and suits is None:
                suits = ["S" if "♠" in c else "H" if "♥" in c else "D" if "♦" in c else "C" if "♣" in c else None
                         for c in cells[1:]]
                continue
            m = re.fullmatch(r"\*\*(A|10|[2-9JQK])\*\*", cells[0])
            if m and suits:
                for su, c in zip(suits, cells[1:]):
                    if su:
                        cards[m.group(1) + su] = (_clean(c), ln)
    for m in re.finditer(r"Exceptions \(allowed to break the code\):([^\n]*)", open(path, encoding="utf-8").read()):
        for r, su in re.findall(r"(A|10|[2-9JQK])\s*([♠♥♦♣])", m.group(1)):
            exc.add(r + {"♠": "S", "♥": "H", "♦": "D", "♣": "C"}[su])
    return nums, cards, exc


def _notebook_images():
    nums, _, _ = load_notes()
    return {k: v[0][0].split(" / ")[0] for k, v in nums.items()} if nums else None


PAIR_CODE = ["z/s", "l", "n", "m", "r", "f/v", "b/p", "t", "ch/sh/j", "g"]

SUITS = "SHDC"
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
DEFAULT_N = {"classic": 20, "numbers": 40, "binary": 60, "cards": 52, "words": 20, "names": 10,
             "dates": 10, "spoken": 20}


def ensure():
    os.makedirs(DRILLS, exist_ok=True)
    if not os.path.exists(LOG):
        with open(LOG, "w") as f:
            f.write("timestamp\tid\tkind\tn\tcorrect\tstreak\tpct\tmemo_seconds\n")


def save(d):
    with open(os.path.join(DRILLS, d["id"] + ".json"), "w") as f:
        json.dump(d, f, indent=1)


def load(i):
    p = os.path.join(DRILLS, i + ".json")
    if not os.path.exists(p):
        sys.exit(f"no drill {i}")
    with open(p) as f:
        return json.load(f)


def fmt_items(d):
    k, it = d["kind"], d["items"]
    if k in ("numbers", "spoken"):
        rows = ["".join(it[i:i + 40]) for i in range(0, len(it), 40)]
        return "\n".join(" ".join(r[j:j + 4] for j in range(0, len(r), 4)) for r in rows)
    if k == "binary":
        rows = ["".join(it[i:i + 30]) for i in range(0, len(it), 30)]
        return "\n".join(" ".join(r[j:j + 3] for j in range(0, len(r), 3)) for r in rows)
    if k == "cards":
        sym = {"S": "♠", "H": "♥", "D": "♦", "C": "♣"}
        return "\n".join("  ".join(f"{c[:-1]}{sym[c[-1]]}" for c in it[i:i + 13])
                         for i in range(0, len(it), 13))
    if k in ("words", "classic"):
        return "\n".join(f"{i + 1:>3}. {w}" for i, w in enumerate(it))
    if k == "names":
        return "\n".join(f"{i + 1:>3}. {p['name']}: {p['job']}, {p['feature'].replace('-', ' ')}"
                         for i, p in enumerate(it))
    if k == "dates":
        return "\n".join(f"{i + 1:>3}. {x}" for i, x in enumerate(it))


def cmd_gen(kind, n):
    ensure()
    n = n or DEFAULT_N[kind]
    if kind in ("numbers", "spoken"):
        items = [str(random.randint(0, 9)) for _ in range(n)]
    elif kind == "binary":
        items = [str(random.randint(0, 1)) for _ in range(n)]
    elif kind == "cards":
        deck = [r + s for s in SUITS for r in RANKS]
        random.shuffle(deck)
        items = deck[:n]
    elif kind == "words":
        items = random.sample(WORDS, n)
    elif kind == "classic":
        items = CLASSIC[:n]
    elif kind == "names":
        firsts, lasts = random.sample(FIRST, n), random.sample(LAST, n)
        items = [{"name": f"{a} {b}", "job": random.choice(JOBS), "feature": f}
                 for a, b, f in zip(firsts, lasts, random.sample(FEATURES * 3, n))]
    elif kind == "dates":
        start, end = date(1900, 1, 1).toordinal(), date(2099, 12, 31).toordinal()
        items = [date.fromordinal(random.randint(start, end)).isoformat() for _ in range(n)]
    else:
        sys.exit(f"unknown kind {kind}")
    d = {"id": datetime.now().strftime("%Y%m%d-%H%M%S") + f"-{kind[:3]}", "kind": kind,
         "n": n, "items": items, "created": datetime.now().isoformat(timespec="seconds")}
    save(d)
    print(f"drill {d['id']}  ({kind}, {n} items)\n")
    if kind == "spoken":
        print("SPOKEN NUMBERS: Claude reads these to you one digit per second; don't show them.")
        print("(Items hidden. Use `show` only after checking.)")
    elif kind == "dates":
        print("Give the weekday for each date (Doomsday method). Timed: start now.\n")
        print(fmt_items(d))
    else:
        print(fmt_items(d))
        print("\nStart your timer. Memorise, then clear or scroll the screen and ask for the quiz.")


def cmd_quiz(i):
    d = load(i)
    k = d["kind"]
    d["quiz_started"] = datetime.now().isoformat(timespec="seconds")
    save(d)
    if k in ("numbers", "binary", "spoken"):
        print(f"Recall all {d['n']} digits in order.")
    elif k == "cards":
        print(f"Recall the {d['n']} cards in order, e.g. `KS 10H 3D AC`.")
    elif k in ("words", "classic"):
        print(f"Recall the {d['n']} words in order.")
    elif k == "names":
        cues = list(enumerate(d["items"], 1))
        random.shuffle(cues)
        d["quiz_order"] = [c[0] for c in cues]
        save(d)
        print("Name each person (first and last), in this order:")
        for j, (_, p) in enumerate(cues, 1):
            print(f"{j:>3}. the {p['job']} with {p['feature'].replace('-', ' ')}")
    elif k == "dates":
        print(fmt_items(d))


def norm_tokens(kind, raw):
    s = " ".join(raw)
    if kind in ("numbers", "binary", "spoken"):
        return list(re.sub(r"\D", "", s))
    if kind == "cards":
        s = s.upper().replace("♠", "S").replace("♥", "H").replace("♦", "D").replace("♣", "C")
        return re.findall(r"(?:10|[2-9AJQKT])[SHDC]", s.replace("T", "10"))
    if kind == "names":
        parts = [p.strip().lower() for p in re.split(r"[,;\n]", s) if p.strip()]
        return parts
    return [w.lower() for w in re.split(r"[,\s]+", s) if w]


def cmd_check(i, raw):
    ensure()
    d = load(i)
    k = d["kind"]
    ans = norm_tokens(k, raw)
    if k == "names":
        order = d.get("quiz_order") or list(range(1, d["n"] + 1))
        truth = [d["items"][o - 1]["name"].lower() for o in order]
    elif k == "dates":
        truth = [WEEKDAYS[date.fromisoformat(x).weekday()] for x in d["items"]]
        ans = [a[:3] for a in ans]
        truth_cmp = [t[:3] for t in truth]
    elif k == "cards":
        truth = [str(x).upper() for x in d["items"]]
    else:
        truth = [str(x).lower() for x in d["items"]]
    cmp_truth = truth_cmp if k == "dates" else truth
    correct = sum(1 for a, t in zip(ans, cmp_truth) if a == t)
    streak = 0
    for a, t in zip(ans, cmp_truth):
        if a != t:
            break
        streak += 1
    created = datetime.fromisoformat(d["created"])
    started = datetime.fromisoformat(d.get("quiz_started") or d["created"])
    memo = int((started - created).total_seconds())
    secs = int((datetime.now() - created).total_seconds()) if k == "dates" else memo
    pct = 100 * correct / len(truth)
    with open(LOG, "a") as f:
        f.write(f"{datetime.now().isoformat(timespec='seconds')}\t{i}\t{k}\t{d['n']}\t"
                f"{correct}\t{streak}\t{pct:.0f}\t{secs}\n")
    timing = f"{secs}s total" if k == "dates" else f"memorised in ~{memo}s (gen → quiz)"
    print(f"{correct}/{len(truth)} correct ({pct:.0f}%), perfect run from the start: {streak}, {timing}")
    errs = [(j + 1, t, ans[j] if j < len(ans) else "—")
            for j, t in enumerate(cmp_truth) if j >= len(ans) or ans[j] != t]
    if errs:
        print("misses (position: expected / you said):")
        for pos, t, a in errs[:20]:
            print(f"  {pos:>3}: {t} / {a}")
        if len(errs) > 20:
            print(f"  … {len(errs) - 20} more")
    d["checked"] = True
    save(d)


def cmd_show(i):
    d = load(i)
    if not d.get("checked"):
        print("(not checked yet; showing anyway)")
    print(fmt_items(d))


def cmd_log(kind=None):
    ensure()
    rows = [l.split("\t") for l in open(LOG).read().splitlines()[1:] if l.strip()]
    if kind:
        rows = [r for r in rows if r[2] == kind]
    if not rows:
        print("no drills logged yet")
        return
    best = {}
    for r in rows:
        k, n, c, pct = r[2], int(r[3]), int(r[4]), int(r[6])
        if pct == 100 and (k not in best or n > best[k]):
            best[k] = n
    print("timestamp            kind     n   correct  streak  pct  secs")
    for r in rows[-15:]:
        print(f"{r[0]:<20} {r[2]:<8} {r[3]:>3}  {r[4]:>7}  {r[5]:>6}  {r[6]:>3}  {r[7]:>4}")
    if best:
        print("\npersonal bests (largest perfect drill): " +
              ", ".join(f"{k} {v}" for k, v in sorted(best.items())))


def cmd_due(days):
    limit = date.today() + timedelta(days=days)
    vault = os.path.join(HOME, "vault")
    hits = []
    for root, _, files in os.walk(vault):
        for fn in sorted(files):
            if not fn.endswith(".md"):
                continue
            p = os.path.join(root, fn)
            for ln, line in enumerate(open(p, errors="replace"), 1):
                for m in re.finditer(r"due:(\d{4}-\d{2}-\d{2})", line):
                    if date.fromisoformat(m.group(1)) <= limit:
                        hits.append((m.group(1), os.path.relpath(p, HOME), ln, line.strip()))
    if not hits:
        print("nothing due")
        return
    for d_, p, ln, line in sorted(hits):
        print(f"{d_}  {p}:{ln}  {line[:100]}")


def decode_word(word):
    """Digits a word encodes under Brown's code, plus warnings. Letter-based (Brown's rule:
    fillers may only be vowels, h, y), with common silent letters and soft sounds handled."""
    w = re.sub(r"[^a-z]", "", word.lower())
    w = SOUND.get(w, w)
    w = w.replace("dge", "j")
    w = re.sub(r"(?<=[aeiou])ge$", "j", w)
    notes = []
    w = re.sub(r"^kn", "n", w)
    w = re.sub(r"^gn", "n", w)
    w = re.sub(r"^wr", "r", w)
    w = re.sub(r"mb$", "m", w)
    w = w.replace("ph", "f").replace("gh", "")
    if "tch" in w:
        notes.append("'tch' contains a t (= 7); Brown's rule counts it, so choose another word")
    digits, i, prev = [], 0, None
    while i < len(w):
        two = w[i:i + 2]
        if two in ("ch", "sh"):
            d, i = "8", i + 2
        else:
            c = w[i]
            i += 1
            if c == "c":
                d = "0" if i < len(w) and w[i] in "eiy" else None
                if d is None:
                    notes.append("hard c is not in the code (ambiguous)")
            elif c in CODE:
                d = CODE[c]
            elif c in FILLERS:
                prev = None
                continue
            else:
                notes.append(f"'{c}' is not in the code (fillers are vowels, h, y)")
                d = None
            if d is not None and c == prev:      # doubled letter = one sound (lorry, ciggy)
                continue
            prev = c
            if d is None:
                continue
        digits.append(d)
        prev = two if two in ("ch", "sh") else prev
    return "".join(digits), sorted(set(notes))


def cmd_decode(words):
    for word in " ".join(words).split(","):
        word = word.strip()
        if not word:
            continue
        digits, notes = decode_word(word)
        print(f"{word} → {digits or '(no code letters)'}" + (f"   ⚠ {'; '.join(notes)}" if notes else ""))


def cmd_encode(number):
    n = re.sub(r"\D", "", number)
    pairs = [n[i:i + 2] for i in range(0, len(n), 2)]
    for p in pairs:
        letters = "-".join(PAIR_CODE[int(c)] for c in p)
        img = (_notebook_images() or NOTEBOOK).get(p)
        print(f"{p:>3}  {letters:<14} {img or '(no notebook image yet; build one with these letters)'}")


def cmd_notes_check():
    nums, cards, exc = load_notes()
    if not nums:
        sys.exit(f"no notes found at {NOTES_PATH}")
    conflicts, info = [], []
    for k, occ in sorted(nums.items(), key=lambda kv: int(kv[0]) + (100 if len(kv[0]) == 1 else 0)):
        if len({o[0] for o in occ}) > 1:
            conflicts.append(f"{k}: two different pictures: " + "; ".join(f"'{o[0]}' (line {o[1]})" for o in occ))
        img, ln = occ[0]
        for alt in _alternatives(img):
            d, warn = decode_word(alt)
            if d != k:
                conflicts.append(f"{k}: '{alt}' decodes to {d or 'nothing'}, not {k} (line {ln})")
    for card, (img, ln) in sorted(cards.items()):
        rank, su = card[:-1], card[-1]
        if rank in ("A", "J", "Q", "K") or card in exc:
            continue
        want = ("0" if su == "S" else "") + ("0" if rank == "10" else str(int(rank)) if rank != "A" else "1")
        want = want if rank != "10" else ("00" if su == "S" else "0")
        alts = _alternatives(img)
        if not any(decode_word(a)[0] == want for a in alts):
            conflicts.append(f"{rank}{'♠♥♦♣'['SHDC'.index(su)]}: '{img}' decodes to "
                             f"{'/'.join(decode_word(a)[0] or '-' for a in alts)}, expected {want} (line {ln})")
    seen = {}
    for k, occ in nums.items():
        for alt in _alternatives(occ[0][0]):
            seen.setdefault(alt.lower(), set()).add(k)
    for card, (img, _) in cards.items():
        for alt in _alternatives(img):
            seen.setdefault(alt.lower(), set()).add(card)
    for word, where in sorted(seen.items()):
        if len(where) > 1:
            conflicts.append(f"'{word}' is used for more than one thing: {', '.join(sorted(where))}")
    missing = [f"{i:02d}" for i in range(10, 100) if f"{i:02d}" not in nums]
    if missing:
        info.append("no picture yet for: " + ", ".join(missing))
    missing_cards = [r + s for s in "SHDC" for r in RANKS_ALL if r + s not in cards]
    if missing_cards:
        info.append("no picture yet for cards: " + ", ".join(missing_cards))
    print(f"notes: {len(nums)} numbers, {len(cards)} cards, exceptions: {', '.join(sorted(exc)) or 'none'}")
    for i in info:
        print("info: " + i)
    if conflicts:
        print(f"\n{len(conflicts)} conflict(s):")
        for c in conflicts:
            print("  ⚠ " + c)
        sys.exit(1)
    print("no conflicts")


def cmd_weekday(s, guess=None):
    d = date.fromisoformat(s)
    truth = WEEKDAYS[d.weekday()]
    if guess:
        print("correct" if guess.lower()[:3] == truth[:3] else f"no, it's {truth.capitalize()}")
    else:
        print(truth.capitalize())


def main():
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
        return
    c = a[0]
    if c == "gen":
        cmd_gen(a[1], int(a[2]) if len(a) > 2 else None)
    elif c == "quiz":
        cmd_quiz(a[1])
    elif c == "check":
        cmd_check(a[1], a[2:])
    elif c == "show":
        cmd_show(a[1])
    elif c == "log":
        cmd_log(a[1] if len(a) > 1 else None)
    elif c == "due":
        cmd_due(int(a[a.index("--days") + 1]) if "--days" in a else 0)
    elif c == "decode":
        cmd_decode(a[1:])
    elif c == "notes-check":
        cmd_notes_check()
    elif c == "encode":
        cmd_encode(a[1])
    elif c == "weekday":
        cmd_weekday(a[1], a[2] if len(a) > 2 else None)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
