"""Aggregate the historical v1 judgements across five sources.

The failed noise reduction tried to widen the denominator inside one source and
paid for it with variance, because the additions went where the reports disagree
most. Sampling across sources widens the denominator the other way: the additions
come from independent programs, so their variance averages instead of compounding.

No generation is needed. Five of the six defect lists already have a v1 judgement
on disk from the same era as arm A, in three different file shapes.

What this measures that nothing before could: how much of a report's score is set
by the program rather than by the report. If the spread across sources is as large
as the spread across runs of one source, then most of what looks like noise is
program difficulty, and comparing two designs on a single program is measuring the
program as much as the design.
"""
import collections
import io
import json
import os
import statistics
import sys

ROOT, RES = sys.argv[1], sys.argv[2]
EV = os.path.join(ROOT, "skill", "analyzing-programs", "evals")


def load_list(name):
    return json.load(io.open(os.path.join(EV, name + ".defects.json"),
                            encoding="utf-8"))


def score(verdicts, n):
    c = collections.Counter(verdicts.values())
    for k in ("yes", "partial", "no"):
        c.setdefault(k, 0)
    w = (c["yes"] + 0.5 * c["partial"]) / n
    return c, w


# (list, verdict source, selector) -- selector picks which report inside the file
PAIRS = [
    ("zcl_fi_toolkit", "judge38-armA.json", None),
    ("z_ave_standalone", "judge-ave.json", None),
    ("zbc_show_error_log", "judge-classic.json", 0),
    ("screen_manager_o01", "judge-classic.json", 1),
    ("dialog_zmsa_r_chapter4_8", "judge-classic.json", 2),
]

rows = []
for name, vfile, idx in PAIRS:
    d = load_list(name)
    n = len(d["defects"])
    p = os.path.join(RES, vfile)
    if not os.path.exists(p):
        print(f"  {name:26} MISSING {vfile}")
        continue
    raw = json.load(io.open(p, encoding="utf-8"))
    if idx is None:
        verdicts = raw["verdicts"] if "verdicts" in raw else raw["report"]["verdicts"]
        fc = raw.get("false_claims") or (raw.get("report") or {}).get("false_claims") or []
    else:
        rep = raw["reports"][idx]
        n = len(rep["defects"])
        verdicts = rep["verdicts"]
        fc = rep.get("false_claims") or []
    if len(verdicts) != n:
        print(f"  {name:26} SKIP {len(verdicts)} verdicts for {n} defects")
        continue
    c, w = score(verdicts, n)
    rows.append((name, n, c, w, len(fc)))
    print(f"  {name:26} {n:>3} defects  {c['yes']:>2}y {c['partial']:>2}p "
          f"{c['no']:>2}n  weighted {w:.3f}  strict {c['yes']/n:.3f}  "
          f"false {len(fc)}")

if not rows:
    sys.exit("no usable pairs")

print()
print(f"sources {len(rows)}   defects {sum(r[1] for r in rows)}")
tw = sum(r[1] * r[3] for r in rows) / sum(r[1] for r in rows)
ty = sum(r[2]["yes"] for r in rows) / len(rows)
print(f"aggregate weighted recall (defect-weighted): {tw:.3f}")
print(f"aggregate strict recall                    : {ty:.3f}")
ws = [r[3] for r in rows]
print()
print(f"spread across sources : {min(ws):.3f} to {max(ws):.3f}, "
      f"range {max(ws)-min(ws):.3f}, sd {statistics.stdev(ws):.3f}")
print("spread across runs of one source (arm D, 38 defects): 0.132, sd 0.068")
print()
print("If the two spreads are comparable, a single-program comparison is")
print("measuring the program as much as the design.")
print()
print("per-source detail:")
for name, n, c, w, fc in sorted(rows, key=lambda r: r[3]):
    print(f"  {name:26} {w:.3f}   {c['yes']:>2}/{n}")