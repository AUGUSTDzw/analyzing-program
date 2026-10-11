"""docgen and abap_deps_analyzer: the two scripts with no coverage of their own.

Both ship in the release, and neither was touched by the other three suites, so
a regression in either one sailed past every check. This suite pins the parsers
to the behaviour they are meant to have. Writing it found four live defects:

  _find_block_end required the subprogram name after the end keyword
    (`ENDMETHOD foo`). ABAP permits `ENDMETHOD foo.` but never requires it, and
    the shipped sources terminate bare, so nothing matched, every block ran to
    the end of the file, and `end` came back identical for every subprogram.
  _extract_calls read CALL FUNCTION names from [A-Z0-9_], which missed the
    quoted form CALL FUNCTION 'Z_BC_LOG' -- the common one in ABAP.
  _extract_forms grouped USING into the FORM regex with `.*?`, which matched
    empty, so no FORM ever reported a single parameter.
  _extract_tables filtered internal tables with a case-sensitive startswith,
    so `lt_tab` and `ws_data` were reported as database tables.

Run: python tests/test_docgen_deps.py
"""
import io, json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(ROOT))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import docgen  # noqa: E402
from abap_deps_analyzer import ABAPDepsAnalyzer  # noqa: E402

DOC = os.path.join(ROOT, "scripts", "docgen.py")
DEPS = os.path.join(ROOT, "scripts", "abap_deps_analyzer.py")
DEPS_SRC = os.path.join(ROOT, "abaplint-deps", "src")

N_OK = 0
FAILS = []


def check(cond, label, detail=""):
    global N_OK
    if cond:
        N_OK += 1
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f"   {detail}" if detail else ""))
    if not cond:
        FAILS.append(label)


# ---------------------------------------------------------------------------
# A hand-written program. Kept inline on purpose: the fixtures under
# analyzing-programs-workspace are archived runs, and a parser regression is
# only visible against code that is short enough to reason about by hand.
# ---------------------------------------------------------------------------

# Written as a list of lines so the expected anchors come from the list index
# rather than from a re-read of the joined string -- the point of the anchor
# checks is that docgen counts the same lines a reader would.
LINES = [
    "*&report ztest.",
    "CLASS zcl_test DEFINITION",
    "  INHERITING FROM cl_abap_object",
    "  CREATE PUBLIC.",
    "  PUBLIC SECTION.",
    "    METHODS constructor.",
    "    METHODS do_work.",
    "  PROTECTED SECTION.",
    "    DATA lv_cnt TYPE i.",
    "ENDCLASS.",
    "",
    "CLASS zcl_test IMPLEMENTATION.",
    "  METHOD constructor.",
    "    lv_cnt = 1.",
    "  ENDMETHOD.",
    "",
    "  METHOD do_work( EXPORTING iv_a TYPE i ).",
    "    CALL FUNCTION 'Z_BC_LOG'.",
    "    CALL FUNCTION Z_UNQUOTED.",
    "    CALL METHOD lo_obj->do_it( EXPORTING iv_x = 2 ).",
    "    CALL lo_obj->do_it2.",
    "    SELECT * FROM ztf001 INTO TABLE lt_lines.",
    "  ENDMETHOD.",
    "ENDCLASS.",
    "",
    "FORM fill_screen USING p_b TYPE i",
    "  CONTINUE p_c TYPE string.",
    "  WRITE p_b.",
    "ENDFORM.",
    "",
    "FORM bare_form.",
    "  WRITE 1.",
    "ENDFORM.",
    "",
    "FUNCTION ZTEST_FM.",
    "  WRITE 'x'.",
    "ENDFUNCTION.",
    "",
    "START-OF-SELECTION.",
    "  PERFORM fill_screen.",
    "",
    "INITIALIZATION.",
    "  WRITE 'init'.",
]

# Exact line text -> the subprogram that line opens.
OPENER = {
    "METHOD constructor.": "constructor",
    "METHOD do_work( EXPORTING iv_a TYPE i ).": "do_work",
    "FORM fill_screen USING p_b TYPE i": "fill_screen",
    "FORM bare_form.": "bare_form",
    "FUNCTION ZTEST_FM.": "ZTEST_FM",
    "START-OF-SELECTION.": "START-OF-SELECTION",
    "INITIALIZATION.": "INITIALIZATION",
}

PROGRAM = "\n".join(LINES) + "\n"
LINE_OF = {}
for _i, _ln in enumerate(LINES, 1):
    if _ln in OPENER:
        LINE_OF[OPENER[_ln]] = _i


def write_program():
    """Return (tmpdir, path) for PROGRAM, cleaned up by the caller."""
    d = tempfile.mkdtemp(prefix="docgen_test_")
    p = os.path.join(d, "ztest.abap")
    with io.open(p, "w", encoding="utf-8") as fh:
        fh.write(PROGRAM)
    return d, p


def main():
    print("docgen: subprograms")
    print("-" * 72)
    subs = docgen._extract_subprograms(PROGRAM)
    by_name = {s["name"]: s for s in subs}

    check(len(subs) == 7, "all seven blocks are found", f"{len(subs)}")
    check([s["name"] for s in subs] ==
          ["constructor", "do_work", "fill_screen", "bare_form",
           "ZTEST_FM", "START-OF-SELECTION", "INITIALIZATION"],
          "sorted by position, not by discovery order",
          str([s["name"] for s in subs]))
    check(by_name["constructor"]["kind"] == "METHOD"
          and by_name["do_work"]["kind"] == "METHOD",
          "METHOD blocks labelled METHOD")
    check(by_name["fill_screen"]["kind"] == "FORM"
          and by_name["ZTEST_FM"]["kind"] == "FUNCTION",
          "FORM and FUNCTION labelled")
    check(by_name["START-OF-SELECTION"]["kind"] == "START-OF-SELECTION",
          "event blocks keep their keyword as the kind")

    # The definition block `METHODS: constructor.` must not be counted: there
    # is one METHOD constructor, not two.
    check(sum(1 for s in subs if s["name"] == "constructor") == 1,
          "the declaration block is not counted as a subprogram")

    # _find_block_end needed `ENDMETHOD constructor`; ABAP writes `ENDMETHOD.`.
    ends = [s["end"] for s in subs if s["kind"] == "METHOD"]
    check(all(e < len(PROGRAM) for e in ends),
          "every method stops at its own ENDMETHOD, not at end of file",
          str(ends))
    check(len(set(ends)) == len(ends),
          "block ends are distinct, so the ranges do not overlap",
          str(ends))
    check(subs[0]["end"] < subs[1]["start"] or subs[0]["end"] <= subs[1]["end"],
          "the first method does not swallow the second")

    for name in LINE_OF:
        check(by_name[name]["anchor"] == str(LINE_OF[name]),
              f"anchor for {name} is line {LINE_OF[name]}",
              by_name[name]["anchor"])

    # The anchor patterns used `^\s*`, and \s also matches a newline, so a
    # subprogram preceded by a blank line anchored one line early.
    prev_blank = docgen._extract_subprograms(
        "ENDFORM.\n\nFORM f.\n  WRITE 1.\nENDFORM.\n")
    check(prev_blank[0]["anchor"] == "3",
          "a blank line before a subprogram does not move its anchor",
          prev_blank[0]["anchor"])

    print()
    print("docgen: FORM parameters")
    print("-" * 72)
    forms = {f["name"]: f for f in docgen._extract_forms(PROGRAM)}
    check(set(forms) == {"fill_screen", "bare_form"},
          "both FORMs found", str(sorted(forms)))
    check(sorted(forms["fill_screen"]["parameters"]) ==
          ["p_b TYPE i", "p_c TYPE string"],
          "both CONTINUE-separated parameters captured",
          str(forms["fill_screen"]["parameters"]))
    check(forms["bare_form"]["parameters"] == [],
          "a FORM without USING has no parameters")

    two = docgen._extract_forms("FORM a USING x TYPE i.\nENDFORM.\n"
                                "FORM b USING y TYPE i.\nENDFORM.")
    check(two[0]["parameters"] == ["x TYPE i"] and two[1]["parameters"] == ["y TYPE i"],
          "each FORM keeps its own parameter list",
          str([(f["name"], f["parameters"]) for f in two]))

    perf = docgen._extract_forms(
        "FORM f.\n  PERFORM other USING p1 TYPE i.\n  WRITE p1.\nENDFORM.")
    check(perf[0]["parameters"] == [],
          "a PERFORM ... USING in the body is not read as this FORM's parameters",
          str(perf[0]["parameters"]))

    nxt = docgen._extract_forms("FORM a.\n  WRITE 1.\nENDFORM.\n"
                                "FORM b USING y TYPE i.\n  WRITE y.\nENDFORM.")
    check(nxt[0]["parameters"] == [] and nxt[1]["parameters"] == ["y TYPE i"],
          "an empty FORM does not borrow the next FORM's USING clause",
          str([(f["name"], f["parameters"]) for f in nxt]))

    print()
    print("docgen: calls")
    print("-" * 72)
    calls = docgen._extract_calls(PROGRAM)
    names = {c["name"] for c in calls}
    check("Z_BC_LOG" in names, "quoted CALL FUNCTION found", str(sorted(names)))
    check("Z_UNQUOTED" in names, "unquoted CALL FUNCTION found")
    check("lo_obj->do_it" in names and "->do_it" in names,
          "CALL METHOD and ->method calls found")
    check(all(c["type"] in ("FUNCTION", "METHOD") for c in calls),
          "every call is typed")
    check([c["position"] for c in calls] == sorted(c["position"] for c in calls),
          "calls ordered by position")

    print()
    print("docgen: tables")
    print("-" * 72)
    tables = [t["name"] for t in docgen._extract_tables(PROGRAM)]
    check("ztf001" in tables, "SELECT ... FROM table reported", str(tables))
    check("lt_lines" not in tables, "LT_ internal table excluded", str(tables))
    for prefix in ("lt_tab", "ws_data", "gt_rows", "LT_TAB", "WS_DATA"):
        t = [x["name"] for x in
             docgen._extract_tables(f"SELECT * FROM zt001 INTO TABLE {prefix}.")]
        check(t == ["zt001"], f"{prefix} is not a database table", str(t))

    print()
    print("docgen: classes")
    print("-" * 72)
    classes = docgen._extract_classes(PROGRAM)
    check(len(classes) == 1 and classes[0]["name"] == "zcl_test",
          "the class is found")
    check(sorted(classes[0]["methods"]) == ["constructor", "do_work"],
          "its methods are listed", str(classes[0]["methods"]))
    check(classes[0]["inherits"] == "cl_abap_object",
          "inheritance resolved", str(classes[0]["inherits"]))
    check("lv_cnt" in classes[0]["class_data"],
          "class data collected", str(classes[0]["class_data"]))

    print()
    print("docgen: empty input")
    print("-" * 72)
    for fn, label in ((docgen._extract_subprograms, "subprograms"),
                      (docgen._extract_classes, "classes"),
                      (docgen._extract_forms, "forms"),
                      (docgen._extract_tables, "tables"),
                      (docgen._extract_calls, "calls"),
                      (docgen._extract_events, "events")):
        check(fn("") == [], f"{label} on an empty source")

    print()
    print("docgen: command line")
    print("-" * 72)
    tmp, prog = write_program()
    try:
        r = subprocess.run([sys.executable, DOC, prog, "--type", "onboarding",
                            "--format", "json"],
                           capture_output=True, encoding="utf-8")
        check(r.returncode == 0, "onboarding/json exits 0", str(r.returncode))
        out = os.path.join(tmp, "ztest.onboarding.json")
        check(os.path.exists(out), "the document is written to a file, not stdout")
        doc = json.load(io.open(out, encoding="utf-8"))
        check(doc["document_type"] == "onboarding", "document_type recorded")
        check(doc["total_lines"] == len(PROGRAM.splitlines()),
              "total_lines matches the source")
        check(len(doc["subprograms"]) == 7,
              "subprograms carried through to JSON",
              str(len(doc["subprograms"])))
        check(len(doc["events"]) == 2, "events carried through",
              str(len(doc["events"])))

        r = subprocess.run([sys.executable, DOC, prog, "--type", "onboarding",
                            "--format", "markdown", "--validate"],
                           capture_output=True, encoding="utf-8")
        check(r.returncode == 0 and "PASS" in r.stdout,
              "--validate accepts a generated document", r.stdout.strip()[:60])

        r = subprocess.run([sys.executable, DOC,
                            os.path.join(tmp, "no_such.abap")],
                           capture_output=True, encoding="utf-8")
        check(r.returncode == 2 and r.stderr.startswith("error  "),
              "a missing source refuses with exit 2",
              f"rc={r.returncode} {r.stderr.strip()[:50]}")

        r = subprocess.run([sys.executable, DOC, prog, "--type", "class",
                            "--format", "html"],
                           capture_output=True, encoding="utf-8")
        check(os.path.exists(os.path.join(tmp, "ztest.class.html")),
              "html is emitted")
        check(not os.path.exists(os.path.join(tmp, "ztest.class.md")),
              "html does not leave a markdown copy behind")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    print("abap_deps_analyzer: standard library index")
    print("-" * 72)
    check(os.path.isdir(DEPS_SRC), "the shipped abaplint-deps are present")
    analyzer = ABAPDepsAnalyzer(DEPS_SRC)
    check(len(analyzer.standard_objects) >= 100,
          "the index is populated", f"{len(analyzer.standard_objects)} objects")
    check({"class", "interface", "program"} <=
          {o.type for o in analyzer.standard_objects.values()},
          "all three object kinds indexed",
          str(sorted({o.type for o in analyzer.standard_objects.values()})))
    check(all(k == k.upper() for k in analyzer.standard_objects),
          "object names are normalised to upper case")

    print()
    print("abap_deps_analyzer: analysis shape")
    print("-" * 72)
    src_path = os.path.join(REPO, "Test-source", "zvend.abap")
    check(os.path.exists(src_path), "the probe source is present")
    result = analyzer.analyze(src_path)
    check(sorted(result) == ["dependencies", "issues", "summary", "unused_code"],
          "the result carries the documented keys", str(sorted(result)))
    s = result["summary"]
    check(sorted(s) == ["errors", "total_dependencies", "total_issues",
                        "total_unused_code", "unique_targets", "warnings"],
          "the summary carries the documented counters", str(sorted(s)))
    check(s["total_issues"] == len(result["issues"]),
          "summary counts the issues it returns")
    check(s["errors"] == 0,
          "zvend.abap raises no errors", str(s["errors"]))

    print()
    print("abap_deps_analyzer: command line")
    print("-" * 72)
    neutral = tempfile.mkdtemp(prefix="deps_neutral_")
    try:
        # A real install is never run from the skill directory, so this is the
        # case that matters: the default --deps value does not exist relative to
        # the working directory, and resolution has to fall back to the copy
        # shipped beside the script.
        r = subprocess.run([sys.executable, DEPS, src_path],
                           capture_output=True, encoding="utf-8", cwd=neutral)
        check(r.returncode == 0, "runs from a working directory outside the skill",
              f"rc={r.returncode} {r.stderr.strip()[:80]}")
        check(any("184" in ln for ln in r.stdout.splitlines()),
              "the shipped library is indexed from that directory")

        r = subprocess.run([sys.executable, DEPS, src_path,
                            "--deps", "no/such/deps", "--format", "json"],
                           capture_output=True, encoding="utf-8", cwd=neutral)
        check(r.returncode == 0,
              "a wrong --deps value falls back instead of failing",
              f"rc={r.returncode}")
        # The analyzer prints its indexing progress before the document, so the
        # document is the JSON object that starts at the first '{'. Slicing at
        # the brace keeps this honest about what the CLI actually emits.
        doc = json.loads(r.stdout[r.stdout.index("{"):])
        check(doc["summary"]["errors"] == 0,
              "json mode carries the summary through",
              str(doc["summary"]))

        r = subprocess.run([sys.executable, DEPS,
                            os.path.join(neutral, "no_such.abap")],
                           capture_output=True, encoding="utf-8", cwd=neutral)
        check(r.returncode == 1 and r.stdout.startswith("正在索引标准库"),
              "a missing source reports after indexing, exit 1",
              f"rc={r.returncode}")
    finally:
        shutil.rmtree(neutral, ignore_errors=True)

    print()
    print("-" * 72)
    print(f"{N_OK} checks passed, {len(FAILS)} failed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
