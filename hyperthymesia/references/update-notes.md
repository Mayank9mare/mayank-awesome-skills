# Add to My Notes

How new personal notes get into the system. [notes.md](notes.md) is the single source of truth;
everything else (the skill references, the drill script, the workbook) follows it. Nothing that's
already there is removed without the owner's explicit yes.

Triggers: "add this to my notes", a photo of new notebook pages, "I learned another technique",
"change my picture for 47", "update my notes".

## 1. Capture

- **Text**: take it as given.
- **Photos** (HEIC/JPG): convert and read them (`sips -s format jpeg -Z 1600 in.HEIC --out out.jpg`).
  Transcribe faithfully: the owner's words, order and examples.
- **Unreadable or ambiguous words**: list them all in one message and ask. Never guess
  (see the notebook rule in SKILL.md).

## 2. Classify each new note

| Kind | Example | Where it goes in notes.md |
|---|---|---|
| New or changed picture | "47 is now *root*" · "J♣ is a boxer" | The numbers or card table, marked ✔ |
| New technique or rule | "Brown's method for languages…" | A new `##` section, in the book's order |
| New example or clarification | another long-number story | Under the technique it belongs to |
| A decision | "always use the second word" | The decisions log |

Every change also gets a decisions-log row with the date.

## 3. Find conflicts before writing anything final

Run the automatic check on the updated notes:

```bash
python3 scripts/memgym.py notes-check     # exit 1 = conflicts
```

It reports: a word that decodes to the wrong number, a card word that doesn't match suit + rank,
a number given two different pictures, and the same picture used for two things.

Then check by reading, for what a script can't see:
- **Method conflicts**: does the new note teach something that contradicts an existing note (a
  different number code, a different order for walking palaces), or **do the same job** as an
  existing method (a second peg list, another palace variant)? Apply the notebook rule.
- **Skill drift**: search the skill and the workbook for the old value or method
  (`grep -rn "<old word>" references/ SKILL.md docs/build/template.html`).

## 4. Ask before removing anything

Present every conflict in one message, each with a recommendation, then **wait**:

> Your new note says 47 = **rat**, but notes.md has 47 = **root / rat** and your 00–99 drill uses
> *root*.
> 1. Make 47 just **rat** and remove *root*? (recommended: one picture per number)
> 2. The new note teaches a second peg list (1 = pencil …). It does the same job as your rhyme
>    pegs. Remove it, or keep it and drop the rhyme pegs?
>
> Which are safe to remove?

- Remove only what the owner approves. If they say keep both, keep both and log that choice.
- Never silently overwrite an existing ✔ decision.

## 5. Propagate

After the notes are final:

1. **notes.md**: write the changes, and add decisions-log rows for every approval and removal.
2. **`notes-check`** must pass (or every remaining conflict must be an approved, logged exception;
   add card exceptions to the "Exceptions (allowed to break the code)" line).
3. **Skill references**: update any reference that teaches the changed method (brown-system.md,
   advanced-systems.md, boosters.md, remember-with-me.md, SKILL.md). Numbers and cards are *not*
   copied into references; they're read from notes.md.
4. **Workbook**, if the change shows on the page:
   - Numbers and cards: just rebuild, since `docs/build/build.py` reads notes.md.
   - Teaching text: edit `docs/build/template.html`, then rebuild.
   - A diagram: edit `docs/build/specs.py` (Excalidraw) or `docs/diagrams/*.mmd` (Mermaid), re-render
     (see docs/README.md), then rebuild.
   - `python3 docs/build/build.py`, then republish to the same artifact link (it's in the repo
     README) with the Artifact tool's `url`, so the link stays the same.
5. **The learner's vault**: if a picture they use in an existing palace changed, tell them which
   vault entries now use an old picture and offer to update them. Don't change their palaces
   silently.
6. **Commit** with a message naming what changed and what was removed.

## 6. Report back

A short summary: what was added, what was changed, what was removed (with their approval), what
still awaits an answer, and the workbook link if it was republished.
