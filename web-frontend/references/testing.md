# Testing

Frontend tests follow a pyramid, same shape as backend: **many** component
tests, **some** integration tests, **few** end-to-end tests. The inversion —
a suite dominated by E2E because "it tests the real thing" — is how teams end
up with a 40-minute CI run and a flaky test culture nobody trusts. Push
verification down the pyramid as far as it will honestly go.

## The pyramid

| Layer | Tool | What it covers | Speed | Count |
|---|---|---|---|---|
| **Component** | Vitest 4 + React Testing Library | A component's rendered output and behavior in isolation | Milliseconds each | Many — one file per component with meaningful logic |
| **Integration** | Vitest + RTL + MSW | Several components wired together, network mocked at the HTTP boundary | Tens of ms each | Some — key flows spanning multiple components (a form + its submission handling) |
| **E2E** | Playwright | A real browser, a real (or staging) backend, a critical user journey start to finish | Seconds each | Few — signup, checkout, the 5-10 flows that must never break |

## Vitest 4 + React Testing Library

**Query priority** exists because RTL's philosophy is "test like a user
would interact with your app," and the query hierarchy is ordered by how
closely each one matches how a real user (and a screen reader) perceives the
page:

```
getByRole            >  getByLabelText  >  getByPlaceholderText  >  getByText  >>  getByTestId
(accessibility tree)    (form fields)      (weak fallback)          (visible text)   (escape hatch, last resort)
```

```tsx
// WRONG — data-testid has no relationship to what a user or screen reader
// perceives. It also breaks the moment someone renames the attribute, even
// if the component's actual behavior is unchanged and correct.
test("submit button works", async () => {
  render(<SignupForm />);
  await userEvent.click(screen.getByTestId("submit-btn"));
  expect(screen.getByTestId("success-msg")).toBeInTheDocument();
});

// RIGHT — queries the accessible name, the same way a screen reader or a
// sighted user scanning for "the button that says Submit" would find it.
// If this query fails, it's a real signal: your button doesn't have an
// accessible name.
test("submitting valid form shows a success message", async () => {
  render(<SignupForm />);
  await userEvent.type(screen.getByLabelText("Email"), "user@example.com");
  await userEvent.click(screen.getByRole("button", { name: "Sign up" }));
  expect(await screen.findByText("Welcome aboard")).toBeInTheDocument();
});
```

**`userEvent` over `fireEvent`.** `fireEvent.click` dispatches a single DOM
event. `userEvent.click` simulates the full sequence a real interaction
produces — pointer down, focus, pointer up, click — including side effects
like a checkbox toggling or an input receiving focus before typing. Bugs
that only manifest through the full event sequence (a blur handler, a focus
trap) are invisible to `fireEvent` and caught by `userEvent`.

**`findBy*` for anything async.** `getBy*` throws synchronously if the
element isn't there *yet*; `findBy*` is `getBy*` + `waitFor` combined, and is
the only correct choice after triggering something that resolves
asynchronously (a query result landing, a modal animating in).

```tsx
// WRONG — getByText assumes the text is already in the DOM synchronously.
// If the data hasn't arrived from the mocked network call yet, this throws
// immediately instead of waiting.
await userEvent.click(screen.getByRole("button", { name: "Load" }));
expect(screen.getByText("Loaded!")).toBeInTheDocument();

// RIGHT — findByText polls until the element appears (or times out),
// which is what you want after any action that triggers async work.
await userEvent.click(screen.getByRole("button", { name: "Load" }));
expect(await screen.findByText("Loaded!")).toBeInTheDocument();
```

**Never assert on implementation details.** Internal `useState` values,
prop values passed to a child, exact CSS class names, or render counts are
all things a correct refactor can change without changing user-visible
behavior — a test coupled to them fails on a good change and gives false
confidence about a bad one.

```tsx
// WRONG — asserts on an implementation detail (component internal state via
// a wrapper's instance, or a class name) rather than what the user sees.
expect(wrapper.find("Modal").prop("isOpen")).toBe(true);
expect(container.querySelector(".modal--open")).not.toBeNull();

// RIGHT — asserts on the user-visible outcome: is the dialog actually
// present and readable in the accessibility tree?
expect(screen.getByRole("dialog", { name: "Confirm deletion" })).toBeVisible();
```

## MSW: mock at the network boundary

Mock Service Worker intercepts actual `fetch`/`XHR` calls at the network
layer, so your component code runs completely unmodified — no injecting a
fake API client, no mocking `fetch` globally and hoping every call site
matches your mock shape.

```ts
// mocks/handlers.ts
import { http, HttpResponse } from "msw";

export const handlers = [
  http.get("/api/users/:id", ({ params }) => {
    return HttpResponse.json({ id: params.id, name: "Ada Lovelace" });
  }),
  http.post("/api/signup", async ({ request }) => {
    const body = await request.json();
    if (!body.email) return HttpResponse.json({ error: "Email required" }, { status: 400 });
    return HttpResponse.json({ id: "usr_1" }, { status: 201 });
  }),
];
```

```tsx
// setupTests.ts — same handlers work in component tests AND in the browser
// via a service worker during manual dev testing.
import { server } from "./mocks/server";
beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
```

This is what makes the useQuery-wrapped-in-a-custom-hook pattern
(`useRecentActivity()`, etc. — see `state-data.md`) easy to test: the
component under test calls the real hook, the real hook calls the real
`fetch`, and MSW intercepts only at the HTTP layer — nothing about the
component or hook's code path is replaced with a test double.

## Playwright for E2E

**What belongs in E2E: critical user journeys only.** Signup, login,
checkout, the handful of flows where a regression means real money or real
users locked out — not every page, not every edge case (those belong at the
component/integration layer, where they run in milliseconds instead of
seconds and don't need a browser).

```ts
// e2e/checkout.spec.ts
import { test, expect } from "@playwright/test";
import { CheckoutPage } from "./pages/checkout-page";

test("user can complete checkout with a saved card", async ({ page }) => {
  const checkout = new CheckoutPage(page);
  await checkout.goto();
  await checkout.addItemToCart("sku_123");
  await checkout.proceedToPayment();
  await checkout.selectSavedCard();
  await checkout.confirmOrder();

  await expect(page.getByRole("heading", { name: "Order confirmed" })).toBeVisible();
});
```

```ts
// e2e/pages/checkout-page.ts — Page Object Model: E2E specs read as user
// journeys, and selector/interaction details live in one place per page.
// When a selector changes, you fix it in one file, not in every spec that
// touches that page.
export class CheckoutPage {
  constructor(private page: Page) {}

  async goto() { await this.page.goto("/checkout"); }

  async addItemToCart(sku: string) {
    await this.page.getByTestId(`add-to-cart-${sku}`).click(); // testid OK here — no a11y story for internal test hooks in E2E setup steps
  }

  async proceedToPayment() {
    await this.page.getByRole("button", { name: "Proceed to payment" }).click();
  }

  async selectSavedCard() {
    await this.page.getByRole("radio", { name: /Visa ending in/ }).check();
  }

  async confirmOrder() {
    await this.page.getByRole("button", { name: "Place order" }).click();
  }
}
```

**Avoiding flakiness** is mostly about not fighting Playwright's built-in
auto-waiting:

```ts
// WRONG — arbitrary sleep guesses at timing; too short and it's flaky, too
// long and every run is slower than it needs to be for no benefit.
await page.click("button#submit");
await page.waitForTimeout(2000);
expect(await page.textContent(".result")).toBe("Success");

// RIGHT — Playwright's locators auto-wait for the element to be actionable
// (attached, visible, stable, enabled) before interacting, and expect()
// assertions auto-retry until they pass or time out. No manual sleep needed.
await page.getByRole("button", { name: "Submit" }).click();
await expect(page.getByText("Success")).toBeVisible();
```

Other flakiness sources: shared test data mutated by parallel test runs (use
unique/seeded data per test, not a shared fixture record), and
non-deterministic ordering assumptions (seed random data with a fixed seed
so "the 3rd item in the list" is stable across runs).

## Visual regression

Pixel/DOM-snapshot diffing (Playwright's own `toHaveScreenshot()`, or
Chromatic/Percy layered on Storybook) catches unintended visual drift — a
CSS change that silently breaks a layout elsewhere — that functional
assertions don't see at all. Cheap to add per component story, but accept
some maintenance cost: intentional design changes require re-approving
baselines, and font-rendering differences across CI runners can cause noisy
false positives if not pinned to one rendering environment.

## Accessibility assertions in tests

```tsx
// Bake an axe check into representative component tests, not just as a
// separate manual audit — see accessibility.md for the full rationale.
import { axe } from "vitest-axe";

test("Modal has no automated a11y violations when open", async () => {
  const { container } = render(<Modal open>Content</Modal>);
  expect(await axe(container)).toHaveNoViolations();
});
```

And in Playwright E2E, `@axe-core/playwright` runs the same check against a
fully rendered, real-browser page — catching issues that only appear after
real CSS layout and real focus behavior, which jsdom-based component tests
can't see.

## What NOT to test

- **Third-party library internals.** Don't test that `useState` updates
  state, or that TanStack Query caches — test your usage of them.
- **Trivial pass-through components** with no logic (`<Container>{children}</Container>`).
- **CSS values via snapshot of computed styles** — brittle, and a visual
  regression tool does this job better.
- **Every prop combination exhaustively** for a component with many props —
  test the meaningful behavioral branches, not the full combinatorial space.
- **The same behavior at every layer.** If an integration test already
  covers "form submission calls the API and shows a success message," a
  component test re-asserting the exact same path adds cost without adding
  confidence. Test different *concerns* at different layers, not the same
  concern redundantly.

## Checklist

- [ ] Test suite shape follows the pyramid: many component, some
      integration, few E2E — not inverted
- [ ] Component tests query via `getByRole`/`getByLabelText` over
      `getByTestId`, and use `userEvent` over `fireEvent`
- [ ] Async assertions use `findBy*` (or `waitFor`), never a bare `getBy*`
      immediately after triggering async work
- [ ] No assertions on implementation details (internal state, class names,
      prop values) — only user-visible outcomes
- [ ] Network mocked at the HTTP boundary (MSW), not by mocking `fetch` or
      injecting a fake API client
- [ ] E2E covers only critical journeys, uses Page Objects, and relies on
      Playwright's auto-waiting instead of manual `waitForTimeout`
- [ ] E2E test data is unique/seeded per test — no shared mutable fixtures
      across parallel runs
- [ ] Visual regression baselines reviewed as part of intentional design
      changes, not treated as noise to dismiss
- [ ] At least representative components/pages get an automated `axe` check
      as part of the test suite, not only a manual audit
- [ ] No tests for third-party library internals, trivial pass-throughs, or
      the same concern redundantly re-tested at every pyramid layer
