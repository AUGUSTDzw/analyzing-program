"""Regression: the skill's own worked example must satisfy the rule it teaches.

This is the first check in this project that validates a skill change without
generating a report and without a model.

The v3 evidence was that the model follows the example rather than the rule: a
prohibition was added and changed nothing, because the example never showed the
shape the prohibition forbade. That makes the example load-bearing, so the
example itself is testable. Run the gate's own A8 logic over the section the
skill ships.

If the teaching example fails the gate the model is asked to pass, every report
imitating it inherits the failure, and no rewording of the rule will help. That
is checkable in under a second, so it runs on every edit from now on.

It also pins the property the v4 change was actually after: a step holding two
code blocks, each carrying its own three layers. If a later edit collapses step
2 back to one block, or moves the labels after the last block only, this fails.
"""
import io
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "skill", "analyzing-programs", "scripts"))
import report_qc

SKILL = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "skill", "analyzing-programs", "SKILL.md")

s = io.open(SKILL, encoding="utf-8").read()
start = s.find("## Three-Layer Format per Code Block")
end = s.find("\n## ", start + 5)
sec = s[start:end if end > 0 else len(s)]

blocks = list(report_qc.source_blocks(sec))
fails = []
for i, (st, en, gap) in enumerate(blocks, 1):
    missing = [l for l in report_qc.LAYERS if l not in gap]
    if missing:
        head = sec[:st].rstrip().split("\n")[-1][:50]
        fails.append(f"block {i} (after {head!r}) missing " + " ".join(missing))

# the v4 property: some step in the example holds two blocks, not one
step2 = re.search(r"####\s*\u2461[^\n]*\n(.*?)(?=\n####|\n##\s|\Z)", sec, re.S)
two_block_step = bool(step2 and step2.group(1).count("```abap") >= 2)

print(f"three-layer section: {len(sec)} chars, {len(blocks)} source block(s)")
for f in fails:
    print("  FAIL", f)
if not fails:
    print("  ok    every block in the example carries all three layers")
print(f"  {'ok   ' if two_block_step else 'FAIL '} "
      f"a step in the example holds two code blocks "
      f"({step2.group(1).count('```abap') if step2 else 0} in step 2)")

# The shipped exemplar must keep passing the gate. It was the only candidate that
# was both complete and gate-clean across all 23 reports on disk, so if a later
# edit breaks it there is nothing to fall back to, and SKILL.md points at it as
# the authoritative rendering of the format.
EXEMPLAR = os.path.join(os.path.dirname(SKILL), "references", "example-report.md")
if os.path.exists(EXEMPLAR):
    import subprocess
    r = subprocess.run([sys.executable, os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "skill", "analyzing-programs", "scripts", "report_qc.py"), EXEMPLAR],
        capture_output=True, text=True, encoding="utf-8")
    ok = r.stdout.startswith("PASS")
    detail = r.stdout.strip().split("\n")[0] if not ok else ""
    print(f"  {'ok   ' if ok else 'FAIL '} "
          f"references/example-report.md still passes the gate"
          + (f"  ({detail})" if not ok else ""))
    if not ok:
        sys.exit(1)

sys.exit(1 if fails or not two_block_step else 0)
