#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build and query a search index over references/ markdown files.

    python scripts/index.py build DIR [--output index.json]
    python scripts/index.py query INDEX_DIR QUERY [--top 5]

build mode scans a directory of markdown files, extracts every level-2 and
level-3 section, and writes an index.json that maps sections to their token
sets. query mode reads the index and returns the top-N sections ranked by
TF-IDF score against the query.

Exit codes:
  0  the command ran cleanly (build wrote the index, query returned results)
  2  refused -- the path does not exist, the index is corrupt, or no
     sections could be extracted. "error" is the first line.

Why this exists: references/ holds 8 markdown files totaling over 50 KB. A
reader who needs one specific rule has to grep through all of them. This
index makes the lookup a single command. The ranking is deliberately simple
(TF-IDF over character-level tokens) because a more sophisticated model
would need an embedding provider, and this skill is self-contained.

The index is a JSON file, not a database. It is meant to be checked in with
the skill, regenerated when references/ changes, and read by query mode
without any external dependency. The token set for each section is stored
inline so query mode does not need to re-read the source files.

Chinese text is tokenized character-by-character, which is not real
segmentation but is enough to rank sections that share Chinese vocabulary
above sections that do not. A proper jieba cut would be better, but it is a
dependency this skill does not otherwise carry.
"""
import argparse
import json
import math
import os
import re
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

_STOP = {"the", "a", "an", "is", "are", "of", "to", "in", "and", "or",
         "for", "with", "by", "on", "at", "from", "as", "it", "its",
         "this", "that", "these", "those", "be", "was", "were", "been",
         "being", "have", "has", "had", "do", "does", "did", "will",
         "would", "can", "could", "may", "might", "shall", "should",
         "not", "no", "yes", "if", "else", "elif", "then", "when",
         "where", "which", "who", "whom", "what", "how", "why", "than",
         "too", "very", "also", "just", "into", "over", "under", "about",
         "up", "down", "out", "off", "again", "once", "here", "there",
         "all", "any", "some", "none", "each", "every", "own", "same",
         "other", "such", "only", "more", "most", "few", "many", "much",
         "well", "new", "old", "first", "last", "next", "one", "two",
         "three", "four", "five", "six", "seven", "eight", "nine", "ten",
         "you", "your", "he", "she", "his", "her", "them", "we", "us",
         "our", "they", "their", "my", "me", "him", "i"}


def _die(msg: str) -> None:
    print(f"error  {msg}")
    sys.exit(2)


def _read_md(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise
    except OSError as e:
        _die(f"cannot read {path}: {e}")


def _tokens(text: str) -> set:
    """Lowercased alphanumeric tokens, stopwords removed.

    Chinese text is tokenized character-by-character. A proper jieba cut
    would be better, but it is a dependency this skill does not carry.
    """
    text = text.lower()
    zh = re.findall(r"[\u4e00-\u9fff]", text)
    en = re.findall(r"[a-z][a-z0-9_]+", text)
    tokens = {t for t in en if len(t) >= 2 and t not in _STOP}
    tokens.update(t for t in zh)
    return tokens


def _split_sections(text: str):
    """Split on level-2 or level-3 headings. Returns (heading, body) pairs."""
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


def _strip_markdown(text: str) -> str:
    """Remove markdown syntax before tokenizing."""
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"`[^`\n]*`", " ", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"[*_]{1,3}([^*_]+)[*_]{1,3}", r"\1", text)
    return text


def _build_index(dirpath: Path) -> dict:
    """Scan dirpath for .md files, extract sections, return index dict."""
    if not dirpath.is_dir():
        _die(f"path is not a directory: {dirpath}")
    files = sorted(dirpath.glob("**/*.md"))
    if not files:
        _die(f"no markdown files under {dirpath}")
    index_files = []
    for f in files:
        if not f.is_file():
            continue
        try:
            text = _read_md(f)
        except UnicodeDecodeError:
            continue
        if not text.strip():
            continue
        sections = []
        for heading, body in _split_sections(text):
            tokens = _tokens(_strip_markdown(body))
            if not tokens:
                continue
            sections.append({
                "heading": heading,
                "text_preview": body[:200].replace("\n", " ").strip(),
                "tokens": sorted(tokens)
            })
        if sections:
            index_files.append({
                "path": str(f.relative_to(dirpath.parent)) if dirpath.name != "." else str(f),
                "sections": sections
            })
    if not index_files:
        _die(f"no sections extracted from {dirpath}")
    return {
        "version": "1.0",
        "root": str(dirpath.resolve()),
        "files": index_files
    }


def _cmd_build(args) -> int:
    dirpath = Path(args.dir)
    index = _build_index(dirpath)
    output = args.output
    if not output:
        output = os.path.join(dirpath, "index.json")
    try:
        with open(output, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=1)
    except OSError as e:
        _die(f"cannot write index: {e}")
    n_files = len(index["files"])
    n_sections = sum(len(f["sections"]) for f in index["files"])
    print(f"built index: {n_files} file(s), {n_sections} section(s) -> {output}")
    return 0


def _cmd_query(args) -> int:
    index_path = Path(args.index)
    if not index_path.is_file():
        _die(f"index file does not exist: {index_path}")
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            index = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        _die(f"index file is not parseable: {e}")

    if "files" not in index or not isinstance(index["files"], list):
        _die("index file is missing `files` list")

    query_tokens = _tokens(_strip_markdown(args.query))
    if not query_tokens:
        _die(f"query has no searchable tokens: {args.query!r}")

    # Compute IDF across all sections.
    all_sections = []
    for f in index["files"]:
        for s in f.get("sections", []):
            if "tokens" in s and s["tokens"]:
                all_sections.append((f, s))

    if not all_sections:
        _die("index has no sections with tokens")

    n_sections = len(all_sections)
    df = {}
    for _, s in all_sections:
        for t in s["tokens"]:
            df[t] = df.get(t, 0) + 1

    def idf(token):
        return math.log(n_sections / (1 + df.get(token, 0)))

    # Score each section: count matching query tokens weighted by IDF.
    # A term that appears in every section has zero discriminative power,
    # so it gets zero weight. A term that appears in one section gets
    # maximum weight. This is the standard IDF formula.
    results = []
    for f, s in all_sections:
        sec_tokens = set(s["tokens"])
        score = 0.0
        for qt in query_tokens:
            if qt in sec_tokens:
                score += max(idf(qt), 0.1)  # floor at 0.1 so matches always score
        if score > 0:
            results.append((score, f["path"], s["heading"], s.get("text_preview", "")))

    results.sort(key=lambda r: -r[0])
    top = results[:args.top]

    if not top:
        print(f"no matches for: {args.query}")
        return 0

    for score, path, heading, preview in top:
        print(f"{score:.3f}  {path}")
        print(f"        {heading}")
        if preview:
            print(f"        {preview[:120]}")
    print()
    print(f"{len(results)} match(es), showing top {len(top)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build and query a search index over references/")
    sub = parser.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="build the index from a directory")
    b.add_argument("dir", help="directory of markdown files")
    b.add_argument("--output", help="output index.json path")

    q = sub.add_parser("query", help="query the index")
    q.add_argument("index", help="path to index.json")
    q.add_argument("query", help="search query")
    q.add_argument("--top", type=int, default=5, help="number of results")

    args = parser.parse_args()
    if args.cmd == "build":
        return _cmd_build(args)
    elif args.cmd == "query":
        return _cmd_query(args)
    else:
        parser.print_help()
        return 2


if __name__ == "__main__":
    sys.exit(main())
