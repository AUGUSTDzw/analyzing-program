#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mine historical reports for patterns and suggest SKILL.md updates.

    python scripts/evolve.py [--results DIR] [--skill SKILL_MD]

Scans a directory of historical analysis reports, counts P0-P3 severity
occurrences, and outputs suggestions for how SKILL.md could be updated to
address recurring patterns. The suggestions are printed to stdout and are
never written to disk -- the caller decides whether to apply them.

Exit codes:
  0  the scan completed and suggestions were printed (even if empty)
  2  refused -- the results directory does not exist, contains no reports,
     or the skill file cannot be read. "error" is the first line.

Why this exists: a skill that never changes will not improve. The reports
in Test-result/ are the empirical record of what the skill found in
practice. A script that mines them for recurring patterns can suggest
updates that are grounded in evidence rather than speculation. SkillNet
and SkillReducer both use evolutionary loops, but they require a model
in the loop to apply the changes. This script is the first half of the
loop: it identifies what should change, and leaves the application to a
human reviewer.

The severity counts are extracted by pattern matching on "P0-", "P1-",
"P2-", "P3-" prefixes in markdown tables. This is not a perfect parser
-- it will miss items in prose and will count items in code fences --
but it is enough to see which severity levels recur across reports. A
more sophisticated parser would need to understand the report structure,
and that is what evolve.py is not for.

The suggestions are deliberately conservative. They name the pattern and
the count, and they say what a change might look like. They do not
rewrite SKILL.md. The caller reads the suggestions, decides whether they
make sense, and edits SKILL.md by hand or through a separate commit.
"""
import argparse
import os
import re
import sys
from collections import Counter
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

_SEVERITY_RE = re.compile(r"\b(P[0-3])-(\d+)\b")


def _die(msg: str) -> None:
    print(f"error  {msg}")
    sys.exit(2)


def _count_severities(text: str) -> Counter:
    """Count P0-P3 occurrences in text, ignoring code fences."""
    # Remove code fences to avoid counting examples.
    text = re.sub(r"```[\s\S]*?```", "", text)
    # Remove inline code to avoid counting identifiers.
    text = re.sub(r"`[^`\n]*`", "", text)
    counts = Counter()
    for match in _SEVERITY_RE.finditer(text):
        counts[match.group(1)] += 1
    return counts


def _scan_results(results_dir: Path):
    """Scan a directory for markdown reports and aggregate severity counts."""
    if not results_dir.is_dir():
        _die(f"results directory does not exist: {results_dir}")

    files = sorted(results_dir.rglob("*.md"))
    if not files:
        _die(f"no markdown reports under {results_dir}")

    all_counts = Counter()
    file_counts = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        counts = _count_severities(text)
        if counts:
            all_counts.update(counts)
            file_counts.append((f.name, counts))

    return all_counts, file_counts, files


def _read_skill(skill_path: Path) -> str:
    if not skill_path.is_file():
        _die(f"skill file does not exist: {skill_path}")
    try:
        return skill_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        _die(f"cannot read skill file: {e}")


def _generate_suggestions(all_counts: Counter, file_counts: list, skill_text: str) -> list:
    """Generate suggestions based on severity patterns."""
    suggestions = []

    if not all_counts:
        suggestions.append(
            "No P0-P3 items found in any report. Either the reports use a "
            "different severity scheme, or none were analyzed with the "
            "current skill. Consider updating the report template to use "
            "P0-P3 severity labels."
        )
        return suggestions

    total = sum(all_counts.values())

    # Suggestion 1: High P0 count suggests the skill is finding critical issues
    # that might need stronger guidance.
    p0_count = all_counts.get("P0", 0)
    if p0_count > 5:
        suggestions.append(
            f"P0 (critical) issues found in {p0_count} items across "
            f"{len(file_counts)} reports. Consider adding more specific "
            f"guidance in SKILL.md for the most common P0 patterns "
            f"(e.g., missing AUTHORITY-CHECK, SELECT in loops)."
        )
    elif p0_count == 0:
        suggestions.append(
            "No P0 issues found. Either the analyzed programs are clean, "
            "or the skill is not detecting critical issues. Consider "
            "reviewing the P0 detection criteria."
        )

    # Suggestion 2: P1 count relative to P0.
    p1_count = all_counts.get("P1", 0)
    if p1_count > p0_count * 2:
        suggestions.append(
            f"P1 issues ({p1_count}) outnumber P0 ({p0_count}) more than "
            f"2:1. This suggests the skill is finding many fixable issues "
            f"but relatively few critical ones. Consider whether P0 "
            f"detection is too narrow."
        )

    # Suggestion 3: P2/P3 count suggests many style/convention issues.
    p2p3 = all_counts.get("P2", 0) + all_counts.get("P3", 0)
    if p2p3 > p0_count + p1_count:
        suggestions.append(
            f"P2/P3 issues ({p2p3}) outnumber P0/P1 ({p0_count + p1_count}). "
            f"The skill is finding many style and convention issues. Consider "
            f"whether these should be reported as P2/P3 or grouped differently."
        )

    # Suggestion 4: Check if SKILL.md mentions severity levels.
    if "P0" not in skill_text or "P1" not in skill_text:
        suggestions.append(
            "SKILL.md does not explicitly define P0-P3 severity levels. "
            "Consider adding a section that explains what each severity "
            "means and gives examples, so future reports are consistent."
        )

    # Suggestion 5: If many reports have no severity items, the template may need work.
    empty_reports = len([f for f in file_counts if not f[1]])
    if empty_reports > len(file_counts) * 0.5:
        suggestions.append(
            f"{empty_reports} of {len(file_counts)} reports have no P0-P3 "
            f"items. Consider updating the report template to require "
            f"severity labels for all findings."
        )

    return suggestions


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mine historical reports for patterns and suggest SKILL.md updates")
    parser.add_argument("--results", default="Test-result",
                        help="directory of historical reports (default: Test-result)")
    parser.add_argument("--skill", default="SKILL.md",
                        help="path to SKILL.md (default: SKILL.md)")
    args = parser.parse_args()

    results_dir = Path(args.results)
    skill_path = Path(args.skill)

    all_counts, file_counts, files = _scan_results(results_dir)
    skill_text = _read_skill(skill_path)

    suggestions = _generate_suggestions(all_counts, file_counts, skill_text)

    print(f"scanned: {len(files)} report(s), {len(file_counts)} with P0-P3 items")
    print(f"total items: {sum(all_counts.values())}")
    print(f"  P0: {all_counts.get('P0', 0)}")
    print(f"  P1: {all_counts.get('P1', 0)}")
    print(f"  P2: {all_counts.get('P2', 0)}")
    print(f"  P3: {all_counts.get('P3', 0)}")
    print()

    if file_counts:
        print("per-report breakdown:")
        for name, counts in sorted(file_counts):
            total = sum(counts.values())
            parts = " ".join(f"{k}={v}" for k, v in sorted(counts.items()))
            print(f"  {name}: {total} ({parts})")
        print()

    if suggestions:
        print(f"suggestions ({len(suggestions)}):")
        for i, s in enumerate(suggestions, 1):
            print(f"  {i}. {s}")
    else:
        print("no suggestions: patterns look consistent with current SKILL.md")

    return 0


if __name__ == "__main__":
    sys.exit(main())
