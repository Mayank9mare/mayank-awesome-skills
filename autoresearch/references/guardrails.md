# Guardrails: Keeping the Ratchet Honest

A greedy keep/discard loop running hundreds of times will find **every** weakness in your
benchmark. Karpathy's original is deliberately minimal, and most of these protections are left
to the human. Shopify's Liquid run was "probably somewhat overfit", and community runs report
reward hacking in a large share of attempts. Build the protections in before starting.

## 1. Noise: don't ratchet on luck

**Problem:** if run-to-run variance is bigger than the improvement, "lower" is a coin flip, and
the ratchet locks in lucky commits. Over 100 experiments, several lucky ones will get through.

**Defence:** `ratchet.py calibrate` measures σ from the baseline repeats and sets a keep
threshold of `max(z · 1.25 · σ · √(2/n), min_effect)`, relative to the current best. Defaults:
z = 2.5, min_effect = 0.2%.

**Make the bench quieter:**
- Repeat it: `REPEATS=5` and compare **medians**, not means.
- Measure **counts, not time** where possible: instructions (`perf stat -e instructions`),
  allocations, bytes, queries, cache misses. These are near-deterministic.
- Isolate the machine: close other load, pin CPU frequency/cores, disable turbo if you can,
  plug in the laptop. For GPUs, fix clocks and use one device per agent.
- Warm up: one discarded run to warm caches/JIT.
- Fix all seeds. For ML, the fixed time budget plus a fixed eval set does most of the work.
- Re-calibrate periodically (`program.md` says every 10 experiments) because machines drift.

**Rule of thumb:** CV < 1% is great, 1–5% workable, > 5% means fix the bench before running.

## 2. Overfitting to the benchmark inputs

**Problem:** the agent picks changes by their score on the search inputs, so over many rounds
it fits the quirks of *those* inputs (validation overfitting).

**Defence:**
- **Held-out split.** Keep a second input set the loop never decides on (`SPLIT=holdout`).
  Check it every ~25 experiments and at the end. Report search gain vs held-out gain side by side.
- **Representative inputs.** Use real, varied production-like inputs. One micro-benchmark gets
  over-tuned fast.
- **Per-slice metrics.** An average can rise while one slice collapses (aggregate blindness).
  Emit `aux_` metrics per slice (small/large templates, short/long sequences, hot/cold cache)
  and check them in review.
- **Transfer test**, the Karpathy move: confirm the wins at a bigger scale or on another
  workload before merging (depth 12 → depth 24).

## 3. Metric hacking

The agent is not malicious, but the loop rewards anything that moves the number. Known patterns:

| Hack | How it shows up | Defence |
|---|---|---|
| Skip real work | Faster because something is no longer done (Shopify saw files deleted to speed up a build) | Correctness gate with strong assertions; output equivalence check |
| Special-case the inputs | `if input == known_bench_case` | Held-out split; review diffs for literals from the bench inputs |
| Cache across runs | Writes a cache file, so the second repeat gets faster | Bench runs in a clean state; cross-run caches forbidden in program.md |
| Edit the measuring stick | Touches tests, bench, eval, fixtures | `ratchet.py` scope guard discards automatically |
| Weaken checks | Removes validation, error handling, bounds checks | Tests for error paths in the gate; review |
| Trade an unmeasured cost | Faster but 3× memory or binary size | Log those as `aux_` metrics and state limits in program.md |
| Precision games | Lower loss by changing what's evaluated | Eval code is frozen; metric is computed by frozen code |

**The scope guard** (`ratchet.py guard`, run inside `decide`) compares tracked files against
the base commit and discards any experiment that touched something outside the editable globs.
It protects against accidental drift, not determined subversion: the agent *could* edit
`ratchet.py`'s config. The final human review is the real backstop. For untrusted or very long
runs, put the bench and eval outside the agent's writable area (a read-only mount in a container).

## 4. Correctness gate

`bench.sh` runs the tests for the editable scope *before* measuring. If they fail, the result is
`status: broken`, which is never kept. Make the gate:
- **Fast**: under ~20% of bench time, or it eats your experiment budget. Run the full suite at
  the end, not in the loop.
- **Strong**: assertions on outputs, not just "didn't crash". For performance work, an
  output-equivalence check against the baseline's output (golden files) is ideal.
- **Frozen**: tests are outside the editable scope.

## 5. Complexity creep

Each kept change may be small and reasonable while the sum becomes unmaintainable.
- Every row in `results.tsv` records the LOC delta. Tiny gains with high LOC get reverted in review.
- `--simplification` keeps deletions that don't hurt, so the loop can pay complexity back.
- The report's checklist asks the human to drop low-value keeps before merging.

## 6. Running safely unattended

Karpathy runs the agent with permissions disabled. That's only reasonable in a sandbox.
- **Prefer a container or VM**: no credentials mounted, no network if the workload allows it,
  and the repo is a disposable clone.
- **On the host**, don't bypass permissions. Pre-approve only what the loop needs (via
  `/fewer-permission-prompts` or settings.json allow rules):
  `Bash(auto/bench.sh*)`, `Bash(python3 */autoresearch/scripts/ratchet.py*)`,
  `Bash(git commit*)`, `Bash(git reset --hard*)`, `Bash(git log*)`, `Bash(git diff*)`,
  `Bash(grep*)`, `Bash(tail*)`, plus `Edit` on the in-scope files.
- Work only on the `autoresearch/<tag>` branch. Never push from the loop.
- Cap per-run time (`TIMEOUT`) and total run length (stop condition in program.md).
- Before open-sourcing results, scan for secrets (Shopify ran `gitleaks`).

## 7. Context hygiene for long runs

- **All state lives on disk**: git history, `results.tsv`, `config.json`, `ideas.md`. After
  compaction or a restart, `ratchet.py status` and `ideas.md` restore the picture.
- Never stream bench output into context. Redirect to `auto/runs/<sha>.log`, then grep the
  `sample:`/`status:` lines.
- Keep `ideas.md` short: one line per idea with its result. It's the agent's lab notebook, and
  it's what stops the loop from retrying the same failed idea after compaction.
