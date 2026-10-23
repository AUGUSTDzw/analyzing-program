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
import re
import shutil
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
REPO = os.path.dirname(os.path.dirname(SKILL))
QC = os.path.join(SKILL, "scripts", "report_qc.py")
CHECKS = os.path.join(SKILL, "scripts", "checks")
SCHEMAS = os.path.join(SKILL, "schemas")
EVAL = os.path.join(SKILL, "scripts", "evaluate.py")
RECON = os.path.join(SKILL, "scripts", "recon.py")
DOCGEN = os.path.join(SKILL, "scripts", "docgen.py")
DEPS = os.path.join(SKILL, "scripts", "abap_deps_analyzer.py")
EXEMPLAR = os.path.join(SKILL, "references", "example-report.md")
# The exemplar's own source. row-src only runs when a source is passed, so the
# source-less run above can never notice a section five row that names nothing.
EXEMPLAR_SRC = os.path.join(
    REPO, "Test-source", "real",
    "hardyp__AbapToTheFuture03__src__zmonsters_p01_enablers"
    "__zmonsters_c04_exceptions__zbc_show_error_log.fugr"
    ".zbc_show_error_log.abap")

FAILS = []
N_OK = 0


def check(cond, label, detail=""):
    global N_OK
    if cond:
        N_OK += 1
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

**做什么** — 1. 取一行。
**为什么** — 索引命中。
**风险与改进** — 未判空。

## 四、流程图

```mermaid
flowchart TD
  A["Z_FOO"] --> B["输出"]
```

```mermaid
sequenceDiagram
  Z_FOO->>Z_FOO: 读取
  Z_FOO-->>Z_FOO: 回填
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

    # The rule set is loaded before main() can run, so a skill installed with
    # its schemas/ directory missing used to die with a bare traceback and exit
    # code 1 -- the code SKILL.md defines as "the check ran and found
    # defects". Nothing was inspected, but the caller read it as a verdict, and
    # step 7's "rerun until clean" loop could never go quiet. Refuse instead.
    #
    # checks/ is copied in alongside report_qc.py because it is now what reads
    # the rule set. Without it both cases below stopped at the package guard
    # and the guard that actually reads schemas/ lost its coverage: the suite
    # still counted six green checks, one exit-2 path quietly replaced another.
    # The assertion below names "rule set" rather than "error" so the two
    # refusals cannot be confused for one another again.
    for kind in ("missing", "corrupt"):
        root = os.path.join(tmp, kind)
        os.makedirs(os.path.join(root, "scripts"))
        if kind == "corrupt":
            os.makedirs(os.path.join(root, "schemas"))
            io.open(os.path.join(root, "schemas", "report-contract.json"),
                    "w", encoding="utf-8").write("{ not json")
        shutil.copy(QC, os.path.join(root, "scripts", "report_qc.py"))
        shutil.copytree(CHECKS, os.path.join(root, "scripts", "checks"),
                        ignore=shutil.ignore_patterns("__pycache__"))
        rep = os.path.join(tmp, kind + ".md")
        io.open(rep, "w", encoding="utf-8").write(brief_report())
        r = run(os.path.join(root, "scripts", "report_qc.py"), rep)
        check(r.returncode == 2,
              "an %s rule set exits 2, not 1" % kind)
        check("Traceback" not in r.stderr and "Traceback" not in r.stdout,
              "an %s rule set says so, it does not raise" % kind)
        check("error" in r.stdout and "nothing was checked" in r.stdout,
              "an %s rule set announces that nothing was checked" % kind)
        # The word "rule set" is the discriminator, and the comment above says
        # why the earlier version of this loop could not tell the two apart.
        check("cannot read the rule set" in r.stdout,
              "an %s rule set is refused by the rule-set guard, not an earlier one"
              % kind,
              r.stdout.strip().split("\n")[0][:44] if r.stdout.strip() else "")

    # The other door to the same verdict: the checks package itself is absent.
    # A malformed module in it must not open a third one -- see the SyntaxError
    # guard in report_qc.py, which is what makes that true.
    root = os.path.join(tmp, "nochecks")
    os.makedirs(os.path.join(root, "scripts"))
    shutil.copy(QC, os.path.join(root, "scripts", "report_qc.py"))
    rep = os.path.join(tmp, "nochecks.md")
    io.open(rep, "w", encoding="utf-8").write(brief_report())
    r = run(os.path.join(root, "scripts", "report_qc.py"), rep)
    check(r.returncode == 2, "a missing checks package exits 2, not 1")
    check("Traceback" not in r.stderr and "Traceback" not in r.stdout,
          "a missing checks package says so, it does not raise")
    check("cannot load the checks" in r.stdout and
          "nothing was checked" in r.stdout,
          "a missing checks package announces that nothing was checked",
          r.stdout.strip().split("\n")[0][:44] if r.stdout.strip() else "")

    # A checks module that will not parse is the same case wearing a different
    # hat: nothing was checked, so it has to exit 2 like the other two. Before
    # the guard it raised SyntaxError, and the traceback exited 1 -- the code
    # SKILL.md defines as "the check ran and found defects". The rule set is
    # copied in good order here, because checks/contract.py is imported first
    # and its own guard would otherwise refuse and the malformed module would
    # never be reached -- which is the case this test exists to exercise.
    root = os.path.join(tmp, "malformed")
    os.makedirs(os.path.join(root, "scripts"))
    shutil.copytree(SCHEMAS, os.path.join(root, "schemas"))
    shutil.copy(QC, os.path.join(root, "scripts", "report_qc.py"))
    shutil.copytree(CHECKS, os.path.join(root, "scripts", "checks"),
                    ignore=shutil.ignore_patterns("__pycache__"))
    io.open(os.path.join(root, "scripts", "checks", "text.py"),
            "w", encoding="utf-8").write("def broken(:\n")
    rep = os.path.join(tmp, "malformed.md")
    io.open(rep, "w", encoding="utf-8").write(brief_report())
    r = run(os.path.join(root, "scripts", "report_qc.py"), rep)
    check(r.returncode == 2, "a checks module that will not parse exits 2, not 1",
          "exit=%d" % r.returncode)
    check("Traceback" not in r.stderr and "Traceback" not in r.stdout,
          "a checks module that will not parse says so, it does not raise",
          (r.stderr.strip().split("\n") or [""])[-1][:44])
    check("cannot load the checks" in r.stdout and
          "nothing was checked" in r.stdout,
          "a checks module that will not parse announces nothing was checked",
          r.stdout.strip().split("\n")[0][:44] if r.stdout.strip() else "")

    # A refusal is a verdict, printed like PASS and FAIL, so its first line is
    # error at column 0 -- the shape conclusion_lines records. die() had a
    # two-space indent while the two import-time refusals printed flush left, so
    # the same refusal arrived three different ways and a caller matching
    # conclusion_lines from column 0 missed every refusal that went through
    # die(). The three paths below each die a different way; the assertion is
    # about the shape, not the message.
    clean = os.path.join(tmp, "clean.md")
    io.open(clean, "w", encoding="utf-8").write("# nothing\n")
    # The sources below do not have to exist: every one of these refusals fires
    # before any path is opened, and the two sources are named with .abap
    # because the split is by extension -- a .md second argument would be read
    # as a second report, not a source, and would die a different way.
    for argv, what in (([clean, "a.abap", "b.abap"],
                        "plain mode with two sources"),
                       (["--fidelity-only", clean, "a.abap", "b.abap"],
                        "--fidelity-only with two sources"),
                       (["--fix", clean, "a.abap", "-o",
                         os.path.join(tmp, "no_such_dir", "x.md")],
                        "--fix into a directory that does not exist")):
        r = run(QC, *argv)
        # splitlines, never .strip(): stripping would eat the two-space indent
        # this check exists to catch, and pass.
        first = r.stdout.splitlines()[0] if r.stdout.splitlines() else ""
        check(r.returncode == 2 and first.startswith("error  "),
              "a refusal via %s prints error at column 0" % what,
              repr(first[:44]))

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
    # Long on purpose: --fix resolves a line citation to the construct above that
    # line, so a citation that points past the end of the source has no anchor
    # and is left for the model. Trailing comments add lines without adding any
    # construct to the anchor list, which is what those tests want.
    io.open(src, "w", encoding="utf-8").write(
        "FUNCTION z_foo.\n"
        "  DATA ls_foo TYPE i.\n"
        "  SELECT foo FROM bar INTO @DATA(ls_foo).\n"
        "ENDFUNCTION.\n"
        + "".join("* filler %d.\n" % i for i in range(120)))
    r = run(QC, good, src)
    check("low density" not in r.stdout,
          "no density note when every declared subprogram is covered")
    check("not occur in the source" not in r.stdout,
          "no fidelity note when every quoted line is faithful")

    # A source with no construct in ANCHORS has no denominator, so density cannot
    # be measured. That used to be reported as silence, which reads as "nothing
    # to worry about". Say what could not be measured instead.
    nsrc = os.path.join(tmp, "plain.abap")
    io.open(nsrc, "w", encoding="utf-8").write(
        "DATA ls_foo TYPE i.\nWRITE ls_foo.\n")
    r = run(QC, good, nsrc)
    check("density not measured" in r.stdout,
          "an uncountable source says so instead of passing silently",
          r.stdout.strip().split("\n")[-1][:52] if r.stdout.strip() else "")

    p = os.path.join(tmp, "altered.md")
    io.open(p, "w", encoding="utf-8").write(
        brief_report().replace("SELECT foo FROM bar", "SELECT foo FROM baz"))
    r = run(QC, p, src)
    check("not occur in the source" in r.stdout,
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
        "\n**做什么** — 1. 声明。\n**为什么** — 定长。\n**风险与改进** — 可改用 c。\n"
        "\n## 四、流程图")
    p = os.path.join(tmp, "second.md")
    io.open(p, "w", encoding="utf-8").write(two)
    r = run(QC, p, src)
    check("not occur in the source" not in (r.stdout or ""),
          "a faithful second block raises no fidelity note")
    p = os.path.join(tmp, "altered2.md")
    io.open(p, "w", encoding="utf-8").write(
        two.replace("DATA ls_foo TYPE i.", "DATA ls_foo TYPE c."))
    r = run(QC, p, src)
    check("not occur in the source" in (r.stdout or ""),
          "a rewritten second block raises a fidelity note")

    # A count with no denominator cannot be read: three rewrites is a few slips
    # in a long report and total fabrication in a short one, and the fidelity
    # note printed the count alone. The note now reads N of M, M every quoted
    # statement in the report, and only M equal to the number of mismatches
    # adds the question -- that is the one boundary the gate cannot otherwise
    # separate from fabrication, and the one that needs no threshold, because a
    # cutoff on identifier count would not separate the cases: a comments-only
    # file yields 6 identities and an English prose file 20, both non-zero.
    p = os.path.join(tmp, "half.md")
    io.open(p, "w", encoding="utf-8").write(
        two.replace("DATA ls_foo TYPE i.", "DATA ls_foo TYPE c."))
    r = run(QC, p, src)
    note = [x for x in r.stdout.splitlines()
            if "quoted statement(s) rewrite" in x]
    check(bool(note) and note[0].strip().startswith(
        "note  1 of 2 quoted statement(s) rewrite the source. First at line"),
          "the fidelity note counts its denominator",
          note[0].strip()[:84] if note else "")
    check("written against" not in r.stdout,
          "a few slips are not accused of being the wrong source")
    p = os.path.join(tmp, "wrongfile.md")
    io.open(p, "w", encoding="utf-8").write(
        two.replace("SELECT foo FROM bar", "SELECT foo FROM baz")
            .replace("DATA ls_foo TYPE i.", "DATA ls_foo TYPE c."))
    r = run(QC, p, src)
    note = [x for x in r.stdout.splitlines()
            if "quoted statement(s) rewrite" in x]
    check(bool(note) and "2 of 2 quoted statement(s) rewrite the source"
          in note[0] and "written against" in note[0],
          "every quotation flagged says the source may be the wrong file",
          note[0].strip()[:120] if note else "")

    # regression: _claims decided a quoted line was the report's own annotation
    # whenever it contained CJK. Chinese ABAP carries CJK in string literals and
    # in statement comments, so WRITE / '开始'. was exempted from the only check
    # that catches an invented statement, and a fabricated Chinese literal read
    # exactly like a faithful one. The corpus check is that the count of flagged
    # statements across 33 real reports did not rise (208 vs 210) while the
    # probed set grew by about 1200 lines.
    csrc = os.path.join(tmp, "cjk.abap")
    io.open(csrc, "w", encoding="utf-8").write(
        "REPORT zr.\n"
        "DATA lv_msg TYPE string. \" 提示文本\n"
        "FORM init.\n"
        "  WRITE / '开始'.\n"
        "ENDFORM.\n")
    SEL = "SELECT foo FROM bar INTO @DATA(ls_foo)."
    cjk = brief_report().replace(SEL, "  WRITE / '开始'.")
    p = os.path.join(tmp, "cjk_ok.md")
    io.open(p, "w", encoding="utf-8").write(cjk)
    r = run(QC, p, csrc)
    check("not occur in the source" not in (r.stdout or ""),
          "a faithful quote with a Chinese literal is not flagged")
    p = os.path.join(tmp, "cjk_bad.md")
    io.open(p, "w", encoding="utf-8").write(
        brief_report().replace(SEL, "  WRITE / '编造的中文提示'."))
    r = run(QC, p, csrc)
    check("not occur in the source" in (r.stdout or ""),
          "a fabricated Chinese literal is flagged, not exempted")

    # a statement comment is prose, so rewording only the comment is not a
    # rewritten statement; the code part before the " is what gets compared
    p = os.path.join(tmp, "cjk_comment.md")
    io.open(p, "w", encoding="utf-8").write(brief_report().replace(
        SEL, "DATA lv_msg TYPE string. \" 改写过的注释"))
    r = run(QC, p, csrc)
    check("not occur in the source" not in (r.stdout or ""),
          "a rewritten statement comment is not called a fabrication")
    p = os.path.join(tmp, "cjk_code.md")
    io.open(p, "w", encoding="utf-8").write(brief_report().replace(
        SEL, "DATA lv_msg TYPE i. \" 同一条注释"))
    r = run(QC, p, csrc)
    check("not occur in the source" in (r.stdout or ""),
          "a rewritten statement with an untouched comment is still flagged")

    # the report's own Chinese line inside a block is annotation, not code
    p = os.path.join(tmp, "cjk_prose.md")
    io.open(p, "w", encoding="utf-8").write(brief_report().replace(
        SEL, " 取一行\n  WRITE / '开始'."))
    r = run(QC, p, csrc)
    check("not occur in the source" not in (r.stdout or ""),
          "the report's own Chinese line inside a block is not probed")

    # regression: the elision exemption was searched anywhere in the line, so a
    # "..." inside a trailing comment exempted the whole statement. The fix must
    # still honour the three elision shapes the skill permits: a bare marker, a
    # marker with an explaining comment, and a partial statement opened by one.
    p = os.path.join(tmp, "elide_backdoor.md")
    io.open(p, "w", encoding="utf-8").write(brief_report().replace(
        SEL, "  LOOP AT some_t INTO wa.  \" ... then more"))
    r = run(QC, p, csrc)
    check("LOOP AT some_t INTO wa." in (r.stdout or ""),
          "an ellipsis inside a comment no longer exempts the statement")
    for shape, label in (
            ("  ...\n", "a bare elision marker is exempt"),
            ("  ...  \" FNC / PCK / DLS 同类\n", "an elision with a note is exempt"),
            ("  ... SELECT SINGLE strkorr FROM e070 ...\n",
             "a partial statement opened by an ellipsis is exempt")):
        p = os.path.join(tmp, "elide_ok.md")
        io.open(p, "w", encoding="utf-8").write(
            brief_report().replace(SEL, "  WRITE / '开始'.\n" + shape))
        r = run(QC, p, csrc)
        check("not occur in the source" not in (r.stdout or ""), label)

    # the balance test counts on the comment-stripped line, so an apostrophe the
    # report wrote inside a comment cannot tip it; and an apostrophe inside the
    # report's own prose reads as an unbalanced literal, so that line is skipped
    # rather than reported as a fabricated statement.
    for shape, label in (
            ('" it\'s a note\n', "an apostrophe inside a comment is not a literal"),
            ("  RS_CMP can't see this.\n", "an apostrophe in report prose is not a literal")):
        p = os.path.join(tmp, "apos_ok.md")
        io.open(p, "w", encoding="utf-8").write(
            brief_report().replace(SEL, "  WRITE / '开始'.\n" + shape))
        r = run(QC, p, csrc)
        check("not occur in the source" not in (r.stdout or ""), label)

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
    check("not occur in the source" not in r.stdout,
          "a labelled fix is not probed against the source")
    check("fence(s) sit inside" not in r.stdout,
          "a correctly labelled fix raises no fix-lang note")

    p = os.path.join(tmp, "fixunlabelled.md")
    io.open(p, "w", encoding="utf-8").write(two.replace(
        "**风险与改进** — 可改用 c。",
        tail.replace("```abap-fix", "```abap").replace("（示意，源码中不存在）", "")))
    r = run(QC, p, src)
    check("not occur in the source" in r.stdout,
          "an unlabelled fix is probed and reads as fabricated")
    check("fence(s) sit inside" in r.stdout,
          "an unlabelled fix raises a fix-lang note")

    # ---- a non-utf-8 REPORT refuses, in every mode ------------------------
    # The source side was guarded from the start. The report side was not: three
    # call sites read it bare, so a report saved as cp936 -- what an editor's
    # "save as" produces on a Chinese Windows, the same trap SKILL.md warns
    # about for pasted source -- raised an uncaught UnicodeDecodeError and exited
    # 1, which SKILL.md defines as "the check ran and found defects". The caller
    # then went looking for defects that were never there.
    print()
    print("a report that is not utf-8 is not a defect")
    print("-" * 72)
    # brief_report carries the four bucket emoji, which GBK cannot encode. That
    # is irrelevant here: the point is only that the file is not utf-8. The
    # utf-16 cases keep the emoji, so the bucket headings still get decoded.
    for enc, blob in (("gbk", brief_report().encode("gbk", "replace")),
                      ("utf-16", brief_report().encode("utf-16")),
                      ("utf-16-le", brief_report().encode("utf-16-le"))):
        p = os.path.join(tmp, "enc-%s.md" % enc)
        with open(p, "wb") as fh:
            fh.write(blob)
        for mode, argv in (("plain", [p, src]),
                           ("--fidelity-only", ["--fidelity-only", p, src]),
                           ("--fix", ["--fix", p, src])):
            r = run(QC, *argv)
            check(r.returncode == 2 and "Traceback" not in r.stderr,
                  "%s report: %s exits 2, not a traceback" % (enc, mode),
                  r.stdout.strip().split("\n")[-1][:44] if r.stdout.strip() else "")
            check("not readable as utf-8" in r.stdout,
                  "%s report: %s names the decode failure" % (enc, mode))
            check("nothing was checked" in r.stdout or "nothing was compared" in r.stdout,
                  "%s report: %s says nothing was inspected" % (enc, mode))

    # the same file in utf-8 is accepted, so the guard is about the encoding and
    # not about the content
    p = os.path.join(tmp, "enc-utf8.md")
    io.open(p, "w", encoding="utf-8").write(brief_report())
    r = run(QC, p, src)
    check(r.returncode == 0 and r.stdout.startswith("PASS"),
          "the same report in utf-8 still passes", r.stdout.strip()[:44])

    # ---- authz / ext-asset: two notes that only fire with a source ---------
    # Measured on a held-out program: a report that wrote "不做权限控制" and then
    # moved on was judged partial for never saying who can then see the data, and
    # another that named a hardcoded bitmap scored it a hardcoded dependency
    # without following it to the missing guard. Neither was blind to the code.
    # So both notes ask the question, and the contract anchors on the phrases
    # SKILL.md actually uses for them.
    # Both were added after a held-out run lost items to reports that named a
    # hardcoded bitmap and said "no permission control" and then moved on. The
    # defect was never seeing it; it was seeing it and not following through.
    # So the notes exist to put the question in front of the writer, and the
    # tests below pin the part that can go wrong silently: firing on a program
    # that has nothing to authorize, and staying silent on one that does.
    print()
    print("the two zero-occurrence notes")
    print("-" * 72)

    # `src` is a path, not its text: inject the AUTHORITY-CHECK into a sibling
    # file so the guarded and unguarded cases can both be run in one pass.
    # The fixture is FUNCTION z_foo, so it goes in above that line.
    src_text = io.open(src, encoding="utf-8").read()
    guarded = os.path.join(tmp, "guarded.abap")
    io.open(guarded, "w", encoding="utf-8").write(
        src_text.replace("FUNCTION z_foo.",
                         "AUTHORITY-CHECK OBJECT 'Z_AUTH' ID 'ACT'.\n"
                         "FUNCTION z_foo."))
    asset_src = os.path.join(tmp, "asset.abap")
    io.open(asset_src, "w", encoding="utf-8").write(
        src_text.replace(
            "  DATA ls_foo TYPE i.",
            "  zcl_x=>set_bitmap( iv_name = 'ZIND_N_LOGO_SMALL' ).\n"
            "  DATA ls_foo TYPE i."))
    p = os.path.join(tmp, "authzoff.md")
    io.open(p, "w", encoding="utf-8").write(brief_report())
    r = run(QC, p, guarded)
    check("no AUTHORITY-CHECK" not in r.stdout,
          "authz stays silent when the source checks authorization",
          r.stdout.strip().split("\n")[-1][:44] if r.stdout.strip() else "")
    check(r.returncode == 0, "the authz source still passes shape")

    r = run(QC, p, src)
    check("no AUTHORITY-CHECK" in r.stdout,
          "authz fires when the source reads data and never checks")
    check("S_TCODE" in r.stdout,
          "authz states the S_TCODE condition instead of asserting a defect")
    check("note" in r.stdout, "authz is a note and does not fail the gate")
    check(r.returncode == 0, "an authz note leaves the exit code at 0")

    # Naming the topic is not answering it. A report that says only "no
    # permission check" must still get the note; one that states who can then
    # see what must not.
    p2 = os.path.join(tmp, "authzsilent.md")
    io.open(p2, "w", encoding="utf-8").write(brief_report())
    r = run(QC, p2, src)
    check("no AUTHORITY-CHECK" in r.stdout,
          "authz fires on a report that says nothing about authorization")

    named = brief_report().replace(
        "## 六、整体评价",
        "## 五之二、越权通道\n\n任何能运行该事务的用户都能看到全量数据。\n\n"
        "## 六、整体评价")
    p3 = os.path.join(tmp, "authzanswered.md")
    io.open(p3, "w", encoding="utf-8").write(named)
    r = run(QC, p3, src)
    check("no AUTHORITY-CHECK" not in r.stdout,
          "authz stays quiet once the report states the consequence",
          r.stdout.strip().split("\n")[-1][:44] if r.stdout.strip() else "")

    # ext-asset: a bitmap literal in the source, guard count reported
    p4 = os.path.join(tmp, "asset.md")
    io.open(p4, "w", encoding="utf-8").write(brief_report())
    r = run(QC, p4, asset_src)
    check("ZIND_N_LOGO_SMALL" in r.stdout,
          "ext-asset names the hardcoded asset literal", r.stdout[:44])
    check("TRY" in r.stdout or "guards" in r.stdout,
          "ext-asset asks whether the call site is guarded")
    check(r.returncode == 0, "an ext-asset note leaves the exit code at 0")

    r = run(QC, p4, src)
    check("external asset" not in r.stdout,
          "ext-asset stays silent when the source names no asset")

    # negative control: the notes must be able to stay quiet together
    r = run(QC, p, guarded)
    check("external asset" not in r.stdout and "no AUTHORITY-CHECK" not in r.stdout,
          "a guarded, asset-free source raises neither note")

    # the same two notes must appear on the --fix path, which recomputes them
    # from the rewritten text
    p5 = os.path.join(tmp, "fixasset.md")
    io.open(p5, "w", encoding="utf-8").write(
        brief_report().replace("**风险与改进** — 未判空。",
                               "**风险与改进** — 未判空。\n（例 10-96 行）"))
    r = run(QC, "--fix", p5, src)
    check("no AUTHORITY-CHECK" in r.stdout,
          "--fix also reports the authz note",
          r.stdout.strip().split("\n")[-1][:44] if r.stdout.strip() else "")

    # the same nesting with a third block in the heading: the third block is a
    # real quote followed by its own layers, so it must not be flagged either
    triple = two.replace(
        "## 四、流程图",
        "```abap\n"
        "  ENDIF.\n"
        "```\n"
        "\n**做什么** — 1. 收尾。\n**为什么** — 对称。\n**风险与改进** — 无。\n"
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
    check("not occur in the source" in r.stdout,
          "a statement the source does not contain is reported")

    if os.path.exists(EXEMPLAR):
        r = run(QC, EXEMPLAR)
        check(r.stdout.startswith("PASS"),
              "the shipped example report still passes",
              r.stdout.strip().split("\n")[0][:44] if r.stdout.strip() else "")
        if not os.path.exists(EXEMPLAR_SRC):
            check(False, "the exemplar's source is present, so row-src can be checked on it")
        else:
            rs = run(QC, EXEMPLAR, EXEMPLAR_SRC)
            check(rs.stdout.startswith("PASS") and rs.returncode == 0,
                  "the shipped example report still passes against its own source",
                  rs.stdout.strip().split("\n")[0][:60] if rs.stdout.strip() else "")

    # SKILL.md step 7 tells the model to re-run the fidelity pass until it is
    # clean. That loop can only terminate if the exit status carries the verdict.
    # Both branches below returned 0 while printing FAIL, so an agent that polled
    # the exit code -- the natural way to run "until clean" -- finished on the
    # first iteration with an unrepaired transcription error still in the report.
    print()
    print("exit status carries the verdict (step 7 depends on it)")
    print("-" * 72)
    fo = run(QC, "--fidelity-only", good, src)
    check(fo.stdout.startswith("PASS") and fo.returncode == 0,
          "--fidelity-only exits 0 when every quotation is faithful")
    fo = run(QC, "--fidelity-only", p, src)
    check("FAIL" in fo.stdout and fo.returncode == 1,
          "--fidelity-only exits nonzero when a quotation is not in the source")
    # The advisory tier has its own PASS form. conclusion_lines listed only
    # `PASS  <name>`, so a reader classifying output by that list met a line it
    # had never been told could appear -- exit 0 while punctuation was still
    # being counted. Match the whole line, not a prefix, so a regression that
    # quietly drops the count is caught too.
    pun = os.path.join(tmp, "punct.md")
    io.open(pun, "w", encoding="utf-8").write(
        brief_report().replace("SELECT foo FROM bar INTO @DATA(ls_foo).",
                               "SELECT foo FROM bar INTO @DATA(ls_foo )"))
    fo = run(QC, "--fidelity-only", pun, src)
    check("PASS  punct.md  (1 punctuation-only)" in fo.stdout,
          "--fidelity-only counts advisory findings on the PASS line itself",
          fo.stdout.strip().splitlines()[-1][:56] if fo.stdout.strip() else "")
    check(fo.returncode == 0,
          "--fidelity-only still exits 0 when the only findings are advisory")
    check("PUNCT-" in fo.stdout,
          "an advisory finding is still shown as a tier line")
    fx = run(QC, "--fix", nolayer, src, "-o", os.path.join(tmp, "fixed.md"))
    check(fx.returncode == 1,
          "--fix exits nonzero while defects still need the model",
          "A8 is not mechanically repairable")
    fx = run(QC, "--fix", good, src, "-o", os.path.join(tmp, "fixed2.md"))
    check(fx.returncode == 0, "--fix exits 0 once nothing is left")
    # The same regression in the third branch. A substantive rewrite is a
    # defect, and plain mode counts it in N, so 0 must mean the same thing in
    # every mode. Before this, --fix returned 0 here while plain mode returned 1
    # for the identical report, and the verdict it printed was PASS -- a report
    # carrying a fabricated quote passed a gate it had never been through, and
    # step 7 would have stopped looping. Nothing in the drift suite could see
    # it, because the exit code is a property of report_qc.py, not of the
    # contract.
    fbr = os.path.join(tmp, "fixbr.md")
    io.open(fbr, "w", encoding="utf-8").write(
        brief_report().replace("SELECT foo FROM bar INTO @DATA(ls_foo).",
                               "SELECT foo FROM bar INTO @DATA(ls_foo). WRITE 2."))
    pl = run(QC, fbr, src)
    check(pl.returncode == 1 and "FAIL" in pl.stdout,
          "plain mode fails a shape-clean report with one fabricated quote")
    fx = run(QC, "--fix", fbr, src, "-o", os.path.join(tmp, "fixbr.out.md"))
    check(fx.returncode == 1,
          "--fix exits nonzero while a rewrite still needs the model",
          "same report as plain mode above, so the exit codes must agree")
    check("PASS" not in fx.stdout,
          "--fix does not print PASS for a report that still needs the model",
          "FAIL line: " + next((l for l in fx.stdout.splitlines()
                                if l.startswith("FAIL")), "none")[:60])
    check("shape defect" not in fx.stdout,
          "--fix names a rewrite, not a shape defect, when only one is left")
    check("rewrite(s)" in fx.stdout,
          "--fix says what is left needs the model")
    # A run that fails to start and a run that reports defects used to be
    # indistinguishable: a missing file raised FileNotFoundError out of the check
    # loop, which exited 1 -- the code a real defect returns. Step 6 loops "until
    # clean", and clean is 0, so a run that never executed read as one that found
    # problems. rc 2 is reserved for "the gate did not run".
    print()
    print("an unreadable input is not a defect")
    print("-" * 72)
    miss = os.path.join(tmp, "no-such-file.md")
    no_src = os.path.join(tmp, "no-such-source.abap")
    for mode, argv in [("plain", [miss]),
                       ("--fidelity-only", ["--fidelity-only", miss, src]),
                       ("--fix", ["--fix", miss, src])]:
        r = run(QC, *argv)
        check(r.returncode == 2 and "Traceback" not in r.stderr,
              "%s: a missing report exits 2, not a traceback" % mode,
              r.stdout.strip().split("\n")[-1][:44] if r.stdout.strip() else "")
        check(os.path.basename(miss) in r.stdout,
              "%s: the message names the missing file" % mode)
    for mode, argv in [("plain", [good, no_src]),
                       ("--fidelity-only", ["--fidelity-only", good, no_src]),
                       ("--fix", ["--fix", good, no_src])]:
        r = run(QC, *argv)
        check(r.returncode == 2 and "Traceback" not in r.stderr,
              "%s: a missing source exits 2, not a traceback" % mode)

    # Two sources resolved to the last one, silently, and the run printed PASS.
    # It is a bad call, not a defect in the report.
    other = os.path.join(tmp, "other.abap")
    io.open(other, "w", encoding="utf-8").write("FORM z_other.\nENDFORM.\n")
    r = run(QC, good, src, other)
    check(r.returncode == 2 and "Traceback" not in r.stderr,
          "two sources are refused instead of the last one winning")
    check("more than one source" in r.stdout,
          "the refusal names the colliding arguments")
    r = run(QC, "--fidelity-only", good, src, other)
    check(r.returncode == 2, "--fidelity-only also refuses two sources")

    # ln reported line 0, which the renderer turned into "document" and sent the
    # writer hunting the whole file for a span one jump away.
    lnp = os.path.join(tmp, "ln.md")
    io.open(lnp, "w", encoding="utf-8").write(
        brief_report().replace("**为什么** — 索引命中。",
                               "**为什么** — 索引命中（见 `L104`）。"))
    r = run(QC, lnp, src)
    row = [x for x in r.stdout.splitlines() if x.strip().startswith("ln")]
    check(len(row) == 1 and "line " in row[0],
          "an ln defect names the line that carries it",
          (row[0].strip() if row else "").replace("document", "?"))

    # Locks the repair: CITE_NUM must be a search, not a full-string match, so a
    # parenthesised or ranged citation still yields a number. It was anchored at
    # both ends and refused three of the four forms SKILL.md prints as wrong, and
    # nothing caught it because no test inspected what --fix actually writes.
    print()
    print("--fix writes what it claims")
    print("-" * 72)
    for i, cite in enumerate(["`zvend.abap:104`", "`（L104）`",
                              "`（第 90-96 行）`", "`L104`"]):
        rp = os.path.join(tmp, "cite%d.md" % i)
        io.open(rp, "w", encoding="utf-8").write(
            brief_report().replace("**为什么** — 索引命中。",
                                   "**为什么** — 索引命中（见 %s）。" % cite))
        outp = os.path.join(tmp, "cite%d.out.md" % i)
        r = run(QC, "--fix", rp, src, "-o", outp)
        fixed = io.open(outp, encoding="utf-8").read()
        check("repaired" in r.stdout and cite not in fixed,
              "--fix rewrites the citation form %s" % cite)

    # A citation past the end of the source is a claim about lines that do not
    # exist. Guessing an anchor would fabricate the citation it replaced, so it
    # stays for the writer -- but says so, because the note used to say the file
    # had no anchor when it was the citation that could not be read.
    far = os.path.join(tmp, "far.md")
    io.open(far, "w", encoding="utf-8").write(
        brief_report().replace("**为什么** — 索引命中。",
                               "**为什么** — 索引命中（见 `zvend.abap:999999`）。"))
    r = run(QC, "--fix", far, src, "-o", os.path.join(tmp, "far.out.md"))
    check("point past the end of the source" in r.stdout,
          "an unreadable citation is reported as such",
          r.stdout.strip().split("\n")[-1][:44] if r.stdout.strip() else "")
    # --fix only writes a .bak when it actually changed something; a clean
    # report is left byte-for-byte alone, which is what makes the backup safe.
    bak = os.path.join(tmp, "inplace.md")
    io.open(bak, "w", encoding="utf-8").write(
        brief_report().replace("**为什么** — 索引命中。",
                               "**为什么** — 索引命中（见 `zvend.abap:104`）。"))
    r = run(QC, "--fix", bak, src)
    check(os.path.exists(bak + ".bak"),
          "--fix in place leaves the previous version behind",
          r.stdout.strip().split("\n")[-1][:44] if r.stdout.strip() else "")
    if os.path.exists(bak + ".bak"):
        before = io.open(bak + ".bak", encoding="utf-8").read()
        after = io.open(bak, encoding="utf-8").read()
        check("zvend.abap:104" in before and "zvend.abap:104" not in after,
              "the backup holds the pre-fix text, not the rewritten one")
    # A line citation needs a source to anchor to, so a sourceless --fix is a
    # refusal rather than a run that repaired nothing and said so quietly.
    r = run(QC, "--fix", bak)
    check(r.returncode == 2 and "needs REPORT and SOURCE" in r.stdout,
          "--fix without a source refuses instead of repairing nothing")

    # participant and actor are the same role in a sequence diagram. Only the
    # first was aliased when this was written, so `actor U as U <x>` slipped
    # through as a bare arrow while its participant twin was caught -- the same
    # asymmetry class as the ln split, in a different function.
    print()
    print("alias forms")
    print("-" * 72)
    for role in ("participant", "actor"):
        sp = os.path.join(tmp, "alias-%s.md" % role)
        io.open(sp, "w", encoding="utf-8").write(
            brief_report().replace('A["Z_FOO"] --> B["输出"]',
                                   "%s U as U <x>" % role))
        r = run(QC, sp)
        row = [x for x in r.stdout.splitlines() if x.strip().startswith("mm")]
        check(len(row) == 1 and "line " in row[0],
              "%s alias is scanned like a node label" % role,
              (row[0].strip() if row else "")[:46])

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
             # a positive verdict must point at the text carrying it. A bare
             # line number is an assertion with nothing to check, so it is
             # refused: the fixture cites the words it rests on
             "evidence": {"D1": {"report_line": 5, "quote": "解决什么问题"},
                          "D2": {"report_line": 5, "quote": "解决什么问题"}},
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

    def noret(v):
        v["report"] = os.path.join(tmp, "no-such-report.md")

    def nokey(v):
        v.pop("report")

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
        ("badquote", lambda v: v["evidence"]["D1"].update(quote="appears nowhere"),
         "a quote that is not on the cited line is rejected"),
        ("noret", noret,
         "a citation to a report that does not exist is rejected"),
        ("nokey", nokey,
         "a verdict file with no report path is rejected"),
    ]:
        r = run(EVAL, "score", "--defects", defs, "--verdicts", vfile(name, mut))
        check(r.returncode != 0 and "REJECTED" in r.stdout, label)

    # The rejection must be visible: a citation requirement accepted without
    # being verified would score a fabricated line as a clean pass. vfile("noret")
    # rewrites the same path the loop already used, so this gets its own file.
    r = run(EVAL, "score", "--defects", defs, "--verdicts", vfile("noretmsg", noret))
    check("cannot be checked" in r.stdout,
          "the rejection says the citations were not verified",
          r.stdout.strip().split("\n")[-1][:44] if r.stdout.strip() else "")

    # ------------------------------------------------------------------
    # Locked by the 1.2.2 review. Each case below is a fix the suite as it
    # stood could not see: the old behaviour passed every existing check.
    print()
    print("regressions locked in 1.2.2")
    print("-" * 72)
    # A citation embedded in prose. The fix replaced the whole backticked
    # span, deleting the statement the citation pointed at, and then reported
    # the repair as complete. Only the citation moves; the prose stays.
    prose = os.path.join(tmp, "prose.md")
    io.open(prose, "w", encoding="utf-8").write(
        brief_report().replace("**为什么** — 索引命中。",
                               "**为什么** — 索引命中（见 `L03 SELECT foo FROM bar`）。"))
    r = run(QC, "--fix", prose, src, "-o", os.path.join(tmp, "prose.out.md"))
    out = io.open(os.path.join(tmp, "prose.out.md"), encoding="utf-8").read()
    check("repaired" in r.stdout and "SELECT foo FROM bar" in out,
          "--fix rewrites the citation, not the prose around it",
          out.strip().split("\n")[-1][:44])
    check("L03" not in out, "the line citation itself is gone")

    # A trailing -o used to index past the end of argv.
    r = run(QC, "--fix", good, src, "-o")
    check(r.returncode == 2 and "Traceback" not in r.stderr,
          "a bare -o exits 2 instead of raising IndexError",
          r.stdout.strip().split("\n")[-1][:44] if r.stdout.strip() else "")

    # Six-digit citations were invisible: two of the five contract patterns
    # capped at {2,5} while the other three did not, so the same report
    # scored differently depending on which spelling the model chose.
    for cite in ("L100000", "obj:123456"):
        p = os.path.join(tmp, "big%d.md" % len(cite))
        io.open(p, "w", encoding="utf-8").write(
            brief_report().replace("**为什么** — 索引命中。",
                                   "**为什么** — 索引命中（见 `%s`）。" % cite))
        r = run(QC, p, src)
        check(any(x.strip().startswith("ln") for x in r.stdout.splitlines()),
              "a %s citation is flagged" % cite)
    # A time literal in backticks is not a line citation: :30 follows a
    # digit, which a bare :NN never does. Before the guard, `01:30:00`
    # read as a citation to line 30.
    p = os.path.join(tmp, "time.md")
    io.open(p, "w", encoding="utf-8").write(
        brief_report().replace("**为什么** — 索引命中。",
                               "**为什么** — 窗口 `01:30:00` 内取数。"))
    r = run(QC, p, src)
    check(not any(x.strip().startswith("ln") for x in r.stdout.splitlines()),
          "a time literal is not reported as a line citation")

    # "### 一" contains "## 一", so a report written entirely at level three
    # satisfied every section -- and section 五 was then harvested from the
    # wrong place, which is where the prow and buck checks read from.
    p = os.path.join(tmp, "h3.md")
    io.open(p, "w", encoding="utf-8").write(brief_report().replace("## ", "### "))
    r = run(QC, p)
    check(any(x.strip().startswith("sec") for x in r.stdout.splitlines()),
          "level-three headings do not pass for level two")

    # An empty source is not a missing one, and a source that is not utf-8
    # must not be scored against as a U+FFFD stream: every quotation would
    # then fail to match, and the fidelity note would call the report a liar.
    emp = os.path.join(tmp, "empty.abap")
    io.open(emp, "w", encoding="utf-8").write("")
    # Plain mode can still check shape, so it says what it could not measure
    # and keeps going. Fidelity-only has nothing to compare against, so it
    # refuses -- before this it reported "no such source", which was a lie.
    r = run(QC, good, emp)
    check("no analysable content" in r.stdout and "not run" in r.stdout,
          "an empty source says what it could not measure",
          r.stdout.strip().split("\n")[-1][:44])
    r = run(QC, "--fidelity-only", good, emp)
    check(r.returncode == 2 and "no analysable content" in r.stdout
          and "Traceback" not in r.stderr,
          "--fidelity-only refuses an empty source, not a missing one",
          r.stdout.strip().split("\n")[-1][:44] if r.stdout.strip() else "")
    binf = os.path.join(tmp, "bad.abap")
    io.open(binf, "wb").write(b"FUNCTION z_foo.\nSELECT \xff\xfe FROM bar.\n")
    r = run(QC, good, binf)
    check(r.returncode == 2 and "utf-8" in r.stdout and "Traceback" not in r.stderr,
          "an undecodable source is refused, not scored against",
          r.stdout.strip().split("\n")[-1][:44] if r.stdout.strip() else "")

    # An empty source and a source of blanks are the same thing: neither has
    # anything to compare against. report_qc.py tested not src.strip() while
    # every source-dependent check tested not src, so a file of blanks was
    # truthy and reached the detectors as a real source. classify() then counted
    # zero identifiers and called every quotation a fabrication, and row-src
    # computed an empty flat_src instead of None, which skipped its own
    # "no source given: cannot judge, so do not fail" hatch and reported every
    # problem row as naming nothing. One blank file turned the report above into
    # 28 defects, the same false verdict the undecodable-source refusal just
    # above exists to stop: what could not be judged was reported as a
    # judgement. The fixture below carries one quoted statement and one problem
    # row, so both halves of it are exercised.
    ws = os.path.join(tmp, "ws.abap")
    io.open(ws, "w", encoding="utf-8").write("   \n\t\n")
    r = run(QC, good, ws)
    check(r.returncode == 0 and not any(
        x.strip().startswith(("SUBSTA", "PUNCT-", "row-src"))
        for x in r.stdout.splitlines()),
          "a source of blanks is not a source that nothing matches",
          r.stdout.strip().split("\n")[-1][:44] if r.stdout.strip() else "")
    check("no analysable content" in r.stdout and "not run" in r.stdout,
          "a source of blanks says the same thing as an empty one",
          r.stdout.strip().split("\n")[-1][:44] if r.stdout.strip() else "")
    wsout = os.path.join(tmp, "ws.out.md")
    r = run(QC, "--fix", good, ws, "-o", wsout)
    check(r.returncode == 0 and "rewrite" not in r.stdout,
          "--fix reports no rewrites against a source of blanks",
          r.stdout.strip().split("\n")[-1][:44] if r.stdout.strip() else "")
    r = run(QC, "--fidelity-only", good, ws)
    check(r.returncode == 2 and "no analysable content" in r.stdout,
          "--fidelity-only refuses a source of blanks, as it does an empty one")

    # The two shapes the blank check could not reach. `.strip()` removes
    # whitespace and control bytes are not whitespace, so a file of NUL bytes
    # survived it and the gate scored the report against a source with
    # nothing in it -- the same false verdict as a blank one. isprintable()
    # alone is no better: it is True of U+FFFD, so a source that is nothing
    # but the replacement character passed, and a document was generated
    # about a program that does not exist. Both now take the blank line.
    for label, payload in (("NUL bytes", b"\x00" * 500),
                           ("only U+FFFD", (("\ufffd" * 9000)
                                            .encode("utf-8")))):
        junk = os.path.join(tmp, "junk.abap")
        io.open(junk, "wb").write(payload)
        r = run(QC, good, junk)
        check("no analysable content" in r.stdout and "not run" in r.stdout,
              "a source of %s says what the gate could not measure" % label,
              r.stdout.strip().split("\n")[-1][:44] if r.stdout.strip() else "")
        check(not any(x.strip().startswith(("SUBSTA", "PUNCT-", "row-src"))
                      for x in r.stdout.splitlines()),
              "a source of %s is not scored against as a real source" % label)
        r = run(QC, "--fidelity-only", good, junk)
        check(r.returncode == 2 and "no analysable content" in r.stdout
              and "Traceback" not in r.stdout + r.stderr,
              "--fidelity-only refuses a source of %s" % label,
              "rc=%d" % r.returncode)
        check(not any(x.strip().startswith(("SUBSTA", "PUNCT-", "row-src"))
                      for x in r.stdout.splitlines()),
              "the refusal on a source of %s names nothing else" % label)


    # The pass normalizes line endings internally and must hand the report
    # back in the shape it found it. Before this, a CRLF report came back LF
    # because the read translated and the write translated again.
    crlf = os.path.join(tmp, "crlf.md")
    io.open(crlf, "wb").write(
        brief_report().replace("**为什么** — 索引命中。",
                               "**为什么** — 索引命中（见 `zvend.abap:104`）。")
        .encode("utf-8").replace(b"\n", b"\r\n"))
    run(QC, "--fix", crlf, src, "-o", os.path.join(tmp, "crlf.out.md"))
    raw = io.open(os.path.join(tmp, "crlf.out.md"), "rb").read()
    lone = raw.replace(b"\r\n", b"").count(b"\n")
    check(b"\r\n" in raw and lone == 0,
          "--fix keeps the report's line endings",
          "crlf=%d lone_lf=%d" % (raw.count(b"\r\n"), lone))

    # fidelity_note reported a position inside its own filtered list, so a
    # skipped line above a fabrication moved the reported line number.
    fid = brief_report().replace("SELECT foo FROM bar INTO",
                                 "取数。\nSELECT foo FROM baz INTO")
    p = os.path.join(tmp, "fid.md")
    io.open(p, "w", encoding="utf-8").write(fid)
    r = run(QC, p, src)
    row = [x for x in r.stdout.splitlines() if "not occur in the source" in x]
    m = re.search(r"line (\d+)", row[0]) if row else None
    actual = fid.split("\n").index("SELECT foo FROM baz INTO @DATA(ls_foo).") + 1
    check(bool(m) and int(m.group(1)) == actual,
          "a fidelity note names the line that carries the fabrication",
          "reported=%s actual=%d" % (m.group(1) if m else "?", actual))

    # ------------------------------------------------------------------
    # evaluate.py: the validation is the point of this file, so a broken
    # verdict file must be rejected rather than crash. A traceback exits 1,
    # the same code a real recall shortfall gets, and a corrupt file read as
    # a bad report is the failure this whole exercise is meant to prevent.
    broken = os.path.join(tmp, "broken.json")
    io.open(broken, "w", encoding="utf-8").write(
        '{"report": "x", "verdicts": {"D1": ')
    r = run(EVAL, "score", "--defects", defs, "--verdicts", broken)
    check(r.returncode == 2 and "REJECTED" in r.stdout and "Traceback" not in r.stderr,
          "an unparseable verdict file is rejected, not a traceback",
          r.stdout.strip().split("\n")[-1][:44] if r.stdout.strip() else "")
    notstr = os.path.join(tmp, "notstr.json")
    io.open(notstr, "w", encoding="utf-8").write(json.dumps({
        "report": ["a", "b"], "verdicts": {"D1": "yes", "D2": "no"},
        "false_claims": []}, ensure_ascii=False))
    r = run(EVAL, "score", "--defects", defs, "--verdicts", notstr)
    check(r.returncode == 2 and "REJECTED" in r.stdout and "Traceback" not in r.stderr,
          "a non-string report path is rejected, not a traceback")
    def noquote(v):
        for e in v["evidence"].values():
            e.pop("quote", None)
    r = run(EVAL, "score", "--defects", defs, "--verdicts", vfile("noquote", noquote))
    check(r.returncode != 0 and "no quote" in r.stdout,
          "a positive verdict citing only a line number is rejected")
    # --legacy is the escape hatch for pre-citation files, and it has to say
    # it is one: a scored file reads as auditable, and these are not.
    r = run(EVAL, "score", "--defects", defs, "--verdicts", vfile("legacy", noquote),
            "--legacy")
    check(r.returncode == 0 and "--legacy" in r.stdout,
          "waiving citations announces itself instead of scoring silently")
    # --legacy waives the citation requirement only. A false claim without a
    # reason is not auditable, and an escape hatch that swallowed that as well
    # would score an unexplained error as a clean result.
    r = run(EVAL, "score", "--defects", defs, "--verdicts", vfile("legfc", fc_bad),
            "--legacy")
    check(r.returncode != 0 and "REJECTED" in r.stdout,
          "--legacy does not waive the false_claims requirement")

    # ------------------------------------------------------------------
    print()
    print("fences and the one-directional pair")
    print("-" * 72)
    # An unclosed fence used to be invisible. FENCE was non-greedy, so an opener
    # with no closer made the rest of the document unreachable to every check
    # that reads fence-free text, and the run reported back clean on exactly the
    # part of the report the fence had swallowed.
    unclosed = brief_report().replace(
        '  A["Z_FOO"] --> B["输出"]\n```\n\n', '  A["Z_FOO"] --> B["输出"]\n\n')
    p = os.path.join(tmp, "unclosed.md")
    io.open(p, "w", encoding="utf-8").write(unclosed)
    r = run(QC, p)
    check(any(x.strip().startswith("fence") for x in r.stdout.splitlines()),
          "an unclosed code fence is reported")
    check(r.returncode == 1, "an unclosed fence exits nonzero, not clean")

    # The defect only matters because it hides other defects. The citation below
    # sits inside the swallowed region, so blank_fences blanked through to EOF
    # and the ln check never saw it.
    p = os.path.join(tmp, "unclosed2.md")
    io.open(p, "w", encoding="utf-8").write(
        unclosed.replace("一句结论。", "一句结论（见 `zvend.abap:104`）。"))
    r = run(QC, p, src)
    check(any(x.strip().startswith("fence") for x in r.stdout.splitlines())
          and any(x.strip().startswith("ln") for x in r.stdout.splitlines()),
          "the swallowed region is still inspected")

    # Mermaid renders a small HTML subset, so <br> is the diagram's own text. The
    # checker stripped those tags before testing and the fixer converted them,
    # so --fix wrote ＜br＞ and reported the result as clean.
    p = os.path.join(tmp, "html.md")
    io.open(p, "w", encoding="utf-8").write(
        brief_report().replace('A["Z_FOO"]', 'A["Z_FOO<br>取数"]'))
    r = run(QC, p, src)
    check(not any(x.strip().startswith("mm") for x in r.stdout.splitlines()),
          "Mermaid's HTML subset is not reported as a bare angle bracket")
    run(QC, "--fix", p, src, "-o", os.path.join(tmp, "html.out.md"))
    kept = io.open(os.path.join(tmp, "html.out.md"), encoding="utf-8").read()
    check('A["Z_FOO<br>取数"]' in kept and "＜" not in kept,
          "--fix leaves a rendered tag alone",
          "fullwidth in output" if "＜" in kept else "")

    # Tolerance is not a blanket exemption: a genuinely bare > in the same label
    # is still converted.
    p = os.path.join(tmp, "html2.md")
    io.open(p, "w", encoding="utf-8").write(
        brief_report().replace('A["Z_FOO"]', 'A["Z_FOO->bar<br>取数"]'))
    run(QC, "--fix", p, src, "-o", os.path.join(tmp, "html2.out.md"))
    kept = io.open(os.path.join(tmp, "html2.out.md"), encoding="utf-8").read()
    check('A["Z_FOO-＞bar<br>取数"]' in kept,
          "--fix converts the bare angle brackets and keeps the tag",
          kept.strip().split("\n")[10][:56])

    # Fence language is the admission test, so its spelling cannot decide whether
    # a block is checked. Deleting one layer must be caught under every spelling.
    for openf in ("```abap\n", "```ABAP  \n", "````abap\n"):
        p = os.path.join(tmp, "lang%d.md" % len(openf))
        io.open(p, "w", encoding="utf-8").write(
            brief_report().replace("```abap\n", openf)
                          .replace("**为什么** — 索引命中。\n", ""))
        r = run(QC, p, src)
        check(any(x.strip().startswith("A8") for x in r.stdout.splitlines()),
              "the fence marker %s still admits the block" % repr(openf))

    # The abap / abap-fix pair locked in one direction only: a fix left in an
    # abap fence is probed against the source and reads as fabricated, but
    # source pasted into an abap-fix fence is never compared with the source at
    # all, so the language tag could opt a quotation out of the check that
    # exists to catch invented quotes.
    block = "```abap\nSELECT foo FROM bar INTO @DATA(ls_foo).\n```"
    p = os.path.join(tmp, "mislabel.md")
    io.open(p, "w", encoding="utf-8").write(
        brief_report().replace(
            block,
            "```abap-fix\nSELECT foo FROM bar INTO @DATA(ls_foo).\n```"))
    r = run(QC, p, src)
    check("repeat the source verbatim" in r.stdout,
          "source pasted into an abap-fix fence is called out")
    check(r.returncode == 0, "a mislabeled fence is a question, not a failure")

    p = os.path.join(tmp, "mislabel2.md")
    io.open(p, "w", encoding="utf-8").write(
        brief_report().replace(
            block,
            "```abap-fix\nSELECT foo FROM baz INTO @DATA(ls_foo).\n```"))
    r = run(QC, p, src)
    check("repeat the source verbatim" not in r.stdout,
          "a genuine abap-fix fence is not called out")
    check(r.returncode == 0, "an abap-fix fence needs no three layers")

    # The criterion is contiguity, not membership. Asking whether every statement
    # occurs somewhere in the source fired five times across nine real reports and
    # every one of those five was a genuine fix -- a CALL FUNCTION with EXCEPTIONS
    # added, a DELETE followed by an sy-subrc check, a restructured TRY block --
    # each line of which exists somewhere in a 1600-line file. Quoting the line
    # you are about to change is legitimate, so membership cannot be the test. A
    # mislabeled quote is a verbatim copy, and a verbatim copy is contiguous.
    # These two cases are what decides it, so they are the ones that must fail
    # loudly if the criterion is reverted.
    asm = os.path.join(tmp, "assembled.abap")
    io.open(asm, "w", encoding="utf-8").write(
        "FUNCTION z_foo.\n"
        "  DELETE FROM d021t.\n"
        "ENDFUNCTION.\n"
        "FUNCTION z_bar.\n"
        "  IF sy-subrc <> 0.\n"
        "    RETURN.\n"
        "  ENDIF.\n"
        "ENDFUNCTION.\n")

    p = os.path.join(tmp, "assembled.md")
    io.open(p, "w", encoding="utf-8").write(
        brief_report().replace(
            block,
            "```abap-fix\nDELETE FROM d021t.\nIF sy-subrc <> 0.\n  RETURN.\n"
            "ENDIF.\n```"))
    r = run(QC, p, asm)
    check("repeat the source verbatim" not in r.stdout,
          "a fix whose lines each exist but are not adjacent is not called out")

    p = os.path.join(tmp, "contiguous.md")
    io.open(p, "w", encoding="utf-8").write(
        brief_report().replace(
            block,
            "```abap-fix\nIF sy-subrc <> 0.\n  RETURN.\n  ENDIF.\n```"))
    r = run(QC, p, asm)
    check("repeat the source verbatim" in r.stdout,
          "a contiguous multi-line copy is still called out")
    check(r.returncode == 0, "that is still a note, not a failure")

    # The gate must not die on a classic screen program. START-OF-SELECTION and
    # its five siblings are event blocks, and ANCHORS gives them no capture
    # group because the keyword is the name. Anchoring on group 1 for every
    # entry raised IndexError on the first of them, so any report checked
    # against the 17 shipped sources that declare one crashed with a traceback
    # and exited 1 -- the defect verdict. SKILL.md step 7 tells the model to
    # re-run until the exit code is 0, so the caller looped on a crash and
    # could never tell that nothing had been checked. Asserted as behaviour,
    # because reading the source would have told the truth: inventory() was
    # one line short of the crash, and the docstring two lines above it already
    # explained why the event blocks had been added.
    print()
    print("the gate does not die on an event block")
    print("-" * 72)
    ev = os.path.join(tmp, "events.abap")
    io.open(ev, "w", encoding="utf-8").write(
        "REPORT zevents.\n"
        "INITIALIZATION.\n  WRITE / 'init'.\n"
        "AT SELECTION-SCREEN.\n  WRITE / 'screen'.\n"
        "START-OF-SELECTION.\n  WRITE / 'start'.\n"
        "AT USER-COMMAND.\n  WRITE / 'command'.\n"
        "END-OF-SELECTION.\n  WRITE / 'end'.\n"
        "TOP-OF-PAGE.\n  WRITE / 'top'.\n")
    p = os.path.join(tmp, "events.md")
    io.open(p, "w", encoding="utf-8").write(brief_report())
    r = run(QC, p, ev)
    check("Traceback" not in r.stdout + r.stderr,
          "a report checked against event blocks does not raise")
    check(r.returncode in (0, 1, 2),
          "an event-block run returns a verdict, not a traceback",
          f"rc={r.returncode}")
    check("for 6 declared subprogram(s)" in r.stdout,
          "inventory() counts all six event blocks as a denominator",
          r.stdout.strip().splitlines()[-1][:90] if r.stdout.strip() else "")

    # The guard above was added around the shape-mode check loop, and the promise
    # it enforces is written for every mode: exit_codes["2"] says an unhandled
    # exception inside the check loop refuses in every mode. The other two
    # branches called their detectors bare, so the same crash there exited 1 with
    # a traceback -- the code SKILL.md defines as "the check ran and found
    # defects" -- and in --fix it did so after the output file had already been
    # rewritten. Step 7 loops until the exit code is 0, so each of those read as
    # a report with defects left to fix. Injected rather than read from the
    # source, for the same reason as the event-block check above.
    print()
    print("a detector that raises refuses, it does not report defects")
    print("-" * 72)
    boom = os.path.join(tmp, "boom.py")
    io.open(boom, "w", encoding="utf-8").write(
        "import sys\n"
        "sys.path.insert(0, %r)\n"
        "import report_qc as R\n"
        "def raise_it(*a, **k):\n"
        "    raise RuntimeError('injected')\n"
        "for _n in ('check', 'fix', 'fidelity_report', 'all_notes'):\n"
        "    setattr(R, _n, raise_it)\n"
        "sys.exit(R.main(sys.argv))\n" % os.path.join(SKILL, "scripts"))
    bp = os.path.join(tmp, "boom.md")
    io.open(bp, "w", encoding="utf-8").write(brief_report())
    for mode, argv in [("plain", [bp, ev]),
                       ("--fidelity-only", ["--fidelity-only", bp, ev]),
                       ("--fix", ["--fix", bp, ev, "-o",
                                  os.path.join(tmp, "boom.out.md")])]:
        r = run(boom, *argv)
        check("Traceback" not in r.stdout + r.stderr,
              "%s: an injected detector crash is not a traceback" % mode)
        check(r.returncode == 2,
              "%s: a crashing detector exits 2, not the defect verdict" % mode,
              "rc=%d" % r.returncode)
        check("the gate crashed" in r.stdout,
              "%s: a crashing detector says nothing was checked" % mode,
              r.stdout.strip().splitlines()[-1][:70] if r.stdout.strip() else "")
    # All four --fix detectors now run before anything is written. Until 1.3.6
    # the write sat between the second detector and the three after it, so a
    # crash in any of those exited 2 and said nothing had been inspected while
    # the output file was already on disk. In place that report is usually the
    # only copy, so the caller had to recover from a .bak rather than from a
    # refusal.
    for nth in (1, 2, 3, 4):
        io.open(boom, "w", encoding="utf-8").write(
            "import sys\n"
            "sys.path.insert(0, %r)\n"
            "import report_qc as R\n"
            "_c = [0]\n"
            "def _wrap(fn):\n"
            "    def _w(*a, **k):\n"
            "        _c[0] += 1\n"
            "        if _c[0] == %d:\n"
            "            raise RuntimeError('injected')\n"
            "        return fn(*a, **k)\n"
            "    return _w\n"
            "for _n in ('check', 'fix', 'fidelity_report',"
            " 'all_notes'):\n"
            "    setattr(R, _n, _wrap(getattr(R, _n)))\n"
            "sys.exit(R.main(sys.argv))\n"
            % (os.path.join(SKILL, "scripts"), nth))
        co = os.path.join(tmp, "crash%d.out.md" % nth)
        if os.path.exists(co):
            os.remove(co)
        r = run(boom, "--fix", bp, ev, "-o", co)
        check(r.returncode == 2 and not os.path.exists(co),
              "--fix: a crash in detector %d leaves no file behind" % nth,
              "rc=%d file=%s" % (r.returncode, os.path.exists(co)))

    # The four detectors are guarded, but nothing guarded the write. open()
    # raising ended --fix in a traceback with exit 1 -- the defect verdict a
    # caller loops on -- after the report had already been read and its defects
    # found, with the repair simply unsaved. The pre-flight check covers only
    # the directory of -o, never -o itself, which is why no test reached it.
    print()
    print("--fix refuses a write that cannot happen")
    print("-" * 72)
    wd = os.path.join(tmp, "outdir")
    os.makedirs(wd)
    rep2 = os.path.join(tmp, "writefix.md")
    io.open(rep2, "w", encoding="utf-8").write(brief_report())
    ro2 = os.path.join(tmp, "readonly.md")
    io.open(ro2, "w", encoding="utf-8").write(brief_report())
    os.chmod(ro2, 0o444)
    for label, argv in [("an existing directory", [rep2, ev, "-o", wd]),
                        ("an existing read-only file", [rep2, ev, "-o", ro2])]:
        r = run(QC, "--fix", *argv)
        errs = [x for x in r.stdout.splitlines() if x.startswith("error")]
        check("Traceback" not in r.stdout + r.stderr,
              "--fix: %s is not a traceback" % label)
        check(r.returncode == 2,
              "--fix: %s exits 2, not the defect verdict" % label,
              "rc=%d" % r.returncode)
        check(len(errs) == 1 and "could not write" in errs[0],
              "--fix: %s says it could not write" % label,
              (errs[0][:60] if errs else "no error line"))
        check("nothing was written" in r.stdout,
              "--fix: %s says the report is untouched" % label)
        check(not [x for x in r.stdout.splitlines()
                   if x.startswith("PASS") or x.startswith("FAIL")],
              "--fix: %s prints no verdict" % label)
    # In place, the .bak is written before the report, so a .bak that
    # already exists as a directory blocks the first of the two writes. The
    # report needs a real repair: --fix writes nothing for a clean one, so
    # there would be no write to fail.
    ip = os.path.join(tmp, "inplace2.md")
    io.open(ip, "w", encoding="utf-8").write(
        brief_report().replace("**为什么** — 索引命中。",
                               "**为什么** — 索引命中（见 `zvend.abap:104`）。"))
    if os.path.exists(ip + ".bak"):
        os.remove(ip + ".bak")
    os.makedirs(ip + ".bak")
    unedited = io.open(ip, encoding="utf-8").read()
    r = run(QC, "--fix", ip, src)
    check(r.returncode == 2 and "could not write" in r.stdout,
          "--fix: an in-place .bak that is a directory refuses",
          "rc=%d" % r.returncode)
    check(io.open(ip, encoding="utf-8").read() == unedited,
          "--fix: a refused write leaves the report byte-identical")

    # A repair rewrites tokens inside a line and never adds or removes one, so
    # break i of the repaired text is break i of the report. Carrying the breaks
    # back one for one is what preserving the report's own endings means. The
    # boolean test read "the report has a CRLF somewhere" as "the report is
    # CRLF" and turned one CRLF among fifty-five LFs into fifty-six CRLFs -- a
    # whole-file re-save, reported by a receipt that said it had repaired
    # nothing.
    def readt(p):
        """A text file, or None when the write it should have come from did not.

        newline="" on purpose: the default mode is universal newlines and turns
        CRLF into LF, which is exactly what these checks are about.
        """
        try:
            return io.open(p, encoding="utf-8", newline="").read()
        except OSError:
            return None

    def breaks(text):
        """The breaks of text in order: 1 for CRLF, 0 for LF."""
        out, i = [], 0
        while i < len(text):
            if text.startswith("\r\n", i):
                out.append(1)
                i += 2
            elif text[i] == "\n":
                out.append(0)
                i += 1
            else:
                i += 1
        return tuple(out)

    print()
    print("--fix carries the report's own endings back")
    print("-" * 72)
    body = brief_report().replace("**为什么** — 索引命中。",
                                  "**为什么** — 索引命中（见 `zvend.abap:104`）。")
    for i, (label, text) in enumerate([
            ("every break CRLF", body.replace("\n", "\r\n")),
            ("every break LF", body),
            ("one CRLF among LFs", body.replace("\n", "\r\n", 1))]):
        mp = os.path.join(tmp, "ends%d.md" % i)
        io.open(mp, "w", encoding="utf-8", newline="").write(text)
        op = mp + ".out.md"
        r = run(QC, "--fix", mp, src, "-o", op)
        got = readt(op)
        check(breaks(got) == breaks(text),
              "--fix keeps the breaks a %s report had" % label,
              "in=%d out=%d" % (len(breaks(text)), len(breaks(got))))
        check("zvend.abap:104" not in got,
              "--fix still repairs inside a %s report" % label)
    check(sum(breaks(body.replace("\n", "\r\n", 1))) == 1,
          "the mixed case really is one CRLF among LFs")

    # In place the backup holds the report's bytes, breaks included, so a
    # recovery hands back the file the report was before the run.
    mp = os.path.join(tmp, "ends-in.md")
    mixed = body.replace("\n", "\r\n", 1)
    io.open(mp, "w", encoding="utf-8", newline="").write(mixed)
    r = run(QC, "--fix", mp, src)
    check(readt(mp + ".bak") == mixed,
          "--fix: the in-place backup keeps the report's breaks")

    # -o may name a file that already holds someone else's report. Replacing it
    # would leave nothing to recover from, so the rule in place applies: save
    # the previous text before the write.
    print()
    print("--fix keeps the file an -o replaces")
    print("-" * 72)
    rep4 = os.path.join(tmp, "ovr.md")
    io.open(rep4, "w", encoding="utf-8").write(body)
    foreign = os.path.join(tmp, "foreign.md")
    io.open(foreign, "w", encoding="utf-8", newline="").write(
        "# someone else's file\n")
    foreign_before = readt(foreign)
    if os.path.lexists(foreign + ".bak"):
        os.remove(foreign + ".bak")
    r = run(QC, "--fix", rep4, src, "-o", foreign)
    check(os.path.exists(foreign + ".bak"),
          "--fix: the file an -o replaces is saved first",
          "rc=%d" % r.returncode)
    check(readt(foreign + ".bak") == foreign_before,
          "--fix: that backup is the file's own previous text")
    fixed_target = readt(foreign)
    check(fixed_target is not None and "zvend.abap:104" not in fixed_target,
          "--fix: the target now holds the repaired report")

    # A second run would overwrite that backup, and the first version of the
    # report is the one worth recovering. Refuse instead, so the caller decides
    # rather than losing it.
    ip2 = os.path.join(tmp, "ipbak.md")
    io.open(ip2, "w", encoding="utf-8").write(body)
    io.open(ip2 + ".bak", "w", encoding="utf-8", newline="").write(
        "an earlier backup\n")
    ip2_before = readt(ip2)
    r = run(QC, "--fix", ip2, src)
    check(r.returncode == 2,
          "--fix: a backup that already exists refuses",
          "rc=%d" % r.returncode)
    check("could not write" in r.stdout and "nothing was written" in r.stdout,
          "--fix: the refusal says it wrote nothing")
    check("Traceback" not in r.stdout + r.stderr,
          "--fix: the refusal is not a crash")
    check(not [x for x in r.stdout.splitlines()
               if x.startswith("PASS") or x.startswith("FAIL")],
          "--fix: it prints no verdict")
    check(readt(ip2 + ".bak") == "an earlier backup\n",
          "--fix: the earlier backup survives the refusal")
    check(readt(ip2) == ip2_before,
          "--fix: it leaves the report byte-identical")

    # PUNCT-ONLY is a quotation whose tokens DO occur in the source, only the
    # punctuation differing. Counting it as a mismatch made the note say not
    # one quotation matches the source in the one configuration that proves
    # the source is the right file -- and the next line said the first one
    # differs in punctuation only.
    print()
    print("the wrong-file hint fires only when every quotation is a rewrite")
    print("-" * 72)
    srcp = os.path.join(tmp, "hintsrc.abap")
    io.open(srcp, "w", encoding="utf-8").write(
        "FUNCTION z_probe.\n  DATA ls_foo TYPE i.\n"
        "  SELECT foo FROM bar INTO @DATA(ls_foo).\nENDFUNCTION.\n")
    R2 = "```abap\nSELECT foo FROM bar INTO @DATA(ls_foo).\n```"
    L3 = "**做什么** — 1. 取一行。\n**为什么** — 索引命中。\n**风险与改进** — 未判空。\n"
    two = brief_report().replace(
        R2, "```abap\nSELECT foo FROM bar INTO @DATA(ls_foo ).\n```\n\n"
            "```abap\nSELECT foo FROM bar INTO @DATA(ls_other).\n```\n\n" + L3)
    allb = brief_report().replace(
        R2, "```abap\nSELECT foo FROM bar INTO @DATA(ls_other).\n```\n\n"
            "```abap\nSELECT foo FROM bar INTO @DATA(ls_third).\n```\n\n" + L3)
    for label, body in [("one punctuation-only and one substantive", two),
                        ("two substantive", allb)]:
        f = os.path.join(tmp, "hint.md")
        io.open(f, "w", encoding="utf-8").write(body)
        r = run(QC, f, srcp)
        sub = [x for x in r.stdout.splitlines() if x.strip().startswith("SUBSTA")]
        check(len(sub) == 1 if "punctuation" in label else len(sub) == 2,
              "%s: only the substantive quotation is a defect line" % label,
              "%d row(s)" % len(sub))
        check(("not one quotation matches" in r.stdout)
              == label.startswith("two substantive"),
              "%s: the wrong-file hint is absent" % label)

    # --fidelity-only takes several reports and used to validate them inside
    # its loop, so it printed PASS for the earlier ones and then refused: exit
    # 2 after a verdict already on stdout. Plain mode pre-validates every path.
    print()
    print("a refusal never follows a printed verdict")
    print("-" * 72)
    okp = os.path.join(tmp, "okreport.md")
    io.open(okp, "w", encoding="utf-8").write(brief_report())
    gone = os.path.join(tmp, "no-such-report.md")
    for mode, argv in [("--fidelity-only", ["--fidelity-only", okp, gone, ev]),
                       ("plain", [okp, gone, ev])]:
        r = run(QC, *argv)
        check(r.returncode == 2 and "no such report" in r.stdout,
              "%s: a missing report path refuses" % mode,
              "rc=%d" % r.returncode)
        check(not [x for x in r.stdout.splitlines()
                   if x.startswith("PASS") or x.startswith("FAIL")],
              "%s: the refusal comes before any verdict" % mode)

    # The source's identity windows are enumerated up to 30 tokens per
    # position. A probe longer than that is not in the set at all, so it could
    # not be found -- and since classify() trusts neither classifier and takes
    # their union, that silence read as a SUBSTANTIVE rewrite even when the
    # quotation was verbatim. Measured over 81 sources and 177092 statements,
    # 8 exceeded the cap, longest 40 tokens, and each was a SUBSTANTIVE that
    # never cleared, so steps 6 and 7 looped on a defect that does not exist.
    print()
    print("a long quotation is not a rewrite")
    print("-" * 72)
    LONG = " ".join("x%d" % i for i in range(1, 42))
    lsrc = os.path.join(tmp, "longsrc.abap")
    io.open(lsrc, "w", encoding="utf-8").write(
        "FUNCTION z_long.\n  DATA ls_foo TYPE i.\n  " + LONG + ".\n"
        "ENDFUNCTION.\n")
    for label, stmt in [("a verbatim quotation longer than the window", LONG),
                        ("one identifier changed at the same length",
                         LONG.replace("x10", "zz10"))]:
        f = os.path.join(tmp, "long.md")
        io.open(f, "w", encoding="utf-8").write(
            brief_report().replace("SELECT foo FROM bar INTO @DATA(ls_foo).",
                                  stmt + "."))
        r = run(QC, f, lsrc)
        sub = [x for x in r.stdout.splitlines() if x.strip().startswith("SUBSTA")]
        check(len(sub) == 0 if "verbatim" in label else len(sub) == 1,
              "%s is classified by its content" % label,
              "%d row(s)" % len(sub))

    # open() on a directory raises PermissionError, which read_src used to
    # report as not readable as utf-8: a PermissionError wearing an encoding
    # error's clothes, and it sent a reader hunting for a BOM in a folder.
    print()
    print("a directory is not an encoding error")
    print("-" * 72)
    for mode, argv in [("plain", [okp, wd]),
                       ("--fidelity-only", ["--fidelity-only", okp, wd]),
                       ("--fix", ["--fix", okp, wd, "-o",
                                  os.path.join(tmp, "dirsrc.out.md")])]:
        r = run(QC, *argv)
        first = r.stdout.strip().splitlines()[0] if r.stdout.strip() else ""
        check(r.returncode == 2, "%s: a directory as the source exits 2" % mode)
        check("is a directory" in r.stdout,
              "%s: a directory names itself" % mode, first[:70])
        check("not readable as utf-8" not in r.stdout,
              "%s: a directory is not an encoding error" % mode)

    # A file that exists but cannot be read is a different failure from a file
    # that is not utf-8. read_report and read_src both caught (UnicodeDecodeError,
    # OSError) and reported the pair as "not readable as utf-8", which sent a
    # reader to fix the encoding of a file that was fine and unreadable for
    # another reason. io.open is denied in a child, because os.path.exists uses
    # os.stat and still passes -- that is how a denial reaches the read at all.
    print()
    print("an unreadable file is not an encoding error")
    print("-" * 72)
    deny = os.path.join(tmp, "deny.py")
    io.open(deny, "w", encoding="utf-8").write(
        "import io as _io, os, sys\n"
        "sys.path.insert(0, %r)\n"
        "import report_qc as R\n"
        "os.makedirs('present', exist_ok=True)\n"
        "_io.open('present/rep.md', 'w', encoding='utf-8').write('# t\\n')\n"
        "_io.open('present/src.abap', 'w', encoding='utf-8')"
        ".write('REPORT z.\\n')\n"
        "_real = _io.open\n"
        "def deny(path, *a, **k):\n"
        "    if 'present' in str(path):\n"
        "        raise PermissionError(13, 'Permission denied', str(path))\n"
        "    return _real(path, *a, **k)\n"
        "_io.open = deny\n"
        "for fn, p in ((R.read_report, 'present/rep.md'),\n"
        "              (R.read_src, 'present/src.abap')):\n"
        "    try:\n"
        "        fn(p)\n"
        "        print(fn.__name__ + ': NO RAISE')\n"
        "    except R.ReadError as e:\n"
        "        print(fn.__name__ + ': ' + str(e))\n"
        % os.path.join(SKILL, "scripts"))
    rd = subprocess.run([sys.executable, deny], capture_output=True,
                        text=True, encoding="utf-8", cwd=tmp,
                        env=dict(os.environ, PYTHONIOENCODING="utf-8",
                                 PYTHONUTF8="1"))
    lines = [x for x in rd.stdout.splitlines() if ": " in x]
    check(len(lines) == 2, "both readers were exercised",
          "%d line(s)" % len(lines))
    check(all("cannot be read" in x for x in lines),
          "an unreadable report and source are reported as unreadable",
          lines[0][:80] if lines else "none")
    check(all("not readable as utf-8" not in x for x in lines),
          "an unreadable file is not called an encoding error")
    check("Traceback" not in rd.stdout + rd.stderr,
          "the refusal is not a traceback")

    print()
    print("--fix takes one report, and in place is judged by path")
    print("-" * 72)
    # Two reports in one call repaired the first and stopped, so a caller who
    # batched a directory of reports got one repaired file and no word about the
    # rest. Refuse instead, naming both, and leave every file alone.
    ra = os.path.join(tmp, "ra.md")
    rb = os.path.join(tmp, "rb.md")
    io.open(ra, "w", encoding="utf-8").write(brief_report())
    io.open(rb, "w", encoding="utf-8").write(brief_report())
    rb_before = io.open(rb, encoding="utf-8").read()
    r = run(QC, "--fix", ra, rb, src)
    check(r.returncode == 2,
          "--fix: two reports refuse instead of repairing the first",
          "rc=%d" % r.returncode)
    check("Traceback" not in r.stdout + r.stderr,
          "--fix: the refusal is not a traceback")
    check(os.path.basename(ra) in r.stdout and os.path.basename(rb) in r.stdout,
          "--fix: the refusal names both reports")
    check(io.open(rb, encoding="utf-8").read() == rb_before,
          "--fix: the second report is byte-identical")
    # -o may spell the report differently (./rep3.md for rep3.md). Comparing the
    # raw strings read such a call as an external output, so the repair ran in
    # place and left no backup of the only copy.
    io.open(os.path.join(tmp, "rep3.md"), "w", encoding="utf-8").write(
        brief_report().replace("**为什么** — 索引命中。",
                               "**为什么** — 索引命中（见 `zvend.abap:104`）。"))
    if os.path.exists(os.path.join(tmp, "rep3.md.bak")):
        os.remove(os.path.join(tmp, "rep3.md.bak"))
    before3 = io.open(os.path.join(tmp, "rep3.md"), encoding="utf-8").read()
    r = subprocess.run([sys.executable, QC, "--fix", "rep3.md", "src.abap",
                        "-o", "./rep3.md"], capture_output=True, text=True,
                       encoding="utf-8", cwd=tmp,
                       env=dict(os.environ, PYTHONIOENCODING="utf-8",
                                PYTHONUTF8="1"))
    bak3 = os.path.join(tmp, "rep3.md.bak")
    check(os.path.exists(bak3),
          "--fix: an -o that spells the report differently still backs up",
          str([x for x in r.stdout.splitlines() if "repaired" in x][:1]))
    check(io.open(bak3, encoding="utf-8").read() == before3,
          "--fix: that backup is the pre-fix text")

    print()
    print("--fidelity-only prints the note it was made for")
    print("-" * 72)
    # It called classify(), which returns the mismatches and nothing else, so
    # step 6 -- the step whose whole point is fidelity -- read neither N of M
    # nor the question of whether the source is the one the report was written
    # against.
    srcf = os.path.join(tmp, "fsrc.abap")
    io.open(srcf, "w", encoding="utf-8").write(
        "FUNCTION z_probe.\n  DATA ls_foo TYPE i.\n"
        "  SELECT foo FROM bar INTO @DATA(ls_foo).\nENDFUNCTION.\n")
    fab = brief_report().replace(
        "```abap\nSELECT foo FROM bar INTO @DATA(ls_foo).\n```",
        "```abap\nSELECT foo FROM bar INTO @DATA(ls_bar).\n```")
    fp = os.path.join(tmp, "fidnote.md")
    io.open(fp, "w", encoding="utf-8").write(fab)
    r = run(QC, "--fidelity-only", fp, srcf)
    notes = [x.strip() for x in r.stdout.splitlines()
             if x.strip().startswith("note")]
    check(r.returncode == 1, "--fidelity-only: a rewrite still exits 1",
          "rc=%d" % r.returncode)
    check(len(notes) >= 1, "--fidelity-only: the note is printed",
          r.stdout.strip().splitlines()[-1][:60])
    check(any("1 of 1 quoted statement" in x for x in notes),
          "--fidelity-only: the note carries the denominator",
          notes[0][:70] if notes else "no note")
    check(any("may not be the one" in x for x in notes),
          "--fidelity-only: the wrong-file question reaches the writer",
          notes[0][:70] if notes else "no note")

    print()
    print("scripts/recon.py")
    print("-" * 72)
    # Steps 1 and 2 of the Analysis Flow were three calls: check the encoding,
    # dump the source numbered, then fetch the subprogram inventory. docgen
    # prints a four-line receipt and writes the inventory to a file, so the
    # inventory needed its own round, and recon.py folds all three into one.
    #
    # It judges no report, so there is no exit 1 to look for. The assertions that
    # mattered were the ones invisible before: a dump line must be the source
    # line it is labelled with, a refusal must never be preceded by half a dump,
    # and the inventory shown must be docgen's rather than a second copy of its
    # extraction.
    check(os.path.exists(RECON), "scripts/recon.py present")
    check(os.path.exists(DOCGEN),
          "scripts/docgen.py present, recon's only dependency")

    SRC = ("REPORT zz_probe.\n"
           "FUNCTION z_one.\n"
           "  DATA ls_one TYPE i.\n"
           "ENDFUNCTION.\n"
           "FUNCTION z_two.\n"
           "  DATA ls_two TYPE i.\n"
           "ENDFUNCTION.\n")
    src = os.path.join(tmp, "probe.abap")
    io.open(src, "wb").write(SRC.encode("utf-8"))
    out = os.path.join(tmp, "probeout")
    os.makedirs(out)
    r = run(RECON, src, "-o", out)
    check(r.returncode == 0, "recon exits 0 on a readable source",
          r.stdout.strip().splitlines()[-1][:60])
    check(r.returncode in (0, 2),
          "recon never exits 1: it has no defects to report",
          "rc=%d" % r.returncode)

    def dump_of(stdout):
        """{line number: text after the separator}."""
        seen = {}
        for ln in stdout.split("\n"):
            m = re.match(r"^\s*(\d+)\s*\| (.*)$", ln)
            if m:
                seen[int(m.group(1))] = m.group(2)
        return seen

    nums = dump_of(r.stdout)
    check(list(nums) == list(range(1, 8)),
          "the dump is numbered from 1 to the last line", str(sorted(nums)))
    check(all(nums[i + 1] == SRC.split("\n")[i] for i in range(7)),
          "every dump line is the source line it is labelled with")
    check(nums.get(7) == "ENDFUNCTION.",
          "a source ending in a newline keeps its last line; splitlines() would drop it",
          repr(nums.get(7)))

    hdr = [x for x in r.stdout.splitlines()
           if x.startswith("== ") and "line(s)" in x]
    check(bool(hdr) and hdr[0].startswith(
        "== %d line(s), %d bytes, utf-8 ok" % (7, len(SRC.encode("utf-8")))),
          "the header says the line and byte counts",
          (hdr[0] if hdr else "no header"))

    # The reader takes the whole run on that number, so a total that did not match
    # what went out would be a promise about size nobody could check. Bytes, not
    # characters: the source may carry multi-byte comments.
    mt = re.search(r"output (\d+) bytes", hdr[0]) if hdr else None
    # Over the bytes on the wire, not over text. text=True translates the
    # carriage returns docgen put in its own markdown, and a total counted over
    # translated text sat 41 bytes below the one recon claimed for the same run.
    # The CRLF test further down makes the same point about the source dump.
    rawr = subprocess.run([sys.executable, RECON, src, "-o", out],
                          capture_output=True,
                          env=dict(os.environ, PYTHONIOENCODING="utf-8",
                                   PYTHONUTF8="1"))
    sent = len(rawr.stdout)
    check(bool(mt) and int(mt.group(1)) == sent,
          "the header\'s total is the byte count that actually went out",
          "%s bytes claimed, %d sent" % (mt.group(1) if mt else "none", sent))

    # A byte count is a byte count. Read as characters the same file is shorter,
    # so a header that reported the character count would make the source look
    # smaller than it is on disk.
    wide = "REPORT zz_wide.\nSELECT * FROM lfa1.\n\" 供应商名称\n"
    mb = os.path.join(tmp, "wide.abap")
    io.open(mb, "wb").write(wide.encode("utf-8"))
    raw = io.open(mb, "rb").read()
    rm = run(RECON, mb, "-o", out)
    hm = [x for x in rm.stdout.splitlines()
          if x.startswith("== ") and "line(s)" in x]
    check(len(raw) > len(wide),
          "that fixture is actually wider than its character count",
          "%d bytes vs %d chars" % (len(raw), len(wide)))
    check(bool(hm) and ", %d bytes, utf-8 ok," % len(raw) in hm[0],
          "the header counts bytes, not characters",
          (hm[0] if hm else "no header"))
    check(bool(hm) and (", %d bytes" % len(wide)) not in hm[0],
          "and the character count does not appear in it",
          "%d chars vs %d bytes" % (len(wide), len(raw)))

    # Windows source is CRLF. report_qc reads it with newline="", recon reads
    # bytes, so both see the carriage return. A dump that quietly dropped it
    # would let a quote copied from it fail the fidelity check.
    crsrc = SRC.replace("\n", "\r\n")
    cr = os.path.join(tmp, "crlf.abap")
    io.open(cr, "wb").write(crsrc.encode("utf-8"))
    # Read bytes, not text: text=True translates \r\n into \n and would strip the
    # carriage return this check exists to catch, making it pass for the wrong
    # reason.
    rcr = subprocess.run([sys.executable, RECON, cr, "-o", out],
                         capture_output=True,
                         env=dict(os.environ, PYTHONIOENCODING="utf-8",
                                  PYTHONUTF8="1"))
    nums2 = dump_of(rcr.stdout.decode("utf-8"))
    check(list(nums2) == list(range(1, 8)),
          "a CRLF source keeps the same numbering", str(sorted(nums2)))
    check(all(nums2[i + 1] == crsrc.split("\n")[i] for i in range(7)),
          "recon neither adds nor drops the carriage return")

    df = os.path.join(out, "probe.onboarding.md")
    inv = [x for x in r.stdout.splitlines()
           if x.startswith("== DOCGEN OUTPUT")]
    check(bool(inv), "the docgen block is present",
          (inv[0][:70] if inv else "absent"))
    check("SUBPROGRAM INVENTORY" not in r.stdout,
          "the block is not labelled an inventory when docgen wrote a guide",
          inv[0][:70] if inv else "absent")
    # Over the raw bytes. The block carries docgen's own line endings, which a
    # text-mode read translates away and so would make a transformed block look
    # identical to the file it claims to mirror.
    shown = rawr.stdout.decode("utf-8").split(inv[0], 1)[1]
    shown = shown.split("== docgen wrote", 1)[0].strip()
    check(shown.encode("utf-8") == io.open(df, "rb").read().strip(),
          "the inventory recon shows is byte-identical to what docgen wrote",
          "%d bytes" % os.path.getsize(df))
    rcpt = [x for x in r.stdout.splitlines() if x.startswith("== docgen wrote")]
    check(bool(rcpt) and os.path.basename(df) in rcpt[0]
          and "%d bytes" % os.path.getsize(df) in rcpt[0],
          "the receipt names the file and its size",
          (rcpt[0] if rcpt else "no receipt"))

    # Unlike report_qc.py, recon locates docgen by its own path, so it does not
    # need the skill root as the current directory.
    r3 = subprocess.run([sys.executable, RECON, src], capture_output=True,
                        text=True, encoding="utf-8", cwd=tmp,
                        env=dict(os.environ, PYTHONIOENCODING="utf-8",
                                 PYTHONUTF8="1"))
    check(r3.returncode == 0 and "== DOCGEN OUTPUT" in r3.stdout,
          "recon runs with the current directory somewhere else",
          "rc=%d" % r3.returncode)

    print()
    print("a refusal is never preceded by half a dump")
    print("-" * 72)
    # Ten numbered lines followed by an error lets a reader take the run for a
    # verdict, which is the failure shape this project has had before. Every
    # check below therefore runs before anything is printed.
    md = os.path.join(tmp, "note.md")
    io.open(md, "w", encoding="utf-8").write("# not a source\n")
    bad = os.path.join(tmp, "latin1.abap")
    io.open(bad, "wb").write(b"REPORT z_bad.\nDATA lv \xe4 TYPE c.\n")
    empty = os.path.join(tmp, "blank.abap")
    io.open(empty, "wb").write(b"   \n\t\n")
    d = os.path.join(tmp, "notasource")
    os.makedirs(d)
    all_clean = True
    for label, path, own in [("a missing file", os.path.join(tmp, "absent.abap"),
                              "does not exist"),
                             ("a directory", d, "is a directory"),
                             ("a markdown file", md, "markdown"),
                             ("a non-utf-8 file", bad, "not utf-8"),
                             ("an empty file", empty,
                               "no analysable content")]:
        rr = run(RECON, path, "-o", out)
        first = rr.stdout.strip().splitlines()[0] if rr.stdout.strip() else ""
        all_clean = all_clean and "Traceback" not in rr.stdout + rr.stderr
        check(rr.returncode == 2, "recon refuses %s, exit 2" % label,
              "rc=%d" % rr.returncode)
        check(first.startswith("error  "),
              "recon says what it refused about %s" % label, first[:70])
        check(own in rr.stdout,
              "recon names the right reason for %s" % label, first[:70])
        check(not any(re.match(r"^\s*\d+\s*\|", x) for x in rr.stdout.splitlines()),
              "recon prints no source before refusing %s" % label)
    check(all_clean, "no refusal path raises a traceback")

    print()
    print("recon reports docgen's outcome, and only that")
    print("-" * 72)
    # recon looks for docgen beside itself, so a stub in its place reaches a
    # branch no real docgen could.
    stub = os.path.join(tmp, "stub")
    os.makedirs(os.path.join(stub, "scripts"))
    shutil.copy(RECON, os.path.join(stub, "scripts", "recon.py"))
    # (name, stub body, the reason recon must quote, what docgen's own words are
    # expected to be echoed back, and whether a traceback may appear at all.)
    cases = [
        ("wrote no file",
         "import sys\nprint(\"Generated: nowhere\")\nsys.exit(0)\n",
         "docgen reported success but wrote no file", None, False),
        ("refused",
         "import sys\nprint(\"error  docgen refused\")\nsys.exit(2)\n",
         "docgen exited 2", "error  docgen refused", False),
        ("crashed",
         "raise RuntimeError(\"boom inside docgen\")\n",
         "docgen exited 1", "boom inside docgen", True),
        ("wrote a non-utf-8 file",
         "import pathlib, sys\n"
         "out = pathlib.Path(sys.argv[-2],\n"
         "                  pathlib.Path(sys.argv[-1]).stem + '.onboarding.md')\n"
         "out.write_bytes(b'\\xff\\xfe\\x00')\n"
         "print('Generated: ' + str(out))\n",
         # exit 0, so recon does not echo docgen's receipt: the refusal
         # already names the file and the reason, and the receipt would
         # add nothing.
         "not readable as utf-8", None, False)]
    for name, body, want_msg, echoed, crashes in cases:
        io.open(os.path.join(stub, "scripts", "docgen.py"), "w",
                encoding="utf-8").write(body)
        # A fresh output dir. The guard only proves that a file exists at that
        # path, so one left there by an earlier run made this stub pass at rc=0:
        # recon showed an inventory it had not produced. That is the guard's own
        # limit, and it is recorded in the changelog rather than hidden.
        fresh = os.path.join(tmp, "stubout-%s" % name)
        os.makedirs(fresh)
        rr = run(os.path.join(stub, "scripts", "recon.py"), src, "-o", fresh)
        check(rr.returncode == 2,
              "a docgen that %s leaves recon refusing" % name,
              "rc=%d" % rr.returncode)
        check(rr.stdout.startswith("error  "),
              "a docgen that %s still leads with error" % name,
              rr.stdout.splitlines()[0][:60])
        check(want_msg in rr.stdout,
              "recon says which docgen outcome it saw for %s" % name,
              rr.stdout.strip().splitlines()[-1][:70])
        # Docgen runs after the source checks but, from 1.1.22, before the dump is
        # written. Before that the whole source had already gone out when docgen
        # refused, so a reader had spent a full context on a run that was a
        # refusal. The loop checked the reason, not the silence.
        check(not any(re.match(r"^\s*\d+\s*\|", x) for x in rr.stdout.splitlines()),
              "a docgen that %s prints no source at all" % name)
        # A crash is the one case where a traceback may appear: it is echoed as
        # the only account of what happened, and it comes after the error line.
        check(("Traceback" in rr.stdout) == crashes,
              "a docgen that %s shows the crash and only the crash" % name)
        if echoed is not None:
            check(echoed in rr.stdout,
                  "a docgen that %s has its own words echoed back" % name,
                  rr.stdout.splitlines()[0][:70])

    # A docgen that is not installed is not a docgen that refused. python exits 2
    # for a script it cannot open, so without a check of its own the message would
    # have said "docgen exited 2" and sent a reader after a diagnosis that does
    # not exist. The stderr that says why is dropped, because it is python's, not
    # docgen's.
    os.remove(os.path.join(stub, "scripts", "docgen.py"))
    miss = os.path.join(tmp, "stubout-missing")
    os.makedirs(miss)
    rr = run(os.path.join(stub, "scripts", "recon.py"), src, "-o", miss)
    check(rr.returncode == 2 and "is not installed" in rr.stdout,
          "recon names a docgen that is not installed",
          rr.stdout.splitlines()[0][:70] if rr.stdout.strip() else "no output")
    check("docgen exited" not in rr.stdout,
          "recon quotes no exit code for a docgen that never ran")
    check(rr.stdout.startswith("error  "),
          "a missing docgen still leads with error")
    check(not any(re.match(r"^\s*\d+\s*\|", x) for x in rr.stdout.splitlines()),
          "recon prints no source before refusing a missing docgen")

    print()
    print("the third script of the pipe, and the third state of a rule set")
    print("-" * 72)
    # recon reads docgen with text=True, encoding="utf-8" and no errors=. A
    # child that emitted bytes that are not utf-8 made that decode return None
    # for child.stdout, and child.stdout + child.stderr raised TypeError: exit 1
    # with an empty stdout, so a refusal arrived in the form of a crash. docgen
    # now reconfigures its streams like the other two scripts, and recon decodes
    # the child with errors="replace" so child.stdout can never be None. This
    # stub makes the second half of that fail -- the pipe, not the console.
    io.open(os.path.join(stub, "scripts", "docgen.py"), "w",
            encoding="utf-8").write(
        "import sys\n"
        "sys.stdout.buffer.write(%r)\n"
        "sys.exit(2)\n" % b"error  cannot write to o\\xff\\xfe\\x00ut.md")
    os.makedirs(os.path.join(tmp, "stubout-bin"))
    rcp = run(os.path.join(stub, "scripts", "recon.py"), src, "-o",
              os.path.join(tmp, "stubout-bin"))
    check(rcp.returncode == 2,
          "a child whose output is not utf-8 still leaves recon refusing")
    check(rcp.stdout.startswith("error  "),
          "a child whose output is not utf-8 still leads with error")
    check("docgen exited" in rcp.stdout,
          "a child whose output is not utf-8 is still reported as a child")
    check("Traceback" not in rcp.stdout,
          "decoding the child never raises",
          rcp.stdout.strip().split("\n")[0][:44])
    check("NoneType" not in rcp.stdout + rcp.stderr,
          "child.stdout is not None: the TypeError is gone")
    io.open(os.path.join(stub, "scripts", "docgen.py"), "w",
            encoding="utf-8").write(
        "import pathlib, sys\n"
        "out = pathlib.Path(sys.argv[-2],\n"
        "                  pathlib.Path(sys.argv[-1]).stem + '.onboarding.md')\n"
        "out.write_bytes(b'\\xff\\xfe\\x00')\n"
        "print('Generated: ' + str(out))\n")
    fresh = os.path.join(tmp, "stubout-bin2")
    os.makedirs(fresh)
    rr = run(os.path.join(stub, "scripts", "recon.py"), src, "-o", fresh)
    check(rr.returncode == 2 and rr.stdout.startswith("error  "),
          "a docgen that crashed before the binary write is reported as one")
    check("Traceback" not in rr.stdout,
          "and it is still not a traceback of recon's own")
    for tag, path in (("report_qc.py", QC), ("docgen.py", DOCGEN),
                      ("recon.py", RECON), ("evaluate.py", EVAL),
                      ("abap_deps_analyzer.py", DEPS)):
        body = io.open(path, encoding="utf-8").read()
        check("_stream.reconfigure(encoding=\"utf-8\"" in body,
              "%s reconfigures its own streams" % tag)
    check('errors="replace"' in io.open(RECON, encoding="utf-8").read(),
          "recon decodes the child so child.stdout can never be None")
    check('_stream.reconfigure(encoding="utf-8"' in io.open(DOCGEN,
                                                            encoding="utf-8").read(),
          "docgen reconfigures its streams before it prints")

    # _read_source is a third function with the same two-clause shape as
    # report_qc's read_report and read_src.
    print()
    print("docgen's own readers")
    print("-" * 72)
    deny2 = os.path.join(tmp, "deny_docgen.py")
    io.open(deny2, "w", encoding="utf-8").write(
        "import io as _io, os, pathlib, sys\n"
        "sys.path.insert(0, %r)\n"
        "import docgen as D\n"
        "os.makedirs('present', exist_ok=True)\n"
        "_io.open('present/src.abap', 'w', encoding='utf-8')"
        ".write('REPORT z.\\n')\n"
        "_real = _io.open\n"
        "def deny(path, *a, **k):\n"
        "    if 'present' in str(path):\n"
        "        raise PermissionError(13, 'Permission denied', str(path))\n"
        "    return _real(path, *a, **k)\n"
        "_io.open = deny\n"
        "try:\n"
        "    D._read_source(pathlib.Path('present/src.abap'))\n"
        "    print('NO RAISE')\n"
        "except SystemExit as e:\n"
        "    print('exit' + str(e.code))\n"
        % os.path.join(SKILL, "scripts"))
    rd2 = subprocess.run([sys.executable, deny2], capture_output=True,
                         text=True, encoding="utf-8", cwd=tmp,
                         env=dict(os.environ, PYTHONIOENCODING="utf-8",
                                  PYTHONUTF8="1"))
    lines2 = [x for x in rd2.stdout.splitlines() if ": " in x]
    check(len(lines2) == 1, "docgen's reader was exercised",
          "%d line(s)" % len(lines2))
    check(lines2 and "exit2" in rd2.stdout,
          "an unreadable source is a refusal, not a crash",
          rd2.stdout.strip().split("\n")[-1][:70])
    check("Traceback" not in rd2.stdout + rd2.stderr,
          "docgen's unreadable source says so, it does not raise")
    check("cannot be read" in rd2.stdout,
          "docgen names the denial", rd2.stdout.strip().split("\n")[0][:60])
    check("not utf-8" not in rd2.stdout,
          "docgen does not call a denial an encoding error")

    # .strip() removes whitespace but not control bytes, so a file with no
    # printable character at all passed as a one-line program and got a document
    # about a program that does not exist.
    for name, blob in (("only null bytes", b"\x00\x00\x00"),
                       ("only escape codes", b"\x1b\x1b\x1b")):
        ctl = os.path.join(tmp, "ctl.abap")
        io.open(ctl, "wb").write(blob)
        for tool, argv in (("recon", (RECON, ctl, "-o", out)),
                           ("docgen", (DOCGEN, "--type", "onboarding",
                                       "-o", out, ctl))):
            r = run(*argv)
            check(r.returncode == 2,
                  "%s refuses %s, exit 2" % (tool, name),
                  "rc=%d" % r.returncode)
            check(r.stdout.startswith("error  "),
                  "%s says what it refused for %s" % (tool, name),
                  r.stdout.strip().split("\n")[0][:60])

    # -o is recon's flag, not docgen's, so recon owes the diagnosis.
    for name, path in (("a missing -o", os.path.join(tmp, "never-created")),
                       ("a -o that is a file", os.path.join(tmp, "afile"))):
        if os.path.isfile(path) or name.startswith("a -o"):
            io.open(path, "w").write("x")
        r = run(RECON, src, "-o", path)
        check(r.returncode == 2, "recon refuses %s, exit 2" % name)
        first = r.stdout.strip().split("\n")[0]
        check(first.startswith("error  "),
              "recon says what it refused for %s" % name, first[:70])
        check("output path" in r.stdout and "docgen exited" not in r.stdout,
              "recon blames its own flag for %s, not docgen" % name,
              first[:70])

    # json.load accepts {"version": "1.3.10"}, and the trigger names only
    # "missing or not parseable". The derivation below the load was the third
    # state, and it died there with a KeyError -- exit 1, the code a real
    # defect verdict gets, for a rule set that was merely reshaped.
    print()
    print("a rule set that parses is not a rule set that is right")
    print("-" * 72)
    for idx, (name, body) in enumerate((
            ("an object with no sections", '{"version": "1.3.10"}'),
            ("a list at the root", '[1, 2]'),
            ("an object with an empty sections list", '{"sections": []}'))):
        root = os.path.join(tmp, "shape-%d" % idx)
        os.makedirs(os.path.join(root, "scripts"))
        os.makedirs(os.path.join(root, "schemas"))
        io.open(os.path.join(root, "schemas", "report-contract.json"),
                "w", encoding="utf-8").write(body)
        shutil.copy(QC, os.path.join(root, "scripts", "report_qc.py"))
        shutil.copytree(CHECKS, os.path.join(root, "scripts", "checks"),
                        ignore=shutil.ignore_patterns("__pycache__"))
        rep = os.path.join(tmp, "shape.md")
        io.open(rep, "w", encoding="utf-8").write(brief_report())
        r = run(os.path.join(root, "scripts", "report_qc.py"), rep)
        check(r.returncode == 2,
              "%s exits 2, not 1" % name, "rc=%d" % r.returncode)
        check("Traceback" not in r.stdout + r.stderr,
              "%s is a refusal" % name)
        check("cannot read the rule set" in r.stdout,
              "%s is refused by the rule-set guard" % name)
        # The loop above covers a rule set that is missing keys. A key that is
        # present and of the wrong type reached the derivation instead: buckets as
        # a number raised TypeError from "".join(), advisories as [] raised
        # StopIteration from next(), and a pattern that does not compile raised
        # re.error. None of the three was in the catch, so each exited 1 with a
        # traceback -- the defect verdict, for a rule set that was only mistyped.
    _base = json.load(io.open(os.path.join(SCHEMAS, "report-contract.json"),
                              encoding="utf-8"))
    for idx, (name, path, value) in enumerate((
            ("buckets is a number", ("problem_section", "buckets"), 5),
            ("patterns is a string",
             ("forbidden_in_location_labels", "patterns"), "x"),
            ("advisories is an empty list", ("advisories",), []),
            ("forbid_in_display_text is 0",
             ("mermaid", "forbid_in_display_text"), 0),
            ("a pattern that does not compile",
             ("forbidden_in_location_labels", "patterns"),
             [{"id": "x", "regex": "["}]))):
        c = json.loads(json.dumps(_base))
        node = c
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value
        root = os.path.join(tmp, "typed-%d" % idx)
        os.makedirs(os.path.join(root, "scripts"))
        os.makedirs(os.path.join(root, "schemas"))
        io.open(os.path.join(root, "schemas", "report-contract.json"),
                "w", encoding="utf-8").write(json.dumps(c))
        shutil.copytree(CHECKS, os.path.join(root, "scripts", "checks"),
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy(QC, os.path.join(root, "scripts", "report_qc.py"))
        r = run(os.path.join(root, "scripts", "report_qc.py"), rep)
        check(r.returncode == 2,
              "%s exits 2, not 1" % name, "rc=%d" % r.returncode)
        check("Traceback" not in r.stdout + r.stderr,
              "%s is a refusal, not a crash" % name)
        check("cannot read the rule set" in r.stdout,
              "%s is refused by the rule-set guard" % name,
              r.stdout.strip()[:60])

    # recon.py reads the predicate from checks/source.py, with a fallback for the
    # layout the stub tests above run it in -- recon.py beside nothing but
    # docgen.py. Two definitions can drift, so compare them on the same inputs.
    print()
    print("recon's fallback predicate agrees with the one it imports")
    print("-" * 72)
    import importlib.util
    fb = os.path.join(tmp, "fallback")
    os.makedirs(fb)
    shutil.copy(RECON, os.path.join(fb, "recon.py"))
    _spec = importlib.util.spec_from_file_location(
        "recon_fallback", os.path.join(fb, "recon.py"))
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    sys.path.insert(0, os.path.join(SKILL, "scripts"))
    from checks.source import has_content as _shared
    for _t in ("", "   \n\t", "\x00" * 500, "\ufffd" * 9000,
               "\ufffd" * 90 + "\n", "\ufffd" * 90 + "REPORT z.",
               "REPORT z.\n", None):
        check(_mod.has_content(_t) is _shared(_t),
              "recon's fallback agrees on %r" % (_t[:12] if _t else _t,),
              "%s vs %s" % (_mod.has_content(_t), _shared(_t)))
    
    print()
    print("evaluate.py: a reshaped reference is a refusal")
    print("-" * 72)
    io.open(os.path.join(tmp, "e_array.json"), "w").write("[]\n")
    io.open(os.path.join(tmp, "e_scalar.json"), "w").write('{"defects": [7]}\n')
    io.open(os.path.join(tmp, "e_good.json"), "w", encoding="utf-8").write(
        '{"defects": [{"id": "D1", "question": "Is it absent?", '
        '"anchors": ["REPORT"]}]}')
    io.open(os.path.join(tmp, "e_vlist.json"), "w").write(
        '{"report": null, "verdicts": {"D1": ["found"]}, '
        '"false_claims": []}')
    io.open(os.path.join(tmp, "e_vstr.json"), "w").write(
        '{"report": null, "verdicts": {"D1": "maybe"}, '
        '"false_claims": []}')
    for name, argv in (
            ("array at the root", ["tasks", "--defects",
                                   os.path.join(tmp, "e_array.json")]),
            ("a defect entry that is a scalar", ["tasks", "--defects",
                                                 os.path.join(tmp, "e_scalar.json")]),
            ("a verdict that is a list", ["score", "--defects",
                                          os.path.join(tmp, "e_good.json"),
                                          "--verdicts",
                                          os.path.join(tmp, "e_vlist.json"),
                                          "--legacy"]),
            ("a verdict outside the vocabulary", ["score", "--defects",
                                                 os.path.join(tmp, "e_good.json"),
                                                 "--verdicts",
                                                 os.path.join(tmp, "e_vstr.json"),
                                                 "--legacy"])):
        r = run(EVAL, *argv)
        check(r.returncode == 2, "%s exits 2, not 1" % name,
              "rc=%d" % r.returncode)
        check("REJECTED" in r.stdout, "%s is reported as a rejection" % name)
        check("Traceback" not in r.stdout + r.stderr,
              "%s is not a crash" % name)
    check("must be a json object" in
          run(EVAL, "tasks", "--defects",
              os.path.join(tmp, "e_array.json")).stdout,
          "evaluate names a root that is not an object")
    check("are not objects" in
          run(EVAL, "tasks", "--defects",
              os.path.join(tmp, "e_scalar.json")).stdout,
          "evaluate names an entry that is not an object")
    check("verdict is not a string" in
          run(EVAL, "score", "--defects", os.path.join(tmp, "e_good.json"),
              "--verdicts", os.path.join(tmp, "e_vlist.json"),
              "--legacy").stdout,
          "evaluate names a verdict that is not a string")

    print()
    print("-" * 72)
    print()
    print("-" * 72)
    if FAILS:
        print(f"{len(FAILS)} check(s) failed, {N_OK} passed:")
        for f in FAILS:
            print("  -", f)
        return 1
    print(f"{N_OK} checks passed, 0 failed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
