---
name: web-frontend
description: Use when building, scaffolding, or reviewing a React/TypeScript web frontend — choosing between Next.js 16 App Router, Vite SPA, Remix/React Router 7 or Astro; CSR vs SSR vs SSG vs ISR vs React Server Components; TanStack Query for server state vs Zustand/Jotai for client state; Core Web Vitals (LCP/INP/CLS) and bundle size; Tailwind and design tokens; accessibility; Vitest + React Testing Library + Playwright; Vite config, ESLint flat config, CSP. Also for "start a web app", "my React app is slow", "fetch in useEffect", "which state manager", "Core Web Vitals failing", "hydration mismatch".
---

# Web Frontend

## Overview

A frontend is five things: a **rendering strategy**, **server state**, **client state**,
**a styling system**, and a **build/deploy pipeline**. Most React problems in production
trace to two root causes: **conflating server state with client state** (which produces the
whole family of `useEffect`-fetch bugs — races, no cancellation, stale data, duplicate
requests), and **shipping too much JavaScript**.

Verified against the **npm registry, 2026-08-01** — registry facts, not blog claims:
React **19.2.8** · Next.js **16.2.12** · Vite **8.2.0** · Vitest **4.1.10** ·
TypeScript **7.0.2** · TanStack Query **5.101** · Tailwind **4.3.3** ·
**ESLint 10.8** (eslintrc is *removed* — see build-deploy.md) · Playwright **1.62** ·
MSW **2.15** · Zod **4.4.3**.

## When to Use

- Starting a web app, or adding a feature/route to one
- Choosing a framework, rendering strategy, state library, or styling approach
- Reviewing frontend code for correctness, performance or accessibility
- Diagnosing: slow LCP/INP, layout shift, large bundles, hydration mismatches, data races,
  duplicate requests, stale UI after a mutation
- Setting up testing, linting, CSP, or bundle budgets

**Not for:** Node backend services (see `node-microservice`) or Flutter (see `flutter-app`).

## Step 0: Choose the rendering strategy

This is the decision everything else follows from — and it's per-route, not per-app.

| Route characteristics | Strategy |
|---|---|
| Public, SEO matters, content changes rarely | **SSG** (+ ISR if it changes on a schedule) |
| Public, SEO matters, per-request data | **SSR / streaming SSR** |
| Behind auth, no SEO value, app-like | **CSR (SPA)** — genuinely the right answer for admin tools |
| Mixed: static shell, dynamic islands | **RSC** (Next.js App Router) or Astro islands |

| If… | Use |
|---|---|
| Public product surface, SEO + per-route flexibility | **Next.js 16** (App Router) |
| Internal tool behind auth | **Vite + React SPA** — simpler mental model, no server to run |
| Content-heavy, minimal JS | **Astro** |
| Want Remix data conventions | **React Router 7** |

**Don't reach for SSR reflexively.** An internal dashboard behind a login gets **zero** SEO
benefit from SSR and pays for it in complexity: a server to run, hydration mismatches, and
"is this code running on the server or the client?" on every line. Full reasoning in
references/frameworks.md.

## Quick Reference

| Task | Reach for | Detail |
|---|---|---|
| Framework / rendering | Next 16 · Vite SPA · Astro | references/frameworks.md |
| **Server state** | **TanStack Query** — never `useEffect` + `fetch` | references/state-data.md |
| Client state | `useState`/`useReducer` → Zustand/Jotai if it must be shared | references/state-data.md |
| Forms | React Hook Form + Zod resolver | references/state-data.md |
| Styling | Tailwind, or CSS Modules; zero-runtime CSS-in-JS | references/styling.md |
| Components | shadcn/ui (you own the code) or Radix primitives | references/styling.md |
| Performance | LCP / **INP** / CLS; code splitting | references/performance.md |
| Accessibility | Semantic HTML first; `getByRole` in tests | references/accessibility.md |
| Tests | Vitest 4 + RTL; Playwright for journeys; MSW | references/testing.md |
| Build/deploy | Vite config, ESLint 10 flat config, CSP, budgets | references/build-deploy.md |

## Bootstrap a new app

```
myapp/
  src/
    main.tsx / app/            # entry (or Next app router)
    routes|pages/
    features/<feature>/        # colocated: components + hooks + types
    hooks/                     # useThing() wrappers around useQuery
    components/ui/             # design-system primitives
    lib/                       # api client, utils
  tests/
  eslint.config.js             # flat config (ESLint 10 — eslintrc is REMOVED)
```

1. TypeScript **strict**, `moduleResolution: "bundler"`, `verbatimModuleSyntax`.
2. **One HTTP client** with a timeout by default — `fetch` has none.
3. TanStack Query for anything from the server, wrapped in **per-concern custom hooks** so
   components call `useRecentActivity()` and never touch a query key.
4. ESLint **10 flat config** + Prettier; `jsx-a11y` rules on from day one — retrofitting
   accessibility is far more expensive.
5. **Bundle-size budget in CI** from the first commit. Budgets added later never pass.
6. Error boundary + a real error tracker with source maps uploaded (not served publicly).

## The non-negotiables

1. **Server state belongs in a data library, not `useState`.** `useEffect` + `fetch` + a
   `loading` flag has no cancellation, races on fast navigation, and refetches nothing on
   focus. This is the single most common React bug class.
2. **Every `fetch` gets a timeout** — `AbortSignal.timeout()`. There is no default.
3. **Semantic HTML first.** A `<button>` gives you focus, keyboard and role for free; a
   `<div onClick>` gives you a bug report from a keyboard user.
4. **Never put a secret behind `VITE_`/`NEXT_PUBLIC_`.** Those are inlined into the bundle
   and shipped to every visitor. This leaks keys regularly.
5. **Set width/height (or aspect-ratio) on images.** Unsized images are the top cause of CLS.
6. **`getByRole` over `getByTestId`.** Tests that query the way assistive tech does are both
   better tests and a live accessibility check.
7. **Code-split at route boundaries.** One bundle for a ten-route app means paying for nine
   routes nobody visited.
8. **Don't memo everything.** `useMemo`/`useCallback` have a cost; applied blindly they add
   noise and hide the real problem. Measure first.
9. **Hashed assets immutable, HTML must-revalidate.** Get this backwards and users are
   stranded on a stale app or refetch everything constantly.
10. **Keep majors aligned across the org** — especially validation libraries. Zod 3 in one
    repo and Zod 4 in another means shared schemas are impossible.

## Reference Map

| File | Read when |
|---|---|
| references/frameworks.md | Framework choice; CSR/SSR/SSG/ISR/RSC; the `"use client"` boundary |
| references/state-data.md | Server vs client state; TanStack Query; the useEffect-fetch anti-pattern; forms |
| references/performance.md | LCP/INP/CLS, bundles, images, fonts, rendering, React Compiler |
| references/styling.md | Tailwind/CSS Modules/zero-runtime CSS-in-JS; tokens; component libs |
| references/accessibility.md | Semantic HTML, focus management, ARIA, testing for a11y |
| references/testing.md | Vitest + RTL query priority, MSW, Playwright, what not to test |
| references/build-deploy.md | Vite/TS/ESLint config, env leaks, CSP, caching, budgets |

## Common Mistakes

| Mistake | Why it hurts | Fix |
|---|---|---|
| `useEffect` + `fetch` + `loading` state | No cancellation; races on fast nav; stale data; duplicate requests | TanStack Query |
| `fetch` with no timeout | Spinner forever; a hung request never resolves | `AbortSignal.timeout()` |
| Secret in `VITE_`/`NEXT_PUBLIC_` | Inlined into the bundle — shipped to every visitor | Server-side only |
| Context as a state manager | Every consumer re-renders on any change | Zustand/Jotai, or split contexts |
| `<div onClick>` | No focus, no keyboard, no role | `<button>` |
| Unsized images | Layout shift — fails CLS | width/height or aspect-ratio |
| `getByTestId` everywhere | Tests pass while the UI is unusable by keyboard/AT | `getByRole`/`getByLabelText` |
| One bundle, no splitting | Users download routes they never visit | Route-level `React.lazy` |
| Barrel files (`index.ts` re-exports) | Defeats tree-shaking; pulls in the whole module graph | Import direct paths |
| `useMemo` on everything | Cost without benefit; hides the real problem | Profile, then memo |
| Unstable `key` (array index) | Wrong element reused; state attaches to the wrong row | Stable IDs |
| Immutable HTML / revalidating assets | Users stuck on a stale app, or no caching at all | Hashed assets immutable; HTML revalidate |
| Public source maps | Ships your source to anyone curious | Upload to the error tracker only |
| Third-party scripts unaudited | Usually the actual cause of bad INP | Audit, defer, or drop them |
| React 18 patterns on 19 | Missing `use()`, Actions, and Compiler benefits | Read the 19 migration notes |
