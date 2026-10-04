"""Merge a partial judgement of the new defects into an existing verdict file.

The original twenty verdicts stay valid: ids were not renumbered, the old anchors
did not move, and judge repeatability was measured at zero variance. So a
twenty-defect judgement is extended by judging only what was added and
concatenating, rather than paying for a fresh read of the whole report.

Refuses to merge unless the new file covers exactly the ids that are missing. A
partial merge that silently leaves a hole would produce a score over a denominator
nobody intended, which is the failure this project has hit repeatedly.
"""
import io
import json
import os
import sys

DEF, base_path, new_path, out_path = sys.argv[1:5]
want = {d["id"] for d in json.load(io.open(DEF, encoding="utf-8"))["defects"]}

base = json.load(io.open(base_path, encoding="utf-8"))
new = json.load(io.open(new_path, encoding="utf-8"))

# The first twenty verdicts were recorded in the legacy judge shape, with the
# verdict object nested under `report`. Read either shape: extending a judgement
# must not require rewriting the record it extends, and the verdict content is
# identical either way.
base_report = base.get("report")
if isinstance(base_report, dict):
    base_report = base_report.get("path")
base_verdicts = base.get("verdicts")
if not base_verdicts and isinstance(base.get("report"), dict):
    base_verdicts = base["report"].get("verdicts") or {}

have = set(base_verdicts)
need = want - have
got = set(new.get("verdicts") or {})


def key(x):
    return int(x[1:])


print(f"reference list   : {len(want)} defects")
print(f"base verdict file: {len(have)}")
print(f"missing          : {len(need)}")
print(f"new file covers  : {len(got)}")

extra = got - need
overlap = got & have
if extra:
    print(f"  REJECT: new file judges ids that already exist: {sorted(extra, key=key)}")
    sys.exit(2)
if overlap:
    print(f"  note: {len(overlap)} re-judged id(s) ignored, the existing verdict stands")
if got != need:
    print(f"  REJECT: partial new judgement, missing {sorted(need - got, key=key)}")
    sys.exit(2)

bad = [f"{k}={v!r}" for k, v in new["verdicts"].items()
       if v not in ("yes", "partial", "no")]
if bad:
    print(f"  REJECT: verdict outside vocabulary: {', '.join(bad)}")
    sys.exit(2)

merged = {
    "report": base_report or new.get("report"),
    "verdicts": dict(base_verdicts),
    "evidence": dict(base.get("evidence") or {}),
    "false_claims": base.get("false_claims") or [],
}
merged["verdicts"].update(new["verdicts"])
merged["evidence"].update(new.get("evidence") or {})

c = {"yes": 0, "partial": 0, "no": 0}
for v in merged["verdicts"].values():
    c[v] += 1
n = len(merged["verdicts"])
w = (c["yes"] + 0.5 * c["partial"]) / n
print()
print(f"merged          : {n} defects  {c['yes']}y {c['partial']}p {c['no']}n")
print(f"recall          : {w:.3f} weighted   {c['yes']/n:.3f} strict")
io.open(out_path, "w", encoding="utf-8").write(
    json.dumps(merged, ensure_ascii=False, indent=1))
print(f"wrote           : {out_path}")