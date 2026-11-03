# Composing a coherent page

Wensity's catalogue is heavy on spectacle: cinematic interactions, gooey morphs, text animations, 3D.
Each one looks great alone. Five on one page look like a demo reel and load like one. Compose the
page first, then pick components that serve it.

## 1. Start from the page's job
- **One primary action** per page (sign up, book a demo, buy, start using). Every section either
  builds the case for it or removes an objection.
- **Write the section order before picking components.** A typical marketing page: hero (promise +
  CTA) → proof (logos, numbers) → how it works / features → deeper proof (testimonials, case
  study) → pricing → FAQ (objections) → final CTA → footer. An app screen: header → the main task →
  supporting panels. Drop any section that has no job.

## 2. The motion budget
| Tier | Per page | Examples |
|---|---|---|
| **Hero moment** | **one** | an animated background, a cinematic hero, a 3D object, a big text reveal |
| **Supporting motion** | 2–3 sections | on-scroll fade or rise, a marquee of logos, an animated counter |
| **Micro-interactions** | anywhere, subtle | hover, press, focus, toggle transitions (≤ 200 ms) |

Rules:
- Motion has to explain something (order, cause, change of state) or direct attention to the CTA.
  Decoration-only motion goes first when the budget is tight.
- Never animate body text people are trying to read. Never block content behind an intro animation.
- Everything respects `prefers-reduced-motion`: swap animations for an instant state, and give
  canvas or WebGL a static image.
- One easing and duration family per page. Don't mix bouncy springs with linear slides.

## 3. One visual language
- **Pick one style family** and stay in it (for example glassy, flat and crisp, or illustrated).
  Wensity categories mix styles; reject candidates that clash even if they're individually good.
- **Tokens only:** colours, radius, shadows and fonts come from the project's theme. If two installed
  components disagree (radius 8 vs 16), normalise both to the token.
- **Spacing rhythm:** one vertical section spacing (for example `py-24 md:py-32`), one container width,
  one grid. The same gaps inside comparable cards.
- **Type scale:** one display style for the hero H1, one for section H2s, one body size. Headings go
  in order (one H1).
- **Colour:** one accent for actions. Gradients and glows stay in the hero tier.

## 4. Hierarchy check (squint test)
Blur your eyes at the screenshot. You should see, in order: the headline, the primary CTA, then
section headings. If an animated background or a decorative card wins, tone it down.

## 5. Performance is part of composition
- Count the new dependencies (motion libraries, three.js, lottie). One heavy library per page at most.
- Lazy-load below-the-fold heavy components (`next/dynamic` / `React.lazy` + `Suspense`), and give them
  a sized placeholder so the layout doesn't shift (CLS).
- The hero must not delay LCP: the headline text renders without waiting for the animation.
- On mobile: swap 3D, WebGL and large canvases for a static image or a simpler variant.
- Detail: web-frontend `references/performance.md`.

## 6. Picking between candidates
Prefer, in order:
1. The project's existing component.
2. A Wensity **primitive** or **block** that matches the style family.
3. A Wensity animated component, if the budget allows.
4. Custom.

Between two Wensity items, prefer fewer dependencies, a smaller API, an accessible
interactive pattern (keyboard and focus), and Free over Pro, unless Pro clearly serves the page's job.
