#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Self-contained checks for scripts/lift.py.

    python tests/test_lift.py

Builds defect and verdict JSON fixtures in a temp directory and runs
lift.py against them. Verifies the exit-code discipline (0 reporter, 2
refused), the sign-test computation, the delta reporting, and refusal on
mismatched verdict files.

Encoding is forced because the default Windows console breaks this file in
two distinct ways: a child that encoded as cp936 raised UnicodeDecodeError,
and printing to a cp936 stdout raised UnicodeEncodeError.
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
SCRIPT = os.path.join(SKILL, "scripts", "lift.py")

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


def write_json(path, data):
    with io.open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def defects_5():
    return {
        "source": "zvend.abap",
        "defects": [
            {"id": "P0-1", "severity": "P0"},
            {"id": "P1-1", "severity": "P1"},
            {"id": "P2-1", "severity": "P2"},
            {"id": "P3-1", "severity": "P3"},
            {"id": "P3-2", "severity": "P3"},
        ]
    }


def verdicts_with():
    return {
        "report": "report.md",
        "verdicts": {
            "P0-1": "yes", "P1-1": "yes", "P2-1": "partial",
            "P3-1": "no", "P3-2": "no",
        },
        "false_claims": []
    }


def verdicts_without():
    return {
        "report": "report.md",
        "verdicts": {
            "P0-1": "no", "P1-1": "yes", "P2-1": "no",
            "P3-1": "partial", "P3-2": "no",
        },
        "false_claims": [{"claim": "fake", "why_wrong": "not in source"}]
    }


def verdicts_equal():
    return {
        "report": "report.md",
        "verdicts": {
            "P0-1": "yes", "P1-1": "yes", "P2-1": "partial",
            "P3-1": "no", "P3-2": "no",
        },
        "false_claims": []
    }


def main():
    tmp = tempfile.mkdtemp()
    print("lift.py")
    print("-" * 72)
    check(os.path.exists(SCRIPT), "scripts/lift.py present")

    dpath = os.path.join(tmp, "defects.json")
    wpath = os.path.join(tmp, "with.json")
    bpath = os.path.join(tmp, "without.json")
    write_json(dpath, defects_5())
    write_json(wpath, verdicts_with())
    write_json(bpath, verdicts_without())

    # Happy path: with-skill better.
    r = run("--defects", dpath, "--with-skill", wpath,
            "--without-skill", bpath)
    check(r.returncode == 0, "comparison exits 0",
          f"exit={r.returncode}\n{r.stdout[:300]}")
    check("recall" in r.stdout, "prints recall for both")
    check("delta recall" in r.stdout, "prints delta recall")
    check("sign test" in r.stdout, "prints sign test")
    check("p =" in r.stdout, "prints p-value")
    check("better on" in r.stdout, "prints better/worse counts")
    # The delta should be positive (with-skill recall > without-skill).
    check("+" in r.stdout, "delta recall is positive")

    # Refusal: missing --defects.
    r = run("--with-skill", wpath, "--without-skill", bpath)
    check(r.returncode == 2, "missing --defects exits 2")
    check("defects" in (r.stdout + r.stderr), "missing --defects names the problem")

    # Refusal: missing --with-skill.
    r = run("--defects", dpath, "--without-skill", bpath)
    check(r.returncode == 2, "missing --with-skill exits 2")
    check("with-skill" in (r.stdout + r.stderr), "missing --with-skill names the problem")

    # Refusal: missing --without-skill.
    r = run("--defects", dpath, "--with-skill", wpath)
    check(r.returncode == 2, "missing --without-skill exits 2")
    check("without-skill" in (r.stdout + r.stderr), "missing --without-skill names the problem")

    # Refusal: defects file does not exist.
    r = run("--defects", os.path.join(tmp, "nope.json"),
            "--with-skill", wpath, "--without-skill", bpath)
    check(r.returncode == 2, "missing defects file exits 2")
    check("does not exist" in r.stdout, "missing defects names the problem")

    # Refusal: verdict file does not exist.
    r = run("--defects", dpath,
            "--with-skill", os.path.join(tmp, "nope.json"),
            "--without-skill", bpath)
    check(r.returncode == 2, "missing verdict file exits 2")
    check("does not exist" in r.stdout, "missing verdict names the problem")

    # Refusal: corrupt JSON.
    bad_json = os.path.join(tmp, "bad.json")
    io.open(bad_json, "w", encoding="utf-8").write("{not valid json")
    r = run("--defects", dpath,
            "--with-skill", bad_json, "--without-skill", bpath)
    check(r.returncode == 2, "corrupt verdict exits 2")
    check("not parseable" in r.stdout, "corrupt verdict names the problem")

    # Refusal: verdicts missing a defect.
    partial_v = os.path.join(tmp, "partial.json")
    partial_verdicts = verdicts_with()
    del partial_verdicts["verdicts"]["P3-2"]
    write_json(partial_v, partial_verdicts)
    r = run("--defects", dpath,
            "--with-skill", partial_v, "--without-skill", bpath)
    check(r.returncode == 2, "missing verdict entry exits 2")
    check("never judged" in r.stdout, "missing verdict names the problem")

    # Refusal: verdict has unknown defect.
    extra_v = os.path.join(tmp, "extra.json")
    extra_verdicts = verdicts_with()
    extra_verdicts["verdicts"]["UNKNOWN"] = "yes"
    write_json(extra_v, extra_verdicts)
    r = run("--defects", dpath,
            "--with-skill", extra_v, "--without-skill", bpath)
    check(r.returncode == 2, "extra verdict entry exits 2")
    check("unknown defect" in r.stdout, "extra verdict names the problem")

    # Refusal: bad verdict value.
    badval_v = os.path.join(tmp, "badval.json")
    badval_verdicts = verdicts_with()
    badval_verdicts["verdicts"]["P0-1"] = "maybe"
    write_json(badval_v, badval_verdicts)
    r = run("--defects", dpath,
            "--with-skill", badval_v, "--without-skill", bpath)
    check(r.returncode == 2, "bad verdict value exits 2")
    check("yes, partial, no" in r.stdout, "bad verdict names the problem")

    # Refusal: false_claims is not a list.
    badfc_v = os.path.join(tmp, "badfc.json")
    badfc_verdicts = verdicts_with()
    badfc_verdicts["false_claims"] = 3  # a count, not a list
    write_json(badfc_v, badfc_verdicts)
    r = run("--defects", dpath,
            "--with-skill", badfc_v, "--without-skill", bpath)
    check(r.returncode == 2, "non-list false_claims exits 2")
    check("false_claims" in r.stdout, "non-list false_claims names the problem")

    # Equal verdicts: delta is 0.000, p = 1.0.
    eq_v = os.path.join(tmp, "equal.json")
    write_json(eq_v, verdicts_equal())
    r = run("--defects", dpath, "--with-skill", eq_v,
            "--without-skill", eq_v)
    check(r.returncode == 0, "equal verdicts exits 0")
    check("p = 1.0000" in r.stdout, "equal verdicts give p=1.0",
          r.stdout)
    check("not distinguishable" in r.stdout,
          "equal verdicts report noise")

    # Delta false_claims: with-skill has 0, without-skill has 1 -> delta -1.
    r = run("--defects", dpath, "--with-skill", wpath,
            "--without-skill", bpath)
    check("-1" in r.stdout, "delta false_claims is negative (fewer in with-skill)")

    # All verdicts "yes" in both: perfect recall, no delta.
    all_yes = os.path.join(tmp, "allyes.json")
    all_yes_verdicts = {
        "report": "report.md",
        "verdicts": {x["id"]: "yes" for x in defects_5()["defects"]},
        "false_claims": []
    }
    write_json(all_yes, all_yes_verdicts)
    r = run("--defects", dpath, "--with-skill", all_yes,
            "--without-skill", all_yes)
    check(r.returncode == 0, "all-yes exits 0")
    check("recall 1.000" in r.stdout, "all-yes gives recall 1.000")
    check("p = 1.0000" in r.stdout, "all-yes gives p=1.0")

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
