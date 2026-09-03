# Build, config & deploy for a web frontend

## The env-var leak — read this first

Every bundler inlines prefixed env vars into the JavaScript it ships. `VITE_*`,
`NEXT_PUBLIC_*`, `PUBLIC_*` — these are **compile-time text substitutions**, not runtime
secrets.

```ts
// CATASTROPHIC. This key is now in a .js file on your CDN, readable by anyone
// who opens devtools. Rotating it is the only remediation.
const stripe = new Stripe(import.meta.env.VITE_STRIPE_SECRET_KEY);

// FINE — a publishable key is designed to be public.
const stripe = new Stripe(import.meta.env.VITE_STRIPE_PUBLISHABLE_KEY);
```

Rules that prevent it:

- **Treat any prefixed var as published.** If you wouldn't tweet it, it doesn't get a prefix.
- **Anything secret goes through a server route** — a Next.js route handler, an API endpoint,
  a BFF. The browser calls your server; your server holds the key.
- **Grep your bundle before you ship**: `grep -r "sk_live\|-----BEGIN\|AKIA" dist/` in CI. A
  five-second check that has saved real companies real money.
- **Never `import.meta.env` spread into a client object** — `{...import.meta.env}` ships
  every var including the unprefixed ones on some setups.

The failure is silent: the build succeeds, the app works, and the key is public. There is no
error to notice.

## TypeScript config for an app

```jsonc
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "moduleResolution": "bundler",     // matches how Vite/esbuild actually resolve
    "module": "ESNext",
    "verbatimModuleSyntax": true,      // `import type` is preserved/erased predictably —
                                       // prevents a type-only import causing a runtime import
    "jsx": "react-jsx",

    "strict": true,                    // non-negotiable
    "noUncheckedIndexedAccess": true,  // arr[0] is T | undefined — the highest-value
                                       // non-default strictness flag by a wide margin
    "noUnusedLocals": true,
    "noFallthroughCasesInSwitch": true,
    "isolatedModules": true,

    "noEmit": true,                    // the bundler emits; tsc only type-checks
    "skipLibCheck": true               // pragmatic: don't type-check node_modules
  }
}
```

`noUncheckedIndexedAccess` is the one people skip and shouldn't. Without it, `items[0].name`
type-checks and throws at runtime on an empty array — the single most common preventable
production TypeError.

Run `tsc --noEmit` in CI as a **separate step from the build**. Vite and esbuild strip types
without checking them, so a green build proves nothing about type correctness.

**TypeScript 7** is the Go-port compiler — a large speedup on the same language. Before
migrating, verify your ESLint type-aware rules, any `tsc` plugin, and your IDE integration
still work; the language is compatible but the toolchain surface isn't guaranteed to be.

## ESLint 10 flat config

**Current: ESLint 10.0.0** (Feb 2026, npm-verified 2026-08). This matters more than a
routine major bump, because **the eslintrc config system is now completely removed with no
opt-out**:

- `.eslintrc.*` and `.eslintignore` are **no longer honoured at all** — not deprecated,
  ignored.
- `ESLINT_USE_FLAT_CONFIG=false` no longer works; the v9 `LegacyESLint` compatibility layer
  is gone.
- CLI flags `--no-eslintrc`, `--env`, `--rulesdir`, `--ignore-path`,
  `--resolve-plugins-relative-to` are removed. `eslint-env` comments are dead.
- **Requires Node ≥ 20.19.0**; Node 18/19/21/23 support dropped.

If you're on ESLint 8 with `.eslintrc`, `npx @eslint/migrate-config .eslintrc.json`
generates an `eslint.config.mjs` to review. If you already moved to flat config in v9,
you're ~90% done.

Two v10 changes worth knowing beyond the config format:

- **Config lookup is now per-file**, resolved from each linted file's directory rather than
  the CWD. Multiple config files in one run now work — this is the fix for monorepos, and it
  was the `v10_config_lookup_from_file` flag in v9.
- **JSX references are now tracked**, so `no-unused-vars` correctly reports unused
  components. You can **delete `react/jsx-uses-vars`** from your config; it was a workaround
  for the old gap.

```js
// eslint.config.js
import js from "@eslint/js";
import tseslint from "typescript-eslint";
import react from "eslint-plugin-react";
import hooks from "eslint-plugin-react-hooks";
import a11y from "eslint-plugin-jsx-a11y";

export default tseslint.config(
  js.configs.recommended,
  ...tseslint.configs.recommendedTypeChecked,   // needs parserOptions.project
  {
    files: ["src/**/*.{ts,tsx}"],
    plugins: { react, "react-hooks": hooks, "jsx-a11y": a11y },
    languageOptions: { parserOptions: { projectService: true } },
    rules: {
      // These two catch real bugs, not style.
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",    // warn, not off — a missing dep is a stale
                                                // closure, which is a real class of bug

      // a11y from day one. Retrofitting accessibility costs far more than
      // never breaking it.
      ...a11y.configs.recommended.rules,

      "@typescript-eslint/no-floating-promises": "error",  // an unawaited promise swallows
                                                          // rejections — silent failure
      "@typescript-eslint/no-misused-promises": "error",   // async fn where void expected
    },
  },
);
```

Enable the **type-checked** ruleset, not just `recommended`. `no-floating-promises` alone
catches a category of silent failure that no amount of testing reliably finds.

Prettier handles formatting; don't duplicate formatting rules in ESLint (they'll fight).

## Vite config essentials

```ts
export default defineConfig({
  plugins: [react()],
  build: {
    sourcemap: true,           // generate them — see below for where they go
    target: "es2022",
    rollupOptions: {
      output: {
        // Split large stable deps so an app change doesn't invalidate them.
        // Don't over-engineer this: too many chunks means too many requests.
        manualChunks: { react: ["react", "react-dom"] },
      },
    },
  },
  server: { proxy: { "/api": { target: "http://localhost:8080", changeOrigin: true } } },
});
```

Two things worth knowing: `define` values are **string replacements**, so
`define: { __VERSION__: pkg.version }` needs `JSON.stringify()` or you inject a bare
identifier. And in dev, Vite pre-bundles dependencies — a dependency that only breaks in
production is often an ESM/CJS interop difference between the dev server and the Rollup build.

## Caching — get the two directions right

This is a two-line configuration that decides whether users see your deploy.

| Asset | Header | Why |
|---|---|---|
| Hashed JS/CSS (`app.a3f9b2.js`) | `Cache-Control: public, max-age=31536000, immutable` | The filename changes when the content does, so it can be cached forever. |
| HTML (`index.html`) | `Cache-Control: no-cache` (or `max-age=0, must-revalidate`) | HTML references the hashed assets. Cache it and users get an old app pointing at deleted files. |
| Fonts, images (hashed) | `immutable` | Same as JS. |
| `/api/*` | `no-store` unless deliberately cached | |

**Get this backwards and you produce a specific, confusing bug**: HTML cached long, assets
`no-cache` → users load stale HTML that requests chunk hashes which no longer exist → a
white screen and `ChunkLoadError` after every deploy. Handle it defensively too: catch
dynamic-import failures and prompt a reload.

## Source maps

**Generate them. Don't serve them publicly.**

Without source maps your error tracker shows `a.b is not a function` at
`app.a3f9b2.js:1:48213`, which is useless. With them public, anyone can reconstruct your
source.

The pattern: build with `sourcemap: true`, upload the `.map` files to your error tracker
(Sentry et al.) as a build step, then **delete them from the deployed artifact**. Same for
Next.js — upload, then exclude from the public output.

## Security headers & CSP

```
Content-Security-Policy: default-src 'self';
  script-src 'self';                      /* no 'unsafe-inline', no 'unsafe-eval' */
  style-src 'self' 'unsafe-inline';       /* pragmatic: many CSS-in-JS setups need it */
  img-src 'self' data: https:;
  connect-src 'self' https://api.example.com;
  frame-ancestors 'none';
  base-uri 'self';
  object-src 'none'
Strict-Transport-Security: max-age=63072000; includeSubDomains
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(), microphone=(), geolocation=()
```

Notes from practice: **`'unsafe-inline'` in `script-src` defeats the point of CSP** — use
nonces or hashes if you need inline scripts (Next.js can generate nonces). Roll CSP out in
**`Content-Security-Policy-Report-Only`** first and watch the violation reports, because a
strict CSP shipped blind will break a third-party widget you forgot about. And
`frame-ancestors 'none'` is the modern replacement for `X-Frame-Options`.

Add **SRI** (`integrity=`) on any script you load from a CDN you don't control.

## Bundle-size budgets in CI

Budgets added later never pass. Add one on day one, when the app is small.

```jsonc
// CI fails if the entry chunk exceeds the budget. The number matters less than
// the ratchet: it stops silent 20KB-per-PR growth.
{ "budgets": [{ "type": "initial", "maximumWarning": "180kb", "maximumError": "250kb" }] }
```

Also worth automating: a bundle-diff comment on PRs (`size-limit`, `bundlewatch`, or a
CI script). Reviewers can't see that a convenience import pulled in a date library; a bot can.

Watch for the two silent bloat sources: **barrel files** (`import { x } from "@/components"`
pulls the whole re-export graph) and **default-importing a large library** for one function.

## Deploy shape

| App type | Deploy as |
|---|---|
| SPA (Vite) | Static files + CDN. No server to run, no server to patch. Cheapest and most reliable. |
| SSR (Next/Remix) | Node container or a platform adapter. Now you own a runtime: health checks, graceful shutdown, memory limits — see `node-microservice`. |
| Static + islands (Astro) | Static + CDN, with functions only where needed. |

If you deploy SSR in a container, it is a Node service and inherits every Node concern:
`--max-old-space-size` below the memory limit, `--init` for PID 1, graceful shutdown with a
pre-stop delay. Don't treat it as "just the frontend".

**Version-drift discipline** matters across an org. Keep majors aligned — especially
validation libraries. Zod 3 in one repo and Zod 4 in another means a shared schema package is
impossible, and the two repos silently disagree about what valid input looks like. Use
Renovate/Dependabot with grouped major PRs so upgrades happen deliberately rather than never.

## Checklist

- [ ] No secret behind `VITE_`/`NEXT_PUBLIC_`; bundle grepped for key patterns in CI
- [ ] Secrets accessed only via a server route
- [ ] `strict: true` **and** `noUncheckedIndexedAccess`
- [ ] `tsc --noEmit` as a separate CI step from the build
- [ ] ESLint **10 flat config**, type-checked ruleset, `no-floating-promises` on
- [ ] `jsx-a11y` enabled from the first commit
- [ ] Hashed assets `immutable`; HTML `no-cache`
- [ ] Dynamic-import failure handled with a reload prompt
- [ ] Source maps generated, uploaded to the error tracker, **not deployed**
- [ ] CSP without `'unsafe-inline'` in `script-src`; rolled out report-only first
- [ ] HSTS, `nosniff`, `Referrer-Policy`, `frame-ancestors 'none'`
- [ ] Bundle budget enforced in CI + size diff on PRs
- [ ] Barrel-file and large-default-import bloat checked
- [ ] Dependency majors aligned across repos (validation libraries especially)
- [ ] SSR deploys treated as Node services (memory limits, PID 1, graceful shutdown)
