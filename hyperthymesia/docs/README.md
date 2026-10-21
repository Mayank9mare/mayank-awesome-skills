# Memory Palace Workbook

`memory-palace-workbook.html` is an illustrated, interactive course in the techniques this skill teaches.
It's a single self-contained page: open it in a browser.

- `diagrams/*.excalidraw`: hand-drawn diagrams made with `excalidraw-cli` (open them at excalidraw.com).
- `diagrams/*.mmd` + `mermaid-config.json`: Mermaid sources, rendered with `mmdc` (hand-drawn look).
- `build/build.py` rebuilds the page. It reads the numbers and cards straight from
  `../references/notes.md`, so after changing the notes just run `python3 docs/build/build.py`.
  Teaching text lives in `build/template.html`; rendered diagrams are cached in `build/svg/`.
- To change a diagram: edit `build/specs.py` (Excalidraw elements; it calls `excalidraw create`) or
  `diagrams/*.mmd`, then re-render. `node build/render.js` turns `.excalidraw` into theme-aware SVG
  with rough.js (`npm i roughjs`); render Mermaid with
  `mmdc -i diagrams/X.mmd -c diagrams/mermaid-config.json -b transparent -I mm-X`, swap the
  placeholder colours (#fe0001… → var(--…), see build history), and save it to `build/svg/mm-X.svg`.
