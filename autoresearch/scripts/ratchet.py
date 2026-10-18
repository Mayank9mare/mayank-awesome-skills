#!/usr/bin/env python3
"""ratchet.py: bookkeeping and guardrails for an autoresearch loop.

Stdlib only. Run from the root of the target repo. All state lives in the
run directory (default: auto/), so the loop survives context compaction and restarts.

  init       record config: direction, editable globs, thresholds, base commit
  calibrate  measure benchmark noise from one or more baseline logs; set the keep threshold
  guard      fail if any file outside the editable scope differs from the base commit
  decide     compare a candidate log to the current best; log a row to results.tsv;
             with --apply, advance (keep) or `git reset --hard` to best (discard)
  status     one-screen summary for resuming: best, counts, last rows
  report     write a markdown report of the run (auto/report.md)

Bench log contract (what auto/bench.sh prints):
  sample: <float>     one line per repeat (preferred)
  metric: <float>     single value, if the bench can't repeat
  aux_<name>: <float> optional secondary metrics (memory, size, ...), logged, not ratcheted
  status: broken|crash  correctness gate failed / run crashed
"""
import argparse
import fnmatch
import json
import math
import os
import re
import statistics
import subprocess
import sys
from datetime import datetime, timezone

HEADER = "commit\tmetric\tspread\tdelta_pct\tloc\tstatus\tdescription\n"
NUM = r"([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)"


# ---------- helpers ----------

def sh(*args, check=True):
    r = subprocess.run(args, capture_output=True, text=True)
    if check and r.returncode != 0:
        sys.exit(f"command failed: {' '.join(args)}\n{r.stderr.strip()}")
    return r.stdout.strip()


def cfg_path(d):
    return os.path.join(d, "config.json")


def load(d):
    p = cfg_path(d)
    if not os.path.exists(p):
        sys.exit(f"{p} not found; run `ratchet.py init` first")
    with open(p) as f:
        return json.load(f)


def save(d, cfg):
    with open(cfg_path(d), "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")


def parse_log(path):
    """Return (samples, aux, status) from a bench log."""
    if not os.path.exists(path):
        return [], {}, "crash"
    text = open(path, errors="replace").read()
    status = None
    m = re.search(r"^status:\s*(\w+)", text, re.M)
    if m:
        status = m.group(1).lower()
    samples = [float(x) for x in re.findall(r"^sample:\s*" + NUM, text, re.M)]
    if not samples:
        samples = [float(x) for x in re.findall(r"^metric:\s*" + NUM, text, re.M)]
    aux = {k: float(v) for k, v in re.findall(r"^aux_(\w+):\s*" + NUM, text, re.M)}
    if status in ("broken", "crash"):
        return [], aux, status
    if not samples or any(math.isnan(s) or math.isinf(s) for s in samples):
        return [], aux, "crash"
    return samples, aux, "ok"


def robust_sigma(xs):
    """Noise estimate: 1.4826 * MAD, falling back to stdev for tiny or degenerate samples."""
    if len(xs) < 2:
        return 0.0
    med = statistics.median(xs)
    mad = statistics.median([abs(x - med) for x in xs]) * 1.4826
    sd = statistics.stdev(xs)
    return mad if mad > 0 else sd


def better(a, b, direction):
    return a < b if direction == "min" else a > b


def loc_delta(rev_a, rev_b):
    out = sh("git", "diff", "--shortstat", rev_a, rev_b, check=False)
    ins = re.search(r"(\d+) insertion", out)
    dels = re.search(r"(\d+) deletion", out)
    return f"+{ins.group(1) if ins else 0}/-{dels.group(1) if dels else 0}"


def changed_files(base):
    """Tracked files that differ from base (committed or not). Untracked files are reported
    separately by untracked_outside(): benches routinely create caches/artifacts."""
    files = set(sh("git", "diff", "--name-only", base, check=False).splitlines())
    return sorted(f for f in files if f)


def untracked_outside(cfg, d):
    files = sh("git", "ls-files", "--others", "--exclude-standard", check=False).splitlines()
    return [f for f in files if f and not in_scope(f, cfg["editable"])
            and not f.startswith(d.rstrip("/") + "/")]


def in_scope(path, globs):
    return any(fnmatch.fnmatch(path, g) for g in globs)


def append_row(d, row):
    p = os.path.join(d, "results.tsv")
    if not os.path.exists(p):
        with open(p, "w") as f:
            f.write(HEADER)
    clean = [str(c).replace("\t", " ").replace("\n", " ") for c in row]
    with open(p, "a") as f:
        f.write("\t".join(clean) + "\n")


def read_rows(d):
    p = os.path.join(d, "results.tsv")
    if not os.path.exists(p):
        return []
    lines = open(p).read().splitlines()[1:]
    keys = HEADER.strip().split("\t")
    return [dict(zip(keys, l.split("\t"))) for l in lines if l.strip()]


# ---------- commands ----------

def cmd_init(a):
    os.makedirs(os.path.join(a.dir, "runs"), exist_ok=True)
    if os.path.exists(cfg_path(a.dir)) and not a.force:
        sys.exit(f"{cfg_path(a.dir)} exists; pass --force to overwrite")
    base = sh("git", "rev-parse", "HEAD")
    cfg = {
        "metric": a.metric,
        "direction": a.direction,
        "editable": [g.strip() for g in a.editable.split(",") if g.strip()],
        "min_effect_rel": a.min_effect_rel,
        "z": a.z,
        "base_commit": base,
        "branch": sh("git", "rev-parse", "--abbrev-ref", "HEAD"),
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "noise": None,
        "best": None,
    }
    save(a.dir, cfg)
    if not os.path.exists(os.path.join(a.dir, "results.tsv")):
        with open(os.path.join(a.dir, "results.tsv"), "w") as f:
            f.write(HEADER)
    print(f"initialised {a.dir}/ on branch {cfg['branch']} at {base[:7]}")
    print(f"metric={a.metric} direction={a.direction} editable={cfg['editable']}")


def cmd_calibrate(a):
    cfg = load(a.dir)
    samples = []
    for p in a.logs:
        s, _, status = parse_log(p)
        if status != "ok":
            sys.exit(f"baseline log {p} is {status}; fix the bench before calibrating")
        samples += s
    if len(samples) < 3:
        print(f"warning: only {len(samples)} sample(s); noise estimate is unreliable. "
              "Use REPEATS>=3 or pass several baseline logs.", file=sys.stderr)
    med = statistics.median(samples)
    sigma = robust_sigma(samples)
    n = max(1, a.repeats or len(samples))
    # Std. error of the difference of two medians of n samples each ≈ 1.2533·σ·sqrt(2/n).
    noise_floor = a.z if a.z is not None else cfg["z"]
    noise_floor *= 1.2533 * sigma * math.sqrt(2 / n)
    effect_floor = cfg["min_effect_rel"] * abs(med)
    threshold = max(noise_floor, effect_floor)
    cfg["noise"] = {
        "median": med, "sigma": sigma, "cv_pct": 100 * sigma / abs(med) if med else None,
        "samples": len(samples), "repeats_per_run": n, "threshold_abs": threshold,
        # Noise usually scales with the metric, so the keep rule uses a relative threshold
        # applied to the *current* best; an absolute one would freeze the ratchet after a big win.
        "threshold_rel": threshold / abs(med) if med else 0.0,
        "threshold_from": "noise" if noise_floor >= effect_floor else "min_effect",
    }
    if cfg.get("baseline_median") is None:
        cfg["baseline_median"] = med
    head = sh("git", "rev-parse", "HEAD")
    cfg["best"] = {"commit": head, "median": med, "samples": samples}
    save(a.dir, cfg)
    if not any(r["status"] == "baseline" for r in read_rows(a.dir)):
        append_row(a.dir, [head[:7], f"{med:.6g}", f"±{sigma:.3g}", "0.00", "+0/-0", "baseline", "baseline"])
    print(f"baseline median={med:.6g}  sigma={sigma:.3g}  cv={cfg['noise']['cv_pct']:.2f}%  n={len(samples)}")
    print(f"keep threshold = {100 * cfg['noise']['threshold_rel']:.2f}% of current best "
          f"({threshold:.4g} now, set by {cfg['noise']['threshold_from']})")
    if cfg["noise"]["cv_pct"] and cfg["noise"]["cv_pct"] > 5:
        print("warning: CV > 5%; the bench is noisy. Pin CPU/GPU, close other load, raise REPEATS, "
              "or measure a more stable proxy (instructions/allocations instead of wall time).")


def cmd_guard(a):
    cfg = load(a.dir)
    bad = [f for f in changed_files(cfg["base_commit"])
           if not in_scope(f, cfg["editable"]) and not f.startswith(a.dir.rstrip("/") + "/")]
    if bad:
        print("GUARD FAIL: files outside the editable scope changed:")
        for f in bad:
            print(f"  {f}")
        sys.exit(1)
    print("guard ok")


def cmd_decide(a):
    cfg = load(a.dir)
    if not cfg.get("best"):
        sys.exit("no baseline yet; run `calibrate` on the baseline log(s) first")
    head = sh("git", "rev-parse", "HEAD")
    best = cfg["best"]
    samples, aux, status = parse_log(a.candidate)

    # Scope guard runs on every decision: out-of-scope edits are discarded no matter the score.
    bad = [f for f in changed_files(cfg["base_commit"])
           if not in_scope(f, cfg["editable"]) and not f.startswith(a.dir.rstrip("/") + "/")]
    if bad:
        status = "guard"
    stray = untracked_outside(cfg, a.dir)
    if stray:
        print(f"warning: untracked files outside scope (not committed, so not part of the experiment; "
              f"gitignore them if they're bench artifacts): {', '.join(stray[:5])}"
              + (" ..." if len(stray) > 5 else ""))

    loc = loc_delta(best["commit"], head)
    if status != "ok":
        verdict, med, spread, delta = status, float("nan"), "", ""
        reason = {"broken": "correctness gate failed", "crash": "run crashed / no metric",
                  "guard": f"edited frozen files: {', '.join(bad)}"}[status]
    else:
        med = statistics.median(samples)
        spread = f"±{robust_sigma(samples):.3g}" if len(samples) > 1 else ""
        delta_pct = 100 * (med - best["median"]) / abs(best["median"]) if best["median"] else 0.0
        delta = f"{delta_pct:+.2f}"
        thr = (cfg.get("noise") or {}).get("threshold_rel", 0.0) * abs(best["median"])
        gain = (best["median"] - med) if cfg["direction"] == "min" else (med - best["median"])
        if gain > thr:
            verdict, reason = "keep", f"improved by {gain:.4g} > threshold {thr:.4g}"
        elif a.simplification and gain > -thr:
            verdict, reason = "keep", f"simplification within noise (gain {gain:.4g}, threshold {thr:.4g})"
        else:
            verdict, reason = "discard", f"gain {gain:.4g} ≤ threshold {thr:.4g}"

    desc = a.description + (f" [{', '.join(f'{k}={v:g}' for k, v in aux.items())}]" if aux else "")
    append_row(a.dir, [head[:7], "" if verdict not in ("keep", "discard") else f"{med:.6g}",
                       spread, delta, loc, verdict, desc])
    print(f"{verdict.upper()}: {reason}")

    if verdict == "keep":
        cfg["best"] = {"commit": head, "median": med, "samples": samples}
        save(a.dir, cfg)
        print(f"best is now {head[:7]} = {med:.6g}")
        cal = (cfg.get("noise") or {}).get("median")
        if cal and abs(med / cal - 1) > 0.25:
            print(f"hint: best has moved {100 * (med / cal - 1):+.0f}% since calibration; noise may have "
                  f"changed too. Re-run the bench on HEAD and `calibrate` that log.")
    elif a.apply:
        if head == best["commit"]:
            print("HEAD is already the best commit; nothing to reset")
        else:
            parent = sh("git", "rev-parse", "HEAD~1", check=False)
            if parent != best["commit"] and not a.force:
                sys.exit(f"refusing to reset: HEAD~1 ({parent[:7]}) is not the best commit "
                         f"({best['commit'][:7]}). Commit each experiment as exactly one commit, "
                         "or pass --force.")
            sh("git", "reset", "--hard", best["commit"])
            print(f"reset to best {best['commit'][:7]}")
    else:
        print(f"next: git reset --hard {best['commit'][:7]}")


def cmd_status(a):
    cfg = load(a.dir)
    rows = read_rows(a.dir)
    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    b, n = cfg.get("best"), cfg.get("noise")
    print(f"metric: {cfg['metric']} ({cfg['direction']})  branch: {cfg['branch']}  base: {cfg['base_commit'][:7]}")
    if n:
        print(f"baseline: {cfg.get('baseline_median', n['median']):.6g}  noise σ={n['sigma']:.3g} "
              f"(cv {n['cv_pct']:.2f}%)  keep threshold={100 * n['threshold_rel']:.2f}% of current best")
    base = cfg.get("baseline_median") or (n or {}).get("median")
    if b and base:
        tot = 100 * (b["median"] - base) / abs(base)
        print(f"best: {b['commit'][:7]} = {b['median']:.6g}  ({tot:+.2f}% vs baseline)")
    print("experiments: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) + f"  total={len(rows)}")
    for r in rows[-a.last:]:
        print(f"  {r['commit']}  {r['metric']:>10}  {r['delta_pct']:>7}  {r['status']:<8} {r['description']}")


def sparkline(vals):
    bars = "▁▂▃▄▅▆▇█"
    lo, hi = min(vals), max(vals)
    if hi == lo:
        return bars[0] * len(vals)
    return "".join(bars[int((v - lo) / (hi - lo) * (len(bars) - 1))] for v in vals)


def cmd_report(a):
    cfg = load(a.dir)
    rows = read_rows(a.dir)
    n = cfg.get("noise") or {}
    base = cfg.get("baseline_median") or n.get("median")
    keeps = [r for r in rows if r["status"] == "keep"]
    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    best_curve, cur = [], base
    for r in rows:
        if r["status"] in ("keep", "baseline") and r["metric"]:
            cur = float(r["metric"])
        if cur is not None:
            best_curve.append(cur)
    best = cfg.get("best") or {}
    lines = [f"# Autoresearch report: {cfg['metric']}", ""]
    lines.append(f"- **Branch:** `{cfg['branch']}` · **base:** `{cfg['base_commit'][:7]}` · "
                 f"**direction:** {cfg['direction']} · **editable:** {', '.join(f'`{g}`' for g in cfg['editable'])}")
    if base is not None and best:
        tot = 100 * (best["median"] - base) / abs(base)
        lines.append(f"- **Baseline:** {base:.6g} → **best:** {best['median']:.6g} at `{best['commit'][:7]}` (**{tot:+.2f}%**)")
        lines.append(f"- **Noise:** σ={n['sigma']:.3g} (cv {n['cv_pct']:.2f}%), keep threshold "
                     f"{100 * n['threshold_rel']:.2f}% of current best")
    lines.append(f"- **Experiments:** {len(rows)} · " + " · ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    if best_curve:
        lines.append(f"- **Best-so-far:** `{sparkline(best_curve)}`")
    lines += ["", "## Kept changes (in order)", "",
              "| # | Commit | Metric | Δ vs prev best | LOC | What |", "|---|---|---|---|---|---|"]
    for i, r in enumerate(keeps, 1):
        lines.append(f"| {i} | `{r['commit']}` | {r['metric']} | {r['delta_pct']}% | {r['loc']} | {r['description']} |")
    ranked = sorted(keeps, key=lambda r: float(r["delta_pct"] or 0),
                    reverse=(cfg["direction"] == "max"))
    lines += ["", "## Biggest wins", ""]
    for r in ranked[:5]:
        lines.append(f"- `{r['commit']}` {r['delta_pct']}%: {r['description']}")
    lines += ["", "## Notable failures", ""]
    for r in [r for r in rows if r["status"] in ("crash", "broken", "guard")][-10:]:
        lines.append(f"- `{r['commit']}` **{r['status']}**: {r['description']}")
    lines += ["", "## Human review checklist", "",
              "- [ ] Each kept diff is a real improvement, not a metric hack (deleted work, skipped checks, cached answers, special-cased the bench inputs)",
              "- [ ] Held-out / production-like benchmark confirms the gain (see held-out section in program.md)",
              "- [ ] Full test suite passes on the best commit",
              "- [ ] Re-ran the best commit and baseline back-to-back; the gain reproduces",
              "- [ ] Complexity added is worth the gain; consider dropping tiny-gain, high-LOC keeps",
              "- [ ] Decide: squash into one PR, or cherry-pick the top wins", ""]
    out = "\n".join(lines)
    path = os.path.join(a.dir, "report.md")
    with open(path, "w") as f:
        f.write(out)
    print(out)
    print(f"\n(wrote {path})", file=sys.stderr)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dir", default="auto", help="run directory (default: auto)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init")
    s.add_argument("--metric", required=True)
    s.add_argument("--direction", choices=["min", "max"], required=True)
    s.add_argument("--editable", required=True, help="comma-separated globs the agent may edit")
    s.add_argument("--min-effect-rel", type=float, default=0.002,
                   help="smallest relative gain worth keeping (default 0.2%%)")
    s.add_argument("--z", type=float, default=2.5, help="noise multiplier for the keep threshold")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("calibrate")
    s.add_argument("logs", nargs="+")
    s.add_argument("--repeats", type=int, help="samples per future run (default: samples found)")
    s.add_argument("--z", type=float)
    s.set_defaults(fn=cmd_calibrate)

    s = sub.add_parser("guard")
    s.set_defaults(fn=cmd_guard)

    s = sub.add_parser("decide")
    s.add_argument("candidate", help="bench log of the candidate run")
    s.add_argument("-m", "--description", required=True)
    s.add_argument("--simplification", action="store_true",
                   help="change removes code/complexity: keep if not worse beyond noise")
    s.add_argument("--apply", action="store_true", help="git reset --hard to best on discard")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_decide)

    s = sub.add_parser("status")
    s.add_argument("--last", type=int, default=10)
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("report")
    s.set_defaults(fn=cmd_report)

    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
