#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lint a SKILL.md file against the skill contract.

    python scripts/lint_skill.py [SKILL_MD]

Defaults to ../SKILL.md relative to this script (i.e. the shipped skill).

Exit codes:
  0  every rule passed
  1  at least one error-severity finding; the summary line lists them
  2  refused -- the file does not exist, is a directory, is not UTF-8, is
     empty, or the contract cannot be read. "error" is the first line.

There is no exit 1 for warning-only findings: warnings are printed but do
not gate. That keeps this tool honest about what it blocks a release for.

The contract is the single source of truth for the rules; lint_skill.py does
not hardcode any pattern. A rule added to skill-contract.json that has no
test in tests/test_lint_skill.py is a drift the drift suite catches.
"""
import argparse
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
CONTRACT_PATH = ROOT / "schemas" / "skill-contract.json"

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def _die(msg: str) -> None:
    print(f"error  {msg}")
    sys.exit(2)


def _load_contract() -> dict:
    if not CONTRACT_PATH.is_file():
        _die(f"skill contract is not installed at {CONTRACT_PATH}, so "
             "nothing was checked")
    try:
        data = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        _die(f"skill contract cannot be read: {e}")
    if not isinstance(data, dict):
        _die(f"skill contract must be a JSON object, got "
             f"{type(data).__name__}")
    for key in ("frontmatter", "required_headings", "trigger_phrases"):
        if key not in data:
            _die(f"skill contract is missing the '{key}' section, so "
                 "nothing was checked")
    return data


def _parse_frontmatter(text: str):
    """Return (dict, body). Returns ({}, text) if no valid frontmatter."""
    if not text.startswith("---"):
        return {}, text
    lines = text.split("\n")
    end = None
    for i, ln in enumerate(lines[1:], 1):
        if ln.strip() == "---":
            end = i
            break
    if end is None:
        return {}, text
    fm_lines = lines[1:end]
    fm = {}
    for ln in fm_lines:
        if not ln.strip() or ln.startswith("#"):
            continue
        if ":" not in ln:
            continue
        key, _, value = ln.partition(":")
        fm[key.strip()] = value.strip()
    body = "\n".join(lines[end + 1:])
    return fm, body


def check_frontmatter(fm: dict, contract: dict, findings: list) -> None:
    rule = contract["frontmatter"]
    for field in rule.get("required_fields", []):
        if field not in fm or not fm[field]:
            findings.append(("FM-001", "error",
                             f"missing frontmatter field: {field}"))
    name = fm.get("name", "")
    if name:
        pat = rule.get("name_pattern", "^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
        if not re.match(pat, name):
            findings.append(("FM-002", "error",
                             f"name '{name}' does not match {pat} "
                             "(lowercase-hyphen-alnum)"))
    ver = fm.get("version", "")
    if ver:
        pat = rule.get("version_pattern", r"^\d+\.\d+\.\d+$")
        if not re.match(pat, ver):
            findings.append(("FM-003", "error",
                             f"version '{ver}' is not semver"))
    ctr = fm.get("contract", "")
    if ctr:
        pat = rule.get("contract_pattern", r"^\d+\.\d+\.\d+$")
        if not re.match(pat, ctr):
            findings.append(("FM-004", "error",
                             f"contract '{ctr}' is not semver"))
    desc = fm.get("description", "")
    mn = rule.get("description_min_chars", 80)
    mx = rule.get("description_max_chars", 5000)
    n = len(desc)
    if 0 < n < mn:
        findings.append(("FM-005", "warning",
                         f"description is {n} chars, below the {mn} minimum; "
                         "agentic tools trigger on this field"))
    if n > mx:
        findings.append(("FM-006", "warning",
                         f"description is {n} chars, above the {mx} maximum"))


def check_headings(body: str, contract: dict, findings: list) -> None:
    for rule in contract.get("required_headings", []):
        pat = rule.get("regex", "")
        sev = rule.get("severity", "warning")
        rid = rule.get("id", "unknown")
        if not re.search(pat, body, re.MULTILINE):
            findings.append((f"H-{rid}", sev,
                             f"required heading missing: /{pat}/"))


def _strip_code_regions(text: str) -> str:
    """Remove code fences and inline code spans.

    SKILL.md is the teaching document: it names the forbidden patterns as
    bad examples inside backticks, and those are demonstrations, not
    violations. Stripping them before the check keeps the rule meaningful
    for actual usage while letting the doc explain what it forbids.
    """
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"`[^`\n]*`", " ", text)
    return text


def check_forbidden(body: str, contract: dict, findings: list) -> None:
    stripped = _strip_code_regions(body)
    for rule in contract.get("forbidden_patterns", []):
        pat = rule.get("regex", "")
        rid = rule.get("id", "unknown")
        matches = re.findall(pat, stripped)
        if matches:
            findings.append((f"FP-{rid}", "error",
                             f"forbidden pattern /{pat}/ appears "
                             f"{len(matches)} time(s) outside code spans"))


def check_triggers(fm: dict, contract: dict, findings: list) -> None:
    rule = contract.get("trigger_phrases", {})
    desc = fm.get("description", "")
    phrases = rule.get("any_of", [])
    hits = [p for p in phrases if p in desc]
    need = rule.get("min_count", 3)
    if len(hits) < need:
        findings.append(("TR-001", "warning",
                         f"description names {len(hits)} of the "
                         f"{need} trigger phrases; the skill may be invisible"))
    if not rule.get("must_contain") or \
            not all(m in desc for m in rule.get("must_contain", [])):
        want = rule.get("must_contain", ["Do NOT use"])
        if not any(w in desc for w in want):
            findings.append(("TR-002", "warning",
                             "description lacks a negative trigger "
                             "phrase like 'Do NOT use'"))


def lint(text: str) -> list:
    findings = []
    contract = _load_contract()
    fm, body = _parse_frontmatter(text)
    check_frontmatter(fm, contract, findings)
    check_headings(body, contract, findings)
    check_forbidden(body, contract, findings)
    check_triggers(fm, contract, findings)
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Lint a SKILL.md file")
    parser.add_argument("path", nargs="?",
                        default=str(ROOT / "SKILL.md"),
                        help="path to SKILL.md (default: shipped skill root)")
    args = parser.parse_args()

    p = Path(args.path)
    if p.is_dir():
        _die(f"skill path is a directory, not a SKILL.md: {p}")
    if not p.is_file():
        _die(f"skill file does not exist: {p}")
    try:
        text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        _die(f"skill is not utf-8: {p}")
    except OSError as e:
        _die(f"skill cannot be read: {p} ({e})")
    if not text.strip():
        _die(f"skill is empty: {p}")

    findings = lint(text)

    if not findings:
        print(f"PASS  {p.name}")
        return 0

    n_err = sum(1 for _, sev, _ in findings if sev == "error")
    n_warn = sum(1 for _, sev, _ in findings if sev == "warning")
    print(f"{p.name}:")
    for rid, sev, msg in findings:
        tag = "error" if sev == "error" else "warn "
        print(f"  {tag}  [{rid}]  {msg}")
    print()
    if n_err:
        print(f"FAIL  {p.name}  ({n_err} error(s), {n_warn} warning(s))")
        return 1
    print(f"PASS  {p.name}  ({n_warn} warning(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
