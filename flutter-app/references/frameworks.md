# State Management, Routing, and DI

The Flutter ecosystem has more state-management options than the problem
warrants. Most teams should pick one of two: **Bloc** or **Riverpod**. Everything
else is either a smaller/simpler subset of what those two do, or actively works
against the framework.

## Decision table

| Option | Version | Learning curve | Boilerplate | Testability | DI included? | Best fit |
|---|---|---|---|---|---|---|
| **flutter_bloc** | 9.1.1 | Medium (event→state mental model) | Medium–high (event, state, bloc classes per feature) | Excellent — `bloc_test`, pure functions of event+state | No (pair with `get_it`/`injectable`) | Teams that want explicit, auditable state transitions; large apps, many contributors |
| **Riverpod 3** | 3.4.2 | Medium (provider graph, `ref` API) | Low–medium (codegen shrinks it further) | Excellent — providers overridable in tests | **Yes** — providers ARE the DI graph | Teams that want one tool for both state and DI; apps with complex derived/async state |
| **provider** | 6.1.5+1 | Low | Low | Good | Partial (`Provider` for constants/services) | Small apps, or as scoped DI in an otherwise Bloc app |
| **signals** | — | Low–medium | Low | Good | No | Teams porting a fine-grained-reactivity mental model from React/Vue/Solid |
| **setState** | built-in | Lowest | None | Poor (coupled to widget lifecycle) | No | Purely local, single-widget UI state (a `TextField` focus flag, an expand/collapse toggle) |
| **GetX** | — | Low | Very low | Poor | Yes (own container) | **Avoid for new work** — see below |

### Why GetX is widely discouraged

GetX is popular in tutorials because it minimizes ceremony — a single package
does state, DI, routing, and snackbars/dialogs. That breadth is the problem:

- It **bypasses `InheritedWidget`/`BuildContext` entirely**, using a global
  service-locator-and-observable pattern instead. That opts out of Flutter's
  own dependency-scoping and testing tools (`ProviderScope` overrides,
  `BlocProvider` test harnesses have no GetX equivalent with comparable rigor).
- Its reactive primitives (`.obs`, `GetBuilder`, `Rx` types) don't integrate with
  the widget rebuild model the same way `InheritedWidget`-based solutions do,
  which has historically produced subtle rebuild and memory-leak bugs that are
  hard to reason about from the framework's own mental model.
- The maintenance and design-review bar is visibly lower than Bloc's or
  Riverpod's — API stability and null-safety soundness have both regressed
  across versions in ways that break existing apps on upgrade.

None of this means a GetX app is doomed. It means: don't start a new one on it,
and if you inherit one, plan a migration path rather than deepening the
investment.

## Bloc — event-driven, explicit state machine

Bloc models a feature as: **events** go in, a **bloc** maps events to **states**,
the UI renders states and dispatches events. `Cubit` is the same idea minus the
event layer — you call methods directly instead of dispatching events.

| | `Bloc` | `Cubit` |
|---|---|---|
| Input | Named `Event` classes | Direct method calls |
| Traceability | Every state change has a named, loggable cause | Method call stack only |
| Boilerplate | More (event classes + handlers) | Less |
| Good for | Complex features, multiple triggers per state change, replay/audit | Simple features, quick derived state |

**A real, deliberate convention worth adopting: always `Bloc`, never `Cubit`.**
Production codebases following this convention have zero `Cubit` subclasses
across dozens of features. The trade-off is explicit: you write more event
classes than a `Cubit`-based codebase would, in exchange for **every state
transition being named, logged, and traceable** through `BlocObserver` — when a
bug report says "the cart total was wrong," you can grep for the event that
caused it instead of trying to reconstruct which method call did it. For a team
above a handful of contributors, that traceability consistently pays for the
extra event classes. Pick one convention project-wide; a mix of `Bloc` and
`Cubit` means two mental models for "how does state change here."

```dart
// Event
sealed class CounterEvent {}
final class CounterIncremented extends CounterEvent {}
final class CounterDecremented extends CounterEvent {}

// State
sealed class CounterState {}
final class CounterValue extends CounterState {
  const CounterValue(this.value);
  final int value;
}

// Bloc
class CounterBloc extends Bloc<CounterEvent, CounterState> {
  CounterBloc() : super(const CounterValue(0)) {
    on<CounterIncremented>((event, emit) => emit(CounterValue(state is CounterValue
        ? (state as CounterValue).value + 1
        : 0)));
    on<CounterDecremented>(
      (event, emit) => emit(CounterValue((state as CounterValue).value - 1)),
      transformer: droppable(),   // ignore rapid repeat taps while one is in flight
    );
  }
}
```

### Event transformers

`on<Event>()` accepts a `transformer` (from `bloc_concurrency`) that controls how
concurrent events of the same type are handled — this is where you put debounce,
throttle, and "ignore while busy" semantics instead of hand-rolling them with
flags:

```dart
on<SearchQueryChanged>(
  _onSearchQueryChanged,
  transformer: (events, mapper) => events
      .debounceTime(const Duration(milliseconds: 300))   // wait for typing to pause
      .switchMap(mapper),                                 // cancel any in-flight search
);
```

| Transformer | Behavior | Use for |
|---|---|---|
| `sequential()` (default) | Process events one at a time, in order | Most cases — safe default |
| `droppable()` | Ignore new events while one is being processed | Submit buttons, "already loading" guards |
| `restartable()` | Cancel the in-progress handler, start the new one | Search-as-you-type, latest-wins refresh |
| `concurrent()` | Process events in parallel, no ordering guarantee | Independent, non-conflicting side effects only |

### `BlocObserver` for logging

```dart
class AppBlocObserver extends BlocObserver {
  @override
  void onTransition(Bloc bloc, Transition transition) {
    super.onTransition(bloc, transition);
    log.debug('${bloc.runtimeType} ${transition.event} → ${transition.nextState}');
  }

  @override
  void onError(BlocBase bloc, Object error, StackTrace stackTrace) {
    crashReporter.recordError(error, stackTrace, context: bloc.runtimeType.toString());
    super.onError(bloc, error, stackTrace);
  }
}

void main() {
  Bloc.observer = AppBlocObserver();   // one line, global visibility into every transition
  runApp(const MyApp());
}
```

This single hook is what makes the "always `Bloc`" convention pay off in
practice — every state transition in the entire app funnels through one place
you can log, sample, or ship to your crash/analytics pipeline.

## Riverpod 3 — providers as state AND dependency graph

Riverpod's core idea: a `Provider` is a node in a dependency graph. Providers can
depend on other providers, are lazily initialized, auto-dispose by default when
unwatched, and are trivially overridable in tests — which is also why Riverpod
**replaces both `provider` and a separate DI container** (`get_it`/`injectable`)
in one tool.

```dart
// Codegen (riverpod_generator) — the recommended style in 3.x. Less boilerplate,
// better type inference, and `ref` is injected for you.
@riverpod
Future<Weather> weather(Ref ref, String city) async {
  final client = ref.watch(httpClientProvider);   // depends on another provider
  return client.fetchWeather(city);
}

// Manual (no codegen) — same semantics, more ceremony, no build_runner step.
final weatherProvider = FutureProvider.family<Weather, String>((ref, city) async {
  final client = ref.watch(httpClientProvider);
  return client.fetchWeather(city);
});
```

| Style | Pros | Cons |
|---|---|---|
| Code-gen (`@riverpod`) | Less boilerplate, strong inference, consistent conventions | Requires `build_runner`, generated file noise in diffs |
| Manual | No build step, works in contexts codegen is awkward in | More verbose, easier to write inconsistent provider shapes across a team |

### `ref.watch` vs `ref.read` vs `ref.listen`

```dart
class WeatherView extends ConsumerWidget {
  const WeatherView({required this.city, super.key});
  final String city;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // watch: subscribe. Rebuilds this widget whenever `weatherProvider` changes.
    final weather = ref.watch(weatherProvider(city));

    // listen (inside build, for one-shot side effects, not for driving rebuilds):
    ref.listen(weatherProvider(city), (previous, next) {
      if (next.hasError) showErrorSnackbar(context, next.error!);
    });

    return switch (weather) {
      AsyncData(:final value) => Text(value.summary),
      AsyncError(:final error) => Text('Error: $error'),
      AsyncLoading() => const CircularProgressIndicator(),
    };
  }
}

void onRefreshPressed(WidgetRef ref) {
  // read: fetch current value once, do NOT subscribe. Correct in callbacks —
  // a callback re-running because a provider it read from changed would be
  // the same read-vs-watch bug flutter_bloc's context.read/watch rule guards
  // against (see state-architecture.md).
  ref.read(weatherProvider('London').notifier).refresh();
}
```

`AsyncValue<T>` (the return type wrapping any `Future`/`Stream`-based provider)
is Riverpod's answer to the same problem freezed unions solve for Bloc state:
it forces the UI to handle loading/data/error explicitly via pattern matching
(shown above) rather than juggling separate nullable/boolean flags.

### Auto-dispose

Providers auto-dispose by default when no widget is watching them — a provider
backing a detail screen releases its state (and cancels any pending work) the
moment the screen is popped, without you writing a `dispose()` override. Opt out
with `.autoDispose` removed / `keepAlive()` only for genuinely app-lifetime state
(auth session, feature flags) — defaulting everything to `keepAlive` reintroduces
the exact memory-leak problem auto-dispose exists to prevent.

## Bloc vs Riverpod — when to pick which

Both are excellent. Neither is "better" in the abstract:

- **Bloc** wins when you want an explicit, replayable event log per feature and
  you're fine writing more classes for it — larger teams, complex business
  workflows, regulated domains where "what caused this state" needs to be
  answerable.
- **Riverpod** wins when your state is heavily **derived** (computed from other
  state, async-dependent, needs fine-grained recomputation) and you don't want a
  second tool just for DI.

Don't run both in the same app as competing state layers — pick one as the
primary state-management tool. (Using `provider`/`get_it` purely for narrow,
Bloc-external DI concerns alongside Bloc is fine; running Riverpod providers
*and* Bloc for overlapping feature state in the same app is not.)

## Routing: go_router vs auto_route vs Navigator 1.0

| | Navigator 1.0 (`push`/`pop`) | go_router 17 | auto_route |
|---|---|---|---|
| Style | Imperative | Declarative, URL-based | Declarative, codegen |
| Deep links | Manual wiring | Built-in | Built-in |
| Type safety | None (raw route names/args) | Optional, via `TypedGoRoute`/codegen | Codegen by default |
| Nested/persistent nav (tabs) | Manual `Navigator` nesting | `ShellRoute` | `AutoTabsRouter` |
| Auth guards | Manual, ad hoc | `redirect` callback | `redirect`/guards |
| Learning curve | Lowest | Low–medium | Medium |

**go_router** is the framework team's recommended declarative router and the
default choice for new apps. It maps routes to URLs (meaningful even for
mobile-only apps — it's what makes deep links and web routing work identically),
and centralizes navigation logic instead of scattering `Navigator.push` calls
through the widget tree.

```dart
final router = GoRouter(
  redirect: (context, state) {
    final loggedIn = authRepository.isLoggedIn;
    final loggingIn = state.matchedLocation == '/login';
    if (!loggedIn && !loggingIn) return '/login';   // auth guard
    if (loggedIn && loggingIn) return '/home';
    return null;   // no redirect
  },
  routes: [
    GoRoute(path: '/login', builder: (context, state) => const LoginPage()),
    ShellRoute(
      // ShellRoute wraps its children in a persistent widget — a BottomNavigationBar
      // that must NOT rebuild/reset when switching tabs, e.g. — while the inner
      // route still changes.
      builder: (context, state, child) => ScaffoldWithNavBar(child: child),
      routes: [
        GoRoute(path: '/home', builder: (context, state) => const HomePage()),
        GoRoute(
          path: '/product/:id',
          builder: (context, state) => ProductPage(id: state.pathParameters['id']!),
        ),
      ],
    ),
  ],
);

// Typed routes (via go_router_builder codegen) trade the stringly-typed
// state.pathParameters['id'] above for a generated, type-checked constructor:
// ProductRoute(id: '42').go(context);
```

`auto_route` offers a similar feature set with heavier codegen and its own
router abstraction; it's a legitimate choice but a second, less-adopted
convention to teach new contributors versus go_router's wider ecosystem
adoption. Navigator 1.0 alone is fine for a genuinely tiny app with two or three
screens and no deep-link requirement — anything larger accrues stringly-typed
route names and duplicated guard logic fast.

## Dependency injection: get_it + injectable vs Riverpod-as-DI

If you're on Bloc (no built-in DI), pair it with **get_it** (a service locator)
and optionally **injectable** (codegen that registers your `get_it` bindings
from annotations, removing hand-written registration boilerplate):

```dart
final getIt = GetIt.instance;

@injectable
class UserRepository {
  UserRepository(this._client);
  final ApiClient _client;
}

// Generated by injectable, called once at startup:
void configureDependencies() => getIt.init();

// Usage — resolved anywhere, not tied to BuildContext:
final repo = getIt<UserRepository>();
```

If you're on Riverpod, don't add `get_it` alongside it — providers already are
the dependency graph (a repository is just a provider other providers `ref.watch`),
and running two DI mechanisms side by side means two places to look for "where
does this get constructed." The choice of state-management tool effectively
decides your DI story too.

## Checklist

- [ ] One primary state-management tool per app — Bloc or Riverpod, not both
      as competing state layers
- [ ] If Bloc: convention decided and enforced — always `Bloc` or always `Cubit`,
      not a mix; `BlocObserver` wired for global transition logging
- [ ] If Riverpod: providers auto-dispose by default; `keepAlive()` reserved for
      genuinely app-lifetime state
- [ ] No GetX in new code; existing GetX usage has a migration plan, not
      deepening investment
- [ ] Routing centralized in go_router (or auto_route), not scattered
      `Navigator.push` calls with stringly-typed route names
- [ ] Auth/onboarding gating implemented via router `redirect`, not per-screen
      `if (!loggedIn) return LoginPage()` checks
- [ ] Persistent nav chrome (tab bars) wrapped in `ShellRoute`/equivalent so it
      doesn't rebuild on every inner-route change
- [ ] DI story matches state-management choice: `get_it`/`injectable` for Bloc
      apps, providers-as-DI for Riverpod apps — not both
