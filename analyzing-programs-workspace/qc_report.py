#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Check generated analysis reports against the analyzing-programs skill's rules.

Script-based on purpose: asking the writing subagent whether it complied is
exactly the wrong instrument. Every count below is derived from the file.

Usage: python qc_report.py Test-result/real/*.skill.md
"""
import io
import os
import re
import sys

TAG = re.compile(r"</?(?:br|b|i|u|em|strong|sub|sup|code|span)\s*/?>", re.I)
ROW = re.compile(r"^\|\s*(?:P[0-3][-.]?\d+|[\U0001F534\U0001F7E0\U0001F7E1\U0001F7E2])\s*\|", re.M)
LINENO = re.compile(r"\.abap:\d+|第\s*\d+\s*[-–]\s*\d+\s*行")
SEC = ["## 一", "## 二", "## 三", "## 四", "## 五", "## 六"]
LAYERS = ("做什么", "为什么", "风险与改进")

rows = []
for p in sys.argv[1:]:
    s = io.open(p, encoding="utf-8").read()
    name = os.path.basename(p)
    if len(name) > 44:
        name = name[:19] + ".." + name[-23:]

    pos = [m.start() for m in re.finditer(r"```abap\n", s)]
    consecutive = partial = 0
    for k, st in enumerate(pos):
        end = s.find("```", st + 8)
        nxt = pos[k + 1] if k + 1 < len(pos) else len(s)
        gap = s[end:nxt]
        if [l for l in LAYERS if l not in gap]:
            # two sub-patterns with different fixes:
            #  - nothing at all between two code blocks
            #  - prose present, but some of the three labels missing
            if len(gap.strip()) <= 20:
                consecutive += 1
            else:
                partial += 1

    mer = re.findall(r"```mermaid\n(.*?)```", s, re.S)
    labels = []
    for b in mer:
        labels += re.findall(r"\[([^\]]*)\]", b)
        labels += [m.group(1) for m in
                   re.finditer(r"participant\s+\S+\s+as\s+(.+)$", b, re.M)]
    unsafe = sum(1 for lab in labels if re.search(r"[<>#]", TAG.sub("", lab)))

    i, j = s.find("## 五"), s.find("## 六")
    sec5 = s[i:j] if (i >= 0 and j > i) else ""
    prows = len(ROW.findall(sec5))
    if prows == 0:
        tbl = [l for l in sec5.split("\n")
               if l.startswith("|") and not set(l) <= set("|- ")]
        prows = max(0, len(tbl) - 1)   # minus the header row
    if prows == 0:
        # the skill mandates the buckets and the subprogram label, not a table;
        # some reports use a numbered list instead
        prows = len(re.findall(r"^\s*\d+\.\s+\*\*", sec5, re.M))
    buckets = sum(1 for b in ("\U0001F534", "\U0001F7E0",
                              "\U0001F7E1", "\U0001F7E2") if b in sec5)

    rows.append((name, s.count("\n") + 1, len(s.encode()) // 1024,
                 sum(1 for h in SEC if h in s), len(pos),
                 consecutive + partial, consecutive, partial, unsafe,
                 len(LINENO.findall(s)), prows, buckets))

hdr = (f"{'report':44s}{'lines':>6}{'KB':>5}{'sec':>5}{'abap':>6}{'A8':>5}"
       f"{'cc':>4}{'pt':>4}{'mm':>4}{'ln':>4}{'prow':>6}{'buck':>5}")
print(hdr)
print("-" * len(hdr))
for r in rows:
    print(f"{r[0]:44s}{r[1]:6d}{r[2]:5d}{r[3]:5d}{r[4]:6d}"
          f"{r[5]:5d}{r[6]:4d}{r[7]:4d}{r[8]:4d}{r[9]:4d}{r[10]:6d}{r[11]:5d}")

tb = sum(r[4] for r in rows)
ta = sum(r[5] for r in rows)
print("-" * len(hdr))
print(f"{'TOTAL':44s}{'':6}{'':5}{'':5}{tb:6d}{ta:5d}"
      f"{sum(r[6] for r in rows):4d}{sum(r[7] for r in rows):4d}"
      f"{sum(r[8] for r in rows):4d}{sum(r[9] for r in rows):4d}")
print(f"\nA8 violation : {ta}/{tb} = {ta/max(1,tb)*100:.0f}% of abap blocks "
      f"lack all three layers")
print("  cc  consecutive code blocks, nothing between them")
print("  pt  prose present, some of the three labels missing")
print("  mm  Mermaid labels with a bare < > #")
print("  ln  location labels using line numbers")
print("  buck  priority buckets present out of 4")
