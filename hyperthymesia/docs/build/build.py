import json, re, html, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "scripts"))
from memgym import load_notes  # notes.md is the single source of truth
T = open(os.path.join(HERE, "template.html")).read()
LABEL = {"linking": "Linking chain: telephone, sausage, monkey, button, book, each linked to the next by an action",
  "palace": "Floor plan of a room with ten loci numbered clockwise from the left of the door, with markers at 5 and 10",
  "code": "Brown's number code: 0 z or s, 1 l, 2 n, 3 m, 4 r, 5 f or v, 6 b or p, 7 t, 8 ch sh or j, 9 g",
  "pin": "1743 becomes L T R M, then Light Room, linked to a cash machine in a white room full of lights",
  "cards": "Nine of hearts becomes H plus g, hag. Six of spades becomes S plus b, sob",
  "football": "Everton 2 Watford 0 in 1983-84: 84 is chair, E2 W0 is E N W S, a chair spinning to the compass points",
  "names": "Mike becomes a microphone, linked to his large nose: a microphone sticking out of his face",
  "mm-loop": "Notice it, turn it into a picture, lock it to something you know, review it",
  "mm-review": "Review schedule: now, 1 hour, that evening, 3 days, 1 week, 3 weeks, 2 months; a miss means rebuild the image",
  "mm-chooser": "Which technique for which kind of information"}
def svg(name):
    s = open(os.path.join(HERE, "svg", f"{name}.svg")).read()
    s = re.sub(r"<\?xml[^>]*>", "", s)
    return s.replace("<svg ", f'<svg role="img" aria-label="{html.escape(LABEL[name])}" ', 1)
T = re.sub(r"\{\{svg:([\w-]+)\}\}", lambda m: svg(m.group(1)), T)

NUMS, CARDS, _EXC = load_notes()
NB = {k: v[0][0] for k, v in NUMS.items()}
L = ["s","l","n","m","r","f","b","t","ch","g"]
rows = []
for tens in range(1, 10):
    cells = []
    for u in range(10):
        k = f"{tens}{u}"
        pair = f"{L[tens]}-{L[u]}"
        if k in NB:
            cells.append(f'<td><span class="w">{NB[k]}</span></td>')
        elif k in ("28", "38"):
            bad = {"28": "notch", "38": "match"}[k]
            cells.append(f'<td><span class="pick">{pair}</span><br><span class="warn" title="{bad} has a t, so it encodes {k[0]}7{k[1]}">not “{bad}”</span></td>')
        else:
            cells.append(f'<td><span class="pick">{pair}</span></td>')
    rows.append(f'<tr><td class="k">{tens}_</td>{"".join(cells)}</tr>')
head = "".join(f"<th>_{u}</th>" for u in range(10))
T = T.replace("{{table:numbers}}", f'<table class="grid"><tr><th></th>{head}</tr>{"".join(rows)}</table>')

ranks = ["A","2","3","4","5","6","7","8","9","10","J","Q","K"]
cards = {}
for s_ in "SHDC":
    for r in ranks:
        img = CARDS.get(r + s_, (None, 0))[0]
        cards[r + s_] = {"w": img} if img else {"w": "your pick", "pick": True}
sym = {"S": "♠ Spades", "H": "♥ Hearts", "D": "♦ Diamonds", "C": "♣ Clubs"}
th = "".join(f'<th class="suit-{s.lower()}">{sym[s]}</th>' for s in "SHDC")
trs = []
for r in ranks:
    tds = []
    for s in "SHDC":
        v = cards[r + s]
        tds.append(f'<td><span class="{"pick" if v.get("pick") else "w"}">{html.escape(v["w"])}</span></td>')
    trs.append(f'<tr><td class="k">{r}</td>{"".join(tds)}</tr>')
T = T.replace("{{table:cards}}", f'<table class="grid"><tr><th></th>{th}</tr>{"".join(trs)}</table>')
T = T.replace("{{json:notebook}}", json.dumps(NB)).replace("{{json:cards}}", json.dumps(cards, ensure_ascii=False))
assert "{{" not in T, re.findall(r"\{\{[^}]+\}\}", T)
open(os.path.join(HERE, "..", "memory-palace-workbook.html"), "w").write(T)
# Standalone copy for GitHub Pages (repo-root docs/hyperthymesia/index.html): the artifact viewer adds the
# document skeleton itself, a plain web host doesn't.
SITE_ROOT = os.path.join(HERE, "..", "..", "..", "docs")
SITE = os.path.join(SITE_ROOT, "hyperthymesia")
os.makedirs(SITE, exist_ok=True)
page = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        '<meta name="description" content="An illustrated, hands-on course in Derren Brown\'s memory techniques: '
        'linking, memory palaces, pegs, his number code, cards, names and reviewing.">\n'
        '<style>html{-webkit-text-size-adjust:100%}img{max-width:100%}[hidden]{display:none!important}</style>\n')
head_end = T.index("</style>") + len("</style>")
page += T[:head_end] + "\n</head>\n<body>\n" + T[head_end:] + "\n</body>\n</html>\n"
open(os.path.join(SITE, "index.html"), "w").write(page)
open(os.path.join(SITE_ROOT, ".nojekyll"), "w").write("")
print(len(T))
