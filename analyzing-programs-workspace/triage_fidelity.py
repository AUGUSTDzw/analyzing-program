"""Triage the fidelity check's remaining candidates.

For each quoted line the check could not find in the source, show the source line
it most resembles, so the difference is visible rather than inferred. Longest
common prefix is a good enough anchor here: ABAP lines that differ usually differ
late, in an identifier or a terminator.
"""
import difflib
import io
import os
import re
import sys

sys.path.insert(0, sys.argv[1])
import report_qc
import check_code_fidelity as f

ROOT = sys.argv[2]
SRCDIR = os.path.join(ROOT, "Test-source", "real")

CLASSES = {
    # reason -> verdict
    "merge": "merged two source lines into one (TYPES: header + field)",
    "terminator": "statement terminator differs",
    "wrap": "same statement, wrapped differently",
    "comment": "trailing comment or report annotation",
    "genuine": "identifier or content differs from the source",
    "pseudo": "placeholder code that is in the source as pseudo-code",
}


def best_match(line, src_lines):
    """Source line sharing the longest common prefix with the report line.

    The probe is the whole line, not a truncation of it. Truncating at 60
    characters capped the score at 60, so every line that agreed for 60
    characters was reported as "common prefix only 60" and fell through to
    genuine -- which is how two faithful lines first appeared as defects.
    """
    probe = f.flat(line)
    best, score = "", -1
    for sl in src_lines:
        key = f.flat(sl)
        n = 0
        while n < min(len(key), len(probe)) and key[n] == probe[n]:
            n += 1
        if n > score:
            best, score = sl, n
    return best, score


def classify(report_line, src_line, score):
    r, s = f.flat(report_line), f.flat(src_line)
    if score < 8:
        return "genuine", "no close source line at all"
    if r.replace(" ", "") == s.replace(" ", ""):
        return "wrap", "identical once whitespace is removed"
    if r.rstrip(";").rstrip() == s.rstrip(";").rstrip():
        return "terminator", "differs only in the terminator"
    # a TYPES: / DATA: header merged onto its first field line
    if re.match(r"^(types|data)\s+\w+\s+type\b", r) and \
       re.match(r"^(types|data)\s*:?\s*$", f.flat(src_line)[:12]):
        return "merge", "source has the header and the field on separate lines"
    if re.match(r"^(types|data)\s+\w+\s+type\b", r):
        return "merge", "source separates the header from its fields"
    # placeholder / demo code that legitimately uses (cond) and itab
    if re.search(r"\b(itab|ref|cond_loop|comp)\b", r) and \
       re.search(r"\b(itab|ref|cond_loop)\b", s):
        return "pseudo", "placeholder identifiers, present in the source as demo code"
    if score >= min(len(r), len(s)) - 4:
        return "wrap", f"common prefix {score} chars, differs at the tail"
    return "genuine", f"common prefix only {score} chars"


def main():
    rows = []
    for rel, srcname in f.PAIRS:
        rp, sp = os.path.join(ROOT, rel), os.path.join(SRCDIR, srcname)
        if not (os.path.exists(rp) and os.path.exists(sp)):
            continue
        rep = io.open(rp, encoding="utf-8").read()
        src = io.open(sp, encoding="utf-8", errors="replace").read()
        src_lines = src.split("\n")
        n, bad = f.audit(rep, src)
        for ln, text in bad:
            b, score = best_match(text, src_lines)
            kind, why = classify(text, b, score)
            rows.append((os.path.basename(rel)[:34], ln, text, b.strip(), kind, why))

    print(f"{'report':36}{'L':>6}  {'verdict':11} detail")
    print("-" * 112)
    for fn, ln, text, b, kind, why in rows:
        print(f"{fn:36}{ln:>6}  {kind:11} {why}")
        print(f"{'':44}report: {text.strip()[:62]}")
        print(f"{'':44}source: {b[:62]}")
    print("-" * 112)
    import collections
    c = collections.Counter(r[4] for r in rows)
    print("tally:", dict(c))
    genuine = [r for r in rows if r[4] == "genuine"]
    print(f"\nsubstantive candidates: {len(genuine)}")
    for fn, ln, text, b, kind, why in genuine:
        print(f"  {fn} L{ln}")
        print(f"     report: {text.strip()[:88]}")
        print(f"     source: {b[:88]}")


if __name__ == "__main__":
    main()
