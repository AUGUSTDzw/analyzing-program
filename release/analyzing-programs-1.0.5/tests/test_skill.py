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
    check("do not occur in the source" not in r.stdout,
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
    check(fo.stdout.startswith("FAIL") and fo.returncode == 1,
          "--fidelity-only exits nonzero when a quotation is not in the source")
    fx = run(QC, "--fix", nolayer, src, "-o", os.path.join(tmp, "fixed.md"))
    check(fx.returncode == 1,
          "--fix exits nonzero while defects still need the model",
          "A8 is not mechanically repairable")
    fx = run(QC, "--fix", good, src, "-o", os.path.join(tmp, "fixed2.md"))
    check(fx.returncode == 0, "--fix exits 0 once nothing is left")
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
    check("is empty" in r.stdout and "not run" in r.stdout,
          "an empty source says what it could not measure",
          r.stdout.strip().split("\n")[-1][:44])
    r = run(QC, "--fidelity-only", good, emp)
    check(r.returncode == 2 and "empty" in r.stdout and "Traceback" not in r.stderr,
          "--fidelity-only refuses an empty source, not a missing one",
          r.stdout.strip().split("\n")[-1][:44] if r.stdout.strip() else "")
    binf = os.path.join(tmp, "bad.abap")
    io.open(binf, "wb").write(b"FUNCTION z_foo.\nSELECT \xff\xfe FROM bar.\n")
    r = run(QC, good, binf)
    check(r.returncode == 2 and "utf-8" in r.stdout and "Traceback" not in r.stderr,
          "an undecodable source is refused, not scored against",
          r.stdout.strip().split("\n")[-1][:44] if r.stdout.strip() else "")

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
    row = [x for x in r.stdout.splitlines() if "do not occur in the source" in x]
    m = re.search(r"First at line (\d+)", row[0]) if row else None
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
