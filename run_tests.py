#!/usr/bin/env python3
"""Run every suite in the skill and fail if any of them fails.

Why this exists
---------------
Eleven test files plus two meta scripts, and no runner: each suite prints its
own summary, so a green overall impression depends on remembering to launch all
of them. That is how test_contract_drift.py and test_lint_skill.py -- the two
most likely to catch a regression, since they police the contract against both
SKILL.md and the gate -- went quiet.

The runner also parses each suite's own "N checks passed, M failed" line, so the
total at the bottom is the real count rather than a guess. A suite whose summary
line this runner cannot parse is reported as such instead of being counted as
green.

Usage
-----
    python run_tests.py [--only SUBSTRING]

    --only   run only suites whose path contains SUBSTRING

Exit codes: 0 every suite passed, 1 at least one failed, 2 nothing was run.
"""
import glob
import io
import os
import re
import subprocess
import sys

COUNTED = re.compile(r"(\d+)\s+(?:\w+\s+)?checks?\s+passed,\s*(\d+)\s+failed")
ALTERNATE = re.compile(r"^\s*(\d+)\s+passed,\s*(\d+)\s+failed", re.M)
PASS_WORD = re.compile(r"^\s*(PASS|OK|green)\b", re.I)
FAIL_WORD = re.compile(r"^\s*(FAIL|error)\b", re.I)


def suites(skill_dir):
    """Every suite, in a stable order: tests/ first, then the meta scripts."""
    tests = sorted(glob.glob(os.path.join(skill_dir, "tests", "test_*.py")))
    meta = [os.path.join(skill_dir, "scripts", n) for n in
            ("lint_skill.py", "security_probe.py")]
    return [p for p in tests + meta if os.path.isfile(p)]


def run_one(path):
    """(returncode, summary_text, raw_output) for one suite."""
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    proc = subprocess.run([sys.executable, path], capture_output=True,
                          text=True, encoding="utf-8", env=env)
    out = (proc.stdout or "") + (proc.stderr or "")
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    summary = lines[-1] if lines else "(no output)"
    return proc.returncode, summary, out, lines


def parse_ok(summary):
    """True/False from the suite's verdict, None if this runner cannot read it.

    Suites disagree about their own summary line: most print a counted
    "N checks passed, M failed" (some put a word in front of "checks"), and
    lint_skill.py prints a bare "PASS  SKILL.md" with no number at all. Anything
    this cannot read is reported as unverified rather than being counted green --
    a suite that prints nothing would otherwise look like a pass.
    """
    for rx in (COUNTED, ALTERNATE):
        m = rx.search(summary)
        if m:
            return int(m.group(2)) == 0
    if PASS_WORD.match(summary):
        return True
    if FAIL_WORD.match(summary):
        return False
    return None


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    here = os.path.dirname(os.path.abspath(__file__))
    skill_root = os.path.join(here, "skill")
    if not os.path.isdir(skill_root):
        print("error  no skill/ next to this script")
        return 2
    pkgs = [d for d in os.listdir(skill_root)
            if os.path.isdir(os.path.join(skill_root, d))]
    if len(pkgs) != 1:
        print("error  expected exactly one skill package, found %s" % pkgs)
        return 2

    only = None
    if "--only" in sys.argv:
        i = sys.argv.index("--only")
        if i + 1 >= len(sys.argv):
            print("error  --only needs a substring")
            return 2
        only = sys.argv[i + 1]

    pkg_dir = os.path.join(skill_root, pkgs[0])
    todo = suites(pkg_dir)
    if only is not None:
        todo = [p for p in todo if only in p.replace(os.sep, "/")]
    if not todo:
        print("error  no suite matched %r" % only)
        return 2

    print("running %d suite(s)" % len(todo))
    print("-" * 78)

    failures = []
    unverified = []
    for path in todo:
        rc, summary, out, lines = run_one(path)
        ok = parse_ok(summary)
        name = os.path.relpath(path, pkg_dir)
        status = "ok  " if (rc == 0 and ok is True) else "FAIL"
        print("%-6s %-34s rc=%d  %s" % (status, name, rc, summary[:60]))
        if rc != 0 or ok is False:
            failures.append((name, rc, out, lines))
        elif ok is None:
            unverified.append((name, summary))

    print("-" * 78)
    for name, rc, out, lines in failures:
        print()
        print("failures in %s (rc=%d):" % (name, rc))
        for l in lines[-25:]:
            print("  " + l[:200])
    for name, summary in unverified:
        print()
        print("unverified %s: could not read a pass/fail count from %r"
              % (name, summary))

    print()
    print("%d suite(s) passed, %d failed, %d unverified"
          % (len(todo) - len(failures) - len(unverified), len(failures),
             len(unverified)))
    return 1 if (failures or unverified) else 0


if __name__ == "__main__":
    sys.exit(main())
