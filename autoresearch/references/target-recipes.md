# Target Recipes

The loop is the same everywhere: one editable scope, one frozen bench that prints a number, a
fixed budget per run, and the ratchet. What changes per target are **five choices**: metric,
editable scope, bench command, correctness gate, and budget per run. Below are tested shapes.

Rule: **can you score it with one number from a script, in minutes, and does a better number
mean a better outcome?** If yes, it can be autoresearched. If the number can go up while the
outcome gets worse, fix the metric first.

---

## ML training (the original)

| Choice | Setting |
|---|---|
| Metric | Validation loss / bits-per-byte (min), or accuracy/F1 (max) on a **fixed** validation set |
| Scope | The training script (`train.py`): model, optimiser, hyperparameters, loop |
| Frozen | Data prep, tokenizer, eval function, time budget constant |
| Bench | Train for a **fixed wall-clock budget** (5 min), then evaluate |
| Gate | Run completes, no NaN, memory under a cap |
| Budget | ~5–7 min → ~10/hour |

Notes: the fixed *time* budget makes architecture/size changes comparable and finds the best
model for your hardware. One run per experiment is typical (repeats are expensive), so
calibrate noise with 3 baseline runs at different seeds. Confirm wins at larger scale before
believing them. For tabular ML (XGBoost and similar), use k-fold CV on train for search and a
locked test split for held-out.

## Runtime performance (latency, throughput)

| Choice | Setting |
|---|---|
| Metric | Median latency (min) or ops/sec (max) on a realistic workload; prefer **instructions or allocations** if wall time is noisy |
| Scope | The hot module(s) found by profiling. Keep it narrow. |
| Frozen | Benchmark harness, inputs, tests, public API |
| Bench | `hyperfine`, language bench tools (`go test -bench`, `cargo bench`, `pytest-benchmark`, `benchmark-ips`), or a script printing one number |
| Gate | Unit tests for the module + **output equivalence** against golden outputs |
| Budget | 30 s – 3 min |
| aux_ | Memory peak, allocations, binary size |

This is Shopify's Liquid case (53% faster parse+render, 61% fewer allocations). Profile first and
include the profile summary in program.md so the agent starts at the real bottleneck.

## Build time / CI time

| Choice | Setting |
|---|---|
| Metric | Clean-build seconds (min), or incremental-build seconds for a fixed edit |
| Scope | Build config (webpack/vite/tsconfig/gradle/bazel files), CI scripts |
| Frozen | Source code, test files, the list of required artifacts |
| Gate | Build artifacts exist and are equivalent (hash or file-list check); app smoke test passes |
| Budget | Whatever one clean build takes; clean caches between repeats |

Watch for "faster because it builds less": the gate must check every required artifact.

## Test-suite speed

| Choice | Setting |
|---|---|
| Metric | Suite wall time (min) |
| Scope | Test *infrastructure*: fixtures, setup/teardown, parallelism config, factories. **Not** test assertions. |
| Gate | Same test count, same pass/fail set, coverage not lower |
| aux_ | Test count, coverage % |

Strongest hack risk of any recipe (delete or skip slow tests), so make the gate compare the
collected test IDs exactly.

## Bundle / binary / image size

| Choice | Setting |
|---|---|
| Metric | Bytes (min), gzip/brotli size for web bundles |
| Scope | Build config, imports, dependency usage in source |
| Gate | App builds; e2e smoke test; no runtime errors in a headless load |
| Budget | One build. Deterministic, so `REPEATS=1` and the min_effect threshold is enough. |

## SQL / query performance

| Choice | Setting |
|---|---|
| Metric | Total execution time of a fixed query set (min), or buffer reads from `EXPLAIN (ANALYZE, BUFFERS)` (more stable) |
| Scope | Query text, indexes (as a migration file), ORM query code |
| Gate | Result sets identical to baseline (hash rows in order) |
| Notes | Use a production-like data snapshot; reset caches or run warm consistently |

## GPU kernels

| Choice | Setting |
|---|---|
| Metric | TFLOPS or µs per call (on fixed shapes) |
| Scope | The kernel file (Triton/CUDA) |
| Gate | Numerical equivalence within tolerance vs a reference implementation, across several shapes |
| Notes | Lock clocks; held-out = shapes not used during search |

## Prompts / LLM agents

| Choice | Setting |
|---|---|
| Metric | Pass rate on an eval set (max), from deterministic checks where possible; LLM-judge only with a fixed judge model and rubric |
| Scope | The prompt / system-prompt / tool-description files |
| Frozen | Eval cases, the judge prompt, model + temperature |
| Gate | Format/schema validity on all cases |
| Budget | One eval pass; repeat 3× if sampling temperature > 0 |
| Held-out | **Mandatory**: a split of eval cases the loop never sees. Prompts overfit to eval cases very easily. |

Judge-based metrics are the most hackable (the prompt learns to please the judge). Prefer binary
programmatic checks, and keep the judge's rubric frozen and hidden from the editable scope.

## Compression ratio, accuracy of a heuristic, game AI, simulators

Anything with a scorer works: compression ratio (with round-trip equality as the gate), solver
quality on a fixed instance set (with timeouts), mean game score over fixed seeds (Weco's Flappy
Bird example), physics-sim error against reference data.

## Not a good fit

- No automatable score, or it takes hours per run (do a manual design review instead).
- The score depends on human judgment (UX, writing quality) and there's no trustworthy proxy.
- The editable scope is the whole repo: diffs become unreviewable and hacks become easy.
- Correctness can't be checked cheaply. A speed metric without a correctness gate *will* be gamed.
