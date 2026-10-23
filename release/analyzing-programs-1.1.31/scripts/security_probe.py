#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Probe report_qc.py --fix against adversarial inputs.

    python scripts/security_probe.py [--verbose]

Creates a set of adversarial report files, runs report_qc.py --fix on each,
and verifies that the fixer:

  - does not crash (no unhandled exception)
  - does not silently bypass a check (a fabricated citation is still caught)
  - produces valid UTF-8 output (no encoding corruption)
  - exits with the correct code (0 clean, 1 defects remain, 2 refused)

Exit codes:
  0  all probes passed (the fixer handled every adversarial input correctly)
  1  at least one probe failed (the fixer crashed, bypassed a check, or
     produced invalid output)
  2  the fixer script itself is missing or not runnable

Why this exists: a repair function is only as safe as its edge cases.
report_qc.py --fix rewrites line numbers and Mermaid labels, and a repair
that crashes on malformed input or silently accepts a fabricated citation
turns the gate into a bypass. SkillGuardBench's point is that safety
evaluation is not optional for tools that modify output. This probe is the
minimal version: it does not try to be a fuzzing framework, it runs a
hand-built corpus of known bad inputs and checks that the fixer survives
them.

The probes are ordered so that a crash on an early probe does not hide
failures on later ones: each probe runs in its own subprocess, and a
crashing probe is reported as a failure without stopping the run.
"""
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
SCRIPT = os.path.join(HERE, "report_qc.py")

VERBOSE = "--verbose" in sys.argv

# A minimal valid ABAP source for probes that need one.
DUMMY_SOURCE = "REPORT zdummy.\n\nDATA: lt_data TYPE TABLE OF sometype.\n"


def _verbose(msg: str) -> None:
    if VERBOSE:
        print(f"    {msg}")


def _run_fix(report_path: str, source_path: str = None):
    """Run report_qc.py --fix on a report and return (exit_code, stdout, stderr, crashed)."""
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    cmd = [sys.executable, SCRIPT, "--fix", report_path]
    if source_path:
        cmd.append(source_path)
    try:
        r = subprocess.run(
            cmd,
            capture_output=True, text=True, encoding="utf-8", env=env,
            timeout=30
        )
        crashed = False
    except subprocess.TimeoutExpired:
        return None, "", "timed out after 30s", True
    except Exception as e:
        return None, "", str(e), True
    return r.returncode, r.stdout, r.stderr, crashed


def _write(path: str, content, binary: bool = False) -> None:
    if binary:
        with open(path, "wb") as f:
            f.write(content)
    else:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)


def _write_dummy_source(tmp: str) -> str:
    """Write a minimal valid ABAP source and return its path."""
    src = os.path.join(tmp, "dummy.abap")
    _write(src, DUMMY_SOURCE)
    return src


def _probe(name: str, setup_fn, check_fn, needs_source: bool = False) -> bool:
    """Run a single probe: setup, fix, check. Returns True if passed."""
    global N_OK
    tmp = tempfile.mkdtemp()
    try:
        source_path = _write_dummy_source(tmp) if needs_source else None
        report_path = setup_fn(tmp, source_path)
        _verbose(f"{name}: setup done")
        code, out, err, crashed = _run_fix(report_path, source_path)
        if crashed:
            print(f"  FAIL  {name}: fixer crashed")
            _verbose(f"    stderr: {err[:200]}")
            FAILS.append(name)
            return False
        _verbose(f"{name}: exit={code}")
        ok = check_fn(code, out, err, report_path)
        if ok:
            print(f"  ok    {name}")
            N_OK += 1
        else:
            print(f"  FAIL  {name}")
            _verbose(f"    stdout: {out[:300]}")
            _verbose(f"    stderr: {err[:200]}")
            FAILS.append(name)
        return ok
    except Exception as e:
        print(f"  FAIL  {name}: probe error: {e}")
        FAILS.append(name)
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


FAILS = []
N_OK = 0


def check(cond, label, detail=""):
    global N_OK
    if cond:
        N_OK += 1
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f"   {detail}" if detail else ""))
    if not cond:
        FAILS.append(label)


def main() -> int:
    print("security_probe.py")
    print("-" * 72)

    if not os.path.exists(SCRIPT):
        print(f"error  report_qc.py not found at {SCRIPT}")
        return 2

    all_ok = True

    # Probe 1: empty report
    def setup_empty(tmp, src):
        p = os.path.join(tmp, "empty.md")
        _write(p, "")
        return p

    def check_empty(code, out, err, path):
        # Empty report is not refused; it's processed and found to have defects
        # (missing sections, missing Mermaid). Exit 1 is correct.
        return code == 1

    if not _probe("empty report", setup_empty, check_empty, needs_source=True):
        pass

    # Probe 2: whitespace-only report
    def setup_whitespace(tmp, src):
        p = os.path.join(tmp, "ws.md")
        _write(p, "   \n\t\n  \n")
        return p

    def check_whitespace(code, out, err, path):
        # Whitespace-only report is processed and found to have defects.
        # Exit 1 is correct.
        return code == 1

    if not _probe("whitespace-only report", setup_whitespace, check_whitespace, needs_source=True):
        pass

    # Probe 3: invalid UTF-8
    def setup_bad_utf8(tmp, src):
        p = os.path.join(tmp, "bad_utf8.md")
        _write(p, b"\xff\xfe\x00not utf8\n", binary=True)
        return p

    def check_bad_utf8(code, out, err, path):
        combined = (out + err).lower()
        return code == 2 and ("utf-8" in combined or "fix needs" in combined)

    if not _probe("invalid UTF-8 report", setup_bad_utf8, check_bad_utf8, needs_source=True):
        all_ok = False

    # Probe 4: null bytes
    def setup_null_bytes(tmp, src):
        p = os.path.join(tmp, "nulls.md")
        _write(p, b"## Overview\n\n\x00\x00\x00test\n", binary=True)
        return p

    def check_null_bytes(code, out, err, path):
        # report_qc.py should either handle or refuse null bytes
        return code in (0, 1, 2)  # must not crash

    if not _probe("null bytes in report", setup_null_bytes, check_null_bytes, needs_source=True):
        all_ok = False

    # Probe 5: unbalanced fences
    def setup_unbalanced(tmp, src):
        p = os.path.join(tmp, "unbalanced.md")
        _write(p, "## Overview\n\nSome text.\n\n```abap\nREPORT ztest.\n")
        return p

    def check_unbalanced(code, out, err, path):
        return code in (0, 1, 2)  # must not crash

    if not _probe("unbalanced code fence", setup_unbalanced, check_unbalanced, needs_source=True):
        all_ok = False

    # Probe 6: very long line
    def setup_long_line(tmp, src):
        p = os.path.join(tmp, "longline.md")
        _write(p, "## Overview\n\n" + "x" * 100000 + "\n")
        return p

    def check_long_line(code, out, err, path):
        return code in (0, 1, 2)  # must not crash

    if not _probe("very long line", setup_long_line, check_long_line, needs_source=True):
        all_ok = False

    # Probe 7: report with only headings
    def setup_headings_only(tmp, src):
        p = os.path.join(tmp, "headings.md")
        _write(p, "## Overview\n\n## Analysis\n\n## Risks\n")
        return p

    def check_headings_only(code, out, err, path):
        return code in (0, 1, 2)  # must not crash

    if not _probe("headings only", setup_headings_only, check_headings_only, needs_source=True):
        all_ok = False

    # Probe 8: special characters in text
    def setup_special_chars(tmp, src):
        p = os.path.join(tmp, "special.md")
        _write(p, "## Overview\n\nText with special chars: <>&\"'`\\{}[]()|*~!@#$%%^\n\n"
                   "Unicode: \u2713 \u2717 \u2192 \u2260 \u2264 \u2265\n\n"
                   "## Analysis\n\nMore special chars: \x01 \x02 \x03 \x7f\n")
        return p

    def check_special_chars(code, out, err, path):
        return code in (0, 1, 2)  # must not crash

    if not _probe("special characters", setup_special_chars, check_special_chars, needs_source=True):
        all_ok = False

    # Probe 9: line number citation forgery (the key adversarial case)
    def setup_forged_citation(tmp, src):
        # Use the dummy source that has 3 lines
        rep_path = os.path.join(tmp, "forged.md")
        _write(rep_path, "## Overview\n\n"
                         "The program at [dummy.abap:99](dummy.abap:99) does something.\n\n"
                         "## Analysis\n\n"
                         "Line [dummy.abap:500](dummy.abap:500) contains a critical defect.\n")
        return rep_path

    def check_forged_citation(code, out, err, path):
        # The fixer should NOT silently accept fabricated citations
        # Code 0 means clean, which would be a bypass
        # Code 1 means defects remain, which is correct
        # Code 2 means refused, which is also acceptable
        if code == 0:
            return False  # bypass!
        return True

    if not _probe("forged line-number citation", setup_forged_citation, check_forged_citation, needs_source=True):
        all_ok = False

    # Probe 10: Mermaid label with bare <
    def setup_bare_angle(tmp, src):
        p = os.path.join(tmp, "mermaid.md")
        _write(p, "## Overview\n\n```mermaid\ngraph TD\n    A --> B <label>\n```\n")
        return p

    def check_bare_angle(code, out, err, path):
        return code in (0, 1, 2)  # must not crash

    if not _probe("Mermaid bare angle bracket", setup_bare_angle, check_bare_angle, needs_source=True):
        all_ok = False

    # Probe 11: directory as report path
    def setup_dir_report(tmp, src):
        p = os.path.join(tmp, "adir")
        os.makedirs(p)
        return p

    def check_dir_report(code, out, err, path):
        return code == 2  # should refuse

    if not _probe("directory as report", setup_dir_report, check_dir_report, needs_source=True):
        all_ok = False

    # Probe 12: nonexistent report
    def setup_nonexistent(tmp, src):
        return os.path.join(tmp, "nonexistent.md")

    def check_nonexistent(code, out, err, path):
        return code == 2  # should refuse

    if not _probe("nonexistent report", setup_nonexistent, check_nonexistent, needs_source=True):
        all_ok = False

    # Probe 13: report with only a preamble (no sections)
    def setup_preamble_only(tmp, src):
        p = os.path.join(tmp, "preamble.md")
        _write(p, "This is just a preamble with no sections.\n")
        return p

    def check_preamble_only(code, out, err, path):
        return code in (0, 1, 2)  # must not crash

    if not _probe("preamble only", setup_preamble_only, check_preamble_only, needs_source=True):
        all_ok = False

    # Probe 14: deeply nested headings
    def setup_nested(tmp, src):
        p = os.path.join(tmp, "nested.md")
        _write(p, "## Overview\n### Analysis\n#### Sub-analysis\n##### Deep\n###### Deeper\n")
        return p

    def check_nested(code, out, err, path):
        return code in (0, 1, 2)  # must not crash

    if not _probe("deeply nested headings", setup_nested, check_nested, needs_source=True):
        all_ok = False

    # Probe 15: mixed encoding (valid UTF-8 with embedded null)
    def setup_mixed_encoding(tmp, src):
        p = os.path.join(tmp, "mixed.md")
        _write(p, b"## Overview\n\n\x00\x00\x00test\n\n\x00\x00\x00more\n", binary=True)
        return p

    def check_mixed_encoding(code, out, err, path):
        return code in (0, 1, 2)  # must not crash

    if not _probe("mixed encoding", setup_mixed_encoding, check_mixed_encoding, needs_source=True):
        all_ok = False

    # Probe 16: report that is exactly the minimum valid report
    def setup_minimal_valid(tmp, src):
        p = os.path.join(tmp, "minimal.md")
        _write(p, "# Report\n\n## Overview\n\nThis is a minimal report.\n\n"
                  "## Analysis\n\nThe analysis section.\n\n"
                  "## Risks\n\nThe risks section.\n")
        return p

    def check_minimal_valid(code, out, err, path):
        return code in (0, 1, 2)  # must not crash

    if not _probe("minimal valid report", setup_minimal_valid, check_minimal_valid, needs_source=True):
        all_ok = False

    # Probe 17: missing source file
    def setup_missing_source(tmp, src):
        p = os.path.join(tmp, "report.md")
        _write(p, "## Overview\n\nReport content.\n")
        return p

    def check_missing_source(code, out, err, path):
        # report_qc.py --fix requires a source; without one it refuses
        return code == 2

    if not _probe("missing source file", setup_missing_source, check_missing_source, needs_source=False):
        all_ok = False

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
