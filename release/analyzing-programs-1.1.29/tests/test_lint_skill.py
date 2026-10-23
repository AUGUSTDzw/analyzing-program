#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Self-contained checks for scripts/lint_skill.py.

    python tests/test_lint_skill.py

Builds minimal SKILL.md fixtures in a temp directory and runs lint_skill.py
against each. Verifies the exit-code discipline (0 pass, 1 errors, 2 refused),
that contract drift is caught, and that forbidden-pattern checks ignore code
spans (the case that would otherwise false-positive on SKILL.md itself).

Encoding is forced because the default Windows console breaks this file in
two distinct ways: a child that encoded as cp936 raised UnicodeDecodeError,
and printing the contract's forbidden patterns to a cp936 stdout raised
UnicodeEncodeError. So the child gets PYTHONIOENCODING and this process
reconfigures its own streams.
"""
import io
import json
import os
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
SCRIPT = os.path.join(SKILL, "scripts", "lint_skill.py")
CONTRACT = os.path.join(SKILL, "schemas", "skill-contract.json")
SHIPPED = os.path.join(SKILL, "SKILL.md")

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


def minimal_skill():
    """A SKILL.md that should pass every rule."""
    return (
        "---\n"
        "name: minimal-skill\n"
        "version: 1.0.0\n"
        "contract: 1.0.0\n"
        "description: Use when the user wants an onboarding report, 分析 this "
        "program, or 讲解 the code. Trigger on '分析这个程序','走读','源码分析'. "
        "Do NOT use for one-line answers or non-SAP code.\n"
        "---\n"
        "\n"
        "# Skill: minimal-skill\n"
        "\n"
        "## Overview\n"
        "\n"
        "One line.\n"
        "\n"
        "## Analysis Flow\n"
        "\n"
        "One step.\n"
        "\n"
        "## 闸门输出\n"
        "\n"
        "Exit codes.\n"
    )


def main():
    tmp = tempfile.mkdtemp()
    print("lint_skill.py")
    print("-" * 72)
    check(os.path.exists(SCRIPT), "scripts/lint_skill.py present")
    check(os.path.exists(CONTRACT), "schemas/skill-contract.json present")

    # The shipped SKILL.md should pass. It is the exemplar for every rule.
    r = run(SHIPPED)
    check(r.returncode == 0, "shipped SKILL.md passes",
          f"exit={r.returncode}")
    check("PASS" in r.stdout, "shipped SKILL.md prints PASS",
          r.stdout.strip().split("\n")[0][:44])

    # Refusal: file does not exist.
    r = run(os.path.join(tmp, "nope.md"))
    check(r.returncode == 2, "missing file exits 2", f"exit={r.returncode}")
    check(r.stdout.startswith("error"), "missing file prints error first")

    # Refusal: path is a directory.
    r = run(tmp)
    check(r.returncode == 2, "directory path exits 2")
    check("directory" in r.stdout, "directory path names the problem")

    # Refusal: not UTF-8.
    bad_enc = os.path.join(tmp, "bad.md")
    with io.open(bad_enc, "wb") as f:
        f.write(b"\xff\xfe\x00not utf8")
    r = run(bad_enc)
    check(r.returncode == 2, "non-utf8 exits 2")
    check("not utf-8" in r.stdout, "non-utf8 names the problem")

    # Refusal: empty.
    empty = os.path.join(tmp, "empty.md")
    io.open(empty, "w", encoding="utf-8").write("   \n\t\n")
    r = run(empty)
    check(r.returncode == 2, "empty file exits 2")
    check("empty" in r.stdout, "empty file names the problem")

    # Happy path: a minimal valid skill passes.
    good = os.path.join(tmp, "good.md")
    io.open(good, "w", encoding="utf-8").write(minimal_skill())
    r = run(good)
    check(r.returncode == 0, "minimal valid skill passes",
          f"exit={r.returncode}\n{r.stdout[:200]}")
    check("PASS" in r.stdout, "minimal valid skill prints PASS")

    # Error: missing required frontmatter field.
    bad_fm = os.path.join(tmp, "no_version.md")
    io.open(bad_fm, "w", encoding="utf-8").write(minimal_skill().replace(
        "version: 1.0.0\n", ""))
    r = run(bad_fm)
    check(r.returncode == 1, "missing frontmatter field exits 1",
          f"exit={r.returncode}")
    check("FM-001" in r.stdout, "missing field names the rule id")

    # Error: bad name pattern (uppercase).
    bad_name = os.path.join(tmp, "badname.md")
    io.open(bad_name, "w", encoding="utf-8").write(minimal_skill().replace(
        "name: minimal-skill", "name: Minimal_Skill"))
    r = run(bad_name)
    check(r.returncode == 1, "bad name pattern exits 1")
    check("FM-002" in r.stdout, "bad name names the rule id")

    # Error: bad version (not semver).
    bad_ver = os.path.join(tmp, "badver.md")
    io.open(bad_ver, "w", encoding="utf-8").write(minimal_skill().replace(
        "version: 1.0.0", "version: v1"))
    r = run(bad_ver)
    check(r.returncode == 1, "bad version exits 1")
    check("FM-003" in r.stdout, "bad version names the rule id")

    # Warning: short description.
    short_desc = os.path.join(tmp, "short.md")
    io.open(short_desc, "w", encoding="utf-8").write(minimal_skill().replace(
        "description: Use when the user wants an onboarding report, 分析 this "
        "program, or 讲解 the code. Trigger on '分析这个程序','走读','源码分析'. "
        "Do NOT use for one-line answers or non-SAP code.",
        "description: Use when. Do NOT use for one-line answers."))
    r = run(short_desc)
    check(r.returncode == 0, "short description exits 0 (warning only)")
    check("FM-005" in r.stdout, "short description names the rule id")
    check("PASS" in r.stdout, "short description still prints PASS")

    # Error: forbidden pattern outside code spans.
    # Note: the minimal_skill helper already has a valid description, so we
    # need to inject the forbidden pattern outside backticks.
    forbidden = os.path.join(tmp, "forbidden.md")
    body = minimal_skill().replace(
        "## Overview\n\nOne line.",
        "## Overview\n\nSee izvend.abap:104 for the anchor.")
    io.open(forbidden, "w", encoding="utf-8").write(body)
    r = run(forbidden)
    check(r.returncode == 1, "forbidden pattern outside code exits 1",
          f"exit={r.returncode}\n{r.stdout[:200]}")
    check("FP-" in r.stdout, "forbidden pattern names the rule id")

    # Same pattern INSIDE a code span is a demonstration, not a violation.
    # This is the case that would otherwise false-positive on SKILL.md itself,
    # which shows the pattern as a bad example.
    in_code = os.path.join(tmp, "in_code.md")
    body = minimal_skill().replace(
        "## Overview\n\nOne line.",
        "## Overview\n\nNever write `zvend.abap:104` like this.")
    io.open(in_code, "w", encoding="utf-8").write(body)
    r = run(in_code)
    check(r.returncode == 0, "forbidden pattern inside code span exits 0",
          f"exit={r.returncode}\n{r.stdout[:200]}")
    check("FP-" not in r.stdout, "code-span demonstration is not a violation")

    # Error: missing required heading.
    no_heading = os.path.join(tmp, "noheading.md")
    io.open(no_heading, "w", encoding="utf-8").write(minimal_skill().replace(
        "## Analysis Flow\n", "## Something Else\n"))
    r = run(no_heading)
    check(r.returncode == 1, "missing heading exits 1",
          f"exit={r.returncode}")
    check("H-analysis-flow" in r.stdout, "missing heading names the rule id")

    # Warning: missing negative trigger phrase.
    no_neg = os.path.join(tmp, "noneg.md")
    io.open(no_neg, "w", encoding="utf-8").write(minimal_skill().replace(
        "Do NOT use for one-line answers or non-SAP code.",
        "Only use for SAP code."))
    r = run(no_neg)
    check(r.returncode == 0, "missing negative trigger exits 0 (warning only)")
    check("TR-002" in r.stdout, "missing negative trigger names the rule id")

    # Warning: too few trigger phrases.
    few_trig = os.path.join(tmp, "fewtrig.md")
    io.open(few_trig, "w", encoding="utf-8").write(minimal_skill().replace(
        "description: Use when the user wants an onboarding report, 分析 this "
        "program, or 讲解 the code. Trigger on '分析这个程序','走读','源码分析'. "
        "Do NOT use for one-line answers or non-SAP code.",
        "description: Use when needed. Do NOT use for unrelated input."))
    r = run(few_trig)
    check(r.returncode == 0, "few trigger phrases exits 0 (warning only)")
    check("TR-001" in r.stdout, "few trigger phrases names the rule id")

    # Contract drift: a contract missing a required section refuses.
    # Copy the script into a fresh root so CONTRACT_PATH resolves inside it.
    root = os.path.join(tmp, "drift")
    os.makedirs(os.path.join(root, "schemas"))
    os.makedirs(os.path.join(root, "scripts"))
    shutil.copy(SCRIPT, os.path.join(root, "scripts", "lint_skill.py"))
    # A contract that parses but lacks the trigger_phrases section.
    io.open(os.path.join(root, "schemas", "skill-contract.json"),
            "w", encoding="utf-8").write(
        json.dumps({"frontmatter": {}, "required_headings": []}))
    skill = os.path.join(tmp, "drift_skill.md")
    io.open(skill, "w", encoding="utf-8").write(minimal_skill())
    r = subprocess.run([sys.executable,
                        os.path.join(root, "scripts", "lint_skill.py"),
                        skill],
                       capture_output=True, text=True, encoding="utf-8",
                       env=dict(os.environ, PYTHONIOENCODING="utf-8",
                                PYTHONUTF8="1"))
    check(r.returncode == 2, "contract missing trigger_phrases exits 2",
          f"exit={r.returncode}")
    check("skill contract is missing" in r.stdout,
          "contract drift names the missing section")
    check("nothing was checked" in r.stdout,
          "contract drift announces nothing was checked")

    # Corrupt contract: not parseable JSON.
    root = os.path.join(tmp, "corrupt")
    os.makedirs(os.path.join(root, "schemas"))
    os.makedirs(os.path.join(root, "scripts"))
    shutil.copy(SCRIPT, os.path.join(root, "scripts", "lint_skill.py"))
    io.open(os.path.join(root, "schemas", "skill-contract.json"),
            "w", encoding="utf-8").write("{ not json")
    skill = os.path.join(tmp, "corrupt_skill.md")
    io.open(skill, "w", encoding="utf-8").write(minimal_skill())
    r = subprocess.run([sys.executable,
                        os.path.join(root, "scripts", "lint_skill.py"),
                        skill],
                       capture_output=True, text=True, encoding="utf-8",
                       env=dict(os.environ, PYTHONIOENCODING="utf-8",
                                PYTHONUTF8="1"))
    check(r.returncode == 2, "corrupt contract exits 2", f"exit={r.returncode}")
    check("cannot be read" in r.stdout, "corrupt contract names the problem")
    check("Traceback" not in r.stdout and "Traceback" not in r.stderr,
          "corrupt contract does not raise")

    # A fully-clean skill: the printed verdict names only PASS, no count.
    clean = os.path.join(tmp, "fullyclean.md")
    io.open(clean, "w", encoding="utf-8").write(minimal_skill().replace(
        "## Overview\n\nOne line.\n\n## Analysis Flow",
        "## Overview\n\nOne line.\n\n## Analysis Flow\n\nSteps."
        "\n\n## Report Structure\n\nSections."
        "\n\nThree-Layer format."))
    r = run(clean)
    check(r.returncode == 0, "fully clean skill exits 0")
    check(r.stdout.strip().endswith("PASS  fullyclean.md"),
          "fully clean skill ends with PASS  <name>",
          r.stdout.strip().split("\n")[-1])

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
