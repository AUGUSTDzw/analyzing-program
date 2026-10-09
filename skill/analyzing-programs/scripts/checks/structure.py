"""Structural rules: six sections, three layers, fences, Mermaid labels,
location labels, and the priority buckets in section five.

`check(s)` returns a list of (kind, line, detail). Empty means clean. The
signature and every kind string are unchanged from the single-file gate; the
1.1.0 change is only that it lives here.
"""
import re

from checks.contract import (A8_GAP, BUCKETS, CONTRACT, DIAGRAM_LANG, LAYERS,
                             LINE_NUM, PSEC_RE, ROW, SEC_RE, _NEXT_SEC_RE)
from checks.encoding import replacement_defects
from checks.text import (TICK, TAG, blank_fences, fence_defects, fence_spans,
                           layer_bodies, line_of, mermaid_labels, mm_violation,
                           source_blocks)

SECTIONS_EXACTLY_ONCE = CONTRACT.get("sections_exactly_once", False)
LAYERS_DISTINCT = CONTRACT["layers"].get("distinct", False)

# Same reason as the lists in contract.py and text.py: without one, `import *`
# into report_qc.py hands every name above to that module as well -- and a
# detector added there could then reach for re or TICK and resolve it through
# this module, working in tests and failing on a system where something else
# owns the name. An explicit list turns a silent resolution into a NameError at
# import.
__all__ = ["check"]


# ------------------------------------------------------------------- checking

def check(s):
    """Return a list of (kind, line, detail). Empty means clean."""
    bad = []

    present = sum(1 for rx, _ in SEC_RE if rx.search(s))
    if present < len(SEC_RE):
        missing = [sid for rx, sid in SEC_RE if not rx.search(s)]
        bad.append(("sec", 0, f"missing section(s): {', '.join(missing)}"))
    elif SECTIONS_EXACTLY_ONCE:
        for rx, sid in SEC_RE:
            n = len(rx.findall(s))
            if n > 1:
                bad.append(("sec-dup", line_of(s, rx.search(s).end()),
                            "section %s appears %d times" % (sid, n)))

    for st, end, gap in source_blocks(s):
        miss = [l for l in LAYERS if l not in gap]
        if not miss:
            if LAYERS_DISTINCT:
                bodies = layer_bodies(gap)
                if len(bodies) == len(LAYERS) and len(set(bodies.values())) == 1:
                    bad.append(("layer-same", line_of(s, st),
                                "all three layers carry the same text: %r"
                                % next(iter(bodies.values()))[:40]))
            continue
        ln = line_of(s, st)
        kind = "A8-cc" if len(gap.strip()) <= A8_GAP else "A8-pt"
        bad.append((kind, ln,
                    "no prose at all before the next block" if kind == "A8-cc"
                    else "prose present, missing label(s): " + " ".join(miss)))

    bad.extend(fence_defects(s))

    for st, bs, be, _en, lang in fence_spans(s):
        if lang != DIAGRAM_LANG.lower():
            continue
        base = line_of(s, st)
        blk = s[bs:be]
        for lab, off in mermaid_labels(blk):
            if not mm_violation(lab):
                continue
            clean = TAG.sub("", lab)
            bad.append(("mm", base + blk[:off].count("\n"),
                        "Mermaid label holds a bare < > or #: "
                        + repr(clean.strip()[:40])))

    # A real line number here is what the gate owes the writer: reporting 0
    # rendered as "document" and sent them hunting the whole file for a span
    # they could have found in one jump.
    for m in TICK.finditer(blank_fences(s)):
        sp = m.group(1)
        if LINE_NUM.search(sp):
            bad.append(("ln", line_of(s, m.start()),
                        f"location label cites a line number: {sp[:40]!r}"))

    m5 = PSEC_RE.search(s)
    i = m5.start() if m5 else -1
    if i >= 0:
        m6 = _NEXT_SEC_RE.search(s, i + 1) if _NEXT_SEC_RE else None
        j = m6.start() if m6 else len(s)
        sec5 = s[i:j]
    else:
        sec5 = ""
    prows = len(ROW.findall(sec5))
    if prows == 0:
        tbl = [l for l in sec5.split("\n") if l.startswith("|")
               and not set(l) <= set("|- ")]
        prows = max(0, len(tbl) - 1)
    if prows == 0:
        prows = len(re.findall(r"^\s*\d+\.\s+\*\*", sec5, re.M))
    if prows == 0:
        bad.append(("prow", line_of(s, i) if i >= 0 else 0,
                    "section 五 has no problem rows"))
    miss_b = [b for b in BUCKETS if b not in sec5]
    if miss_b:
        bad.append(("buck", line_of(s, i) if i >= 0 else 0,
                    "section 五 missing priority bucket(s): " + " ".join(miss_b)))
    bad.extend(replacement_defects(s))
    return bad
