---
name: brace-for-compact
description: Save what this session knows to .claude/brace-state.md before the context is compacted or cleared, and resume from it afterwards. Writes the file first (compaction can cut a reply off mid-way), records only what isn't already saved, and keeps it short. Use when the user runs /brace-for-compact, says they're about to compact or clear, that context is nearly full, "save state", "checkpoint this session", or asks to resume after a compaction ("/brace-for-compact resume", "where were we?").
argument-hint: "[resume | checkpoint | close]"
user-invocable: true
---

# Brace for Compact

Compaction keeps a lossy summary and drops detail. The details most likely to vanish are exactly the
ones a future session needs: the precise goal, the decision made an hour ago and *why*, the approach
that already failed, the question still waiting on the user, the half-finished step.

This skill moves those onto disk, in `.claude/brace-state.md` at the project root, so they survive
compaction, `/clear` and new sessions. The global hooks (see "Hooks" below) put the file back into
context automatically after a compaction, `/clear` or resume.

Claude can't compact the session itself, and a hook can't make Claude write anything during
compaction (the model doesn't run then). So the save is a command: run it **before** compacting,
and at milestones during long work.

## Modes

| Invocation | What it does |
|---|---|
| `/brace-for-compact` | **Save.** Sweep the session, write the state file, then report. |
| `/brace-for-compact checkpoint` | **Save mid-session.** Same, but only what changed since the last save; the session continues. |
| `/brace-for-compact resume` | **Resume.** Read the file, verify it against reality, and pick up. |
| `/brace-for-compact close` | **Close.** The work is done: mark the file CLOSED so no future session resumes a finished thread. |

## Save

**Order matters: files first, chat text last.** Compaction often fires while a reply is still being
written; anything only in the chat is lost, and anything already on disk survives.

### 1. Stub first
The project root is `${CLAUDE_PROJECT_DIR}` (otherwise the git root, otherwise the working
directory). Create `.claude/` if needed. Write a one-line stub to `.claude/brace-state.md`:
`BRACE · <goal in a few words> · <YYYY-MM-DD HH:MM> · SAVING`. If a previous state file exists,
read it first: you're updating it, not starting over.

### 2. Sweep for what isn't saved anywhere
Look through the session (or, for `checkpoint`, only since the last save) for:
- **The goal** and what "done" means.
- **Where things stand**: what's finished, what's half-done, what's verified (tests passing, build green).
- **Decisions and reversals**, with the reason. "Went with X because Y" survives; "use X" alone gets
  second-guessed.
- **Tried and failed**: approaches that didn't work and why, so nobody repeats them.
- **Open questions** still waiting on the user: what's pending and what unblocks it. These are the
  easiest to lose.
- **User preferences and corrections** given this session ("don't push without asking", "keep my
  notes' system only").
- **Exact facts a summary would blur**: file paths, commands, URLs, IDs, versions, error messages.
- **The next 3 steps.**

Skip what's already durable: things in the code, committed docs, a plan file, or memory. Point to
those by path instead. Keep the sweep to about 10 tool calls; if you're not done, save what you have
and say the sweep was partial.

### 3. Route anything permanent elsewhere
- A fact about the user or how they like to work, which matters beyond this task → memory (if this
  setup has a memory system; update an existing entry rather than duplicating it).
- A durable project decision → the project's own docs (plan, decisions log, README), and fix any
  file that now contradicts it.
- Everything about *this task's* state → `brace-state.md`.

### 4. Write the state file
Overwrite the stub with this structure. Leave out sections that don't apply. Aim for under 150 lines;
it's a handoff, not a transcript.

```markdown
BRACE · <the task in one line> · <YYYY-MM-DD HH:MM> · OPEN

## Goal
<what we're doing and why> · Done when: <the definition of done>

## Where we are
<done / in progress / blocked, in 2–5 lines; what's verified>

## Read first
- <path> — <what it holds, why it matters>

## Decisions
- <decision> — because <reason> (<when, if it matters>)

## Tried and failed
- <approach> — <why it failed>

## Open questions (waiting on the user)
- <question> — unblocks <what>

## User preferences this session
- <preference or correction>

## How to run / test
<exact commands>

## Next
1. <the immediate next action>
2. …
3. …
```

### 5. Report, last
In chat, briefly:
- **Saved:** what went into the state file (and anything routed to memory or docs, with paths).
- **Left out on purpose:** one line (already durable, or not needed).
- "Safe to `/compact` now." If nothing new needed saving, say exactly that; a clean sweep is a real
  result.

## Resume

1. Read `.claude/brace-state.md`. If it's missing, say so and fall back to the conversation summary
   and git history.
2. If the first line says **CLOSED**, the thread is finished: say so and ask what's next.
3. **Verify, don't trust**: check `git status` / `git log -5`, open the "Read first" files, and run
   the "How to run / test" check if it's quick. The file may be stale if work continued after the
   last save (the header shows when it was written; the hook also says how old it is).
4. Tell the user in 3–5 lines: the goal, where it stands, anything that no longer matches the file,
   open questions still waiting on them, and the next step you'll take. Then continue (or wait, if
   an open question blocks the next step).
5. Update the file's "Where we are" as soon as real progress is made.

## Close
Rewrite the first line as `BRACE · <task> · <date> · CLOSED: <one-line outcome>` and keep the rest
for the record. The hooks stop injecting a CLOSED file.

## Keeping it fresh
During long work, save a `checkpoint` at natural milestones (a feature passes its tests, a decision
is made, before a risky change) and whenever the context is clearly getting full. A state file
saved early is far better than a perfect one that never gets written.

## Hooks (installed globally in ~/.claude/settings.json)
- **SessionStart** (`compact`, `clear`, `resume`, `startup`): `hooks/session_start.py` injects the
  state file if it exists and isn't CLOSED, with its age. On a fresh startup it only mentions that an
  open state file exists, so Claude can ask whether to resume.
- **PreCompact** (`manual`, `auto`): `hooks/pre_compact.py` copies the full transcript to
  `.claude/brace-transcripts/` (keeping the last 5) as a safety net, and tells the user whether the
  state file is fresh or more than 20 minutes old. It never blocks compaction. (PreCompact hooks
  can't add context to the summary; that's what the SessionStart restore is for.)
- `.claude/brace-*` is in the global git ignore file (`~/.config/git/ignore`), so these files are
  never committed by accident.

To install on another machine: link this folder into `~/.claude/skills/brace-for-compact`, add the two
hook entries from `hooks/settings-snippet.json` to `~/.claude/settings.json`, add `.claude/brace-*` to
`~/.config/git/ignore`, and add the line from `hooks/claude-md-line.md` to `~/.claude/CLAUDE.md`.

---
Ideas adapted with thanks from [save-before-compact](https://github.com/LippInc/save-before-compact)
(MIT): write the stub first, files before chat text, save only what isn't durable, and the CLOSED
marker.
