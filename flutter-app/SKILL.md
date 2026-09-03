---
name: flutter-app
description: Use when building, scaffolding, or reviewing a Flutter/Dart mobile app — choosing between flutter_bloc, Riverpod, provider or setState; go_router navigation and deep links; freezed sealed-union state; get_it/injectable DI; dio networking and timeouts; platform channels and Pigeon; jank and frame-budget debugging; app size; widget/golden/bloc tests; flavours, build modes and store releases; Crashlytics. Also for "start a Flutter app", "my Flutter app is janky", "Flutter state management choice", "app size too large", "widget test hangs on pumpAndSettle".
---

# Flutter App

## Overview

A Flutter app is six things: **state management**, **navigation**, **networking**,
**local storage**, **platform integration**, and **release engineering**. The framework
gives you the widget layer; almost every real decision is about how state flows into it and
how you ship.

Two things dominate quality. **Dart is single-threaded per isolate**, so anything expensive
on the main isolate is visible jank — you have 16.7ms per frame at 60fps, 8.3ms at 120fps.
And **there is no code push** (an explicit Flutter non-goal), so a bad release needs a store
update — which makes feature flags and staged rollout part of the architecture, not an
afterthought.

Verified against **pub.dev and flutter.dev, 2026-08-01** — registry facts, not blog claims:
Flutter **3.44** (3.44.7) / Dart **3.12.1** · riverpod **3.4.2** · flutter_bloc **9.1.1** ·
go_router **17.3.0** · dio **5.11.0** · freezed **3.2.5** · drift **2.34.3** ·
injectable **3.0.0** · get_it **9.2.1** · mocktail **1.0.5** ·
flutter_secure_storage **10.3.1**. **`hive` is abandoned** — 2.2.3, last published
2022-06-30.

## When to Use

- Starting a Flutter app, or adding a feature to one
- Choosing state management, routing, DI, or a local-storage layer
- Reviewing Flutter code for correctness or performance
- Diagnosing: jank, memory leaks, oversized APK/IPA, slow startup, `pumpAndSettle` hangs
- Platform integration — channels, permissions, push, deep links
- Release engineering: flavours, signing, staged rollout, crash symbolication

**Not for:** Flutter web-only apps where web platform concerns dominate (see `web-frontend`),
or backend Dart.

## Step 0: Choose state management

| If… | Use |
|---|---|
| Team wants explicit, traceable, event-sourced state; large app | **flutter_bloc** — every transition is an event you can log and replay |
| Want less boilerplate, DI included, modern API | **Riverpod 3** — providers double as your DI container |
| Small app / single screen / local widget concern | **`setState`** — genuinely fine, don't over-engineer |
| Existing codebase already on it | **provider** — stable, but Riverpod is its successor |
| — | **Not GetX.** Widely discouraged: global mutable state, magic, testability problems |

Both bloc and Riverpod are correct choices. Bloc buys traceability at the cost of
boilerplate; Riverpod buys concision and DI at the cost of a less explicit history. **Pick one
per app and enforce it** — a codebase with both is the worst outcome.

## Quick Reference

| Task | Reach for | Detail |
|---|---|---|
| State | flutter_bloc 9 / Riverpod 3 | references/frameworks.md |
| State modelling | **freezed sealed unions + exhaustive `when()`** | references/state-architecture.md |
| Layout | feature-first, `presentation`/`domain`/`data` | references/state-architecture.md |
| Routing | **go_router 17** (`ShellRoute`, redirects for auth) | references/frameworks.md |
| DI | get_it + injectable, or Riverpod-as-DI | references/frameworks.md |
| Networking | **dio 5** with all three timeouts set | references/networking.md |
| JSON | freezed + json_serializable | references/networking.md |
| Local storage | **drift** / sqflite / isar — **not hive** (abandoned 2022) | references/platform-integration.md |
| Secure storage | Keychain/Keystore — **never `shared_preferences` for tokens** | references/platform-integration.md |
| Platform channels | **Pigeon** (typed codegen), not raw `MethodChannel` | references/platform-integration.md |
| Performance | DevTools timeline; UI vs raster thread | references/performance.md |
| Tests | `bloc_test`, `testWidgets`, **mocktail** over mockito | references/testing.md |
| Release | flavours + `--dart-define-from-file`, obfuscation | references/packaging-deploy.md |

## Bootstrap a new app

```
lib/
  main.dart                    # thin: bootstrap, error handlers, DI init, runApp
  src/
    core/                      # cross-cutting: theme, errors, extensions
    features/
      <feature>/
        presentation/          # widgets + bloc/notifier   <-- ONE name, always
        domain/                # entities, use cases, repository INTERFACES
        data/                  # repository impls, DTOs, data sources
    observability/             # crash/perf/analytics init in one place
```

1. Pin the SDK with **FVM** per project — "works on my machine" is usually a Flutter version.
2. `runZonedGuarded` + `FlutterError.onError` + `PlatformDispatcher.instance.onError` wired
   **before** anything else, or early crashes go unreported.
3. Config via `--dart-define-from-file`, **never committed** — and remember dart-defines are
   **visible in the shipped binary**, so they are not secrets.
4. State as a **freezed sealed union**, consumed with exhaustive `when()`.
5. go_router with a `redirect` for auth; `ShellRoute` for persistent bottom nav.
6. dio with `connectTimeout` / `receiveTimeout` / `sendTimeout` all set.
7. `dispose()` every controller, stream subscription and listener.

## The non-negotiables

1. **Set all three dio timeouts.** On a flaky mobile network a request with no timeout hangs
   until the OS kills it, and the user sees a spinner forever.
2. **Never block the main isolate.** JSON parsing of large payloads, crypto, image work →
   `Isolate.run()` / `compute()`.
3. **`dispose()` discipline.** Undisposed `AnimationController`s, `StreamSubscription`s,
   `TextEditingController`s and listeners are the #1 Flutter leak.
4. **`context.read` in callbacks, `context.watch`/`select` in `build`.** `watch` in a
   callback subscribes the whole widget; `read` in `build` misses updates. Both are silent.
5. **Exhaustive `when()`, not `maybeWhen()`.** `maybeWhen` with an `orElse` silently swallows
   new states; `when` breaks the build at every site that must change — that's the feature.
6. **`BlocListener` for side effects, `BlocBuilder` for rendering.** Navigation or snackbars
   from a build method fire on every rebuild.
7. **Never put tokens in `shared_preferences`.** It is plaintext. Use secure storage.
8. **One state-management library per app.**
9. **Never profile in debug mode.** Debug carries JIT and assertion overhead; measure in
   `--profile`.
10. **Feature-flag risky changes.** There's no code push; a bad release means a store review.

## Reference Map

| File | Read when |
|---|---|
| references/language-runtime.md | Dart 3 features, sealed classes, isolates, async, error handling, render model |
| references/frameworks.md | State management, routing, DI comparison and depth |
| references/state-architecture.md | Layout, layering, freezed unions, bloc widget-layer rules |
| references/networking.md | dio config, timeouts, interceptors, token refresh, cancellation |
| references/performance.md | Frame budget, DevTools, rebuild scoping, images, app size, leaks |
| references/platform-integration.md | Pigeon, channels, iOS SPM, permissions, storage, push |
| references/testing.md | Unit/widget/integration/golden, bloc_test, mocktail |
| references/packaging-deploy.md | Flavours, build modes, signing, CI/CD, Crashlytics, rollout |

## Common Mistakes

Several of these come from reading real production Flutter codebases.

| Mistake | Why it hurts | Fix |
|---|---|---|
| dio with no timeouts | Request hangs forever on a flaky network | Set all three |
| Heavy JSON parse on main isolate | Dropped frames; visible jank | `compute()` / `Isolate.run()` |
| Missing `dispose()` | Leaks memory and keeps streams alive | Dispose every controller/subscription |
| `context.watch` in a callback | Subscribes the whole widget — spurious rebuilds | `context.read` in callbacks |
| `context.read` in `build` | Misses updates; stale UI | `watch` or `select` in `build` |
| `maybeWhen` / `orElse` everywhere | New states silently unhandled | Exhaustive `when()` |
| Navigation inside `BlocBuilder` | Fires on every rebuild | `BlocListener` |
| Tokens in `shared_preferences` | Plaintext on disk | `flutter_secure_storage` |
| `hive` for storage | **Abandoned — last release 2022** | drift / sqflite / isar, or `hive_ce` |
| Raw `MethodChannel` with string keys | Typos fail at runtime, untyped maps | **Pigeon** codegen |
| `ListView(children: [...])` for long lists | Builds every child up front | `ListView.builder` |
| Full-size image decode | Decode size ≠ display size — top memory cause | `cacheWidth`/`cacheHeight` |
| Mixed layer naming (`screens/` vs `presentation/`) | Nobody can guess where a file lives | Pick one, enforce it |
| `feature/` and `feature_v2/` coexisting | Unfinished rewrite; dead code; which one runs? | Finish the migration, delete the old |
| Profiling in debug | JIT + assertions make numbers meaningless | `flutter run --profile` |
| Crash reporting treated as observability | No link from an app action to the backend span | Send a correlation/trace header |
| Two state-management libraries | Two mental models, two testing styles | One per app |
