#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Self-contained checks for scripts/dedup.py.

    python tests/test_dedup.py

Builds markdown fixtures with known token overlap in a temp directory and
runs dedup.py against each. Verifies the exit-code discipline (0 pass, 1
duplicates found, 2 refused), the threshold boundary, cross-file catalog
mode, and that sections below the token floor are skipped.

Encoding is forced because the default Windows console breaks this file in
two distinct ways: a child that encoded as cp936 raised UnicodeDecodeError,
and printing Chinese section headings to a cp936 stdout raised
UnicodeEncodeError. So the child gets PYTHONIOENCODING and this process
reconfigures its own streams.
"""
import io
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
SCRIPT = os.path.join(SKILL, "scripts", "dedup.py")

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


def unique_doc():
    """Two sections that share no vocabulary."""
    return (
        "## Section One\n\n"
        "The program reads material master data from table MARA and writes "
        "it to a sorted internal table using FOR ALL ENTRIES.\n\n"
        "## Section Two\n\n"
        "Authorization is enforced through AUTHORITY-CHECK before any "
        "SELECT executes. The role profile is checked against the "
        "user's role list at session start.\n"
    )


def duplicate_doc():
    """Two sections that say almost the same thing."""
    return (
        "## Section One\n\n"
        "The program reads material master data from table MARA using FOR "
        "ALL ENTRIES and writes it to a sorted internal table. The "
        "authorization is enforced through AUTHORITY-CHECK before any "
        "SELECT executes.\n\n"
        "## Section Two\n\n"
        "Material master data is read from the MARA table using FOR ALL "
        "ENTRIES and written to a sorted internal table. AUTHORITY-CHECK "
        "enforces authorization before any SELECT executes.\n"
    )


def chinese_doc():
    """Two Chinese sections with heavy overlap."""
    return (
        "## 第一节\n\n"
        "程序从 MARA 表读取物料主数据，使用 FOR ALL ENTRIES 写入排序内部表。"
        "授权通过 AUTHORITY-CHECK 在任何 SELECT 执行前强制执行。\n\n"
        "## 第二节\n\n"
        "从 MARA 表读取物料主数据，FOR ALL ENTRIES 写入排序内部表。"
        "AUTHORITY-CHECK 在 SELECT 前执行授权检查。\n"
    )


def main():
    tmp = tempfile.mkdtemp()
    print("dedup.py")
    print("-" * 72)
    check(os.path.exists(SCRIPT), "scripts/dedup.py present")

    # Happy path: unique document, no duplicates.
    good = os.path.join(tmp, "unique.md")
    io.open(good, "w", encoding="utf-8").write(unique_doc())
    r = run(good)
    check(r.returncode == 0, "unique document exits 0",
          f"exit={r.returncode}\n{r.stdout[:200]}")
    check("PASS" in r.stdout, "unique document prints PASS")

    # Refusal: file does not exist.
    r = run(os.path.join(tmp, "nope.md"))
    check(r.returncode == 2, "missing file exits 2")
    check(r.stdout.startswith("error"), "missing file prints error first")

    # Refusal: directory path given without --catalog.
    r = run(tmp)
    check(r.returncode == 2, "directory path exits 2",
          f"exit={r.returncode}\n{r.stdout[:200]}")
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

    # Refusal: bad threshold.
    r = run(good, "--threshold", "1.5")
    check(r.returncode == 2, "threshold > 1 exits 2")
    check("threshold" in r.stdout, "bad threshold names the problem")

    # Refusal: negative threshold.
    r = run(good, "--threshold", "-0.1")
    check(r.returncode == 2, "threshold < 0 exits 2")

    # Refusal: min-tokens < 1.
    r = run(good, "--min-tokens", "0")
    check(r.returncode == 2, "min-tokens < 1 exits 2")

    # Duplicate detection: same English document.
    dup = os.path.join(tmp, "dup.md")
    io.open(dup, "w", encoding="utf-8").write(duplicate_doc())
    r = run(dup, "--min-tokens", "5")
    check(r.returncode == 1, "duplicate document exits 1",
          f"exit={r.returncode}\n{r.stdout[:200]}")
    check("FAIL" in r.stdout, "duplicate document prints FAIL")
    check("duplicate pair" in r.stdout, "duplicate document names the count")
    # The score line should be high.
    check(any(x.startswith("  0.") for x in r.stdout.split("\n")),
          "duplicate document prints a similarity score")

    # Threshold boundary: threshold 0 finds everything, threshold 1 finds nothing.
    r = run(dup, "--threshold", "0", "--min-tokens", "5")
    check(r.returncode == 1, "threshold 0 finds the pair", f"exit={r.returncode}")
    r = run(dup, "--threshold", "1", "--min-tokens", "5")
    check(r.returncode == 0, "threshold 1 finds nothing", f"exit={r.returncode}")
    check("PASS" in r.stdout, "threshold 1 prints PASS")

    # Chinese duplication.
    zh = os.path.join(tmp, "zh.md")
    io.open(zh, "w", encoding="utf-8").write(chinese_doc())
    r = run(zh)
    check(r.returncode == 1, "chinese duplicate exits 1",
          f"exit={r.returncode}")
    check("FAIL" in r.stdout, "chinese duplicate prints FAIL")

    # Chinese uniqueness: different topics.
    zh_unique = os.path.join(tmp, "zh_unique.md")
    zh_unique_doc = (
        "## 程序定位\n\n"
        "该报表解决采购订单的批量导入问题。选择屏区间用于过滤物料号。\n\n"
        "## 风险与改进\n\n"
        "AUTHORITY-CHECK 缺失导致越权访问。建议补上角色检查。\n"
    )
    io.open(zh_unique, "w", encoding="utf-8").write(zh_unique_doc)
    r = run(zh_unique)
    check(r.returncode == 0, "chinese unique exits 0",
          f"exit={r.returncode}\n{r.stdout[:200]}")

    # Section below token floor is skipped, so no pair is reported.
    short = os.path.join(tmp, "short.md")
    short_doc = (
        "## One\n\nShort.\n\n## Two\n\nAlso short.\n"
    )
    io.open(short, "w", encoding="utf-8").write(short_doc)
    r = run(short, "--min-tokens", "5")
    check(r.returncode == 0, "short sections below floor exit 0",
          f"exit={r.returncode}")
    check("PASS" in r.stdout, "short sections print PASS")

    # --catalog: cross-file duplicates.
    cat = os.path.join(tmp, "cat")
    os.makedirs(cat)
    io.open(os.path.join(cat, "a.md"), "w", encoding="utf-8").write(
        "## One\n\n"
        "Program reads material master data from MARA using FOR ALL "
        "ENTRIES and writes to a sorted internal table. AUTHORITY-CHECK "
        "enforces authorization before SELECT.\n")
    io.open(os.path.join(cat, "b.md"), "w", encoding="utf-8").write(
        "## Two\n\n"
        "Material master is read from MARA via FOR ALL ENTRIES into a "
        "sorted internal table. AUTHORITY-CHECK enforces authorization "
        "before any SELECT.\n")
    r = run(cat, "--catalog", "--min-tokens", "5")
    check(r.returncode == 1, "cross-file duplicate exits 1",
          f"exit={r.returncode}\n{r.stdout[:300]}")
    check("FAIL" in r.stdout, "cross-file duplicate prints FAIL")
    check("a.md" in r.stdout and "b.md" in r.stdout,
          "cross-file duplicate names both files")

    # --catalog: unique files.
    cat2 = os.path.join(tmp, "cat2")
    os.makedirs(cat2)
    io.open(os.path.join(cat2, "a.md"), "w", encoding="utf-8").write(
        "## One\n\n"
        "Program reads MARA for material master data with FOR ALL ENTRIES.\n")
    io.open(os.path.join(cat2, "b.md"), "w", encoding="utf-8").write(
        "## Two\n\n"
        "Authorization through AUTHORITY-CHECK before SELECT execution.\n")
    r = run(cat2, "--catalog")
    check(r.returncode == 0, "cross-file unique exits 0",
          f"exit={r.returncode}")

    # --catalog: empty directory refuses.
    cat3 = os.path.join(tmp, "cat3")
    os.makedirs(cat3)
    r = run(cat3, "--catalog")
    check(r.returncode == 2, "empty catalog directory exits 2",
          f"exit={r.returncode}")
    check("no markdown" in r.stdout, "empty catalog names the problem")

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
