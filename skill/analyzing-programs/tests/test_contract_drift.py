#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fail when the contract and SKILL.md stop describing the same rules.

    python tests/test_contract_drift.py

Why this exists. Seven separate fixes in this project were a checker disagreeing
with the rule it was supposed to enforce:

  - LINE_NUM matched only `.abap:12` and `第 12-34 行`, so a report written as
    `L23` throughout scored clean
  - widening it then flagged LINE1 and LINE2, which are identifiers
  - the checking half and the fixing half of the Mermaid rule carried different
    patterns, so one reported what the other silently skipped
  - the Mermaid fixer had a "label already starts with a quote, so exempt"
    guard that the skill never granted
  - the remediation-snippet exemption was missing, so 92 faithful AVE statements
    were counted as A8 violations
  - the triage script truncated its probe at 60 characters, capping the match
    score so faithful lines fell through to "genuine"
  - the exemplar gate test read the wrong report's row

Every one of them was a second copy of a rule disagreeing with the first. The
rules now live once, in schemas/report-contract.json, and the checker reads them.
What this test adds is the other half: the contract also carries a `skill_anchor`
per rule, so the prose cannot drift away from what is enforced either.

A rule with no anchor in SKILL.md is enforced but not taught. An anchor with no
rule is taught but not enforced. Both are failures, and neither is visible by
running the checker.

stdout is reconfigured because the labels printed below are the contract's own
anchors, and the bucket anchor is the emoji U+1F534. Printing it to a Windows
console defaulting to cp936 raised UnicodeEncodeError and killed the run at the
fifth check, so this test had never been seen to finish there.
"""
import io
import json
import os
import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
CONTRACT = os.path.join(SKILL, "schemas", "report-contract.json")
SKILL_MD = os.path.join(SKILL, "SKILL.md")

fails = []
n_ok = 0


def check(cond, label, detail=""):
    global n_ok
    if cond:
        n_ok += 1
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f"   {detail}" if detail else ""))
    if not cond:
        fails.append(label)


def anchors(node, out):
    """Every skill_anchor in the contract, wherever it sits."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "skill_anchor" and isinstance(v, str):
                out.append((v, node.get("heading_anchor")
                            or node.get("id") or node.get("label") or k))
            else:
                anchors(v, out)
    elif isinstance(node, list):
        for v in node:
            anchors(v, out)
    return out


def main():
    if not os.path.exists(SKILL_MD):
        print("SKILL.md not found at", SKILL_MD)
        return 2
    skill = io.open(SKILL_MD, encoding="utf-8").read()
    contract = json.load(io.open(CONTRACT, encoding="utf-8"))

    print("contract parses")
    print("-" * 74)
    check("sections" in contract and len(contract["sections"]) == 6,
          "six sections declared")
    check(len(contract["layers"]["labels"]) == 3, "three layer labels declared")
    check(len(contract["problem_section"]["buckets"]) == 4, "four buckets declared")

    print()
    print("each section names the heading SKILL.md actually uses")
    print("-" * 74)
    for s in contract.get("sections", []):
        h = s.get("heading_anchor")
        check(bool(h), f"section {s.get('id')}: heading_anchor is set",
              f"label={s.get('label')!r}")
        check(h in skill, f"section {s.get('id')}: {h!r} appears in SKILL.md",
              f"label={s.get('label')!r}")

    found = anchors(contract, [])
    print()
    print(f"every enforced rule is taught  ({len(found)} anchors)")
    print("-" * 74)
    if not found:
        print("  FAIL  no skill_anchor found in the contract at all")
        fails.append("no anchors")
    for anchor, owner in found:
        check(anchor in skill, f"{owner}: {anchor!r} appears in SKILL.md")

    print()
    print("the prose does not teach rules nothing enforces")
    print("-" * 74)
    # Constraints the skill states that the checker must cover. Each must be
    # traceable to something in the contract, otherwise a reader is told to obey
    # a rule no run will ever check.
    taught = {
        "不用行号": "forbidden_in_location_labels",
        "Mermaid 标签安全": "mermaid",
        "逐字符忠实": "advisories[fidelity]",
        "每个代码块后三层都必须出现": "layers",
        "🔴 P0 业务正确性": "problem_section",
        "闸门只管形状": "claim_separation",
    }
    for anchor, where in taught.items():
        in_skill = anchor in skill
        in_contract = where.split("[")[0] in json.dumps(contract, ensure_ascii=False)
        check(in_skill and in_contract,
              f"{anchor!r} is both taught and enforced",
              f"skill={in_skill} contract[{where}]={in_contract}")

    print()
    print("the loop position rule is in both places")
    print("-" * 74)
    lp = contract.get("loop_position", {})
    for k in ("inside_generation_cost_weighted_recall",
              "outside_generation_cost_weighted_recall",
              "checks_make_no_difference_p", "repair_pass_may_change"):
        check(k in lp, f"loop_position.{k} is recorded")
    check(bool(lp.get("repair_pass_must_not_change")),
          "loop_position states what a repair pass must not change")
    check("这一轮不许改分析" in skill,
          "the prohibition is stated in SKILL.md, not only in the contract")
    check("分析在这一步已经是终稿" in skill,
          "SKILL.md says the analysis is final before the repair pass")

    print()
    print("claim separation is stated, not implied")
    print("-" * 74)
    cs = contract.get("claim_separation", {})
    for k in ("deterministic_checks_establish", "requires_a_named_reviewer_for",
              "reviewer_mechanism"):
        check(bool(cs.get(k)), f"claim_separation.{k} is populated")
    comment = cs.get("_comment") or []
    if isinstance(comment, str):
        comment = [comment]
    check("never implies" in " ".join(comment),
          "the contract says one pass never implies the others",
          "borrowed from archify's delivery contract")

    print()
    print("every contract rule is wired into the gate")
    print("-" * 74)
    # The two checks above cover contract -> SKILL.md. This covers the other
    # half: contract -> gate. Without it a rule can be declared in the
    # contract, taught in SKILL.md, and never implemented -- all green.
    import importlib.util
    gate = os.path.join(SKILL, "scripts", "report_qc.py")
    spec = importlib.util.spec_from_file_location("rq", gate)
    rq = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rq)
    import re as _re
    # The gate is report_qc.py plus the checks package it imports. The
    # derivations moved into checks/contract.py in 1.1.0, so counting the single
    # file reads a constant that is declared in one place and read in another as
    # "declared but never read" -- which is the opposite of the defect below, and
    # is what put five of these eleven at zero. One copy of the source of the
    # whole gate, and the count for every one of the eleven is at least what it
    # was when they all lived in report_qc.py.
    _pkg = os.path.join(SKILL, "scripts", "checks")
    gsrc = "".join(
        io.open(p, encoding="utf-8").read()
        for p in [gate] + sorted(os.path.join(_pkg, f) for f in
                                 os.listdir(_pkg) if f.endswith(".py")))
    for key, attr in (("sections", "SEC"), ("layers", "LAYERS"),
                      ("sections", "SEC_RE"), ("layers", "A8_GAP"),
                      ("problem_section", "PSEC"),
                      ("problem_section", "BUCKETS"),
                      ("forbidden_in_location_labels", "LINE_NUM"),
                      ("mermaid", "FULLWIDTH"),
                      ("mermaid", "DIAGRAM_LANG"),
                      ("layers", "QUOTE_LANG"), ("layers", "FIX_LANG")):
        # Populated is not enough: a constant can be declared from the contract
        # and never read, and every assertion below would still pass. Counting
        # the identifier is what catches that -- PSEC was declared here and used
        # nowhere, and check() looked up "## 五" by hand instead.
        n = len(_re.findall(r"\b%s\b" % attr, gsrc))
        check(bool(getattr(rq, attr, None)),
              f"report_qc.{attr} is populated from contract.{key}")
        check(n >= 2, f"report_qc.{attr} is read by the gate, not just declared",
              f"{attr} appears {n} time(s) in the gate package")
    for fn in ("density_note", "fidelity_note", "fix_lang_note", "fix_mislabel_note",
               "prose_end"):
        check(hasattr(rq, fn), f"report_qc.{fn} exists for its advisory")
    # The four advisories sit outside check(), so no mutated exemplar above
    # can see them. Existence was the whole of their coverage: a declared
    # advisory that nothing calls would still pass every assertion here.
    for fn in ("density_note", "fidelity_note", "fix_lang_note", "fix_mislabel_note"):
        n = len(_re.findall(r"\b%s\b" % fn, gsrc))
        check(n >= 2, f"{fn} is called, not just defined",
              f"{fn} appears {n} time(s) in the gate package")

    print()
    print("the gate reads every citation form the contract admits")
    print("-" * 74)
    # A pattern LINE_NUM accepts must be one CITE_NUM can pull a number
    # out of, or check() reports a citation fix_ln() reads as something
    # else. Widening the contract to {2,} did exactly that: check() accepted
    # `L100000` while fix_ln() truncated it to 10000 and reported it as
    # pointing past the end of a file it had never counted.
    _PROBE = {"file-colon-line": "zvend.abap:104", "cn-line": "第 90-96 行",
              "en-lines": "lines 90", "short-L": "L104",
              "colon-number": "obj:104"}
    for p in contract["forbidden_in_location_labels"]["patterns"]:
        probe = _PROBE.get(p["id"], "zvend.abap:104")
        check(bool(rq.LINE_NUM.search(probe)),
              f"LINE_NUM accepts {probe!r} ({p['id']})")
        check(bool(rq.CITE_NUM.search(probe)),
              f"CITE_NUM extracts a number from {probe!r}")
    _lims = [int(x) for p in contract["forbidden_in_location_labels"]["patterns"]
             for x in _re.findall(r"\\d\{(\d+),\}", p["regex"])]
    _widest = min(_lims) if _lims else 1
    _m = _re.search(r"\\d\{(\d+),\}", rq.CITE_NUM.pattern)
    check(bool(_m) and int(_m.group(1)) >= _widest,
          "CITE_NUM's digit run is no narrower than the contract's widest",
          f"CITE_NUM={_m.group(0) if _m else '-'} contract widest={_widest}")
    check(rq.CITE_NUM.search("L100000").group(1) == "100000",
          "CITE_NUM does not truncate a long line number")
    check(bool(rq.LINE_NUM.search("L100000")),
          "a six-digit L citation is flagged, not invisible")
    check(not rq.LINE_NUM.search("01:30:00"),
          "a time literal is not a line citation")

    print()
    print("each gate rule actually fires (mutated exemplar)")
    print("-" * 74)
    ex = os.path.join(SKILL, "references", "example-report.md")
    if not os.path.exists(ex):
        check(False, "references/example-report.md present for the probe")
    else:
        base = io.open(ex, encoding="utf-8").read()
        tmp = ex + ".drift.md"
        # A8 needs a real window, not a string search: take the first quoted
        # block and either delete everything it owes the reader or keep the prose
        # and drop two of the three labels. Deleting to the next boundary has to
        # land on its own line -- a heading glued right after the closing fence
        # is literal text rather than a heading, so prose_end treats it as prose
        # and this mutation would report A8-pt instead.
        st, en, gap = next(rq.source_blocks(base))
        nxt = rq.prose_end(base, en)
        _labels = list(rq.LAYERS)
        _gap_pt = "\n".join(l for l in gap.split("\n")
                            if not l.strip().startswith("**" + _labels[1])
                            and not l.strip().startswith("**" + _labels[2]))
        mutations = [
            ("sec", base.replace("## 五", "## 伍")),
            ("prow", _re.sub(r"(?ms)^## 五.*?(?=^## 六)", "## 五\n\n(empty)\n\n", base)),
            ("buck", base.replace("\U0001F534", "ZZ")),
            ("A8-cc", base[:en] + "\n" + base[nxt:]),
            ("A8-pt", base[:en] + _gap_pt + base[en + len(gap):]),
            ("ln", base + "\n\nx `zvend.abap:104` y\n"),
            ("mm", base.replace("```mermaid", "```mermaid\nA[<bad>]", 1)),
        ]
        for label, text in mutations:
            io.open(tmp, "w", encoding="utf-8", newline="").write(text)
            try:
                kinds = [b[0] for b in rq.check(text)]
            finally:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            check(label in kinds, f"defect {label!r} is detected",
                  f"gate returned {kinds}")

        # The probe only proves something if a gate that stops checking gives a
        # The probe only proves something if a gate that stops checking gives a
        # different result. Both directions: every mutation fires above, and a
        # neutered gate catches none of them. `any()` as it stood made the list
        # stay green no matter what -- neutering check() emptied every kinds
        # list, so the assertion could never fail, which is how A8-cc and A8-pt
        # sat outside it for so long. `and kinds` rules out an empty list, where
        # all() is vacuously true.
        real_check = rq.check
        try:
            rq.check = lambda s: []
            kinds = {label: [b[0] for b in rq.check(text)]
                     for label, text in mutations}
        finally:
            rq.check = real_check
        check(bool(kinds) and all(v == [] for v in kinds.values()),
              "the probe has teeth: a neutered gate catches none of these",
              f"neutered returned {kinds}")

    print()
    print("-" * 74)
    if fails:
        print(f"{len(fails)} drift check(s) failed, {n_ok} passed:")
        for f in fails:
            print("  -", f)
        return 1
    print(f"{n_ok} drift checks passed, 0 failed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
