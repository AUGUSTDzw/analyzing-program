"""Third arm: v1 plus the fidelity diagnostic only, with no format enforcement.

The isolation run found -35 points of strict recall at p=0.0215 between v1 and
v1-plus-gate, and the fidelity diagnostic was in both arms, so it was never
isolated. Format enforcement looks like the harmful half: A8 fell to 0 while
recall fell. But the fidelity diagnostic has a separate kind of value, observed
once: in the slice run it named three infidelities the subagent had just
introduced and the subagent corrected all three against the source.

If this arm lands near v1's 0.700, format enforcement is the whole cost and the
fidelity diagnostic is free. If it lands near v1+gate's 0.350, then running any
checker inside the generation loop costs recall, and the diagnostic should be
reported to the reader rather than fed back to the writer.

Built from the same v1 blob as the other arm, so the three arms differ only in
step 6.
"""
import io
import os
import subprocess
import sys

REPO, OUT = sys.argv[1], sys.argv[2]
V1 = "2cced57"
PATH = "skill/analyzing-programs/SKILL.md"

v1 = subprocess.run(["git", "-C", REPO, "cat-file", "blob", f"{V1}:{PATH}"],
                    capture_output=True).stdout.decode("utf-8")

STEP6 = """\
6. **只核一遍引文忠实性**：写完运行
   `python scripts/report_qc.py --fidelity-only <报告路径> <源码路径>`。
   它只回答一件事：**你引用的语句是否逐字存在于源码里**。
   若报告某处引用了源码里没有的语句，对照源码改正，然后继续。
   这一步**不涉及**六节结构、三层标签、优先级分桶、Mermaid 或位置标签 ——
   那些不归它管，本步骤也不会因此要求你改写它们。
   闸门只管引文。**分析是否正确、漏没漏，它答不了** —— 那需要对着冻结缺陷清单判分。
"""

k = v1.find("## Analysis Flow")
m = v1.find("\n## ", k + 5)
variant = v1[:m] + "\n" + STEP6 + v1[m:]
io.open(OUT, "w", encoding="utf-8", newline="\n").write(variant)

print(f"v1      {len(v1)} bytes, {v1.count(chr(10))+1} lines")
print(f"arm 3   {len(variant)} bytes, {variant.count(chr(10))+1} lines, "
      f"+{len(variant)-len(v1)}")
print()
print("step 6 of this arm:")
for l in STEP6.rstrip().split("\n"):
    print("   ", l[:96])
print()
import re
print("headings, v1 vs arm 3:")
for tag, t in (("v1  ", v1), ("arm3", variant)):
    print(f"  {tag}  {len(re.findall(r'^## ', t, re.M))}")
print()
for probe, want in [("过一遍确定性闸门", False), ("--fidelity-only", True),
                    ("一步两块", False), ("这四问", False)]:
    got = probe in variant
    print(f"  {'ok  ' if got == want else 'FAIL'} {probe:22} present={got} want={want}")