#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Detect near-duplicate sections in a markdown file.

    python scripts/dedup.py FILE [--threshold 0.6] [--min-tokens 20]
    python scripts/dedup.py FILE --catalog DIR    # scan a directory

Compares every pair of sections by Jaccard similarity over their normalized
token sets. Sections above the threshold are printed with their headings and
an excerpt of each, so a reader can decide whether the overlap is a real
duplication or a legitimate cross-reference.

Exit codes:
  0  no pair exceeds the threshold
  1  at least one pair exceeds it; the summary line names them
  2  refused -- the path does not exist, is not UTF-8, is empty, or no
     sections could be extracted. "error" is the first line.

Why this exists: a skill or report that says the same thing twice in two
sections reads as thorough, but it is not. The word-count is a red herring.
report_qc.py checks report structure but has no detector for this -- the
word-count goes up while the information goes down. This is the tier-2
deduplication step in NVIDIA's SkillEvaluator three-tier model, reduced to
a self-contained token-overlap check that needs no embedding provider.

The threshold is deliberately conservative (0.6). Below it the comparison
is noise: two sections about "how to write ABAP" and "how to read ABAP"
share vocabulary but say different things. Above it they usually repeat.
Pass --threshold 0 to see every pair; that is how a reader calibrates the
default against their own corpus.

--catalog takes a directory of markdown files and reports cross-file
duplicates too. Without it only intra-file pairs are scored. Cross-file
duplicates are usually more important than intra-file ones, because the
reader is less likely to notice them.
"""
import argparse
import os
import re
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def _die(msg: str) -> None:
    print(f"error  {msg}")
    sys.exit(2)


def _read(path: Path) -> str:
    if not path.is_file():
        _die(f"path does not exist: {path}")
    if path.is_dir():
        _die(f"path is a directory, not a file: {path}")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        _die(f"file is not utf-8: {path}")
    except OSError as e:
        _die(f"file cannot be read: {path} ({e})")


_STOP = {"the", "a", "an", "is", "are", "of", "to", "in", "and", "or",
         "for", "with", "by", "on", "at", "from", "as", "it", "its",
         "this", "that", "these", "those", "be", "was", "were", "be",
         "been", "being", "have", "has", "had", "do", "does", "did",
         "will", "would", "can", "could", "may", "might", "shall",
         "should", "not", "no", "yes", "if", "else", "elif", "then",
         "when", "where", "which", "who", "whom", "what", "how", "why",
         "than", "too", "very", "also", "just", "into", "over", "under",
         "about", "up", "down", "out", "off", "again", "once", "here",
         "there", "all", "any", "some", "none", "each", "every", "own",
         "same", "other", "such", "only", "more", "most", "few", "many",
         "much", "well", "new", "old", "first", "last", "next", "next",
         "one", "two", "three", "four", "five", "six", "seven", "eight",
         "nine", "ten", "you", "your", "he", "she", "his", "her", "them",
         "we", "us", "our", "they", "their", "my", "me", "him", "i"}


def _tokens(text: str) -> set:
    """Lowercased alphanumeric tokens, stopwords removed.

    Chinese text is tokenized character-by-character, which is not real
    segmentation but is enough to distinguish sections that share Chinese
    vocabulary from sections that do not. A proper jieba cut would be
    better, but it is a dependency this skill does not otherwise carry.
    """
    text = text.lower()
    # Chinese: keep individual characters that look like CJK
    zh = re.findall(r"[\u4e00-\u9fff]", text)
    # Latin: word tokens
    en = re.findall(r"[a-z][a-z0-9_]+", text)
    tokens = {t for t in en if len(t) >= 2 and t not in _STOP}
    tokens.update(t for t in zh if len(t) >= 1)
    return tokens


def _split_sections(text: str):
    """Split on level-2 or level-3 headings.

    Returns a list of (heading, body) pairs. The heading is the first line
    of the section including its markers. Sections with no heading (the
    preamble) are skipped: a preamble is usually metadata and not prose
    that could duplicate another section.
    """
    out = []
    current = []
    current_heading = None
    for line in text.split("\n"):
        m = re.match(r"^(#{2,3})\s+(.+)$", line)
        if m:
            if current_heading is not None and current:
                out.append((current_heading, "\n".join(current)))
            current_heading = line.strip()
            current = []
        else:
            if current_heading is not None:
                current.append(line)
    if current_heading is not None and current:
        out.append((current_heading, "\n".join(current)))
    return out


def _excerpt(text: str, max_chars: int = 80) -> str:
    """First non-empty line of text, truncated to max_chars."""
    for ln in text.split("\n"):
        s = ln.strip()
        if s and not re.match(r"^#|^```", s):
            s = re.sub(r"\s+", " ", s)
            return s if len(s) <= max_chars else s[:max_chars - 1] + "…"
    return "(empty section)"


def _strip_markdown(text: str) -> str:
    """Remove markdown syntax before tokenizing.

    Headings, code fences, links, and emphasis all carry tokens that
    would otherwise pollute the comparison. A code fence is almost
    always language-specific and would make every code-heavy section
    look similar to every other.
    """
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"`[^`\n]*`", " ", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"[*_]{1,3}([^*_]+)[*_]{1,3}", r"\1", text)
    return text


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def scan(text: str, threshold: float, min_tokens: int):
    sections = _split_sections(text)
    if not sections:
        return [], []
    sections = [(h, b) for h, b in sections if len(_tokens(_strip_markdown(b))) >= min_tokens]
    if not sections:
        return [], []
    pairs = []
    for i in range(len(sections)):
        for j in range(i + 1, len(sections)):
            hi, bi = sections[i]
            hj, bj = sections[j]
            ti = _tokens(_strip_markdown(bi))
            tj = _tokens(_strip_markdown(bj))
            sim = _jaccard(ti, tj)
            if sim >= threshold:
                pairs.append((hi, hj, sim, _excerpt(bi), _excerpt(bj)))
    pairs.sort(key=lambda p: -p[2])
    return sections, pairs


def _scan_file(path: Path, threshold: float, min_tokens: int):
    text = _read(path)
    if not text.strip():
        _die(f"file is empty: {path}")
    sections, pairs = scan(text, threshold, min_tokens)
    return [(str(path), h, h2, sim, e1, e2)
            for (h, h2, sim, e1, e2) in pairs]


def _scan_dir(dirpath: Path, threshold: float, min_tokens: int):
    files = sorted(dirpath.glob("**/*.md"))
    if not files:
        _die(f"no markdown files under {dirpath}")
    all_sections = []
    for f in files:
        if not f.is_file():
            continue
        text = _read(f)
        if not text.strip():
            continue
        for h, b in _split_sections(text):
            tokens = _tokens(_strip_markdown(b))
            if len(tokens) >= min_tokens:
                all_sections.append((str(f), h, tokens, b))
    pairs = []
    for i in range(len(all_sections)):
        for j in range(i + 1, len(all_sections)):
            fi, hi, ti, bi = all_sections[i]
            fj, hj, tj, bj = all_sections[j]
            if fi == fj:
                continue  # cross-file only
            sim = _jaccard(ti, tj)
            if sim >= threshold:
                pairs.append((fi, hi, fj, hj, sim, _excerpt(bi), _excerpt(bj)))
    pairs.sort(key=lambda p: -p[4])
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detect near-duplicate sections in markdown")
    parser.add_argument("path", help="markdown file or directory")
    parser.add_argument("--threshold", type=float, default=0.6,
                        help="Jaccard similarity threshold (default: 0.6)")
    parser.add_argument("--min-tokens", type=int, default=20,
                        help="minimum token count for a section to be compared "
                             "(default: 20)")
    parser.add_argument("--catalog", action="store_true",
                        help="compare sections across files in the directory")
    args = parser.parse_args()

    if args.threshold < 0 or args.threshold > 1:
        _die(f"threshold must be in [0, 1], got {args.threshold}")
    if args.min_tokens < 1:
        _die(f"min-tokens must be >= 1, got {args.min_tokens}")

    p = Path(args.path)
    if p.is_dir():
        if not args.catalog:
            _die(f"path is a directory; pass --catalog to compare across files: {p}")
        pairs = _scan_dir(p, args.threshold, args.min_tokens)
    elif p.is_file():
        pairs = _scan_file(p, args.threshold, args.min_tokens)
    else:
        _die(f"path does not exist: {p}")

    if not pairs:
        print(f"PASS  {p}  (no pair above {args.threshold:.2f})")
        return 0

    print(f"{p}:")
    for entry in pairs:
        if p.is_dir():
            f1, h1, f2, h2, sim, e1, e2 = entry
            print(f"  {sim:.2f}  {f1} [{h1}]  <->  {f2} [{h2}]")
            print(f"           {e1}")
            print(f"           {e2}")
        else:
            _, h1, h2, sim, e1, e2 = entry
            print(f"  {sim:.2f}  {h1}  <->  {h2}")
            print(f"           {e1}")
            print(f"           {e2}")
    print()
    print(f"FAIL  {p}  ({len(pairs)} duplicate pair(s) above {args.threshold:.2f})")
    return 1


if __name__ == "__main__":
    sys.exit(main())
