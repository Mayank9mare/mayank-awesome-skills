#!/usr/bin/env bash
# auto/bench.sh: FROZEN. The agent must never edit this file (ratchet.py guard enforces it).
#
# Contract: prints one `sample: <float>` line per repeat, optional `aux_<name>: <float>`
# lines, or `status: broken` (correctness gate failed) / `status: crash` (run failed).
# Usage:   auto/bench.sh > auto/runs/<label>.log 2>&1
# Env:     REPEATS (default {{REPEATS}}), TIMEOUT seconds per repeat (default {{TIMEOUT}}),
#          SPLIT=holdout to measure on the held-out inputs instead of the search inputs.
set -uo pipefail

REPEATS="${REPEATS:-{{REPEATS}}}"
TIMEOUT="${TIMEOUT:-{{TIMEOUT}}}"
SPLIT="${SPLIT:-search}"
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
mkdir -p auto/runs

# Portable timeout: GNU timeout, Homebrew gtimeout, or a perl fallback (stock macOS).
run_with_timeout() {
  if command -v timeout >/dev/null 2>&1; then timeout "$TIMEOUT" "$@"
  elif command -v gtimeout >/dev/null 2>&1; then gtimeout "$TIMEOUT" "$@"
  else perl -e 'alarm shift; exec @ARGV or die "exec failed: $!"' "$TIMEOUT" "$@"
  fi
}

# ---------------------------------------------------------------------------
# 1. Build (optional). Failure here is a crash.
# ---------------------------------------------------------------------------
{{BUILD_CMD_OR_DELETE}}
if [ $? -ne 0 ]; then echo "status: crash"; echo "build failed"; exit 3; fi

# ---------------------------------------------------------------------------
# 2. Correctness gate. A faster wrong answer is not an improvement.
#    Run the tests that cover the editable scope; keep it under ~20% of total bench time.
# ---------------------------------------------------------------------------
if ! run_with_timeout {{TEST_CMD}} > auto/runs/last-tests.log 2>&1; then
  echo "status: broken"
  tail -n 30 auto/runs/last-tests.log
  exit 2
fi

# ---------------------------------------------------------------------------
# 3. Measure. One number per repeat, extracted from the measurement's output.
# ---------------------------------------------------------------------------
if [ "$SPLIT" = "holdout" ]; then
  MEASURE=({{HOLDOUT_MEASURE_CMD}})
else
  MEASURE=({{MEASURE_CMD}})
fi

{{WARMUP_OR_DELETE}}   # e.g. one discarded run to warm caches/JIT

for i in $(seq 1 "$REPEATS"); do
  out="$(run_with_timeout "${MEASURE[@]}" 2>&1)"
  rc=$?
  if [ $rc -ne 0 ]; then
    echo "status: crash"
    echo "repeat $i exited $rc"
    echo "$out" | tail -n 40
    exit 3
  fi
  # Extract the metric. Must print exactly one number. Examples:
  #   grep '^val_bpb:' | awk '{print $2}'
  #   grep -oE 'time: [0-9.]+' | awk '{print $2}'
  #   jq '.mean'          (for JSON output)
  val="$(printf '%s\n' "$out" | {{EXTRACT_CMD}})"
  if ! [[ "$val" =~ ^[-+]?[0-9]*\.?[0-9]+([eE][-+]?[0-9]+)?$ ]]; then
    echo "status: crash"
    echo "could not extract metric from repeat $i; got: '$val'"
    echo "$out" | tail -n 20
    exit 3
  fi
  echo "sample: $val"
done

# ---------------------------------------------------------------------------
# 4. Secondary metrics (optional): logged, never ratcheted. Watch these for gaming.
# ---------------------------------------------------------------------------
{{AUX_METRICS_OR_DELETE}}   # e.g. echo "aux_binary_kb: $(du -k dist/app | cut -f1)"
