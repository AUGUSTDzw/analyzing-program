import io, os, re, sys

sys.path.insert(0, sys.argv[1])
import report_qc

ROOT = sys.argv[2]
SRC = os.path.join(ROOT, "Test-source", "real",
                   "Keremkoseoglu__ABAP-Library__functional__fi__ZCL_FI_TOOLKIT.abap")

# Every generation attempt on this file, in order, including the ones that wrote
# nothing. The record was being kept from memory before, which is how the v2 AVE
# fragment ended up sitting in real2/ looking like a finished report.
ATTEMPTS = [
    # (label, delivery method, relative path or None for "wrote nothing")
    ("v3 r1", "single", "Test-result/real3/r1_Keremkoseoglu__ZCL_FI_TOOLKIT.skill.md"),
    ("v3 r2", "single", "Test-result/real3/r2_Keremkoseoglu__ZCL_FI_TOOLKIT.skill.md"),
    ("v4 #1", "single", None), ("v4 #2", "single", None), ("v4 #3", "single", None),
    ("v4 #4", "single", "Test-result/real4/_truncated/v4_r2_Keremkoseoglu__ZCL_FI_TOOLKIT.skill.md"),
    ("v4 r1", "single", "Test-result/real4/_truncated/v4_r1_Keremkoseoglu__ZCL_FI_TOOLKIT.skill.md"),
    ("staged 1", "two-stage", "Test-result/staged/st1_Keremkoseoglu__ZCL_FI_TOOLKIT.skill.md"),
    ("staged 2", "two-stage", "Test-result/staged/st2_Keremkoseoglu__ZCL_FI_TOOLKIT.skill.md"),
    ("v1+gate 1", "two-stage", None), ("v1+gate 2", "two-stage", None),
    ("v1+gate 3", "two-stage", None),
    ("slice 1", "slice", "Test-result/isolated/slice_Keremkoseoglu__ZCL_FI_TOOLKIT.skill.md"),
    ("slice 2", "slice", "Test-result/isolated/slice2_Keremkoseoglu__ZCL_FI_TOOLKIT.skill.md"),
]

METHODS = ["single", "two-stage", "slice"]
tally = {m: [0, 0, 0] for m in METHODS}
print(f"{'attempt':12}{'method':11}{'lines':>7}{'sec':>5}  outcome")
print("-" * 66)
for name, method, rel in ATTEMPTS:
    t = tally[method]
    if rel is None or not os.path.exists(os.path.join(ROOT, rel)):
        t[2] += 1
        print(f"{name:12}{method:11}{'-':>7}{'-':>5}  no file written")
        continue
    s = io.open(os.path.join(ROOT, rel), encoding="utf-8").read()
    nl = s.count("\n") + 1
    secs = sum(1 for h in report_qc.SEC if h in s)
    if secs == 6:
        t[0] += 1
        out = "complete"
    else:
        t[1] += 1
        out = f"truncated ({secs}/6)"
    print(f"{name:12}{method:11}{nl:>7}{secs:>5}  {out}")
print("-" * 66)
print(f"{'method':12}{'complete':>10}{'truncated':>11}{'silent':>8}{'n':>5}{'rate':>8}")
for m in METHODS:
    ok, part, none = tally[m]
    n = ok + part + none
    print(f"{m:12}{ok:>10}{part:>11}{none:>8}{n:>5}{ok/n*100:>7.0f}%")
so = sum(tally[m][0] for m in METHODS)
sn = sum(sum(tally[m]) for m in METHODS)
print("-" * 66)
print(f"all methods: {so}/{sn} complete = {so/sn*100:.0f}%")