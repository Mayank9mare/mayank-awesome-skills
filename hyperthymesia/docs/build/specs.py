"""Write excalidraw element specs (JSON) for each diagram, then build with excalidraw-cli."""
import json, subprocess, os

BLUE, GREEN, ORANGE, PURPLE, RED, YELLOW, TEAL = ("#a5d8ff", "#b2f2bb", "#ffd8a8", "#d0bfff",
                                                  "#ffc9c9", "#fff3bf", "#c3fae8")
INKRED = "#e03131"


def box(i, x, y, w, h, text, fill=None, fs=20, shape="rectangle", dashed=False):
    e = {"type": shape, "id": i, "x": x, "y": y, "width": w, "height": h,
         "label": {"text": text, "fontSize": fs}}
    if fill:
        e.update(backgroundColor=fill, fillStyle="solid")
    if dashed:
        e["strokeStyle"] = "dashed"
    return e


def arrow(i, x1, y1, x2, y2, label=None, a=None, b=None, dashed=False, color=None, pts=None):
    p = pts or [[0, 0], [x2 - x1, y2 - y1]]
    e = {"type": "arrow", "id": i, "x": x1, "y": y1, "width": abs(p[-1][0]), "height": abs(p[-1][1]),
         "points": p, "endArrowhead": "arrow"}
    if label:
        e["label"] = {"text": label, "fontSize": 16}
    if a:
        e["startBinding"] = {"elementId": a[0], "fixedPoint": a[1]}
    if b:
        e["endBinding"] = {"elementId": b[0], "fixedPoint": b[1]}
    if dashed:
        e["strokeStyle"] = "dashed"
    if color:
        e["strokeColor"] = color
    return e


def text(i, x, y, t, fs=18, color=None):
    e = {"type": "text", "id": i, "x": x, "y": y, "text": t, "fontSize": fs}
    if color:
        e["strokeColor"] = color
    return e


D = {}

# 1. Linking chain (snake: 3 across, then down and back) -----------------------------
els = [box("w0", 0, 40, 150, 64, "telephone", BLUE, 24), box("w1", 220, 40, 150, 64, "sausage", YELLOW, 24),
       box("w2", 440, 40, 150, 64, "monkey", GREEN, 24), box("w3", 440, 210, 150, 64, "button", ORANGE, 24),
       box("w4", 220, 210, 150, 64, "book", PURPLE, 24),
       arrow("l0", 150, 72, 220, 72, a=("w0", [1, .5]), b=("w1", [0, .5])),
       arrow("l1", 370, 72, 440, 72, a=("w1", [1, .5]), b=("w2", [0, .5])),
       arrow("l2", 515, 104, 515, 210, a=("w2", [.5, 1]), b=("w3", [.5, 0])),
       arrow("l3", 440, 242, 370, 242, pts=[[0, 0], [-70, 0]], a=("w3", [0, .5]), b=("w4", [1, .5])),
       text("t0", 128, 116, "it's a greasy\nsausage", 18), text("t1", 352, 116, "snatched\nby a", 18),
       text("t2", 528, 138, "can't do up\nits huge", 18), text("t3", 350, 286, "pops off\ninto a", 18),
       text("n1", 0, 350, "Each picture holds only two things.\nLose one link and the rest of the chain goes with it.", 19, INKRED)]
D["linking"] = els

# 2. Memory palace floor plan ----------------------------------------------------
els = [{"type": "rectangle", "id": "room", "x": 0, "y": 0, "width": 620, "height": 420,
        "backgroundColor": "#f8f9fa", "fillStyle": "solid"}]
loci = [  # (n, x, y, label) clockwise from the immediate left of the door (door at bottom centre)
    (1, 150, 330, "coat hook"), (2, 30, 250, "bookshelf"), (3, 30, 140, "window"),
    (4, 40, 30, "armchair"), (5, 190, 30, "lamp  ✋5"), (6, 340, 30, "fireplace"),
    (7, 480, 30, "painting"), (8, 490, 140, "sofa"), (9, 490, 250, "TV"), (10, 400, 330, "plant  10"),
]
fills = {5: YELLOW, 10: YELLOW}
for n, x, y, lab in loci:
    els.append(box(f"p{n}", x, y, 110, 54, f"{n}. {lab}" if n not in (5, 10) else f"{n}. {lab.split()[0]}",
                   fills.get(n, TEAL), 17, "ellipse" if n in (5, 10) else "rectangle"))
els.append(box("door", 270, 395, 80, 40, "door", ORANGE, 16))
els.append(text("you", 262, 448, "you start here", 16))
# clockwise route
route = [[0, 0], [-100, -68], [-140, -105], [-140, -245], [-110, -282], [0, -286], [140, -282],
         [170, -245], [170, -105], [128, -66]]
els.append(arrow("route", 300, 380, 0, 0, pts=route, dashed=True, color=INKRED))
els.append(text("rt", 205, 175, "clockwise,\nstarting on your\nimmediate left", 18, INKRED))
els.append(text("m5", 0, 490, "✋ A hand at every 5th locus,\nso you can jump straight\nto #5 or #10.", 19))
els.append(text("in", 330, 490, "Put the action INSIDE things:\nDave sits in the fridge, so\nthe space next to it stays free.", 19))
D["palace"] = els

# 3. Number code tiles -----------------------------------------------------------
code = [("0", "z / s", "z in zero"), ("1", "l", "looks like 1"), ("2", "n", "two down-strokes"),
        ("3", "m", "three down-strokes"), ("4", "r", "fouR"), ("5", "f / v", "FiVe"),
        ("6", "b / p", "b looks like 6"), ("7", "t", "7 ≈ capital T"), ("8", "ch sh j", "the gh in eiGHt"),
        ("9", "g", "g looks like 9")]
els = []
for k, (d, l, why) in enumerate(code):
    r, c = divmod(k, 5)
    x, y = c * 170, r * 170
    els.append(box(f"c{k}", x, y, 150, 110, f"{d}  →  {l}", [BLUE, GREEN, YELLOW, ORANGE, PURPLE][c], 24))
    els.append(text(f"cw{k}", x + 4, y + 118, why, 17))
els.append(text("fill", 0, 345, "Fill the gaps with vowels, h and y only. Any other letter changes the number.", 17, INKRED))
D["code"] = els

# 4. PIN: 1743 (two rows) ------------------------------------------------------------
els = [box("n", 0, 30, 120, 64, "1743", YELLOW, 28),
       box("l", 190, 30, 150, 64, "L  T  R  M", BLUE, 24),
       box("w", 410, 30, 180, 64, "Light Room", GREEN, 24),
       box("s", 340, 170, 250, 110, "a cash machine in a\ndazzling white room\nfull of lights", ORANGE, 19),
       arrow("a0", 120, 62, 190, 62, a=("n", [1, .5]), b=("l", [0, .5])),
       arrow("a1", 340, 62, 410, 62, a=("l", [1, .5]), b=("w", [0, .5])),
       arrow("a2", 500, 94, 465, 170, a=("w", [.5, 1]), b=("s", [.5, 0])),
       text("t0", 124, 104, "code", 18), text("t1", 336, 104, "+ vowels", 18),
       text("t2", 120, 205, "link it to\nthe cash machine", 19, INKRED)]
D["pin"] = els

# 5. Cards -----------------------------------------------------------------------
els = []
for r, (card, suit, num, cons, word, fill) in enumerate([("9 ♥", "H", "9", "H · g", "HAG", RED),
                                                          ("6 ♠", "S", "6", "S · b", "SOB", BLUE)]):
    y = r * 110
    els += [box(f"k{r}", 0, y, 90, 80, card, fill, 26),
            box(f"s{r}", 150, y + 8, 150, 64, f"{suit} + {num}", None, 20),
            box(f"c{r}", 360, y + 8, 120, 64, cons, None, 20),
            box(f"w{r}", 540, y + 8, 130, 64, word, YELLOW, 24)]
    for k, (a_, b_, xs, xe) in enumerate([(f"k{r}", f"s{r}", 90, 150), (f"s{r}", f"c{r}", 300, 360),
                                           (f"c{r}", f"w{r}", 480, 540)]):
        els.append(arrow(f"a{r}{k}", xs, y + 40, xe, y + 40, a=(a_, [1, .5]), b=(b_, [0, .5])))
els.append(text("h1", 150, 225, "suit initial + rank code", 16))
els.append(text("h2", 0, 255, "Court cards are characters, since J would clash with j = 8.\nHearts: Cupid, bride, bridegroom.", 16, INKRED))
D["cards"] = els

# 6. Football scores (top to bottom) ----------------------------------------------------
els = [box("m", 150, 0, 300, 76, "Everton 2 – Watford 0\nseason 1983–84", YELLOW, 21),
       box("y", 0, 140, 220, 62, "84 → ch · r", BLUE, 22),
       box("e", 380, 140, 220, 62, "E2 W0 → E N W S", BLUE, 22),
       box("c", 40, 260, 140, 62, "CHAIR", GREEN, 24),
       box("k", 420, 260, 140, 62, "compass", GREEN, 22),
       box("s", 150, 380, 300, 104, "a chair spinning to\npoint East, North,\nWest, South", ORANGE, 20),
       arrow("a1", 230, 76, 110, 140, a=("m", [.27, 1]), b=("y", [.5, 0])),
       arrow("a2", 370, 76, 490, 140, a=("m", [.73, 1]), b=("e", [.5, 0])),
       arrow("a3", 110, 202, 110, 260, a=("y", [.5, 1]), b=("c", [.5, 0])),
       arrow("a4", 490, 202, 490, 260, a=("e", [.5, 1]), b=("k", [.5, 0])),
       arrow("a5", 110, 322, 230, 380, a=("c", [.5, 1]), b=("s", [.27, 0])),
       arrow("a6", 490, 322, 370, 380, a=("k", [.5, 1]), b=("s", [.73, 0]))]
D["football"] = els

# 7. Names ------------------------------------------------------------------------
els = [box("n", 0, 0, 170, 64, "\"Mike\"", YELLOW, 24),
       box("i", 0, 130, 170, 64, "microphone", BLUE, 22),
       box("f", 300, 130, 190, 64, "his large nose", PURPLE, 22),
       box("l", 140, 270, 300, 90, "a microphone sticking out\nof the middle of his face", GREEN, 18),
       arrow("a1", 85, 64, 85, 130, label=None, a=("n", [.5, 1]), b=("i", [.5, 0])),
       arrow("a2", 85, 194, 240, 270, a=("i", [.5, 1]), b=("l", [.3, 0])),
       arrow("a3", 395, 194, 340, 270, a=("f", [.5, 1]), b=("l", [.7, 0])),
       text("t1", 100, 84, "name → image", 15),
       text("t2", 300, 92, "something on the face", 15),
       text("t3", 470, 300, "link them", 16, INKRED)]
D["names"] = els

os.makedirs("ex", exist_ok=True)
for name, els in D.items():
    with open(f"ex/{name}.json", "w") as f:
        json.dump(els, f)
    subprocess.run(["excalidraw", "create", f"ex/{name}.json", "-o", f"ex/{name}.excalidraw",
                    "--no-checkpoint"], check=True, capture_output=True)
    print("built", name)
