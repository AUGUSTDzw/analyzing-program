"""Does gate_ab.py's criterion actually discriminate, or only agree with itself?

    python gate_ab_selftest.py SKILL_SCRIPTS

Run gate_ab.py against itself on iteration-8 with both arms set to `with_skill`
and it reproduces the known numbers -- which is also what it would print if the
sign test were wired up backwards, or if `defects()` always returned 0. Agreement
on a degenerate input proves nothing.

So four synthetic A/Bs are built from real iteration-8 reports, each with a known
answer, and gate_ab.py must reach it:

  tie        arm B identical to arm A          -> NOT MET   (p = 1.0, delta 0)
  fix        arm B has arm A's defects removed -> MET        (7 -> 0, 6/0, p=0.031)
  partial    one of six fixed                  -> NOT MET   (p >= 0.05 at 1 win)
  regress    arm B gains a defect              -> NOT MET   (losses > wins)
  unpaired   one report missing from arm B     -> INCOMPLETE, exit 1
  truncated  a report stops mid-section-three  -> EXCLUDED before aggregation

`fix` is the one that matters. It is the only case where the pre-registered bar
is reachable, and reaching it is the whole justification for setting the bar
there rather than above the ceiling.
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

SCRIPTS = sys.argv[1]
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
GATE_AB = os.path.join(HERE, "gate_ab.py")
SRC_WS = os.path.join(REPO, "analyzing-programs-workspace", "iteration-8")
ARM_A, ARM_B = "with_skill_b8f84e8", "with_skill_718f5988"

# A report with a removable A8 defect: two adjacent abap fences with no prose
# between them. Stripping the middle fence leaves one block with its three
# layers, which passes. Written by hand rather than by mutating a real report so
# the injected defect is unambiguous.
BROKEN = """# T

## 一、概述

x

## 二、执行流程

### 责任链表

| 子程序 | 触发者 |
|---|---|
| `Z_FOO` | 事务 |

## 三、分组分析

### 3.1 步骤① 取数（函数模块 `Z_FOO`）

```abap
DATA lv_a TYPE i.
```

```abap
SELECT foo FROM bar INTO @DATA(ls_foo).
```

**做什么** — 取一行。
**为什么** — 索引命中。
**风险与改进** — 未判空。

## 四、流程图

```mermaid
flowchart TD
  A["Z_FOO"] --> B["输出"]
```

## 五、问题清单

### 🔴 P0 业务正确性

| # | 所在子程序 | 问题 | 建议 |
|---|---|---|---|
| P0-1 | `Z_FOO` | 未判空 | 补 `CHECK` |

### 🟠 P1 健壮性

### 🟡 P2 性能

### 🟢 P3 扩展

## 六、整体评价

一句结论。
"""

fails = []


# A report that stops inside section three, which is where every observed failure
# died. It keeps its heading and its first code block, so it looks like data and
# it is exactly the shape that was once counted as a finished report.
# Split on the section-four marker rather than its full title, so this keeps
# working if the wording in BROKEN changes -- an earlier version split on a
# heading string that was not there and silently produced an untruncated copy.
FRAGMENT = BROKEN.split("## 四")[0]
assert "## 六" not in FRAGMENT and "## 三" in FRAGMENT, "fixture must stop in 三"


def check(cond, msg, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'}  {msg}" + (f"   {detail}" if detail else ""))
    if not cond:
        fails.append(msg)


def build(tmp):
    """A copy of iteration-8's with_skill reports as two named arms."""
    ws = os.path.join(tmp, "ws")
    os.makedirs(ws)
    for ev in sorted(os.listdir(SRC_WS)):
        src = os.path.join(SRC_WS, ev, "with_skill")
        if not os.path.isdir(src):
            continue
        for arm in (ARM_A, ARM_B):
            shutil.copytree(os.path.join(src), os.path.join(ws, ev, arm))
    return ws


def run(ws):
    r = subprocess.run([sys.executable, GATE_AB, SCRIPTS, ws, ARM_A, ARM_B],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    return r.returncode, r.stdout


def inject_broken(ws, n=1):
    """Overwrite n reports in arm B with the BROKEN fixture."""
    evs = [e for e in sorted(os.listdir(ws))
           if os.path.isdir(os.path.join(ws, e, ARM_B))]
    for ev in evs[:n]:
        for run in sorted(os.listdir(os.path.join(ws, ev, ARM_B))):
            d = os.path.join(ws, ev, ARM_B, run, "outputs")
            if os.path.isdir(d):
                io.open(os.path.join(d, "report.md"), "w",
                        encoding="utf-8").write(BROKEN)
                return os.path.join(ws, ev, ARM_B, run, "outputs", "report.md")
    return None


def repair_arm_b(ws, limit=None):
    """Replace every arm-B report that arm A has failing with one that passes.

    The replacement is a report that the gate scores clean, taken from anywhere
    in arm A. An earlier version copied the failing report's *sibling run*, which
    is wrong whenever both runs of an eval fail -- eval-7 does, twice -- so the
    "repaired" copy arrived carrying its sibling's defect and the run reported 4
    wins instead of 6. This is a test-fixture bug, but it is also a fact about
    the real round worth stating: when both runs of one eval fail, repairing one
    of them buys at most one win, so the win ceiling is below the naive 9.

    Content is deliberately borrowed across evals. This exercises the arithmetic,
    not the prose; the gate is asked the same question either way.
    """
    sys.path.insert(0, SCRIPTS)
    import report_qc
    clean = None
    for ev in sorted(os.listdir(ws)):
        a = os.path.join(ws, ev, ARM_A)
        if not os.path.isdir(a):
            continue
        for run in sorted(os.listdir(a)):
            p = os.path.join(a, run, "outputs", "report.md")
            if os.path.isfile(p) and not report_qc.check(
                    io.open(p, encoding="utf-8").read()):
                clean = io.open(p, encoding="utf-8").read()
                break
        if clean:
            break
    if clean is None:
        return -1

    fixed = 0
    for ev in sorted(os.listdir(ws)):
        a, b = os.path.join(ws, ev, ARM_A), os.path.join(ws, ev, ARM_B)
        if not (os.path.isdir(a) and os.path.isdir(b)):
            continue
        for run in sorted(os.listdir(a)):
            pa = os.path.join(a, run, "outputs", "report.md")
            pb = os.path.join(b, run, "outputs", "report.md")
            if not (os.path.isfile(pa) and os.path.isfile(pb)):
                continue
            if report_qc.check(io.open(pa, encoding="utf-8").read()):
                io.open(pb, "w", encoding="utf-8").write(clean)
                fixed += 1
                if limit and fixed >= limit:
                    return fixed
    return fixed


def nums(out):
    """(defects_a, defects_b, wins, losses, ties, p) parsed back out of the run."""
    da = db = w = l = t = None
    p = None
    m = re.search(r"defect instances\s+%s\s+(\d+)\s+%s\s+(\d+)" % (ARM_A, ARM_B), out)
    if m:
        da, db = int(m.group(1)), int(m.group(2))
    m = re.search(r"better on (\d+), worse on (\d+), tied (\d+)", out)
    if m:
        w, l, t = int(m.group(1)), int(m.group(2)), int(m.group(3))
    m = re.search(r"p = ([0-9.]+)", out)
    if m:
        p = float(m.group(1))
    return da, db, w, l, t, p


def main():
    tmp = tempfile.mkdtemp()

    print("degenerate input: both arms are the same directory")
    print("-" * 74)
    ws = build(tmp)
    rc, out = run(ws)
    da, db, w, l, t, p = nums(out)
    check((da, db) == (7, 7), "7 defect instances on both arms", f"{da}/{db}")
    check((w, l, t) == (0, 0, 26), "26 pairs, all tied", f"{w}/{l}/{t}")
    check(rc == 1, "exit 1 -- a tie is not a pass", f"rc={rc}")

    print()
    print("arm B is a copy, then its defects are repaired: the fix case")
    print("-" * 74)
    ws2 = os.path.join(tmp, "ws2")
    shutil.copytree(ws, ws2)
    fixed = repair_arm_b(ws2)
    rc, out = run(ws2)
    da, db, w, l, t, p = nums(out)
    check(fixed == 6, "6 failing reports identified and replaced", f"fixed={fixed}")
    check(db == 0, "arm B now carries 0 defect instances", f"{db}")
    check(w == 6 and l == 0, "6 wins, 0 losses", f"{w}/{l}")
    check(p is not None and p < 0.05, "sign test reaches p<0.05",
          f"p={p}")
    check(rc == 0, "exit 0 -- criterion MET", f"rc={rc}")
    check("CRITERION: MET" in out, "and says so in words")

    print()
    print("one of the six repaired: below the bar, and must NOT be called a pass")
    print("-" * 74)
    ws3 = os.path.join(tmp, "ws3")
    shutil.copytree(ws, ws3)
    repair_arm_b(ws3, limit=1)
    rc, out = run(ws3)
    da, db, w, l, t, p = nums(out)
    check((w, l) == (1, 0), "1 win, 0 losses", f"{w}/{l}")
    check(p is not None and p >= 0.05, "p is not significant", f"p={p}")
    check(rc == 1, "exit 1 -- NOT MET", f"rc={rc}")
    check("power is not the" in out or "not on enough pairs" in out,
          "and the reason given is the pair count, not the defect total")

    print()
    print("arm B gains a defect arm A does not have: the regression case")
    print("-" * 74)
    ws4 = os.path.join(tmp, "ws4")
    shutil.copytree(ws, ws4)
    inject_broken(ws4, 1)
    rc, out = run(ws4)
    da, db, w, l, t, p = nums(out)
    check(db > da, "arm B carries more defect instances", f"{da} -> {db}")
    check(l > 0, "at least one loss", f"w={w} l={l}")
    check(rc == 1, "exit 1 -- NOT MET", f"rc={rc}")
    check("does not carry strictly fewer" in out, "and says which half failed")

    print()
    print("a report present in one arm only: survivorship guard")
    print("-" * 74)
    ws5 = os.path.join(tmp, "ws5")
    shutil.copytree(ws, ws5)
    ev = sorted(os.listdir(ws5))[0]
    run1 = sorted(os.listdir(os.path.join(ws5, ev, ARM_B)))[0]
    os.remove(os.path.join(ws5, ev, ARM_B, run1, "outputs", "report.md"))
    rc, out = run(ws5)
    check("UNPAIRED" in out, "the unpaired report is reported, not dropped")
    check("INCOMPLETE" in out, "and the run is refused")
    check(rc == 1, "exit 1", f"rc={rc}")

    print()
    print("a report that stops mid-section-three is excluded, not counted")
    print("-" * 74)
    ws6 = os.path.join(tmp, "ws6")
    shutil.copytree(ws, ws6)
    target = None
    for ev6 in [e for e in sorted(os.listdir(ws6))
                if os.path.isdir(os.path.join(ws6, e, ARM_B))]:
        for rk in sorted(os.listdir(os.path.join(ws6, ev6, ARM_B))):
            d = os.path.join(ws6, ev6, ARM_B, rk, "outputs")
            if os.path.isdir(d):
                target = os.path.join(d, "report.md")
                break
        if target:
            break
    io.open(target, "w", encoding="utf-8").write(FRAGMENT)
    rc, out = run(ws6)
    check("truncated: 1" in out, "the fragment is identified as truncated")
    check("EXCLUDED" in out, "and named in the output")
    check("25 after" in out and "excluding truncated" in out,
          "the pair count drops from 26 to 25")
    check("excluded (truncated)" in out, "and the exclusion is listed by path")
    da, db, w, l, t, _p = nums(out)
    check(db < da or (w == 0 and l == 0),
          "the fragment does not enter the sign test",
          f"defects {da}->{db}, w={w} l={l}")

    print()
    print("-" * 74)
    if fails:
        print(f"{len(fails)} check(s) failed:")
        for f in fails:
            print("  -", f)
        return 1
    print("gate_ab.py discriminates in every direction, including the one that matters")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())