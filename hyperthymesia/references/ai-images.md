# AI Images for Memory Pictures

Turn the pictures in a memory plan into actual images with Google's **Nano Banana** (Gemini image
models) or **ChatGPT's** image models, using `scripts/imagine.py`. This is a tool for the
notebook's methods, not a new method: the picture is still built by the notebook's rules.

## Imagine first, then generate

A picture you build in your own head sticks better than one you're shown (the generation effect;
it's why the notebook says to make your own images). So the order matters:

1. **Build the picture in your head first**, with Remember with me.
2. **Then generate the image** as a review aid: look at it, close your eyes, see it at its place.
3. If the AI image differs from your mental picture, **keep your mental picture**. The image is a
   prompt for recall, not a replacement.

When AI images help most:
- **People who can't visualise** (aphantasia), or who find it hard. A real image gives them
  something concrete to anchor.
- **Reviewing a palace quickly**: the gallery is a walk-through of the whole palace.
- **Teaching beginners**, who often make pictures that are too tame. A generated image shows
  what "vivid, interacting, absurd" looks like.

## Two routes

### Free: the apps (no API key)
```bash
python3 scripts/imagine.py prompts ~/.hyperthymesia/vault/<topic>.md        # all rows
python3 scripts/imagine.py prompts ~/.hyperthymesia/vault/<topic>.md --rows 1,4-6
```
This writes `<topic>-prompts.md` next to the vault file, with one copy-paste prompt per picture.
Paste each into the **Gemini app** (Nano Banana) or **ChatGPT**, which are free within their daily
limits, save the image, and link it:
```bash
python3 scripts/imagine.py attach ~/.hyperthymesia/vault/<topic>.md 3 ~/Downloads/earth.png
```

### Automatic: the APIs (paid, needs a key)
```bash
export GEMINI_API_KEY=...     # Google AI Studio key, for Nano Banana
export OPENAI_API_KEY=...     # for ChatGPT's image models
python3 scripts/imagine.py generate ~/.hyperthymesia/vault/<topic>.md --provider gemini
python3 scripts/imagine.py generate ~/.hyperthymesia/vault/<topic>.md --provider openai --quality low
python3 scripts/imagine.py generate … --dry-run        # show the requests, send nothing
python3 scripts/imagine.py one "Goofy juggles 95 tiny moons" --provider gemini
```

Defaults are Nano Banana 2.1 (`gemini-nano-banana-2.1`) and GPT Image 2.5 Flare
(`gpt-image-2.5-flare`). Override with `--model`, or `HYPERTHYMESIA_GEMINI_MODEL` /
`HYPERTHYMESIA_OPENAI_MODEL`, since model names change often. Rough cost (October 2026): Nano
Banana 2.1 about $0.03 per image; GPT Image from under $0.01 (low quality) to about $0.20 (high).
A 20-locus palace costs well under a dollar on the cheaper settings.

## What you get

- Images in `~/.hyperthymesia/images/<topic>/`, named `NN-item.png` by locus number (one per row).
- `index.html` there: a **palace walk gallery** in route order, each image with its locus, item
  and picture.
- An **Image** column in the vault table, linking each row's image.

## The prompt

Every prompt uses the same style, so a palace looks like one world:

> One vivid, exaggerated, surreal cartoon illustration for a memory palace. Bright saturated
> colours, strong motion, the action happening right now, a clear main subject filling the frame,
> slightly absurd scale. No text, no letters, no numbers, no captions, no speech bubbles.
> Scene: *the row's picture*. It happens at *the locus* in *the palace*.

"No text" matters: image models love to write the word in the picture, which turns a memory
picture back into reading.

## Limits and care

- **Crude or violent pictures get refused.** Several notebook pictures are deliberately crude
  (Brown's advice), and image models will block some of them. The script reports the refusal and
  carries on. For the *image*, describe a milder version; keep the original in your head.
- **Real people.** Pictures that use friends' faces or names don't belong in an image prompt:
  prompts go to Google or OpenAI. Use a generic character and keep the real person in your head.
- **Keys** come from environment variables only; the script never writes them to a file.
- **Whose picture it is doesn't change.** Generating an image for a "yours" row doesn't make the
  picture Claude's. The image only illustrates it.
