# Search Strategy

Autoresearch is **greedy hill-climbing with a ratchet**: one branch, one change at a time, keep
if better. That's its strength (simple, auditable, every commit an improvement) and its limit
(it gets stuck at local optima, and it can't take a step that's worse before it's better).

## Making the greedy loop smarter

**Profile before guessing.** For performance targets, the first experiment after the baseline
should be a profile, not an edit. Re-profile after every big keep, because the bottleneck moves.

**Keep a lab notebook** (`auto/ideas.md`): one line per idea, its result, and what was learned.
It stops the agent from retrying failed ideas after compaction, and it's the most readable
artifact for the human the next morning.

**Order ideas by expected value / cost.**
1. Cheap, likely wins: config knobs, obvious inefficiencies from the profile, known-good
   techniques for this kind of system.
2. Structural changes: algorithm, data layout, batching, removing a layer.
3. Speculative changes: radical rewrites of a component.

**One idea per experiment.** Bundling two changes hides which one helped and keeps a passenger
that may hurt. The exception is re-trying two near-misses together on purpose.

**Use near-misses.** Changes that improved slightly but stayed under the threshold are signal.
Log them in ideas.md. Combinations of 2–3 near-misses often clear the bar.

**Ablate after a streak.** After several keeps, try removing each earlier keep one at a time
(`--simplification`). Some will have stopped mattering once later changes landed, and removing
them pays back complexity.

**Sweep instead of single-shot** for numeric knobs: try ×0.5 and ×2 before fine-tuning.

**Stuck (e.g. 15+ consecutive discards)?**
- Re-read the code from the top; re-profile.
- Try the opposite of a failed idea.
- Go to a bigger structural change.
- Read the domain's literature or docs (papers referenced in the code, framework perf guides).
- As a last resort, rewind to an earlier keep and take a different branch of ideas, noting
  why in ideas.md.

## Beyond greedy: population search (optional)

When the greedy loop plateaus and compute allows, the evolutionary systems keep **many
candidates alive** instead of one branch:

| System | Idea |
|---|---|
| FunSearch → AlphaEvolve (DeepMind) | LLM proposes edits to programs sampled from a database of good ones; automated evaluators score them |
| OpenEvolve | Open-source AlphaEvolve: elite archive + diversity maintenance |
| ShinkaEvolve (Sakana) | Bandit-style choice of parents and models; far fewer evaluations |
| AIDE (Weco) | Tree search over solutions: branch from any earlier node, not just the tip |
| CORAL, autoresearch-at-home | Many agents, with a shared hub of findings |

**A lightweight version with Claude Code** (only when the user asks for parallel agents):

1. Create K worktrees, each on its own branch `autoresearch/<tag>-<i>`, from the current best.
   Each gets its own `auto/` run directory (`ratchet.py --dir auto-<i>`) and, for GPU work, its
   own device.
2. Give each agent a different **focus** in its program.md (e.g. "optimiser & schedule",
   "attention & architecture", "data pipeline & batching"). Diversity is the point.
3. Periodically (e.g. hourly) take each branch's best, cherry-pick the wins onto a merge
   branch one at a time, and re-bench after each (wins don't always stack).
4. Re-seed the worktrees from the merged best.

Caveats: parallel benches on one machine add noise to each other (CPU contention, thermal
limits), so re-calibrate. Merging is where interactions show up, so re-verify every
cherry-pick. More agents means more diffs to review; budget the human review time.

## When to stop

Stop conditions belong in program.md: wall-clock hours, experiment count, N consecutive
discards, or "never" (manual interrupt). Diminishing returns are normal: Karpathy's run found
~20 keeps in ~700 experiments, about a 3% keep rate. A low keep rate is fine as long as the
keeps are real.
