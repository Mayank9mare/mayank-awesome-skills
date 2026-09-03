# State Management: Server State vs Client State

The single most consequential architectural decision in a React app is
recognizing that **server state and client state are different problems with
different solutions**, and that conflating them is the root cause of most
React data bugs: stale UI, race conditions on fast navigation, duplicate
fetches, manually-wired loading spinners that get the boolean wrong, and
"why did this re-render four times" debugging sessions.

## The distinction

| | Server state | Client state |
|---|---|---|
| **Owned by** | The backend; your component just holds a cached copy | The component/app itself |
| **Examples** | User profile, product list, order history, anything from an API | Form input mid-typing, modal open/closed, selected tab, theme preference |
| **Can go stale** | Yes — someone else can change it | No — you're the only writer |
| **Needs** | Caching, deduplication, background refetch, invalidation, retry | Simple synchronous updates |
| **Right tool** | TanStack Query (or SWR, RTK Query) | `useState`/`useReducer`, Zustand, Jotai, Context (sparingly) |

If you reach for `useState` + `useEffect` to hold server data, you're
rebuilding — badly, by hand — the cache invalidation, deduplication, and
race-condition handling that a server-state library already solved. If you
reach for TanStack Query to hold "is this dropdown open," you're adding
machinery a boolean doesn't need.

## Server state: TanStack Query

### `queryKey` design

The key is the cache identity. Structure it so invalidation can target
exactly the right scope:

```ts
// Hierarchical: broad-to-narrow, so you can invalidate at any level
const keys = {
  all: ["todos"] as const,
  lists: () => [...keys.all, "list"] as const,
  list: (filters: TodoFilters) => [...keys.lists(), filters] as const,
  details: () => [...keys.all, "detail"] as const,
  detail: (id: string) => [...keys.details(), id] as const,
};

useQuery({ queryKey: keys.list({ status: "active" }), queryFn: () => fetchTodos({ status: "active" }) });
useQuery({ queryKey: keys.detail(id), queryFn: () => fetchTodo(id) });

// Invalidate ALL todo lists (any filter) after a mutation, without touching detail caches:
queryClient.invalidateQueries({ queryKey: keys.lists() });
```

### `staleTime` vs `gcTime` — the two knobs everyone confuses

```ts
useQuery({
  queryKey: keys.detail(id),
  queryFn: () => fetchTodo(id),
  staleTime: 30_000, // data is considered FRESH for 30s — no refetch on
                      // mount/refocus/reconnect during this window, even
                      // though it's still in the cache and rendered instantly
  gcTime: 5 * 60_000, // data stays in the cache for 5 MINUTES after the last
                       // component unsubscribes, before being garbage-collected.
                       // Renamed from cacheTime in v5. Controls memory, not freshness.
});
```

`staleTime: 0` (the default) means every mount/window-refocus triggers a
background refetch — fine for data that changes often, wasteful for data that
rarely does (e.g., a list of countries). Set `staleTime` per query based on
how fast that specific resource actually changes; don't set one global value
for everything.

### Invalidation

```ts
const queryClient = useQueryClient();

const { mutate } = useMutation({
  mutationFn: (todo: NewTodo) => createTodo(todo),
  onSuccess: () => {
    // Tell the cache "this data might be wrong now" — triggers a background
    // refetch for any active query matching the key, refreshing the UI
    // without a manual refetch call scattered through your components.
    queryClient.invalidateQueries({ queryKey: keys.lists() });
  },
});
```

### Optimistic updates with rollback

```ts
const { mutate } = useMutation({
  mutationFn: updateTodo,
  onMutate: async (newTodo) => {
    await queryClient.cancelQueries({ queryKey: keys.detail(newTodo.id) });
    const previous = queryClient.getQueryData(keys.detail(newTodo.id));

    // Write the optimistic value immediately — UI updates before the network
    // round-trip completes, which is the whole point of "optimistic."
    queryClient.setQueryData(keys.detail(newTodo.id), newTodo);

    // Stash the pre-mutation snapshot so onError can restore it.
    return { previous };
  },
  onError: (_err, newTodo, context) => {
    // Roll back to the snapshot. Without this step, a failed optimistic
    // update leaves the UI showing data that was never actually saved.
    if (context?.previous) {
      queryClient.setQueryData(keys.detail(newTodo.id), context.previous);
    }
  },
  onSettled: (_data, _err, newTodo) => {
    // Always resync with the server truth once the dust settles, whether
    // the mutation succeeded or failed.
    queryClient.invalidateQueries({ queryKey: keys.detail(newTodo.id) });
  },
});
```

### `select` for narrowing

```ts
// Subscribe to the full todo list query, but only re-render this component
// when the DERIVED count changes — not on every field change in every todo.
const { data: activeCount } = useQuery({
  queryKey: keys.list({}),
  queryFn: fetchAllTodos,
  select: (todos) => todos.filter((t) => !t.done).length,
});
```

`select` runs on every render but its result is memoized against the raw
query data — use it to avoid re-rendering on irrelevant field changes, and to
keep transformation logic out of components.

## The `useEffect`-fetch anti-pattern

This is the single most common React data bug, and it's taught in nearly
every beginner tutorial, which is why it's everywhere in production code.

```tsx
// WRONG — manual fetch-in-effect. Every one of these bugs is real and common:
// 1. No cancellation: if `id` changes fast (arrow-key navigation through a
//    list), the OLD request can resolve AFTER the new one and overwrite
//    fresh data with stale data — a race condition, not a hypothetical.
// 2. No dedup: two components fetching the same id fire two network calls.
// 3. No caching: navigating away and back refetches from scratch every time.
// 4. `loading` is trivially wrong on rapid re-renders — it can get stuck
//    true, or flash false between two overlapping fetches.
// 5. No retry, no stale-while-revalidate, no error boundary integration.
function UserProfile({ id }: { id: string }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetch(`/api/users/${id}`)
      .then((res) => res.json())
      .then((data) => {
        setUser(data);   // if `id` changed again before this resolves, this
        setLoading(false); // overwrites the newer request's eventual result
      });
  }, [id]);

  if (loading) return <Spinner />;
  return <div>{user?.name}</div>;
}
```

```tsx
// RIGHT — useQuery handles cancellation, dedup, caching, retry, and race
// conditions for you. The query key IS the cancellation/dedup boundary:
// TanStack Query automatically ignores the result of a superseded fetch.
function UserProfile({ id }: { id: string }) {
  const { data: user, isPending, isError } = useQuery({
    queryKey: ["users", id],
    queryFn: ({ signal }) => fetch(`/api/users/${id}`, { signal }).then((r) => r.json()),
    // `signal` is an AbortSignal TanStack Query provides — pass it to fetch
    // so an in-flight request is actually cancelled when `id` changes again.
  });

  if (isPending) return <Spinner />;
  if (isError) return <ErrorState />;
  return <div>{user.name}</div>;
}
```

There is no scenario where hand-rolled `useEffect` + `useState` fetching beats
a server-state library for anything beyond a genuinely one-off, fire-once,
never-refetched side effect (and even then, question whether it's really
server state at all).

## The recommended shape: per-concern custom hooks

Don't call `useQuery` inline all over your component tree with the query key
hardcoded in a dozen places. Wrap each server-state concern in a dedicated
hook that owns its key, its fetcher, and its cache tuning:

```ts
// src/hooks/useRecentActivity.ts
export function useRecentActivity(userId: string) {
  return useQuery({
    queryKey: ["activity", "recent", userId],
    queryFn: () => fetchRecentActivity(userId),
    staleTime: 60_000, // activity feed can be a minute stale, that's fine
  });
}
```

```tsx
// Component just calls the hook. It has NO idea what the query key is,
// how long data is cached, or what endpoint backs it. If the endpoint moves,
// or you switch from REST to GraphQL, exactly one file changes.
function ActivityFeed({ userId }: { userId: string }) {
  const { data, isPending } = useRecentActivity(userId);
  if (isPending) return <Spinner />;
  return <ul>{data.map((item) => <ActivityItem key={item.id} item={item} />)}</ul>;
}
```

This pattern — `useX()` hooks in `src/hooks/`, one per server-state concern —
is worth standardizing across a codebase. It gives you: a single place to
change caching behavior, a natural seam for testing (mock the hook, not
`fetch`), and it stops query keys from leaking into component code where a
typo silently breaks cache invalidation.

## Client state

| Tool | Use when |
|---|---|
| `useState` / `useReducer` | State is local to one component or a small subtree; no other component needs it |
| **Zustand** | Global client state shared across distant components (theme, auth session shape, UI flags), without provider nesting or boilerplate; minimal API, no context re-render problem |
| **Jotai** | Atomic state where different pieces of UI need independently-updating slices — avoids one big store object where any change re-renders every subscriber |
| **Redux Toolkit** | Large app, many developers, need for strict conventions/devtools/time-travel debugging, or existing org standard — heavier than the above two for equivalent problems, but battle-tested at scale |
| **Context** | Passing a rarely-changing value down deeply (theme, locale, an injected service) — NOT a general state manager |

### Context is not a state manager

```tsx
// WRONG — Context used as a general app-state store. EVERY consumer of
// CartContext re-renders on ANY change to ANY field, because Context has
// no selector mechanism: it delivers the whole value object on every update.
const CartContext = createContext<{ items: Item[]; total: number; discount: number }>(null!);

function CartProvider({ children }) {
  const [items, setItems] = useState<Item[]>([]);
  const [discount, setDiscount] = useState(0);
  const total = items.reduce((s, i) => s + i.price, 0);
  // Every re-render creates a new object identity — even components reading
  // only `discount` re-render when `items` changes, because they can't
  // subscribe to a slice, only to the whole context value.
  return <CartContext.Provider value={{ items, total, discount }}>{children}</CartContext.Provider>;
}

// RIGHT — Zustand gives every consumer a selector, so a component reading
// only `discount` does NOT re-render when `items` changes.
const useCartStore = create<CartState>((set) => ({
  items: [],
  discount: 0,
  addItem: (item) => set((s) => ({ items: [...s.items, item] })),
}));

function DiscountBadge() {
  const discount = useCartStore((s) => s.discount); // fine-grained subscription
  return <span>{discount}% off</span>;
}
```

Context is fine for values that change rarely (theme, i18n locale, a stable
service instance) precisely because infrequent change means the re-render cost
doesn't matter. The moment a Context value updates on every keystroke or every
list mutation, move it to a store with selectors.

## URL as state

Anything the user should be able to bookmark, share, or hit "back" to restore
belongs in the URL, not in component state:

```tsx
// Filters, pagination, selected tab, search query — all URL state.
// Refresh-safe, shareable, back-button-safe, and shallow-comparable.
const [searchParams, setSearchParams] = useSearchParams();
const page = Number(searchParams.get("page") ?? "1");
const sort = searchParams.get("sort") ?? "recent";

function setPage(next: number) {
  setSearchParams((prev) => {
    prev.set("page", String(next));
    return prev;
  });
}
```

Don't duplicate this into `useState` "for convenience" — you'll get
desynced state where the URL says page 3 but the UI shows page 1 after a
back-navigation the state didn't observe.

## Forms: React Hook Form + Zod, uncontrolled by default

```tsx
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

const schema = z.object({
  email: z.string().email(),
  age: z.number().int().min(18),
});
type FormValues = z.infer<typeof schema>;

function SignupForm() {
  const { register, handleSubmit, formState: { errors } } = useForm<FormValues>({
    resolver: zodResolver(schema),
    // Uncontrolled by default: RHF reads input values via refs, not via
    // onChange + setState on every keystroke. This avoids a re-render per
    // character typed — controlled inputs re-render the whole form tree
    // on every keystroke, which is fine for one field and a real cost at
    // twenty fields with validation running each time.
  });

  return (
    <form onSubmit={handleSubmit((data) => submit(data))}>
      <input {...register("email")} />
      {errors.email && <span role="alert">{errors.email.message}</span>}
      <input type="number" {...register("age", { valueAsNumber: true })} />
      {errors.age && <span role="alert">{errors.age.message}</span>}
      <button type="submit">Sign up</button>
    </form>
  );
}
```

The Zod schema is your single source of truth for shape and validation —
reuse it on the server (API route/Server Action) so client and server
validation can never drift apart. This is also why keeping Zod major versions
aligned across an org's repos matters: a schema authored against Zod 4 cannot
be imported into a codebase still on Zod 3 (breaking changes to `.parse`
error shape, `z.string().email()` deprecated in favor of `z.email()`, and the
core `ZodError` internals changed) — see `build-deploy.md` for the version-
drift discipline this implies.

## React 19 Actions — the fourth kind of state

React 19 added a set of APIs for **pending/optimistic state around a mutation**. They don't
replace TanStack Query (no cache, no dedupe, no invalidation, no refetch-on-focus), but they
do replace the hand-rolled `isSubmitting` / `error` / `optimisticValue` `useState` trio.

```tsx
// useActionState — the successor to the canary-only useFormState. Returns a THIRD
// value, isPending, which is why you rarely need useFormStatus in simple cases.
function UpdateName() {
  const [error, submitAction, isPending] = useActionState(
    async (_prev: string | null, formData: FormData) => {
      const result = await updateName(formData.get("name") as string);
      return result.error ?? null;   // returned value becomes the new state
    },
    null,
  );

  return (
    <form action={submitAction}>
      <input name="name" />
      <button disabled={isPending}>{isPending ? "Saving…" : "Save"}</button>
      {error && <p role="alert">{error}</p>}
    </form>
  );
}
```

| API | Use for |
|---|---|
| **`useActionState`** | Pending + error + result state for one action. The common case. |
| **`useOptimistic`** | Show the expected result immediately, auto-revert on failure. |
| `useFormStatus` | Pending state read by a *descendant* of the form (e.g. a shared submit button that doesn't own the action). |

**`use()` breaks the rules of hooks — deliberately.** It can be called conditionally, in a
loop, inside an `if`. It reads a Promise or a Context and integrates with Suspense.

```tsx
// The gotcha that costs people an afternoon: the promise MUST be created outside
// render (or cached). A promise created during render is a NEW promise every render,
// so the Suspense fallback never clears — an infinite loading spinner with no error.
const userPromise = fetchUser(id);          // outside render, or from a cache
function Profile() {
  const user = use(userPromise);            // suspends until resolved
  return <h1>{user.name}</h1>;
}
```

In a **Server Component prefer `async`/`await`** over `use()`: `await` resumes rendering from
where it paused, while `use()` re-renders the component after the resource resolves.

Two smaller 19 changes worth knowing: **`ref` is now an ordinary prop**, so `forwardRef` is no
longer needed for new components (it still works, and is documented as heading for deprecation
rather than removal); and **`useEffectEvent`** (19.2) gives you a stable callback that always
reads fresh props — the thing `useCallback` handles badly and the usual reason
`exhaustive-deps` gets disabled.

## Checklist

- [ ] Server data goes through TanStack Query (or equivalent) — never
      `useState` + `useEffect` + manual `loading` boolean
- [ ] Query keys are structured hierarchically for targeted invalidation
- [ ] `staleTime` set per-query based on how often that data actually changes
- [ ] Mutations that update the UI optimistically also implement rollback via
      `onError` + a stashed snapshot
- [ ] Server-state hooks are wrapped per-concern in `src/hooks/useX.ts` —
      components never see the raw query key
- [ ] Client state uses `useState` for local, Zustand/Jotai for shared global,
      Context only for rarely-changing values
- [ ] No Context value that changes on every keystroke or list mutation
- [ ] Shareable/bookmarkable UI state (filters, pagination, tabs) lives in
      the URL, not component state
- [ ] Forms use React Hook Form (uncontrolled) + Zod resolver, with the same
      schema reused for server-side validation
