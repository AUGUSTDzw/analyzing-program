#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
recon.py - One-pass reconnaissance for an ABAP program analysis.

Covers Analysis Flow steps 1 and 2 in a single call: check the source, print it
numbered, then print the subprogram inventory that scripts/docgen.py produces.

    python scripts/recon.py SOURCE [-o OUTDIR]

Exit codes follow the rest of the gate, minus the middle one:
  0  done - the source is readable UTF-8 and the inventory was produced
  2  refused - the source cannot be read, is not UTF-8, is a directory, is a
     markdown file, is empty, or docgen refused. "error" is the first line.

There is no exit 1. This tool does not judge the report, so it has nothing to
report as a defect. A reader that treats every nonzero exit as "defects found"
would go looking for defects here that were never checked.

Everything that can refuse runs before anything is printed. The source is read
and checked first, then docgen runs, and only then is the output written. A
refusal preceded by a complete dump would spend a reader's whole context on a
run that turned out to be a refusal, and the reader could still take the dump
for a verdict. That second reading is the failure shape this project has had.

Why this exists: the encoding check, the numbered source, and the subprogram
inventory used to be three separate calls. The content is identical, only the
number of passes over the growing context changes. The inventory needed its own
call because docgen prints a four-line receipt and writes the inventory to a
file, so it had to be read back from disk.

Single source of truth: docgen generates the inventory. This script runs it as a
child and reads the file the child wrote, so a change to docgen's extraction
cannot drift from what a report is written against. Reimplementing the
extraction here would let the two diverge silently.

The header reports the total bytes this run will print, so a reader can decide
before reading whether the source belongs on the chunked path instead. It costs
running docgen first, which is why nothing is streamed: the total is only known
once the inventory is in hand.

Nothing is written except the docgen output file that docgen already writes. The
numbered dump is a view of the source, not a copy of it.

Current directory does not matter: this script locates docgen by its own path,
as do the scripts it replaces.
"""

from __future__ import annotations

import argparse
import io as _io
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent

for _stream in (sys.stdout, sys.stderr):
    try:
        # newline="" keeps print() writing a bare \n. Windows would otherwise turn
        # it into \r\n, so a dump line read byte for byte would carry a carriage
        # return the source never had -- and report_qc reads the source with
        # newline="", so the dump and the gate would disagree on it.
        _stream.reconfigure(encoding="utf-8", errors="replace", newline="")
    except (AttributeError, ValueError):
        pass


def _die(msg: str, code: int = 2) -> None:
    """Print an error and exit with code 2.

    On stdout, like report_qc.py and docgen.py: a caller that captures one
    stream and sees exit 2 should still see what was refused.
    """
    print(f"error  {msg}")
    sys.exit(code)


def _numbered(text: str) -> list[str]:
    """Split into physical lines without dropping trailing empties.

    splitlines() drops the final empty line of a file that ends in a newline.
    That shifts every later line number by one, so a quote written against this
    dump would not line up with the source the gate checks.
    """
    return text.split("\n")[:-1] if text.endswith("\n") else text.split("\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Print the source numbered and its subprogram inventory",
    )
    parser.add_argument("source", help="Path to ABAP source file")
    parser.add_argument("-o", "--output",
                        help="Output directory for the docgen file "
                             "(default: same directory as the source)")
    args = parser.parse_args()

    source_path = Path(args.source)

    # Every refusal is checked before anything is printed.
    if source_path.is_dir():
        _die(f"source path is a directory, not a source file: {source_path}")
    if not source_path.is_file():
        _die(f"source path does not exist: {source_path}")
    if source_path.suffix.lower() in (".md", ".markdown"):
        _die(f"source is a markdown file, not ABAP: {source_path} "
             f"(check a report with scripts/report_qc.py)")
    try:
        raw = source_path.read_bytes()
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        _die(f"source is not utf-8: {source_path}")
    if not text.strip():
        _die(f"source is empty: {source_path} (nothing to analyse)")

    lines = _numbered(text)

    # Docgen runs before the dump is written, so a docgen failure refuses with no
    # output at all instead of after the whole source has gone out. It also has
    # to run first for the total below to be knowable.
    outdir = Path(args.output) if args.output else source_path.parent
    child = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "docgen.py"),
         "--type", "onboarding", "-o", str(outdir), str(source_path)],
        capture_output=True, text=True, encoding="utf-8",
    )
    if child.returncode != 0:
        sys.stdout.write(child.stdout)
        _die(f"docgen exited {child.returncode}")

    doc_file = outdir / f"{source_path.stem}.onboarding.md"
    if not doc_file.is_file():
        # docgen returns 0 after writing, so success without a file means it
        # wrote somewhere this script did not look. Reporting it as a refusal is
        # the only honest answer: the inventory is not in hand.
        _die(f"docgen reported success but wrote no file at {doc_file}")

    inventory = doc_file.read_text(encoding="utf-8").rstrip()

    prefix = f"== SOURCE  {source_path}\n"
    dump = "".join(f"{n:>5} | {line}\n" for n, line in enumerate(lines, 1))
    inv_hdr = "== SUBPROGRAM INVENTORY  (scripts/docgen.py --type onboarding)\n"
    receipt = f"== docgen wrote {doc_file} ({doc_file.stat().st_size} bytes)\n"
    inv_bytes = len(inventory.encode("utf-8"))

    # The summary line carries the total, and the total includes the summary
    # line, so converge on the digit count. Lengths are taken of the utf-8
    # encoding: the dump carries the source's own characters, and a Chinese
    # comment is one character but three bytes.
    def summary(total):
        return (f"== {len(lines)} line(s), {len(raw)} bytes, utf-8 ok, "
                f"output {total} bytes, inventory {inv_bytes} bytes\n")

    parts = (prefix, dump, "\n", inv_hdr, inventory, "\n\n", receipt)
    total = 0
    for _ in range(8):
        t = sum(len(s.encode("utf-8")) for s in parts) + len(summary(total).encode("utf-8"))
        if t == total:
            break
        total = t

    output = (prefix + summary(total) + dump + "\n"
              + inv_hdr + inventory + "\n\n" + receipt)
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
