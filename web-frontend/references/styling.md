# Styling

The styling landscape converged hard on one axis: **does the CSS exist at
build time or does it exist at runtime?** Runtime CSS-in-JS is on its way
out — RSC has no client runtime to inject `<style>` tags into during a
server render, and even outside RSC, computing styles in JS on every render
is real work you can eliminate entirely with a build step. Everything below
is organized around that split.

## The field

| Approach | Runtime cost | RSC-compatible | Status | Choose when |
|---|---|---|---|---|
| **Tailwind CSS** (v4) | Zero — utility classes, no runtime | Yes | Current, dominant | Default choice for most new projects; fast iteration, no naming decisions, tree-shakes unused classes automatically |
| **CSS Modules** | Zero — compiles to static `.css` + scoped class names | Yes | Current, stable | You want plain CSS with locally-scoped class names and no utility-class verbosity in markup |
| **vanilla-extract** | Zero — TypeScript authored, compiles to static CSS at build time | Yes | Current | You want type-safe design tokens and zero-runtime CSS without giving up CSS-in-JS ergonomics |
| **Panda CSS** | Zero — build-time extraction, similar goals to vanilla-extract | Yes | Current | Similar to vanilla-extract, with a utility-first API on top of build-time extraction |
| **styled-components / Emotion** (runtime CSS-in-JS) | Real — style computation and injection happen in the browser on render | **No** — breaks in Server Components, requires `"use client"` everywhere it's used, and injects `<style>` tags in a way RSC's streaming model doesn't support cleanly | **DEPRECATED for new RSC-based projects**; still fine in pure-SPA codebases that aren't adopting RSC | Legacy codebases, or CSR-only apps where the runtime cost and RSC incompatibility don't apply |
| **Plain CSS / Sass** | Zero | Yes | Current, never left | Small projects, teams that prefer a global stylesheet and don't want a build-time abstraction |

**Why runtime CSS-in-JS is falling out of favour**: two independent forces
converged. First, RSC fundamentally can't support it — a Server Component
renders once on the server with no client-side JS runtime attached to it;
styled-components needs a `<StyleSheetManager>`-style runtime present at
render time to generate and inject class names, which means every component
using it must be a Client Component, which defeats the entire point of
Server Components (shipping less JS). Second, even ignoring RSC, computing
styles in JS on every render — parsing template literals, hashing class
names, injecting into a stylesheet — is measurable work that a build step
eliminates for free. The build-time alternatives (Tailwind, CSS Modules,
vanilla-extract, Panda) all produce plain, static `.css` files; nothing runs
in the browser to generate styles.

## Tailwind

**Current: 4.3.3** (npm-verified 2026-08). **v4 was a rewrite, not a version bump** — if you
learned Tailwind on v3, four things you know are now wrong.

### 1. Config moved from JS to CSS

```css
/* v4 — @theme in your CSS is the source of truth. Every value here is
   automatically exposed as a CSS custom property, so `var(--color-brand)`
   works everywhere, including outside Tailwind. */
@import "tailwindcss";

@theme {
  --color-brand: #3b82f6;
  --font-display: "Inter", sans-serif;
  --breakpoint-3xl: 120rem;
}
```

```js
// v3 — no longer read. v4 does NOT automatically load tailwind.config.js.
module.exports = { theme: { extend: { colors: { brand: "#3b82f6" } } } };
```

The old file isn't an error — it's **silently ignored**, which is worse. Symptom: your custom
colours stop resolving and utilities render as if undefined. The `@config` directive can load
it as a temporary bridge, but treat that as a migration aid, not a destination.

### 2. Directives and the build plugin changed

| v3 | v4 |
|---|---|
| `@tailwind base; @tailwind components; @tailwind utilities;` | `@import "tailwindcss";` |
| PostCSS plugin `tailwindcss` | **`@tailwindcss/postcss`** |
| (n/a) | **`@tailwindcss/vite`** — faster, use it on Vite |
| `content: [...]` array | **automatic content detection** |
| `require()` a plugin in config | **`@plugin`** directive in CSS |
| `theme()` in CSS | native `var(--color-brand)` |
| `safelist` | no longer needed |

### 3. Silent visual changes

- **`border` now defaults to `currentColor`**, not `gray-200`. Every bare `border` in a v3
  codebase changes colour — and nothing errors.
- Renamed utilities: `bg-gradient-to-*` → **`bg-linear-to-*`**, `flex-shrink-0` → **`shrink-0`**.

These are why a v3→v4 migration needs **visual regression tests on the PR**, not just a
green build.

### 4. `@apply` still works, but the team advises against it

Prefer writing the actual CSS properties. `@apply` re-introduces the indirection that
utility-first was meant to remove, and it's the main thing that makes a v4 migration hard.

**Migrating:** `npx @tailwindcss/upgrade` handles ~90% mechanically and shows a diff. The
missing 10% is reliably **custom plugins and `safelist` entries** — i.e. the parts holding
your design system together. Budget review time for exactly those.

**Why it's worth it:** a Rust/Lightning-CSS engine with 60–80% faster cold builds on large
design systems, plus container queries and 3D transforms as v4-only features. Headless UI and
Radix need no changes (they're headless); theming plugins like DaisyUI did.

**Greenfield: start on v4.** Existing project with heavy plugins or `@apply`: stage it.

```tsx
// Utility-first: styles live in the markup, no separate stylesheet to
// context-switch to, and the final CSS bundle only contains classes you
// actually used (tree-shaken via content scanning at build time).
function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-800 dark:bg-gray-900">
      <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100">{title}</h3>
      <div className="mt-2 text-sm text-gray-600 dark:text-gray-400">{children}</div>
    </div>
  );
}
```

```ts
// tailwind.config.ts — design tokens live here, not scattered across
// components as magic hex values. Every `bg-brand-500` in your markup
// resolves to this one source of truth.
export default {
  theme: {
    extend: {
      colors: {
        brand: {
          500: "oklch(0.65 0.2 260)",
          600: "oklch(0.55 0.2 260)",
        },
      },
    },
  },
};
```

The recurring complaint — "unreadable class soup" — is real for deeply
nested conditional class logic. The fix is extracting repeated patterns into
components, not abandoning the approach; a `<Card>` component hides its own
utility classes from every call site that uses it.

## CSS Modules

```css
/* Button.module.css — class names are scoped to this file at build time;
   ".button" here can't collide with ".button" in any other module. */
.button {
  padding: 0.5rem 1rem;
  border-radius: 0.375rem;
  font-weight: 600;
}

.primary {
  background: var(--color-brand-500);
  color: white;
}
```

```tsx
import styles from "./Button.module.css";

function Button({ variant = "primary", ...props }: ButtonProps) {
  return <button className={`${styles.button} ${styles[variant]}`} {...props} />;
}
```

Zero runtime, works everywhere including RSC (the CSS ships as a static
asset, not JS), and reads like plain CSS — the trade-off against Tailwind is
you're back to inventing class names and switching files to see styles.

## vanilla-extract / Panda: zero-runtime CSS-in-JS

```ts
// styles.css.ts — this FILE looks like JS/TS, but the build step (a Vite/
// esbuild plugin) extracts it into a static .css file. Nothing runs in the
// browser to produce these styles — you get CSS-in-JS ergonomics (co-located
// with components, type-checked, themeable) with the runtime cost of plain
// CSS Modules.
import { style, createTheme } from "@vanilla-extract/css";

export const [themeClass, vars] = createTheme({
  color: { brand: "oklch(0.65 0.2 260)", text: "oklch(0.2 0 0)" },
  space: { sm: "0.5rem", md: "1rem" },
});

export const button = style({
  padding: `${vars.space.sm} ${vars.space.md}`,
  background: vars.color.brand,
  borderRadius: "0.375rem",
});
```

This is the shape to reach for when you want type-safe, co-located design
tokens (autocomplete on `vars.color.brand`, a compile error if you typo it)
without paying CSS-in-JS's traditional runtime tax or losing RSC
compatibility. Panda CSS covers the same ground with a more utility-flavored
API on top of the same build-time-extraction idea.

## Design tokens and theming

```css
/* globals.css — CSS custom properties are the token layer every approach
   above can consume (Tailwind config references them, CSS Modules use
   var(), vanilla-extract can wrap them). One definition, every consumer
   agrees. */
:root {
  --color-bg: oklch(1 0 0);
  --color-text: oklch(0.2 0 0);
  --color-brand: oklch(0.65 0.2 260);
}

/* System preference: respects the OS/browser-level setting for users who
   haven't made an explicit in-app choice. */
@media (prefers-color-scheme: dark) {
  :root {
    --color-bg: oklch(0.15 0 0);
    --color-text: oklch(0.95 0 0);
  }
}

/* Explicit override: a user-toggled class on <html> wins regardless of
   system preference — this is what makes an in-app light/dark toggle
   actually override the OS setting rather than fight it. */
:root.dark {
  --color-bg: oklch(0.15 0 0);
  --color-text: oklch(0.95 0 0);
}

:root.light {
  --color-bg: oklch(1 0 0);
  --color-text: oklch(0.2 0 0);
}

body {
  background: var(--color-bg);
  color: var(--color-text);
}
```

```tsx
// WRONG — theme choice only respects system preference, no way for the
// user to override it in-app; also causes a flash-of-wrong-theme if you
// try to force one via JS after paint.
function useTheme() {
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

// RIGHT — explicit user choice (persisted) takes priority over system
// preference; both are honoured, and the resolved class is set BEFORE
// first paint (inline script in <head>, or a framework's theme script) to
// avoid a flash.
function resolveTheme(userPreference: "light" | "dark" | "system"): "light" | "dark" {
  if (userPreference !== "system") return userPreference;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}
// Applied as document.documentElement.classList.add(resolveTheme(pref))
// as early as possible — inline, blocking, before React hydrates.
```

## Component libraries: control vs speed

| Library | What you get | Trade-off |
|---|---|---|
| **shadcn/ui** | CLI copies component source directly into your repo (`src/components/ui/button.tsx`) — you own and can edit every line | No versioned package to update; you're responsible for merging upstream improvements manually. Best when you need deep customization and don't mind that responsibility. |
| **Radix primitives** | Unstyled, fully accessible behavior primitives (Dialog, Popover, DropdownMenu) — focus management, ARIA, keyboard nav all handled; you supply 100% of the visual styling | Maximum styling freedom, but you build the design system on top yourself. This is what shadcn/ui is built from — Radix primitives + Tailwind styling + copy-in distribution. |
| **MUI (Material UI)** | Fully styled, fully-featured components out of the box, huge surface area, theming API | Fast to ship with, but fighting its opinions (Material design defaults, its own theming/CSS engine) costs more the further your design diverges from Material |

The honest trade-off: shadcn/ui and Radix maximize control at the cost of
building more yourself; MUI maximizes speed-to-first-screen at the cost of
control once your design has any opinions of its own. Most greenfield
products building a custom design system land on shadcn/ui (Radix underneath
+ Tailwind + code you own) specifically because "you own it" means no
version-upgrade breakage and no fighting a library's defaults.

## Responsive strategy, container queries, logical properties

```css
/* WRONG — media queries only respond to VIEWPORT width. A card component
   dropped into a narrow sidebar still gets the "desktop" styles because the
   viewport is wide, even though the card's actual available space is narrow. */
@media (min-width: 768px) {
  .card { flex-direction: row; }
}

/* RIGHT — container queries respond to the CONTAINING ELEMENT's size, so a
   component behaves correctly regardless of where in the layout it's
   placed — a real fix for a real, common layout bug. */
.card-container {
  container-type: inline-size;
}

@container (min-width: 400px) {
  .card { flex-direction: row; }
}
```

```css
/* WRONG — physical properties assume a left-to-right writing mode. Wrong
   for RTL languages (Arabic, Hebrew) without a separate RTL stylesheet. */
.button {
  margin-left: 1rem;
  padding-left: 0.5rem;
}

/* RIGHT — logical properties adapt automatically to writing direction; no
   RTL-specific override stylesheet needed. */
.button {
  margin-inline-start: 1rem;
  padding-inline-start: 0.5rem;
}
```

Default to container queries for any component meant to be reusable across
layout contexts (cards, sidebars, widgets) — viewport media queries are
still correct for page-level layout shifts (nav collapsing to a hamburger),
just wrong as the *only* responsive tool in a component library.

## Checklist

- [ ] No new runtime CSS-in-JS (styled-components/Emotion) introduced in an
      RSC-based project — use Tailwind/CSS Modules/vanilla-extract/Panda
- [ ] Design tokens defined once (CSS custom properties or a config file),
      never hardcoded hex/px values scattered across components
- [ ] Dark mode respects `prefers-color-scheme` by default AND an explicit
      user override class wins over system preference
- [ ] Theme resolved before first paint to avoid a flash of the wrong theme
- [ ] Component library choice matches the actual need: shadcn/ui or Radix
      for a custom design system, MUI for speed when defaults are acceptable
- [ ] Reusable components use container queries, not viewport media queries,
      for their internal responsive behavior
- [ ] Logical properties (`margin-inline-start`, not `margin-left`) used
      anywhere RTL support might ever matter
- [ ] Bundle-size impact of the chosen CSS approach checked — utility-first
      and build-time-extracted CSS should tree-shake to only used styles
