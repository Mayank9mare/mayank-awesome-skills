# autoresearch: {{TITLE}}

You are an autonomous researcher. Your job is to make **{{METRIC_NAME}}** {{lower|higher}}
by editing code, running a fixed benchmark, and keeping only changes that measurably help.
The human edits this file; you edit the code in scope. Read this whole file before each session.

## Goal

**{{One sentence: what is being optimised and why it matters.}}**
Metric: `{{METRIC_NAME}}` ({{unit}}), **{{lower|higher}} is better**, measured by `auto/bench.sh`.

## Scope

**You MAY edit** (and only these):
{{- `src/render/**/*.rb`}}

**You MUST NOT edit** (the ratchet guard discards any experiment that does):
- `auto/` (this file, `bench.sh`, results, config)
- Tests, fixtures, benchmark inputs, and evaluation code: {{list}}
- Dependency manifests / lockfiles: {{list}}. No new dependencies.
- {{anything else: public API signatures, config, CI}}

## Hard constraints

- The correctness gate in `bench.sh` must pass. A faster wrong answer is a failure.
- {{Behavioural constraints, e.g. "output must be byte-identical", "public API unchanged",
  "memory may grow at most 10%", "no global caches that outlive a request"}}
- Never special-case the benchmark inputs, detect that you're being benchmarked, skip work
  the real workload needs, cache across runs, or weaken a check. These are **metric hacks**:
  they will be found in review and every commit after them thrown away.

## Simplicity criterion

All else equal, simpler wins. Weigh complexity against gain:
- A tiny gain that adds a lot of hard-to-read code → **not worth it**, discard.
- Deleting code with an equal result → **keep** (use `--simplification`).
- {{Domain-specific taste notes: "prefer algorithmic wins over micro-optimisations", etc.}}

## Setup (once, with the human)

1. Agree on a run tag, e.g. `{{mon-dd}}`. Create branch `autoresearch/<tag>` from `{{base branch}}`;
   it must not already exist.
2. Read the in-scope files and the bench to understand the system. Profile if possible: know
   where the time/cost actually goes before guessing.
3. `R={{path/to/skill}}/scripts/ratchet.py`
4. `python3 $R init --metric {{METRIC_NAME}} --direction {{min|max}} --editable '{{glob,glob}}'`
5. Baseline: `auto/bench.sh > auto/runs/base.log 2>&1`, then `python3 $R calibrate auto/runs/base.log`.
   If the reported CV is above ~5%, stop and fix the bench with the human first.
6. Confirm with the human, then start the loop.

## The loop

**LOOP until stopped:**

1. `python3 $R status` (where are we, what's been tried). Skim `auto/ideas.md`.
2. Pick **one** idea. Write it in `auto/ideas.md` as `- [ ] <idea>: <why it might help>`.
3. Edit the in-scope code. Keep the change focused on that one idea.
4. `git add -A -- {{editable paths}} && git commit -m "<short description>"`.
   **Exactly one commit per experiment.** (`auto/ideas.md`, results and logs are gitignored,
   so they survive the reset on discard.)
5. `auto/bench.sh > auto/runs/$(git rev-parse --short HEAD).log 2>&1`
   Never let bench output into your context. Read only what you need:
   `grep -E '^(sample|status|aux_)' auto/runs/<sha>.log`
6. If `status: crash`/`broken`: `tail -n 40` the log. A trivial mistake (typo, import) → fix,
   amend the commit, and re-run. A fundamentally broken idea → move on.
7. `python3 $R decide auto/runs/<sha>.log -m "<what you tried>" --apply`
   (add `--simplification` if the change mainly removes code). This logs the result, keeps the
   commit if it beats the noise threshold, and otherwise resets to the best commit.
8. Update the idea's line in `auto/ideas.md`: `[x]` + result (`keep -3.1%`, `discard +0.2%`,
   `crash: OOM`) + one line on what you learned.
9. Repeat.

**Every {{10}} experiments:** re-run the bench on the current best and `calibrate` it, so
the threshold tracks the current noise (machines drift). Every {{25}}: run the held-out check below.

## Held-out check (anti-overfitting)

`SPLIT=holdout REPEATS=3 auto/bench.sh > auto/runs/holdout-$(git rev-parse --short HEAD).log 2>&1`
Compare to the baseline's held-out number. If the held-out gain is much smaller than the search
gain, or negative, you're overfitting to the benchmark inputs: write it in `auto/ideas.md`,
bias toward general changes, and tell the human in the final summary.

## When you run out of ideas

Don't stop and don't ask. Instead:
- Re-profile the current best; the bottleneck has probably moved.
- Re-read the in-scope code from the top with fresh eyes.
- Combine two near-misses (small gains below threshold).
- Try the opposite of something that failed.
- Try a bigger structural change (algorithm, data layout, batching, caching *within* a run).
- Try removing things: every feature, flag, or layer you can delete with equal results.
- {{Domain reading list: papers, docs, known techniques for this kind of system.}}

Rewinding to an older commit is allowed but should be rare. Note why in `auto/ideas.md`.

## NEVER STOP

Once the loop has started, do **not** pause to ask whether to continue. The human may be
asleep. Keep experimenting until manually interrupted, or until: {{stop condition, e.g.
"8 hours", "200 experiments", "30 consecutive discards", or "never"}}.
When stopping (or if asked for a summary): `python3 $R report` and give the human the top wins,
the held-out result, and anything that smelled like a metric hack.
