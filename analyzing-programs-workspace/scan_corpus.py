"""Corrected construct scan.

The earlier probe used `FOR SELECT|ALL FIELDS|COUNT|...` as the AMDP signature,
which is the *body* of a SQLScript method, not its declaration. AMDP methods are
declared `... BY DATABASE PROCEDURE FOR HDB LANGUAGE SQLSCRIPT`. The old regex
scored 0/19 even with an AMDP file in the corpus, so its "AMDP is missing"
conclusion was an artifact of the probe, not a fact about the corpus.
"""
import io, os, re, sys

d = sys.argv[1]

PROBES = {
    "AMDP proc/func":  r"BY\s+DATABASE\s+(?:PROCEDURE|FUNCTION)",
    "  └ SQLScript":    r"LANGUAGE\s+SQLSCRIPT",
    "  └ USING clause": r"BY\s+DATABASE\s+PROCEDURE[^.]{0,200}?\bUSING\b",
    "CDS view entity":  r"define\s+view\s+entity",
    "RAP side effect":  r"\bside\s+effects?\b",
    "BADI impl class":  r"^\s*CLASS\s+\w+\s+IMPLEMENTATION\s*$",
    "CLASS-POOL":       r"CLASS-POOL",
    "FUNCTION module":  r"^\s*FUNCTION\s+\w+\s*\.",
    "dynamic SQL":      r"EXECUTE\s+IMMEDIATE|EXECUTE\s+STATEMENT",
    "obsolete COMPUTE": r"^\s*COMPUTE\s+\w+\s*=",
    "obsolete MOVE TO": r"^\s*MOVE\s+TO\s+\w+\s*=",
    "obsolete ADD TO":  r"^\s*ADD\s+TO\s+\w+\s*=",
    "obsolete SUBTRACT": r"^\s*SUBTRACT\s+FROM\s+\w+\s*=",
    "PBO/PAI module":   r"^\s*MODULE\s+\w+\s+(?:OUTPUT|INPUT)",
    "PERFORM ON COMMIT": r"PERFORM\s+\w+\s+ON\s+(?:COMMIT|ROLLBACK)",
    "ENQUEUE":          r"\bENQUEUE_\w+",
    "UPDATE TASK":      r"UPDATE\s+TASK\s+\w+|ON\s+COMMIT\s+ROLLBACK",
    "RFC / DESTINATION": r"\bDESTINATION\b|CALL\s+FUNCTION\s+'\w+'\s+DESTINATION",
    "CL_HTTP_CLIENT":   r"\bCL_HTTP_CLIENT\b|\bIF_HTTP_CLIENT\b",
    "CLASS-EVENTS":     r"\bCLASS-EVENTS\b",
    "RAISE EVENT":      r"\bRAISE\s+EVENT\b",
    "STRING TEMPLATE":  r"\|[^|\n]*\{",
    "inline DATA()":    r"\bDATA\s*\(",
    "VALUE #()":        r"VALUE\s+#\(",
    "REDUCE":           r"\bREDUCE\s+\w*\s*\(",
    "FILTER":           r"\bFILTER\s+\w*\s*\(",
    "FOR ALL ENTRIES":  r"FOR\s+ALL\s+ENTRIES",
    "FIELD-SYMBOL":     r"FIELD-SYMBOL",
    "FORM ... TABLES":  r"^\s*TABLES\s+\w+",
    "EXIT/CONTINUE":    r"\bEXIT\b|\bCONTINUE\b",
    "authorization":    r"AUTHORITY-CHECK",
    "MESSAGE class":    r"MESSAGE\s+ID\s+'",
    "lock object":      r"\bDEQUEUE_\w+",
    "ASSERT":           r"^\s*ASSERT\b",
    "obsolete RANGES":  r"^\s*RANGES\s+\w+",
}

files = [f for f in os.listdir(d) if f.endswith((".abap", ".asddls", ".asbdef"))]
rows = {}
for name, pat in PROBES.items():
    rx = re.compile(pat, re.M | re.I)
    rows[name] = [1 if rx.search(io.open(os.path.join(d, f), encoding="utf-8",
                                           errors="replace").read()) else 0
                  for f in files]

print(f"{len(files)} files in {d}\n")
print(f"{'construct':22s}{'files':>7}   where")
print("-" * 78)
for name, hits in sorted(rows.items(), key=lambda x: -sum(x[1])):
    n = sum(hits)
    where = [files[i][:26] for i, h in enumerate(hits) if h][:2]
    print(f"{name:22s}{n:>4}/{len(files)}   {', '.join(where)}")
print("-" * 78)
zero = [n for n, h in rows.items() if sum(h) == 0]
print("STILL ABSENT from the whole corpus:")
for z in zero:
    print("   -", z)
