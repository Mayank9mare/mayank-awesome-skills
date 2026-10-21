# Memory Palace Workbook

`memory-palace-workbook.html` is an illustrated, interactive course in the techniques this skill teaches.
It's a single self-contained page: open it in a browser.

- `diagrams/*.excalidraw`: hand-drawn diagrams made with `excalidraw-cli` (open them at excalidraw.com).
- `diagrams/*.mmd` + `mermaid-config.json`: Mermaid sources, rendered with `mmdc` (hand-drawn look).
- `build/`: `specs.py` writes the Excalidraw element JSON and runs `excalidraw create`; `render.js`
  turns `.excalidraw` into theme-aware SVG with rough.js (`npm i roughjs`); `build.py` puts the SVGs
  and tables into `template.html`. Run them from one working directory in that order, after `mmdc`
  has rendered `mm/*.svg` into `svg/mm-*.svg`.
