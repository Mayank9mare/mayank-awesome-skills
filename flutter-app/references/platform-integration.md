# Platform Integration: Channels, Native Build Config, Storage

Every Flutter app is Dart on top of a native shell. The shell has opinions —
its own build system, its own package manager, its own storage APIs, its own
lifecycle rules for background code. This file is about the seam where Dart
meets that shell, and where it tends to snap.

## Pigeon over raw `MethodChannel`

A raw `MethodChannel` call is a stringly-typed remote call: the method name is
a string, the payload is `Map<String, dynamic>`, and nothing checks that your
Dart side and native side agree on either. **Pigeon** generates the boilerplate
on both sides from a single Dart definition, so a mismatch is a compile error
instead of a runtime crash.

```dart
// pigeons/battery.dart — the single source of truth, compiled by pigeon
import 'package:pigeon/pigeon.dart';

@ConfigurePigeon(PigeonOptions(
  dartOut: 'lib/src/platform/battery.g.dart',
  kotlinOut: 'android/app/src/main/kotlin/com/example/myapp/Battery.g.kt',
  swiftOut: 'ios/Runner/Battery.g.swift',
))
@HostApi()
abstract class BatteryApi {
  int getBatteryLevel();          // native -> Dart return type is checked at compile time
  @async
  bool isCharging();              // async host calls are just annotated, no manual Future plumbing
}
```

Run `dart run pigeon --input pigeons/battery.dart`, implement the generated
`BatteryApi` protocol/interface natively (Kotlin/Swift give you an abstract
class or protocol with the right signatures already stubbed), and call it from
Dart like any other typed object:

```dart
final battery = BatteryApi();
final level = battery.getBatteryLevel();   // no method-name string, no manual decode
```

| | Raw `MethodChannel`/`EventChannel` | Pigeon |
|---|---|---|
| Method identity | String, compared at runtime | Generated method, checked at compile time |
| Payload | `Map<String, dynamic>`, both sides hand-decode | Generated typed classes, codec generated |
| Typo in method name | Silent failure or `MissingPluginException` at runtime | Doesn't compile |
| Native-side changes | Manually kept in sync with Dart by convention | Regenerate from the same `.dart` file |
| Streams | `EventChannel`, manual `Stream` wiring | `@FlutterApi()` for native-initiated calls, or a manual stream on top |
| When to use anyway | One trivial call, prototyping, or a stream-heavy API pigeon doesn't model well | Everything else, especially plugin code shipped to others |

The real failure modes raw channels produce in production, in order of how
often they bite: a method name typo'd on one side only (compiles fine, throws
`MissingPluginException` at call time, no static check catches it); a native
side that starts sending an extra map key or renaming one, silently breaking
Dart's `payload['userId']` lookup with a null instead of an error; and a
platform-specific type that doesn't round-trip through the standard codec (a
64-bit int on the native side truncating on platforms with 32-bit codec
paths). Pigeon doesn't eliminate every mistake, but it turns the first two
into compile-time errors on regeneration and makes the third a solvable, typed
problem instead of a silent one.

## Federated plugins: when you need the split

A federated plugin separates into an **app-facing package** (the public API
consumers import), a **platform interface package** (the abstract contract,
usually a `PlatformInterface` subclass with a `verifyToken` guard against
accidental re-implementation), and **one package per platform** implementing
that interface. `path_provider`, `shared_preferences`, and `url_launcher` are
all structured this way in the Flutter team's own plugins.

You need this split when: you're publishing a plugin to pub.dev and want the
community to be able to add platform support (Linux, web) without touching
your code; you support platforms with meaningfully different implementations
and want them versioned and released independently; or your org ships the same
plugin API across apps but swaps the native implementation per product. You
do **not** need it for app-internal platform code — a Pigeon-generated API
called directly from your app's `lib/` is simpler and there's no third party
who needs the interface contract.

## iOS: Swift Package Manager is now the default

As of Flutter 3.44, new iOS projects use **Swift Package Manager (SwiftPM)**
by default for plugin dependency resolution; CocoaPods is being phased out
across the ecosystem, not just deprecated in docs. For an **existing** app
with a `Podfile`: nothing breaks today — Flutter still supports CocoaPods, and
a mixed setup (some plugins resolved via SwiftPM, some still via CocoaPods) is
supported during the transition. But treat the `Podfile` as a liability
starting now, not later:

- New plugin versions are increasingly SwiftPM-first; a plugin that dropped
  CocoaPods support entirely is the eventual end state for the ecosystem, not
  a hypothetical.
- If you maintain a plugin, ship **both** a `Package.swift` and a `.podspec`
  during the transition window — dropping either early cuts off a slice of
  consuming apps.
- `flutter create` for new projects no longer scaffolds CocoaPods files;
  don't assume `pod install` is step one in a fresh setup doc anymore.

```
WRONG (in 2026) — writing new setup docs / CI scripts that assume
`cd ios && pod install` is always required.

RIGHT — check whether the project's plugins resolve via SwiftPM first
(`ios/Flutter/ephemeral/Flutter-Generated.xcconfig` and the Xcode project's
Package Dependencies list are the tells); only fall back to CocoaPods
instructions for plugins that haven't migrated.
```

## Android: Gradle, `minSdk`, and R8's silent reflection breakage

`minSdk` is a product decision disguised as a build setting — every version
you support below the current Android release is a real user you're keeping,
and real native API surface you can't use without a runtime check. Set it from
actual usage data (Play Console's Android version distribution for your app),
not from "what's the lowest Flutter still supports."

The R8/ProGuard failure mode that costs the most debugging time: **it only
happens in release builds.** Debug builds don't run code shrinking/obfuscation,
so anything that uses reflection — `Gson`/`Moshi` deserializing a native model
class, a plugin that looks up a class by string name, `Class.forName(...)` —
works perfectly in every local run and CI debug build, then crashes on launch
or on a specific feature the first time a release APK/AAB reaches that code
path. The symptom is usually a `ClassNotFoundException` or a field silently
coming back null, because R8 renamed or stripped a class/field it couldn't see
was referenced (it only sees direct code references, not string-based lookups).

```
// android/app/proguard-rules.pro
// WRONG — no keep rules; ships fine in every debug build, breaks a native
// model class's JSON deserialization the moment it's built in --release.

// RIGHT — keep anything reached via reflection: your native data classes,
// any plugin's documented keep rules (check the plugin's README/wiki first —
// most reflection-using plugins publish their own -keep block), and generated
// serialization code.
-keep class com.example.myapp.model.** { *; }
-keepclassmembers class com.example.myapp.model.** { *; }
```

Verify by actually testing a `--release` build before shipping, not just a
`--profile` build — profile mode still skips some release-only shrinking
behavior depending on configuration. This is the single highest-value native
check you can add to a release checklist: **run the release build, not just
the release-mode flag, through the feature that uses reflection.**

## Permissions: ask at point of use, not at launch

```dart
// WRONG — requesting every permission on first launch, before the user has
// seen any reason to grant them. iOS App Review rejects apps that do this
// without contextual justification, and users deny blind prompts on reflex.
Future<void> onAppStart() async {
  await Permission.camera.request();
  await Permission.location.request();
  await Permission.notification.request();
}

// RIGHT — request exactly when the feature needing it is invoked, with UI
// context already explaining why.
Future<void> onScanReceiptTapped() async {
  final status = await Permission.camera.request();
  if (status.isGranted) {
    // proceed to camera
  } else if (status.isPermanentlyDenied) {
    // route to Permission.camera.request() won't re-prompt — send to
    // openAppSettings() with an explanation, not a repeated dead-end request
  }
}
```

`permission_handler` normalizes both platforms' permission models, but the
platform manifests still need real entries: `Info.plist` usage-description
strings (`NSCameraUsageDescription` etc. — missing or vague ones are an App
Review rejection reason on their own) and Android's manifest permission
declarations plus runtime request for dangerous-permission-group items on API
23+.

## Deep links: App Links (Android) and Universal Links (iOS)

Both platforms require a **server-hosted verification file** proving you own
the domain you're claiming links for — this is what distinguishes a verified
deep link (opens your app) from a custom URL scheme (any app can register the
same scheme and hijack it).

| | Android App Links | iOS Universal Links |
|---|---|---|
| Verification file | `/.well-known/assetlinks.json` | `/.well-known/apple-app-site-association` |
| Declares | Your app's package name + signing cert SHA-256 fingerprint | Your app's Team ID + bundle ID, per path |
| Manifest/entitlement | `<intent-filter android:autoVerify="true">` | Associated Domains capability, `applinks:example.com` |
| Failure mode if misconfigured | Link opens in browser instead of app, silently | Same — falls back to Safari with no error surfaced |

Test with the platform's own verification tooling before shipping (Android's
Digital Asset Links API tester, or `swcutil` on macOS for Apple's side) —
these fail closed and silent, so "it just opens the browser" is the only
symptom you get without checking the verification file directly.

## Push notifications: the background-handler isolate constraint

Firebase Cloud Messaging's background message handler runs in a **separate
isolate**, spun up specifically to run that one function when a push arrives
while the app isn't in the foreground. That isolate does not share memory with
your running app — no access to your `get_it`/Riverpod container, no access to
any singleton, no access to anything constructed in `main()`. It must be a
**top-level function** (or static method), because Dart needs a way to
reference it without a closure over instance state that won't exist in the
new isolate.

```dart
// WRONG — a method that closes over app state; this either fails to
// register as a background handler or silently can't reach the state it
// closes over when the isolate spins up fresh.
class NotificationService {
  Future<void> _onBackgroundMessage(RemoteMessage message) async {
    _analytics.log(message.data);   // _analytics doesn't exist in this isolate
  }
}

// RIGHT — top-level function, re-initializes anything it needs from scratch.
@pragma('vm:entry-point')   // required so release-mode tree-shaking doesn't strip it
Future<void> firebaseMessagingBackgroundHandler(RemoteMessage message) async {
  await Firebase.initializeApp();       // this isolate has no prior initialization
  // do the minimum needed here — write to local storage, schedule a local
  // notification — then let the foreground isolate pick up the rest on next launch
}

void main() {
  FirebaseMessaging.onBackgroundMessage(firebaseMessagingBackgroundHandler);
  runApp(const MyApp());
}
```

## Background execution limits

Both platforms aggressively curtail what runs when the app isn't foregrounded,
and the limits are platform policy, not something you configure around:

- **iOS**: background execution is time-boxed (roughly 30 seconds when the
  app requests extra time via `beginBackgroundTask`), and true recurring
  background work requires specific capabilities (Background Fetch,
  Background Processing tasks) that iOS schedules opportunistically — you
  request a window, you don't get to demand one.
- **Android**: Doze mode and App Standby batch and defer background network
  and wake locks for apps the user hasn't opened recently; `WorkManager` is
  the supported way to schedule deferrable background work because it
  cooperates with these restrictions instead of fighting them.
- Neither platform guarantees a background task completes — design background
  work as resumable (checkpoint progress, retry on next opportunity), not as
  a single long-running operation you assume finishes.

## Secure storage vs `shared_preferences`

```
WRONG — storing an auth token, refresh token, or any PII in
shared_preferences. On Android it's an unencrypted XML file in app-private
storage; on iOS it's an unencrypted plist. "App-private" is not "encrypted" —
a rooted device, a device backup, or a debug build with adb access reads it
in plaintext.
await sharedPreferences.setString('auth_token', token);

RIGHT — flutter_secure_storage, backed by Keychain on iOS and
Keystore-backed EncryptedSharedPreferences on Android.
await secureStorage.write(key: 'auth_token', value: token);
```

`shared_preferences` is correctly scoped for what it's for: small
non-sensitive UI/app state (a "seen onboarding" flag, a selected theme, a
feature flag override). The moment the value is a credential, a session
token, or anything you'd be uncomfortable seeing in a plaintext file dump,
it's `flutter_secure_storage` or nothing.

## Local storage decision table

| | Model | Typed | Codegen | Maintenance status | Use when |
|---|---|---|---|---|---|
| **drift** 2.34.3 | SQL, relational | Yes, generated | Yes | Active | Default choice — relational data, complex queries, migrations you need to reason about |
| sqflite | Raw SQL | No — you write and parse SQL by hand | No | Active, low-level | You want direct SQL control and don't want an ORM layer, or a very small schema |
| isar | NoSQL, object store | Yes | Yes | Active, but smaller ecosystem than drift | Document-shaped data, want NoSQL semantics with type safety |
| ~~hive~~ | NoSQL, object store | Partial | No | **Abandoned — last published 2022-06-30** | Don't. See below. |

**`hive` is not a current option.** Version 2.2.3, last published mid-2022,
with no maintenance since. Don't start new usage on it, and treat existing
usage as migration debt — Flutter's own SDK and dependent packages have moved
on in the years since, and an unmaintained storage layer is exactly the kind
of dependency that breaks silently on some future Dart/Flutter release with no
one left to fix it. If the API shape is the appeal, `hive_ce` is the
community-maintained fork carrying the torch forward — evaluate it on its own
merits, but default new work to **drift** unless you have a specific reason
not to.

## Checklist

- [ ] Platform channel code goes through Pigeon, not hand-written
      `MethodChannel` string calls, for anything beyond a single trivial call
- [ ] Federated plugin structure used only when publishing externally or
      genuinely swapping native implementations per product — not for
      app-internal platform code
- [ ] iOS dependency setup checked against SwiftPM-first reality, not assumed
      to require CocoaPods
- [ ] `minSdk` set from real usage data, not copied from a template
- [ ] R8/ProGuard keep rules added for anything reached via reflection, and a
      real `--release` build tested before shipping — not just `--profile`
- [ ] Permissions requested at point of use with context, never all at launch
- [ ] Deep link verification files (`assetlinks.json` /
      `apple-app-site-association`) hosted and verified with platform tooling
- [ ] Push background handler is a top-level function with
      `@pragma('vm:entry-point')`, re-initializes its own dependencies
- [ ] Background work designed as resumable, not assumed to run to completion
- [ ] No token, credential, or PII ever written to `shared_preferences`
- [ ] New local storage work defaults to drift; no new `hive` usage
