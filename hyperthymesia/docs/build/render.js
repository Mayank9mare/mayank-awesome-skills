// Render .excalidraw files to theme-aware hand-drawn SVG using rough.js (what Excalidraw uses).
const fs = require("fs");
const rough = require("roughjs/bundled/rough.cjs.js");
const gen = rough.generator();

const FILL = { "#a5d8ff": "var(--f-blue)", "#b2f2bb": "var(--f-green)", "#ffd8a8": "var(--f-orange)",
  "#d0bfff": "var(--f-purple)", "#ffc9c9": "var(--f-red)", "#fff3bf": "var(--f-yellow)",
  "#c3fae8": "var(--f-teal)", "#f8f9fa": "var(--f-paper)" };
const STROKE = { "#1e1e1e": "var(--ink)", "#e03131": "var(--margin)" };
const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

function seedOf(id) { let h = 7; for (const c of id) h = (h * 31 + c.charCodeAt(0)) % 2147483647; return h || 1; }

function roundRect(x, y, w, h, r) {
  r = Math.min(r, w / 2, h / 2);
  return `M${x + r} ${y} L${x + w - r} ${y} Q${x + w} ${y} ${x + w} ${y + r} L${x + w} ${y + h - r} ` +
    `Q${x + w} ${y + h} ${x + w - r} ${y + h} L${x + r} ${y + h} Q${x} ${y + h} ${x} ${y + h - r} ` +
    `L${x} ${y + r} Q${x} ${y} ${x + r} ${y} Z`;
}

function pathsOf(drawable, stroke, fill) {
  return gen.toPaths(drawable).map((p) => {
    const isFill = p.fill && p.fill !== "none";
    const s = p.stroke === "#FILL" ? fill : (p.stroke === "none" ? "none" : stroke);
    const f = isFill ? fill : "none";
    return `<path d="${p.d.replace(/-?\d+\.\d+/g, (n) => (+n).toFixed(1))}" stroke="${s}" stroke-width="${p.strokeWidth}" fill="${f}"` +
      `${p.stroke !== "none" ? ' stroke-linecap="round" stroke-linejoin="round"' : ""}/>`;
  }).join("");
}

function render(file) {
  const doc = JSON.parse(fs.readFileSync(file, "utf8"));
  const els = doc.elements.filter((e) => !e.isDeleted);
  const byId = Object.fromEntries(els.map((e) => [e.id, e]));
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  const grow = (x, y) => { minX = Math.min(minX, x); minY = Math.min(minY, y); maxX = Math.max(maxX, x); maxY = Math.max(maxY, y); };
  const out = [];
  for (const e of els) {
    const stroke = STROKE[(e.strokeColor || "#1e1e1e").toLowerCase()] || "var(--ink)";
    const fill = e.backgroundColor && e.backgroundColor !== "transparent" ? (FILL[e.backgroundColor.toLowerCase()] || e.backgroundColor) : null;
    const o = { seed: seedOf(e.id), roughness: 1.1, strokeWidth: 1.6, stroke: "#STROKE", bowing: 1,
      fill: fill ? "#FILL" : undefined, fillStyle: "hachure", hachureGap: 7, fillWeight: 1.2,
      strokeLineDash: e.strokeStyle === "dashed" ? [9, 7] : undefined };
    if (e.type === "rectangle") {
      grow(e.x, e.y); grow(e.x + e.width, e.y + e.height);
      const d = gen.path(roundRect(e.x, e.y, e.width, e.height, e.roundness ? 14 : 0), o);
      out.push(pathsOf(d, stroke, fill));
    } else if (e.type === "ellipse") {
      grow(e.x, e.y); grow(e.x + e.width, e.y + e.height);
      out.push(pathsOf(gen.ellipse(e.x + e.width / 2, e.y + e.height / 2, e.width, e.height, o), stroke, fill));
    } else if (e.type === "diamond") {
      grow(e.x, e.y); grow(e.x + e.width, e.y + e.height);
      const cx = e.x + e.width / 2, cy = e.y + e.height / 2;
      out.push(pathsOf(gen.polygon([[cx, e.y], [e.x + e.width, cy], [cx, e.y + e.height], [e.x, cy]], o), stroke, fill));
    } else if (e.type === "arrow" || e.type === "line") {
      const pts = e.points.map(([px, py]) => [e.x + px, e.y + py]);
      pts.forEach(([x, y]) => grow(x, y));
      const shape = pts.length > 2 ? gen.curve(pts, { ...o, fill: undefined }) : gen.linearPath(pts, { ...o, fill: undefined });
      out.push(pathsOf(shape, stroke, null));
      if (e.type === "arrow" && e.endArrowhead !== null) {
        const [ax, ay] = pts[pts.length - 2], [bx, by] = pts[pts.length - 1];
        const ang = Math.atan2(by - ay, bx - ax), L = 13, sp = 0.45;
        const h1 = [bx - L * Math.cos(ang - sp), by - L * Math.sin(ang - sp)];
        const h2 = [bx - L * Math.cos(ang + sp), by - L * Math.sin(ang + sp)];
        out.push(pathsOf(gen.linearPath([h1, [bx, by], h2], { ...o, fill: undefined, strokeLineDash: undefined }), stroke, null));
      }
    } else if (e.type === "text") {
      const fsz = e.fontSize || 20, lines = e.text.split("\n"), lh = fsz * 1.2;
      const color = STROKE[(e.strokeColor || "#1e1e1e").toLowerCase()] || "var(--ink)";
      let x, y, anchor;
      const c = e.containerId && byId[e.containerId];
      if (c && c.type !== "arrow") {
        x = c.x + c.width / 2; anchor = "middle";
        y = c.y + c.height / 2 - (lines.length * lh) / 2 + fsz * 0.85;
      } else {
        x = e.x; anchor = "start"; y = e.y + fsz * 0.85;
        const wmax = Math.max(...lines.map((l) => l.length)) * fsz * 0.5;
        grow(e.x, e.y); grow(e.x + wmax, e.y + lines.length * lh);
      }
      const tsp = lines.map((l, k) => `<tspan x="${x}" dy="${k ? lh : 0}">${esc(l)}</tspan>`).join("");
      out.push(`<text x="${x}" y="${y}" font-size="${fsz}" text-anchor="${anchor}" fill="${color}" class="hand">${tsp}</text>`);
    }
  }
  const pad = 16, vw = maxX - minX + pad * 2, vh = maxY - minY + pad * 2;
  return `<svg class="sketch" viewBox="${(minX - pad).toFixed(0)} ${(minY - pad).toFixed(0)} ${vw.toFixed(0)} ${vh.toFixed(0)}" ` +
    `width="${vw.toFixed(0)}" xmlns="http://www.w3.org/2000/svg">${out.join("")}</svg>`;
}

const outDir = "svg";
fs.mkdirSync(outDir, { recursive: true });
for (const f of fs.readdirSync("ex").filter((f) => f.endsWith(".excalidraw"))) {
  fs.writeFileSync(`${outDir}/${f.replace(".excalidraw", ".svg")}`, render(`ex/${f}`));
  console.log("rendered", f);
}
