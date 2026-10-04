"""Truncation detection, as a library, because a truncated report is worse than a
missing one: it is still a file, still gets counted, and still looks like data.

    import truncation; truncation.classify(report_text, source_text)

Three signals, because each alone can be fooled:

  sections   a complete report has all six. Missing a later section while having
             an earlier one means the write stopped.
  coverage   quoted abap blocks per 1000 source lines. A report that quotes almost
             nothing from a large source was cut, whatever its length.
  volume     report lines against source lines.

This started as a scan over four fixed directories, which is why it could not be
applied to a benchmark round at all. The predicate now lives here, once, and both
truncation_audit.py and gate_ab.py call it -- the same reason the gate's rules
live in schemas/report-contract.json rather than inside the checker. Two of this
project's seven checker/rule disagreements were a second copy of a rule.
"""
import io
import os
import re
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# section markers, duplicated from the contract on purpose: importing report_qc
# here would make this module depend on the gate's install path, and this is the
# one check that has to run when the gate is not the thing being tested.
SEC = ["## 一", "## 二", "## 三", "## 四", "## 五", "## 六"]

FENCE = re.compile(r"```.*?```", re.S)

# thresholds, measured rather than chosen
COVERAGE_MIN_SRC_LINES = 2000   # below this, blocks-per-1k is meaningless
COVERAGE_MIN_RATE = 3.0         # real2's AVE report quoted 0.09 against 1000
VOLUME_RATIO = 20.0             # "report lines >= source/20"; used by large-inputs.md


def count_blocks(report_text):
    """Quoted abap blocks. `lang` is ignored: a report may label them variously."""
    n = 0
    for m in FENCE.finditer(report_text):
        if m.group(0).lower().startswith("```abap"):
            n += 1
    return n


def classify(report_text, source_text=None):
    """(truncated: bool, reasons: list[str], facts: dict).

    source_text may be None when the source is unavailable; the volume and
    coverage signals are then skipped rather than guessed, and that fact is
    recorded in `facts` so a caller can see the check was partial.
    """
    nl = report_text.count("\n") + 1
    secs = sum(1 for h in SEC if h in report_text)
    blocks = count_blocks(report_text)
    facts = {"report_lines": nl, "sections": secs, "blocks": blocks,
             "source_lines": None, "blocks_per_1k": None}

    why = []
    if secs < 6:
        have = [h[-1] for h in SEC if h in report_text]
        why.append(f"only {secs}/6 sections (has {' '.join(have) or 'none'})")

    if source_text is None:
        facts["coverage_checked"] = False
    else:
        sl = source_text.count("\n") + 1
        rate = blocks / max(1, sl) * 1000
        facts["source_lines"] = sl
        facts["blocks_per_1k"] = rate
        facts["coverage_checked"] = True
        if sl > COVERAGE_MIN_SRC_LINES and rate < COVERAGE_MIN_RATE:
            why.append(f"quotes {rate:.2f} blocks/1k src lines "
                       f"({blocks} blocks for {sl} lines)")
        if nl < sl / VOLUME_RATIO:
            why.append(f"{nl} lines for a {sl}-line source")

    return bool(why), why, facts


def classify_file(report_path, source_path=None):
    r = io.open(report_path, encoding="utf-8", errors="replace").read()
    s = None
    if source_path and os.path.isfile(source_path):
        s = io.open(source_path, encoding="utf-8", errors="replace").read()
    return classify(r, s)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    rc = 0
    for spec in sys.argv[1:]:
        rep, _, src = spec.partition("=")
        trunc, why, facts = classify_file(rep, src or None)
        tag = "TRUNCATED" if trunc else "ok"
        print(f"{tag:10} {os.path.basename(rep)}")
        print(f"           sections {facts['sections']}/6  blocks {facts['blocks']}"
              f"  lines {facts['report_lines']}"
              + (f"  src {facts['source_lines']}"
                 + (f"  {facts['blocks_per_1k']:.2f} blk/1k"
                    if facts["blocks_per_1k"] is not None else "")
                 if facts["source_lines"] else "  src (not checked)"))
        for w in why:
            print(f"           - {w}")
        if trunc:
            rc = 1
    sys.exit(rc)