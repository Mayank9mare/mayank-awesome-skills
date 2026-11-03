# UI plan: <page or feature>

## Project brief
- Stack: <framework + version · React · Tailwind v4 · TS · router · data layer · tests>
- Design system: <tokens file · fonts · radius · dark mode · existing components/ui · icons>
- Data: <API layer · types source · fetch pattern (server/client)>
- Scripts: lint `<cmd>` · typecheck `<cmd>` · test `<cmd>` · build `<cmd>`
- Wensity: <MCP connected / CLI · wensity.json present? · Pro access: yes/no>

## Purpose
<who it's for> · Primary action: <the one thing the page should get people to do>

## Sections (top to bottom)
| # | Section | Job | Component (source) | Tier | Data source | Motion |
|---|---|---|---|---|---|---|
| 1 | Hero | Promise + CTA | <slug> (Wensity) | Free | content/hero.ts | **hero moment** |
| 2 | Social proof | Trust | <existing LogoCloud> (project) | — | content/logos.ts | marquee (subtle) |
| 3 | Pricing | Choose a plan | <slug> (Wensity block) | Pro → free alt: <slug> | `GET /api/plans` → `Plan[]` | toggle micro |
| … | | | | | | |

Custom builds (and why nothing fits): <none / list>

## Budgets
- Motion: hero = <item>; supporting = <items>; reduced-motion fallback = <plan>
- New dependencies: <list> (heavy: <none / which, lazy-loaded>)
- Mobile swaps: <e.g. 3D hero → static image under 768 px>

## Open questions for the user
- <copy, data endpoints that don't exist, Pro purchase, brand decisions>

## Install order
1. <slug> → plan → approve → install
2. …
