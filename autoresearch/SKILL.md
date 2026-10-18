---
name: autoresearch
description: Set up and run a Karpathy-style autoresearch loop on any repo. An agent repeatedly edits code in a fixed scope, runs a frozen benchmark, and keeps a commit only if the metric beats measured noise, otherwise resets. It runs unattended (overnight) with noise calibration, a scope guard, a correctness gate, held-out checks against overfitting, a results log, and a morning report. Works for ML training loss, latency/throughput, build or test time, bundle size, query speed, GPU kernels, prompt pass rates: anything scored by one number from a script. Use when the user says "autoresearch", "optimise X overnight", "let the agent experiment", "hill-climb this metric", "run experiments while I sleep", or wants to resume or report on an autoresearch run.
user-invocable: true
---

# Autoresearch

Karpathy's [autoresearch](https://github.com/karpathy/autoresearch) is a loop:

```
edit code (one idea) → commit → run frozen benchmark (fixed budget) → better? keep : git reset → repeat forever
```

The human doesn't write the code. They write **`program.md`**, the instructions for the
research org, and the agent does the experiments. On nanochat, ~700 experiments over 2 days
found ~20 improvements that all stacked and transferred to bigger models (11% faster to
GPT-2 quality). At Shopify, the same loop on the Liquid template engine gave 53% faster
rendering with 61% fewer allocations.

This skill turns that into a repeatable setup for **any repo and any metric**, adding the
guardrails the minimal original leaves to the human: noise-aware keep decisions, a scope
guard, a correctness gate, held-out checks, and a report for human review.

## Files

| File | Use |
|---|---|
| [scripts/ratchet.py](scripts/ratchet.py) | Stdlib-only helper: `init`, `calibrate`, `guard`, `decide --apply`, `status`, `report`. **Use it; don't hand-roll keep/discard logic.** |
| [templates/program.md](templates/program.md) | The agent's instructions in the target repo. Fill every `{{…}}`. |
| [templates/bench.sh](templates/bench.sh) | Frozen benchmark: build → correctness gate → N timed repeats → `sample:` lines. |
| [references/target-recipes.md](references/target-recipes.md) | Metric / scope / gate / budget settings for ML, perf, build, tests, bundle size, SQL, kernels, prompts. |
| [references/guardrails.md](references/guardrails.md) | Noise, overfitting, metric hacking, correctness, complexity creep, unattended-run safety. **Read before setup.** |
| [references/search-strategy.md](references/search-strategy.md) | Idea generation, getting unstuck, and optional parallel/evolutionary variants. |

`R=<this skill's directory>/scripts/ratchet.py` below.

## Phase 1: Design the experiment (with the user)

Settle **the five choices** (target-recipes.md has defaults per domain). Ask only what you can't
infer from the repo. Propose answers; don't make the user author them from scratch.

1. **Metric and direction.** One number from a script; lower or higher is better. Prefer stable
   proxies (instructions, allocations, bytes) over wall time when the bench is noisy.
2. **Editable scope.** As narrow as possible: one file or module is ideal. It's the main lever
   against hacks, and it keeps diffs reviewable.
3. **Frozen.** The bench, its inputs, tests, eval code, dependency manifests. List them explicitly.
4. **Correctness gate.** The fast tests that prove the scope still behaves; ideally output
   equivalence against golden outputs. *A speed metric without a gate will be gamed.*
5. **Budget per run.** Fixed time or work per experiment, so runs are comparable; aim for
   1–10 minutes. 5 min ≈ 12 experiments/hour ≈ 100 overnight.

Also agree on: **held-out inputs** (a split the loop never decides on), **constraints** (memory,
API, output format), **stop condition** (hours, experiment count, N consecutive discards, or
never), and **where it runs** (container or VM preferred for unattended runs; see guardrails.md §6).

Don't proceed until the metric is real: *can it go up while the outcome gets worse?* If yes, fix
the metric or the gate first.

## Phase 2: Scaffold `auto/` in the target repo

```
auto/
  program.md   ← from templates/program.md, every {{…}} filled      (committed)
  bench.sh     ← from templates/bench.sh, placeholders filled       (committed, chmod +x)
  .gitignore   ← runs/  results.tsv  config.json  report.md  ideas.md
  ideas.md     ← lab notebook, one line per idea + result            (untracked: survives resets)
```

1. Write the files, `chmod +x auto/bench.sh`, and run it once by hand. Check that it prints
   `sample:` lines, that the gate fails when you break the code on purpose (then revert), and
   that `TIMEOUT` works. Also gitignore bench artifacts (`__pycache__`, `dist/`, etc.).
2. Commit `auto/` on the base branch, then `git checkout -b autoresearch/<tag>` (e.g. `oct18`).
   The branch must be new.
3. `python3 $R init --metric <name> --direction <min|max> --editable '<glob>,<glob>'`
4. Baseline: `auto/bench.sh > auto/runs/base.log 2>&1 && python3 $R calibrate auto/runs/base.log`
   - Prints the median, σ, CV and the keep threshold (relative to the current best).
   - **CV > 5% → stop and make the bench quieter** (guardrails.md §1). Don't run a noisy loop.
   - Single-repeat benches (expensive ML runs): run the baseline 3 times into 3 logs and pass all three.
5. Set up permissions for unattended running: pre-approve only the loop's commands (guardrails.md
   §6), or run in a sandbox. Show the user the plan and get a go-ahead.

## Phase 3: Run the loop

Follow `auto/program.md`. Per experiment:

```bash
# 1 idea → edit in-scope files → one commit
git add -A -- <scope paths> && git commit -m "<idea>"
auto/bench.sh > auto/runs/$(git rev-parse --short HEAD).log 2>&1
grep -E '^(sample|status|aux_)' auto/runs/<sha>.log          # never cat the whole log
python3 $R decide auto/runs/<sha>.log -m "<idea>" --apply     # logs, keeps or resets
# update auto/ideas.md with the result + one line of learning
```

`decide` discards automatically when the gate fails (`broken`), the run crashes, files outside
the scope changed (`guard`), or the gain is within noise. It refuses to reset if HEAD isn't
exactly one commit past the best, so keep **one commit per experiment**. Use `--simplification`
for changes that mainly delete code: they're kept if not worse beyond noise.

Rules while looping:
- **NEVER STOP to ask whether to continue.** The user may be asleep. Run until the stop condition
  or an interrupt. Out of ideas → search-strategy.md "Stuck?".
- **Keep bench output out of context**: redirect to files and grep. All state lives on disk (git,
  `results.tsv`, `config.json`, `ideas.md`), so compaction or a restart loses nothing.
- **Re-calibrate every ~10 experiments** on the current best, and after any keep that moves the
  metric by more than 25% (`decide` prints a hint).
- **Held-out check every ~25 experiments**: `SPLIT=holdout auto/bench.sh`. A shrinking gap between
  search gain and held-out gain is fine; a held-out regression means overfitting. Note it and
  change course.
- **Crashes**: fix trivial mistakes (typo, import) by amending and re-running; otherwise log and move on.

## Phase 4: Report and hand back

When stopped, or when the user asks:

1. `python3 $R report` → `auto/report.md`: baseline → best, noise, experiment counts, a
   best-so-far sparkline, kept changes in order with Δ and LOC, the biggest wins, failures, and a
   review checklist.
2. Run the **held-out** bench and the **full test suite** on the best commit; add both to the report.
3. Re-run baseline and best back-to-back (same conditions) to confirm the gain reproduces.
4. Review every kept diff yourself for **metric hacks** (guardrails.md §3) and flag anything suspicious.
5. Tell the user, in a few lines: total gain (search vs held-out), the top 3–5 wins in plain
   words, anything suspicious, and the next step. Typical next steps: squash into one PR,
   cherry-pick the top wins, or update program.md and run again.

Never push, open PRs, or merge from the loop. That's the user's call after review.

## Resuming

`python3 $R status` and `auto/ideas.md` give the full picture. Check that you're on the
`autoresearch/<tag>` branch at the best commit (`git log -1` vs `status`), then continue the
loop. To start a fresh run on top of the results, make a new tag and branch from the best commit
and run `init --force` + `calibrate`.

## Improving `program.md`

`program.md` is the thing the human iterates on. After a run, read `ideas.md` and the report with
the user and tighten it: add constraints for hacks that were attempted, add promising directions,
narrow or widen the scope, adjust the simplicity taste. Karpathy's framing: you're programming the
research org, not the code.

## Not for

- One-off optimisation you can do in a single focused session → just do it.
- Building a new feature → `implement-feature`.
- Metrics that need human judgment with no trustworthy automated proxy.
