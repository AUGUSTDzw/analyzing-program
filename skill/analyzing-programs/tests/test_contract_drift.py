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
"""
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
CONTRACT = os.path.join(SKILL, "schemas", "report-contract.json")
SKILL_MD = os.path.join(SKILL, "SKILL.md")

fails = []


def check(cond, label, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f"   {detail}" if detail else ""))
    if not cond:
        fails.append(label)


def anchors(node, out):
    """Every skill_anchor in the contract, wherever it sits."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "skill_anchor" and isinstance(v, str):
                out.append((v, node.get("id") or node.get("label") or k))
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
    check("never implies" in " ".join(cs.get("_comment", [])) or
          "never implies" in cs.get("_comment", [""])[0] if cs.get("_comment") else False,
          "the contract says one pass never implies the others",
          "borrowed from archify's delivery contract")

    print()
    print("-" * 74)
    if fails:
        print(f"{len(fails)} drift check(s) failed:")
        for f in fails:
            print("  -", f)
        return 1
    print("no drift between the contract and SKILL.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
