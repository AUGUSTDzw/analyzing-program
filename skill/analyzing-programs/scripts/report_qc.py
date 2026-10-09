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
import os
import re
import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# The rule set the checks read, and the text primitives every one of them is a
# function of, live in checks/ -- one copy each, so a detector added in 1.1.0
# cannot re-spell either and disagree with the half that did not.
# Inserted only when absent: "checks" is a plain enough name that something may
# already have put it on the path, and re-prepending the same directory on every
# run pushes whatever the host system had behind it for no gain.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    from checks.contract import *          # noqa: F401,F403
    from checks.text import *             # noqa: F401,F403
    # `import *` skips a leading underscore. These three are read by name below,
    # so they are named here rather than renamed to suit the import.
    from checks.contract import _NEXT_SEC_RE                     # noqa: F401
    from checks.text import _claims, _flat                       # noqa: F401
except (ImportError, SyntaxError) as _e:
    # The rule set and the checks that read it load before main() can run, so a
    # skill installed without scripts/checks/ dies here -- before main(), before
    # every exit-2 guard below. An unhandled ImportError exits 1, which SKILL.md
    # defines as "the check ran and found defects", so the caller goes looking
    # for defects that do not exist. Refuse the way the rule set itself does.
    # SyntaxError is here for the same reason: a checks module that will not
    # parse raises it, and it used to escape this guard and exit 1 on a
    # traceback. Moving the detectors into checks/ added two new places for that
    # to happen, so the guard covers both import-time failures and refuses the
    # way the rule set itself does rather than reporting a verdict it never
    # reached.
    sys.stdout.write("error  cannot load the checks at %s (%s), so nothing "
                     "was checked\n" % (os.path.dirname(
                         os.path.abspath(__file__)), _e))
    sys.exit(2)


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


def authz_note(s, src):
    """Advisory: a program that reads data but never checks authorization.

    Scoped to source-quoting programs. Only fires when the source carries an
    actual data read (SELECT / READ / a query FM), because a program that
    touches no data has nothing to authorize -- flagging it would be noise,
    and noise is what makes people skip notes.

    Absent AUTHORITY-CHECK is not by itself a defect: reporting programs run
    under S_TCODE, and anyone who can execute the transaction is already
    authorized to see its output. So this asks a question instead of
    asserting a verdict, which is the same bargain every other advisory here
    makes. A report that answers it in prose -- either way -- should say so,
    and silence is the thing worth flagging.
    """
    if not src:
        return None
    if re.search(r"\bAUTHORITY-CHECK\b", src, re.I):
        return None
    reads = re.search(r"\bSELECT\b|\bREAD\s+TABLE\b|"
                      r"\b(?:CL_SALV_TABLE|ZCL_.*DB|ZDB_.*SELECT)\b|"
                      r"\bCALL\s+FUNCTION\s+'(\w*SELECT\w*|REUSE_ALV\w*)'", src, re.I)
    if not reads:
        return None
    # Answered already? Naming the topic is not answering it. "不做权限控制"
    # states the absence and stops; the question is what follows from it. So the
    # bar is a consequence statement, not the word 权限.
    if re.search(r"越权|未受控|无权限隔离|看到全量|任何(?:能|可)运行|"
                 r"任意用户|全体用户|数据权限|SoD|职责分离", s):
        return None
    return ("the source reads data (SELECT/READ) but contains no "
            "AUTHORITY-CHECK. Whether that is a finding depends on the "
            "transaction's S_TCODE authorization -- if so, say so in the "
            "report; if the report says nothing about it, the question is "
            "unanswered.")


def ext_asset_note(s, src):
    """Advisory: a hardcoded external asset name with no existence guard.

    Bitmaps, icons and OData service names are objects that live in the
    target system, not in the source. Naming one as a string literal makes the
    program depend on something no compiler and no syntax check can see, so the
    usual guard is a check plus an exception handler around the call.

    Deliberately narrow: it wants the literal AND the absence of a guard in the
    neighbourhood, because most hardcoded names are fine and flagging all of
    them would be the note nobody reads.
    """
    if not src:
        return None
    names = set(re.findall(r"['\"]([ZIY](?:[A-Z0-9]+_)*N[A-Z0-9_]*(?:_LOGO(?:_SMALL|_LARGE|_ICON)?|_ICON|_BITMAP|_LOGO))['\"]",
                           src))
    if not names:
        return None
    guards = re.findall(r"\bTRY\b|\bAT\s+SELECTION-SCREEN\b|\bEXCEPTIONS\b", src, re.I)
    hits = sorted(names)
    shown = ", ".join(hits[:3]) + (f" (+{len(hits)-3} more)" if len(hits) > 3 else "")
    if not guards:
        return (f"the source names external asset(s) {shown} as literals, and has "
                f"no TRY/EXCEPTIONS anywhere: if the target system does not have "
                f"them, the failure appears at run time, not compile time. Say "
                f"whether each is guarded.")
    return (f"the source names external asset(s) {shown} as literals. The source "
            f"has {len(guards)} TRY/EXCEPTIONS guard(s) in total; check that each "
            f"named asset's call site is actually inside one, and say so in the "
            f"report.")


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
    try:
        s = read_report(path)
    except ReadError as e:
        die(str(e))
    bad = check(s)
    name = os.path.basename(path)
    notes = [n for n in (density_note(s, src), fidelity_note(s, src),
                         fix_lang_note(s), fix_mislabel_note(s, src),
                         authz_note(s, src), ext_asset_note(s, src)) if n]
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
    """A file that exists but cannot be read as utf-8.

    errors="replace" turned a bad encoding into a U+FFFD stream, and every
    quotation then failed to match it. The fidelity advisory reported
    fabrication where the failure was in the read, which is the one thing
    that advisory exists to catch.

    This was originally about the SOURCE only. The REPORT had the same defect
    for longer and worse: three call sites read it bare, so a report saved as
    cp936 -- which is what an editor's "save as" on a Chinese Windows produces,
    the same trap SKILL.md warns about for pasted source -- raised an uncaught
    UnicodeDecodeError and exited 1. Exit 1 is the code SKILL.md defines as
    "the check ran and found defects", so the caller went looking for defects
    that were never there. The rule set already refused this way by catching at
    import; the report had to learn it too, or the guarantee only covered one
    of the two files.
    """


def read_report(path):
    """Report text, or None when the path does not exist.

    Same refusal as read_src, for the same reason: a decode failure has to
    arrive as exit 2 through die(), never as a traceback exiting 1.
    """
    if not path or not os.path.exists(path):
        return None
    try:
        with io.open(path, encoding="utf-8", errors="strict", newline="") as fh:
            return fh.read()
    except UnicodeDecodeError as e:
        raise ReadError("%s is not readable as utf-8 (%s), so nothing "
                        "was checked" % (path, e)) from e


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
            try:
                s = read_report(p)
            except ReadError as e:
                die(str(e))
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
            raw = read_report(rep)
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
                     fix_lang_note(fixed), fix_mislabel_note(fixed, ssrc),
                     authz_note(fixed, ssrc), ext_asset_note(fixed, ssrc)):
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
        print("  note  no source recognised, so density, fidelity, fix-mislabel, "
              "authz and ext-asset were not run (pass the ABAP file after the "
              "report)")
    elif not src.strip():
        print("  note  %s is empty, so density and fidelity were not run"
              % srcs[0])
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
