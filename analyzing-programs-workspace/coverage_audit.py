#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Inventory which ABAP constructs the eval fixtures actually exercise,
then list SKILL.md's claimed scope so gaps are visible rather than assumed."""
import io, json, os, re

REPO = r"D:\Workspace\Skills\analyzing-programs"
EV = os.path.join(REPO, "evals")

# construct -> regex. Anything SKILL.md promises but nothing exercises is a gap.
FEATURES = {
    "CLASS-POOL":            r"CLASS-POOL",
    "FUNCTION-POOL":         r"FUNCTION-POOL",
    "REUSE_ALV_*_DISPLAY":   r"REUSE_ALV_\w+_DISPLAY",
    "CL_GUI_ALV_GRID":       r"CL_GUI_ALV_GRID",
    "CL_SALV_TABLE":         r"CL_SALV_",
    "INTERFACES / SET HANDLER": r"\bINTERFACES\b|SET\s+HANDLER",
    "INHERITING / super->":  r"\bINHERITING\b|super->",
    "CLASS-EVENTS":          r"\bCLASS-EVENTS\b",
    "CALL SCREEN + MODULE":  r"CALL\s+SCREEN|^\s*MODULE\s+\w+\s+(OUTPUT|INPUT)",
    "AT SELECTION-SCREEN":   r"AT\s+SELECTION-SCREEN",
    # dynpro flow logic: PROCESS BEFORE OUTPUT / PROCESS AFTER INPUT, and
    # MODULE <name> OUTPUT|INPUT. Do NOT require a field name after OUTPUT —
    # `MODULE status_0100 OUTPUT.` is the normal form.
    "Dialog / Dynpro":       r"PROCESS\s+(BEFORE\s+OUTPUT|AFTER\s+INPUT)"
                             r"|^\s*MODULE\s+\w+\s+(OUTPUT|INPUT)",
    # Both a PBO and a PAI module present (the normal dialog-program shape).
    # Two independent alternatives rather than a DOTALL range, which the
    # non-DOTALL compile flags below would never match.
    "MODULE PBO + PAI":      r"MODULE\s+\w+\s+OUTPUT\b"
                             r"(?=[\s\S]*?MODULE\s+\w+\s+INPUT\b)",
    "Exception classes CX_": r"\bCX_\w+",
    "RAISING / TRY-CATCH":   r"\bRAISING\b|\bTRY\b|\bCATCH\b",
    "BAPI call":             r"CALL FUNCTION 'BAPI_",
    "RFC DESTINATION":       r"\bDESTINATION\b",
    "Commit / LUW":          r"COMMIT WORK|BAPI_TRANSACTION_COMMIT",
    "Update task / background": r"UPDATE TASK|JOB|BACKGROUND",
    "Selection screen":      r"SELECTION-SCREEN|SELECT-OPTIONS|PARAMETERS",
    "FOR ALL ENTRIES":       r"FOR\s+ALL\s+ENTRIES",
    "String templates / inline": r"\|[^|]*\{|DATA\(|VALUE\s+#\(",
    "XML / JSON / HTTP":     r"\bJSON\b|\bXML\b|CL_HTTP_CLIENT|RESTFUL",
    "Authorization check":   r"AUTHORITY-CHECK",
    "Message class":         r"MESSAGE\s+ID\s+'",
    # Inline declarations and string templates are the two modern syntax forms
    # worth tracking separately from the catch-all "String templates / inline"
    # entry above, because a regression in either would hide inside it.
    # Both forms are inline declarations: `DATA(lv_x) = ...` as a standalone
# statement, and `... INTO DATA(ls_row)` inside a loop body. Match either.
    "Inline declaration DATA(": r"\bDATA\s*\(\s*\w+\s*\)\s*(=|,|\)|\s)",
    # `DATA(lv_x) = <expr>` — the declaration is on the LEFT of the assignment.
    "Inline decl. as statement": r"^\s*DATA\s*\(\s*\w+\s*\)\s*=",
    "String template |{}":   r"\|[^\n]*\{\s*[a-z_]",
    "Locking (ENQUEUE)":     r"\bENQUEUE_\w+|\bDEQUEUE_\w+",
    "Number range object":   r"NUMBER_GET|NUMBER_RANGE|NUMBER_CHECK",
    "Application layer i_bap": r"CALL FUNCTION 'BAPI_|FUNCTION\s+'Z?",
    "CDSv consumer (ABAP SQL)": r"FROM\s+[ZYI]_[A-Z0-9_]+",
    "CDSv DDL source":       r"DEFINE\s+(ROOT\s+)?VIEW\s+ENTITY",
    "HTTP client":           r"\bCL_HTTP_CLIENT\b|\bIF_HTTP_CLIENT\b|\bIF_HTTP_RESPONSE\b",
    "JSON assembly":         r"\|[^\n]*\"[a-zA-Z_]+\":",
    "CLASS-EVENTS publish":  r"\bCLASS-EVENTS\b",
    "RAISE EVENT":           r"\bRAISE\s+EVENT\b",
    "FOR EVENT handler":     r"FOR\s+EVENT\s+\w+\s+OF",
    "MESSAGE ID (correct)":  r"MESSAGE\s+ID\s+'",
    "SY-BATCH branching":    r"\bSY-BATCH\b",
    "ABAP SQL escape @":     r"\bINTO\s+TABLE\s+@\w+|\bFROM\s+\w+\s+WHERE\s+\w+\s+IN\s+@",
    "Table expressions VALUE": r"VALUE\s+#\(",
}

ev = json.load(io.open(os.path.join(EV, "evals.json"), encoding="utf-8"))
print(f"{'eval':6} {'name':32} constructs exercised")
print("-" * 100)
covered = {k: set() for k in FEATURES}
for e in ev["evals"]:
    src = "".join(io.open(os.path.join(EV, f), encoding="utf-8").read()
                  for f in e["files"])
    # re.S so cross-line lookaheads in a few features can span newlines.
    hits = [k for k, p in FEATURES.items() if re.search(p, src, re.M | re.S | re.I)]
    for k in hits:
        covered[k].add(e["id"])
    print(f"eval-{e['id']:<2} {e['name']:32} {', '.join(hits) if hits else '(none)'}")

print("-" * 100)
print("\nCONSTRUCT COVERAGE ACROSS THE EVAL SET")
print("-" * 100)
untested = []
for k in FEATURES:
    ids = sorted(covered[k])
    if ids:
        print(f"  COVERED    {k:30} evals {ids}")
    else:
        untested.append(k)
        print(f"  ** NOT TESTED ** {k:30} —")

print("-" * 100)
print(f"\n{len(untested)} of {len(FEATURES)} constructs never exercised:")
for k in untested:
    print(f"  - {k}")

s = io.open(os.path.join(REPO, "skill", "analyzing-programs", "SKILL.md"),
            encoding="utf-8").read()
m = re.search(r"description:(.*?)\n---", s, re.S)
print("\nSKILL.md claims to handle:")
for tok in re.findall(r"[^（）()]+", m.group(1)):
    t = tok.strip()
    if any(w in t for w in ("报表", "FORM", "事件块", "CLAS", "类", "函数组", "ALV")):
        print(f"  · {t[:70]}")