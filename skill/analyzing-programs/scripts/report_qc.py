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

Detectors live in checks/ and are shared by both modes on purpose. An
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
    from checks.structure import check                          # noqa: F401
    # `import *` skips every underscore-prefixed name and nothing below needs
    # one. Worth knowing before that stops being true: a detector written here
    # that reached for _flat or _claims would resolve neither, and say so with a
    # NameError at the first call rather than at import.

    # all_notes() builds the advisory list this file used to spell out twice.
    # fidelity_note is named for --fidelity-only, which adjudicates it alone and
    # promotes it to a failure. The other five are called from inside all_notes
    # rather than here, and are imported so this module stays the gate's whole
    # surface: test_contract_drift.py reads them off the module it loads, and an
    # advisory the gate can no longer reach by name is the drift that suite
    # exists to catch. Naming all six keeps that surface uniform rather than
    # importing only the ones a given test happens to list today.
    from checks.advisory import (all_notes, authz_note, density_note,  # noqa: F401
                                 ext_asset_note, fidelity_note, fix_lang_note,
                                 fix_mislabel_note)
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


# ------------------------------------------------------------------- fixing

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
    notes = all_notes(s, src)
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
        for note in all_notes(fixed, ssrc):
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
