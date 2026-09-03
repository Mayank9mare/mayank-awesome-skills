---
name: remotion
description: >-
  Create programmatic videos using React with Remotion framework. This skill provides
  domain-specific knowledge for compositions, animations, media handling, 3D content,
  text animations, transitions, and timing patterns. This skill should be used when
  the user wants to build video generation pipelines, create dynamic video content,
  or needs guidance on Remotion-specific patterns and best practices.
---

# Remotion Video Creation

Create programmatic videos using React and Remotion. This skill provides domain-specific knowledge for building video compositions that render locally without external APIs.

## Prerequisites

Remotion requires Node.js and renders videos locally using:
- **React** for composing scenes
- **Chromium** for rendering frames
- **FFmpeg** for encoding video

Initialize a new Remotion project:
```bash
npx create-video@latest
```

## Core Concepts

### Compositions

Define renderable videos with `<Composition>` in `src/Root.tsx`:

```tsx
import { Composition } from "remotion";
import { MyVideo } from "./MyVideo";

export const RemotionRoot = () => {
  return (
    <Composition
      id="MyVideo"
      component={MyVideo}
      durationInFrames={150}
      fps={30}
      width={1920}
      height={1080}
    />
  );
};
```

### Animation Fundamentals

**All animations MUST be driven by `useCurrentFrame()`**. CSS transitions and Tailwind animation classes will not render correctly.

```tsx
import { useCurrentFrame, useVideoConfig, interpolate } from "remotion";

export const MyVideo = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const opacity = interpolate(frame, [0, 2 * fps], [0, 1], {
    extrapolateRight: "clamp",
  });

  return <div style={{ opacity }}>Hello</div>;
};
```

### Timing in Seconds

Write animations in seconds and multiply by `fps`:

```tsx
const { fps } = useVideoConfig();
const fadeInDuration = 2 * fps; // 2 seconds
```

### Spring Animations

Use `spring()` for natural motion:

```tsx
import { spring, useCurrentFrame, useVideoConfig } from "remotion";

const frame = useCurrentFrame();
const { fps } = useVideoConfig();

const scale = spring({
  frame,
  fps,
  config: { damping: 200 }, // Smooth, no bounce
});
```

Common spring configs:
- `{ damping: 200 }` — Smooth, no bounce
- `{ damping: 20, stiffness: 200 }` — Snappy, minimal bounce
- `{ damping: 8 }` — Bouncy entrance

## Media Components

### Images

Always use `<Img>` from remotion (never native `<img>`):

```tsx
import { Img, staticFile } from "remotion";

<Img src={staticFile("photo.png")} />
```

### Videos

Install `@remotion/media` first:
```bash
npx remotion add @remotion/media
```

```tsx
import { Video } from "@remotion/media";
import { staticFile } from "remotion";

<Video
  src={staticFile("video.mp4")}
  volume={0.5}
  playbackRate={1}
/>
```

### Audio

```tsx
import { Audio } from "@remotion/media";
import { staticFile } from "remotion";

<Audio
  src={staticFile("audio.mp3")}
  volume={(f) => interpolate(f, [0, 30], [0, 1], { extrapolateRight: "clamp" })}
/>
```

## Sequencing

Use `<Sequence>` to delay elements:

```tsx
import { Sequence } from "remotion";

const { fps } = useVideoConfig();

<Sequence from={1 * fps} durationInFrames={2 * fps} premountFor={1 * fps}>
  <Title />
</Sequence>
```

**Always premount sequences** to preload content before playback.

Use `<Series>` for sequential playback:

```tsx
import { Series } from "remotion";

<Series>
  <Series.Sequence durationInFrames={60}>
    <Intro />
  </Series.Sequence>
  <Series.Sequence durationInFrames={90}>
    <MainContent />
  </Series.Sequence>
</Series>
```

## Transitions

Install `@remotion/transitions`:
```bash
npx remotion add @remotion/transitions
```

```tsx
import { TransitionSeries, linearTiming } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { slide } from "@remotion/transitions/slide";

<TransitionSeries>
  <TransitionSeries.Sequence durationInFrames={60}>
    <SceneA />
  </TransitionSeries.Sequence>
  <TransitionSeries.Transition
    presentation={fade()}
    timing={linearTiming({ durationInFrames: 15 })}
  />
  <TransitionSeries.Sequence durationInFrames={60}>
    <SceneB />
  </TransitionSeries.Sequence>
</TransitionSeries>
```

Available transitions: `fade`, `slide`, `wipe`, `flip`, `clockWipe`

## 3D Content

Install `@remotion/three`:
```bash
npx remotion add @remotion/three
```

```tsx
import { ThreeCanvas } from "@remotion/three";
import { useVideoConfig, useCurrentFrame } from "remotion";

const { width, height } = useVideoConfig();
const frame = useCurrentFrame();

<ThreeCanvas width={width} height={height}>
  <ambientLight intensity={0.4} />
  <directionalLight position={[5, 5, 5]} />
  <mesh rotation={[0, frame * 0.02, 0]}>
    <boxGeometry args={[2, 2, 2]} />
    <meshStandardMaterial color="#4a9eff" />
  </mesh>
</ThreeCanvas>
```

**Important**: Never use `useFrame()` from `@react-three/fiber` — it causes flickering. Animate only with `useCurrentFrame()`.

## Fonts

Install `@remotion/google-fonts`:
```bash
npx remotion add @remotion/google-fonts
```

```tsx
import { loadFont } from "@remotion/google-fonts/Roboto";

const { fontFamily } = loadFont("normal", {
  weights: ["400", "700"],
  subsets: ["latin"],
});

<div style={{ fontFamily }}>Text</div>
```

## Rendering

Preview in Remotion Studio:
```bash
npx remotion studio
```

Render to file:
```bash
npx remotion render src/index.ts MyVideo out/video.mp4
```

## Key Rules

1. **Never use CSS transitions or animations** — they don't render
2. **Always use `<Img>` from remotion** — not native `<img>`
3. **Always premount sequences** — prevents blank frames
4. **Calculate time in frames** — multiply seconds by `fps`
5. **Clamp interpolations** — use `extrapolateRight: "clamp"`

## References

Consult these references for detailed patterns:

### Core
- `references/compositions.md` — Composition structure, stills, folders, metadata
- `references/animations.md` — Animation fundamentals
- `references/timing.md` — Interpolation, springs, easing curves
- `references/sequencing.md` — Sequence and Series patterns
- `references/trimming.md` — Trimming patterns for cutting animations
- `references/transitions.md` — Scene transitions

### Media
- `references/assets.md` — Importing images, videos, audio, fonts
- `references/videos.md` — Video embedding, trimming, volume, speed
- `references/audio.md` — Audio handling, looping, pitch
- `references/images.md` — Image component usage
- `references/gifs.md` — GIFs, APNG, AVIF, WebP animated images
- `references/lottie.md` — Lottie animation integration

### Metadata & Dynamic Compositions
- `references/calculate-metadata.md` — Dynamic duration, dimensions, props
- `references/get-video-duration.md` — Get video duration with Mediabunny
- `references/get-video-dimensions.md` — Get video dimensions with Mediabunny
- `references/get-audio-duration.md` — Get audio duration with Mediabunny
- `references/can-decode.md` — Check browser video decoding support
- `references/extract-frames.md` — Extract frames from videos

### Captions & Subtitles
- `references/display-captions.md` — TikTok-style captions with word highlighting
- `references/import-srt-captions.md` — Import SRT subtitle files
- `references/transcribe-captions.md` — Audio transcription options

### Typography & Layout
- `references/fonts.md` — Google Fonts and local fonts
- `references/text-animations.md` — Typography patterns
- `references/measuring-text.md` — Text measurement and fitting
- `references/measuring-dom-nodes.md` — DOM element measurement

### Advanced
- `references/3d.md` — Three.js integration
- `references/charts.md` — Data visualization patterns
- `references/tailwind.md` — TailwindCSS integration
