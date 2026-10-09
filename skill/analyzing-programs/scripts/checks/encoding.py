"""Encoding faults the structural checks cannot see.

One U+FFFD in prose passes every other rule: the report still has six sections,
still three layers per fence, still four buckets. It reached a finished report
once already -- exp-1.0.9/with_skill/run3.md carried two adjacent U+FFFD from a
truncated multi-byte character and went unnoticed for a whole round.

read_report() refuses a report that is not valid utf-8, which catches the file
being wrong. This catches the file being valid utf-8 and still damaged, which is
what a truncated character decodes to.
"""
from checks.contract import CONTRACT


def replacement_defects(s):
    """(kind, line, detail) for every U+FFFD in the report.

    One defect per line, not per character: a run of replacement chars is one
    truncation event and should not inflate the defect count.
    """
    ch = CONTRACT["encoding"]["replacement_char"]
    out = []
    for i, line in enumerate(s.split("\n"), 1):
        if ch in line:
            n = line.count(ch)
            detail = ("report text carries %d replacement character(s) (U+FFFD) "
                      "-- a multi-byte character was truncated on save"
                      % n)
            out.append(("enc", i, detail))
    return out
