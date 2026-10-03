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
    ("v3 r1", "Test-result/real3/r1_Keremkoseoglu__ZCL_FI_TOOLKIT.skill.md"),
    ("v3 r2", "Test-result/real3/r2_Keremkoseoglu__ZCL_FI_TOOLKIT.skill.md"),
    ("v4 #1", None), ("v4 #2", None), ("v4 #3", None),
    ("v4 #4", "Test-result/real4/_truncated/v4_r2_Keremkoseoglu__ZCL_FI_TOOLKIT.skill.md"),
    ("v4 r1", "Test-result/real4/_truncated/v4_r1_Keremkoseoglu__ZCL_FI_TOOLKIT.skill.md"),
    ("staged 1", "Test-result/staged/st1_Keremkoseoglu__ZCL_FI_TOOLKIT.skill.md"),
    ("staged 2", "Test-result/staged/st2_Keremkoseoglu__ZCL_FI_TOOLKIT.skill.md"),
    ("v1+gate 1", None), ("v1+gate 2", None), ("v1+gate 3", None),
]

ok = part = none = 0
print(f"{'attempt':12}{'lines':>7}{'sec':>5}  outcome")
print("-" * 62)
for name, rel in ATTEMPTS:
    if rel is None or not os.path.exists(os.path.join(ROOT, rel)):
        none += 1
        print(f"{name:12}{'-':>7}{'-':>5}  no file written")
        continue
    s = io.open(os.path.join(ROOT, rel), encoding="utf-8").read()
    nl = s.count("\n") + 1
    secs = sum(1 for h in report_qc.SEC if h in s)
    if secs == 6:
        ok += 1
        out = "complete"
    else:
        part += 1
        out = f"truncated ({secs}/6 sections)"
    print(f"{name:12}{nl:>7}{secs:>5}  {out}")
tot = ok + part + none
print("-" * 62)
print(f"{tot} attempts: {ok} complete, {part} truncated, {none} wrote nothing")
print(f"complete rate {ok/tot*100:.0f}%")