#!/usr/bin/env python3
"""imagine.py: turn memory-plan pictures into images (Nano Banana / ChatGPT image models).

Stdlib only. Reads a vault topic file (~/.hyperthymesia/vault/<topic>.md) whose table has a
"Picture" column (see templates/vault-topic.md), builds one consistent prompt per row, and either:

  prompts  <vault.md> [--rows 1,3-5]
           Free route: write <topic>-prompts.md with copy-paste prompts for the Gemini app
           (Nano Banana) or ChatGPT. No API key needed.
  generate <vault.md> --provider gemini|openai [--rows …] [--model ID] [--quality low|medium|high]
           [--dry-run]
           API route: generate each image, save it under ~/.hyperthymesia/images/<topic>/, write a
           walkable gallery (index.html), and add an Image column to the vault table.
  one "<picture>" --provider gemini|openai [--out file.png] [--dry-run]
           A single image from a one-line picture description.
  attach <vault.md> <row> <image-file>
           Attach an image you made in the Gemini app or ChatGPT to a row (copies it into the
           images folder and links it in the table and gallery).

Keys come from the environment only and are never written anywhere:
  GEMINI_API_KEY (or GOOGLE_API_KEY) for --provider gemini
  OPENAI_API_KEY for --provider openai
Models default to Nano Banana 2.1 and GPT Image 2.5 Flare; override with --model or
HYPERTHYMESIA_GEMINI_MODEL / HYPERTHYMESIA_OPENAI_MODEL.
"""
import argparse
import base64
import html
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.request

HOME = os.path.expanduser(os.environ.get("HYPERTHYMESIA_HOME", "~/.hyperthymesia"))
GEMINI_MODEL = os.environ.get("HYPERTHYMESIA_GEMINI_MODEL", "gemini-nano-banana-2.1")
OPENAI_MODEL = os.environ.get("HYPERTHYMESIA_OPENAI_MODEL", "gpt-image-2.5-flare")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
OPENAI_URL = "https://api.openai.com/v1/images/generations"

STYLE = ("One vivid, exaggerated, surreal cartoon illustration for a memory palace. "
         "Bright saturated colours, strong motion, the action happening right now, a clear main subject "
         "filling the frame, slightly absurd scale. No text, no letters, no numbers, no captions, "
         "no speech bubbles.")


# ---------- vault table ----------

def read_vault(path):
    lines = open(path, encoding="utf-8").read().split("\n")
    meta = {"topic": os.path.splitext(os.path.basename(path))[0], "palace": ""}
    m = re.search(r"\*\*Palace:\*\*\s*([^·\n(]+)", "\n".join(lines))
    if m:
        meta["palace"] = m.group(1).strip()
    head = next((i for i, l in enumerate(lines) if l.startswith("|") and "picture" in l.lower()), None)
    if head is None:
        sys.exit(f"{path}: no table with a 'Picture' column (see templates/vault-topic.md)")
    cols = [c.strip().lower() for c in lines[head].strip().strip("|").split("|")]
    rows = []
    for i in range(head + 2, len(lines)):
        if not lines[i].startswith("|"):
            break
        cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
        row = dict(zip(cols, cells))
        row["_line"] = i
        rows.append(row)
    return lines, head, cols, rows, meta


def col(row, *names):
    for n in names:
        for k, v in row.items():
            if k.startswith(n):
                return v
    return ""


def pick_rows(rows, spec):
    if not spec:
        return rows
    want = set()
    for part in spec.split(","):
        a, _, b = part.partition("-")
        want.update(range(int(a), int(b or a) + 1))
    return [r for r in rows if re.sub(r"\D", "", col(r, "#")) and int(re.sub(r"\D", "", col(r, "#"))) in want]


def prompt_for(row, meta):
    picture = re.sub(r"[*_`]", "", col(row, "picture"))
    locus = re.sub(r"[✋*_`]", "", col(row, "locus", "link")).strip()
    where = f" It happens at the {locus}" + (f" in {meta['palace']}" if meta["palace"] else "") + "." if locus else ""
    return f"{STYLE} Scene: {picture}.{where}"


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "image"


# ---------- providers ----------

def _post(url, body, headers):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:600]
        raise RuntimeError(f"HTTP {e.code}: {detail}")


def find_image_b64(obj):
    """Find base64 image data anywhere in a JSON response (handles Gemini interactions
    output_image.data, generateContent inlineData.data, and OpenAI b64_json)."""
    if isinstance(obj, dict):
        for k in ("b64_json", "data"):
            v = obj.get(k)
            if isinstance(v, str) and len(v) > 200 and re.fullmatch(r"[A-Za-z0-9+/=\s]+", v[:400]):
                return v
        for v in obj.values():
            hit = find_image_b64(v)
            if hit:
                return hit
    elif isinstance(obj, list):
        for v in obj:
            hit = find_image_b64(v)
            if hit:
                return hit
    return None


def find_text(obj):
    if isinstance(obj, dict):
        for k in ("text", "revised_prompt", "message", "finishReason", "finish_reason"):
            if isinstance(obj.get(k), str):
                return obj[k]
        for v in obj.values():
            t = find_text(v)
            if t:
                return t
    elif isinstance(obj, list):
        for v in obj:
            t = find_text(v)
            if t:
                return t
    return None


def request_for(provider, prompt, model, quality):
    if provider == "gemini":
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        body = {"model": model or GEMINI_MODEL, "input": [{"type": "text", "text": prompt}],
                "response_format": {"type": "image", "aspect_ratio": "4:3"}}
        return GEMINI_URL, body, {"x-goog-api-key": key or ""}, key
    key = os.environ.get("OPENAI_API_KEY")
    body = {"model": model or OPENAI_MODEL, "prompt": prompt, "size": "1536x1024",
            "quality": quality, "n": 1, "output_format": "png"}
    return OPENAI_URL, body, {"Authorization": f"Bearer {key or ''}"}, key


def generate_image(provider, prompt, out, model=None, quality="medium", dry=False):
    url, body, headers, key = request_for(provider, prompt, model, quality)
    if dry:
        print(f"[dry-run] POST {url}\n{json.dumps(body, indent=2)}")
        return False
    if not key:
        env = "GEMINI_API_KEY" if provider == "gemini" else "OPENAI_API_KEY"
        sys.exit(f"{env} is not set. Set it in your shell, or use `prompts` for the free copy-paste route.")
    resp = _post(url, body, headers)
    b64 = find_image_b64(resp)
    if not b64:
        why = find_text(resp) or json.dumps(resp)[:400]
        raise RuntimeError(f"no image in the response (often a content-policy refusal): {why}")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "wb") as f:
        f.write(base64.b64decode(b64))
    return True


# ---------- outputs ----------

def images_dir(meta):
    d = os.path.join(HOME, "images", slug(meta["topic"]))
    os.makedirs(d, exist_ok=True)
    return d


def write_gallery(meta, rows, images):
    d = images_dir(meta)
    cards = []
    for r in rows:
        n = re.sub(r"\D", "", col(r, "#"))
        img = images.get(n)
        fig = (f'<img src="{html.escape(os.path.basename(img))}" alt="{html.escape(col(r, "picture"))}">'
               if img else '<div class="none">no image yet</div>')
        cards.append(f'<li><div class="n">{html.escape(n)}</div>{fig}<div class="t"><b>{html.escape(col(r, "locus", "link"))}</b>'
                     f' · {html.escape(col(r, "item"))}<br>{html.escape(col(r, "picture"))}</div></li>')
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{html.escape(meta['topic'])}: palace walk</title>
<style>body{{margin:0;padding:24px;font:16px/1.5 system-ui,sans-serif;background:#10172a;color:#e7ecff}}
h1{{font-weight:600}}ol{{list-style:none;padding:0;display:grid;gap:20px;grid-template-columns:repeat(auto-fill,minmax(300px,1fr))}}
li{{background:#172038;border-radius:14px;overflow:hidden;position:relative}}img{{width:100%;display:block;aspect-ratio:3/2;object-fit:cover}}
.none{{aspect-ratio:3/2;display:grid;place-items:center;color:#9aa6c7}}.n{{position:absolute;top:8px;left:8px;background:#ff7a96;color:#10172a;
font-weight:700;border-radius:999px;padding:2px 10px}}.t{{padding:10px 14px 14px}}</style></head><body>
<h1>{html.escape(meta['topic'])}{(' · ' + html.escape(meta['palace'])) if meta['palace'] else ''}</h1>
<p>Walk it in order. Look at each picture for two seconds, then close your eyes and see it at its place.</p>
<ol>{''.join(cards)}</ol></body></html>"""
    path = os.path.join(d, "index.html")
    open(path, "w", encoding="utf-8").write(page)
    return path


def link_in_vault(path, lines, head, cols, rows, images, meta):
    """Add (or fill) an Image column with links to the saved images."""
    rel_base = os.path.relpath(images_dir(meta), os.path.dirname(os.path.abspath(path)))
    if "image" not in cols:
        lines[head] = lines[head].rstrip().rstrip("|") + "| Image |"
        lines[head + 1] = lines[head + 1].rstrip().rstrip("|") + "|---|"
        for r in rows:
            lines[r["_line"]] = lines[r["_line"]].rstrip().rstrip("|") + "| |"
        cols = cols + ["image"]
    ci = cols.index("image")
    for r in rows:
        n = re.sub(r"\D", "", col(r, "#"))
        if n in images:
            cells = [c.strip() for c in lines[r["_line"]].strip().strip("|").split("|")]
            while len(cells) <= ci:
                cells.append("")
            cells[ci] = f"[view]({rel_base}/{os.path.basename(images[n])})"
            lines[r["_line"]] = "| " + " | ".join(cells) + " |"
    open(path, "w", encoding="utf-8").write("\n".join(lines))


def existing_images(meta):
    d = images_dir(meta)
    found = {}
    for f in os.listdir(d):
        m = re.match(r"(\d+)-.*\.(png|jpe?g|webp)$", f, re.I)
        if m:
            found[str(int(m.group(1)))] = os.path.join(d, f)
    return found


# ---------- commands ----------

def cmd_prompts(a):
    _, _, _, rows, meta = read_vault(a.vault)
    rows = pick_rows(rows, a.rows)
    out = os.path.join(os.path.dirname(os.path.abspath(a.vault)), f"{meta['topic']}-prompts.md")
    parts = [f"# {meta['topic']}: image prompts\n",
             "Paste each prompt into the Gemini app (Nano Banana) or ChatGPT. Save each image, then run\n"
             f"`imagine.py attach {a.vault} <row> <image-file>` to link it.\n"]
    for r in rows:
        n = re.sub(r"\D", "", col(r, "#"))
        parts.append(f"## {n}. {col(r, 'item')} ({col(r, 'locus', 'link')})\n\n```\n{prompt_for(r, meta)}\n```\n")
    open(out, "w", encoding="utf-8").write("\n".join(parts))
    print(f"wrote {len(rows)} prompts to {out}")


def cmd_generate(a):
    lines, head, cols, rows, meta = read_vault(a.vault)
    chosen = pick_rows(rows, a.rows)
    images = existing_images(meta)
    failed = []
    for r in chosen:
        n = re.sub(r"\D", "", col(r, "#"))
        out = os.path.join(images_dir(meta), f"{int(n):02d}-{slug(col(r, 'item'))}.png")
        try:
            if generate_image(a.provider, prompt_for(r, meta), out, a.model, a.quality, a.dry_run):
                images[n] = out
                print(f"  {n}. {col(r, 'item')} → {out}")
        except RuntimeError as e:
            failed.append((n, str(e)))
            print(f"  {n}. {col(r, 'item')} FAILED: {e}")
    if a.dry_run:
        return
    gallery = write_gallery(meta, rows, images)
    link_in_vault(a.vault, lines, head, cols, rows, images, meta)
    print(f"gallery: {gallery}")
    if failed:
        print(f"{len(failed)} failed. A content-policy refusal usually means a crude or violent picture: "
              "rephrase that row's prompt more mildly for the image (keep the original picture in your head).")
        sys.exit(1)


def cmd_one(a):
    out = a.out or os.path.join(HOME, "images", "single", f"{slug(a.picture)}.png")
    prompt = f"{STYLE} Scene: {a.picture}."
    if generate_image(a.provider, prompt, out, a.model, a.quality, a.dry_run):
        print(out)


def cmd_attach(a):
    lines, head, cols, rows, meta = read_vault(a.vault)
    ext = os.path.splitext(a.image)[1].lower() or ".png"
    row = next((r for r in rows if re.sub(r"\D", "", col(r, "#")) == str(a.row)), None)
    if not row:
        sys.exit(f"no row {a.row} in {a.vault}")
    d = images_dir(meta)
    dest = os.path.join(d, f"{int(a.row):02d}-{slug(col(row, 'item'))}{ext}")
    shutil.copyfile(a.image, dest)
    for f in os.listdir(d):   # one image per row: drop the one this replaces
        if re.match(rf"0*{int(a.row)}-.*\.(png|jpe?g|webp)$", f, re.I) and os.path.join(d, f) != dest:
            os.remove(os.path.join(d, f))
    images = existing_images(meta)
    write_gallery(meta, rows, images)
    link_in_vault(a.vault, lines, head, cols, rows, images, meta)
    print(f"attached {dest}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("prompts"); s.add_argument("vault"); s.add_argument("--rows"); s.set_defaults(fn=cmd_prompts)
    s = sub.add_parser("generate"); s.add_argument("vault"); s.add_argument("--provider", choices=["gemini", "openai"], required=True)
    s.add_argument("--rows"); s.add_argument("--model"); s.add_argument("--quality", default="medium")
    s.add_argument("--dry-run", action="store_true"); s.set_defaults(fn=cmd_generate)
    s = sub.add_parser("one"); s.add_argument("picture"); s.add_argument("--provider", choices=["gemini", "openai"], required=True)
    s.add_argument("--out"); s.add_argument("--model"); s.add_argument("--quality", default="medium")
    s.add_argument("--dry-run", action="store_true"); s.set_defaults(fn=cmd_one)
    s = sub.add_parser("attach"); s.add_argument("vault"); s.add_argument("row", type=int); s.add_argument("image")
    s.set_defaults(fn=cmd_attach)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
