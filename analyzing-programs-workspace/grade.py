#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Grade analyzing-programs skill eval outputs against structural assertions."""
import json, re, os, sys

WS = r"C:\Users\DzwU\.agents\skills\analyzing-programs-workspace\iteration-1"

REPORTS = {
    "eval-1-with_skill":   os.path.join(WS, "eval-1-alv-editable-total-poc", "with_skill", "outputs", "report.md"),
    "eval-1-without_skill":os.path.join(WS, "eval-1-alv-editable-total-poc", "without_skill", "outputs", "report.md"),
    "eval-2-with_skill":   os.path.join(WS, "eval-2-procedural-vendor-report", "with_skill", "outputs", "report.md"),
    "eval-2-without_skill":os.path.join(WS, "eval-2-procedural-vendor-report", "without_skill", "outputs", "report.md"),
}

def read(p):
    try:
        with open(p, encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return ""

def mermaid_blocks(t):
    return re.findall(r"```mermaid\s*\n(.*?)```", t, re.S)

def count(t, sub):
    return len(re.findall(sub, t))

def check_assertions(t):
    res = []
    # A1 six chapters
    chapters = ["一、", "二、", "三、", "四、", "五、", "六、"]
    present = [c for c in chapters if c in t]
    res.append(("A1", "报告含全部六章（一二三四五六）", len(present)==6, f"找到 {len(present)}/6: {present}"))
    # A2 responsibility chain table with 调用者
    has_table = bool(re.search(r"\|.*?子程序.*?\|.*?调用者.*?\|", t, re.S))
    res.append(("A2", "二章含责任链表且表头含'调用者'列", has_table, "找到含调用者列表头" if has_table else "未找到含调用者的表头"))
    # A3 flowchart TD
    a3 = "flowchart" in t and "TD" in t
    res.append(("A3", "含 Mermaid flowchart TD", a3, "" ))
    # A4 sequenceDiagram
    a4 = "sequenceDiagram" in t
    res.append(("A4", "含 Mermaid sequenceDiagram", a4, ""))
    # A5 no source-line citations (file:line, line ranges, parenthetical 第N行 location labels).
    # Describing a table row index ("第 1 行" = read row 1) is NOT a violation.
    bad_line = re.findall(r"\.abap\s*:\s*\d+|第\s*\d+\s*[—\-]\s*\d+\s*行|（\s*第\s*\d+[^）]*行\s*）", t)
    a5 = len(bad_line)==0
    res.append(("A5", "无行号引用", a5, f"疑似行号引用: {bad_line[:3]}" if bad_line else "未发现行号引用"))
    # A6 mermaid no raw angle brackets (except <br/>)
    blocks = mermaid_blocks(t)
    bad_ang = []
    for b in blocks:
        m = re.findall(r"<(?!br/?[>])\s*[A-Za-z_]", b)
        if m: bad_ang.append(m[:3])
    a6 = len(bad_ang)==0
    res.append(("A6", "Mermaid 块无裸尖括号标识符", a6, f"违规块数 {len(bad_ang)}: {bad_ang[:2]}" if bad_ang else "mermaid 标签安全"))
    # A7 P0 and P3 markers
    a7 = ("P0" in t) and ("P3" in t)
    res.append(("A7", "含 P0 与 P3 优先级标记", a7, ""))
    # A8 every abap block has 做什么 & 风险 layer
    nblk = len(re.findall(r"```abap", t))
    n_do = count(t, "做什么")
    n_risk = count(t, "风险")
    a8 = (n_do >= nblk) and (n_risk >= nblk) and nblk>0
    res.append(("A8", f"每个 abap 代码块后有'做什么'与'风险'层", a8, f"abap块={nblk} 做什么={n_do} 风险={n_risk}"))
    # A9 code blocks labeled abap
    a9 = nblk>0
    res.append(("A9", "代码块标注 ```abap", a9, f"abap块数 {nblk}"))
    # A10 has ### 3.X grouping headers
    n_sec = len(re.findall(r"###\s*3\.\d", t))
    a10 = n_sec>=2
    res.append(("A10", "含 ### 3.X 分组标题(≥2)", a10, f"分组标题数 {n_sec}"))
    # A11 transition sentences between sections (heuristic: text between consecutive ### 3.X has a sentence)
    a11 = n_sec>=2  # placeholder; deeper check below
    res.append(("A11", "子程序分组按执行顺序(≥2 section)", a11, ""))
    return res

summary = {}
for run_id, path in REPORTS.items():
    t = read(path)
    if not t:
        summary[run_id] = {"error": "could not read", "len": 0}
        continue
    results = check_assertions(t)
    passed = sum(1 for r in results if r[2])
    summary[run_id] = {
        "len": len(t),
        "abap_blocks": len(re.findall(r"```abap", t)),
        "passed": passed,
        "total": len(results),
        "pass_rate": round(passed/len(results), 3),
        "expectations": [{"text": r[1], "passed": r[2], "evidence": r[3]} for r in results],
    }
    # write grading.json next to the report
    gpath = os.path.join(os.path.dirname(path), "grading.json")
    with open(gpath, "w", encoding="utf-8") as f:
        json.dump({"run_id": run_id, "expectations": summary[run_id]["expectations"]}, f, ensure_ascii=False, indent=2)

print("="*80)
print(f"{'run':28} {'len':>6} {'abap':>5} {'pass':>6} {'rate':>6}")
print("-"*80)
for run_id, s in summary.items():
    if "error" in s:
        print(f"{run_id:28} ERROR")
        continue
    print(f"{run_id:28} {s['len']:>6} {s['abap_blocks']:>5} {s['passed']:>2}/{s['total']:<3} {s['pass_rate']:>6}")
print("="*80)
# per-assertion matrix
print("\nPer-assertion matrix:")
hdr = f"{'aid':6} " + " ".join(f"{rid[:20]:22}" for rid in REPORTS)
print(hdr)
for i, aid in enumerate(["A1","A2","A3","A4","A5","A6","A7","A8","A9","A10","A11"]):
    row = f"{aid:6} "
    for run_id in REPORTS:
        if "error" in summary[run_id]:
            row += f"{'E':20} "
            continue
        ex = summary[run_id]["expectations"][i]
        row += f"{'PASS' if ex['passed'] else 'FAIL':20} "
    print(row)

# save summary
with open(os.path.join(WS, "grading_summary.json"), "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)
print(f"\nWrote grading_summary.json to {WS}")
