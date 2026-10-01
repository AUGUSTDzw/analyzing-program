#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Grade analyzing-programs skill eval outputs (parameterized by workspace)."""
import json, re, os, sys, statistics

WS = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\DzwU\.agents\skills\analyzing-programs-workspace\iteration-3"

REPORTS = {
    "eval-1-with_skill":   os.path.join(WS, "eval-1-alv-editable-total-poc", "with_skill", "outputs", "report.md"),
    "eval-1-without_skill":os.path.join(WS, "eval-1-alv-editable-total-poc", "without_skill", "outputs", "report.md"),
    "eval-2-with_skill":   os.path.join(WS, "eval-2-procedural-vendor-report", "with_skill", "outputs", "report.md"),
    "eval-2-without_skill":os.path.join(WS, "eval-2-procedural-vendor-report", "without_skill", "outputs", "report.md"),
}

def read(p):
    try:
        with open(p, encoding="utf-8") as f: return f.read()
    except Exception: return ""

def mermaid_blocks(t):
    return re.findall(r"```mermaid\s*\n(.*?)```", t, re.S)

def check(t):
    res = []
    ch = ["一、","二、","三、","四、","五、","六、"]
    res.append(("A1","报告含全部六章", all(c in t for c in ch), f"找到 {[c for c in ch if c in t]}"))
    res.append(("A2","二章含责任链表且表头含调用者列", bool(re.search(r"\|[^|]*子程序[^|]*\|[^|]*调用者", t, re.S)), ""))
    res.append(("A3","含 Mermaid flowchart TD", "flowchart" in t and "TD" in t, ""))
    res.append(("A4","含 Mermaid sequenceDiagram", "sequenceDiagram" in t, ""))
    bad_line = re.findall(r"\.abap\s*:\s*\d+|第\s*\d+\s*[—\-]\s*\d+\s*行|（\s*第\s*\d+[^）]*行\s*）", t)
    res.append(("A5","无源码行号引用", len(bad_line)==0, f"疑似: {bad_line[:3]}" if bad_line else "无"))
    blocks = mermaid_blocks(t)
    bad_ang = [m for b in blocks for m in re.findall(r"<(?!br/?[>])\s*[A-Za-z_]", b)]
    res.append(("A6","Mermaid 标签无裸尖括号", len(bad_ang)==0, f"违规 {len(bad_ang)}" if bad_ang else "安全"))
    res.append(("A7","含 P0 与 P3 优先级标记", "P0" in t and "P3" in t, ""))
    nblk = len(re.findall(r"```abap", t))
    n_do = t.count("做什么"); n_risk = t.count("风险")
    res.append(("A8","每个 abap 块后有做什么与风险层", nblk>0 and n_do>=nblk and n_risk>=nblk, f"abap={nblk} 做什么={n_do} 风险={n_risk}"))
    res.append(("A9","代码块标注 ```abap", nblk>0, f"abap块 {nblk}"))
    nsec = len(re.findall(r"###\s*3\.\d", t))
    res.append(("A10","含 ### 3.X 分组标题(≥2)", nsec>=2, f"{nsec} 个"))
    res.append(("A11","子程序分组按执行顺序(≥2 section)", nsec>=2, ""))
    # A12 content: ntgew semantic check (eval-1 only meaningful)
    has_ntgew = "ntgew" in t
    if has_ntgew:
        mismatch = ("语义错配" in t or "不匹配" in t or "mismatch" in t.lower() or ("Net Weight" in t and "brgew" in t) or ("净重" in t and ("毛重" in t or "brgew" in t)))
        endorse = bool(re.search(r"ntgew[^n]{0,40}(与[^n]{0,12}BRGEW|一致)", t)) and ("语义错配" not in t and "不匹配" not in t)
        res.append(("A12","ntgew/brgew 语义错配被识别为风险(非背书)", mismatch and not endorse, "已识别为风险" if mismatch else ("仍背书为一致" if endorse else "未判定")))
    return res

summary = {}
for run_id, path in REPORTS.items():
    t = read(path)
    if not t:
        summary[run_id] = {"error":"unread","len":0}; continue
    results = check(t)
    passed = sum(1 for r in results if r[2])
    summary[run_id] = {"len":len(t), "abap_blocks":len(re.findall(r"```abap",t)),
                       "passed":passed, "total":len(results), "pass_rate":round(passed/len(results),3),
                       "expectations":[{"text":r[1],"passed":r[2],"evidence":r[3]} for r in results]}
    with open(os.path.join(os.path.dirname(path),"grading.json"),"w",encoding="utf-8") as f:
        json.dump({"run_id":run_id,"expectations":summary[run_id]["expectations"]},f,ensure_ascii=False,indent=2)

print("="*82)
print(f"{'run':28} {'len':>6} {'abap':>5} {'pass':>8} {'rate':>6}")
print("-"*82)
for rid,s in summary.items():
    if "error" in s: print(f"{rid:28} ERROR"); continue
    print(f"{rid:28} {s['len']:>6} {s['abap_blocks']:>5} {s['passed']:>2}/{s['total']:<3} {s['pass_rate']:>6}")
print("="*82)
AIDS = ["A1","A2","A3","A4","A5","A6","A7","A8","A9","A10","A11","A12"]
print("\nPer-assertion:")
print(f"{'aid':5} " + " ".join(f"{rid[:20]:22}" for rid in REPORTS))
for i,aid in enumerate(AIDS):
    row=f"{aid:5} "
    for rid in REPORTS:
        if "error" in summary[rid]: row+=f"{'E':22} "; continue
        ex=summary[rid]["expectations"][i] if i < len(summary[rid]["expectations"]) else None
        row += f"{('-' if ex is None else ('PASS' if ex['passed'] else 'FAIL')):22} "
    print(row)
with open(os.path.join(WS,"grading_summary.json"),"w",encoding="utf-8") as f:
    json.dump(summary,f,ensure_ascii=False,indent=2)
print(f"\nWrote {os.path.join(WS,'grading_summary.json')}")
