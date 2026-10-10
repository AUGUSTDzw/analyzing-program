"""Advisories: things worth reading, and the one mode where one of them fails.

Contract IDs (schemas/report-contract.json) use hyphens; Python function names
use underscores. The mapping is 1:1:
  density    -> density_note
  fidelity   -> fidelity_note
  fix-lang   -> fix_lang_note
  authz      -> authz_note
  ext-asset  -> ext_asset_note
  fix-mislabel -> fix_mislabel_note [not in contract; internal only]

`die()`'s docstring says a note never stops the run, and it is right about the
failures it was written for: labelling a fatal error as a note let a caller that
greps for advisories collect hard failures as soft ones. The six note functions
here each return a string or None, and none of them prints; all_notes() returns
a list of whichever fired, and is the only thing here that returns a list. So
nothing in this module can exit anything -- a note here is a value, and the mode
that printed it decides what it is worth.

Five of the six are advisory wherever the gate runs. fidelity_note is the
exception, and deliberately so: --fidelity-only adjudicates it alone and
promotes it to a failure, exiting 1. That is the mode asking a question and
counting the answer, not a note deciding to stop the run -- which is why the
promotion lives in report_qc.py's --fidelity-only branch and not here. Plain mode
prints it as a note and its exit code is check()'s alone: 0 when the structure is
clean, 1 when check() found a defect, and nothing in between on this note's
account.

That mode is not fidelity having teeth. What 1.1.0 intends, and what Task 10
does, is splitting the note in two: PUNCT-ONLY stays advisory, SUBSTANTIVE gets
counted in plain mode's exit code. Until that lands, a report that invented an
ABAP statement prints "Check whether the report rewrote the source" and still
passes the structural pass.
"""
import re

from checks.contract import ANCHORS, DENSITY_FLOOR, FIX_LANG, LAYERS, QUOTE_LANG
from checks.text import (_claims, _flat, block_head, fence_spans, in_risk_layer,
                         inventory, line_of, prose_end, source_blocks)

# Same reason as the lists in contract.py and text.py: without one, `import *`
# into report_qc.py hands every name above to that module as well. check() and
# these advisories and all_notes() must be the only things the gate re-exports,
# and an explicit list turns a name that arrived by accident into a NameError at
# import.
__all__ = ["density_note", "fix_lang_note", "fix_mislabel_note", "authz_note",
           "ext_asset_note", "fidelity_note", "all_notes"]


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
    s_lower = s.lower()
    named = sum(1 for n in inv if n.lower() in s_lower)
    if d >= DENSITY_FLOOR:
        return None
    return (f"low density: {blocks} quoted block(s) for {len(inv)} declared "
            f"subprogram(s) = {d:.2f} each ({named} of them named in the text). "
            f"If the text reads as a list rather than a walkthrough, it is an "
            f"inventory, not an analysis.")


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


def all_notes(s, src=None):
    """Every advisory for this report, in the order they were printed before.

    report() and the --fix branch each spelled this list out by hand, in the
    same order. One list, defined once.

    That order is what both modes print, so changing it changes the gate's
    output in plain mode and --fix alike. test_contract_drift.py pins the
    order: reversing every note here fails a check. Do not reshuffle it on
    the way past.
    """
    out = []
    n = density_note(s, src)
    if n:
        out.append(n)
    n = fix_lang_note(s)
    if n:
        out.append(n)
    n = fix_mislabel_note(s, src)
    if n:
        out.append(n)
    n = authz_note(s, src)
    if n:
        out.append(n)
    n = ext_asset_note(s, src)
    if n:
        out.append(n)
    return out
