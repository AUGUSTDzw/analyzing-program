#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json, os, statistics, sys
WS = sys.argv[1]
summary = json.load(open(os.path.join(WS, "grading_summary.json"), encoding="utf-8"))
EVALS = [(1,"alv-editable-total-poc","eval-1-with_skill","eval-1-without_skill"),
         (2,"procedural-vendor-report","eval-2-with_skill","eval-2-without_skill")]
def std(xs): return statistics.pstdev(xs) if len(xs)>1 else 0.0
runs=[]; wr=[]; br=[]
for eid,en,ws_k,bs_k in EVALS:
    wr.append(summary[ws_k]["pass_rate"]); br.append(summary[bs_k]["pass_rate"])
    for k,cfg in [(ws_k,"with_skill"),(bs_k,"without_skill")]:
        s=summary[k]
        runs.append({"eval_id":eid,"eval_name":en,"configuration":cfg,"run_number":1,
            "result":{"pass_rate":s["pass_rate"],"passed":s["passed"],"failed":s["total"]-s["passed"],
                      "total":s["total"],"time_seconds":0,"tokens":0,"tool_calls":0,"errors":0},
            "expectations":s["expectations"],"notes":[]})
def agg(r): return {"mean":round(statistics.mean(r),3),"stddev":round(std(r),3),"min":round(min(r),3),"max":round(max(r),3)}
b={"metadata":{"skill_name":"analyzing-programs","skill_path":r"C:\Users\DzwU\.agents\skills\analyzing-programs","executor_model":"general-subagent","timestamp":"2026-10-01T07:00:00Z","evals_run":[1,2],"runs_per_configuration":1},
   "runs":runs,
   "run_summary":{"with_skill":{"pass_rate":agg(wr),"time_seconds":{"mean":0,"stddev":0},"tokens":{"mean":0,"stddev":0}},
                 "without_skill":{"pass_rate":agg(br),"time_seconds":{"mean":0,"stddev":0},"tokens":{"mean":0,"stddev":0}},
                 "delta":{"pass_rate":f"+{round(statistics.mean(wr)-statistics.mean(br),3)}","time_seconds":"+0.0","tokens":"+0"}},
   "notes":[f"with_skill mean {statistics.mean(wr)*100:.0f}% vs without_skill {statistics.mean(br)*100:.0f}% — +{round(statistics.mean(wr)-statistics.mean(br),3)*100:.0f}pp.",
      "Both with_skill runs at 100% structural compliance; baselines 50%/55%.",
      "Skill-driven gains cluster in A2 (责任链表), A4 (sequenceDiagram), A7 (P0/P3), A8 (three-layer-per-block) — all FAIL baseline, PASS with skill.",
      "A12 (ntgew/brgew semantic mismatch) now PASS with-skill without hand-holding — refinement generalizes.",
      "A1/A6/A9/A10/A11 are non-discriminating (pass in both)."]}
json.dump(b,open(os.path.join(WS,"benchmark.json"),"w",encoding="utf-8"),ensure_ascii=False,indent=2)
print(f"with_skill mean: {statistics.mean(wr)*100:.1f}%  | without_skill mean: {statistics.mean(br)*100:.1f}%  | delta +{(statistics.mean(wr)-statistics.mean(br))*100:.1f}pp")
print("Wrote", os.path.join(WS,"benchmark.json"))
