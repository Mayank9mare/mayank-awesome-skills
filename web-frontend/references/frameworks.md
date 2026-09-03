# Choosing a Frontend Framework and Rendering Strategy

The framework choice matters less than people think. The rendering-strategy
choice — CSR vs SSR vs SSG vs ISR vs streaming vs RSC — matters more, because it
determines your TTFB, your TTI, your SEO ceiling, and your infrastructure bill.
Pick the framework that gives you the rendering strategy your product actually
needs, not the one with the loudest Twitter.

## The field, 2026

| Framework | Current version | Rendering model | Data fetching | Choose when |
|---|---|---|---|---|
| **Next.js** | 16.2 (App Router) | RSC by default, SSR/SSG/ISR per-route, streaming | `async` Server Components, Route Handlers, Server Actions | Default choice for anything public-facing: marketing, e-commerce, content sites, SaaS with SEO surface |
| **Remix / React Router 7** | RR7 (Remix merged in) | SSR-first, nested loaders, no RSC | `loader`/`action` per route, runs on server | You want SSR without the RSC mental model; framework-agnostic data layer; tighter control over caching semantics |
| **Vite + React (SPA)** | Vite 8.2 | CSR only, no server render | Client-side (TanStack Query, SWR, fetch) | Internal tools, admin dashboards, anything behind auth with zero SEO need |
| **Astro** | current | Islands — HTML by default, JS opt-in per component | Server-side in `.astro` frontmatter, or client islands | Content-heavy sites (docs, blogs, marketing) where most of the page is static and only fragments are interactive |
| **TanStack Start** | current, still young | Full-stack, SSR + streaming, framework-agnostic router | TanStack Query/Router native, server functions | You want Next.js-shaped SSR/streaming but with TanStack Router's type-safe routing and without the App Router's opinions |
| **SvelteKit** | — | SSR/SSG/CSR configurable per route, no VDOM | `load` functions | Team prefers Svelte's compiler-driven reactivity over React; smaller runtime |
| **Nuxt** | — | SSR/SSG/ISR, Vue equivalent of Next | `useFetch`/`useAsyncData` | Vue shop wanting Next-equivalent capabilities |
| **SolidStart** | — | Fine-grained reactivity, SSR + resumability | `createResource`, server functions | Performance-obsessed team willing to trade ecosystem size for a smaller, faster runtime |

Don't evaluate these on syntax. Evaluate on: does the team already know React
(then Next/Remix/TanStack Start), is the site 90% static content (then Astro),
is it a SPA behind a login wall with no SEO requirement (then Vite+React, full
stop — don't reach for a meta-framework you don't need).

## The rendering-strategy decision

This is the actual engineering decision. Every meta-framework above is just a
delivery mechanism for some subset of these strategies.

| Strategy | What runs where | TTFB | TTI | SEO | Content freshness | Cost |
|---|---|---|---|---|---|---|
| **CSR** (client-side render) | Empty HTML shell; JS fetches data and renders in-browser | Fast (static shell) | Slow (wait for JS bundle + data fetch) | Poor — crawlers see a blank div unless they execute JS | Always fresh (fetched at runtime) | Cheapest to host (static files + CDN) |
| **SSR** (server-side render, per request) | Full HTML rendered on server for every request | Slower (server does work per request) | Fast (HTML has content; hydration is cheap-ish) | Excellent | Always fresh | Server compute per request |
| **SSG** (static site generation, build time) | HTML rendered once at build, served as static file | Fastest (pure static file from CDN) | Fast | Excellent | Stale until next build/deploy | Cheapest to run, but rebuild-and-redeploy to update |
| **ISR** (incremental static regen) | SSG, but pages regenerate in the background after a `revalidate` window or on-demand | Fast (serves stale-while-revalidating) | Fast | Excellent | Fresh within your revalidate window | Cheap; occasional regen compute |
| **Streaming SSR** | Server sends HTML in chunks as it becomes ready — shell first, slow data later | Fast (shell arrives immediately) | Fast for above-the-fold; progressive for the rest | Excellent | Always fresh | Server compute, but perceived latency is much better than blocking SSR |
| **RSC** (React Server Components) | Some components render exclusively on the server and never ship their code to the client; others are Client Components that hydrate | Fast (server does the heavy render, sends less JS) | Fast (smaller client bundle = less to parse/hydrate) | Excellent | Always fresh (or cacheable per-component) | Server compute, but lower client bundle cost than full CSR/SSR-hydrate-everything |

### How to choose

Ask these in order:

1. **Does this page need to rank in search or be link-unfurled (OG tags)?**
   If yes, CSR is disqualified — crawlers and unfurlers that don't execute JS
   (many still don't, and even Googlebot's JS rendering is a second-pass queue
   that can lag by days) will see nothing. Pick SSR/SSG/ISR/streaming/RSC.

2. **Is the content the same for every user, and does it change less often
   than you deploy?** (Marketing pages, docs, blog posts.) SSG or ISR. Build
   once, serve from CDN edge, cheapest possible TTFB.

3. **Is the content the same for every user but changes between deploys —
   e.g., a product catalog that updates hourly via a CMS webhook?** ISR with
   on-demand revalidation. You get SSG's speed with a freshness escape hatch.

4. **Is the content personalized per request (auth-gated dashboard, user
   feed) but you still want a fast first paint and good SEO for the shell?**
   Streaming SSR or RSC. Send the static shell (nav, layout) instantly, stream
   in the personalized data as it resolves.

5. **Is this behind a login wall with zero SEO surface — an admin panel, an
   internal tool?** CSR is not just acceptable, it's *correct*. You gain
   nothing from SSR (nobody crawls it, TTFB doesn't matter as much once a user
   is authenticated and using the app daily) and you avoid an entire class of
   server-infra complexity: no server render pipeline, no hydration mismatch
   bugs, simpler deploys (static files behind an auth proxy). **A SPA is not
   a legacy pattern — it's the right tool when SEO is irrelevant and you want
   the simplest mental model available.**

The TTFB-vs-TTI tension is the crux: SSR/SSG buys you TTFB and SEO at the cost
of either build complexity (SSG staleness) or server compute (SSR per
request). Streaming and RSC are the two techniques that try to have both —
fast shell, progressive content — at the cost of a more complex mental model.

## React Server Components: what actually runs where

RSC is not "SSR but newer." It's a build-time/render-time split of your
component tree into two universes that never fully merge:

- **Server Components** (default in the App Router, no directive needed) run
  **only on the server**. Their code is never sent to the browser. They can
  do async work directly — `await fetch(...)`, hit a database, read a secret
  env var — because they execute in a trusted server context.
- **Client Components** (marked with `"use client"` at the top of the file)
  run on the server for the *initial* render (to produce HTML) and then
  **also** ship their JS to the browser and hydrate, so they can respond to
  clicks, hold `useState`, use effects, etc.

```tsx
// app/dashboard/page.tsx — Server Component (no directive = server by default)
import { UserGreeting } from "./user-greeting"; // Client Component

async function DashboardPage() {
  // Runs on the server. Can talk to a DB or internal service directly —
  // no API route needed, no client-side waterfall, no exposed credentials.
  const user = await db.users.findCurrent();

  return (
    <div>
      <h1>Welcome back</h1>
      {/* Passing SERIALIZABLE props across the server/client boundary is fine */}
      <UserGreeting name={user.name} joinedAt={user.joinedAt.toISOString()} />
    </div>
  );
}
```

```tsx
// app/dashboard/user-greeting.tsx — Client Component
"use client";

import { useState } from "react";

export function UserGreeting({ name, joinedAt }: { name: string; joinedAt: string }) {
  const [expanded, setExpanded] = useState(false); // needs interactivity → must be client
  return (
    <button onClick={() => setExpanded(!expanded)}>
      Hi {name}{expanded ? ` (joined ${joinedAt})` : ""}
    </button>
  );
}
```

### The `"use client"` boundary is a serialization boundary, not a stylistic one

Everything crossing from a Server Component into a Client Component as props
must survive serialization — because under the hood it's transmitted over the
RSC wire protocol (conceptually similar to JSON, with support for a few extra
types like `Date`, `Map`, `Set`, and Promises for streaming). This means:

```tsx
// WRONG — passing a function from Server to Client Component
async function ServerPage() {
  async function handleDelete(id: string) {   // closure over server-only state
    await db.items.delete(id);
  }
  // Functions can't be serialized across the boundary. This throws at build/
  // render time: "Functions cannot be passed directly to Client Components
  // unless you explicitly expose it by marking it with 'use server'."
  return <DeleteButton onDelete={handleDelete} />;
}

// RIGHT — expose server logic as a Server Action, which IS a special
// serializable reference (a callable RPC endpoint), not a raw closure
async function ServerPage() {
  async function handleDelete(id: string) {
    "use server"; // marks this function as a Server Action — safe to pass down
    await db.items.delete(id);
  }
  return <DeleteButton onDelete={handleDelete} />;
}
```

Other things that cannot cross the boundary as props: class instances, Symbols,
functions that aren't Server Actions, React context values created on the
server (Context.Provider itself can be a Server Component wrapping Client
Component consumers, but the *value* must be serializable or the Provider
itself needs to be a Client Component).

The practical rule: **push Client Components as far down the tree as
possible.** Don't mark a whole page `"use client"` because one button needs
`onClick`. Isolate the interactive leaf, keep everything above it — data
fetching, layout, static content — as Server Components so their code and
their dependencies never ship to the browser.

```tsx
// WRONG — marking the whole page client just because of one interactive widget
"use client";
export default function ProductPage({ product }) {
  const [qty, setQty] = useState(1);
  return (
    <div>
      <ProductGallery images={product.images} />   {/* now also shipped as client JS */}
      <ProductDescription text={product.description} /> {/* same */}
      <QuantityPicker value={qty} onChange={setQty} />
    </div>
  );
}

// RIGHT — page stays a Server Component; only the picker is client
export default async function ProductPage({ params }) {
  const product = await getProduct(params.id); // server-only fetch, no client waterfall
  return (
    <div>
      <ProductGallery images={product.images} />       {/* server-rendered, zero client JS */}
      <ProductDescription text={product.description} /> {/* server-rendered, zero client JS */}
      <QuantityPicker />  {/* "use client" internally; the only JS shipped */}
    </div>
  );
}
```

## When a SPA is still the right answer

The industry narrative is "everything should be SSR/RSC now." That's wrong for
a specific and common case: **internal tools behind auth**. An admin console,
an ops dashboard, an internal CRUD app. Characteristics:

- No SEO surface — it's not indexed, not shared as a link preview, not
  discovered by search. RSC/SSR buys you nothing here.
- Users are logged in for the entire session; the "first paint before
  hydration" win of SSR matters far less than for a marketing page a stranger
  bounces off in two seconds.
- The team wants the simplest possible mental model: one client bundle, one
  deploy target (static files + CDN, or even just an S3 bucket), no server
  render pipeline to operate, no hydration-mismatch class of bugs, no
  server/client component split to reason about.
- Vite + React SPA + TanStack Query/Router gets you there with the fastest
  dev server, the simplest deploy, and zero server-side surprises.

Don't cargo-cult RSC onto a tool where nobody will ever hit it unauthenticated.
The complexity tax of a server-render pipeline only pays for itself when SEO,
first-paint-for-strangers, or per-request personalization at the edge actually
matter.

## Checklist

- [ ] Chose rendering strategy based on SEO + freshness + auth requirements,
      not framework popularity
- [ ] Confirmed whether content is the same for every user (SSG/ISR
      candidate) or personalized (SSR/streaming/RSC candidate)
- [ ] For RSC: interactive components isolated as small `"use client"` leaves,
      not whole-page directives
- [ ] No functions passed as props across the server/client boundary except
      via `"use server"` Server Actions
- [ ] Verified all Server → Client props are serializable (no class instances,
      no raw functions, no Symbols)
- [ ] Considered a plain SPA for anything behind auth with no SEO need,
      instead of defaulting to a meta-framework
- [ ] For content-heavy sites, evaluated Astro's islands before reaching for
      a full JS framework
