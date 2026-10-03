"""Per-file defect matrix: only files present in more than one variant."""
import collections
import io
import os
import re
import subprocess
import sys

QC = sys.argv[1]
root = sys.argv[2]
DIRS = [("v1", "Test-result/real"), ("v2", "Test-result/real2"),
        ("v3", "Test-result/real3"), ("v4", "Test-result/real4")]


def stem(n):
    """Strip run prefixes and org/repo prefixes so the same source lines up.

    The same file is named Keremkoseoglu__ABAP-Library__ZCL_FI_TOOLKIT under v1
    but Keremkoseoglu__ZCL_FI_TOOLKIT under v2, so dropping only the first
    segment left them as two different rows.
    """
    n = re.sub(r"\.skill\.md$", "", n)
    n = re.sub(r"^r[12]_", "", n)
    n = re.sub(r"^v4(_\d+)?_", "", n)
    while "__" in n:
        head, _, tail = n.partition("__")
        if not tail:
            break
        n = tail
    return n


sys.path.insert(0, os.path.dirname(QC))
import report_qc

SRCDIR = os.path.join(root, "Test-source", "real")


def guess_src(name):
    base = re.sub(r"\.skill\.md$", "", name)
    obj = re.sub(r"^r[12]_|^v\d+(_\d+)?_", "", base).split("__")[-1]
    c = [f for f in os.listdir(SRCDIR) if f.endswith(".abap") and obj in f]
    return os.path.join(SRCDIR, c[0]) if c else None


def truncated(path):
    """A fragment cannot be compared against a finished report."""
    s = io.open(path, encoding="utf-8").read()
    if sum(1 for h in report_qc.SEC if h in s) < 6:
        return "cut mid-write (fewer than six sections)"
    sp = guess_src(os.path.basename(path))
    if sp:
        sl = io.open(sp, encoding="utf-8", errors="replace").read().count("\n") + 1
        if sl and s.count("\n") + 1 < sl / 20:
            return f"cut mid-write ({s.count(chr(10))+1} lines for a {sl}-line source)"
    return None


grid = {}
skipped = []
for ver, d in DIRS:
    p = os.path.join(root, d)
    if not os.path.isdir(p):
        continue
    files = sorted(f for f in os.listdir(p) if f.endswith(".skill.md"))
    if not files:
        continue
    out = subprocess.run([sys.executable, QC] + [os.path.join(p, f) for f in files],
                         capture_output=True, text=True, encoding="utf-8").stdout
    pending = collections.Counter()

    for ln in out.split("\n"):
        d2 = re.match(r"^\s+(sec|prow|buck|ln|mm|A8-\w+)\s", ln)
        if d2:
            # report_qc prints a report's defect lines BEFORE its FAIL line, so
            # they belong to the FAIL that follows, not the one before.
            pending[d2.group(1)] += 1
            pending["total"] += 1
            continue
        m = re.match(r"^(PASS|FAIL)\s+(\S+)", ln)
        if m:
            n = re.search(r"\((\d+) defect", ln)
            rec = collections.Counter(pending)
            if n:
                rec["total"] = int(n.group(1))
            why = truncated(os.path.join(p, m.group(2)))
            if why:
                skipped.append((ver, m.group(2), why))
            else:
                grid.setdefault(stem(m.group(2)), {})[ver] = rec["total"]
            pending = collections.Counter()
    if pending:
        sys.stderr.write("WARNING: %d unattributed defect line(s)\n" % sum(
            1 for k in pending if k != "total"))

if skipped:
    print("excluded as fragments, not comparable to a finished report:")
    for ver, f, why in skipped:
        print(f"  {ver:5} {f[:60]:62} {why}")
    print()

shared = {k: v for k, v in grid.items() if len(v) > 1}
vers = [v for v, _ in DIRS if any(v in d for d in shared.values())]
w = max(len(k) for k in shared) + 2
print("file".ljust(w) + "".join(v.rjust(6) for v in vers) + "   note")
print("-" * (w + 6 * len(vers) + 24))
for k in sorted(shared, key=lambda x: -max(shared[x].values())):
    d = shared[k]
    cells = "".join(str(d.get(v, "-")).rjust(6) for v in vers)
    note = ""
    vals = [d[v] for v in vers if v in d]
    if len(vals) > 1:
        note = f"best={min(vals)} worst={max(vals)} spread={max(vals)-min(vals)}"
    print(k[:w - 2].ljust(w) + cells + "   " + note)
print()
print("files compared:", len(shared), " of", len(grid))
