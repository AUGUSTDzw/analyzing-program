"""The validation in evaluate.py must actually reject. Four malformed verdict
files, each of which a laxer script would have scored silently.

An earlier merge script in this project clobbered its aggregate without raising,
and the only reason it was caught was that someone recomputed the number by hand.
A gate that has never been seen to refuse is not known to work.
"""
import io
import json
import os
import subprocess
import sys
import tempfile

EVAL = sys.argv[1]
DEFS = sys.argv[2]
GOOD = sys.argv[3]

base = json.load(io.open(GOOD, encoding="utf-8"))
tmp = tempfile.mkdtemp()


def variant(name, mutate):
    v = json.loads(json.dumps(base))
    mutate(v)
    p = os.path.join(tmp, name + ".json")
    io.open(p, "w", encoding="utf-8").write(json.dumps(v, ensure_ascii=False))
    return p


def drop_one(v):
    v["verdicts"].pop("D7")


def bad_value(v):
    v["verdicts"]["D7"] = "maybe"


def unknown_id(v):
    v["verdicts"]["D99"] = "no"


def bad_false_claim(v):
    v["false_claims"] = [{"claim": "something"}]


CASES = [
    ("complete", None, True),
    ("missing_one_defect", drop_one, False),
    ("verdict_out_of_vocabulary", bad_value, False),
    ("verdict_for_unknown_defect", unknown_id, False),
    ("false_claim_missing_why_wrong", bad_false_claim, False),
]

print(f"{'case':34}{'expected':>10}{'got':>8}  result")
print("-" * 78)
allok = True
for name, mut, should_pass in CASES:
    p = GOOD if mut is None else variant(name, mut)
    r = subprocess.run([sys.executable, EVAL, "score", "--defects", DEFS,
                        "--verdicts", p], capture_output=True, text=True,
                       encoding="utf-8")
    accepted = r.returncode == 0
    ok = accepted == should_pass
    allok &= ok
    print(f"{name:34}{'accept' if should_pass else 'reject':>10}"
          f"{'accept' if accepted else 'reject':>8}  "
          f"{'ok' if ok else 'MISMATCH'}")
    if not should_pass:
        first = [l for l in r.stdout.split("\n") if l.strip().startswith("-")]
        if first:
            print(f"{'':54}{first[0].strip()[:60]}")
print("-" * 78)
print("validation", "WORKS -- rejects every malformed file"
      if allok else "BROKEN -- a malformed file was accepted")
