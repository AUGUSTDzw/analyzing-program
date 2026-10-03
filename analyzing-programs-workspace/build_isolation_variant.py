"""Build the isolation variant: v1's SKILL.md plus only the gate step.

To attribute the recall drop, three things have to be separated. v1 is
2cced57, whose blob hashes to b8f84e8... -- the same file the v1 reports were
generated from, so this is v1 and not an approximation of it.

Added: step 6, the gate instruction, verbatim from the current skill. Nothing
else. No A8 template change, no activation questions. Everything outside the
instruction file -- report_qc.py, evaluate.py, evals/, references/ -- stays put
in both arms, so it cannot be the variable.
"""
import io
import os
import subprocess
import sys

REPO, OUT = sys.argv[1], sys.argv[2]
V1 = "2cced57"
CUR = "faa8643"
PATH = "skill/analyzing-programs/SKILL.md"


def blob(commit):
    return subprocess.run(["git", "-C", REPO, "cat-file", "blob", f"{commit}:{PATH}"],
                          capture_output=True).stdout.decode("utf-8")


v1 = blob(V1)
cur = blob(CUR)

# lift step 6 out of the current skill, unchanged
i = cur.find("6. **过一遍确定性闸门**")
if i < 0:
    sys.exit("could not find step 6 in the current skill")
j = cur.find("\n## ", i)
step6 = cur[i:j if j > 0 else len(cur)].rstrip()
print(f"step 6 lifted verbatim, {len(step6)} chars\n")

# v1's flow section ends before its next heading
k = v1.find("## Analysis Flow")
m = v1.find("\n## ", k + 5)
head, tail = v1[:m], v1[m:]

variant = head + "\n" + step6 + "\n" + tail
io.open(OUT, "w", encoding="utf-8", newline="\n").write(variant)

print(f"v1          {len(v1):>6} bytes, {v1.count(chr(10))+1} lines")
print(f"variant     {len(variant):>6} bytes, {variant.count(chr(10))+1} lines")
print(f"added       {len(variant)-len(v1):>6} bytes")
print()
print("section headings, v1 vs variant:")
import re
for tag, t in (("v1     ", v1), ("variant", variant)):
    hs = re.findall(r"^## (.+)$", t, re.M)
    print(f"  {tag}  {len(hs)}  {' | '.join(h[:26] for h in hs)}")
print()
for probe in ["过一遍确定性闸门", "一步两块", "这四问", "声明过"]:
    print(f"  {'present' if probe in variant else 'ABSENT ':8} {probe}")
