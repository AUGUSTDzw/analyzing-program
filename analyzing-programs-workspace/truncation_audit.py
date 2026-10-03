"""Flag reports that were cut off mid-write, wherever they are sitting.

A truncated report is worse than a missing one: it is still a file, still gets
counted, and still looks like data. real2's AVE report is 464 lines for a
29.5k-line source and was sitting in real2/ rather than in _truncated/, so every
aggregate that included real2 scored it as a finished report. It contributed 14
Mermaid defects and zero A8 defects purely because it never got past three code
blocks.

Two independent signals, because either alone can be fooled:

  sections   a complete report has all six. Anything missing a later section
             while having an earlier one was cut.
  coverage   quoted abap blocks per 1000 source lines. A report that quotes
             almost nothing from a large source was cut, whatever its length.
"""
import io
import os
import re
import sys

sys.path.insert(0, sys.argv[1])
import report_qc

root = sys.argv[2]
SRCDIR = os.path.join(root, "Test-source", "real")
REPORTS = ["Test-result/real", "Test-result/real2", "Test-result/real3",
           "Test-result/real4"]

srcs = {}
for f in os.listdir(SRCDIR):
    if not f.endswith((".abap", ".clas.abap", ".fugr.abap")):
        continue
    stem = re.sub(r"\.skill\.md$", "", f)
    for pre in ("functional__", "src__"):
        stem = stem.replace(pre, "")
    srcs[f] = stem


def guess_source(rep_name):
    """Map a report filename back to its source by longest matching stem."""
    base = re.sub(r"\.skill\.md$", "", rep_name)
    base = re.sub(r"^r[12]_", "", base)
    base = re.sub(r"^v\d+(_\d+)?_", "", base)
    cands = [f for f, st in srcs.items() if st.endswith(base) or base.endswith(st)]
    if not cands:
        # reports are named after the object, sources after the whole path
        obj = base.split("__")[-1]
        cands = [f for f in os.listdir(SRCDIR)
                 if f.endswith(".abap") and obj in f]
    return max(cands, key=len) if cands else None


print(f"{'report':52}{'lines':>7}{'src':>8}{'sec':>5}{'blocks':>8}{'blk/1k':>9}  verdict")
print("-" * 96)
flagged = []
for d in REPORTS:
    p = os.path.join(root, d)
    if not os.path.isdir(p):
        continue
    for f in sorted(os.listdir(p)):
        if not f.endswith(".skill.md"):
            continue
        path = os.path.join(p, f)
        s = io.open(path, encoding="utf-8").read()
        nl = s.count("\n") + 1
        secs = sum(1 for h in report_qc.SEC if h in s)
        blocks = len(list(report_qc.source_blocks(s)))
        sf = guess_source(f)
        if sf:
            sl = io.open(os.path.join(SRCDIR, sf), encoding="utf-8",
                         errors="replace").read().count("\n") + 1
        else:
            sl = 0
        rate = blocks / max(1, sl) * 1000
        why = []
        if secs < 6:
            why.append(f"only {secs}/6 sections")
        if sl > 2000 and rate < 3:
            why.append(f"quotes {rate:.1f} blocks/1k src lines")
        if sl and nl < sl / 20:
            why.append(f"{nl} lines for a {sl}-line source")
        verdict = "TRUNCATED" if why else "ok"
        if why:
            flagged.append((d, f, "; ".join(why)))
        print(f"{f[:50]:52}{nl:>7}{sl:>8}{secs:>5}{blocks:>8}{rate:>9.1f}  {verdict}")

print()
if flagged:
    print(f"{len(flagged)} report(s) are truncated but not quarantined:")
    for d, f, why in flagged:
        print(f"  {d}/{f}")
        print(f"      {why}")
else:
    print("every report carries all six sections")
