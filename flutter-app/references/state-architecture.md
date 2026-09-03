# App Architecture: Layers, State Modeling, Rebuild Discipline

Everything here is about making one thing true: **a bug or a new requirement has
exactly one obvious place to change**, and the compiler tells you if you missed
a spot.

## Feature-first, not layer-first

| | Layer-first (`lib/blocs/`, `lib/screens/`, `lib/repositories/`) | Feature-first (`lib/features/<feature>/`) |
|---|---|---|
| Navigating the code | Jump across 3+ top-level dirs to see one feature | Everything for one feature is under one directory |
| Deleting a feature | Grep across the whole tree, hope you got every file | Delete one directory |
| Merge conflicts | Everyone touches the same few top-level dirs | Conflicts localized to the feature being changed |
| Scales to a big team | Poorly — shared dirs become contention points | Well — features are close to independently ownable |

**Recommendation: feature-first**, with layers nested *inside* each feature.
Layer-first looks organized at 5 screens and becomes an argument about which of
three near-identical `UserRepository` classes is the real one at 50.

```
lib/
  src/
    core/                    # cross-feature primitives: theming, env config, error types
    constants/
    features/
      auth/
        presentation/        # widgets + bloc
        domain/               # entities, use cases, repository INTERFACES
        data/                 # repository impls, DTOs, data sources
      cart/
        presentation/
        domain/
        data/
    observability/            # crash/perf reporting initialization
    storage/
    messaging/                 # push notification handling
    audio/
    pigeons/                  # Pigeon platform-channel definitions (see platform-integration.md)
  generated/                   # build_runner output — freezed, json_serializable, etc.
```

This is a real, observed production layout. Two things in it are worth calling
out explicitly because they're inconsistencies to actively guard against, not
things to imitate:

**Naming drift within the same layer.** One feature's presentation layer was
named `features/auth/screens/` while every other feature used
`features/<other>/presentation/` for the identical role. Same layer, two names,
no functional difference — just friction for anyone who has to remember which
feature uses which word, and a source of "which directory do I even open" time
loss that compounds across a team. Pick one name for the presentation layer
project-wide and lint/review for it; don't let a single feature's original
author's preference outlive them as an inconsistency everyone else has to know
about.

**Unfinished rewrites left resident.** `features/onboarding/` sat alongside
`features/onboarding_v2/` — a rewrite that was never finished, and never
removed once it stalled. This is dead-code risk in the specific sense that
matters most: a contributor fixing a bug can easily fix it in the wrong one, or
fix it in both inconsistently, and neither the compiler nor a quick glance tells
them which one is live. If a rewrite stalls, either finish the cutover and
delete the old feature in the same PR that flips the route, or explicitly mark
the abandoned one (a `// DEPRECATED — do not extend, see <ticket>` doc comment
at the top of the directory's main file, or delete it outright) rather than
letting both exist with no signal about which is authoritative.

## Dependency direction: presentation → domain ← data

```
presentation/   (widgets, bloc/state)
      │  depends on
      ▼
  domain/       (entities, use cases, repository INTERFACES)
      ▲  implements
      │
   data/        (repository impls, DTOs, remote/local data sources)
```

`domain/` depends on nothing else in the feature. It defines *interfaces*
(`abstract class UserRepository`), not implementations — `data/` provides the
implementation and is the only layer that knows about `dio`, `drift`,
`json_serializable`-generated DTOs, or any other concrete technology. This
inversion is what makes `domain/` (and therefore your business logic, and your
bloc tests) independent of network/database details: swapping REST for
GraphQL, or `dio` for a different HTTP client, is a `data/`-only change.

```dart
// domain/repositories/user_repository.dart — an interface, no implementation detail
abstract class UserRepository {
  Future<User> getUser(String id);
}

// domain/entities/user.dart — the domain's own type, no JSON annotations,
// no knowledge that it ever came from a network response
class User {
  const User({required this.id, required this.displayName});
  final String id;
  final String displayName;
}

// data/dtos/user_dto.dart — the wire format, freezed + json_serializable
@freezed
abstract class UserDto with _$UserDto {
  const factory UserDto({
    required String id,
    @JsonKey(name: 'display_name') required String displayName,
  }) = _UserDto;

  factory UserDto.fromJson(Map<String, dynamic> json) => _$UserDtoFromJson(json);
}

// data/repositories/user_repository_impl.dart — the only place that maps DTO → entity
class UserRepositoryImpl implements UserRepository {
  UserRepositoryImpl(this._api);
  final ApiClient _api;

  @override
  Future<User> getUser(String id) async {
    final dto = await _api.fetchUser(id);
    return User(id: dto.id, displayName: dto.displayName);   // the mapping boundary
  }
}
```

**Why you don't leak DTOs into the UI:** a DTO's shape is dictated by whatever
the backend returns *today*. A widget that reads `user.dto.display_name`
directly is now coupled to a wire format that can change for reasons that have
nothing to do with the UI (a backend refactor, an API version bump, a field
rename). The entity is your insulation layer — change the wire format, update
one mapping function in `data/`, and nothing in `presentation/` or `domain/`
even needs to know. Skipping the mapping step to "save a class" is the single
most common shortcut that turns into a wide, mechanical refactor later.

## Modeling state as an exhaustive sealed union

This is the pattern `sealed`/`final` (see `language-runtime.md`) exists to
support, applied to bloc state. Instead of one state class with nullable fields
and boolean flags (`isLoading`, `error`, `data` — all technically settable at
once, most combinations meaningless), model every *actual* state as its own
type:

```dart
@freezed
sealed class ProductListState with _$ProductListState {
  const factory ProductListState.initial() = ProductListInitial;
  const factory ProductListState.loading() = ProductListLoading;
  const factory ProductListState.loaded(List<Product> products) = ProductListLoaded;
  const factory ProductListState.error(String message) = ProductListError;
}
```

```dart
// In the widget layer — exhaustive `when()`. Every branch is REQUIRED.
BlocBuilder<ProductListBloc, ProductListState>(
  builder: (context, state) => switch (state) {
    // freezed generates a `when`/`map` API too; pattern-matching `switch` on the
    // sealed union works identically and needs no generated helper at all.
    ProductListInitial() => const SizedBox.shrink(),
    ProductListLoading() => const Center(child: CircularProgressIndicator()),
    ProductListLoaded(products: final products) => ProductGrid(products: products),
    ProductListError(message: final message) => ErrorView(message: message),
  },
);
```

**Now add a fifth state** — say, `ProductListEmpty` for "loaded successfully but
zero results," which is meaningfully different UI from both `Loading` and a
generic `Loaded` with an empty list check buried in the widget. The moment you
add that variant to the `sealed class`, **every `switch`/`when()` over
`ProductListState` in the codebase fails to compile** until you add a case for
it. That's not friction to route around — it's the feature. The compiler just
handed you the exact list of every place that needs to know about the new
state, instead of you finding out at runtime (or in QA, or in production) that
one call site silently fell through to a default and rendered the wrong thing.

### Why `maybeWhen`/`orElse` silently defeats this

`when()` demands every branch. `maybeWhen()` and `orElse` let you handle a
subset and fall through to a default for anything else — which is exactly the
escape hatch that makes adding a new state **not** break the build:

```dart
// WRONG — compiles fine after adding ProductListEmpty. Silently renders the
// generic empty-state fallback for it, which might be wrong, and you'd have
// no compiler signal telling you this call site needs attention.
state.maybeWhen(
  loaded: (products) => ProductGrid(products: products),
  orElse: () => const SizedBox.shrink(),
);

// RIGHT — exhaustive. Adding ProductListEmpty forces you to decide, here,
// explicitly, what this call site does with it.
state.when(
  initial: () => const SizedBox.shrink(),
  loading: () => const Center(child: CircularProgressIndicator()),
  loaded: (products) => ProductGrid(products: products),
  empty: () => const EmptyStateView(),
  error: (message) => ErrorView(message: message),
);
```

A production codebase with 4953 freezed references had 966 uses of `when(` and
only 12 uses of `maybeWhen(`/`orElse` combined — roughly an 80:1 ratio. That
ratio is the healthy shape: `maybeWhen` should be the rare, deliberate exception
(a shared widget that only cares about the terminal "loaded" state and
genuinely treats every other state identically), not a default habit reached
for because writing out every branch feels verbose. If you're reaching for
`maybeWhen` regularly, that's a sign the union's branches aren't cleanly
factored, not a sign `maybeWhen` is the right tool.

## `context.read` vs `context.watch` vs `context.select`

The single most common flutter_bloc/provider mistake is watching in the wrong
place — either watching where you should read (extra rebuilds) or reading where
you should watch (stale UI that never updates).

```dart
// WRONG — context.watch inside a callback. This subscribes the ENTIRE
// enclosing widget to CartBloc, rebuilding it every time the cart changes,
// even though the callback only needs the bloc reference once, at tap time.
ElevatedButton(
  onPressed: () => context.watch<CartBloc>().add(const CheckoutRequested()),
  child: const Text('Checkout'),
);

// RIGHT — context.read in the callback. No subscription; just grabs the
// current bloc instance to dispatch an event. The button widget doesn't need
// to rebuild when the cart changes — it's not rendering cart state.
ElevatedButton(
  onPressed: () => context.read<CartBloc>().add(const CheckoutRequested()),
  child: const Text('Checkout'),
);

// RIGHT — context.watch (or context.select for scoping) in build(), because
// this widget's OUTPUT actually depends on the current state.
Widget build(BuildContext context) {
  final itemCount = context.select((CartBloc bloc) => bloc.state.items.length);
  return Text('$itemCount items');
}
```

**The rule: `read` in callbacks and one-shot event handlers; `watch`/`select` in
`build()`.** A production codebase's widget-layer API usage: `context.read` 336
call sites, `context.watch` 13, `BlocSelector` 55, `BlocProvider` 140,
`BlocListener` 139, `BlocBuilder` 112, `BlocConsumer` 30, `MultiBlocProvider` 21,
`context.select` 7. The 336:13 read-to-watch ratio is the healthy shape — most
interaction with a bloc is dispatching events (read) from callbacks; comparatively
few widgets need to actually rebuild on every state change (watch), and even
fewer need to watch the *whole* bloc rather than a scoped slice (select). If your
ratio inverts — lots of `watch` relative to `read` — audit for widgets rebuilding
on state changes they don't render anything different for.

## `BlocListener` vs `BlocBuilder` vs `BlocSelector`

| Widget | Purpose | Rebuilds the widget it wraps? |
|---|---|---|
| `BlocBuilder` | Render UI from state | Yes, on every state change (unless `buildWhen`) |
| `BlocListener` | Side effects — navigation, snackbars, dialogs | No — it never rebuilds anything, it just reacts |
| `BlocSelector` | Render UI from a narrow **slice** of state | Yes, but only when the *selected* slice changes |
| `BlocConsumer` | `BlocBuilder` + `BlocListener` combined | Yes, for the builder half |

```dart
// WRONG — driving a navigation side effect from BlocBuilder. Works by
// accident (calling Navigator.push during build is a timing landmine) and
// re-triggers every time build() runs for unrelated reasons.
BlocBuilder<AuthBloc, AuthState>(
  builder: (context, state) {
    if (state is AuthAuthenticated) context.go('/home');   // WRONG PLACE
    return const LoginForm();
  },
);

// RIGHT — BlocListener for the side effect, BlocBuilder (or nothing, if the
// form doesn't need to render off AuthState at all) for rendering.
BlocListener<AuthBloc, AuthState>(
  listener: (context, state) {
    if (state is AuthAuthenticated) context.go('/home');
  },
  child: const LoginForm(),
);
```

`BlocSelector` scopes the rebuild to a projection of state, which matters when a
bloc's state is a large object but a given widget only cares about one field:

```dart
// Without BlocSelector: this widget rebuilds on EVERY CartState change,
// even changes to fields it doesn't render (e.g. a shipping-address update).
BlocBuilder<CartBloc, CartState>(
  builder: (context, state) => Text('${state.items.length} items'),
);

// With BlocSelector: rebuilds ONLY when items.length actually changes.
BlocSelector<CartBloc, CartState, int>(
  selector: (state) => state.items.length,
  builder: (context, count) => Text('$count items'),
);
```

## Checklist

- [ ] Feature-first layout; one name for the presentation layer used
      consistently across every feature (no `screens/` vs `presentation/` drift)
- [ ] No two versions of the same feature coexisting past the sprint the
      rewrite was meant to land in — finish the cutover or explicitly mark
      the abandoned copy
- [ ] `domain/` defines repository interfaces; `data/` is the only layer that
      imports networking/DB packages or knows about DTOs
- [ ] DTOs (`json_serializable`/freezed wire types) never referenced from
      `presentation/`; entities are the only type the UI sees
- [ ] Bloc/Cubit state modeled as a `sealed` freezed union, not one class with
      nullable fields and boolean flags
- [ ] `when()` used at nearly every call site; `maybeWhen`/`orElse` reserved for
      genuine "every other state is identical here" cases, not habit
- [ ] `context.read`/`ref.read` in callbacks and event handlers;
      `context.watch`/`ref.watch`/`context.select` only in `build()`
- [ ] Navigation and other side effects live in `BlocListener`
      (or `ref.listen`), never inside a builder
- [ ] `BlocSelector`/`context.select` used to scope rebuilds when a widget only
      needs a slice of a larger state object
