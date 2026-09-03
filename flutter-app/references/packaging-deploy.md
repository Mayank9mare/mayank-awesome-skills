# Packaging & Deploy: Flavors, Signing, CI/CD, Rollout

Getting a Flutter app to compile is the easy 80%. The remaining 20% —
flavors that don't leak staging config into prod, crash traces that are
actually readable, signing that doesn't block a release at 11pm, and a
rollout mechanism for when the inevitable bad build ships anyway — is where
most teams lose days. None of it is hard; all of it is easy to get wrong
exactly once, expensively.

## Flavors: `--flavor` + `--dart-define-from-file`

```bash
flutter run --flavor dev --dart-define-from-file=config/dev.json
flutter build apk --flavor prod --dart-define-from-file=config/prod.json
```

```json
// config/prod.json
{
  "API_BASE_URL": "https://api.example.com",
  "SENTRY_DSN": "https://public-key@sentry.example.com/1",
  "ENVIRONMENT": "prod"
}
```

```dart
// Read with String.fromEnvironment / bool.fromEnvironment — these are
// resolved at COMPILE time, not runtime, which is exactly what you want:
// wrong-flavor bugs become build-time facts instead of runtime surprises.
const apiBaseUrl = String.fromEnvironment('API_BASE_URL', defaultValue: 'https://api.example.com');
```

```
WRONG — a committed Config class with environment picked by a runtime flag.
class Config {
  static Environment current = Environment.dev;   // set by... what, exactly?
}
// Every environment's secrets/URLs live in the same compiled binary
// simultaneously; a runtime bug can flip `current` and hit prod with staging
// credentials, or vice versa. There's also nothing stopping dev's URLs from
// shipping inside the prod binary as unused-but-present strings.

RIGHT — --dart-define-from-file, one JSON per environment, only the
selected environment's values are ever compiled into that specific binary.
flutter build appbundle --flavor prod --dart-define-from-file=config/prod.json
```

`--flavor` additionally switches native build variants (Android
`productFlavors`, iOS schemes/configurations) — separate `applicationId`
suffixes, separate app icons/names, separate `google-services.json` /
`GoogleService-Info.plist` per environment, so dev and prod can be installed
side by side on the same device without collision.

**`--dart-define` values are not secrets.** They are compiled directly into
the binary as plain strings and are trivially extractable with `strings` on
the compiled artifact or by decompiling the APK/IPA — no reverse-engineering
skill required. An API key, a signing secret, anything that must stay
confidential does not belong in a `--dart-define`, in `config/*.json`, or
anywhere in the client binary at all; it belongs behind a backend endpoint
the app calls. `--dart-define` is for configuration (which base URL, which
feature flags default on), not credentials — despite how commonly apps ship
"secret" API keys this exact way.

## Build modes: debug, profile, release

| Mode | Compilation | Assertions | Use for |
|---|---|---|---|
| debug | JIT | Enabled | Development, hot reload |
| profile | AOT | Disabled | Performance measurement, DevTools profiling |
| release | AOT | Disabled | Store submission, real users |

**Never measure performance in debug mode.** Debug is JIT-compiled with
assertions enabled and none of release's tree-shaking or AOT optimization —
a jank you see in debug may not exist in release, and a smooth debug run can
still jank in release once real AOT-compiled, non-instrumented code paths run
at real device speed. Use `--profile` for anything you're timing or
profiling with DevTools; it's release-speed code with just enough
instrumentation hooks left in to be observable, which debug and release
individually are not.

## Obfuscation and symbol archival

```bash
flutter build appbundle --release \
  --obfuscate \
  --split-debug-info=build/symbols/
```

`--obfuscate` renames Dart symbols in the compiled binary so a decompiled
release build doesn't hand out your class/method names for free.
`--split-debug-info` pulls debug symbols out of the shipped binary into a
separate directory instead of embedding them — smaller binary, and the
symbols aren't sitting inside something you're distributing publicly.

The critical operational consequence: **you must archive that
`build/symbols/` output, tied to the exact build/version that shipped.**
Without it, an obfuscated release crash report is a stack trace of
meaningless renamed symbols and offsets — unreadable, permanently, because
the mapping only ever existed in the directory you just didn't keep. Treat
symbol files the way you'd treat a release artifact: versioned, retained,
retrievable months later when a delayed crash report for that version comes
in from Crashlytics or the Play Console.

```
WRONG — obfuscate and ship, symbols discarded after CI finishes.
flutter build appbundle --release --obfuscate --split-debug-info=/tmp/symbols
# /tmp is wiped; the next crash report for this build is permanently opaque.

RIGHT — symbols archived per-build, keyed by version+build number, retained
at least as long as that build can still be running on a user's device.
flutter build appbundle --release --obfuscate --split-debug-info=build/symbols/1.4.2+89/
# then upload build/symbols/1.4.2+89/ to durable storage (S3/GCS/artifact
# registry) as a CI step, before the runner is torn down.
```

## Code signing

**iOS**: a provisioning profile ties together an App ID, a distribution
certificate, and (for ad-hoc/enterprise) a device list; Xcode or `fastlane
match` manages the certificate/profile pair. Expired certificates and
profiles are the single most common iOS release-day failure — they expire
silently on a calendar schedule unrelated to your release schedule, and the
build only fails at archive/upload time, not before.

**Android**: a keystore (`.jks`/`.keystore`) signs the release build; Google
Play additionally re-signs with **Play App Signing** if enabled, in which
case your upload key signs the upload and Google's own key signs what
actually reaches devices — meaning a lost upload key is recoverable through
Play Console, whereas a lost signing key with App Signing disabled is not:
you cannot update that app again, ever, under that package name.

```
WRONG — the release keystore committed to the repo, or attached to a single
engineer's laptop with no backup.
android/app/upload-keystore.jks   # committed alongside key.properties, in git
# Leaked to anyone with repo access; if it's the ONLY copy and that laptop
# dies, the app can never be updated again (without Play App Signing).

RIGHT — keystore excluded from git, stored in a secrets manager or CI
secret store, referenced by CI at build time, with Play App Signing enabled
so the upload key is a recoverable credential rather than a single point of
permanent failure.
# .gitignore
*.jks
key.properties
```

## Version and build number: `pubspec.yaml`

```yaml
version: 1.4.2+89
#         ^^^^^ user-visible version   ^^ build number
```

The build number (`+89`) must be **monotonically increasing** for a given
package/app ID on both stores — Play Console and App Store Connect both
reject an upload whose build number isn't strictly greater than every prior
upload for that app, even across different version-name tracks (a `1.4.3`
hotfix's build number still has to exceed `1.4.2`'s). Automate the bump in
CI (derive it from the CI run number or a counter file) rather than trusting
manual edits — a forgotten bump is a rejected upload discovered only at
submission time.

## CI/CD

- **Fastlane** — the de facto standard for both platforms' release
  mechanics: cert/profile management (`match`), build (`gym`/`build_app`),
  and upload (`deliver`/`upload_to_play_store`/`upload_to_testflight`) behind
  one consistent CLI, callable from any CI system.
- **Codemagic / Bitrise / GitHub Actions** — Codemagic is Flutter-specific
  and has first-class flavor/signing support out of the box; Bitrise and
  GitHub Actions are general-purpose and need more manual Flutter-specific
  setup (SDK install/cache, signing injection) but fit better if the rest of
  your stack is already there.
- **Cache the pub cache and Gradle cache** across runs
  (`~/.pub-cache`, `~/.gradle/caches`, and iOS's `Pods`/SwiftPM checkouts) —
  a cold CI runner re-resolving and re-downloading every dependency on every
  run is minutes of pure waste multiplied by every run of every day.

## Crashlytics, Performance Monitoring, and the tracing gap

```dart
// main.dart
Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Firebase.initializeApp();

  FlutterError.onError = FirebaseCrashlytics.instance.recordFlutterFatalError;
  PlatformDispatcher.instance.onError = (error, stack) {
    FirebaseCrashlytics.instance.recordError(error, stack, fatal: true);
    return true;
  };

  runApp(const MyApp());
}
```

`firebase_crashlytics` (fatal/non-fatal error capture) and
`firebase_performance` (network/screen-render traces) cover "did the app
crash" and "was the app slow" — real, necessary telemetry. What they do
**not** give you, and what most Flutter apps ship without, is **distributed
tracing**: a link from a specific app action to the specific backend span
that action caused. Crashlytics tells you the app crashed in a network
callback; it cannot tell you which backend request, trace, or downstream
service call that network request corresponds to on the server side — those
are two disconnected telemetry systems, one client-side and one
server-side, with no shared identifier joining them.

Fix it by generating a correlation ID client-side and propagating it as a
standard W3C `traceparent` header on every outbound request, so the backend's
tracing system (whatever it is — OTel, Sentry, a homegrown one) sees the
same identifier the client generated and can join its spans back to the
originating app action:

```dart
// trace_interceptor.dart — attach to your http client (see networking.md)
class TraceInterceptor extends Interceptor {
  @override
  void onRequest(RequestOptions options, RequestInterceptorHandler handler) {
    final traceId = _generateTraceId();     // 16 random bytes, hex-encoded
    final spanId = _generateSpanId();       // 8 random bytes, hex-encoded
    options.headers['traceparent'] = '00-$traceId-$spanId-01';
    handler.next(options);
  }
}
```

Without this, "crash reporting" and "backend observability" stay two
separate, un-correlatable systems — you can see the app crashed and see the
backend had an error spike in the same rough minute, but you cannot prove,
from telemetry alone, that they're the same incident.

## Staged/phased rollout

Both stores support releasing to a percentage of users before ramping to
100%: Play Console's staged rollout percentage, App Store Connect's phased
release (a fixed 7-day ramp curve). Use it for every release that touches
anything risky — new payment flow, new auth flow, a dependency major-version
bump — not just "big" releases; the entire value of a staged rollout is
catching a bad build at 1–10% of your install base instead of 100%, and that
value doesn't correlate with how big the release felt when you shipped it.

## No code push: feature flags are architecture, not an afterthought

Flutter has **no built-in code push mechanism** — this is an explicit,
stated non-goal of the framework, not a missing feature waiting on a
roadmap. A shipped bug cannot be patched over-the-air; the only path back is
a new build through the same store review and staged rollout as any other
release, which is hours to days, not minutes.

The direct consequence: feature flags and a remote kill switch are not a
nice-to-have layered on top of a finished app — they are part of the release
architecture from the start, because they are the *only* sub-minute lever
you have over already-installed binaries. A risky feature ships behind a
flag that defaults off remotely; if it misbehaves in production, flipping
the remote flag is the fix, and the store-review-gated rebuild becomes the
slow, non-urgent follow-up rather than the only option under pressure.

## App size

```bash
flutter build appbundle --analyze-size
```

`--analyze-size` breaks down exactly what's contributing to binary size —
which packages, which assets, which of your own code — as a browsable
report rather than a single opaque total, which is what turns "the app got
bigger" into "this one bundled font did it."

- **Deferred components** (Android) split rarely-used features (a debug
  console, an admin-only screen, large ML models) into on-demand downloaded
  modules instead of shipping them in the initial install, cutting the
  install size everyone pays for a feature most users never open.
- **Icon tree-shaking** is on by default for `IconData`-based icon fonts —
  it strips unused glyphs from bundled icon fonts like `MaterialIcons`
  automatically, so a font that logically has thousands of glyphs ships only
  the handful your app actually references, with no action needed beyond
  not disabling it.

## Checklist

- [ ] Every environment's config comes from `--dart-define-from-file`, never
      a committed `Config` class with a runtime-selected environment
- [ ] Nothing confidential (API secrets, signing keys) is ever passed via
      `--dart-define` — it is compiled into the binary and extractable
- [ ] Performance is measured in `--profile` builds, never `--debug`
- [ ] Release builds use `--obfuscate --split-debug-info`, and the resulting
      symbol files are archived per-version in durable storage before the CI
      runner is torn down
- [ ] Signing keystore/certs are excluded from git and live in a secrets
      manager or CI secret store; Play App Signing is enabled so the upload
      key is recoverable
- [ ] Build number in `pubspec.yaml` is bumped automatically in CI and is
      monotonically increasing across all release tracks
- [ ] pub cache and Gradle/SwiftPM caches are cached across CI runs
- [ ] Crashlytics wired via `FlutterError.onError` and
      `PlatformDispatcher.instance.onError`
- [ ] Outbound requests carry a client-generated `traceparent` header so
      backend tracing can join app actions to backend spans
- [ ] Risky releases go out via staged/phased rollout, not 100% immediately
- [ ] Any feature with real production risk sits behind a remotely
      controllable flag/kill switch — not held back only by store review
- [ ] `--analyze-size` checked before a release that adds new dependencies
      or large assets
