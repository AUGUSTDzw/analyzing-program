"""Structural rules: six sections, three layers, fences, Mermaid labels,
location labels, and the priority buckets in section five.

`check(s)` returns a list of (kind, line, detail). Empty means clean. The
signature and every kind string are unchanged from the single-file gate; the
1.1.0 change is only that it lives here.
"""
import re

from checks.contract import (A8_GAP, BUCKETS, CONTRACT, DIAGRAM_LANG, LAYERS,
                             LINE_NUM, PSEC_RE, QUOTE_LANG, ROW, SEC_RE,
                             _NEXT_SEC_RE)
from checks.encoding import replacement_defects
from checks.escape import escape_defects
from checks.text import (LIST_ITEM, TICK, TAG, _flat, _src_of, blank_fences,
                         fence_defects, fence_spans, layer_bodies, layer_body,
                         line_of, mermaid_labels, mm_violation, source_blocks)

SECTIONS_EXACTLY_ONCE = CONTRACT.get("sections_exactly_once", False)
LAYERS_DISTINCT = CONTRACT["layers"].get("distinct", False)
ROWS_REQUIRE_OBJECT = CONTRACT["problem_section"].get("rows_require_source_object", False)
REQUIRED_DIAGRAMS = tuple(CONTRACT["mermaid"].get("required_diagrams") or ())

DW = CONTRACT["layers"].get("do_what") or {}
DW_KIND = DW.get("violation_kind", "A8-list")
DW_MIN = DW.get("items_min_per_block", 2)
DW_ONE = DW.get("single_statement_items", 1)
DO_WHAT_LIST = bool(DW)

# Same reason as the lists in contract.py and text.py: without one, `import *`
# into report_qc.py hands every name above to that module as well -- and a
# detector added there could then reach for re or TICK and resolve it through
# this module, working in tests and failing on a system where something else
# owns the name. An explicit list turns a silent resolution into a NameError at
# import.
__all__ = ["check"]


_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")

# Common ABAP keywords that match _IDENT but are not source objects. A row that
# says "this code uses FOR loops" would otherwise pass the source-name test
# because FOR occurs in almost every ABAP program.
_ABAP_KEYWORDS = frozenset([
    # OOP keywords
    "class", "class-data", "class-methods", "class-pool", "private",
    "public", "protected", "endclass", "endinterface", "try", "exception",
    "exceptions", "message", "method", "interface", "implement", "alias",
    "exporting", "importing", "changing", "returning", "receiving",
    # Flow control
    "else", "exit", "break", "raise", "check", "perform", "call", "submit",
    "continue", "return", "returns", "exit-command",
    # Database operations
    "insert", "update", "commit", "rollback", "append", "endloop", "endform",
    "tables", "into", "from", "where", "select", "for", "all", "entries",
    "in", "not", "initial", "space", "up", "down", "first", "last",
    "occurrences", "occurrence", "lines", "of",
    # Selection screen
    "authority-check", "send", "wait", "provide", "endprovide",
    "enhancement", "enhancement-point", "enhancement-section",
    "end-of-selection", "start-of-selection", "selection-screen",
    "at-selection-screen", "at-pf", "at-user-command", "top-of-page",
    "load-of-program", "initialization", "end-of-page", "print-control",
    "process-before-output", "process-after-input",
    "process-on-help-request", "process-on-value-request",
    # Data manipulation
    "load", "move", "move-corresponding", "sort", "compute", "concatenate",
    "find", "replace", "shift", "translate", "condense", "count",
    "length", "offset", "leading", "trailing", "left", "right", "length",
    # Operators and comparisons
    "eq", "ne", "lt", "le", "gt", "ge", "cs", "cp", "cn", "co",
    # String and data
    "string", "char", "numc", "dec", "int", "bool", "xstring", "bit",
    # Types and declarations
    "type", "types", "typed", "like", "value", "values", "default",
    "optional", "obligatory", "mandatory", "required",
    # Module and form
    "module", "endmodule", "input", "output", "begin", "end", "define",
    "enddefine", "form", "endform", "function", "endfunction",
    # Event blocks
    "at", "case", "when", "endcase", "loop", "endloop", "if", "endif",
    "while", "endwhile", "do", "enddo", "catch", "endcatch", "endtry",
    # Display and output
    "write", "display", "show", "uline", "new-line", "new-page", "skip",
    "title", "position", "places", "no-sign", "no-zero",
    # SQL-related
    "where", "having", "order", "by", "group", "distinct", "duplicates",
    "ascending", "descending",
    # Original keywords
    "and", "as", "by", "clear", "collected", "data", "declare", "delete",
    "describe", "exec", "export", "extract", "fetch", "field",
    "fieldsymbol", "free", "generate", "get", "group", "hiding", "import",
    "include", "is", "itab", "nesting", "otherwise", "out", "performs",
    "place", "placing", "position", "read", "receive", "ref", "refresh",
    "set", "source", "split", "static", "step", "structure", "table",
    "test", "then", "to", "tokenize", "using", "until", "value", "with",
])


def _row_names_source(row, flat_src):
    """True when a problem row points at something the source actually has.

    A backticked token counts on its own -- the writer chose to mark it as code.
    Otherwise the row must contain an identifier-shaped token that occurs in the
    source text. 'this code is written well' satisfies neither.

    Common ABAP keywords are excluded: FOR, AND, LOOP etc. appear in almost
    every program, so they would satisfy the test without naming a specific
    object.
    """
    if "`" in row:
        # Backticks can be markdown formatting or code references. Require a
        # backticked token that looks like an identifier and appears in the
        # source, not just the presence of any backtick character.
        bt_matches = re.findall(r"`([^`]+)`", row)
        if bt_matches and any(m.lower() in flat_src
                              and m.lower() not in _ABAP_KEYWORDS
                              for m in bt_matches):
            return True
    if flat_src is None:
        return False           # no source given: cannot judge, so do not fail
    return any(m.group(0).lower() in flat_src
               and m.group(0).lower() not in _ABAP_KEYWORDS
               for m in _IDENT.finditer(row))


def _missing_diagrams(s):
    """(kind, line, detail) for each required diagram type the report lacks.

    SKILL.md's 四、流程图 prescribes both a flowchart and a sequenceDiagram, but
    only the fence itself was checked before: a report could ship one and skip
    the other, and the gate reported clean. This looks for the type keyword
    inside each Mermaid block -- anchored to a line start because `flowchart`
    and `sequenceDiagram` both begin a diagram on their own line in valid
    Mermaid, and a free-text occurrence of the word would silently satisfy the
    check.
    """
    if not REQUIRED_DIAGRAMS:
        return []
    have = {}
    for st, bs, be, _en, lang in fence_spans(s):
        if lang != DIAGRAM_LANG.lower():
            continue
        blk = s[bs:be]
        for t in REQUIRED_DIAGRAMS:
            if t in have:
                continue
            if re.search(r"^\s*" + re.escape(t) + r"\b", blk, re.M):
                have[t] = line_of(s, st)
    return [("mm-missing", 0,
             "SKILL.md requires a Mermaid %s; the report has none" % t)
            for t in REQUIRED_DIAGRAMS if t not in have]


# Lines that carry no action: a comment, a blank, or the boundary of a block.
_COMMENT = ("*", "\u0022")
_STRUCT = ("FORM", "ENDFORM", "FUNCTION", "ENDFUNCTION", "START-OF-SELECTION",
           "ENDLOOP", "ENDCASE", "ENDWHILE", "ENDDO", "ENDIF", "ENDTRY",
           "ENDPROVIDE")


def _statements(blk):
    """Executable statement lines in one quoted block -- the denominator for
    A8-list.

    One list item per statement is the bar SKILL.md sets for the first layer, so
    the count decides how many items the layer owes. Comments and blanks carry no
    action; a block opener or closer is a boundary, not an action. A statement
    continued by a trailing marker makes its next line count too, which
    over-counts rather than under-counts.
    """
    n = 0
    for raw in blk.splitlines():
        t = raw.strip()
        if not t or t[0] in _COMMENT:
            continue
        if t.split(None, 1)[0].upper().rstrip(":.") in _STRUCT:
            continue
        n += 1
    return n


# ------------------------------------------------------------------- checking

def check(s, src=None):
    """Return a list of (kind, line, detail). Empty means clean.

    `src` is optional and only C1 needs it. Every existing caller that passes one
    argument keeps working, which is what lets the rule land without touching the
    fixtures.
    """
    bad = []

    # Block start -> block text, for the statement count behind A8-list.
    BLOCKS = {st: s[bs:be] for st, bs, be, _en, lang in fence_spans(s)
              if lang == QUOTE_LANG.lower()}

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
            if DO_WHAT_LIST:
                # LAYERS[0] is the first layer by contract order, the one whose
                # shape this rule polices. A8-cc and A8-pt stay ahead of it: a
                # block with no prose at all is reported for that first.
                n_items = len(LIST_ITEM.findall(layer_body(gap, LAYERS[0])))
                n_stmt = _statements(BLOCKS[st])
                need = DW_ONE if n_stmt <= 1 else DW_MIN
                if n_items < need:
                    body = layer_body(gap, LAYERS[0])
                    # A writer whose body is full of ① sees 0 items and has no
                    # reason to guess why. Name the marker that was not counted.
                    hint = ""
                    if not n_items and re.search(
                            r"^[ \t]*[\u2460-\u246b]", body, re.M):
                        hint = (" -- circled digits are not markdown list "
                                "markers, they render as one paragraph; use "
                                "1. 2. 3.")
                    bad.append((DW_KIND, line_of(s, st),
                                "%s is a paragraph, not a segmented list: "
                                "%d item(s) for %d statement(s)%s"
                                % (LAYERS[0], n_items, n_stmt, hint)))
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

    bad.extend(_missing_diagrams(s))

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
    if ROWS_REQUIRE_OBJECT and _src_of(src):
        flat_src = _flat(src).lower()
        sec5_off = s.find(sec5)
        for off, line in enumerate(sec5.split("\n")):
            if not line.strip().startswith("|") or set(line) <= set("|- "):
                continue
            if not ROW.match(line):
                continue
            if not _row_names_source(line, flat_src):
                bad.append(("row-src",
                            line_of(s, sec5_off + off) if sec5_off >= 0 else 0,
                            "problem row names no object from the source: %r"
                            % line.strip()[:60]))
    bad.extend(replacement_defects(s))
    # Both prose-integrity faults sit here, outside every structural loop: each
    # scans the whole document rather than one section or fence, and neither
    # needs a source, so neither belongs with the source-dependent checks above.
    bad.extend(escape_defects(s))
    return bad
