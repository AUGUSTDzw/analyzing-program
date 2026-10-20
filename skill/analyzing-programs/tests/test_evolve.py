#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Self-contained checks for scripts/evolve.py.

    python tests/test_evolve.py

Builds markdown report fixtures in a temp directory, runs evolve.py
against them, and verifies the exit-code discipline (0 success, 2
refused), the severity counting, and the suggestion generation.

Encoding is forced because the default Windows console breaks this file
in two distinct ways: a child that encoded as cp936 raised
UnicodeDecodeError, and printing Chinese section headings to a cp936
stdout raised UnicodeEncodeError.
"""
import io
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
SCRIPT = os.path.join(SKILL, "scripts", "evolve.py")

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
    return subprocess.run([sys.executable, SCRIPT] + list(args),
                          capture_output=True, text=True, encoding="utf-8", env=env)


def write_md(path, content):
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(content)


def report_with_severities(p0=0, p1=0, p2=0, p3=0):
    """Generate a report with the given number of P0-P3 items."""
    lines = ["# Report\n\n"]
    if p0:
        lines.append("### P0 Issues\n")
        lines.append("| ID | Description |")
        lines.append("| --- | --- |")
        for i in range(p0):
            lines.append(f"| P0-{i+1} | Issue {i+1} |")
        lines.append("")
    if p1:
        lines.append("### P1 Issues\n")
        lines.append("| ID | Description |")
        lines.append("| --- | --- |")
        for i in range(p1):
            lines.append(f"| P1-{i+1} | Issue {i+1} |")
        lines.append("")
    if p2:
        lines.append("### P2 Issues\n")
        lines.append("| ID | Description |")
        lines.append("| --- | --- |")
        for i in range(p2):
            lines.append(f"| P2-{i+1} | Issue {i+1} |")
        lines.append("")
    if p3:
        lines.append("### P3 Issues\n")
        lines.append("| ID | Description |")
        lines.append("| --- | --- |")
        for i in range(p3):
            lines.append(f"| P3-{i+1} | Issue {i+1} |")
        lines.append("")
    return "\n".join(lines)


def minimal_skill():
    """A minimal SKILL.md for testing."""
    return """# Skill

## Overview

This is a test skill.
"""


def main():
    tmp = tempfile.mkdtemp()
    print("evolve.py")
    print("-" * 72)
    check(os.path.exists(SCRIPT), "scripts/evolve.py present")

    # Setup: results directory with reports.
    results = os.path.join(tmp, "results")
    os.makedirs(results)
    write_md(os.path.join(results, "report1.md"),
             report_with_severities(p0=3, p1=5, p2=2, p3=4))
    write_md(os.path.join(results, "report2.md"),
             report_with_severities(p0=2, p1=3, p2=1, p3=2))
    write_md(os.path.join(results, "report3.md"),
             report_with_severities(p0=1, p1=2, p2=3, p3=1))

    # Skill file.
    skill_path = os.path.join(tmp, "SKILL.md")
    write_md(skill_path, minimal_skill())

    # Happy path.
    r = run("--results", results, "--skill", skill_path)
    check(r.returncode == 0, "evolve exits 0",
          f"exit={r.returncode}\n{r.stdout[:300]}")
    check("scanned:" in r.stdout, "prints scan summary")
    check("total items:" in r.stdout, "prints total count")
    check("P0:" in r.stdout, "prints P0 count")
    check("P1:" in r.stdout, "prints P1 count")
    check("P2:" in r.stdout, "prints P2 count")
    check("P3:" in r.stdout, "prints P3 count")
    check("per-report breakdown:" in r.stdout, "prints per-report breakdown")
    check("suggestions" in r.stdout, "prints suggestions")

    # Verify counts: report1 has 3+5+2+4=14, report2 has 2+3+1+2=8, report3 has 1+2+3+1=7
    # Total: P0=6, P1=10, P2=6, P3=7 = 29
    check("3 report(s)" in r.stdout or "3 report" in r.stdout, "counts 3 reports")
    # Check the total is correct
    check("29" in r.stdout, "total items is 29")

    # Refusal: results directory does not exist.
    r = run("--results", os.path.join(tmp, "nodir"), "--skill", skill_path)
    check(r.returncode == 2, "missing results dir exits 2")
    check("does not exist" in r.stdout, "missing results names the problem")

    # Refusal: skill file does not exist.
    r = run("--results", results, "--skill", os.path.join(tmp, "noskill.md"))
    check(r.returncode == 2, "missing skill file exits 2")
    check("does not exist" in r.stdout, "missing skill names the problem")

    # Refusal: no markdown reports.
    empty_results = os.path.join(tmp, "empty")
    os.makedirs(empty_results)
    r = run("--results", empty_results, "--skill", skill_path)
    check(r.returncode == 2, "empty results dir exits 2")
    check("no markdown" in r.stdout, "empty results names the problem")

    # Refusal: reports with no severity items.
    no_sev_results = os.path.join(tmp, "nosev")
    os.makedirs(no_sev_results)
    write_md(os.path.join(no_sev_results, "clean.md"), "# Clean Report\n\nNo issues found.\n")
    r = run("--results", no_sev_results, "--skill", skill_path)
    check(r.returncode == 0, "no-severity reports exit 0",
          f"exit={r.returncode}\n{r.stdout[:200]}")
    check("No P0-P3 items found" in r.stdout, "suggests updating template")

    # Verify severity counting excludes code fences.
    code_results = os.path.join(tmp, "code")
    os.makedirs(code_results)
    write_md(os.path.join(code_results, "with_code.md"),
             "# Report\n\n"
             "## P0 Issues\n"
             "```\n"
             "P0-1 is in a code fence, should not be counted.\n"
             "P1-2 also in code fence.\n"
             "```\n"
             "\n"
             "Real P0-1 item here.\n")
    r = run("--results", code_results, "--skill", skill_path)
    check(r.returncode == 0, "code fence test exits 0")
    # Should count only 1 P0 (the one outside code fence)
    check("P0: 1" in r.stdout, "code fence P0 not counted",
          r.stdout)

    # Verify inline code is also excluded.
    inline_results = os.path.join(tmp, "inline")
    os.makedirs(inline_results)
    write_md(os.path.join(inline_results, "inline.md"),
             "# Report\n\n"
             "This is `P0-1` in inline code, should not be counted.\n"
             "Real P0-1 item.\n")
    r = run("--results", inline_results, "--skill", skill_path)
    check(r.returncode == 0, "inline code test exits 0")
    check("P0: 1" in r.stdout, "inline code P0 not counted",
          r.stdout)

    # Test with default paths (will use actual Test-result/ if it exists).
    # Just verify it doesn't crash.
    r = run()
    check(r.returncode in (0, 2), "default paths exit 0 or 2",
          f"exit={r.returncode}")

    print()
    print(f"{N_OK} passed, {len(FAILS)} failed")
    if FAILS:
        print("failures:")
        for f in FAILS:
            print("  -", f)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
