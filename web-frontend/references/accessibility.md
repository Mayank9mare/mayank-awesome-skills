# Accessibility

Most accessibility work is not ARIA. It's using the HTML element that already
has the behavior you want, instead of reimplementing that behavior badly on a
`<div>`. ARIA is what you reach for when semantic HTML genuinely runs out —
and reaching for it first, or reaching for it when it wasn't needed, is the
most common a11y mistake in React codebases.

## Semantic HTML first

```tsx
// WRONG — a div with an onClick "looks" clickable but gets none of the
// platform behavior for free: no keyboard focus, no Enter/Space activation,
// no announced role, no disabled state, nothing.
function SubmitAction({ onSubmit }: { onSubmit: () => void }) {
  return <div className="btn" onClick={onSubmit}>Submit</div>;
}
// A screen reader announces this as nothing. Tab skips right past it.
// A keyboard-only user cannot activate it at all.

// RIGHT — a real <button> gets focus, keyboard activation (Enter AND
// Space), the "button" role, and disabled semantics, all without a single
// line of extra code.
function SubmitAction({ onSubmit }: { onSubmit: () => void }) {
  return <button onClick={onSubmit}>Submit</button>;
}
```

The general rule: reach for `<button>`, `<a href>`, `<input>`, `<select>`,
`<label>`, `<nav>`, `<main>`, `<h1>`–`<h6>` before reaching for a styled
`<div>` with a role bolted on. Every one of those elements gives you free,
browser-implemented behavior that a `<div>` + JS reimplementation will
under-deliver on some edge case you didn't think to test (Space-to-activate,
screen-reader-specific navigation shortcuts by heading level, form
autofill).

```tsx
// WRONG — a link that navigates via onClick instead of href means no
// "open in new tab," no "copy link address," no status-bar URL preview,
// and search engines see nothing to crawl.
function ProductLink({ id, children }: { id: string; children: React.ReactNode }) {
  const navigate = useNavigate();
  return <span onClick={() => navigate(`/products/${id}`)}>{children}</span>;
}

// RIGHT
function ProductLink({ id, children }: { id: string; children: React.ReactNode }) {
  return <Link to={`/products/${id}`}>{children}</Link>; // renders a real <a>
}
```

## Keyboard navigation and focus management

Every interactive element must be reachable by Tab and operable without a
mouse. Two situations React apps routinely get wrong: modal focus trapping,
and focus restoration on close.

```tsx
// WRONG — opening a modal doesn't move focus into it. A keyboard/screen-
// reader user tabbing through the page has no idea a modal opened; focus
// stays on whatever was behind it (or worse, on a now-hidden trigger).
function Modal({ open, children }: { open: boolean; children: React.ReactNode }) {
  if (!open) return null;
  return <div className="modal">{children}</div>;
}

// RIGHT — focus moves into the modal on open, is trapped inside it while
// open (Tab can't escape to the page behind), and returns to the trigger
// element on close. Radix's Dialog / most modal primitives do this for you;
// here's what it does under the hood.
function Modal({ open, onClose, children }: ModalProps) {
  const contentRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (open) {
      triggerRef.current = document.activeElement as HTMLElement; // remember what opened it
      contentRef.current?.focus();
    } else {
      triggerRef.current?.focus(); // restore focus on close
    }
  }, [open]);

  if (!open) return null;
  return (
    <FocusTrap>
      <div ref={contentRef} role="dialog" aria-modal="true" tabIndex={-1}>
        {children}
        <button onClick={onClose}>Close</button>
      </div>
    </FocusTrap>
  );
}
```

**Don't hand-roll a focus trap.** Getting Tab/Shift+Tab wrap-around correct
at the first/last focusable element, handling dynamically added focusables,
and interacting correctly with `Escape` is fiddly enough that Radix's
`Dialog`, Headless UI, or `focus-trap-react` are the right call almost every
time — hand-rolling one is a common source of subtle a11y regressions.

**Skip links** let keyboard users jump past repeated navigation:

```tsx
// First focusable element on the page. Visually hidden until focused, so
// sighted mouse users never see it, but a keyboard user tabbing from the
// address bar lands on it immediately.
<a href="#main-content" className="sr-only focus:not-sr-only focus:absolute focus:top-0 focus:left-0">
  Skip to main content
</a>
<nav>{/* ... 20 nav links ... */}</nav>
<main id="main-content">{/* ... */}</main>
```

## ARIA: the first rule is don't

The first rule of ARIA use is: **if an HTML element or attribute already has
the semantics you need, use it instead of re-purposing an element with an
ARIA role.** ARIA describes behavior to assistive technology; it does not
implement it. Adding `role="button"` to a `<div>` announces it as a button
but does not give it keyboard activation — you'd still have to hand-wire
`onKeyDown` for Enter and Space, and you'd still be worse off than just using
`<button>`.

```tsx
// WRONG — role="button" on a div announces the role, but keyboard
// activation, focus, and disabled state are all still your job to build
// and easy to get subtly wrong (e.g. forgetting Space, only handling Enter).
<div role="button" tabIndex={0} onClick={submit} onKeyDown={(e) => e.key === "Enter" && submit()}>
  Submit
</div>

// RIGHT
<button onClick={submit}>Submit</button>
```

ARIA earns its place when there's genuinely no HTML equivalent: a live
region for async status updates, a combobox with a custom popup, a tab
panel set.

```tsx
// aria-label — accessible name when there's no visible text (icon-only button)
<button aria-label="Close dialog"><XIcon /></button>

// aria-describedby — links an element to its extended description elsewhere in the DOM
<input aria-describedby="password-hint" type="password" />
<p id="password-hint">Must be at least 12 characters.</p>

// aria-live — announces dynamic content changes that aren't in response to
// a user's own action (e.g. a background save confirmation, a toast).
// "polite" waits for the screen reader to finish its current utterance;
// "assertive" interrupts immediately — reserve assertive for genuine errors.
<div aria-live="polite" role="status">
  {saveStatus === "saved" && "Changes saved"}
</div>
```

## Forms

```tsx
// WRONG — placeholder is not a label. It disappears on input, isn't
// announced consistently across screen readers, and fails color-contrast
// requirements at typical placeholder opacity.
<input type="email" placeholder="Email address" />

// RIGHT — explicit label association via htmlFor/id (or wrapping the
// input in the label element) is announced by every screen reader and
// stays visible while the user types.
<label htmlFor="email">Email address</label>
<input id="email" type="email" />
```

```tsx
// WRONG — an inline error message with no programmatic link to the field
// and no announcement. A screen-reader user tabbing past the field hears
// nothing about the error; a sighted user scanning quickly might miss it too.
function EmailField({ error }: { error?: string }) {
  return (
    <div>
      <input type="email" />
      {error && <span className="text-red-500">{error}</span>}
    </div>
  );
}

// RIGHT — aria-invalid flags the field's state, aria-describedby links it
// to the error text, and role="alert" ensures the message is announced
// as soon as it appears (not just when focus happens to land on it).
function EmailField({ error }: { error?: string }) {
  return (
    <div>
      <label htmlFor="email">Email</label>
      <input
        id="email"
        type="email"
        aria-invalid={!!error}
        aria-describedby={error ? "email-error" : undefined}
      />
      {error && (
        <span id="email-error" role="alert" className="text-red-500">
          {error}
        </span>
      )}
    </div>
  );
}
```

## Colour contrast

WCAG AA requires a contrast ratio of **4.5:1** for normal text and **3:1**
for large text (≥24px, or ≥19px bold) against its background. AAA raises
that to 7:1 / 4.5:1. Check contrast at design time, not after a designer's
palette is already implemented — a brand's exact grey-on-white might land at
3.8:1 and fail AA for body copy. Browser DevTools' color picker and
axe both surface the actual computed ratio.

## Reduced motion

```css
/* Some users get vestibular symptoms (nausea, dizziness) from parallax,
   large-scale motion, and auto-playing animations. Respect the OS-level
   opt-out unconditionally — it's not a preference to override with a
   "cooler" experience. */
@media (prefers-reduced-motion: reduce) {
  * {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
```

## Testing

**Automated (axe)** catches roughly 30-40% of issues — missing alt text,
insufficient contrast, missing form labels, invalid ARIA usage. It cannot
catch "does this make sense read in order by a screen reader" or "is this
keyboard flow actually usable." Run it in CI (`@axe-core/react` in dev,
`jest-axe`/`vitest-axe` in tests, or `@axe-core/playwright` in E2E) as a
floor, not a ceiling.

```tsx
import { render } from "@testing-library/react";
import { axe } from "vitest-axe";

test("SignupForm has no automated a11y violations", async () => {
  const { container } = render(<SignupForm />);
  expect(await axe(container)).toHaveNoViolations();
});
```

**Testing Library query priority mirrors accessibility on purpose.**

```tsx
// WRONG — queries by an implementation detail (data-testid) that has no
// relationship to what a real user or a screen reader perceives. The test
// can pass while the component is completely inaccessible.
screen.getByTestId("submit-button");

// RIGHT — getByRole queries the accessibility tree the same way assistive
// tech does. If this query fails to find your button, a screen-reader user
// can't find it either — the test failure IS an accessibility bug report.
screen.getByRole("button", { name: "Submit" });
```

This is the deeper reason `getByRole` > `getByTestId`: it's not just a
testing-style preference, it's a built-in accessibility check on every
test run. A component that only passes `getByTestId` queries can ship with
zero accessible roles or names and nobody notices until a real user with a
screen reader hits it in production.

**Manual passes still matter** and automated tools cannot substitute for
them: a full keyboard-only pass (unplug the mouse, complete the primary user
flow using only Tab/Shift+Tab/Enter/Space/Arrow keys/Escape), and a basic
screen-reader pass (VoiceOver on macOS/iOS — Cmd+F5; NVDA on Windows, free)
listening for whether the page reads in a sensible order, whether
interactive elements announce their role and state, and whether dynamic
content changes are announced at all.

## Checklist

- [ ] Interactive elements use native HTML (`button`, `a`, `input`, `select`)
      before reaching for `<div>` + ARIA role + hand-wired keyboard handlers
- [ ] Every interactive element is reachable and operable via keyboard alone
- [ ] Modals trap focus while open and restore focus to the trigger on close
      (via a tested primitive, not hand-rolled)
- [ ] Skip link present for pages with repeated navigation
- [ ] ARIA used only where no HTML equivalent exists; `aria-label` on
      icon-only controls; `aria-live` for out-of-band status updates
- [ ] Every form input has an associated `<label>` (not just a placeholder)
- [ ] Form errors use `aria-invalid` + `aria-describedby` + an announced
      (`role="alert"`) message
- [ ] Text contrast meets 4.5:1 (normal) / 3:1 (large text) against its
      background
- [ ] `prefers-reduced-motion` respected for all non-essential animation
- [ ] Automated `axe` checks run in CI as a floor, not the only a11y testing
- [ ] Tests query via `getByRole`/`getByLabelText` over `getByTestId` —
      treat query failures as accessibility bugs, not just test flakiness
- [ ] At least one full keyboard-only pass and one screen-reader pass done
      manually before shipping a new flow
