"""Escape residue: an escape sequence written out as text in the report's prose.

The sibling of encoding, and the half of it that encoding does not cover.
read_report() refuses a file that does not decode as utf-8, and
encoding.replacement_defects catches a file that decodes but carries U+FFFD.
Neither sees a file that is valid utf-8 and still damaged by intent: the writer
owed one newline and typed the two characters, so the finished report reads as a
rendering fault in its own prose.

One shipped report carried nine of them, all nine the same shape, and it was
otherwise clean -- valid utf-8, six sections, three layers per fence, four
buckets -- so every structural detector passed it. That is the class this exists
for: a report the gate could see everything about and still had no note to make.

--fix does not repair this, on purpose. ln and mm are substitutions with one
right answer, so a mechanical rewrite cannot change meaning. Here the answer is a
line break in a place only the writer knows, and a repair that guessed would have
invented prose. esc exits 1 the way enc does, and the writer makes the edit.

Contract 1.3.12 -> 1.3.13 in 1.1.29.
"""
from checks.contract import ESC_KIND, ESC_SHAPES
from checks.text import TICK, blank_fences, line_of


def _blank_inline(s):
    """Same length as s, with inline backtick spans blanked as well.

    blank_fences blanks code fence bodies only, which is the right scope for a
    rule about prose. TICK is the one definition of an inline span, so it is the
    one to blank with here too: a quoted \\n is the writer naming the escape,
    not shipping it, and quoting an escape is legitimate prose.

    Length-preserving, on purpose, for the same reason as blank_fences: offsets
    survive both blanking passes, so line_of() can still be called on the
    untouched original and the defect points at the line the writer will read.
    """
    out = []
    last = 0
    for m in TICK.finditer(s):
        out.append(s[last:m.start()])
        out.append("\x00" * (m.end() - m.start()))
        last = m.end()
    out.append(s[last:])
    return "".join(out)


def escape_defects(s):
    """(kind, line, detail) for every line of prose carrying escape residue.

    One defect per line, not per match: a line that ships two escapes is one
    slip and should not inflate the defect count. The same convention encoding
    uses for a run of replacement characters, so a run of either reads as one
    event in the report the writer is told to fix.
    """
    prose = blank_fences(s)
    out = []
    for name, rx, blank_spans in ESC_SHAPES:
        text = _blank_inline(prose) if blank_spans else prose
        per_line = {}
        for m in rx.finditer(text):
            per_line.setdefault(line_of(s, m.start()), []).append(m.group(0))
        for ln in sorted(per_line):
            toks = per_line[ln]
            detail = ("report text carries %d literal escape sequence(s) %s -- "
                      "%s; write the character, not its escape"
                      % (len(toks), " ".join(repr(t) for t in toks[:3]), name))
            out.append((ESC_KIND, ln, detail))
    return out
