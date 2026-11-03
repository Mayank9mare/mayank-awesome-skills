# Final review checklist

Run this against `git diff` (and `git status` for new files) before reporting. Fix what fails, or list it
under "left" in the report with the reason.

## Scope and hygiene
- [ ] Only files related to the task changed. No stray reformatting of unrelated files.
- [ ] No `.wensity-tmp/` and no secrets or tokens in the diff.
- [ ] `wensity.json` committed-ready (if newly created); `.mcp.json` pinned to an exact version.
- [ ] New dependencies are listed and justified, the lockfile is updated, and none duplicates an existing one
      (for example a second animation library).
- [ ] No unused installed components or leftover demo files.

## Design system
- [ ] No hard-coded colours, radius, shadows or font families where a token exists.
- [ ] Dark mode looks right (if the project has it).
- [ ] Spacing, container width and type scale match the rest of the app.
- [ ] One hero moment; the motion budget is respected ([composition.md](composition.md)).

## Data
- [ ] No mock or demo data in shipped code (run the grep in [data-integration.md](data-integration.md)).
- [ ] Types come from the project's API types or schemas. No `any`, no unchecked `as` casts.
- [ ] Loading, empty, error and long-content states exist and were seen.

## Accessibility
- [ ] Landmarks (`header`, `main`, `nav`, `footer`), one H1, and headings in order.
- [ ] Every interactive element is reachable and usable by keyboard, with visible focus and no traps.
- [ ] Dialogs, menus and tabs manage focus and use the right ARIA (Base UI primitives already do; custom ones must too).
- [ ] Images have meaningful alt text, or `alt=""` if decorative. Icon-only buttons have labels.
- [ ] Text contrast is at least AA (4.5:1 for body text). Information isn't conveyed by colour alone.
- [ ] `prefers-reduced-motion` turns off or simplifies every animation, including canvas and WebGL.

## Responsive and performance
- [ ] Checked at 360, 768, 1024 and 1440 px: no horizontal scroll, and touch targets are at least 44 px.
- [ ] Heavy below-the-fold components are lazy-loaded with sized placeholders (no CLS).
- [ ] The hero text isn't blocked by animation or script (LCP).
- [ ] In RSC apps, `"use client"` is only on the components that need it.

## Code quality
- [ ] Installed Wensity source is restyled minimally; project logic lives outside it where possible
      (so a later `wensity update` stays easy to diff).
- [ ] Components are presentational; data fetching follows the project's pattern.
- [ ] Names, file layout and imports follow the project's conventions and aliases.

## Checks (paste the real result in the report)
- [ ] Lint passes.
- [ ] Type-check passes.
- [ ] Tests pass, with new tests for new states and interactions.
- [ ] Build passes.
- [ ] Screenshots taken: mobile and desktop, light and dark, with reduced motion on.
