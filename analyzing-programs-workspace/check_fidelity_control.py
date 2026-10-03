"""Negative control for the fidelity check.

Injects one altered identifier into a known-clean report and confirms the check
notices, then confirms it clears again when the file is restored. A check that
flags faithful code is worse than no check, so it has to be shown to fire on a
real alteration and stay quiet otherwise.

The first two attempts at this control were themselves wrong: one read the row
for the wrong report, the other renamed an identifier inside a file whose blocks
the check skips. Both reported a failure that was not about the check.
"""
import io
import os
import re
import subprocess
import sys

QC = sys.argv[1]
SCRIPT = os.path.join(sys.argv[2], "check_code_fidelity.py")
ROOT = sys.argv[3]
REL = "Test-result/real/abapgit_flow_logic.skill.md"
WANT = os.path.basename(REL)

live = os.path.join(ROOT, REL)
orig = io.open(live, encoding="utf-8").read()


def row():
    out = subprocess.run([sys.executable, SCRIPT, QC, ROOT],
                         capture_output=True, text=True, encoding="utf-8").stdout
    for l in out.split("\n"):
        if WANT[:30] in l:
            return " ".join(l.split()[-4:]) if "absent" not in l else l.strip()[:70]
    return "?"


def absent():
    out = subprocess.run([sys.executable, SCRIPT, QC, ROOT],
                         capture_output=True, text=True, encoding="utf-8").stdout
    for l in out.split("\n"):
        if WANT[:30] in l:
            f = l.split()
            return f[1] + " absent " + f[2]
    return "?"


before = absent()
print("clean       :", before)

# rename inside a block that is a quote, not a risk-layer remediation snippet
sys.path.insert(0, sys.argv[1])
import report_qc
m = None
for cand in re.finditer(r"```abap\n(.*?)```", orig, re.S):
    if not report_qc.in_risk_layer(orig[:cand.start()]):
        m = cand
        break
if m is None:
    print("SKIP: no quotable block")
    sys.exit(1)

body = m.group(1)
tok = re.search(r"\b[a-z_][a-z0-9_]*(\-[a-z0-9_]+)?\b", body)
if not tok:
    print("SKIP: no identifier")
    sys.exit(1)
name = tok.group(0)
altered = body.replace(name, name + "_x", 1)
dirty = orig[:m.start(1)] + altered + orig[m.end(1):]
print(f"injected    : {name} -> {name}_x")

try:
    io.open(live, "w", encoding="utf-8").write(dirty)
    after = absent()
    print("after inject:", after)
finally:
    io.open(live, "w", encoding="utf-8").write(orig)

print("restored    :", absent())
ok = before != after
print()
print("control", "PASSED -- fires on a real alteration, clears when reverted"
      if ok else "FAILED -- blind to the alteration")


