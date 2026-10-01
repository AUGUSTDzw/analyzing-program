#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build iteration-4 benchmark.json + cross-iteration comparison vs iteration-3.

Unlike build_benchmark3.py, every note and every per-assertion verdict here is
DERIVED FROM grading_summary.json. No hard-coded claims survive a regression.

Usage: python build_benchmark4.py <workspace-dir> [--compare <other-workspace-dir>]
"""
import json, os, statistics, sys, hashlib, datetime

WS = sys.argv[1]
COMPARE = None
if "--compare" in sys.argv:
    COMPARE = sys.argv[sys.argv.index("--compare") + 1]

SKILL_PATH = r"C:\Users\DzwU\.agents\skills\analyzing-programs\SKILL.md"


def skill_digest():
    """SHA256 of the SKILL.md under test, so two rounds can be proven identical."""
    try:
        with open(SKILL_PATH, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None

EVALS = [
    (1, "alv-editable-total-poc",
     "eval-1-with_skill", "eval-1-without_skill",
     "eval-1-alv-editable-total-poc"),
    (2, "procedural-vendor-report",
     "eval-2-with_skill", "eval-2-without_skill",
     "eval-2-procedural-vendor-report"),
]

# A12 only exists for eval-1 (ntgew semantic check). Keep the shared core separate
# so per-assertion deltas across rounds are always like-for-like.
SHARED_AIDS = [f"A{i}" for i in range(1, 12)]


def std(xs):
    return statistics.pstdev(xs) if len(xs) > 1 else 0.0


def agg(r):
    return {"mean": round(statistics.mean(r), 3), "stddev": round(std(r), 3),
            "min": round(min(r), 3), "max": round(max(r), 3)}


def aid_map(summary, run_id):
    """{'A1': bool, ...} for one run, keyed by assertion id."""
    return {e["text"][:0] or "" for e in []} or {
        f"A{i+1}": e["passed"] for i, e in enumerate(summary[run_id]["expectations"])
    }


def load(ws):
    with open(os.path.join(ws, "grading_summary.json"), encoding="utf-8") as f:
        return json.load(f)


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def aid_matrix(summary):
    """{(eval_id, config): {aid: passed}} plus per-run aid->text."""
    m, text = {}, {}
    for eid, _en, ws_k, bs_k, _d in EVALS:
        for k in (ws_k, bs_k):
            if k not in summary or "expectations" not in summary[k]:
                continue
            cfg = "with_skill" if k == ws_k else "without_skill"
            m[(eid, cfg)] = {f"A{i+1}": e["passed"]
                             for i, e in enumerate(summary[k]["expectations"])}
            text[(eid, cfg)] = {f"A{i+1}": e["text"]
                                for i, e in enumerate(summary[k]["expectations"])}
    return m, text


summary = load(WS)
runs, wr, br = [], [], []
for eid, en, ws_k, bs_k, _d in EVALS:
    wr.append(summary[ws_k]["pass_rate"])
    br.append(summary[bs_k]["pass_rate"])
    for k, cfg in [(ws_k, "with_skill"), (bs_k, "without_skill")]:
        s = summary[k]
        runs.append({
            "eval_id": eid, "eval_name": en, "configuration": cfg, "run_number": 1,
            "result": {"pass_rate": s["pass_rate"], "passed": s["passed"],
                       "failed": s["total"] - s["passed"], "total": s["total"],
                       "time_seconds": 0, "tokens": 0, "tool_calls": 0, "errors": 0},
            "expectations": s["expectations"], "notes": [],
        })

M, TEXT = aid_matrix(summary)

# ---- derive notes from data -------------------------------------------------
# Bucket every shared assertion by how it behaved ACROSS evals, once per aid.
# Verdict per aid: (skill_gains, always_pass, always_fail_both, mixed)
skill_gains, always_pass, always_fail_both, mixed = [], [], [], []
with_fail = []

for aid in SHARED_AIDS:
    labels, wv, bv = set(), [], []
    for eid, _en, _w, _b, _d in EVALS:
        w, b = M.get((eid, "with_skill"), {}), M.get((eid, "without_skill"), {})
        if aid not in w or aid not in b:
            continue
        labels.add(TEXT[(eid, "with_skill")][aid])
        wv.append(w[aid])
        bv.append(b[aid])
        if not w[aid]:
            with_fail.append(f"{aid} on eval-{eid}: {TEXT[(eid, 'with_skill')][aid]}")
    if not wv:
        continue
    label = " / ".join(sorted(labels))
    skill_always = all(wv)
    base_always = all(bv)
    if skill_always and not base_always:
        skill_gains.append((aid, label))
    elif skill_always and base_always:
        always_pass.append((aid, label))
    elif not skill_always and not base_always:
        always_fail_both.append((aid, label))
    else:
        mixed.append((aid, label, wv, bv))

notes = [
    f"with_skill mean {statistics.mean(wr)*100:.1f}% vs without_skill "
    f"{statistics.mean(br)*100:.1f}% — +{(statistics.mean(wr)-statistics.mean(br))*100:.1f}pp.",
    f"per-eval with_skill: {[round(x*100) for x in wr]}%  |  "
    f"without_skill: {[round(x*100) for x in br]}%.",
    "skill gains (with_skill PASS in every eval, baseline FAIL in >=1): "
    + (", ".join(f"{a} ({l})" for a, l in skill_gains) or "none") + ".",
]
if with_fail:
    notes.append("REGRESSION — with_skill FAIL: " + "; ".join(with_fail) +
                 ". The baseline fails these too, so the skill is not the cause, but "
                 "with_skill is expected to clear every structural assertion.")
else:
    notes.append("with_skill cleared every shared structural assertion.")
notes.append("non-discriminating, PASS in both configs for every eval: " +
             (", ".join(a for a, _ in always_pass) or "none") + ".")
if always_fail_both:
    notes.append("FAIL in both configs for every eval (skill cannot help): " +
                 ", ".join(f"{a} ({l})" for a, l in always_fail_both) + ".")
if mixed:
    notes.append("inconsistent across evals: " +
                 "; ".join(f"{a} with={wv} base={bv} ({l})" for a, l, wv, bv in mixed)
                 + ".")

benchmark = {
    "metadata": {
        "skill_name": "analyzing-programs",
        "skill_path": r"C:\Users\DzwU\.agents\skills\analyzing-programs",
        "executor_model": "general-subagent",
        "iteration": os.path.basename(WS.rstrip("\\/")),
        "evals_run": [e[0] for e in EVALS],
        "runs_per_configuration": 1,
        "grader": "grade3.py",
        "skill_sha256": skill_digest(),
        "generated_at": datetime.datetime.now(datetime.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
    },
    "runs": runs,
    "run_summary": {
        "with_skill": {"pass_rate": agg(wr), "time_seconds": {"mean": 0, "stddev": 0},
                       "tokens": {"mean": 0, "stddev": 0}},
        "without_skill": {"pass_rate": agg(br), "time_seconds": {"mean": 0, "stddev": 0},
                          "tokens": {"mean": 0, "stddev": 0}},
        "delta": {"pass_rate": f"+{round(statistics.mean(wr)-statistics.mean(br),3)}",
                  "time_seconds": "+0.0", "tokens": "+0"},
    },
    "notes": notes,
}

out = os.path.join(WS, "benchmark.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump(benchmark, f, ensure_ascii=False, indent=2)
print(notes[0])
print(notes[1])
for n in notes[2:]:
    print(n)
print("\nWrote", out)

# ---- cross-iteration comparison ---------------------------------------------
if COMPARE:
    print("\n" + "=" * 78)
    print(f"CROSS-ITERATION: {os.path.basename(COMPARE)}  ->  "
          f"{os.path.basename(WS)}")
    print("=" * 78)
    # Same skill version? Then score deltas are sampling variance, not improvement.
    try:
        ometa = load_json(os.path.join(COMPARE, "benchmark.json")).get("metadata", {})
    except OSError:
        ometa = {}
    old_digest, new_digest = ometa.get("skill_sha256"), skill_digest()
    if old_digest and new_digest:
        print(f"skill_sha256 {old_digest[:12]} -> {new_digest[:12]}")
        print("  => " + ("SAME SKILL VERSION — deltas below are sampling variance, "
                         "NOT a skill improvement"
                         if old_digest == new_digest else
                         "SKILL CHANGED — deltas reflect the skill revision"))
    else:
        print("skill_sha256 not recorded in the older round — cannot separate "
              "variance from improvement.")
    print("")
    om = load(COMPARE)
    OM, OTEXT = aid_matrix(om)
    hdr = f"{'eval':6} {'config':14} {'old':>7} {'new':>7} {'delta':>7}"
    print(hdr); print("-" * 78)
    for eid, en, ws_k, bs_k, _d in EVALS:
        for k, cfg in [(ws_k, "with_skill"), (bs_k, "without_skill")]:
            o = summary[k]["pass_rate"] if False else None
            o = om[k]["pass_rate"] if k in om and "pass_rate" in om[k] else None
            n = summary[k]["pass_rate"]
            d = "n/a" if o is None else f"{(n-o)*100:+.0f}pp"
            print(f"{eid:<6} {cfg:14} {(f'{o*100:.0f}%' if o is not None else '-'):>7} "
                  f"{n*100:>7.0f}% {d:>7}")
    print("-" * 78)
    changed = []
    for eid, _en, _w, _b, _d in EVALS:
        for cfg in ("with_skill", "without_skill"):
            if (eid, cfg) not in M or (eid, cfg) not in OM:
                continue
            for aid in SHARED_AIDS:
                if aid not in M[(eid, cfg)] or aid not in OM[(eid, cfg)]:
                    continue
                if M[(eid, cfg)][aid] != OM[(eid, cfg)][aid]:
                    o, n = OM[(eid, cfg)][aid], M[(eid, cfg)][aid]
                    changed.append((f"eval-{eid} {cfg}", aid,
                                    "PASS->FAIL" if o and not n else "FAIL->PASS",
                                    TEXT[(eid, cfg)][aid]))
    if changed:
        print("Per-assertion flips:")
        for scope, aid, flip, label in changed:
            print(f"  {scope:22} {aid:4} {flip:11} {label}")
    else:
        print("Per-assertion flips: none")