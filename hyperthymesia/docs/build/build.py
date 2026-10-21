import json, re, html
T = open("template.html").read()
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
    s = open(f"svg/{name}.svg").read()
    s = re.sub(r"<\?xml[^>]*>", "", s)
    return s.replace("<svg ", f'<svg role="img" aria-label="{html.escape(LABEL[name])}" ', 1)
T = re.sub(r"\{\{svg:([\w-]+)\}\}", lambda m: svg(m.group(1)), T)

NB = {"0":"zoo","1":"ale","2":"hen","3":"ham","4":"whore","5":"hive","6":"bee","7":"tea","8":"shoe","9":"goo",
 "10":"lice","11":"lily","12":"line","13":"lime","14":"lorry","15":"life","16":"lip","17":"lit","18":"lash","19":"leg",
 "20":"nose","21":"nail","22":"noon","23":"name","24":"Nero","25":"knife","26":"nob","27":"knight","29":"nog",
 "31":"mole","32":"man","33":"mum","36":"map","37":"mat","39":"mug","40":"rose","41":"role","42":"rain","43":"ram",
 "44":"roar","47":"root / rat","48":"rash","50":"fuse","52":"fan","30":"maze / mass","34":"more / merry","45":"rave","46":"rap","51":"fall","35":"mf","49":"rag","28":"Nash","38":"mesh","53":"foam", "54":"fire", "55":"fife", "56":"fob", "57":"feet", "58":"fish", "59":"fig", "60":"bus", "61":"ball", "62":"bone", "63":"bomb", "64":"bear", "65":"beef", "66":"baby", "67":"bat", "68":"bush", "69":"bag", "70":"toes", "71":"tail", "72":"tin", "73":"tomb", "74":"tyre", "75":"toffee", "76":"tub", "77":"tattoo", "78":"Taj", "79":"toga", "80":"chess", "81":"shell", "82":"chain", "83":"jam", "87":"jet", "88":"choo-choo", "89":"jug", "90":"goose", "91":"gull", "92":"gun", "93":"gum", "94":"gear", "95":"Goofy", "96":"guppy", "97":"goat", "98":"gash", "99":"Gaga","84":"chair","85":"shave","86":"shop"}
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
C = {
 "S": ["Grim Reaper","sun","Sam / sum","sore","safe","sob","soot","sash","ciggy","sissy","boy digging / Beelzebub","housekeeper","gardener / Dante (Lucifer)"],
 "H": ["a big love heart","lovers (two hearts)","home","hair","hoof","hoop","hat","hedge","hag","hose","Cupid","bride","bridegroom"],
 "D": ["a big sparkly diamond","Don","Dom","door","dove","DB (Derren Brown)","dot","dish","dog","dizzy","diamond thief","the Queen","old jeweller"],
 "C": ["a big club","can","cam","car","cough","cab","cat","cash","cog","kiss","young athlete","brothel madam","bouncer"]}
cards = {}
for s, words in C.items():
    for r, w in zip(ranks, words):
        if w.startswith("?"):
            cards[r + s] = {"w": "your pick: " + w[1:], "pick": True}
        else:
            cards[r + s] = {"w": w}
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
open("memory-palace-workbook.html", "w").write(T)
print(len(T))
