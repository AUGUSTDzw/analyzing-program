import io, json, os, subprocess, sys, tempfile
SCRIPTS, SKILL = sys.argv[1], sys.argv[2]
REP = os.path.join(SKILL, "references", "example-report.md")
good = io.open(REP, encoding="utf-8").read().split("\n")
tmp = tempfile.mkdtemp()
defs = [{"id": "D1", "area": "a", "question": "q1"},
        {"id": "D2", "area": "b", "question": "q2"},
        {"id": "D3", "area": "c", "question": "q3"}]
dp = os.path.join(tmp, "d.json")
io.open(dp, "w", encoding="utf-8").write(json.dumps({"source": "x.abap", "defects": defs}, ensure_ascii=False))
EV = {d["id"]: {"report_line": 12, "quote": good[11].strip()[:40]} for d in defs}

def vfile(name, mutate=None):
    v = {"report": REP, "verdicts": {"D1": "yes", "D2": "yes", "D3": "no"},
         "evidence": {k: dict(x) for k, x in EV.items()}, "false_claims": []}
    if mutate: mutate(v)
    p = os.path.join(tmp, name + ".json")
    io.open(p, "w", encoding="utf-8").write(json.dumps(v, ensure_ascii=False))
    return p

def ok(path):
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "evaluate.py"), "score",
                        "--defects", dp, "--verdicts", path],
                       capture_output=True, text=True, encoding="utf-8")
    return r.returncode == 0, r.stdout

CASES = [
    ("ok", None, True),
    ("missing_evidence", lambda v: v.pop("evidence"), False),
    ("evidence_wrong_id", lambda v: v["evidence"].pop("D1"), False),
    ("line_out_of_range", lambda v: v["evidence"]["D1"].update(report_line=99999), False),
    ("quote_not_on_line", lambda v: v["evidence"]["D1"].update(quote="not on that line at all"), False),
    ("line_not_a_number", lambda v: v["evidence"]["D1"].update(report_line="twelve"), False),
    ("no_needs_no_evidence", lambda v: (v["verdicts"].update(D3="no"), v["evidence"].pop("D3")), True),
]
print(f"{'case':28}{'expected':>10}{'got':>9}  result")
print("-" * 70)
allok = True
for name, mut, should in CASES:
    accepted, out = ok(vfile(name, mut))
    good_ = accepted == should
    allok &= good_
    print(f"{name:28}{'accept' if should else 'reject':>10}{'accept' if accepted else 'reject':>9}  {'ok' if good_ else 'MISMATCH'}")
    if not good_ and not should:
        why = [l.strip() for l in out.split("\n") if l.strip().startswith("-")]
        if why: print(f"{'':50}{why[0][:52]}")
print("-" * 70)
print("evidence requirement", "WORKS" if allok else "BROKEN")
