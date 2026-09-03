# Testing: Pyramid, bloc_test, mocktail, Widgets, Goldens

Flutter's test pyramid isn't different in shape from any other pyramid — many
fast unit tests, fewer widget tests, fewer still integration tests, a handful
of goldens — but each layer has a Flutter-specific failure mode that a
generic-testing background won't warn you about. This file is those failure
modes.

## The pyramid

| Layer | Runs | Speed | What it verifies |
|---|---|---|---|
| Unit | Pure Dart, no Flutter bindings | Milliseconds | Business logic, blocs, mappers, use cases — most of your tests live here |
| Widget | `testWidgets`, Flutter test bindings, no real device | Fast, seconds | A widget renders correctly and responds to interaction, in isolation |
| Integration | `integration_test`, a real device/simulator | Slow, minutes | End-to-end user flows through the real app, real platform channels |
| Golden | `testWidgets` + pixel comparison | Fast to run, slow to maintain | Pixel-exact visual regression |

Weight your suite toward the top of this table, not the bottom. A bloc's
business logic tested as a unit test runs in milliseconds and needs no widget
tree; testing the same logic only through a full widget or integration test
makes it slow to run and slow to diagnose when it fails.

## `bloc_test`: `build`/`act`/`expect`/`verify`

```dart
// counter_bloc_test.dart
import 'package:bloc_test/bloc_test.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';

class MockCounterRepository extends Mock implements CounterRepository {}

void main() {
  late MockCounterRepository repository;

  setUp(() {
    repository = MockCounterRepository();
  });

  group('CounterBloc', () {
    blocTest<CounterBloc, CounterState>(
      'emits [loading, loaded] when CounterFetched succeeds',
      build: () {
        when(() => repository.fetchCount()).thenAnswer((_) async => 5);
        return CounterBloc(repository);
      },
      act: (bloc) => bloc.add(const CounterFetched()),
      expect: () => [
        const CounterState.loading(),
        const CounterState.loaded(5),
      ],
      verify: (_) {
        verify(() => repository.fetchCount()).called(1);   // no double-fetch
      },
    );

    blocTest<CounterBloc, CounterState>(
      'emits [loading, error] when CounterFetched throws',
      build: () {
        when(() => repository.fetchCount()).thenThrow(Exception('network'));
        return CounterBloc(repository);
      },
      act: (bloc) => bloc.add(const CounterFetched()),
      expect: () => [
        const CounterState.loading(),
        isA<CounterState>().having((s) => s.error, 'error', isNotNull),
      ],
    );

    // seed: start the bloc already in a mid-flow state, instead of its
    // initial state — for testing "increment while already loaded" without
    // re-driving the fetch that got it there.
    blocTest<CounterBloc, CounterState>(
      'emits incremented count when already loaded',
      build: () => CounterBloc(repository),
      seed: () => const CounterState.loaded(5),
      act: (bloc) => bloc.add(const CounterIncremented()),
      expect: () => [const CounterState.loaded(6)],
    );
  });
}
```

`build` constructs the bloc (with mocks already stubbed); `act` drives events
into it; `expect` asserts the exact sequence of states emitted, in order —
this is stricter than "did it eventually reach state X," and that strictness
is what catches an extra spurious `loading` re-emit or a state emitted in the
wrong order; `verify` checks side effects (repository calls, analytics, logs)
after the state sequence has been asserted. `seed` skips past setup you don't
want to re-test in this particular case — use it for "given this state, then
X" tests rather than replaying the events that produced that state every time.

## mocktail over mockito

`mockito`'s idiomatic path is `build_runner` codegen (`@GenerateMocks`), a
build step that has to rerun on every interface change and is a common source
of "did you forget to run codegen" CI failures. `mocktail` needs none of
that — it's pure Dart, works with null safety out of the box because it was
designed for it rather than retrofitted, and a mock is just `class MockFoo
extends Mock implements Foo {}`.

```dart
class MockAuthApi extends Mock implements AuthApi {}

// registerFallbackValue is required whenever any() is used for a type mocktail
// hasn't seen before — mocktail needs a real instance to hand back internally
// for argument matching machinery, and it has no way to construct an arbitrary
// custom type on its own. Built-in types (String, int, ...) are pre-registered;
// your own classes are not.
class FakeLoginRequest extends Fake implements LoginRequest {}

void main() {
  setUpAll(() {
    registerFallbackValue(FakeLoginRequest());
  });

  test('login calls api with the given request', () async {
    final api = MockAuthApi();
    when(() => api.login(any())).thenAnswer((_) async => const AuthToken('t'));

    await api.login(const LoginRequest(username: 'a', password: 'b'));

    verify(() => api.login(any(that: isA<LoginRequest>()))).called(1);
  });
}
```

```
WRONG — using any() for a custom type without registering a fallback.
when(() => api.login(any())).thenAnswer(...);
// throws: "Bad state: type 'LoginRequest' has not been registered"
// at the moment mocktail needs to match an argument of that type.

RIGHT — register a Fake for every custom type you'll pass to any() or
captureAny(), once, in setUpAll.
registerFallbackValue(FakeLoginRequest());
```

Extend `Fake`, not `Mock`, for the fallback instance — `Fake` throws
`UnimplementedError` on any real method call, which is correct because this
instance only ever exists to satisfy the type-matching machinery; it is never
actually invoked.

## Widget testing: finders, `pump` vs `pumpAndSettle`

```dart
testWidgets('tapping the increment button updates the count', (tester) async {
  await tester.pumpWidget(const MaterialApp(home: CounterPage()));

  expect(find.text('0'), findsOneWidget);
  await tester.tap(find.byKey(const Key('increment_button')));
  await tester.pump();   // one frame — enough for a synchronous state update

  expect(find.text('1'), findsOneWidget);
});
```

`find.byType(Widget)` for structural queries, `find.byKey(Key(...))` for
anything you need to target unambiguously regardless of its text or type
(preferred for interactive elements — text changes, keys shouldn't), and
`find.text('...')` for asserting rendered content.

`pump()` advances exactly one frame — use it when you know how many frames
the change under test needs (usually one, for a synchronous `setState`/bloc
emission). `pumpAndSettle()` keeps pumping frames until no more are scheduled,
which is convenient for "wait for this animation/transition to finish" — and
**hangs the test forever** the moment anything on screen animates
continuously with no natural end: a loading spinner (`CircularProgressIndicator`
with no explicit stop), a shimmer effect, any `AnimationController` set to
`repeat()`. There is no frame where "no more frames are scheduled" becomes
true, so `pumpAndSettle` never returns and the test times out.

```dart
// WRONG — the page shows a CircularProgressIndicator while loading; that
// spinner's implicit animation never settles, so pumpAndSettle() hangs until
// the test framework's timeout, and the failure message gives no hint why.
await tester.pumpWidget(const MaterialApp(home: LoadingPage()));
await tester.pumpAndSettle();   // hangs — the spinner keeps scheduling frames

// RIGHT — pump a specific duration instead, enough for the state you're
// actually asserting to have landed, without waiting for the animation to end.
await tester.pumpWidget(const MaterialApp(home: LoadingPage()));
await tester.pump(const Duration(milliseconds: 100));
expect(find.byType(CircularProgressIndicator), findsOneWidget);
```

## Testing a `BlocProvider`-wrapped widget

```dart
testWidgets('shows loaded count from CounterBloc', (tester) async {
  final bloc = MockCounterBloc();
  whenListen(
    bloc,
    Stream.fromIterable([const CounterState.loaded(5)]),
    initialState: const CounterState.loading(),
  );

  await tester.pumpWidget(
    MaterialApp(
      home: BlocProvider<CounterBloc>.value(
        value: bloc,
        child: const CounterPage(),
      ),
    ),
  );
  await tester.pump();   // let the emitted state's rebuild land

  expect(find.text('5'), findsOneWidget);
});
```

`whenListen` (from `bloc_test`) is the mocktail-compatible way to make a mock
bloc emit a scripted state stream — a plain `when(() => bloc.state)` stub only
covers the synchronous getter, not the `Stream<State>` the `BlocBuilder`
actually subscribes to, so without it the widget under test never rebuilds.

## Testing go_router navigation

```dart
testWidgets('tapping a product navigates to its detail route', (tester) async {
  final router = GoRouter(routes: [
    GoRoute(path: '/', builder: (_, __) => const ProductListPage()),
    GoRoute(
      path: '/product/:id',
      builder: (_, state) => ProductDetailPage(id: state.pathParameters['id']!),
    ),
  ]);

  await tester.pumpWidget(MaterialApp.router(routerConfig: router));
  await tester.tap(find.byKey(const Key('product_42')));
  await tester.pumpAndSettle();   // page-transition animation has a defined end — safe here

  expect(find.byType(ProductDetailPage), findsOneWidget);
  expect(router.routerDelegate.currentConfiguration.uri.toString(), '/product/42');
});
```

Build a real `GoRouter` scoped to the test rather than mocking the router
itself — go_router's route-matching and redirect logic is exactly what you
want exercised, and mocking it away tests nothing but your mock's setup.
`pumpAndSettle` is safe here specifically because a route transition is a
finite animation with a real end frame, unlike the spinner case above.

## Faking platform channels in tests

Any plugin backed by a `MethodChannel` throws `MissingPluginException` in the
plain `flutter_test` environment — there's no real native side to answer the
call. Stub the channel directly:

```dart
setUp(() {
  TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
      .setMockMethodCallHandler(const MethodChannel('plugins.example.com/battery'),
          (call) async {
    if (call.method == 'getBatteryLevel') return 85;
    return null;
  });
});

tearDown(() {
  TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
      .setMockMethodCallHandler(const MethodChannel('plugins.example.com/battery'), null);
});
```

For a Pigeon-generated API, prefer whatever mock/test target Pigeon generated
for that API (it typically generates a way to swap the host implementation)
over hand-rolling a raw channel stub — see `platform-integration.md` for why
Pigeon exists in the first place.

## Golden tests and their font/platform flakiness

A golden test renders a widget and diff-compares it pixel-for-pixel against a
stored reference image. The comparison is exact, which makes it brittle
against anything that legitimately varies: the default Ahem/fallback test
font differs from your app's real font metrics, and text layout — hence pixel
positions — differs subtly across operating systems even with identical code.

- **Load real fonts explicitly** in the test (`loadAppFonts()` from
  `golden_toolkit`, or your own font-loading setup) rather than trusting the
  test framework's default block-glyph font — otherwise your golden locks in
  a rendering that looks nothing like what a device shows.
- **Generate and compare goldens on exactly one platform/CI runner**, never
  "whatever machine happens to run the test" — a golden generated on macOS
  and compared on Linux CI will show spurious diffs from anti-aliasing and
  font-hinting differences that have nothing to do with your code changing.
- **Some tolerance, not byte-identity**, if your comparison supports it —
  a fixed pixel-difference threshold absorbs sub-pixel rendering noise without
  hiding a real regression, which is a large solid-color change vastly above
  any reasonable threshold.

## `WidgetTester.view` for size/orientation

```dart
testWidgets('shows compact layout on narrow screens', (tester) async {
  tester.view.physicalSize = const Size(360, 640);
  tester.view.devicePixelRatio = 2.0;
  addTearDown(tester.view.reset);   // always restore — this is process-global test state

  await tester.pumpWidget(const MaterialApp(home: ResponsivePage()));

  expect(find.byType(CompactLayout), findsOneWidget);
});
```

Always pair a `tester.view` override with `addTearDown(tester.view.reset)` —
otherwise a size set in one test leaks into the next test file's default
view size in the same run.

## Coverage: what it doesn't tell you

`flutter test --coverage` produces line coverage, which answers "was this
line executed" and nothing about "was the *right* assertion made when it
ran." A test that calls a function and asserts nothing hits 100% of that
function's lines while verifying zero behavior. Treat coverage as a finder
for completely untested code paths, not as a quality score — a codebase can
sit at 95% coverage and still ship a regression coverage never would have
caught, because the assertions were weak, not because the lines weren't hit.

## What NOT to test

- Flutter framework internals — don't test that `setState` rebuilds a widget;
  that's Flutter's contract, not your code's.
- Third-party package internals — you're not responsible for verifying `dio`
  retries correctly; you're responsible for verifying your interceptor calls
  the right thing (mock `dio`, don't hit real endpoints in unit tests).
- Generated code (`.g.dart`, `.freezed.dart`) — test the class it's generated
  for through its public behavior, not the generated implementation.
- Trivial getters/constructors with no logic — a `const` data class with no
  computed fields doesn't need a dedicated test; it'll be exercised by
  whatever actually uses it.

## Checklist

- [ ] Suite is weighted toward unit tests; widget and integration tests cover
      interaction and flow, not business logic already covered by units
- [ ] `bloc_test` used for every bloc, asserting the exact `expect` sequence,
      not just the final state
- [ ] `mocktail`, not `mockito` — no `build_runner` mock codegen step in CI
- [ ] `registerFallbackValue` registered once per custom type used with
      `any()`/`captureAny()`, using a `Fake`, not a `Mock`
- [ ] No `pumpAndSettle()` on any screen with a continuous/looping animation —
      use `pump(Duration)` instead
- [ ] `BlocProvider`-wrapped widgets tested with `whenListen`, not a bare
      `when(() => bloc.state)` stub
- [ ] go_router tested with a real `GoRouter` instance, not a mocked router
- [ ] Any `MethodChannel`-backed plugin has a mock handler registered in
      `setUp`/torn down in `tearDown`
- [ ] Goldens load real fonts, generate/compare on one CI platform only, and
      use a tolerance rather than byte-identity
- [ ] Every `tester.view` override paired with `addTearDown(tester.view.reset)`
- [ ] Coverage numbers checked for gaps, not treated as a quality score
