#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate the judge merge: coverage, arithmetic, and no silent overwrites.

The merge script had three real defects that all failed SILENTLY (no exception,
just empty or clobbered aggregates). This asserts the invariants so they cannot
come back.
"""
import json, os, sys

WS = sys.argv[1]
JUDGE = os.path.join(WS, "judge")
DEF = json.load(open(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "evals", "judge-defects.json"), encoding="utf-8"))["defects"]
gs = json.load(open(os.path.join(WS, "grading_summary.json"), encoding="utf-8"))
J = gs["judge"]
SCORE = {"yes": 1.0, "partial": 0.5, "no": 0.0}
bad = []
ok = lambda c, m: (print(f"  {'OK  ' if c else 'FAIL'}  {m}"), bad.append(m) if not c else None)

print("judge merge validation")
print("-" * 78)

# 1. one judge file per (eval, config)
# Filenames differ per eval: eval-1/2 were dispatched before a rename pass, so
# they lack the -with/-base suffix. Assert on CONTENT (config field / path
# segment) rather than filenames.
missing = []
for e in DEF:
    for cfg in ("with_skill", "without_skill"):
        hit = False
        for f in os.listdir(JUDGE):
            if not f.endswith(".json"):
                continue
            j = json.load(open(os.path.join(JUDGE, f), encoding="utf-8"))
            if j.get("eval") != int(e):
                continue
            want = cfg.replace("_skill", "")
            for rep in j.get("reports", []):
                segs = rep.get("path", "").replace("/", "\\").split("\\")
                if cfg in segs and f"eval-{e}-" in rep.get("path", ""):
                    hit = True
        if not hit:
            missing.append(f"eval-{e}/{cfg}")
ok(not missing, f"judge coverage for all 5 evals x 2 configs "
   f"(missing: {missing})")

# 2. every report was judged
n_reports = sum(len(json.load(open(os.path.join(JUDGE, f), encoding="utf-8"))["reports"])
                for f in os.listdir(JUDGE) if f.endswith(".json"))
ok(n_reports == 20, f"20 reports judged (got {n_reports})")

# 3. per_run covers exactly the runs the grader graded
ok(len(J["per_run"]) == 20, f"per_run has 20 entries (got {len(J['per_run'])})")

# 4. per_cell has 5 evals x 2 configs
ok(len(J["per_cell"]) == 10, f"per_cell has 10 cells (got {len(J['per_cell'])})")

# 5. per_defect keyed eval-scoped -> 24 defects, none overwritten
ok(len(J["per_defect"]) == sum(len(v) for v in DEF.values()),
   f"per_defect has {sum(len(v) for v in DEF.values())} entries "
   f"(got {len(J['per_defect'])}) — keys must be eval-scoped")

# 6. every verdict is one of the three legal values
illegal = [(k, d, v) for k, r in J["per_run"].items()
           for d, v in r["per_defect"].items() if v not in SCORE]
ok(not illegal, f"all verdicts in {{yes,partial,no}} (bad: {illegal[:3]})")

# 7. arithmetic: score == weighted mean of per_defect
errs = []
for k, r in J["per_run"].items():
    exp = sum(SCORE[v] for v in r["per_defect"].values()) / len(r["per_defect"])
    # stored value is rounded to 3dp
    if abs(round(exp, 3) - r["score"]) > 1e-9:
        errs.append((k, r["score"], round(exp, 3)))
ok(not errs, f"per_run score == round(weighted mean, 3) ({errs[:2]})")

# 8. found/partial/missed sum to total
errs = [k for k, r in J["per_run"].items()
        if r["found"] + r["partial"] + r["missed"] != r["total"]]
ok(not errs, f"found+partial+missed == total ({errs[:3]})")

# 9. summary means match per_cell
import statistics
w = [v["mean"] for v in J["per_cell"].values() if v["config"] == "with_skill"]
b = [v["mean"] for v in J["per_cell"].values() if v["config"] == "without_skill"]
ok(abs(round(statistics.mean(w), 3) - J["summary"]["with_skill_mean"]) < 1e-9,
   f"with_skill_mean matches per_cell ({J['summary']['with_skill_mean']})")
ok(abs(round(statistics.mean(b), 3) - J["summary"]["without_skill_mean"]) < 1e-9,
   f"without_skill_mean matches per_cell ({J['summary']['without_skill_mean']})")

# 10. sign test agrees with the summary
ps = J["paired_sign_test"]
ok(ps["with_higher"] + ps["baseline_higher"] + ps["ties"] == ps["n_paired"],
   f"sign test partitions all pairs ({ps})")

# 11. per-defect rows agree with per_run
errs = []
for key, row in J["per_defect"].items():
    e, did = key.split("-")[1], key.split("-")[2]
    for cfg in ("with_skill", "without_skill"):
        vals = [r["per_defect"][did] for r in J["per_run"].values()
                if r["eval_id"] == int(e) and r["config"] == cfg]
        if len(vals) != row[cfg]["n"]:
            errs.append((key, cfg, len(vals), row[cfg]["n"]))
ok(not errs, f"per_defect rows consistent with per_run ({errs[:3]})")

# 12. the headline finding is stated honestly
print("-" * 78)
s = J["summary"]
print(f"  judged defect recall: with_skill {s['with_skill_mean']:.3f} "
      f"vs baseline {s['without_skill_mean']:.3f} (delta {s['delta_pp']}pp)")
print(f"  paired sign test: {ps['with_higher']} better / {ps['baseline_higher']} worse "
      f"/ {ps['ties']} ties, exact p = {ps['exact_two_sided_p']}")
print("-" * 78)
print("ALL CHECKS PASSED" if not bad else f"{len(bad)} CHECK(S) FAILED")
sys.exit(1 if bad else 0)