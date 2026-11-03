---
name: wensity-ui
description: Build or change frontend UI in a React + Tailwind project using the Wensity UI library (ui.wensity.com) through its MCP server or CLI, with a fixed workflow — inspect the project first, search Wensity before writing custom components, compose a coherent page instead of stacking animations, follow the project's design tokens, accessibility and responsive rules, wire components to real API data instead of mock data, then run lint, type checks and tests and review the diff. Use when the user mentions Wensity, asks for a landing page, hero, pricing, dashboard, AI chat UI, animated section or "make this page look good" in a React/Next/Vite/Remix/Astro + Tailwind project, or wants to add, swap or upgrade UI components.
argument-hint: "[what to build, e.g. 'pricing page with monthly/yearly toggle']"
user-invocable: true
---

# Wensity UI

[Wensity UI](https://ui.wensity.com) is a React + TypeScript + Tailwind v4 library that installs
**source files** (`.tsx`) into the project. It covers animated components, 57 primitives on Base UI,
and 82 page blocks. Wensity's MCP server already handles **finding and installing** components.
This skill adds the part around it: a fixed workflow, page-level judgement, real data, and
verification.

General React depth (rendering strategy, server vs client state, performance, accessibility,
testing) lives in the **web-frontend** skill. Read its references when a step points to them; don't
repeat them here.

## The rules (enforced at every step)

1. **Inspect before changing.** Never write UI code before Step 1 is done.
2. **Wensity before custom.** Search Wensity (and the project's own components) before writing a
   new component. Write custom only when nothing fits, and say why.
3. **Compose a page, not a demo reel.** One visual idea per page, a motion budget, and a clear
   hierarchy. See [composition.md](references/composition.md).
4. **The project's design system wins.** Use its tokens, fonts, radius, spacing, dark mode,
   breakpoints and a11y rules. Restyle Wensity components to match, not the other way round.
5. **Real data, not mock data.** Replace every demo array and placeholder with the project's real
   API, types, and loading / empty / error states. See [data-integration.md](references/data-integration.md).
6. **Plan, approve, then write.** Every Wensity install is planned and shown to the user first.
7. **Prove it.** Lint, type-check, test, build, look at it, and review the diff before saying done.

## Workflow

### Step 0 · Tooling
Check that the Wensity MCP tools (`wensity_search`, …) are available. If not, offer the setup in
[wensity-tools.md](references/wensity-tools.md#setup) (it writes `.mcp.json`; ask before running it).
If the user declines MCP, use the CLI (`npx wensity@latest list --json`, `add --dry-run`).

### Step 1 · Inspect the project (read-only)
Do all of this before proposing anything:
- `wensity_inspect_project` → framework, package manager, aliases, Tailwind CSS file.
- **Stack:** React version, TypeScript and TSX compile, Tailwind v4 (v3 needs a decision, see
  wensity-tools.md), router, data layer (TanStack Query, RSC fetch, SWR, tRPC…), test runner.
- **Design system:** the Tailwind `@theme` block or CSS variables (colours, radius, fonts, spacing),
  dark mode strategy, existing `components/ui`, an existing shadcn setup, and the icon library.
- **Data:** where API calls live (client, hooks, server actions, route handlers), the generated or
  shared types, and the auth/session pattern.
- **Conventions:** file layout, naming, `cn()` helper, lint and format config, and the scripts in
  `package.json` (`lint`, `typecheck`, `test`, `build`).
- **The target:** the page or route being built or changed, and what's already on it.

Write a short **Project brief** (5–10 lines) for the user. It also feeds the plan.

### Step 2 · Plan the page
Fill [templates/ui-plan.md](templates/ui-plan.md):
- **Purpose and the one action** the page should drive.
- **Sections, top to bottom.** For each: the need, a candidate (an existing project component,
  then a Wensity item, then custom), the data source, and its motion (none / subtle / hero).
- **Find candidates** with `wensity_search` (by need, category or tag), then `wensity_get_item` for
  props and dependencies. Label each candidate **Free / Pro / Needs Pro**. For a Needs Pro item, say
  so and give the free alternative.
- **Motion budget** and the **performance budget** (new dependencies, 3D / WebGL, bundle weight).

Show the plan and **wait for approval.** Fold any changes the user asks for back into the plan.

### Step 3 · Install (one item at a time)
For each approved item: `wensity_plan_install` → show the files, token changes, package command and
conflicts → on approval, `wensity_install` with that plan's token. Follow the agent rules in
[wensity-tools.md](references/wensity-tools.md#agent-rules): use each token once, re-plan if the plan is
stale, never ask for or accept an API token, keep the MCP version pinned, never commit `.wensity-tmp/`.
After each install, read the installed source: you can only see it once it's in the project.

### Step 4 · Integrate
- **Restyle to the project's tokens.** Replace hard-coded colours, radius, shadows and fonts in the
  installed source with the project's tokens. Keep the edits small so a later `wensity update` is
  easy to diff.
- **Connect real data** ([data-integration.md](references/data-integration.md)): typed props, the
  project's fetch pattern, and loading, empty and error states. Remove the component's demo data.
- **Compose** the page ([composition.md](references/composition.md)): spacing rhythm, one hero
  moment, headings in order, and real copy (ask the user for copy you can't infer).
- **Responsive:** check it at 360, 768, 1024 and 1440 px widths. Nothing scrolls sideways, touch
  targets are at least 44 px, and heavy effects are swapped for lighter ones on mobile.
- **Accessible:** semantic landmarks, focus visible and in order, keyboard paths through every
  interactive part, labels and alt text, contrast AA, and `prefers-reduced-motion` honoured
  (web-frontend `references/accessibility.md`).
- **Server and client:** in RSC apps, only components that need it are `"use client"`. Keep data
  fetching on the server where the project already does that.

### Step 5 · Verify
Run the project's own scripts. Find them in `package.json`; don't invent them:
1. Lint. 2. Type-check (`tsc --noEmit` if there's no script). 3. Tests (add or update tests for new
behaviour: rendering states and interactions). 4. Build.
Then **look at it**: run the dev server and screenshot the page at mobile and desktop widths
(the `run` skill or Claude in Chrome), in light and dark mode, with reduced motion on.
Fix anything that fails. Don't call it done with a red check.

### Step 6 · Review and report
Go through [review-checklist.md](references/review-checklist.md) against `git diff`, then report:
- What was built, and which sections came from Wensity, the project, or custom code (and why custom).
- New dependencies and token changes.
- Check results: lint, types, tests and build, with the real output if anything failed.
- Anything left: copy you need from the user, Pro items skipped, follow-ups.

Don't commit or push unless asked.

## Quick reference

| Situation | Do |
|---|---|
| "Make it look amazing" | Plan first; one hero moment; everything else calm |
| Item is Pro, user has no Pro | Say so, offer the free alternative or a custom build |
| Wensity's demo uses hard-coded arrays | Replace them with the project's real data and types |
| Project already has a matching component | Use it; don't install a duplicate |
| Tailwind v3 project | Stop and ask (see wensity-tools.md) |
| Install reports "stale plan" | Re-plan; nothing was written |
| Install reports "Recovery required" | Follow its steps, check `git diff`, keep `.wensity-tmp` until the user checks |
| 3D / WebGL / canvas component | Lazy-load it, give it a static fallback, skip it on mobile and reduced motion |

## Licence note
Free items are MIT. Pro items have a commercial licence for one developer and **can't be
redistributed** as a library or kit. Install them into the user's app only, never into shared
templates or public packages, and never copy their source into this skills repo.
