"""Pure text utilities, no state and no I/O.

Everything here is a function of its arguments alone. `structure`, `fidelity`,
`advisory` and `encoding` all need to agree on what a code fence is and which
line an offset falls on; that agreement has to live in exactly one place or the
checks drift apart. This is that place.

Extracted verbatim from report_qc.py in 1.1.0. Behaviour is unchanged.
"""
import re

from .contract import ANCHORS, MM_BAD, QUOTE_LANG

# Same reason as the list in contract.py: without it `import *` hands `re` to
# report_qc.py as well. ANCHORS/MM_BAD/QUOTE_LANG are re-exported out of
# contract.py and belong to its __all__, not to a second one here.
__all__ = ["TICK", "TAG", "FENCE_MARK", "mm_violation", "NODE", "mermaid_labels",
           "inventory", "lang_of", "fence_spans", "fence_defects", "blank_fences",
           "anchors_of", "anchor_for", "block_head", "in_risk_layer", "PROSE_END",
           "prose_end", "source_blocks", "line_of", "cite_extent", "ELIDE",
           "PAREN_NOTE", "CJK", "STR_LIT", "PUNCT"]

TICK = re.compile(r"`([^`\n]{2,80})`")
# Mermaid renders this HTML subset, so these are the only angle brackets a label
# may keep; every other < or > terminates it or starts a comment. One definition,
# read by mm_violation, so check() and fix_mm() cannot disagree about which
# brackets count -- the fixer used to convert the tags this regex names.
TAG = re.compile(r"</?(?:br|b|i|u|em|strong|sub|sup|code|span)\s*/?>", re.I)
# Line-anchored, three or more backticks: a fence opened with four closes with
# four, and a bare ```search reads the wrong character as the boundary. Every
# caller goes through fence_spans, which is where that pairing lives once.
FENCE_MARK = re.compile(r"^[ \t]*`{3,}([^\n]*)$", re.M)


def mm_violation(text):
    """Indices of bare < > or # that Mermaid would parse as HTML or an arrow.

    One definition, used by both halves. check() used to strip the tags in TAG
    before testing and fix_mm() to test the raw label, so the fixer turned the
    < and > inside <br> into full-width and broke diagrams it had been called to
    fix -- and it reported 0 defects on the result, because the checker never
    saw what the fixer wrote. Same split that has caused every other bug in this
    file, one layer down.
    """
    keep = [False] * len(text)
    for m in TAG.finditer(text):
        for i in range(m.start(), m.end()):
            keep[i] = True
    return [i for i, c in enumerate(text)
            if not keep[i] and MM_BAD.match(c)]


NODE = re.compile(r"(\[\s*|\(\s*|\{\s*)([^\]\)\}\n]*?)([\]\)\}])")


def mermaid_labels(block):
    """(label_text, offset_in_block) for every bracketed Mermaid node label.

    Single definition, used by both check and fix. They previously carried
    separate patterns: check used ``[^\\]]*`` and fix excluded ``)`` and ``}`` as
    well, so a label holding a bare ``>`` after a bracket was reported by one
    and silently skipped by the other. Same defect as the ln split, one layer up.
    """
    out = []
    for m in NODE.finditer(block):
        out.append((m.group(2), m.start(2)))
    # participant and actor are the same role in a sequence diagram; only the
    # first was aliased here, so `actor U as U <x>` rendered as a bare arrow
    # while its participant twin was caught.
    for m in re.finditer(r"(?:participant|actor)\s+\S+\s+as\s+(.+)$", block, re.M):
        out.append((m.group(1), m.start(1)))
    return out


def inventory(src):
    """Subprogram names declared in the source, in order of first appearance.

    Every construct in ANCHORS counts. Slicing this list used to leave FUNCTION
    and MODULE out, so a function group or a classic screen program produced an
    empty inventory and the density advisory could never fire on exactly the two
    input types the skill advertises.
    """
    out = []
    for rx, _ in ANCHORS:
        for m in rx.finditer(src):
            n = m.group(1)
            if n and n not in out:
                out.append(n)
    return out


def _past_line(s, off):
    """Offset just past the newline that terminates the line at off."""
    nl = s.find("\n", off)
    return len(s) if nl < 0 else nl + 1


def lang_of(m):
    """Language a fence marker declares: case-insensitive, trailing junk ignored."""
    t = m.group(1).strip()
    return t.split()[0].lower() if t else ""


def fence_spans(s):
    """[(open, body_start, body_end, close, lang)] for every closed code fence.

    The one definition. source_blocks, the mermaid check, blank_fences,
    fidelity_note, fix_lang_note and fix_mislabel_note all used to spell it
    their own way -- a hardcoded 8-character offset, an exact ```abap\n, a
    non-greedy search, and startswith() in the fixer -- four answers to one
    question, and each pair of answers differed on exactly the fences that were
    not ```abap followed by ``` on their own lines.

    8 is len("```abap\n") and only that, so the hardcoded offset mispaired a
    fence opened with four backticks and its prose window started inside its own
    code. The offset past a marker is the marker's own length, never a constant.

    body_start is past the marker's newline, because $ stops before it and a
    body that begins with one shifts every reported line index by one.

    A fence that never closes is dropped here and reported by fence_defects.
    Swallowing it to EOF would make every later section invisible to check(),
    which is the silent half of that bug.
    """
    ms = list(FENCE_MARK.finditer(s))
    out = []
    for i in range(0, len(ms) - 1, 2):
        o, c = ms[i], ms[i + 1]
        out.append((o.start(), _past_line(s, o.start()), c.start(),
                    c.end(), lang_of(o)))
    return out


def fence_defects(s):
    """('fence', line, detail) for a fence that never closes.

    FENCE_MARK pairs markers in order, so an odd count means the last one is an
    opener with no closer. Unreported it is the worst defect in the set: it
    swallows every later section, layer label and citation, so the checks run on
    less than the document and report back clean. The report is structurally
    perfect in every way the gate can still see.
    """
    ms = list(FENCE_MARK.finditer(s))
    if len(ms) % 2 == 0:
        return []
    st = ms[-1].start()
    return [("fence", line_of(s, st),
             "code fence never closes: everything after this line is inside the "
             "fence, so the section, layer and citation checks never see it")]


def blank_fences(s):
    """Same length as s, with code fence bodies blanked."""
    out = []
    last = 0
    for st, _bs, _be, en, _lang in fence_spans(s):
        out.append(s[last:st])
        out.append("\x00" * (en - st))
        last = en
    out.append(s[last:])
    return "".join(out)


def anchors_of(src):
    marks = []
    for i, ln in enumerate(src.split("\n"), 1):
        for rx, tmpl in ANCHORS:
            m = rx.match(ln)
            if m:
                marks.append((i, tmpl.format(*m.groups())))
                break
    marks.sort()
    return marks


def anchor_for(marks, line):
    best = None
    for ln, name in marks:
        if ln <= line:
            best = name
        else:
            break
    return best


def block_head(s, off):
    """Text from the nearest sub-program heading up to ``off``.

    Used only by fix_lang_note, to say whether a fence sits inside the
    风险与改进 layer. Position is advisory there and exempts nothing: an unlabelled
    proposed fix and the next sub-step's real quote occupy the same position and
    are identical to inspect. Two gates used to need this same answer and computed
    it two different ways -- heading-scoped in one, whole-document in the other --
    and the drift let a fabricated statement score clean.
    """
    head = s[:off]
    h = max(head.rfind("\n#### "), head.rfind("\n### "))
    return head[h:] if h >= 0 else head


def in_risk_layer(head):
    ir = head.rfind("风险与改进")
    if ir < 0:
        return False
    return ir > head.rfind("做什么") and ir > head.rfind("为什么")


PROSE_END = re.compile(r"(?m)^#{1,6}[ \t]")


def prose_end(s, off):
    """Where the prose belonging to a preceding block ends.

    The three layers belong to the block they follow, so the window stops at the
    next fence of any language or the next heading. Ending it at the next quoted
    fence instead let two clean passes through: labels sitting inside an
    intervening abap-fix fence satisfied a block that had no prose of its own,
    and a trailing block with no layers at all was satisfied by the label words
    anywhere later in the document. Both were the report claiming a per-block
    walkthrough it never wrote.

    Single definition on purpose -- fix_lang_note asks the same question, and two
    answers to one question is the defect class this file exists to remove.
    """
    end = len(s)
    f = s.find("```", off)
    if f >= 0:
        end = f
    h = PROSE_END.search(s, off)
    if h:
        end = min(end, h.start())
    return end


def source_blocks(s):
    """Yield (block_start, block_end, gap_text) for fences quoting source.

    Fence language is the only admission test. An earlier version also exempted
    any block sitting in the 风险与改进 layer, which is where a proposed fix lives
    -- but so does the next sub-step's real quote, and the exemption skipped that
    one too. Nothing structural can tell the two apart, so the report says which
    it is in the language of the fence.
    """
    for st, _bs, _be, en, lang in fence_spans(s):
        if lang != QUOTE_LANG.lower():
            continue
        yield st, en, s[en:prose_end(s, en)]


def line_of(s, off):
    return s.count("\n", 0, off) + 1


# Punctuation and whitespace that may wrap a citation. Anything else inside
# the span means the citation is embedded in prose, and the prose stays.
_WRAP = set(" \t.,;:()[]{}<>/-") | {
    "\u0027", "\u0022", "|",
    "\uff08", "\uff09", "\u3010", "\u3011", "\u300a", "\u300b",
    "\u3001", "\uff0c", "\u3002", "\uff1b", "\uff1a", "\uff5e",
    "\u2014", "\u2013", "\u201c", "\u201d", "\u2018", "\u2019", "-",
}


def cite_extent(inner, lm):
    """(start, end) of the citation to rewrite inside a backticked span.

    A span is usually just the citation, possibly wrapped in punctuation:
    rewrite the whole thing. Sometimes the citation sits inside prose, as in
    `L03 SELECT foo FROM bar`. Rewriting the whole span there deletes the
    statement the citation points at, and the note that follows says the
    repair is complete. Rewrite only the citation in that case, so nothing
    the writer said can be lost to a mechanical fix.
    """
    st, en = lm.span()
    # `.abap:104` and `:104` cannot stand alone: fold in the file name they
    # belong to, or the repair leaves `zFUNCTION z_foo` behind.
    if inner[st] in ".:":
        while st > 0 and re.match(r"[A-Za-z0-9_.\-]", inner[st - 1]):
            st -= 1
    rest = inner[:st] + inner[en:]
    if all(c in _WRAP for c in rest):
        return 0, len(inner)
    return st, en


# Lines that assert nothing about the source, so a fidelity pass must skip them.
# ELIDE must be searched in the code portion, never the raw line: searching the
# raw line meant an ellipsis inside a trailing comment -- "LOOP AT t INTO wa. "
# ... more" -- exempted the statement it sat on. The comment is dropped by
# _strip_comment first, so a marker there no longer reaches the test.
ELIDE = re.compile(r"\.\.\.|\u2026")
PAREN_NOTE = re.compile(r"^[\s|*]*[\uff08(].*[\uff09)]\s*$")
CJK = re.compile(r"[\u4e00-\u9fff]")
# An ABAP string literal: the delimiter is ' , so " is always a comment marker
# and never part of a string. Read by _claims, which uses it twice: once with
# the comment still attached, to count literals for the balance test, and once
# without, to decide whether what is left is code or the report's annotation.
STR_LIT = re.compile(r"'[^']*'")
# The source writes "t_documents ," with a space before the comma; the report
# writes "t_documents,". Punctuation spacing, not a rewritten statement.
PUNCT = re.compile(r"\s+([,;:)])")


def _flat(s):
    s = re.sub(r"\s+", " ", s).strip().lower()
    s = PUNCT.sub(r"\1", s)
    return re.sub(r"([(])\s+", r"\1", s)


def _strip_comment(l):
    """A quoted line with any ABAP comment removed.

    Outside a string literal " always opens a comment, and * opens one at the
    beginning of a line. Everything from there on is prose, never code.

    This is the one place that decides whether a quoted line is source or the
    report's own annotation, so it runs before every test below. Quoted ABAP in
    a Chinese system is full of CJK that is not commentary -- WRITE / '开始'.
    and DATA lv_x TYPE string. " 物料号 both carry CJK and are real statements --
    so testing for CJK alone used to exempt them from the only check that
    catches an invented statement, and a fabricated Chinese literal read exactly
    like a faithful one.
    """
    c = l.find('"')
    if c >= 0:
        return l[:c]
    return "" if l.lstrip().startswith("*") else l



def _claims(body):
    """(line_index_in_block, text) for every line that asserts about source.

    The index is the position in body.split("\n"), not in the filtered
    result. Counting inside the filtered result pointed at the wrong line
    whenever a skipped line -- a comment, or the report's own commentary --
    sat above the fabricated one.
    """
    out = []
    for i, raw in enumerate(body.split("\n")):
        l = re.sub(r'^\s*[*"\'"]', "", raw).rstrip()
        if len(l.strip()) < 3 or PAREN_NOTE.match(l):
            continue
        pre = _strip_comment(l)
        code = STR_LIT.sub("''", pre)
        if ELIDE.search(code):
            continue                    # skill-permitted elision, anywhere in the code
        if not re.search(r"[A-Za-z0-9]", code):
            continue                    # a comment, or the report's own annotation
        if CJK.search(code):
            continue                    # CJK survived the strip: prose, not ABAP
        if pre.count("'") % 2:
            # Unbalanced literal outside comments: the report's own debris, not a
            # statement. Counted on pre, not l, so an apostrophe inside a comment
            # does not tip it; counted on pre, not code, so a paired literal is
            # not stripped away before the test runs. A line whose truncation
            # left a bare delimiter -- 'BUK' FIELD written as BUK' FIELD -- fails
            # this test too and is therefore not probed. Measured over the 33
            # archived reports that cost four rewrites and no false positives.
            continue
        out.append((i, l))
    return out
