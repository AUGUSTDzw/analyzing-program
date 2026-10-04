"""Verify candidate defects against the source, then merge them.

A defect added to the frozen list is worse than a defect missing from it: a
missing one costs recall, a wrong one penalises a correct report. So nothing is
merged on the strength of having been written down. Each candidate must clear
three checks:

  anchor      appears in the source, character for character
  identifier  the question names at least one identifier from its own anchor, so
              a report that found the defect has a token to be found by
  novelty     neither the anchor nor the question restates one of the twenty

Only then is the id assigned and the entry written, and the existing twenty keep
their ids so every verdict file already on disk stays valid.
"""
import io
import json
import os
import re
import sys

ROOT = sys.argv[1]
CAND = sys.argv[2]
SRC = os.path.join(ROOT, "Test-source", "real",
                   "Keremkoseoglu__ABAP-Library__functional__fi__ZCL_FI_TOOLKIT.abap")
DEF = os.path.join(ROOT, "skill", "analyzing-programs", "evals",
                   "zcl_fi_toolkit.defects.json")

src = io.open(SRC, encoding="utf-8", errors="replace").read()
src_flat = re.sub(r"\s+", " ", src)
cur = json.load(io.open(DEF, encoding="utf-8"))
cand = json.load(io.open(CAND, encoding="utf-8"))["new"]

existing_q = [d["question"].lower() for d in cur["defects"]]
existing_a = [(d.get("anchor") or "").lower() for d in cur["defects"]]

TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_~-]*")
STOP = {"does", "the", "report", "identify", "that", "and", "for", "with",
        "from", "any", "not", "are", "its", "it", "a", "an", "of", "to", "in",
        "is", "be", "on", "so", "by", "or", "at", "as", "this", "their",
        "while", "into", "than", "then", "which", "while", "up", "only"}

accepted, rejected = [], []
for c in cand:
    aid, q = c["anchor"], c["question"]
    reasons = []

    if re.sub(r"\s+", " ", aid).lower() not in src_flat.lower():
        reasons.append("anchor not found in the source")

    toks = {t.lower() for t in TOKEN.findall(q)} - STOP
    atoks = {t.lower() for t in TOKEN.findall(aid)}
    if not (toks & atoks):
        reasons.append("question names no identifier from its own anchor")

    if any(a and a in aid.lower() for a in existing_a):
        reasons.append("anchor restates an existing defect")
    if any(q.lower()[:60] in e or e[:60] in q.lower() for e in existing_q):
        reasons.append("question restates an existing defect")

    if reasons:
        rejected.append((c["id"], reasons))
    else:
        accepted.append(c)

print(f"candidates {len(cand)}, accepted {len(accepted)}, rejected {len(rejected)}")
print()
for cid, why in rejected:
    print(f"  REJECT {cid}: {'; '.join(why)}")
print()
for c in accepted:
    print(f"  accept {c['id']}  anchor {c['anchor'][:46]!r}")
print()

if not accepted:
    print("nothing merged")
    sys.exit(0)

n0 = len(cur["defects"])
ids = {d["id"] for d in cur["defects"]}
for c in accepted:
    assert c["id"] not in ids, f"id collision {c['id']}"
    cur["defects"].append({"id": c["id"], "area": c["area"],
                           "question": c["question"], "anchor": c["anchor"]})

NOTE = ("D21 onward added by reading the source: the list was too small for the "
        "measurement. Relative noise is absolute disagreement divided by defect "
        "count, so at 20 defects two reports differing by three items is 15 "
        "percent, which is the size of every effect this project has claimed. "
        "Judge variance was measured at zero over three independent judgements of "
        "one report, so the noise is generation and the only lever is the "
        "denominator.")
for key in ("_comment", "_schema"):
    if isinstance(cur.get(key), list):
        cur[key] = [x for x in cur[key] if not str(x).startswith("D21 onward")]
        cur[key].append(NOTE)
        print(f"note appended to {key}")
        break
else:
    cur["_note"] = NOTE
    print("note added under _note")
io.open(DEF, "w", encoding="utf-8").write(json.dumps(cur, ensure_ascii=False, indent=1))
print(f"{DEF}")
print(f"  {n0} -> {len(cur['defects'])} defects")