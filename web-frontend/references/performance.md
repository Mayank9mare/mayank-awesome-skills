# Frontend Performance

Performance work has a real ordering of impact: fix Core Web Vitals first
(they're measured, they gate search ranking, and users feel them directly),
then bundle size, then rendering micro-optimizations. Teams routinely invert
this — memoizing components obsessively while a 400KB third-party chat widget
blocks the main thread for two seconds. Check the third-party scripts before
you reach for `useMemo`.

## Core Web Vitals

| Metric | Measures | Good | Needs improvement | Poor | Usual causes | Usual fixes |
|---|---|---|---|---|---|---|
| **LCP** (Largest Contentful Paint) | Time until the largest visible element (hero image, headline block) renders | ≤ 2.5s | ≤ 4.0s | > 4.0s | Slow server response (TTFB), render-blocking CSS/JS, unoptimized/unsized hero image, client-side rendering delaying content | SSR/SSG the above-the-fold content, `priority`/preload the LCP image, inline critical CSS, reduce TTFB (CDN, edge caching) |
| **INP** (Interaction to Next Paint) | Latency from a user interaction (click, tap, key press) to the next visual update — **replaced FID in March 2024** | ≤ 200ms | ≤ 500ms | > 500ms | Long tasks blocking the main thread during/after the interaction, heavy state updates, unbatched re-renders, third-party scripts hogging the thread | Break up long tasks, defer non-critical work off the input path, `startTransition` for non-urgent updates, audit third-party scripts |
| **CLS** (Cumulative Layout Shift) | Sum of unexpected layout shifts during the page's lifetime | ≤ 0.1 | ≤ 0.25 | > 0.25 | Images/embeds without reserved dimensions, web fonts swapping to a different-sized fallback, content injected above existing content (banners, ads), animations that aren't `transform`-based | Always set `width`/`height` (or `aspect-ratio`), reserve space for ads/embeds, `font-display: swap` + matched fallback metrics, animate with `transform`/`opacity` only |

**Why INP replaced FID**: FID only measured the delay *before* an event
handler started running — it said nothing about how long the handler itself
took, or how long the browser took to actually paint the result. A page could
have a perfect FID and still feel laggy because the click handler took 800ms
to produce visible feedback. INP measures the *whole* interaction-to-paint
latency, across all interactions on the page, not just the first one.

## Bundle size

### Code splitting

```tsx
// WRONG — eagerly importing a heavy, rarely-used component into the main
// bundle. Every visitor pays for the analytics dashboard's weight even if
// 95% of them never open it.
import AnalyticsDashboard from "./AnalyticsDashboard"; // pulls in a charting lib

// RIGHT — route-level or component-level splitting via React.lazy. The
// chunk downloads only when this branch actually renders.
import { lazy, Suspense } from "react";
const AnalyticsDashboard = lazy(() => import("./AnalyticsDashboard"));

function App() {
  return (
    <Suspense fallback={<Spinner />}>
      <AnalyticsDashboard />
    </Suspense>
  );
}
```

Route-level splitting is the highest-leverage form of this: each route's
meta-framework (Next.js, Remix, TanStack Router) already splits by route
automatically — the mistake is importing something heavy at the *root* layout
that only one route needs, which defeats the split.

### Tree shaking and the barrel-file trap

Barrel files (`index.ts` files that re-export everything from a directory)
are convenient to import from and **actively defeat tree-shaking** in ways
that are under-known and easy to miss in a bundle report:

```ts
// WRONG — a barrel file re-exporting 40 components
// src/components/index.ts
export * from "./Button";
export * from "./Modal";
export * from "./DataTable";      // pulls in a heavy grid library
export * from "./ChartWidget";    // pulls in a charting library
// ...36 more

// A consumer that only needs Button:
import { Button } from "@/components";
// Depending on the bundler and how aggressively it can statically analyze
// re-exports (and whether any of those 40 files has a top-level side effect —
// a CSS import, a module-scope registration call), the bundler may be unable
// to prove the DataTable/ChartWidget code is unused, and includes it anyway.
// This is worse with CommonJS interop and with libraries that aren't marked
// "sideEffects": false in package.json.
```

```ts
// RIGHT — import directly from the specific module
import { Button } from "@/components/Button";
```

The safest fix isn't "never use barrels," it's: **mark packages/directories
`"sideEffects": false` in `package.json`** so bundlers can prove re-exports
are pure and eliminate the unused ones, and **audit your bundle visualizer**
after introducing any barrel file to confirm the split actually held. Treat
barrel-file bloat as a recurring bundle-analysis check, not a one-time fix —
it regresses silently every time someone adds a new export to the barrel.

### Analysing with a bundle visualiser

Run a treemap visualizer (`rollup-plugin-visualizer` for Vite, `@next/bundle-analyzer`
for Next.js) as part of your normal workflow, not just when something feels
slow. The single most common finding: one dependency (a moment.js-style date
library, a full lodash import instead of `lodash-es` with named imports, an
icon library imported as a whole set) accounts for 30-50% of a route's JS.

```ts
// WRONG — pulls in the entire lodash CJS bundle
import _ from "lodash";
_.debounce(fn, 300);

// RIGHT — named import from the ESM build, tree-shakes to just this function
import { debounce } from "lodash-es";
debounce(fn, 300);
```

## Images

```tsx
// Next.js: next/image handles responsive sizing, lazy loading below the
// fold, modern format negotiation (AVIF/WebP with fallback), and — the part
// that prevents CLS — it reserves layout space from width/height BEFORE the
// image loads, so nothing jumps when it arrives.
import Image from "next/image";

<Image
  src="/hero.jpg"
  width={1200}
  height={600}
  alt="Product hero shot"
  priority // for the LCP image ONLY — skips lazy loading, fetches immediately
/>
```

```html
<!-- Plain <img>: same CLS-prevention principle applies without a framework.
     width/height (or aspect-ratio in CSS) reserve the box before the
     image loads; loading="lazy" defers below-the-fold images. -->
<img src="/hero.jpg" width="1200" height="600" alt="Product hero shot" fetchpriority="high" />
<img src="/thumb.jpg" width="200" height="200" alt="Thumbnail" loading="lazy" />
```

Rules: never ship an `<img>` without explicit dimensions or `aspect-ratio`.
Use `fetchpriority="high"` (or `priority` in `next/image`) on the LCP
candidate only — marking everything high-priority defeats prioritization
entirely. Prefer AVIF/WebP with a fallback; both beat JPEG at equivalent
visual quality for meaningfully smaller payloads.

## Fonts

```css
@font-face {
  font-family: "Inter";
  src: url("/fonts/inter-var.woff2") format("woff2");
  font-display: swap; /* show fallback text immediately, swap when the
                          custom font loads — avoids invisible text (FOIT),
                          trades it for a font-swap layout shift instead */
  font-weight: 100 900;
}
```

```html
<!-- Preload the font that's used above the fold, so the browser starts
     fetching it during the initial HTML parse instead of discovering the
     need for it only after CSSOM is built. -->
<link rel="preload" href="/fonts/inter-var.woff2" as="font" type="font/woff2" crossorigin />
```

**Self-hosting vs Google Fonts**: self-hosting removes a third-party DNS
lookup + connection + request round trip entirely (Google Fonts' own perf
benefit — shared caching across sites — mostly evaporated once browsers
partitioned the HTTP cache per top-level site for privacy reasons). Next.js's
`next/font` self-hosts automatically at build time and inlines
`font-display` + preload wiring for you; there's rarely a reason to load from
Google's CDN directly anymore.

**Layout shift from font swap**: `font-display: swap` trades invisible text
for a visible reflow when the custom font's metrics (x-height, character
width) differ from the fallback's. Mitigate with a fallback font stack whose
metrics are close to your custom font (or use `size-adjust`/`ascent-override`
in a `@font-face` block for the fallback to match), not just a generic
`sans-serif`.

## React rendering: memo/useMemo/useCallback

| Technique | Genuinely helps when | Cargo-cult when |
|---|---|---|
| `React.memo` | The component is expensive to render AND its parent re-renders often with the same props (e.g., a row in a long list, a chart) | Wrapping small, cheap components "for safety" — the comparison check itself has a cost, and for trivial components it's pure overhead |
| `useMemo` | The computation is genuinely expensive (sorting/filtering thousands of items, heavy derived math) OR the value's referential identity must be stable for a dependency array / `memo`ed child | Wrapping `{ x: 1 }` object literals or cheap arithmetic — you're paying memoization overhead to save less work than the memoization costs |
| `useCallback` | The function is passed to a `memo`ed child or a `useEffect` dependency array where identity stability prevents an infinite loop or unnecessary child re-render | Wrapping every inline handler "just in case" — with no memoized child consuming it, this does nothing but add noise |

The actual test before reaching for any of these: **profile first.** Open
React DevTools Profiler, find the component that's actually slow, then
memoize that one. Blanket memoization without a profile is guessing, and
often makes things slower (every memo call has bookkeeping cost).

### `key` stability

```tsx
// WRONG — index as key. When the list reorders/filters, React matches by
// position, not identity, so it reuses the wrong DOM node/component state
// (a text input at index 2 keeps its value even though a different item
// is now rendered there).
{items.map((item, i) => <Row key={i} data={item} />)}

// RIGHT — a stable, unique identifier tied to the actual entity
{items.map((item) => <Row key={item.id} data={item} />)}
```

### List virtualisation

Once a list is long enough that rendering every row costs real time
(hundreds+ of DOM nodes, especially with rich row content), render only the
visible slice plus a small overscan buffer:

```tsx
import { useVirtualizer } from "@tanstack/react-virtual";

function VirtualList({ items }: { items: Item[] }) {
  const parentRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 48, // row height in px
    overscan: 5,
  });

  return (
    <div ref={parentRef} style={{ height: 600, overflow: "auto" }}>
      <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
        {virtualizer.getVirtualItems().map((row) => (
          <div key={row.key} style={{ position: "absolute", top: row.start, height: row.size, width: "100%" }}>
            {items[row.index].label}
          </div>
        ))}
      </div>
    </div>
  );
}
```

## React Compiler

**Stable at 1.0 since October 2025** — not experimental, and this is the fact most
circulating articles get wrong. The React Compiler auto-memoizes components and values at
build time by static analysis, making manual `memo`/`useMemo`/`useCallback` unnecessary for
the common case.

Two things worth knowing that surprise people:

- **It is not tied to React 19.** The Babel plugin works back to **React 17**, so you can
  adopt it without a major React upgrade — often the cheaper win.
- **It is still opt-in per project**, not on by default. You add the plugin.

```js
// vite.config.ts — opt in via the Babel plugin
plugins: [react({ babel: { plugins: ["babel-plugin-react-compiler"] } })]
```

You still need to understand *why* memoization matters, because the compiler **bails out
silently** on patterns it can't prove safe — those components simply get no memoization, with
no error. So the workflow doesn't change: profile, find the real problem, verify the fix.
What changes is that hand-written `useMemo` should now be the exception you justify, rather
than a reflex.

While you're on 19.2, two other stable additions are relevant to perf work: **`<Activity>`**
(keep a subtree mounted but deprioritised instead of unmounting/remounting it) and
**Performance Tracks** in devtools. And `useEffectEvent` finally solves the "I need a stable
callback that reads fresh props" problem that `useCallback` handles badly.

## Waterfalls

```tsx
// WRONG — sequential fetches create a waterfall: each request waits for
// the previous one's response before starting, even though they don't
// depend on each other.
async function loadDashboard(userId: string) {
  const user = await fetchUser(userId);
  const orders = await fetchOrders(userId);     // could have started with user
  const recommendations = await fetchRecs(userId); // could have started with user
  return { user, orders, recommendations };
}

// RIGHT — parallelize independent requests
async function loadDashboard(userId: string) {
  const [user, orders, recommendations] = await Promise.all([
    fetchUser(userId),
    fetchOrders(userId),
    fetchRecs(userId),
  ]);
  return { user, orders, recommendations };
}
```

In React Server Components / SSR frameworks, the same principle applies to
data loading across the component tree: fetch at the top and pass down, or
use the framework's parallel-route/parallel-loader primitives, rather than
letting nested components each `await` their own data serially as the tree
renders top-down (a "fetch waterfall" that's invisible in the code but
visible in a network trace as a staircase).

**Preloading**: for known-next navigations (hovering a link, a route you know
the user will likely visit), kick off the data fetch before the navigation
event fires — `<Link prefetch>` in Next.js, `router.preload` /
`queryClient.prefetchQuery` for TanStack Router/Query — so the data is warm
in cache by the time the route actually mounts.

## Third-party scripts: the usual real culprit

Before optimizing your own code, check what you didn't write: chat widgets,
analytics/tag managers, ad tech, A/B testing SDKs, session-replay tools.
These routinely account for more main-thread blocking time (hurting INP) and
more render-blocking network weight (hurting LCP) than the entire first-party
application combined — and they're the easiest thing to overlook because
"someone in marketing added a tag" doesn't show up in a code review.

Mitigations: load third-party scripts with `async`/`defer` or `next/script`'s
`strategy="lazyOnload"`/`"worker"` (offloads to a web worker via Partytown-style
proxying where supported), audit what's actually still needed on a schedule
(tags accumulate and are rarely removed), and put a real budget on
third-party weight in your performance review process — it's the single most
under-scrutinized category in most audits.

## Checklist

- [ ] LCP, INP, CLS measured in the field (real-user monitoring), not just lab
      tools — lab tools miss real device/network variance
- [ ] LCP image marked `priority`/`fetchpriority="high"`, everything else lazy
- [ ] Every image/embed has explicit dimensions or `aspect-ratio`
- [ ] Fonts self-hosted with `font-display: swap` and preloaded if used above
      the fold; fallback metrics matched to minimize swap-induced shift
- [ ] Bundle visualizer run and reviewed after any new dependency, not just
      when things feel slow
- [ ] No barrel-file (`index.ts` re-export) import defeating tree-shaking on
      a hot path; packages marked `sideEffects: false` where true
- [ ] `memo`/`useMemo`/`useCallback` applied only after profiling identified
      an actual expensive re-render, not defensively
- [ ] List `key`s are stable entity IDs, never array index, for any
      reorderable/filterable list
- [ ] Long lists (hundreds+ rows) virtualized
- [ ] Independent data fetches run in parallel (`Promise.all` / parallel
      loaders), not chained sequentially
- [ ] Third-party scripts audited for necessity and loaded async/deferred
