# Real data, not mock data

Installed components ship with demo content: arrays of fake plans, users, messages, stats. The job
isn't done while any of it is left. The aim is a component that shows **the project's real data**,
typed, through the project's own fetch pattern, with every state handled.

## 1. Find the real source (Step 1 should already have this)
- **Existing API layer:** a `lib/api`, `services/`, generated client (OpenAPI, tRPC, GraphQL codegen),
  TanStack Query hooks, server actions, route handlers, CMS SDK.
- **Types:** generated types, zod schemas, shared `types/`. Use them; don't hand-write a parallel type.
- **Where it's fetched:** server (RSC, loaders, `getServerSideProps`) or client (Query or SWR hooks).
  Follow what the project already does for similar data (web-frontend `references/state-data.md`).

If there's no endpoint for something the design needs (for example a testimonials list), **don't
invent one silently.** Options to offer the user:
- (a) Static content in a typed content file (`content/testimonials.ts`) or the CMS, for content that
  is genuinely static.
- (b) Add the endpoint (a backend change, so ask first).
- (c) Drop the section.

Marketing copy that's static by nature (feature bullets, FAQ) belongs in a typed content module,
not hard-coded inside the component's JSX.

## 2. Reshape the component around data
- Turn the demo array into **props** with a precise type (`plans: Plan[]`), or a mapping from the API
  type to the component's view type in one adapter function (`toPricingCard(plan)`). Don't spread API
  shapes through the UI.
- Keep the component **presentational**. The page (or a container) fetches and passes data down. In
  RSC apps, fetch on the server and keep the interactive part as a small client component.
- Keys come from real ids, never array indexes.
- Formatting: currency, dates and numbers use the project's locale helpers (`Intl`), not string concatenation.

## 3. Every state, designed
| State | Must have |
|---|---|
| Loading | A skeleton the same size as the content (no layout shift); no spinner-only full page for sections |
| Empty | A real message and the next action ("No invoices yet — create one") |
| Error | A human message, a retry, and no raw error dump. Errors are logged the way the project logs them |
| Partial / slow | Streaming or Suspense boundaries per section, so one slow call doesn't blank the page |
| Long / odd data | Long names truncate or wrap; 0, 1 and 1,000 items all look right; missing optional fields are hidden cleanly |
| Auth | Logged-out and no-permission states if the data is protected |

## 4. Mutations and interaction
- Forms use the project's form and validation stack (React Hook Form + zod, server actions…), with
  field errors, disabled-while-submitting and success feedback.
- After a mutation, invalidate or revalidate the right queries; no stale UI.
- Optimistic updates only where the project already uses them, and always with a rollback.

## 5. Tests for the data wiring
- Render tests for loading, empty, error and success, with the project's mocking tool (MSW or test
  doubles at the API layer). Mocks live **in tests only**, never in the shipped component.
- One interaction test per interactive component (toggle a billing period, send a chat message,
  open a dialog).

## 6. Before calling it done
Search the diff for leftovers. Matches in tests are fine; matches in shipped code are not:

```bash
git diff | grep -nEi 'lorem|john doe|jane doe|acme|example\.com|placeholder|mock|dummy|fake|TODO|\$9\.99|99\.99'
```
