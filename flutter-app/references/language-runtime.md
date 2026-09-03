# Flutter/Dart Runtime and Language Essentials

Flutter and Dart ship on a fixed cadence. Knowing where you are in that cadence —
and pinning it deliberately — is the difference between a reproducible build and
"works on my machine."

## Channels and cadence

| Channel | Purpose | Stability | Use it for |
|---|---|---|---|
| `stable` | Production | Fully tested, 4 releases/year | **All app and CI builds** |
| `beta` | Preview | Mostly stable, monthly-ish (~12/year) | Early access to next stable; never ship on it |
| `master` | HEAD | Breaks daily | Contributing to the framework itself; never for app work |

Flutter cuts a new **stable** roughly every quarter and a new **beta** roughly
monthly. As of this cadence, stable is **3.44** (Dart **3.12.1**), announced at
Google I/O. Track stable. Riding beta in a production app buys you nothing but
surprise breakage — the framework team's own bar for beta is "safe enough for
early adopters to file bugs against," not "safe enough to ship to end users."

```bash
flutter channel stable
flutter upgrade          # updates the Flutter SDK on the current channel
flutter --version        # confirm Dart + Flutter versions actually in use
```

### Pinning per project

`flutter upgrade` mutates a machine-global SDK install. That's fine for a single
developer on a single project; it's a footgun the moment you have two projects on
two Flutter versions, or a CI runner that needs bit-for-bit reproducibility.

**FVM (Flutter Version Management)** pins a Flutter SDK version per project,
the same way `nvm`/`asdf` pin a Node/Ruby version:

```bash
dart pub global activate fvm
fvm install 3.44.7
fvm use 3.44.7            # writes .fvmrc / .fvm/fvm_config.json
fvm flutter run           # uses the pinned SDK, not whatever `flutter` resolves to
```

Commit `.fvmrc` (or `.fvm/fvm_config.json`) so every developer and every CI runner
resolves the identical SDK. Do not commit `.fvm/flutter_sdk` (the actual SDK
checkout) — that belongs in `.gitignore`.

```yaml
# pubspec.yaml — pin the Dart SDK constraint, not just the Flutter version.
# This is what pub actually resolves against.
environment:
  sdk: ^3.9.2          # apps: pin to what CI/production actually runs
  flutter: ">=3.44.0"
```

A published **package** (as opposed to an app) should use a wider, more
conservative constraint — `^3.10.3` rather than pinning to the exact version you
happen to develop against — because you don't control what SDK your consumers run.
Apps can and should be narrower; you control the whole toolchain.

## Dart 3 essentials for app code

### Sound null safety

Every type is non-nullable unless suffixed with `?`. This isn't a style
preference — the analyzer statically rejects any code path that can dereference
`null` without a check. If you're still seeing `!`-laden code from a
pre-null-safety migration, that's technical debt, not idiomatic Dart.

```dart
// WRONG — using ! to silence the analyzer instead of proving non-null
String greet(User? user) => 'Hello ${user!.name}';

// RIGHT — narrow with a real check; the analyzer promotes the type after it
String greet(User? user) {
  if (user == null) return 'Hello guest';
  return 'Hello ${user.name}';   // user is promoted to `User` here, no `!` needed
}
```

### `sealed`, `final`, `base` — exhaustive modeling

This is the language feature the entire freezed-union state-modeling pattern
(see `state-architecture.md`) is built on top of. `sealed` restricts a class
hierarchy to the current library — every subtype is known at compile time — which
lets `switch` be **exhaustive**: the analyzer errors if you don't handle every case.

```dart
sealed class AuthState {}
final class AuthInitial extends AuthState {}
final class AuthAuthenticated extends AuthState {
  AuthAuthenticated(this.userId);
  final String userId;
}
final class AuthUnauthenticated extends AuthState {}

String label(AuthState state) => switch (state) {
  AuthInitial() => 'Loading…',
  AuthAuthenticated(userId: final id) => 'Signed in as $id',
  AuthUnauthenticated() => 'Signed out',
  // Add a new subtype of AuthState and this switch fails to compile until
  // you add a case for it. That's the entire point: the compiler, not a
  // runtime null-check or a forgotten `if`, catches the missed case.
};
```

| Modifier | Meaning |
|---|---|
| `sealed` | Subtypes restricted to this library; enables exhaustive `switch` outside the library |
| `final` (on a class) | No subtyping *and* no implementing at all, even within the library |
| `base` | Must be extended/implemented via `extends`/`implements` with the same modifier chain, not freely mixed in — preserves invariants down the hierarchy |
| `interface` | Can be implemented but not extended — forces implementers to satisfy the full contract, not inherit behavior |

Use `sealed` on the parent of a closed state/result hierarchy. Use `final` on
leaf classes you never intend anyone to extend (which, for state classes, is
always — a subtype of a state variant defeats exhaustiveness).

### Records and pattern matching

Records are anonymous, immutable, structurally-typed tuples — useful for
returning multiple values without declaring a class just to shuttle them out of
a function.

```dart
(double, double) minMax(List<double> values) {
  var lo = values.first, hi = values.first;
  for (final v in values) {
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  return (lo, hi);   // positional record
}

final (min: low, max: high) = (min: 1.0, max: 9.0);  // named-field record + destructuring

// Pattern matching over records and collections in one expression:
String describe(Object o) => switch (o) {
  (int x, int y) when x == y => 'equal pair',
  (int x, int y) => 'pair $x,$y',
  [int a, int b, ...] => 'list starting $a,$b',
  {'error': final msg} => 'error: $msg',
  _ => 'unknown',
};
```

Don't reach for records where a proper class (or a freezed union) belongs — a
record has no named type, no methods, and no room to grow invariants. Records are
for **local, short-lived, structural** data; domain entities and bloc states still
want real classes.

### `late`

`late` defers initialization and defers *null-safety checking* to first access —
useful for fields initialized in `initState()` (which the constructor can't see)
or expensive values you want computed lazily. It is not a general-purpose
escape hatch from proving non-nullability; every genuine escape from `late`
turns into a `LateInitializationError` at runtime instead of a compile error.

```dart
class _PageState extends State<Page> {
  late final AnimationController _controller;   // set in initState, used everywhere after

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(vsync: this);
  }
}
```

### Extension types (Dart 3)

Zero-cost wrapper types — compiled away entirely, no runtime allocation — used to
give a raw type (often `int`, `String`, or a platform type) a distinct static
identity so you can't accidentally pass a `UserId` where an `OrderId` is expected,
even though both are `String` under the hood.

```dart
extension type UserId(String value) {
  bool get isValid => value.length == 36;   // UUID length check, e.g.
}

extension type OrderId(String value) {}

void fetchUser(UserId id) { /* ... */ }

fetchUser(UserId('abc-123'));      // fine
// fetchUser(OrderId('xyz-999'));  // compile error — different static type, same runtime repr
```

Prefer extension types over `typedef` when you want the compiler to reject
cross-wiring, and over a full wrapper class when you don't need extra fields or
runtime identity — the wrapper genuinely disappears at compile time.

## Dart 3.12 additions

- **Private named parameters.** A named parameter can be backed by a
  private-named field directly, removing boilerplate constructors that existed
  solely to assign a public parameter to a private field.
- **Primary constructors — EXPERIMENTAL.** Class-level constructor parameter
  lists (similar in spirit to Kotlin's primary constructors), still gated behind
  an experiment flag. Don't build on this in production code yet; the syntax and
  semantics can still change before stabilization.

## Async model: isolates, `Future`, `Stream`

Dart is **single-threaded per isolate**. There is no shared-memory concurrency
within an isolate — `async`/`await` gives you concurrency (interleaving), not
parallelism (simultaneous execution). The UI isolate runs your widget tree, your
bloc/provider logic, and the Flutter engine's event loop, all on one thread. Any
CPU-bound work you run there blocks frame production.

```dart
// Future: a single async value.
Future<User> fetchUser(String id) async {
  final response = await httpClient.get(Uri.parse('/users/$id'));
  return User.fromJson(jsonDecode(response.body));
}

// Stream: zero or more async values over time.
Stream<int> countdown(int from) async* {
  for (var i = from; i >= 0; i--) {
    await Future.delayed(const Duration(seconds: 1));
    yield i;
  }
}

// unawaited: explicitly mark a Future you intentionally don't wait on —
// silences the "unawaited_futures" lint AND documents intent for the next reader.
void logAnalyticsEvent(String name) {
  unawaited(analytics.logEvent(name));   // fire-and-forget by design, not an oversight
}
```

### The frame budget — why isolates matter

Flutter must produce a frame within the display's refresh window or the user
sees a stutter ("jank"):

| Refresh rate | Frame budget |
|---|---|
| 60 Hz | 16.7 ms |
| 90 Hz | 11.1 ms |
| 120 Hz | 8.3 ms |

That budget covers build, layout, paint, *and* whatever your Dart callbacks do
on the UI isolate that frame. JSON-decoding a 5 MB payload, running an image
filter, or doing any nontrivial computation inline in a widget callback eats
directly into it — there is no separate "logic thread" to absorb it, unlike a
typical native app with worker threads sharing a heap.

**Move CPU-bound work off the UI isolate:**

```dart
// WRONG — decoding a large JSON payload on the UI isolate blocks every frame
// for as long as decode takes, well past 16.7ms for anything nontrivial.
Future<List<Product>> parseCatalog(String rawJson) async {
  final list = jsonDecode(rawJson) as List;
  return list.map(Product.fromJson).toList();
}

// RIGHT — compute() spins up (or reuses) a worker isolate, runs the top-level
// function there, and marshals the result back. Requires the function and its
// argument to be sendable across the isolate boundary (no closures over UI state).
Future<List<Product>> parseCatalog(String rawJson) {
  return compute(_parseCatalogWorker, rawJson);
}

List<Product> _parseCatalogWorker(String rawJson) {
  final list = jsonDecode(rawJson) as List;
  return list.map(Product.fromJson).toList();
}

// RIGHT (Dart 2.19+/Flutter's Isolate.run) — same idea, slightly lower ceremony,
// no separate top-level function required if you don't need compute()'s pooling.
Future<List<Product>> parseCatalogAlt(String rawJson) {
  return Isolate.run(() {
    final list = jsonDecode(rawJson) as List;
    return list.map(Product.fromJson).toList();
  });
}
```

`compute()` and `Isolate.run()` both spawn a real OS-level isolate with its own
memory and event loop — message-passing in, message-passing out. There's fixed
overhead (isolate spin-up, serialization of the argument and result), so don't
reach for it on work that's already sub-millisecond; reach for it when the work
would otherwise visibly janks frames — JSON parsing of large payloads, image
processing, cryptography, and heavy list sorting/filtering are the classic cases.

## Error handling: catching what `try`/`catch` can't

`try`/`catch` only catches errors on the call stack it's part of. Errors thrown
asynchronously (in a callback, in a different microtask, during a frame
render) need dedicated top-level handlers, or they're silently swallowed by the
framework's default error reporting (or crash the process, depending on where
they originate).

```dart
void main() {
  // Framework-level errors: widget build/layout/paint errors, gesture errors.
  FlutterError.onError = (details) {
    FlutterError.presentError(details);   // keep default red-screen in debug
    crashReporter.recordFlutterError(details);
  };

  // Errors that escape the Flutter framework entirely: e.g. isolate-level errors
  // in the platform dispatcher (rendering pipeline, `PlatformDispatcher.onError`
  // callbacks) not funneled through FlutterError.
  PlatformDispatcher.instance.onError = (error, stack) {
    crashReporter.recordError(error, stack);
    return true;   // true = handled, don't also crash the app
  };

  // Everything else — uncaught async errors anywhere in the zone, including
  // ones that never touch FlutterError or PlatformDispatcher at all.
  runZonedGuarded(
    () => runApp(const MyApp()),
    (error, stack) => crashReporter.recordError(error, stack),
  );
}
```

All three exist because they cover different layers: `FlutterError.onError` is
framework/widget-tree errors, `PlatformDispatcher.instance.onError` is the
platform/engine boundary, and `runZonedGuarded` is the zone-level catch-all for
anything an `await` chain lost track of. Wire all three; wiring only one leaves
a real gap in crash visibility.

## Rendering model: why rebuilds cost what they cost

Flutter maintains three parallel trees:

| Tree | What it holds | Lifetime |
|---|---|---|
| **Widget** | Immutable configuration you wrote (`Text('hi')`) | Rebuilt constantly, cheap to allocate |
| **Element** | Mutable, holds the widget's position in the tree and links to render objects | Persists across rebuilds when possible |
| **RenderObject** | Actual layout/paint logic, box constraints, geometry | Persists; only touched when layout/paint actually changes |

`build()` returning a new widget tree does **not** mean everything gets
relaid-out and repainted. Flutter diffs the new widget against the element it's
attached to: if the widget's runtime type and key match, the framework reuses
the element and render object, and just updates their configuration. Widgets are
deliberately cheap to allocate — the expensive part of a rebuild is layout and
paint, which the framework tries hard to skip when it can prove nothing visible
changed.

### `const` constructors

A `const` widget is a compile-time constant: the same instance is reused across
rebuilds rather than reallocated, and Flutter's `==`-based canonicalization lets
it skip that subtree's rebuild entirely when the parent rebuilds but the `const`
child's inputs haven't changed.

```dart
// WRONG — allocated fresh every build, defeats the framework's ability to
// short-circuit unchanged subtrees even though the content never varies.
Widget build(BuildContext context) {
  return Padding(padding: EdgeInsets.all(16), child: Text('Static label'));
}

// RIGHT — const all the way down. The analyzer (`prefer_const_constructors`,
// `prefer_const_literals_to_create_immutables`) will flag missed opportunities.
Widget build(BuildContext context) {
  return const Padding(padding: EdgeInsets.all(16), child: Text('Static label'));
}
```

This matters more as trees get deeper — a `const` subtree near the root of a
frequently-rebuilding parent (a list item, a card in a feed) is the difference
between "rebuild the whole card" and "rebuild nothing," multiplied by however
many times that parent rebuilds per second.

## Checklist

- [ ] Project pinned to a specific Flutter/Dart SDK via FVM (or equivalent),
      `.fvmrc` committed, `.fvm/flutter_sdk` gitignored
- [ ] `pubspec.yaml` SDK constraint matches what CI actually runs; apps pin
      narrower than published packages
- [ ] Building/testing on `stable` only; `beta`/`master` never in CI or release
- [ ] State hierarchies modeled with `sealed`/`final` for exhaustive `switch`,
      not `enum` + a grab-bag of nullable fields
- [ ] `late` used only for genuinely deferred-but-guaranteed initialization,
      not as an escape from proving non-nullability
- [ ] CPU-bound work (large JSON parse, image processing, heavy sort/filter)
      routed through `compute()`/`Isolate.run()`, not inline in a widget callback
- [ ] All three error surfaces wired: `FlutterError.onError`,
      `PlatformDispatcher.instance.onError`, `runZonedGuarded`
- [ ] Hot, frequently-rebuilt widget subtrees marked `const` wherever their
      inputs are genuinely constant
