#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify and repair reports written against the analyzing-programs skill.

Script-based on purpose. Asking a model whether it followed the skill is exactly
the wrong instrument: across runs on one file the same skill scored 0.700 /
0.625 / 0.650 recall, and different models drift further still. Normative text
cannot be the enforcement mechanism for output that varies; a deterministic gate
can. Anything a script can decide, decide here, so the model spends its
judgement only on the parts that need judgement.

Modes:

    python report_qc.py REPORT [SOURCE.abap]         check, list every defect
    python report_qc.py --fidelity-only REPORT SOURCE check only the quotations
    python report_qc.py --fix REPORT SOURCE [-o OUT] check, and repair the
                                                   classes that cannot change
                                                   meaning

SOURCE is optional in plain mode, but density and fidelity both need it, so a
report checked without one passes with two of its diagnostics still unrun. The
script says so rather than staying quiet about it.

Repair is deliberately narrow. A line-number location label and a bare ``<`` in
a Mermaid label are both violations the skill states without exception, so
rewriting them cannot alter meaning. An A8 three-layer violation is different:
the fix needs to know what the prose after the block was meant to say, and
guessing re-labels a risk discussion as a description. Those are reported with
line numbers and left to the model.

Detectors live in this one file and are shared by both modes on purpose. An
earlier version kept the checker and the fixer in separate scripts with separate
regexes; they drifted, and the fixer silently missed a form the checker caught.

Exit codes are the contract with the caller, and SKILL.md step 7 tells the model
to re-run this script until it is clean. So every mode reports the verdict in
the exit status as well as in stdout: 0 only when check() finds no defect. A
mode that returns 0 after printing FAIL gives the caller a termination signal
that is always green.

2 is a refusal to run, not a defect: a report path that does not exist, a source
path that does not exist, or a source that is not utf-8. A caller that cannot tell
the two apart treats "nothing was checked" as "nothing is wrong" -- a typo in
the source path then reads exactly like a clean fidelity pass, which is the one
false reassurance this script is allowed to give.

Defects and advisories are different things here on purpose. check() failures
exit nonzero; the four advisories -- density, fidelity, fix-lang and
fix-mislabel -- print as `note` and do not change
the exit code in plain mode, because plain mode is the structural pass and the
fidelity violations it happens to see are adjudicated by --fidelity-only, which
does promote them to a failure. A note is a question for the writer, not a gate.

stdout is forced to UTF-8 because the contract's own bucket markers are emoji
(U+1F534 and friends). On a Windows console defaulting to cp936, printing one
raises UnicodeEncodeError -- and it raised it from inside the defect loop, so the
crash replaced the diagnosis with a traceback and the bucket check, one of the
four things this gate exists to do, was unreachable on that platform.
"""
import io
import json
import os
import re
import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# ---------------------------------------------------------------- shared rules

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

# Fence language decides whether a fence quotes source or illustrates a proposed
# fix. Position exempts nothing: a block after a 风险与改进 label is indistinguishable
# from the next sub-step's real quote, and the positional exemption used to skip
# genuine quotes wholesale (12 of 138 statements inspected on a report carrying
# 20 blocks). A mislabeled fix is caught by fix_lang_note instead of being
# silently trusted. Both names are read from the contract below rather than
# spelled out here, which is where they used to live.

# The rule set is read from schemas/report-contract.json, not hardcoded here.
# Seven fixes in this project were a detector disagreeing with the rule it was
# meant to enforce: LINE_NUM matched two spellings so a report written as `L23`
# throughout scored clean, and the checking half and the fixing half of the
# Mermaid rule carried different patterns so one reported what the other skipped.
# A second copy of the rules inside this file is the cause of that class of bug,
# so there is now one copy. Every rule in the contract carries a skill_anchor,
# and test_contract_drift.py fails when that anchor is absent from SKILL.md, so
# the contract and the prose cannot drift apart either.
CONTRACT_PATH = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "schemas", "report-contract.json")
with io.open(CONTRACT_PATH, encoding="utf-8") as _fh:
    CONTRACT = json.load(_fh)

SEC = ["## " + s["id"] for s in CONTRACT["sections"]]
# The gate must find a section at level two, not merely contain its string.
# "### 一、..." contains "## 一", so a report written entirely in ### satisfied
# every section and reported back clean -- and section 五 was then harvested
# from the wrong place. Anchored at the line start instead.
SEC_RE = [(re.compile(r"^" + re.escape(h), re.M), h[3:]) for h in SEC]
LAYERS = tuple(CONTRACT["layers"]["labels"])
# How much prose counts as "some" at all. A bare 20 sat in check(), the one
# threshold in this rule set that existed in no other place.
A8_GAP = CONTRACT["layers"]["prose_window_max_chars"]
BUCKETS = tuple(CONTRACT["problem_section"]["buckets"])
# Built from BUCKETS instead of re-spelling the four emoji, and DIAGRAM_LANG read
# from the contract instead of being written twice. Both are the second-copy
# defect: the priority colours appeared once in the contract and once here, and
# the Mermaid fence name appeared once in the gate and once in the fixer.
ROW = re.compile(r"^\|\s*(?:P[0-3][-.]?\d+|[%s])\s*\|"
                 % re.escape("".join(BUCKETS)), re.M)
DIAGRAM_LANG = CONTRACT["mermaid"]["fence_language"]
FENCE_LANGS = CONTRACT["layers"]["fence_languages"]
QUOTE_LANG = FENCE_LANGS["quotes_source"]
FIX_LANG = FENCE_LANGS["illustrates_a_fix"]
PSEC = CONTRACT["problem_section"]["heading"]
PSEC_RE = re.compile(r"^" + re.escape(PSEC), re.M)
# The problem section ends where the next section begins. Both bounds come from
# the contract: check() used to look for the literals "## 五" and "## 六", so
# editing problem_section.heading changed nothing and PSEC sat unused.
_IDS = [x["id"] for x in CONTRACT["sections"]]
_NEXT_SEC = (SEC[_IDS.index(CONTRACT["problem_section"]["id"]) + 1]
             if CONTRACT["problem_section"]["id"] in _IDS else None)
_NEXT_SEC_RE = (re.compile(r"^" + re.escape(_NEXT_SEC), re.M)
                if _NEXT_SEC else None)
# The English spellings require whitespace. Allowing \s* let `lines?\s*\d+` match
# LINE1 and LINE2, which are identifiers, and report them as line citations.
LINE_NUM = re.compile(
    "|".join("(?:%s)" % p["regex"]
             for p in CONTRACT["forbidden_in_location_labels"]["patterns"]), re.I)
FULLWIDTH = CONTRACT["mermaid"]["fullwidth"]
# The three characters the checker rejects are the contract's own list, not a
# second [<>#] literal. The class used to be spelled out in the checker and in
# the fixer separately; the file's docstring opens with the history of that
# exact split causing a reported defect the fixer skipped.
MM_BAD = re.compile(r"[%s]"
                    % re.escape("".join(CONTRACT["mermaid"]["forbid_in_display_text"])))


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
DENSITY_FLOOR = next(a["floor_blocks_per_subprogram"] for a in
                     CONTRACT["advisories"] if a["id"] == "density")
# LINE_NUM decides whether a backticked span is a citation at all, so this only
# has to pull the number out of one it already approved. Anchoring it to the whole
# string used to make three of the five forms the contract lists unparseable:
# `zvend.abap:104` and `（第 90-96 行）` are not "purely a line number", and they
# are the two examples SKILL.md prints as wrong, so --fix told the model to write
# them and then refused to repair them.
# First digit run, so a range resolves to its start -- the nearest preceding
# construct there is the one the range begins in.
# Take the widest digit run the contract admits, out of the contract, so no
# accepted citation is ever left unparsed and check() and fix_ln() cannot
# disagree about what a citation is. A copied {2,5} cap made check() accept
# `L100000` while fix_ln() read it as 10000, compared that with the line
# count and reported a number past the end of a file it had never counted.
_CITE_LIM = [int(x) for p in CONTRACT["forbidden_in_location_labels"]["patterns"]
             for x in re.findall(r"\\d\{(\d+),\}", p["regex"])]
CITE_NUM = re.compile(r"(\d{%d,})" % (min(_CITE_LIM) if _CITE_LIM else 1))

# ABAP constructs usable as location anchors, ordered so the more specific
# pattern wins: CLASS x IMPLEMENTATION. must beat CLASS x.
ANCHORS = [
    (re.compile(r"^\s*CLASS\s+(\w+)\s+IMPLEMENTATION", re.M), "CLASS {0} IMPLEMENTATION"),
    (re.compile(r"^\s*(?:INTERFACE)\s+(\w+)", re.M), "INTERFACE {0}"),
    (re.compile(r"^\s*CLASS\s+(\w+)", re.M), "CLASS {0}"),
    (re.compile(r"^\s*METHODS?\s+(\w+)", re.M), "METHOD {0}"),
    (re.compile(r"^\s*FORM\s+(\w+)", re.M), "FORM {0}"),
    (re.compile(r"^\s*FUNCTION\s+(\w+)", re.M), "FUNCTION {0}"),
    (re.compile(r"^\s*MODULE\s+(\w+)\s+(INPUT|OUTPUT)", re.M), "MODULE {0} {1}"),
    (re.compile(r"^\s*DEFINE\s+(\w+)", re.M), "DEFINE {0}"),
    (re.compile(r"^\s*PROCEDURE\s+(\w+)", re.M), "PROCEDURE {0}"),
]
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


def density_note(s, src):
    """Advisory: quoted blocks per declared subprogram.

    Naming every subprogram is cheap. The v1 AVE report names 435 of 439 and
    passes every structural check in this file -- six sections, four priority
    buckets, no bare Mermaid characters, no line-number locations -- while
    quoting 68 blocks for 439 subprograms. It is an inventory wearing an
    analysis-shaped wrapper, and nothing else here can see that.

    Reported rather than enforced. Six sections and four buckets are rules the
    skill states without exception, so they can fail a report. A density floor
    cannot: 0.50 blocks per subprogram is what 19 samples happened to separate
    at, with only four below it, and a source of many one-line helpers does not
    owe one block each. A wrong floor here would fail correct reports, which is
    worse than missing a soft signal.
    """
    if not src:
        return None
    inv = inventory(src)
    if not inv:
        # No construct in ANCHORS at all, so there is no denominator. This is a
        # limitation of the detector, not a judgement about the source -- and it
        # used to be reported as silence, which reads as "nothing to worry
        # about". Say what could not be measured instead.
        names = []
        for _, t in ANCHORS:
            n = t.split("{")[0].strip()
            if n and n not in names:
                names.append(n)
        return ("density not measured: the source declares no %s this script can "
                "count, so there is no denominator. That is a limit of the "
                "detector, not evidence that the report is thorough."
                % " / ".join(names))
    blocks = len(list(source_blocks(s)))
    d = blocks / len(inv)
    named = sum(1 for n in inv if n.lower() in s.lower())
    if d >= DENSITY_FLOOR:
        return None
    return (f"low density: {blocks} quoted block(s) for {len(inv)} declared "
            f"subprogram(s) = {d:.2f} each ({named} of them named in the text). "
            f"If the text reads as a list rather than a walkthrough, it is an "
            f"inventory, not an analysis.")


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


# ------------------------------------------------------------------- checking

def check(s):
    """Return a list of (kind, line, detail). Empty means clean."""
    bad = []

    present = sum(1 for rx, _ in SEC_RE if rx.search(s))
    if present < len(SEC_RE):
        missing = [sid for rx, sid in SEC_RE if not rx.search(s)]
        bad.append(("sec", 0, f"missing section(s): {', '.join(missing)}"))

    for st, end, gap in source_blocks(s):
        miss = [l for l in LAYERS if l not in gap]
        if not miss:
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
    return bad


# --------------------------------------------------------------------- fixing

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


def fix_ln(s, src):
    """Rewrite a line-number citation as the nearest preceding construct.

    Edits are applied to the original string by offset. blank_fences preserves
    offsets, so this can find labels in fence-free text and still write back
    into the untouched original; returning the blanked text instead silently
    deletes every code block in the report.

    Returns (text, n_edits, notes). The reasons a label is left alone are all
    different and used to share a single message: a citation that cannot be
    parsed as a line number is a format problem, a parsed number with no
    preceding construct is an anchor problem, and a number past the end of the
    source is a citation that was never written against this file. Reporting all
    three as "no usable anchor" sent the writer to add constructs to the source
    instead of fixing the label, which is why every example SKILL.md shows came
    back unrepaired. The third case also mattered on its own: anchoring a number
    the source has no such line to means handing the citation a plausible name.
    """
    notes = []
    marks = anchors_of(src)
    nl = len(src.splitlines())
    if not marks:
        return s, 0, ["ln: the source has no recognisable construct to anchor to"]
    masked = blank_fences(s)
    edits = []
    unparsed = []
    no_anchor = []
    past_end = []
    for m in TICK.finditer(masked):
        inner = m.group(1)
        lm = LINE_NUM.search(inner)
        if not lm:
            continue
        cm = CITE_NUM.search(inner)
        if not cm:
            unparsed.append(inner)
            continue
        num = int(cm.group(1))
        if num > nl:
            past_end.append(inner)
            continue
        a = anchor_for(marks, num)
        if not a:
            no_anchor.append(inner)
            continue
        # Rewrite the citation, not the span: a span often carries the
        # statement the citation points at, and replacing it wholesale
        # deleted that prose while reporting the repair as complete.
        st, en = cite_extent(inner, lm)
        edits.append((m.start(1) + st, m.start(1) + en, a))
    if unparsed:
        notes.append("ln: %d label(s) could not be read as a line number, left "
                     "for the model: %s" % (len(unparsed), unparsed[:2]))
    if no_anchor:
        notes.append("ln: %d citation(s) have no preceding construct to point "
                     "at, left alone" % len(no_anchor))
    if past_end:
        notes.append("ln: %d citation(s) point past the end of the source (%d "
                     "line(s)), left for the model: %s"
                     % (len(past_end), nl, past_end[:2]))
    if not edits:
        return s, 0, notes
    out = s
    for a, b, rep in reversed(edits):
        out = out[:a] + rep + out[b:]
    return out, len(edits), notes


# Lines that assert nothing about the source, so a fidelity pass must skip them.
ELIDE = re.compile(r"\.\.\.|\u2026")
PAREN_NOTE = re.compile(r"^[\s|*]*[\uff08(].*[\uff09)]\s*$")
CJK = re.compile(r"[\u4e00-\u9fff]")
# An ABAP string literal: the delimiter is ' , so " is always a comment marker
# and never part of a string. Read by _abap_code, which is the one place that
# decides whether a quoted line is code or the report's own annotation.
STR_LIT = re.compile(r"'[^']*'")
# The source writes "t_documents ," with a space before the comma; the report
# writes "t_documents,". Punctuation spacing, not a rewritten statement.
PUNCT = re.compile(r"\s+([,;:)])")


def _flat(s):
    s = re.sub(r"\s+", " ", s).strip().lower()
    s = PUNCT.sub(r"\1", s)
    return re.sub(r"([(])\s+", r"\1", s)


def _abap_code(l):
    """A quoted line with comments and string-literal contents removed.

    Quoted ABAP in a Chinese system is full of CJK that is not commentary:
    WRITE / '开始'. and DATA lv_x TYPE string. " 物料号 both carry CJK and are
    real statements. Testing for CJK alone exempted them from the only check
    that catches an invented statement, so a fabricated Chinese literal read
    exactly like a faithful one. A statement comment (" ...) and a full-line
    comment (* ...) carry no code either, so they come out with the comment.
    What is left is ABAP code, and ABAP identifiers are ASCII.
    """
    c = l.find('"')
    if c >= 0:
        l = l[:c]
    if l.lstrip().startswith("*"):
        return ""
    return STR_LIT.sub("''", l)


def _claims(body):
    """(line_index_in_block, text) for every line that asserts about source.

    The index is the position in body.split("\n"), not in the filtered
    result. Counting inside the filtered result pointed at the wrong line
    whenever a skipped line -- a comment, or the report's own commentary --
    sat above the fabricated one.
    """
    out = []
    for i, raw in enumerate(body.split("\n")):
        if ELIDE.search(raw):
            continue                    # skill-permitted boilerplate elision
        l = re.sub(r'^\s*[*"\'"]', "", raw).rstrip()
        if len(l.strip()) < 3 or PAREN_NOTE.match(l):
            continue
        code = _abap_code(l)
        if not re.search(r"[A-Za-z0-9]", code):
            continue                    # a comment, or the report's own annotation
        if CJK.search(code):
            continue                    # CJK survived the strip: prose, not ABAP
        if l.count("'") % 2:
            continue                    # unbalanced string literal: layout debris
        out.append((i, l))
    return out


def fidelity_note(s, src):
    """Advisory: quoted statements that do not occur in the source.

    The skill requires pasted code to be character-for-character faithful and
    forbids altering statements to read better. Nothing structural can see this:
    a fabricated block still has six sections, three layers per block and four
    priority buckets.

    Measured over 1444 quoted statements in ten reports, 16 did not occur in the
    source and 11 of those 16 were substantive. The worst was not a rename: a
    report quoted two calls that load a prior and a latest version and gave both
    the same argument, so the code it described no longer did what it does.

    Reported, not enforced. Three of the sixteen are punctuation or a merged
    TYPES header, and 69% precision is not good enough to fail a report -- the
    same reason density is advisory. It is good enough to be worth reading.
    """
    if not src:
        return None
    sf = _flat(src)
    bad = []
    n = 0
    for st, bs, be, _en, lang in fence_spans(s):
        if lang != QUOTE_LANG.lower():
            continue
        base = line_of(s, st)
        for i, l in _claims(s[bs:be]):
            n += 1
            probe = l.strip()
            c = probe.find('"')
            if c >= 0:
                probe = probe[:c]      # a statement comment is prose, not code
            probe = probe.rstrip(".")
            if probe and _flat(probe) not in sf:
                bad.append((base + 1 + i, l.strip()))
    if not bad:
        return None
    head = bad[0]
    more = f" (+{len(bad)-1} more)" if len(bad) > 1 else ""
    return (f"{len(bad)} quoted statement(s) of {n} do not occur in the source. "
            f"First at line {head[0]}: {head[1][:60]!r}{more}. "
            f"Check whether the report rewrote the source.")


def fix_lang_note(s):
    """Advisory: a source-quoting fence sitting inside the 风险与改进 layer.

    Language decides what gets checked, but only if the author relabels. A proposed
    fix left in an abap fence is indistinguishable from a faithful quote, so it is
    probed against the source and reads as fabricated -- precisely the false
    negative this gate exists to remove. Flagging the fence costs one line;
    explaining why a correct fix looks like a lie costs a debugging session.

    Position alone cannot decide, and this advisory would flag the second quoted
    block of a heading that carries two. A8 already requires every quote to be
    followed by its own three layers, so a tail lacking them is a fix, not a quote.
    """
    hits = []
    for st, _bs, _be, en, lang in fence_spans(s):
        if lang != QUOTE_LANG.lower():
            continue
        if not in_risk_layer(block_head(s, st)):
            continue
        # Search from just past the block's own closing fence; starting at the
        # opening fence makes the first ``` found the closing one, so the tail
        # is the block's code and no layer can ever be in it.
        tail = s[en:prose_end(s, en)]
        if all(l in tail for l in LAYERS):
            continue
        hits.append(st)
    if not hits:
        return None
    ln = line_of(s, hits[0])
    more = f" (+{len(hits)-1} more)" if len(hits) > 1 else ""
    return (f"{len(hits)} {QUOTE_LANG} fence(s) sit inside a 风险与改进 layer{more}, "
            f"first at line {ln}. If one illustrates a proposed fix, tag it "
            f"{FIX_LANG}: unlabelled, it is probed against the source and reads "
            f"as fabricated.")


def fix_mislabel_note(s, src):
    """Advisory: an abap-fix fence that repeats a contiguous run of the source.

    The abap / abap-fix pair locked in one direction only. A fix left in an abap
    fence is probed against the source and reads as fabricated, so it is caught.
    Source pasted into an abap-fix fence is never compared with the source at
    all, so the language tag could opt a quotation out of the very check that
    exists to catch invented quotes. A one-directional fence is how this class
    of bug appears: the exemption is the hole.

    THE TEST IS CONTIGUITY, NOT MEMBERSHIP. The first version asked whether every
    statement occurs somewhere in the source. It fired on five times across nine
    real reports, and every one of those five was a genuine fix: a CALL FUNCTION
    with EXCEPTIONS added, a DELETE followed by an sy-subrc check, each line of
    which exists somewhere in a 1600-line file. Quoting the line you are about to
    change is legitimate -- the contract says so -- so membership cannot be the
    test. A mislabeled quote is a verbatim copy, and a verbatim copy is
    contiguous. Flatten the statements, join them with the single space that
    flattening leaves between lines, and look for that run.

    Reported, not enforced, like the other three advisories -- it is a question
    for the writer, not a gate.
    """
    if not src:
        return None
    sf = _flat(src)
    hits = []
    for st, bs, be, _en, lang in fence_spans(s):
        if lang != FIX_LANG.lower():
            continue
        flat = []
        flat_nodot = []
        first_text = None
        for _i, l in _claims(s[bs:be]):
            raw = l.strip()
            if not raw:
                continue
            if first_text is None:
                first_text = raw
            # Two spellings of the same run. Flattening keeps the sentence stops,
            # so joining the statements verbatim reproduces a contiguous run; the
            # run also has to be findable when the writer dropped the stops, which
            # is why the second variant exists.
            flat.append(_flat(raw))
            flat_nodot.append(_flat(raw.rstrip(".")))
        if not flat:
            continue
        if not any(" ".join(v) in sf for v in (flat, flat_nodot)):
            continue
        hits.append((line_of(s, st), first_text))
    if not hits:
        return None
    first = hits[0]
    more = " (+%d more)" % (len(hits) - 1) if len(hits) > 1 else ""
    return ("%d %s fence(s) repeat the source verbatim%s, first at line %d: %r. "
            "Contiguous, not assembled from elsewhere -- so this reads as a "
            "quotation rather than a proposed fix. An %s fence is exempt from "
            "the fidelity check, so a mislabeled quote is never compared with "
            "the source at all. If this is a quotation, tag it %s.") % (
        len(hits), FIX_LANG, more, first[0], first[1][:60], FIX_LANG, QUOTE_LANG)


def fix_mm(s):
    """Convert bare < > # in Mermaid display text to their full-width forms.

    The skill prescribes full-width conversion, not quoting, and states the ban
    without exception -- there is no "already quoted, so exempt" allowance. An
    earlier version had such a guard, which made it skip exactly the labels that
    began with a quote and still held a bare '>' inside: the checker flagged
    those and the fixer declined them.
    Tags in TAG are kept, not converted. Mermaid renders them, so writing <br>
    as ＜br＞ is a defect the checker never reported and the fixer introduced.
    mm_violation is the one definition both halves read.
    """
    lines = s.split("\n")
    n = 0
    inside = False
    for i, ln in enumerate(lines):
        mk = FENCE_MARK.match(ln)
        if mk:
            # The diagram fence opens on its own language and closes on any
            # backtick run, so a fence opened inside a diagram is a boundary.
            inside = (lang_of(mk) == DIAGRAM_LANG.lower()) if not inside else False
            continue
        if not inside or not MM_BAD.search( ln):
            continue
        edits = []
        for lab, off in mermaid_labels(ln):
            hits = mm_violation(lab)
            if not hits:
                continue
            bare = set(hits)
            edits.append((off, off + len(lab),
                          "".join(FULLWIDTH.get(c, c) if k in bare else c
                                    for k, c in enumerate(lab))))
        if not edits:
            continue
        n += len(edits)
        for a, b, rep in reversed(edits):
            ln = ln[:a] + rep + ln[b:]
        lines[i] = ln
    return "\n".join(lines), n


def fix(s, src):
    """Apply only repairs that cannot change meaning. Returns (text, n, notes)."""
    notes = []
    s, n, ln_notes = fix_ln(s, src)
    notes.extend(ln_notes)
    s, m = fix_mm(s)
    return s, n + m, notes


# ----------------------------------------------------------------------- main

def report(path, src=None):
    s = io.open(path, encoding="utf-8").read()
    bad = check(s)
    name = os.path.basename(path)
    notes = [n for n in (density_note(s, src), fidelity_note(s, src),
                         fix_lang_note(s), fix_mislabel_note(s, src)) if n]
    if not bad:
        print(f"PASS  {name}")
        for n in notes:
            print(f"  note  {n}")
        return 0
    order = {"fence": 0, "sec": 1, "prow": 2, "buck": 3, "ln": 4, "mm": 5,
             "A8-cc": 6, "A8-pt": 7}
    for kind, ln, detail in sorted(bad, key=lambda x: (order.get(x[0], 9), x[1])):
        where = f"line {ln}" if ln else "document"
        print(f"  {kind:6} {where:>10}  {detail}")
    print(f"FAIL  {name}  ({len(bad)} defect(s))")
    for n in notes:
        print(f"  note  {n}")
    return len(bad)


class ReadError(Exception):
    """A source path that exists but cannot be read as utf-8.

    errors="replace" turned a bad encoding into a U+FFFD stream, and every
    quotation then failed to match it. The fidelity advisory reported
    fabrication where the failure was in the read, which is the one thing
    that advisory exists to catch.
    """


def read_src(path):
    """Source text, or None when no usable source path was given."""
    if not path or not os.path.exists(path):
        return None
    with io.open(path, encoding="utf-8", errors="strict", newline="") as fh:
        try:
            return fh.read()
        except UnicodeDecodeError as e:
            raise ReadError("%s is not readable as utf-8 (%s), so nothing "
                            "was compared" % (path, e)) from e


def die(msg):
    """A refusal to run.

    Not a note: a note is a question for the writer and a note never stops
    the run. Labelling fatal errors as notes let a caller that greps for
    advisories collect hard failures as soft ones.
    """
    print(f"  error  {msg}")
    sys.exit(2)


def main(argv):
    args = argv[1:]
    if not args:
        print(__doc__)
        return 2
    if args and args[0] == "--fidelity-only":
        # Report only the statements that are not in the source. The format gate
        # and the structural checks are suppressed, which is what makes it
        # possible to measure whether format enforcement is what costs recall.
        # Added after an isolation run found -35 points of strict recall at
        # p=0.0215 between v1 and v1-plus-gate, with the fidelity diagnostic
        # still in both -- so the harmful half had not been separated from the
        # useful half.
        # argv is [prog, --fidelity-only, REPORT, SOURCE]. Splitting by extension
        # is the same rule plain mode uses; an allowlist of .abap here meant a
        # non-markdown report was dropped instead of checked.
        reports, srcs = [], []
        for x in args[1:]:
            if x.lower().endswith((".md", ".markdown")):
                reports.append(x)
            else:
                srcs.append(x)
        if not reports:
            die("no report path: --fidelity-only REPORT SOURCE")
        if len(srcs) != 1:
            die("fidelity needs exactly one source path (got %d: %s)"
                     % (len(srcs), ", ".join(srcs) or "none"))
        try:
            src = read_src(srcs[0])
        except ReadError as e:
            die(str(e))
        if src is None:
            die("no such source: %s" % srcs[0])
        if not src.strip():
            die("source is empty: %s (nothing to compare against)" % srcs[0])
        rc = 0
        for p in reports:
            if not os.path.exists(p):
                die("no such report: %s" % p)
            s = io.open(p, encoding="utf-8").read()
            n = fidelity_note(s, src)
            if n:
                print(f"FAIL  {os.path.basename(p)}")
                print(f"  note  {n}")
                rc = 1
            else:
                print(f"PASS  {os.path.basename(p)}")
        return rc
    if args[0] == "--fix":
        # Checked before the index is taken: indexing past the end raised
        # IndexError and printed a traceback, which is what this guard exists
        # to prevent, so it was unreachable.
        if "-o" in args and args.index("-o") + 1 >= len(args):
            die("-o needs an output path")
        rest = [a for a in args[1:] if a != "-o"]
        if len(rest) < 2:
            print("--fix needs REPORT and SOURCE")
            return 2
        out = args[args.index("-o") + 1] if "-o" in args else None
        rep, src = rest[0], rest[1]
        if not os.path.exists(rep):
            die("no such report: %s" % rep)
        if not os.path.exists(src):
            die("no such source: %s" % src)
        try:
            raw = io.open(rep, encoding="utf-8", newline="").read()
            ssrc = read_src(src)
        except ReadError as e:
            die(str(e))
        # The checks look for "```abap\n" and "## ", so they need one
        # terminator. Normalize for the pass, then restore the report's own
        # endings on the way out: a repair should not re-save the document.
        # Reading universal newlines instead converted CRLF to LF, and writing
        # them back out converted LF to CRLF on Windows.
        crlf = "\r\n" in raw
        fixed, n, notes = fix(raw.replace("\r\n", "\n"), ssrc)
        for nt in notes:
            print(f"  note  {nt}")
        dest = out or rep
        if dest == rep and n:
            # In place this rewrites the report, and the report is the
            # deliverable -- usually the only copy. --fix only touches mechanical
            # defects, but write the previous text next to it anyway.
            io.open(rep + ".bak", "w", encoding="utf-8", newline="").write(raw)
            print("previous text -> %s.bak" % rep)
        written = fixed.replace("\n", "\r\n") if crlf else fixed
        io.open(dest, "w", encoding="utf-8", newline="").write(written)
        print(f"repaired {n} mechanical defect(s) -> {dest}")
        left = check(fixed)
        for kind, ln, detail in left:
            where = f"line {ln}" if ln else "document"
            print(f"  {kind:6} {where:>10}  {detail}")
        # The other two modes print PASS or FAIL. A caller that greps for
        # either sees nothing from --fix, so the verdict lived only in the
        # exit code. Same vocabulary here.
        if left:
            print(f"FAIL  {os.path.basename(dest)}  "
                  f"({len(left)} defect(s) need the model)")
        else:
            print(f"PASS  {os.path.basename(dest)}")
        for note in (density_note(fixed, ssrc), fidelity_note(fixed, ssrc),
                     fix_lang_note(fixed), fix_mislabel_note(fixed, ssrc)):
            if note:
                print(f"  note  {note}")
        # Repaired what could be repaired; whatever is left needs the model, and
        # the caller has to be able to see that. Returning 0 here made a partial
        # repair indistinguishable from a finished one.
        return 1 if left else 0

    # A report is a markdown file; anything else on the command line is the
    # source. An allowlist of .abap extensions used to mean a .txt or .ab1
    # source was neither read nor announced, and worse, was then checked as if it
    # were a report -- a source file with no six sections fails the gate.
    reports, srcs = [], []
    for a in args:
        if a.lower().endswith((".md", ".markdown")):
            reports.append(a)
        else:
            srcs.append(a)
    if not reports:
        # Nothing looked like a report. The usual cause is a report saved as
        # .txt, so naming the paths passed is what lets the caller see that.
        die("no report path: report_qc.py REPORT [SOURCE] (got: %s)"
            % ", ".join(args))
    # Two sources on one line used to resolve to the last one, silently. That
    # looks like a successful run while checking one report against nothing.
    if len(srcs) > 1:
        die("more than one source: %s (pass exactly one)"
                 % ", ".join(srcs))
    # A path that does not exist is a typo, not "no source". Reading it as the
    # latter printed PASS and "no source recognised", which reads as "the report
    # is fine, coverage was optional" when the user meant to give a source.
    if srcs and not os.path.exists(srcs[0]):
        die("no such source: %s" % srcs[0])
    for p in reports:
        if not os.path.exists(p):
            die("no such report: %s" % p)
    try:
        src = read_src(srcs[0] if srcs else None)
    except ReadError as e:
        die(str(e))
    rc = 0
    for p in reports:
        rc += report(p, src) and 1
    if src is None:
        # After the verdict so a bare "report_qc.py REPORT" still reads PASS
        # first, and so the omission lands next to the coverage it costs rather
        # than somewhere the reader will not connect them.
        print("  note  no source recognised, so density, fidelity and "
              "fix-mislabel were not run (pass the ABAP file after the report)")
    elif not src.strip():
        print("  note  %s is empty, so density and fidelity were not run"
              % srcs[0])
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
