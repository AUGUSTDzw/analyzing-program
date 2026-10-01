#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Final iteration-7 build: score + judge + paired stats -> benchmark.json.

Replaces the fake zeros in the old benchmark schema:
  * time_seconds  -> measured from report.md mtimes (generation window), with an
                     explicit `measurement` note so nobody reads it as precise.
  * tokens        -> REMOVED. Not observable through the task tool; emitting 0
                     was indistinguishable from "measured zero".
  * stddev        -> REMOVED from the headline. With n=2 per cell a pstdev is not
                     an estimate of anything; the McNemar / sign-test results are
                     the defensible statistics.
"""
import json, os, statistics, sys
from math import comb

WS = sys.argv[1]
STAMP = sys.argv[2]
GRADER = sys.argv[3] if len(sys.argv) > 3 else "grade_v2.py"

gs = json.load(open(os.path.join(WS, "grading_summary.json"), encoding="utf-8"))
stamps = {r["run"]: r for r in json.load(open(STAMP, encoding="utf-8"))}


def mcnemar(a, b):
    n = a + b
    if n == 0:
        return 1.0
    k = min(a, b)
    return min(1.0, 2 * sum(comb(n, i) for i in range(0, k + 1)) / 2 ** n)


def wilson(k, n, z=1.96):
    if not n:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * (p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5 / d
    return (round(max(0, c - h), 3), round(min(1, c + h), 3))


runs = []
for r in gs["runs"]:
    key = f"eval-{r['eval_id']}-{r['config']}-run{r['run']}"
    st = stamps.get(key, {})
    runs.append({
        "eval_id": r["eval_id"], "eval_name": r["eval_name"],
        "config": r["config"], "run": r["run"],
        "result": {
            "format_pass_rate": r["pass_rate"],
            "passed": r["passed"], "failed": r["total"] - r["passed"],
            "total": r["total"], "skipped": r["skipped"],
            "chars": r["chars"], "abap_blocks": r["abap_blocks"],
            "judge_score": r.get("judge", {}).get("score"),
        },
        "generated_at_utc": st.get("mtime_utc"),
        "expectations": r["expectations"],
    })

pf = gs["paired"]
J = gs["judge"]
pc = list(J["per_cell"].values())

wf = [v["pass_rate_mean"] for v in gs["per_cell"].values() if v["config"] == "with_skill"]
bf = [v["pass_rate_mean"] for v in gs["per_cell"].values() if v["config"] == "without_skill"]
wj = [v["mean"] for v in pc if v["config"] == "with_skill"]
bj = [v["mean"] for v in pc if v["config"] == "without_skill"]
agg_wf, agg_bf = round(statistics.mean(wf), 3), round(statistics.mean(bf), 3)
agg_wj, agg_bj = round(statistics.mean(wj), 3), round(statistics.mean(bj), 3)

benchmark = {
    "metadata": {
        "skill_name": "analyzing-programs",
        "iteration": "iteration-7",
        "grader": GRADER,
        "judge": "LLM judge, per planted defect, yes/partial/no",
        "runs_per_configuration": gs["metadata"]["runs_per_configuration"],
        "evals": gs["metadata"]["evals"],
        "stats": {
            "headline": "McNemar exact two-sided on paired (eval, run, assertion) cells",
            "format_p": pf["mcnemar_exact_two_sided_p"],
            "judge_sign_test_p": J["paired_sign_test"]["exact_two_sided_p"],
            "note": "stddev deliberately omitted: n=2 per cell cannot estimate variance.",
        },
        "measurement": {
            "time_seconds": "NOT COLLECTED — the task tool does not report generation "
                            "wall-clock. Report mtimes are stored per run as "
                            "generated_at_utc but are NOT a duration.",
            "tokens": "REMOVED — not observable; previous rounds emitted 0 which was "
                      "indistinguishable from a real zero.",
        },
    },
    "runs": runs,
    "per_cell": gs["per_cell"],
    "assertion_stats": gs["assertion_stats"],
    "paired_format": pf,
    "judge": J,
    "summary": gs["summary"],
    # Kept so iteration-7 stays loadable by the earlier tooling, but the useless
    # time/token fields are NOT reproduced here — see metadata.measurement.
    "run_summary": {
        "with_skill": {"format_pass_rate": agg_wf, "judge_pass_rate": agg_wj},
        "without_skill": {"format_pass_rate": agg_bf, "judge_pass_rate": agg_bj},
        "delta": {"format_pass_rate_pp": round((agg_wf - agg_bf) * 100, 1),
                  "judge_pass_rate_pp": round((agg_wj - agg_bj) * 100, 1)},
    },
    "headline_findings": [],
}

F = benchmark["headline_findings"]
F.append(f"FORMAT COMPLIANCE: with_skill {statistics.mean(wf):.3f} vs baseline "
         f"{statistics.mean(bf):.3f} across 5 program types. Paired McNemar on "
         f"{pf['concordant_pass'] + pf['with_only_pass'] + pf['without_only_pass']} cells: "
         f"{pf['with_only_pass']} with-only vs {pf['without_only_pass']} baseline-only, "
         f"exact p = {pf['mcnemar_exact_two_sided_p']:.2e}. The skill's structural "
         f"value is real and large.")
F.append(f"TECHNICAL CORRECTNESS: judged defect recall with_skill "
         f"{statistics.mean(wj):.3f} vs baseline {statistics.mean(bj):.3f} "
         f"(delta {(statistics.mean(wj)-statistics.mean(bj))*100:+.1f}pp). Paired sign "
         f"test {J['paired_sign_test']['with_higher']} better / "
         f"{J['paired_sign_test']['baseline_higher']} worse / "
         f"{J['paired_sign_test']['ties']} ties, exact p = "
         f"{J['paired_sign_test']['exact_two_sided_p']}. NO significant difference.")
F.append("REGEX CONTENT ASSERTIONS A14-A19 ARE DEAD: every run including bare-model "
         "baselines scored 100% on all of them. They measure keyword presence, and "
         "any competent Chinese ABAP write-up contains those keywords. They were "
         "replaced by the LLM judge as the real content layer.")
F.append("SKILL DOES NOT IMPROVE DEFECT DETECTION: on planted defects the bare model "
         "is already strong (0.729). The skill's contribution is structure and "
         "completeness, not sharper code review. Per-defect table shows the skill "
         "wins big on 语义校核 (eval-1-D2 +100pp, eval-3-D3 +50pp) and 事务处理 "
         "(eval-4-D1 +75pp) but LOSES on eval-2-D1 (-100pp, hardcoded MESSAGE text).")
F.append("A8 v1 WAS A FALSE-NEGATIVE PROVOCATION: it required one three-layer set per "
         "```abap block, penalising inline evidence snippets. eval-3/with/run-2 was "
         "read manually and found fully compliant yet scored 22/33. Now counts "
         "#### ① ② ③ sub-steps.")

out = os.path.join(WS, "benchmark.json")
json.dump(benchmark, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("\n".join(f"  {i+1}. {f}" for i, f in enumerate(F)))
print(f"\nWrote {out} ({os.path.getsize(out)} bytes)")