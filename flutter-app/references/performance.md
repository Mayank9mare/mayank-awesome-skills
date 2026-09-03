# Performance: Frames, Rebuilds, Memory

Flutter's performance problems have a small number of root causes wearing
different costumes: something ran on the UI thread that shouldn't have,
something rebuilt that didn't need to, or something was never disposed. This
file is about recognizing which one you're looking at and fixing that, not
about micro-optimizing widgets that were never the bottleneck.

## The frame budget

| Refresh rate | Budget per frame |
|---|---|
| 60 Hz | 16.7 ms |
| 90 Hz | 11.1 ms |
| 120 Hz | 8.3 ms |

Miss the budget and you drop a frame — visible as jank, not as a crash, which
is exactly why it's easy to ship unnoticed until a user on a 120Hz device
complains. Two threads matter here: the **UI thread** (builds widgets, runs
your Dart code, constructs the layer tree) and the **raster thread** (turns
that layer tree into pixels via the GPU). A slow `build()` blocks the UI
thread; an expensive `shouldRepaint` or a huge stack of `Opacity`/`ClipPath`
blocks the raster thread. DevTools' performance overlay shows both as separate
bars — learn to read which one is red before "fixing" the wrong one.

## Impeller vs Skia

Impeller is Flutter's newer rendering backend, built to eliminate the
shader-compilation jank that Skia's runtime-shader model causes (see below).
As of Flutter 3.44, Impeller is the default on iOS and its Android migration
is being completed — most Android devices now render through Impeller too,
with Skia remaining as a fallback path for edge cases. Practically: if you're
still targeting an older Flutter version, check which renderer is active on
your minimum-supported Android API level, because some Skia-specific
workarounds (asset-based shader warm-up in particular) become unnecessary or
even counterproductive once Impeller is active.

## DevTools: know which thread is red

- **Performance overlay** (`P` in the DevTools flutter inspector, or the
  in-app overlay) shows two graphs: UI and raster. A tall bar past the 16ms
  line on the *UI* graph means your `build()`/`didChangeDependencies`/state
  logic is too slow. A tall bar on the *raster* graph means what you're
  drawing is too complex for the GPU regardless of how fast Dart ran.
- **Timeline view** in DevTools breaks a frame into named spans
  (`Widget.build`, layout, paint) — use it to find *which widget's* `build()`
  is slow, not just that build overall is slow.
- **Track widget rebuilds** (DevTools' "Track widget builds" toggle) to see
  rebuild counts per widget per frame — this is how you catch a widget
  rebuilding 60 times a second when its underlying state changed once.

## `const` constructors, again

Covered in `language-runtime.md` for the rendering-tree mechanics; the
performance framing is simpler: a `const` widget is a compile-time constant
Flutter can skip diffing entirely on rebuild. Sprinkling `const` on every
widget that qualifies is close to free and adds up across a large tree —
enable the `prefer_const_constructors` and `prefer_const_literals_to_create_immutables`
lints and let the analyzer flag the ones you missed.

## Lists: `ListView.builder`, not `ListView(children: …)`

```dart
// WRONG — builds and lays out every item up front, even the 9,970 that are
// off-screen. Startup cost scales with total item count, not visible count.
ListView(
  children: products.map((p) => ProductTile(product: p)).toList(),
)

// RIGHT — builds items lazily as they scroll into view.
ListView.builder(
  itemCount: products.length,
  itemBuilder: (context, index) => ProductTile(product: products[index]),
)
```

If every item has the same fixed height, set `itemExtent` — it lets
`ListView` compute scroll offsets and the scrollbar without measuring every
item, which is both a layout-cost win and what makes `jumpTo`/`scrollToIndex`
on far-away indices cheap.

## `RepaintBoundary` and `AutomaticKeepAlive`

`RepaintBoundary` isolates a subtree into its own composited layer so a
repaint elsewhere in the tree doesn't force this subtree to re-rasterize.
Wrap widgets that repaint frequently (an animated indicator) next to widgets
that are expensive to rasterize but visually static (a complex static chart)
— without the boundary, the animation's repaint drags the static chart along
with it every frame.

```dart
Column(
  children: [
    const RepaintBoundary(child: ExpensiveStaticChart()),
    const PulsingLoadingIndicator(),   // animates every frame; isolated by the boundary above
  ],
)
```

`AutomaticKeepAliveClientMixin` (via `AutomaticKeepAlive`, which `ListView`
already wraps items in by default) keeps an off-screen list item's state
alive instead of disposing it when scrolled out of the viewport and
reconstructing it when scrolled back in. Use it deliberately for something
like a `TabBarView` page holding form input the user shouldn't lose by
switching tabs — not by default on every list item, since it defeats the
memory benefit `ListView.builder` was giving you.

## Scoping rebuilds

The widget-level version of the bloc-level techniques from
`state-architecture.md`: the smaller the widget that rebuilds, the cheaper
the frame.

- `BlocSelector`/`context.select` — rebuild only when a derived value changes,
  not the whole state object (see `state-architecture.md` for the `CartState`
  example).
- `ValueListenableBuilder` around a single `ValueNotifier` for state that's
  local to one widget and doesn't need a full bloc.
- **Split large widgets.** A 300-line `build()` method rebuilds top-to-bottom
  on every state change. Extract the parts that don't depend on the changing
  state into their own `const` or separately-listened widgets so a change to
  one field doesn't force layout/paint on unrelated siblings.

## Images: decode size vs display size

The single most common cause of unexplained memory bloat in a Flutter app:
decoding a full-resolution image (a 4000×3000 camera photo) to display it in
a 100×100 thumbnail. Flutter decodes to the *decode* size you ask for, not the
display size, unless you tell it otherwise.

```dart
// WRONG — decodes the full 4000x3000 source image into memory just to shrink
// it visually to 100x100. The decoded bitmap (~48MB at 4 bytes/pixel) sits in
// the image cache at full size regardless of the rendered size.
Image.network(url, width: 100, height: 100)

// RIGHT — decode at (approximately) the size it will actually render at,
// accounting for device pixel ratio.
Image.network(
  url,
  width: 100,
  height: 100,
  cacheWidth: (100 * MediaQuery.of(context).devicePixelRatio).round(),
  cacheHeight: (100 * MediaQuery.of(context).devicePixelRatio).round(),
)
```

For images you know you'll need shortly (the next carousel page, an
about-to-be-visible avatar), `precacheImage(imageProvider, context)` warms the
image cache ahead of the frame that needs it, trading a slightly earlier
decode for a jank-free reveal.

## Shader compilation jank

On first use, a novel visual effect (a new gradient, blur, clip shape) not
seen before in this run triggers a shader compile — this can take tens of
milliseconds and shows up as a stutter the *first* time an animation or effect
plays, even though it's smooth on every subsequent play. This is largely an
Impeller-solved problem going forward (Impeller precompiles its shader set
ahead of time rather than compiling novel ones at runtime), but for
Skia-rendered targets or when you see a one-time stutter on an otherwise-fixed
frame, generate a **Skia Shader Warm-Up** (`flutter build … --bundle-sksl-path`)
from a representative run and ship it bundled so those shaders are precompiled
before the user ever hits them.

## App size

```
flutter build apk --split-per-abi --obfuscate --split-debug-info=build/symbols
flutter build appbundle --obfuscate --split-debug-info=build/symbols
```

- `--split-per-abi` / app bundles avoid shipping every CPU architecture's
  native code to every device.
- **Deferred components** (Android) let you split rarely-used features (a PDF
  viewer, a rarely-opened settings sub-screen) out of the initial install and
  fetch them on demand.
- **Icon tree-shaking** is on by default for `IconData` from `Icons`/`CupertinoIcons`
  when used as `const` — it strips unused glyphs from the bundled font. It
  breaks silently if you construct `IconData` dynamically (e.g., from a string
  lookup); keep icon references `const` and statically analyzable.
- `--obfuscate` shrinks and protects Dart code; see `packaging-deploy.md` for
  the symbol-upload step this requires to keep crash reports readable.

## Startup time

Cold start is bounded by what runs before the first frame: keep `main()` and
the widget tree above the first meaningful paint free of network calls,
heavy disk reads, or synchronous JSON parsing of large config blobs. Defer
that work to run *after* the first frame (`WidgetsBinding.instance.addPostFrameCallback`,
or simply awaiting it inside a loading state your first screen already
renders) rather than blocking the splash-to-content transition on it.

## Memory leaks: the #1 Flutter leak

Undisposed controllers, streams, and listeners. Every `AnimationController`,
`TextEditingController`, `ScrollController`, `StreamSubscription`, and
`FocusNode` you create holds resources (and, for streams, keeps the
subscriber's closure — and everything it captures — alive) until explicitly
disposed.

```dart
// WRONG — controller created in initState, never disposed. The widget's
// State object (and everything the closures inside it captured) is retained
// even after the widget is removed from the tree.
class SearchField extends StatefulWidget {
  const SearchField({super.key});
  @override
  State<SearchField> createState() => _SearchFieldState();
}

class _SearchFieldState extends State<SearchField> {
  final _controller = TextEditingController();
  StreamSubscription<ConnectivityResult>? _sub;

  @override
  void initState() {
    super.initState();
    _sub = Connectivity().onConnectivityChanged.listen((_) {});
  }

  @override
  Widget build(BuildContext context) => TextField(controller: _controller);
}

// RIGHT — every resource created has a matching dispose() call.
class _SearchFieldState extends State<SearchField> {
  final _controller = TextEditingController();
  StreamSubscription<ConnectivityResult>? _sub;

  @override
  void initState() {
    super.initState();
    _sub = Connectivity().onConnectivityChanged.listen((_) {});
  }

  @override
  void dispose() {
    _controller.dispose();
    _sub?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => TextField(controller: _controller);
}
```

The same discipline applies to blocs/cubits (`close()`, usually handled for
you by `BlocProvider` but not for a bloc you constructed manually) and to the
`CancelToken` pattern in `networking.md`. Use DevTools' memory view and take
two heap snapshots before/after navigating to and away from a screen several
times — if retained object counts for that screen's types climb each cycle
instead of returning to baseline, something isn't being disposed.

## Checklist

- [ ] Checked which thread (UI vs raster) is actually over budget before
      optimizing
- [ ] `const` constructors used wherever the analyzer's `prefer_const_*` lints allow
- [ ] Long/dynamic lists use `ListView.builder` (or `.separated`), not
      `ListView(children: …)`; fixed-height items set `itemExtent`
- [ ] `RepaintBoundary` isolates frequently-animating widgets from expensive
      static siblings
- [ ] Rebuilds scoped with `BlocSelector`/`context.select`/`ValueListenableBuilder`
      rather than rebuilding whole subtrees
- [ ] Images decoded at display size via `cacheWidth`/`cacheHeight`, not full
      source resolution
- [ ] Shader warm-up bundled for Skia targets if first-play stutter is observed
- [ ] App-size flags (`--split-per-abi`, `--obfuscate` + `--split-debug-info`,
      deferred components) applied to release builds
- [ ] Every controller/stream subscription/listener created has a matching
      `dispose()`/`cancel()`, verified with a before/after heap snapshot
