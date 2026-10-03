"""Lines per subprogram in reports that actually finished.

Every generation failure died inside section 3, and size did not predict which
runs failed -- 1988, 2079 and 3257 line reports succeeded while 1464 and 1784
failed. So "count the lines and worry" is not a usable rule.

What is measurable is the rate: for reports that completed all six sections, how
many lines each declared subprogram cost. That converts "large inputs are hard"
into a number, and a number is something a reader can act on.
"""
import io
import os
import re
import statistics
import subprocess
import sys

sys.path.insert(0, sys.argv[1])
import report_qc

ROOT = sys.argv[2]
DIRS = ["Test-result/real", "Test-result/real2", "Test-result/real3",
        "Test-result/real4", "Test-result/staged"]
QC = os.path.join(sys.argv[1], "report_qc.py")


def guess_src(name, srcdir):
    base = re.sub(r"\.skill\.md$", "", name)
    obj = re.sub(r"^r[12]_|^v\d+(_\d+)?_", "", base).split("__")[-1]
    c = [f for f in os.listdir(srcdir) if f.endswith(".abap") and obj in f]
    return os.path.join(srcdir, max(c, key=len)) if c else None


rows = []
for d in DIRS:
    p = os.path.join(ROOT, d)
    if not os.path.isdir(p):
        continue
    srcdir = os.path.join(ROOT, "Test-source", "real")
    for f in sorted(os.listdir(p)):
        if not f.endswith(".skill.md"):
            continue
        fp = os.path.join(p, f)
        s = io.open(fp, encoding="utf-8").read()
        six = sum(1 for h in report_qc.SEC if h in s)
        sp = guess_src(f, srcdir)
        if not sp:
            continue
        src = io.open(sp, encoding="utf-8", errors="replace").read()
        sl = src.count("\n") + 1
        nl = s.count("\n") + 1
        # Six sections is not sufficient evidence of completion. A 465-line AVE
        # fragment carries all six and slipped through on the section count
        # alone; it is an inventory, not an analysis. Both signals are needed.
        if six < 6:
            continue
        if sl > 2000 and nl < sl / 20:
            continue                       # truncated: not a data point
        inv = report_qc.inventory(src)
        if not inv:
            continue                       # classic screen flow: no methods
        nl = s.count("\n") + 1
        i3 = s.find("## 三")
        j34 = s.find("\n## 四")
        sec3 = s[i3:j34] if (i3 >= 0 and j34 > i3) else ""
        nl3 = sec3.count("\n") + 1
        rows.append((f[:40], nl, len(inv), nl / len(inv), nl3 / len(inv)))

print(f"{'completed report':42}{'lines':>7}{'subs':>6}{'ln/sub':>8}{'sec3/sub':>10}")
print("-" * 74)
for f, nl, n, r, r3 in sorted(rows, key=lambda x: -x[2]):
    print(f"{f:42}{nl:>7}{n:>6}{r:>8.1f}{r3:>10.1f}")
print("-" * 74)
if rows:
    rates = [r for _, _, _, r, _ in rows]
    r3s = [r3 for _, _, _, _, r3 in rows]
    print(f"{'median':42}{'':>7}{'':>6}{statistics.median(rates):>8.1f}"
          f"{statistics.median(r3s):>10.1f}")
    print(f"{'range':42}{'':>7}{'':>6}{min(rates):>8.1f}-{max(rates):<6.1f}"
          f"{min(r3s):>6.1f}-{max(r3s):.1f}")
    med = statistics.median(rates)
    print()
    print(f"at the median {med:.0f} lines per subprogram, a single ~2000-line pass")
    print(f"covers about {2000/med:.0f} subprograms. Observed deaths at 925 and")
    print(f"1974 lines were both inside section 3, so treat this as an order of")
    print(f"magnitude rather than a budget.")
