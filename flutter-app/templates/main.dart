/// Production-shaped Flutter bootstrap.
///
/// Copy to lib/main.dart and adapt. It demonstrates the things that cause real
/// incidents when omitted:
///
///   * error handlers wired BEFORE anything else, or early crashes go unreported
///   * config via --dart-define-from-file (and why those are NOT secrets)
///   * go_router with an auth redirect and a ShellRoute for persistent nav
///   * freezed sealed-union state consumed with exhaustive when()
///   * BlocListener for side effects vs BlocBuilder for rendering
///   * dispose() discipline
///
/// See the flutter-app skill's references/ for the reasoning behind each.
library;

import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:go_router/go_router.dart';

// ---------------------------------------------------------------------------
// Config
//
// Supplied at build time:
//   flutter run --flavor prod --dart-define-from-file=config/prod.json
//
// CRITICAL: --dart-define values are COMPILED INTO THE BINARY and are
// extractable from a shipped app. They are configuration, NOT secrets. Never
// put an API secret, signing key or private token here — people do this
// routinely and ship credentials to every user.
// ---------------------------------------------------------------------------

class AppConfig {
  const AppConfig({
    required this.apiBaseUrl,
    required this.environment,
    required this.enableVerboseLogging,
  });

  factory AppConfig.fromEnvironment() {
    const url = String.fromEnvironment('API_BASE_URL');
    const env = String.fromEnvironment('ENVIRONMENT', defaultValue: 'dev');

    // Fail loudly at startup rather than producing confusing 404s against an
    // empty base URL on the first network call.
    assert(url.isNotEmpty, 'API_BASE_URL missing — pass --dart-define-from-file');

    return const AppConfig(
      apiBaseUrl: url,
      environment: env,
      enableVerboseLogging: bool.fromEnvironment('VERBOSE_LOGGING'),
    );
  }

  final String apiBaseUrl;
  final String environment;
  final bool enableVerboseLogging;

  bool get isProduction => environment == 'prod';
}

// ---------------------------------------------------------------------------
// Bootstrap
// ---------------------------------------------------------------------------

Future<void> main() async {
  // runZonedGuarded catches async errors that escape the Flutter framework —
  // a rejected Future in a bloc handler, for instance. Everything, including
  // ensureInitialized, goes INSIDE it so startup crashes are captured too.
  await runZonedGuarded(
    () async {
      WidgetsFlutterBinding.ensureInitialized();

      final config = AppConfig.fromEnvironment();

      // Framework errors (build/layout/paint). Print in debug so you see them
      // in the console; forward to the crash reporter in release.
      FlutterError.onError = (details) {
        FlutterError.presentError(details);
        if (config.isProduction) {
          // crashlytics.recordFlutterFatalError(details);
        }
      };

      // Errors from the platform/engine layer that never reach FlutterError.
      // Easy to forget, and it's the handler that catches the weirdest crashes.
      PlatformDispatcher.instance.onError = (error, stack) {
        if (config.isProduction) {
          // crashlytics.recordError(error, stack, fatal: true);
        }
        return true; // handled
      };

      await configureDependencies(config); // get_it / injectable
      // Bloc-wide transition logging — a cheap, high-value observability win.
      Bloc.observer = AppBlocObserver(verbose: config.enableVerboseLogging);

      runApp(MyApp(config: config));
    },
    (error, stack) {
      // Last resort: uncaught async errors.
      debugPrint('Uncaught zone error: $error\n$stack');
      // crashlytics.recordError(error, stack, fatal: true);
    },
  );
}

/// Logs every bloc transition. Invaluable for reconstructing "what did the user
/// actually do" from a bug report.
class AppBlocObserver extends BlocObserver {
  const AppBlocObserver({this.verbose = false});
  final bool verbose;

  @override
  void onTransition(Bloc<dynamic, dynamic> bloc, Transition<dynamic, dynamic> t) {
    super.onTransition(bloc, t);
    if (verbose) {
      debugPrint('${bloc.runtimeType}: ${t.event.runtimeType} '
          '→ ${t.nextState.runtimeType}');
    }
  }

  @override
  void onError(BlocBase<dynamic> bloc, Object error, StackTrace stackTrace) {
    // A bloc that throws would otherwise fail silently from the UI's point of view.
    debugPrint('${bloc.runtimeType} error: $error');
    super.onError(bloc, error, stackTrace);
  }
}

// ---------------------------------------------------------------------------
// Routing
// ---------------------------------------------------------------------------

class MyApp extends StatefulWidget {
  const MyApp({required this.config, super.key});
  final AppConfig config;

  @override
  State<MyApp> createState() => _MyAppState();
}

class _MyAppState extends State<MyApp> {
  late final GoRouter _router;
  late final AuthBloc _authBloc;

  @override
  void initState() {
    super.initState();
    _authBloc = getIt<AuthBloc>();

    _router = GoRouter(
      initialLocation: '/',
      // Re-evaluate redirects when auth state changes, so a token expiry kicks
      // the user to /login without every screen having to check.
      refreshListenable: GoRouterRefreshStream(_authBloc.stream),
      redirect: (context, state) {
        final loggedIn = _authBloc.state is Authenticated;
        final atLogin = state.matchedLocation == '/login';

        if (!loggedIn && !atLogin) {
          // Preserve the destination so we can return there after login.
          return '/login?from=${Uri.encodeComponent(state.matchedLocation)}';
        }
        if (loggedIn && atLogin) return '/';
        return null; // no redirect
      },
      routes: [
        GoRoute(path: '/login', builder: (_, __) => const LoginScreen()),
        // ShellRoute keeps the bottom nav mounted across tab switches, so tab
        // state survives navigation instead of being rebuilt each time.
        ShellRoute(
          builder: (_, __, child) => AppScaffold(child: child),
          routes: [
            GoRoute(path: '/', builder: (_, __) => const HomeScreen()),
            GoRoute(
              path: '/orders/:id',
              builder: (_, s) => OrderScreen(orderId: s.pathParameters['id']!),
            ),
          ],
        ),
      ],
      errorBuilder: (_, state) => NotFoundScreen(location: state.uri.toString()),
    );
  }

  @override
  void dispose() {
    _router.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MultiBlocProvider(
      providers: [
        BlocProvider<AuthBloc>.value(value: _authBloc),
        // Lazy by default: the bloc is built on first use, not at startup.
        BlocProvider<OrdersBloc>(create: (_) => getIt<OrdersBloc>()),
      ],
      child: MaterialApp.router(
        title: 'myapp',
        routerConfig: _router,
        theme: appTheme,
        darkTheme: appDarkTheme,
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// A screen: the widget-layer rules made concrete
// ---------------------------------------------------------------------------

class OrderScreen extends StatelessWidget {
  const OrderScreen({required this.orderId, super.key});
  final String orderId;

  @override
  Widget build(BuildContext context) {
    // context.read in a callback / one-shot dispatch: does NOT subscribe.
    // Using context.watch here would rebuild this widget on every state change.
    return BlocListener<OrdersBloc, OrdersState>(
      // BlocListener for SIDE EFFECTS. Doing this inside BlocBuilder would fire
      // a snackbar or a navigation on every rebuild.
      listenWhen: (prev, next) => next is OrdersFailure,
      listener: (context, state) {
        if (state case OrdersFailure(:final message)) {
          ScaffoldMessenger.of(context)
              .showSnackBar(SnackBar(content: Text(message)));
        }
      },
      child: Scaffold(
        appBar: AppBar(title: Text('Order $orderId')),
        // BlocBuilder for RENDERING only.
        body: BlocBuilder<OrdersBloc, OrdersState>(
          builder: (context, state) {
            // Exhaustive switch over a sealed union: adding a state BREAKS THE
            // BUILD here, which is the point. An `orElse`/default would silently
            // swallow the new case and render nothing.
            return switch (state) {
              OrdersInitial() => const SizedBox.shrink(),
              OrdersLoading() => const Center(child: CircularProgressIndicator()),
              OrdersFailure(:final message) => ErrorView(
                  message: message,
                  onRetry: () =>
                      context.read<OrdersBloc>().add(OrdersRequested(orderId)),
                ),
              OrdersLoaded(:final orders) => ListView.builder(
                  // .builder, not ListView(children:) — only visible rows are built.
                  itemCount: orders.length,
                  itemExtent: 72, // known extent lets Flutter skip layout passes
                  itemBuilder: (_, i) => OrderTile(order: orders[i]),
                ),
            };
          },
        ),
      ),
    );
  }
}

/// Bridges a Stream to a Listenable for go_router's refreshListenable.
/// Note the dispose() — an undisposed StreamSubscription is the single most
/// common Flutter memory leak.
class GoRouterRefreshStream extends ChangeNotifier {
  GoRouterRefreshStream(Stream<dynamic> stream) {
    notifyListeners();
    _sub = stream.asBroadcastStream().listen((_) => notifyListeners());
  }

  late final StreamSubscription<dynamic> _sub;

  @override
  void dispose() {
    _sub.cancel();
    super.dispose();
  }
}
