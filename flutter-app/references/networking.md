# Networking: HTTP Clients, Interceptors, Errors

Mobile networks are worse than the network you tested on. Wi-Fi to cellular
handoffs, airplane mode, captive portals, a train entering a tunnel mid-request
— everything here exists to make those ordinary events survivable instead of
crashes or hangs.

## dio vs http vs retrofit+dio

| | `http` | `dio` 5.11.0 | `retrofit` 4.9.2 + `dio` |
|---|---|---|
| Interceptors | No (wrap manually) | Yes — first-class `Interceptor` chain | Yes (via dio) |
| Timeouts | Manual, per-call | Built into `BaseOptions` | Built into `BaseOptions` |
| Cancellation | No | `CancelToken` | `CancelToken` |
| Request/response transform | Manual | `Transformer` | Generated |
| Multipart/form-data | Manual | Built in | Generated from annotations |
| Boilerplate per endpoint | Highest | Medium | Lowest — annotate, codegen does the rest |
| Best fit | A single trivial call, or a package that must stay dependency-light | Most apps | Apps with many endpoints where hand-written request code becomes repetitive |

Note the real-world evidence: across four production repos, adoption was `http`
1, dio 0, retrofit 0. That doesn't make `http` the recommendation — it reflects
that all four repos are older or thin on networking surface, not that `dio` is
unproven. For any app making more than a handful of calls with auth headers,
retries, or interceptor-based cross-cutting concerns, **dio is the default
recommendation** here; add `retrofit` once you have enough endpoints that
hand-writing each `Response` unwrap is repetitive.

## One client instance, constructed once

```dart
// WRONG — a new Dio() per call. Rebuilds the connection pool and re-runs
// every interceptor's setup cost on every request; no benefit, only cost.
Future<User> getUser(String id) async {
  final dio = Dio();
  final response = await dio.get('/users/$id');
  return User.fromJson(response.data);
}

// RIGHT — one Dio instance, constructed once (typically registered in your
// DI container — get_it or Riverpod, see frameworks.md), reused everywhere.
class ApiClient {
  ApiClient()
      : _dio = Dio(
          BaseOptions(
            baseUrl: 'https://api.example.com',
            connectTimeout: const Duration(seconds: 5),   // time to establish connection
            receiveTimeout: const Duration(seconds: 10),  // time between response bytes
            sendTimeout: const Duration(seconds: 10),     // time to upload the request body
          ),
        ) {
    _dio.interceptors.addAll([AuthInterceptor(_dio), RetryInterceptor(_dio)]);
  }

  final Dio _dio;
  Dio get client => _dio;
}
```

## Timeouts are not optional

`dio`'s default `BaseOptions` has **no timeouts set** — you must set them.
Without a `connectTimeout`/`receiveTimeout`, a call to a server that accepted
the TCP connection but then never responds (a very common failure mode on
flaky mobile networks — the request got through, the response got lost) hangs
the `Future` forever. That `Future` is usually awaited from a bloc event
handler, so the UI sits on a loading spinner indefinitely with no way out
except killing the app. Set all three: `connectTimeout` (dial), `receiveTimeout`
(gap between response bytes, not total transfer time — matters for large
downloads), and `sendTimeout` (gap while uploading, matters for large uploads).

## Auth-refresh interceptor and the concurrent-401 stampede

The naive version of "refresh the token on 401 and retry" breaks the moment
more than one request is in flight when the token expires: every one of them
gets a 401, every one of them tries to refresh, and you hit your auth server
with N simultaneous refresh calls — several of which may race and invalidate
each other's resulting tokens depending on your backend's refresh-token
rotation policy.

```dart
// WRONG — no coordination. Five concurrent requests expiring at once fire
// five concurrent refresh calls.
class NaiveAuthInterceptor extends Interceptor {
  NaiveAuthInterceptor(this._dio, this._authApi);
  final Dio _dio;
  final AuthApi _authApi;

  @override
  void onError(DioException err, ErrorInterceptorHandler handler) async {
    if (err.response?.statusCode == 401) {
      final newToken = await _authApi.refresh();   // called once PER failed request
      err.requestOptions.headers['Authorization'] = 'Bearer $newToken';
      handler.resolve(await _dio.fetch(err.requestOptions));
    } else {
      handler.next(err);
    }
  }
}

// RIGHT — single-flight refresh. The first 401 triggers the refresh; every
// other concurrent 401 awaits the SAME in-flight Future instead of starting
// its own.
class AuthInterceptor extends Interceptor {
  AuthInterceptor(this._dio, this._authApi);
  final Dio _dio;
  final AuthApi _authApi;
  Future<String>? _refreshInFlight;

  Future<String> _refresh() {
    // If a refresh is already running, every caller awaits that ONE Future.
    // The `??=` is the entire trick — only the first caller assigns it.
    return _refreshInFlight ??= _authApi.refresh().whenComplete(() {
      _refreshInFlight = null;   // clear once done so the NEXT expiry can refresh again
    });
  }

  @override
  void onError(DioException err, ErrorInterceptorHandler handler) async {
    if (err.response?.statusCode != 401) return handler.next(err);

    try {
      final newToken = await _refresh();
      final retryOptions = err.requestOptions
        ..headers['Authorization'] = 'Bearer $newToken';
      handler.resolve(await _dio.fetch(retryOptions));
    } catch (_) {
      handler.next(err);   // refresh itself failed — surface the original 401, log user out
    }
  }
}
```

The `_refreshInFlight ??= …` pattern is the whole mechanism: the first request
to hit a 401 kicks off the refresh and stores the `Future`; every other request
that hits a 401 while that `Future` is still pending gets the *same* `Future`
handed back instead of starting a second refresh call. Once it completes,
clearing the field lets the next expiry (potentially minutes later) trigger a
fresh refresh instead of replaying a stale one.

## Retries with jitter, and what's safe to retry

Same rule as any HTTP client: retry only idempotent methods (GET, PUT, DELETE)
or POSTs guarded by an idempotency key, only for transient failures (timeouts,
connection errors, 502/503/504, 429), and never in more than one layer (don't
stack a dio retry interceptor on top of a platform-level retry — they multiply).

```dart
class RetryInterceptor extends Interceptor {
  RetryInterceptor(this._dio);
  final Dio _dio;
  static const _maxAttempts = 3;

  @override
  void onError(DioException err, ErrorInterceptorHandler handler) async {
    final attempt = (err.requestOptions.extra['retryAttempt'] as int?) ?? 0;
    final isRetryable = _isTransient(err) && _isIdempotent(err.requestOptions.method);

    if (!isRetryable || attempt >= _maxAttempts) return handler.next(err);

    // Full jitter, same reasoning as any distributed client: without jitter,
    // every client that failed together retries together.
    final backoffMs = (100 * (1 << attempt)).clamp(0, 2000);
    final jitterMs = Random().nextInt(backoffMs + 1);
    await Future<void>.delayed(Duration(milliseconds: jitterMs));

    err.requestOptions.extra['retryAttempt'] = attempt + 1;
    try {
      handler.resolve(await _dio.fetch(err.requestOptions));
    } catch (_) {
      handler.next(err);
    }
  }

  bool _isIdempotent(String method) => const {'GET', 'PUT', 'DELETE', 'HEAD'}.contains(method);

  bool _isTransient(DioException err) =>
      err.type == DioExceptionType.connectionTimeout ||
      err.type == DioExceptionType.receiveTimeout ||
      const {502, 503, 504, 429}.contains(err.response?.statusCode);
}
```

## `CancelToken` tied to disposal

An in-flight request whose result nobody will use anymore (the screen that
started it was popped, the bloc that started it was closed) is at minimum
wasted work, and at worst a crash if the response handler touches a disposed
`BuildContext` or emits on a closed bloc.

```dart
// WRONG — no CancelToken. Navigate away mid-request, and the response handler
// still runs later, potentially calling emit() on a closed bloc.
class SearchBloc extends Bloc<SearchEvent, SearchState> {
  SearchBloc(this._api) : super(const SearchState.initial()) {
    on<SearchQueryChanged>(_onQueryChanged);
  }
  final ApiClient _api;

  Future<void> _onQueryChanged(SearchQueryChanged event, Emitter<SearchState> emit) async {
    final results = await _api.search(event.query);
    emit(SearchState.loaded(results));   // may run after close()
  }
}

// RIGHT — CancelToken cancelled in close(); the bloc also guards emit with
// isClosed as defense in depth.
class SearchBloc extends Bloc<SearchEvent, SearchState> {
  SearchBloc(this._api) : super(const SearchState.initial()) {
    on<SearchQueryChanged>(_onQueryChanged, transformer: restartable());
  }
  final ApiClient _api;
  final _cancelToken = CancelToken();

  Future<void> _onQueryChanged(SearchQueryChanged event, Emitter<SearchState> emit) async {
    try {
      final results = await _api.search(event.query, cancelToken: _cancelToken);
      if (!isClosed) emit(SearchState.loaded(results));
    } on DioException catch (e) {
      if (e.type == DioExceptionType.cancel) return;   // expected on dispose — not an error
      if (!isClosed) emit(SearchState.error(e.toString()));
    }
  }

  @override
  Future<void> close() {
    _cancelToken.cancel();
    return super.close();
  }
}
```

Using `restartable()` here (see `frameworks.md` for the event-transformer
table) means a new keystroke also cancels the previous in-flight search at the
bloc level; the `CancelToken` additionally ensures the underlying HTTP request
is aborted, not just its result ignored, freeing the connection immediately
instead of waiting for a response that will be discarded.

## Error mapping: never leak `DioException` into the UI

```dart
// domain/failures.dart — what the rest of the app is allowed to know about
sealed class Failure {
  const Failure(this.message);
  final String message;
}

class NetworkFailure extends Failure {
  const NetworkFailure() : super('Check your connection and try again.');
}

class UnauthorizedFailure extends Failure {
  const UnauthorizedFailure() : super('Session expired. Please log in again.');
}

class ServerFailure extends Failure {
  const ServerFailure(super.message);
}

// data/repositories mapping boundary — the ONLY place that touches DioException
Failure _mapError(DioException e) => switch (e.type) {
  DioExceptionType.connectionTimeout ||
  DioExceptionType.receiveTimeout ||
  DioExceptionType.connectionError => const NetworkFailure(),
  DioExceptionType.badResponse when e.response?.statusCode == 401 => const UnauthorizedFailure(),
  DioExceptionType.badResponse => ServerFailure('Server error: ${e.response?.statusCode}'),
  _ => ServerFailure(e.message ?? 'Unknown error'),
};
```

A bloc catches `DioException` at the repository boundary and emits a `Failure`
into its freezed state union (see `state-architecture.md`) — a widget should
never need to know what `DioExceptionType.connectionError` means, and should
never import `package:dio/dio.dart` at all.

## JSON off the main isolate

Parsing is usually fine inline for small payloads, but a large list response
(hundreds of KB of JSON, thousands of list items each running through a
generated `fromJson`) can single-handedly blow the frame budget (see
`performance.md`) while it runs. Use `compute()` for the decode-and-map step:

```dart
List<Product> _parseProducts(String body) =>
    (jsonDecode(body) as List).map((e) => ProductDto.fromJson(e as Map<String, dynamic>).toEntity()).toList();

Future<List<Product>> fetchProducts() async {
  final response = await _dio.get<String>(
    '/products',
    options: Options(responseType: ResponseType.plain),   // get raw string, decode ourselves off-thread
  );
  return compute(_parseProducts, response.data!);
}
```

## Certificate pinning

For apps handling sensitive data, pin the server certificate (or its public
key) to prevent MITM even with a compromised or malicious root CA on-device
(rooted devices, corporate MITM proxies, malware-installed CAs):

```dart
(dio.httpClientAdapter as IOHttpClientAdapter).createHttpClient = () {
  final client = HttpClient(context: SecurityContext(withTrustedRoots: false));
  client.badCertificateCallback = (cert, host, port) {
    final expectedSha256 = 'AB:CD:...';   // the pinned cert's SHA-256 fingerprint
    return _sha256Fingerprint(cert) == expectedSha256;
  };
  return client;
};
```

Pin at least two certificates (current + next, rotated in advance) so a
scheduled certificate rotation doesn't lock out every installed copy of the
app the day it happens — this has bricked apps in production before.

## Offline handling

- **Check connectivity before firing, don't rely on the failure alone** —
  `connectivity_plus` gives you a fast "no network" signal so you can show
  "You're offline" immediately rather than waiting out a full timeout.
- **Cache-then-network** for read paths that should work offline: return the
  last cached response immediately, then fire the network request and update
  if it succeeds. Store the cache in `drift`/`sqflite` (see
  `platform-integration.md`), not `shared_preferences` — this is exactly the
  structured, queryable data those exist for.
- **Queue writes for retry** rather than dropping them on failure: a "mark
  challan paid" action attempted mid-tunnel should be persisted locally and
  retried on reconnect, not silently lost.

## Checklist

- [ ] `Dio` instance constructed once and injected, not per call
- [ ] `connectTimeout`/`receiveTimeout`/`sendTimeout` all set explicitly
- [ ] Auth-refresh interceptor uses single-flight (`??=`-guarded `Future`), not
      a naive "refresh on every 401"
- [ ] Retries limited to idempotent methods + transient failures, capped,
      jittered, single-layer
- [ ] Every long-lived request tied to a `CancelToken` cancelled in
      `close()`/`dispose()`
- [ ] `DioException` mapped to domain `Failure` types at the repository
      boundary; no `dio` import above `data/`
- [ ] Large JSON payloads decoded via `compute()`, not inline on the UI isolate
- [ ] Certificate pinning in place for apps handling sensitive data, with at
      least two pinned certs for rotation safety
- [ ] Offline reads use cache-then-network; offline writes are queued, not dropped
