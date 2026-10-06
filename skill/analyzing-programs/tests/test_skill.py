#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Self-contained checks for the shipped scripts. No project data required.

    python tests/test_skill.py

A gate that has never been seen to refuse is not known to work. That is not a
general worry here, it is this project's record: three merge scripts failed
silently, and one was caught only because somebody recomputed the total by hand.
So the tests below are mostly about the failure paths, not the happy one.

Everything is built in a temp directory. Nothing outside this skill folder is
read or written.

Encoding is forced in two places because the default Windows console breaks this
file in two distinct ways. Reading a child that encoded its output as cp936 with
encoding="utf-8" raised UnicodeDecodeError and killed the run at check 5; printing
the contract's bucket emoji to a cp936 stdout raised UnicodeEncodeError. So the
child is given PYTHONIOENCODING and this process reconfigures its own streams.
"""
import io
import json
import os
import subprocess
import sys
import tempfile

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
QC = os.path.join(SKILL, "scripts", "report_qc.py")
EVAL = os.path.join(SKILL, "scripts", "evaluate.py")
EXEMPLAR = os.path.join(SKILL, "references", "example-report.md")

FAILS = []


def check(cond, label, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f"   {detail}" if detail else ""))
    if not cond:
        FAILS.append(label)


def run(*args):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    return subprocess.run([sys.executable] + list(args), capture_output=True,
                          text=True, encoding="utf-8", env=env)


def brief_report():
    """A minimal report the gate should accept."""
    return """# T 分析报告

## 一、概述

解决什么问题。

## 二、执行流程

### 责任链表

| 子程序 | 触发者 |
|---|---|
| `Z_FOO` | 事务 |

## 三、分组分析

### 3.1 步骤① 取数（函数模块 `Z_FOO`）

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


def main():
    tmp = tempfile.mkdtemp()
    print("shipped scripts")
    print("-" * 72)
    check(os.path.exists(QC), "scripts/report_qc.py present")
    check(os.path.exists(EVAL), "scripts/evaluate.py present")
    check(os.path.exists(EXEMPLAR), "references/example-report.md present")

    print()
    print("report_qc.py")
    print("-" * 72)
    good = os.path.join(tmp, "good.md")
    io.open(good, "w", encoding="utf-8").write(brief_report())
    r = run(QC, good)
    check(r.stdout.startswith("PASS"), "a well-formed brief report passes",
          r.stdout.strip().split("\n")[0][:44] if r.stdout.strip() else "")
    check(r.returncode == 0, "a passing report exits 0")

    # drop one of the three layers -> must be caught and located
    bad = brief_report().replace("**为什么** — 索引命中。\n", "")
    nolayer = os.path.join(tmp, "nolayer.md")
    io.open(nolayer, "w", encoding="utf-8").write(bad)
    r = run(QC, nolayer)
    check("A8" in r.stdout and not r.stdout.startswith("PASS"),
          "a missing three-layer label is caught", "A8 reported")
    check("line " in r.stdout, "the A8 defect carries a line number")
    check(r.returncode == 1, "a failing report exits nonzero")

    # remove section six -> must be caught
    p = os.path.join(tmp, "nosix.md")
    io.open(p, "w", encoding="utf-8").write(brief_report().split("## 六")[0])
    r = run(QC, p)
    check("sec" in r.stdout, "a missing section is caught")

    # bare '>' inside a Mermaid label -> must be caught
    p = os.path.join(tmp, "mermaid.md")
    io.open(p, "w", encoding="utf-8").write(
        brief_report().replace('A["Z_FOO"]', 'A["Z_FOO->bar"]'))
    r = run(QC, p)
    check("mm" in r.stdout, "a bare > in a Mermaid label is caught")

    # the two source-aware advisories: density and fidelity
    # the source must actually contain what the brief report quotes, otherwise
    # the "faithful" case is not faithful and the check is right to complain
    src = os.path.join(tmp, "src.abap")
    io.open(src, "w", encoding="utf-8").write(
        "FUNCTION z_foo.\n"
        "  DATA ls_foo TYPE i.\n"
        "  SELECT foo FROM bar INTO @DATA(ls_foo).\n"
        "ENDFUNCTION.\n")
    r = run(QC, good, src)
    check("low density" not in r.stdout,
          "no density note for a report with no declared subprograms")
    check("do not occur in the source" not in r.stdout,
          "no fidelity note when every quoted line is faithful")

    p = os.path.join(tmp, "altered.md")
    io.open(p, "w", encoding="utf-8").write(
        brief_report().replace("SELECT foo FROM bar", "SELECT foo FROM baz"))
    r = run(QC, p, src)
    check("do not occur in the source" in r.stdout,
          "a fidelity note fires when an identifier is rewritten")

    # regression: fidelity_note scoped its exemption to the whole document prefix
    # rather than the current heading, so once a report had written a single
    # 风险与改进 layer every later block was skipped. Real reports carry many
    # blocks; this fixture has one, placed before any layer, which is why the bug
    # survived and why this case had to be written by hand.
    two = brief_report().replace(
        "## 四、流程图",
        "### 3.2 步骤② 声明（函数模块 `Z_FOO`）\n"
        "\n```abap\n"
        "  DATA ls_foo TYPE i.\n"
        "```\n"
        "\n**做什么** — 声明。\n**为什么** — 定长。\n**风险与改进** — 可改用 c。\n"
        "\n## 四、流程图")
    p = os.path.join(tmp, "second.md")
    io.open(p, "w", encoding="utf-8").write(two)
    r = run(QC, p, src)
    check("do not occur in the source" not in (r.stdout or ""),
          "a faithful second block raises no fidelity note")
    p = os.path.join(tmp, "altered2.md")
    io.open(p, "w", encoding="utf-8").write(
        two.replace("DATA ls_foo TYPE i.", "DATA ls_foo TYPE c."))
    r = run(QC, p, src)
    check("do not occur in the source" in (r.stdout or ""),
          "a rewritten second block raises a fidelity note")

    # Fence language decides what is probed; position exempts nothing. A fix
    # nested in the risk layer used to be skipped by position, which skipped the
    # next sub-step's real quote as well. Label it abap-fix and neither gate
    # touches it; leave it abap and both do.
    tail = ("**风险与改进** — 可改用 c（示意，源码中不存在）：\n"
            "   ```abap-fix\n"
            "     DATA ls_foo TYPE c.\n"
            "   ```\n")
    p = os.path.join(tmp, "fixlabelled.md")
    io.open(p, "w", encoding="utf-8").write(
        two.replace("**风险与改进** — 可改用 c。", tail))
    r = run(QC, p, src)
    check(r.stdout.startswith("PASS") and r.returncode == 0,
          "a labelled fix needs no layers and breaks nothing",
          r.stdout.strip().split("\n")[0][:44] if r.stdout.strip() else "")
    check("do not occur in the source" not in r.stdout,
          "a labelled fix is not probed against the source")
    check("fence(s) sit inside" not in r.stdout,
          "a correctly labelled fix raises no fix-lang note")

    p = os.path.join(tmp, "fixunlabelled.md")
    io.open(p, "w", encoding="utf-8").write(two.replace(
        "**风险与改进** — 可改用 c。",
        tail.replace("```abap-fix", "```abap").replace("（示意，源码中不存在）", "")))
    r = run(QC, p, src)
    check("do not occur in the source" in r.stdout,
          "an unlabelled fix is probed and reads as fabricated")
    check("fence(s) sit inside" in r.stdout,
          "an unlabelled fix raises a fix-lang note")

    # the same nesting with a third block in the heading: the third block is a
    # real quote followed by its own layers, so it must not be flagged either
    triple = two.replace(
        "## 四、流程图",
        "```abap\n"
        "  ENDIF.\n"
        "```\n"
        "\n**做什么** — 收尾。\n**为什么** — 对称。\n**风险与改进** — 无。\n"
        "\n## 四、流程图")
    p = os.path.join(tmp, "third.md")
    io.open(p, "w", encoding="utf-8").write(
        triple.replace("**风险与改进** — 可改用 c。", tail))
    r = run(QC, p, src)
    check("fence(s) sit inside" not in r.stdout,
          "a later quoted block in the same heading is not flagged",
          r.stdout.strip()[:120] if r.stdout else "")

    # a report may quote two source lines merged, which must NOT be reported
    p = os.path.join(tmp, "merged.md")
    io.open(p, "w", encoding="utf-8").write(
        brief_report().replace("SELECT foo FROM bar INTO @DATA(ls_foo).",
                               "SELECT foo FROM bar INTO @DATA(ls_foo). WRITE 2."))
    r = run(QC, p, src)
    check("do not occur in the source" in r.stdout,
          "a statement the source does not contain is reported")

    if os.path.exists(EXEMPLAR):
        r = run(QC, EXEMPLAR)
        check(r.stdout.startswith("PASS"),
              "the shipped example report still passes",
              r.stdout.strip().split("\n")[0][:44] if r.stdout.strip() else "")

    # SKILL.md step 6 tells the model to re-run the fidelity pass until it is
    # clean. That loop can only terminate if the exit status carries the verdict.
    # Both branches below returned 0 while printing FAIL, so an agent that polled
    # the exit code -- the natural way to run "until clean" -- finished on the
    # first iteration with an unrepaired transcription error still in the report.
    print()
    print("exit status carries the verdict (step 6 depends on it)")
    print("-" * 72)
    fo = run(QC, "--fidelity-only", good, src)
    check(fo.stdout.startswith("PASS") and fo.returncode == 0,
          "--fidelity-only exits 0 when every quotation is faithful")
    fo = run(QC, "--fidelity-only", p, src)
    check(fo.stdout.startswith("FAIL") and fo.returncode == 1,
          "--fidelity-only exits nonzero when a quotation is not in the source")
    fx = run(QC, "--fix", nolayer, src, "-o", os.path.join(tmp, "fixed.md"))
    check(fx.returncode == 1,
          "--fix exits nonzero while defects still need the model",
          "A8 is not mechanically repairable")
    fx = run(QC, "--fix", good, src, "-o", os.path.join(tmp, "fixed2.md"))
    check(fx.returncode == 0, "--fix exits 0 once nothing is left")
    r = run(QC, os.path.join(tmp, "no-such-file.md"))
    check(r.returncode != 0, "a missing report file exits nonzero")

    # the contract's own bucket markers are emoji, and printing one to a cp936
    # console used to raise UnicodeEncodeError from inside the defect loop, which
    # replaced the diagnosis with a traceback and made the bucket check
    # unreachable on Windows.
    print()
    print("the gate survives a console that cannot encode its own output")
    print("-" * 72)
    nb = os.path.join(tmp, "nobucket.md")
    io.open(nb, "w", encoding="utf-8").write(
        brief_report().replace("### 🟠 P1 健壮性", "### 其他问题"))
    env = dict(os.environ, PYTHONIOENCODING="ascii", PYTHONUTF8="")
    r = subprocess.run([sys.executable, QC, nb], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    check("UnicodeEncodeError" not in r.stderr and "buck" in r.stdout,
          "a missing priority bucket is reported, not crashed on",
          r.stdout.strip().split("\n")[0][:44] if r.stdout.strip() else "")

    print()
    print("evaluate.py")
    print("-" * 72)
    defs = os.path.join(tmp, "d.json")
    io.open(defs, "w", encoding="utf-8").write(json.dumps({
        "source": "z_foo.abap",
        "defects": [
            {"id": "D1", "area": "a", "question": "报告是否指出未判空？",
             "anchor": "SELECT foo FROM bar"},
            {"id": "D2", "area": "b", "question": "报告是否指出缺少 sy-subrc 检查？",
             "anchor": "IF sy-subrc = 0."},
        ]}, ensure_ascii=False))

    def vfile(name, mutate=None):
        v = {"report": good,
             "verdicts": {"D1": "yes", "D2": "partial"},
             # a positive verdict must cite the report line carrying it, so the
             # fixture has to cite one or it is rejected before it is scored
             "evidence": {"D1": {"report_line": 5},
                          "D2": {"report_line": 5}},
             "false_claims": []}
        if mutate:
            mutate(v)
        p = os.path.join(tmp, name + ".json")
        io.open(p, "w", encoding="utf-8").write(json.dumps(v, ensure_ascii=False))
        return p

    r = run(EVAL, "score", "--defects", defs, "--verdicts", vfile("ok"))
    check(r.returncode == 0, "a complete verdict file scores")
    check("0.750" in r.stdout, "weighted recall is (1 + 0.5) / 2 = 0.750",
          r.stdout.strip().split("\n")[4][:52] if len(r.stdout.split("\n")) > 4 else "")

    def drop(v):
        v["verdicts"].pop("D2")

    def wrong(v):
        v["verdicts"]["D2"] = "maybe"

    def unknown(v):
        v["verdicts"]["D9"] = "no"

    def fc_int(v):
        v["false_claims"] = 3

    def fc_bad(v):
        v["false_claims"] = [{"claim": "x"}]

    for name, mut, label in [
        ("missing", drop, "an unjudged defect is rejected"),
        ("wrongval", wrong, "a verdict outside the vocabulary is rejected"),
        ("unknown", unknown, "a verdict for an unknown defect is rejected"),
        ("fcint", fc_int, "a bare count in false_claims is rejected"),
        ("fcbad", fc_bad, "a false claim missing why_wrong is rejected"),
        ("noevidence", lambda v: v.pop("evidence"),
         "a positive verdict with no cited line is rejected"),
        ("badline", lambda v: v["evidence"]["D1"].update(report_line=99999),
         "a cited line outside the report is rejected"),
    ]:
        r = run(EVAL, "score", "--defects", defs, "--verdicts", vfile(name, mut))
        check(r.returncode != 0 and "REJECTED" in r.stdout, label)

    print()
    print("-" * 72)
    if FAILS:
        print(f"{len(FAILS)} check(s) failed:")
        for f in FAILS:
            print("  -", f)
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
