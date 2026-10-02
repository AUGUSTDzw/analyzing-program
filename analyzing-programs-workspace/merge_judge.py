#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""merge_judge.py — fold LLM-judge verdicts into grading_summary.json.

The regex content assertions (A14-A19) turned out to be non-discriminating:
every run, including bare-model baselines, tripped every keyword. This script
adds the layer that actually measures technical correctness: for each eval, did
the report actually NAME the planted defect?

Scoring: yes = 1.0, partial = 0.5, no = 0.0. A defect the judge could not find
in the report scores 0.
"""
import json
import os
import re
import statistics
import sys
from math import comb

WS = sys.argv[1]
JUDGE_DIR = os.path.join(WS, "judge")
GS = os.path.join(WS, "grading_summary.json")
DEFECTS = json.load(open(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "evals", "judge-defects.json"), encoding="utf-8"))["defects"]

SCORE = {"yes": 1.0, "partial": 0.5, "no": 0.0}


def run_key(path):
    # Parse by path SEGMENT rather than regex: Windows separators make escaping
    # fragile, and an earlier `\\(with_skill...` silently matched nothing, which
    # emptied every aggregate without raising.
    p = path.replace("/", os.sep)
    try:
        i_cfg = next(i for i, seg in enumerate(p.split(os.sep))
                     if seg in ("with_skill", "without_skill"))
        segs = p.split(os.sep)
        cfg = segs[i_cfg]
        run = int(segs[i_cfg + 1].split("run-", 1)[1])
        eid = int(next(s for s in segs
                       if s.startswith("eval-")).split("-", 2)[1])
    except (StopIteration, IndexError, ValueError):
        raise SystemExit(
            f"merge_judge: cannot parse (eval, config, run) from judge path:\n  {path}")
    return eid, cfg, run


verdicts = {}          # (eval, cfg, run) -> {defect_id: verdict}
for fn in sorted(os.listdir(JUDGE_DIR)):
    if not fn.endswith(".json"):
        continue
    j = json.load(open(os.path.join(JUDGE_DIR, fn), encoding="utf-8"))
    for rep in j.get("reports", []):
        k = run_key(rep["path"])
        if k:
            verdicts[k] = rep

gs = json.load(open(GS, encoding="utf-8"))
runs = {(r["eval_id"], r["config"], r["run"]): r for r in gs["runs"]}

per_run, per_cell = {}, {}
for (eid, cfg, run), rep in sorted(verdicts.items()):
    want = DEFECTS[str(eid)]
    ids = [d["id"] for d in want]
    v = rep.get("verdicts", {})
    per_defect = {d: v.get(d, "no") for d in ids}
    hit = sum(SCORE[per_defect[d]] for d in ids) / len(ids)
    per_run[f"eval-{eid}-{cfg}-run{run}"] = {
        "eval_id": eid, "config": cfg, "run": run,
        "found": sum(1 for d in ids if per_defect[d] == "yes"),
        "partial": sum(1 for d in ids if per_defect[d] == "partial"),
        "missed": sum(1 for d in ids if per_defect[d] == "no"),
        "total": len(ids), "score": round(hit, 3),
        "per_defect": per_defect,
        "evidence": rep.get("evidence", {}),
        "notes": rep.get("notes", ""),
    }
    if (eid, cfg, run) in runs:
        runs[(eid, cfg, run)]["judge"] = per_run[
            f"eval-{eid}-{cfg}-run{run}"]

for eid in sorted({v["eval_id"] for v in per_run.values()}):
    for cfg in ("with_skill", "without_skill"):
        sc = [v["score"] for v in per_run.values()
              if v["eval_id"] == eid and v["config"] == cfg]
        if not sc:
            continue
        per_cell[f"eval-{eid}-{cfg}"] = {
            "eval_id": eid, "config": cfg, "runs": len(sc),
            "mean": round(statistics.mean(sc), 3),
            "min": round(min(sc), 3), "max": round(max(sc), 3),
            "per_run": sc,
        }

# per-defect breakdown across both configs.
# NOTE: defect ids restart at D1 for every eval, so the key MUST be eval-scoped
# or eval-5/D1 silently overwrites eval-3/D1.
# NOTE: iterate only the evals that were ACTUALLY judged. DEFECTS is the current
# master list (13 evals), but an older iteration dir only ran 5 of them —
# walking the whole list there emitted rows with n=0 for 53 defects that were
# never scored, inflating per_defect and skewing any mean computed over it.
per_defect_agg = {}
judged_evals = sorted({v["eval_id"] for v in per_run.values()})
skipped = sorted(set(int(k) for k in DEFECTS) - set(judged_evals))
if skipped:
    print(f"note: {len(skipped)} eval(s) in judge-defects.json were not judged "
          f"in this iteration and are excluded from per_defect: {skipped}")
for eid_str in (str(e) for e in judged_evals):
    want = DEFECTS[eid_str]
    for d in want:
        did = d["id"]
        key = f"eval-{eid_str}-{did}"
        row = {"eval": int(eid_str), "defect": did, "area": d["area"],
               "question": d["question"]}
        for cfg in ("with_skill", "without_skill"):
            vals = [v["per_defect"].get(did, "no") for v in per_run.values()
                    if v["eval_id"] == int(eid_str) and v["config"] == cfg]
            row[cfg] = {
                "n": len(vals),
                "yes": sum(1 for x in vals if x == "yes"),
                "partial": sum(1 for x in vals if x == "partial"),
                "no": sum(1 for x in vals if x == "no"),
                "score": round(sum(SCORE[x] for x in vals) / len(vals), 3)
                if vals else None,
            }
        per_defect_agg[key] = row

w = [v["mean"] for v in per_cell.values() if v["config"] == "with_skill"]
b = [v["mean"] for v in per_cell.values() if v["config"] == "without_skill"]

# paired sign test on per-report judged score (with_skill vs baseline, same
# eval + same run) — nonparametric, exact, appropriate for n=13 per arm.
# NOTE: iterate the with_skill arm only. Walking all of per_run would count
# every pair twice with mirrored signs, forcing pos == neg and pinning p at
# 1.0 regardless of the actual effect.
diffs = []
for k, v in per_run.items():
    if v["config"] != "with_skill":
        continue
    o = per_run.get(f"eval-{v['eval_id']}-without_skill-run{v['run']}")
    if o:
        diffs.append(v["score"] - o["score"])
pos = sum(1 for x in diffs if x > 0)
neg = sum(1 for x in diffs if x < 0)
n = pos + neg
p = 1.0 if n == 0 else min(1.0, 2 * sum(comb(n, i) for i in range(0, min(pos, neg) + 1)) / 2 ** n)

gs["judge"] = {
    "method": "LLM judge, per planted defect, 3-way (yes/partial/no)",
    "scoring": SCORE,
    "per_run": per_run,
    "per_cell": per_cell,
    "per_defect": per_defect_agg,
    "summary": {
        "with_skill_mean": round(statistics.mean(w), 3) if w else 0,
        "without_skill_mean": round(statistics.mean(b), 3) if b else 0,
        "delta_pp": round((statistics.mean(w) - statistics.mean(b)) * 100, 1)
        if w and b else 0,
    },
    "paired_sign_test": {"n_paired": len(diffs), "with_higher": pos,
                         "baseline_higher": neg, "ties": len(diffs) - n,
                         "exact_two_sided_p": round(p, 6)},
}
json.dump(gs, open(GS, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

print("=" * 92)
print(f"{'run':34} {'yes':>4} {'part':>5} {'miss':>5} {'score':>6}")
print("-" * 92)
for k, v in per_run.items():
    print(f"{k:34} {v['found']:>4} {v['partial']:>5} {v['missed']:>5} {v['score']:>6}")
print("=" * 92)
print(f"\nper (eval,config):")
for k, v in per_cell.items():
    print(f"  {k:28} mean {v['mean']:>5}  range [{v['min']}, {v['max']}]  runs {v['per_run']}")
print(f"\nwith_skill {gs['judge']['summary']['with_skill_mean']:.3f} vs "
      f"without_skill {gs['judge']['summary']['without_skill_mean']:.3f} "
      f"(delta {gs['judge']['summary']['delta_pp']}pp)")
ps = gs["judge"]["paired_sign_test"]
print(f"paired sign test: n={ps['n_paired']} with_higher={ps['with_higher']} "
      f"baseline_higher={ps['baseline_higher']} ties={ps['ties']} "
      f"exact p={ps['exact_two_sided_p']}")
print(f"\nper-defect (score = weighted hit rate across runs of that config):")
print(f"{'defect':16} {'area':12} {'with':>6} {'base':>6} {'delta':>7}")
for key in sorted(per_defect_agg, key=lambda x: (per_defect_agg[x]["eval"], x)):
    row = per_defect_agg[key]
    ww = row["with_skill"]["score"]
    bb = row["without_skill"]["score"]
    f = lambda x: f"{x*100:.0f}%" if x is not None else "  -  "
    delta = f"{(ww-bb)*100:+.0f}pp" if (ww is not None and bb is not None) else "  -  "
    print(f"{key:16} {row['area']:11} {f(ww):>6} {f(bb):>6} {delta:>7}")
print(f"\nMerged into {GS}")