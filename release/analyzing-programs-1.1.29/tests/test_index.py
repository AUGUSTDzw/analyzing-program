#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Self-contained checks for scripts/index.py.

    python tests/test_index.py

Builds markdown fixtures in a temp directory, runs index.py build and
query, and verifies the exit-code discipline (0 success, 2 refused),
the index structure, query ranking, and refusal on bad input.

Encoding is forced because the default Windows console breaks this file
in two distinct ways: a child that encoded as cp936 raised
UnicodeDecodeError, and printing Chinese section headings to a cp936
stdout raised UnicodeEncodeError.
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
SCRIPT = os.path.join(SKILL, "scripts", "index.py")

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


def main():
    tmp = tempfile.mkdtemp()
    print("index.py")
    print("-" * 72)
    check(os.path.exists(SCRIPT), "scripts/index.py present")

    # Setup: two markdown files with known sections.
    refs = os.path.join(tmp, "references")
    os.makedirs(refs)
    write_md(os.path.join(refs, "abap.md"),
             "## Overview\n\n"
             "The program reads material master data from table MARA using "
             "FOR ALL ENTRIES and writes it to a sorted internal table.\n\n"
             "## Authorization\n\n"
             "AUTHORITY-CHECK enforces authorization before any SELECT "
             "executes. The role profile is checked at session start.\n")
    write_md(os.path.join(refs, "reports.md"),
             "## Report Structure\n\n"
             "Every report must have six sections: Overview, Analysis, "
             "Flow, Risks, Verification, and Appendix.\n\n"
             "## Mermaid Diagrams\n\n"
             "Reports must include a flowchart and a sequenceDiagram "
             "to visualize the program's control flow.\n")

    # Build mode.
    idx = os.path.join(tmp, "index.json")
    r = run("build", refs, "--output", idx)
    check(r.returncode == 0, "build exits 0",
          f"exit={r.returncode}\n{r.stdout[:200]}")
    check("built index" in r.stdout, "build prints summary")
    check("file(s)" in r.stdout, "build prints file count")
    check(os.path.exists(idx), "build creates index.json")

    # Verify index structure.
    with io.open(idx, "r", encoding="utf-8") as f:
        index_data = json.load(f)
    check(index_data.get("version") == "1.0", "index has version")
    check("files" in index_data, "index has files list")
    check(len(index_data["files"]) == 2, "index has 2 files",
          f"got {len(index_data.get('files', []))}")
    total_sections = sum(len(f["sections"]) for f in index_data["files"])
    check(total_sections == 4, "index has 4 sections",
          f"got {total_sections}")
    # Each section has tokens.
    all_have_tokens = all(s.get("tokens") for f in index_data["files"]
                          for s in f["sections"])
    check(all_have_tokens, "all sections have tokens")

    # Query mode: find a section by keyword.
    r = run("query", idx, "AUTHORITY-CHECK")
    check(r.returncode == 0, "query exits 0",
          f"exit={r.returncode}\n{r.stdout[:200]}")
    check("abap.md" in r.stdout, "query finds the right file")
    check("Authorization" in r.stdout, "query finds the right section")
    check("match(es)" in r.stdout, "query prints match count")

    # Query mode: no matches.
    r = run("query", idx, "xyznonexistentterm")
    check(r.returncode == 0, "no-match query exits 0")
    check("no matches" in r.stdout, "no-match query prints no matches")

    # Query mode: --top limits results.
    r = run("query", idx, "report", "--top", "1")
    check(r.returncode == 0, "--top 1 exits 0")
    check("showing top 1" in r.stdout, "--top 1 limits results")

    # Query mode: empty query.
    r = run("query", idx, "")
    check(r.returncode == 2, "empty query exits 2")
    check("no searchable" in r.stdout, "empty query names the problem")

    # Query mode: index does not exist.
    r = run("query", os.path.join(tmp, "nope.json"), "test")
    check(r.returncode == 2, "missing index exits 2")
    check("does not exist" in r.stdout, "missing index names the problem")

    # Query mode: corrupt index.
    bad_idx = os.path.join(tmp, "bad.json")
    io.open(bad_idx, "w", encoding="utf-8").write("{not valid json")
    r = run("query", bad_idx, "test")
    check(r.returncode == 2, "corrupt index exits 2")
    check("not parseable" in r.stdout, "corrupt index names the problem")

    # Build mode: missing directory.
    r = run("build", os.path.join(tmp, "nodir"))
    check(r.returncode == 2, "missing dir exits 2")
    check("not a directory" in r.stdout, "missing dir names the problem")

    # Build mode: empty directory.
    empty_dir = os.path.join(tmp, "empty")
    os.makedirs(empty_dir)
    r = run("build", empty_dir)
    check(r.returncode == 2, "empty dir exits 2")
    check("no markdown" in r.stdout, "empty dir names the problem")

    # Build mode: directory with only non-md files.
    nomd_dir = os.path.join(tmp, "nomd")
    os.makedirs(nomd_dir)
    io.open(os.path.join(nomd_dir, "readme.txt"), "w", encoding="utf-8").write("hello")
    r = run("build", nomd_dir)
    check(r.returncode == 2, "no-md dir exits 2")
    check("no markdown" in r.stdout, "no-md dir names the problem")

    # Build mode: file with no sections.
    nosd_dir = os.path.join(tmp, "nosd")
    os.makedirs(nosd_dir)
    write_md(os.path.join(nosd_dir, "plain.md"), "Just plain text, no headings.\n")
    r = run("build", nosd_dir)
    check(r.returncode == 2, "no-sections dir exits 2")
    check("no sections" in r.stdout, "no-sections dir names the problem")

    # Build mode: Chinese content.
    zh_dir = os.path.join(tmp, "zh")
    os.makedirs(zh_dir)
    write_md(os.path.join(zh_dir, "zh.md"),
             "## 程序定位\n\n"
             "该报表解决采购订单的批量导入问题。选择屏区间用于过滤物料号。\n\n"
             "## 风险与改进\n\n"
             "AUTHORITY-CHECK 缺失导致越权访问。建议补上角色检查。\n")
    zh_idx = os.path.join(tmp, "zh_index.json")
    r = run("build", zh_dir, "--output", zh_idx)
    check(r.returncode == 0, "chinese build exits 0",
          f"exit={r.returncode}\n{r.stdout[:200]}")
    # Query Chinese content.
    r = run("query", zh_idx, "AUTHORITY")
    check(r.returncode == 0, "chinese query exits 0")
    check("风险" in r.stdout, "chinese query finds the section with AUTHORITY-CHECK")

    # Build mode: default output path.
    def_dir = os.path.join(tmp, "default")
    os.makedirs(def_dir)
    write_md(os.path.join(def_dir, "test.md"),
             "## Test\n\nSome content about authorization and security.\n")
    r = run("build", def_dir)
    check(r.returncode == 0, "default output exits 0")
    default_idx = os.path.join(def_dir, "index.json")
    check(os.path.exists(default_idx), "default output creates index.json")

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
