#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify and repair reports written against the analyzing-programs skill.

Script-based on purpose. Asking a model whether it followed the skill is exactly
the wrong instrument: across runs on one file the same skill scored 0.700 /
0.625 / 0.650 recall, and different models drift further still. Normative text
cannot be the enforcement mechanism for output that varies; a deterministic gate
can. Anything a script can decide, decide here, so the model spends its
judgement only on the parts that need judgement.

Two modes:

    python report_qc.py REPORT [REPORT ...]          check, list every defect
    python report_qc.py --fix REPORT SOURCE [-o OUT] check, and repair the
                                                   classes that cannot change
                                                   meaning

Repair is deliberately narrow. A line-number location label and a bare ``<`` in
a Mermaid label are both violations the skill states without exception, so
rewriting them cannot alter meaning. An A8 three-layer violation is different:
the fix needs to know what the prose after the block was meant to say, and
guessing re-labels a risk discussion as a description. Those are reported with
line numbers and left to the model.

Detectors live in this one file and are shared by both modes on purpose. An
earlier version kept the checker and the fixer in separate scripts with separate
regexes; they drifted, and the fixer silently missed a form the checker caught.

Exit codes are the contract with the caller, and SKILL.md step 6 tells the model
to re-run this script until it is clean. So every mode must report the verdict
in the exit status as well as in stdout: 0 only when nothing is left to fix. A
mode that returns 0 after printing FAIL gives the caller a termination signal
that is always green.

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

SEC = ["## 一", "## 二", "## 三", "## 四", "## 五", "## 六"]
LAYERS = ("做什么", "为什么", "风险与改进")
BUCKETS = ("\U0001F534", "\U0001F7E0", "\U0001F7E1", "\U0001F7E2")

# Fence language decides whether a fence quotes source or illustrates a proposed
# fix. Position exempts nothing: a block after a 风险与改进 label is indistinguishable
# from the next sub-step's real quote, and the positional exemption used to skip
# genuine quotes wholesale (12 of 138 statements inspected on a report carrying
# 20 blocks). A mislabeled fix is caught by fix_lang_note instead of being
# silently trusted.
QUOTE_LANG = "abap"
FIX_LANG = "abap-fix"

FENCE = re.compile(r"```.*?```", re.S)
TICK = re.compile(r"`([^`\n]{2,80})`")
TAG = re.compile(r"</?(?:br|b|i|u|em|strong|sub|sup|code|span)\s*/?>", re.I)
ROW = re.compile(r"^\|\s*(?:P[0-3][-.]?\d+|[\U0001F534\U0001F7E0\U0001F7E1\U0001F7E2])\s*\|", re.M)

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
LAYERS = tuple(CONTRACT["layers"]["labels"])
BUCKETS = tuple(CONTRACT["problem_section"]["buckets"])
PSEC = CONTRACT["problem_section"]["heading"]
# The English spellings require whitespace. Allowing \s* let `lines?\s*\d+` match
# LINE1 and LINE2, which are identifiers, and report them as line citations.
LINE_NUM = re.compile(
    "|".join("(?:%s)" % p["regex"]
             for p in CONTRACT["forbidden_in_location_labels"]["patterns"]), re.I)
FULLWIDTH = CONTRACT["mermaid"]["fullwidth"]
DENSITY_FLOOR = next(a["floor_blocks_per_subprogram"] for a in
                     CONTRACT["advisories"] if a["id"] == "density")
# A bare digit range is legitimate when describing a file's size, so only the
# explicit citation forms above count.
CITE_NUM = re.compile(r"^\s*(?:L|line|lines|第)?\s*(\d{2,5})\s*(?:行|lines?)?\s*$", re.I)

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
    for m in re.finditer(r"participant\s+\S+\s+as\s+(.+)$", block, re.M):
        out.append((m.group(1), m.start(1)))
    return out


def inventory(src):
    """Subprogram names declared in the source, in order of first appearance."""
    out = []
    for rx, _ in ANCHORS[:5]:
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
        return None          # classic screen flow: MODULE / INCLUDE, not methods
    blocks = len(list(source_blocks(s)))
    d = blocks / len(inv)
    named = sum(1 for n in inv if n.lower() in s.lower())
    if d >= DENSITY_FLOOR:
        return None
    return (f"low density: {blocks} quoted block(s) for {len(inv)} declared "
            f"subprogram(s) = {d:.2f} each ({named} of them named in the text). "
            f"If the text reads as a list rather than a walkthrough, it is an "
            f"inventory, not an analysis.")


def blank_fences(s):
    """Same length as s, with code fence bodies blanked."""
    return FENCE.sub(lambda m: "\x00" * len(m.group(0)), s)


def label_spans(s):
    """Backticked spans outside fences: where location labels live."""
    return [m.group(1) for m in TICK.finditer(blank_fences(s))]


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


def source_blocks(s):
    """Yield (block_start, block_end, gap_text) for fences quoting source.

    Fence language is the only admission test. An earlier version also exempted
    any block sitting in the 风险与改进 layer, which is where a proposed fix lives
    -- but so does the next sub-step's real quote, and the exemption skipped that
    one too. Nothing structural can tell the two apart, so the report says which
    it is in the language of the fence.
    """
    pos = [m.start() for m in re.finditer(r"```%s\n" % QUOTE_LANG, s)]
    for k, st in enumerate(pos):
        end = s.find("```", st + 8)
        if end < 0:
            continue
        nxt = pos[k + 1] if k + 1 < len(pos) else len(s)
        yield st, end + 3, s[end + 3:nxt]


def line_of(s, off):
    return s.count("\n", 0, off) + 1


# ------------------------------------------------------------------- checking

def check(s):
    """Return a list of (kind, line, detail). Empty means clean."""
    bad = []

    present = sum(1 for h in SEC if h in s)
    if present < 6:
        missing = [h[3:] for h in SEC if h not in s]
        bad.append(("sec", 0, f"missing section(s): {', '.join(missing)}"))

    for st, end, gap in source_blocks(s):
        miss = [l for l in LAYERS if l not in gap]
        if not miss:
            continue
        ln = line_of(s, st)
        kind = "A8-cc" if len(gap.strip()) <= 20 else "A8-pt"
        bad.append((kind, ln,
                    "no prose at all before the next block" if kind == "A8-cc"
                    else "prose present, missing label(s): " + " ".join(miss)))

    for m in re.finditer(r"```mermaid\n(.*?)```", s, re.S):
        base = line_of(s, m.start())
        blk = m.group(1)
        for lab, off in mermaid_labels(blk):
            clean = TAG.sub("", lab)
            if re.search(r"[<>#]", clean):
                bad.append(("mm", base + blk[:off].count("\n"),
                            "Mermaid label holds a bare < > or #: "
                            + repr(clean.strip()[:40])))

    for sp in label_spans(s):
        if LINE_NUM.search(sp):
            bad.append(("ln", 0, f"location label cites a line number: {sp[:40]!r}"))

    i, j = s.find("## 五"), s.find("## 六")
    sec5 = s[i:j] if (i >= 0 and j > i) else ""
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
    """
    marks = anchors_of(src)
    if not marks:
        return s, 0, ["source has no recognisable construct to anchor to"]
    masked = blank_fences(s)
    edits = []
    skipped = []
    for m in TICK.finditer(masked):
        inner = m.group(1)
        if not LINE_NUM.search(inner):
            continue
        cm = CITE_NUM.match(inner)
        if not cm:
            skipped.append(inner)
            continue
        a = anchor_for(marks, int(cm.group(1)))
        if not a:
            skipped.append(inner)
            continue
        edits.append((m.start(), m.end(), "`" + a + "`"))
    if not edits:
        return s, 0, skipped
    out = s
    for a, b, rep in reversed(edits):
        out = out[:a] + rep + out[b:]
    return out, len(edits), skipped


# Lines that assert nothing about the source, so a fidelity pass must skip them.
ELIDE = re.compile(r"\.\.\.|\u2026")
PAREN_NOTE = re.compile(r"^[\s|*]*[\uff08(].*[\uff09)]\s*$")
CJK = re.compile(r"[\u4e00-\u9fff]")
# The source writes "t_documents ," with a space before the comma; the report
# writes "t_documents,". Punctuation spacing, not a rewritten statement.
PUNCT = re.compile(r"\s+([,;:)])")


def _flat(s):
    s = re.sub(r"\s+", " ", s).strip().lower()
    s = PUNCT.sub(r"\1", s)
    return re.sub(r"([(])\s+", r"\1", s)


def _claims(body):
    out = []
    for raw in body.split("\n"):
        if ELIDE.search(raw):
            continue                    # skill-permitted boilerplate elision
        l = re.sub(r'^\s*[*"\'"]', "", raw).rstrip()
        if len(l.strip()) < 3 or PAREN_NOTE.match(l):
            continue
        if CJK.search(l) and "|" not in l:
            continue                    # the report's own commentary
        if l.count('"') % 2:
            continue                    # unbalanced quote: layout debris
        out.append(l)
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
    for m in re.finditer(r"```%s\n(.*?)```" % QUOTE_LANG, s, re.S):
        base = s[:m.start()].count("\n") + 1
        for i, l in enumerate(_claims(m.group(1))):
            n += 1
            probe = l.strip().rstrip(".")
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
    for m in re.finditer(r"```%s\n" % QUOTE_LANG, s):
        if not in_risk_layer(block_head(s, m.start())):
            continue
        nxt = s.find("\n#", m.end())
        tail = s[m.end():nxt] if nxt > 0 else s[m.end():]
        if all(l in tail for l in LAYERS):
            continue
        hits.append(m.start())
    if not hits:
        return None
    ln = line_of(s, hits[0])
    more = f" (+{len(hits)-1} more)" if len(hits) > 1 else ""
    return (f"{len(hits)} {QUOTE_LANG} fence(s) sit inside a 风险与改进 layer{more}, "
            f"first at line {ln}. If one illustrates a proposed fix, tag it "
            f"{FIX_LANG}: unlabelled, it is probed against the source and reads "
            f"as fabricated.")


def fix_mm(s):
    """Convert bare < > # in Mermaid display text to their full-width forms.

    The skill prescribes full-width conversion, not quoting, and states the ban
    without exception -- there is no "already quoted, so exempt" allowance. An
    earlier version had such a guard, which made it skip exactly the labels that
    began with a quote and still held a bare '>' inside: the checker flagged
    those and the fixer declined them. Third drift between the two halves of
    this file, all from the same cause.
    """
    lines = s.split("\n")
    n = 0
    inside = False
    for i, ln in enumerate(lines):
        st = ln.strip()
        if st.startswith("```mermaid"):
            inside = True
            continue
        if st.startswith("```"):
            inside = False
            continue
        if not inside or not re.search(r"[<>#]", ln):
            continue
        edits = []
        for lab, off in mermaid_labels(ln):
            if not re.search(r"[<>#]", lab):
                continue
            edits.append((off, off + len(lab),
                          "".join(FULLWIDTH.get(c, c) for c in lab)))
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
    s, n, sk = fix_ln(s, src)
    if sk:
        notes.append(f"ln: {len(sk)} citation(s) had no usable anchor, left alone")
    s, m = fix_mm(s)
    return s, n + m, notes


# ----------------------------------------------------------------------- main

def report(path, src=None):
    s = io.open(path, encoding="utf-8").read()
    bad = check(s)
    name = os.path.basename(path)
    notes = [n for n in (density_note(s, src), fidelity_note(s, src),
                         fix_lang_note(s)) if n]
    if not bad:
        print(f"PASS  {name}")
        for n in notes:
            print(f"  note  {n}")
        return 0
    order = {"sec": 0, "prow": 1, "buck": 2, "ln": 3, "mm": 4, "A8-cc": 5, "A8-pt": 6}
    for kind, ln, detail in sorted(bad, key=lambda x: (order.get(x[0], 9), x[1])):
        where = f"line {ln}" if ln else "document"
        print(f"  {kind:6} {where:>10}  {detail}")
    print(f"FAIL  {name}  ({len(bad)} defect(s))")
    for n in notes:
        print(f"  note  {n}")
    return len(bad)


def read_src(path):
    if not path or not os.path.exists(path):
        return None
    return io.open(path, encoding="utf-8", errors="replace").read()


def die_note(msg):
    print(f"  note  {msg}")
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
        # argv is [prog, --fidelity-only, REPORT, SOURCE], and args drops argv[0]
        src = read_src(args[2]) if len(args) > 2 else None
        if not src:
            die_note("fidelity needs a source path: "
                     "--fidelity-only REPORT SOURCE.abap")
        rc = 0
        for p in [x for x in args[1:] if not x.lower().endswith(".abap")]:
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
        rest = [a for a in args[1:] if a != "-o"]
        if "-o" in args:
            out = args[args.index("-o") + 1]
        else:
            out = None
        if len(rest) < 2:
            print("--fix needs REPORT and SOURCE")
            return 2
        rep, src = rest[0], rest[1]
        s = io.open(rep, encoding="utf-8").read()
        fixed, n, notes = fix(s, io.open(src, encoding="utf-8", errors="replace").read())
        for nt in notes:
            print("note:", nt)
        dest = out or rep
        io.open(dest, "w", encoding="utf-8").write(fixed)
        print(f"repaired {n} mechanical defect(s) -> {dest}")
        left = check(fixed)
        if left:
            print(f"{len(left)} defect(s) need the model, listed above/below:")
            for kind, ln, detail in left:
                where = f"line {ln}" if ln else "document"
                print(f"  {kind:6} {where:>10}  {detail}")
        else:
            print("all checks now pass")
        note = density_note(fixed, src)
        if note:
            print("note:", note)
        # Repaired what could be repaired; whatever is left needs the model, and
        # the caller has to be able to see that. Returning 0 here made a partial
        # repair indistinguishable from a finished one.
        return 1 if left else 0

    src = read_src(args[1]) if len(args) > 1 and args[1].lower().endswith(".abap") else None
    rc = 0
    for p in args:
        if p.lower().endswith(".abap"):
            continue
        rc += report(p, src) and 1
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
