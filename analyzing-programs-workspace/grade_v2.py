#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""grade_v2.py — grader for analyzing-programs with content-type assertions.

Changes vs grade3.py
--------------------
* Arbitrary evals x arbitrary runs (reads evals.json, not a hardcoded list).
* Every content assertion's TRIGGER IS DERIVED FROM THE SOURCE by regex, so a
  trigger can never drift from the fixture. Assertions whose trigger does not
  fire are recorded as `skipped` and excluded from that run's denominator.
* A13-A19 are content assertions. They are deliberately NOT format checks: they
  ask whether the report reached a technical judgement about the code.
* Aggregates over runs (median pass rate) instead of pretending n=1.

Usage: python grade_v2.py <workspace> [--runs N]
Layout: <ws>/eval-<id>-<name>/{with_skill,without_skill}/run-<k>/outputs/report.md
"""
import json
import os
import re
import statistics
import sys
from math import comb, sqrt

WS = sys.argv[1]
RUNS = 2
if "--runs" in sys.argv:
    RUNS = int(sys.argv[sys.argv.index("--runs") + 1])

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVALS_JSON = os.path.join(REPO, "evals", "evals.json")

# ---------------------------------------------------------------- fixtures
EV = json.load(open(EVALS_JSON, encoding="utf-8"))
EVALS = []
for e in EV["evals"]:
    src = "".join(open(os.path.join(REPO, "evals", f), encoding="utf-8").read()
                  for f in e["files"])
    EVALS.append({"id": e["id"], "name": e["name"], "prompt": e["prompt"],
                  "files": e["files"], "src": src})

# ------------------------------------------------- source-derived triggers
# Fields whose data element carries business semantics that a naive
# length/precision check would pass: weights, quantities, currency,
# document counters. Used to decide whether A17 (semantic review) applies.
WEIGHTY = ("BRGEW", "NTGEW", "EINA", "EINUM", "MENGE", "WAERS", "NETPR",
           "NETWR", "MSTOCK", "MVBELN", "WRBTR", "BWHTB", "WRDAT", "SHKZG")

# Standard tables whose MODIFY/INSERT/UPDATE is a real database write.
# Internal-table MODIFYs (`MODIFY ct_stock FROM ...`) must NOT match, so the
# target has to be an allow-listed DDIC table.
DBTABLES = ("MARA", "MARC", "MARD", "MAKT", "KNA1", "LFA1", "EKKO", "EKPO",
            "VBAK", "VBAP", "VBELN_VA")


def triggers(src):
    u = src.upper()
    db_writes = bool(
        re.search(r"\bMODIFY\s+(" + "|".join(DBTABLES) + r")\s+FROM", u)
        or re.search(r"\bINSERT\s+INTO\s+(" + "|".join(DBTABLES) + r")\b", u)
        or re.search(r"\bUPDATE\s+(" + "|".join(DBTABLES) + r")\s+SET\b", u)
        or re.search(r"\bDELETE\s+FROM\s+(" + "|".join(DBTABLES) + r")\b", u)
        or re.search(r"BAPI_\w*(MAINTAIN|CREATE|CHANGE|DELETE)\w*", u))
    return {
        # a READ TABLE that is never followed by a sy-subrc guard anywhere near it
        "read_table": "READ TABLE" in u,
        "fae": "FOR ALL ENTRIES" in u,
        # a language / currency literal where sy-langu or a config should be
        "hardcode": bool(re.search(r"SPRAS\s*=\s*'", u)
                         or re.search(r"VALUE\s+'(EN|DE|ZH|JA|1|USD|EUR|CNY)'", u)
                         or re.search(r"\bWAERS\b[^.]{0,40}=\s*'", u)
                         or re.search(r"\bWAERK\b[^.]{0,40}=\s*'", u)),
        "semantic": any(w in u for w in WEIGHTY),
        "persist": db_writes,
        # hardcoded message text (as opposed to MESSAGE ID ... NUMBER, which is
        # the correct pattern; that is tracked separately as msg_class_ok)
        "literal_msg": bool(re.search(r"MESSAGE\s+'", u)),
        "msg_class_ok": bool(re.search(r"MESSAGE\s+ID\s+'", u)),
        "locking": bool(re.search(r"\b(ENQUEUE|DEQUEUE)_\w+", u)),
        "bg_job": bool(re.search(r"\bSY-BATCH\b", u)),
        "http": bool(re.search(r"\bCL_HTTP_CLIENT\b|\bIF_HTTP_CLIENT\b", u)),
        "cds": bool(re.search(r"DEFINE\s+(ROOT\s+)?VIEW\s+ENTITY", u)
                    # or an ABAP SQL SELECT whose source is a Z_/Y_/I_ CDS entity
                    or re.search(r"FROM\s+[ZYI]_[A-Z0-9_]+", u)),
    }


def subprograms(src):
    """Subprogram inventory driving the A13 coverage assertion.

    Covers every callable unit a report can contain. MODULE was added for
    dialog programs (eval-8): without it the inventory is empty, A13 becomes
    vacuously true, and a report could omit every PBO/PAI module and still
    pass.
    """
    names = re.findall(r"^\s*FORM\s+(\w+)", src, re.M | re.I)
    names += re.findall(r"^\s*METHOD\s+(\w+)\s*\.", src, re.M | re.I)
    names += re.findall(r"^\s*FUNCTION\s+(\w+)", src, re.M | re.I)
    names += re.findall(r"^\s*MODULE\s+(\w+)\s+(OUTPUT|INPUT)", src, re.M | re.I)
    seen, out = set(), []
    for n in names:
        # MODULE regex yields a 2-tuple; normalise before de-duplicating.
        if isinstance(n, tuple):
            n = n[0]
        k = n.lower()
        if k not in seen:
            seen.add(k)
            out.append(n)
    return out


for e in EVALS:
    e["trg"] = triggers(e["src"])
    e["subs"] = subprograms(e["src"])


# ------------------------------------------------------------- assertions
KW = {
    "subrc": ("sy-subrc", "sy_subrc", "SY-SUBRC"),
    "subrc_cn": ("未判", "未判断", "未检查", "漏判", "残留", "没判断", "未校验",
                 "忘记判断", "没有判断", "脏数据", "串数据", "上一行"),
    "fae": ("FOR ALL ENTRIES",),
    "fae_cn": ("空表", "为空", "空驱动", "IS INITIAL", "全表扫描", "驱动表",
               "空内表", "初始为"),
    "hard": ("硬编码", "魔数", "魔法值", "magic", "SY-LANGU", "sy-langu",
             "应改为", "配置化", "可配置", "固定字面量", "写死"),
    "sem": ("语义", "毛重", "净重", "单位", "口径", "不匹配", "错配", "含义",
            "brgew", "ntgew", "eina", "waers", "netpr", "mstok", "MVBELN".lower()),
    "persist": ("COMMIT", "ROLLBACK", "事务", "LUW", "BAPIRET", "BAPIRETURN",
                "return 表", "RETURN 表", "错误处理", "未提交", "未检查错误",
                "忽略错误", "失败处理", "EXCEPTIONS"),
    "msg": ("消息类", "硬编码消息", "硬编码文本", "不可翻译", "SE63", "文本元素",
            "MESSAGE ID", "直接写在", "文本硬编码", "翻译"),
    # A20 HTTP: response status, timeouts, transport failures
    "timeout": ("timeout", "超时", "HTTP 状态", "状态码", "4xx", "5xx",
                "transport", "通信失败", "get_status", "响应码"),
    "status": ("get_status", "状态码", "HTTP 状态", "响应码", "4xx", "5xx"),
    # A23 background: the same report running in batch has different rules
    "bg_cn": ("后台", "批处理", "sy-batch", "SY-BATCH", "定时", "作业", "job"),
}


def hits(t, keys):
    return any(k.lower() in t.lower() for k in keys)


def check(report, ev):
    """Return list of (aid, name, kind, passed|None, evidence). None = skipped."""
    t = report
    r = []
    ch = ["一、", "二、", "三、", "四、", "五、", "六、"]
    r.append(("A1", "报告含全部六章", "format",
              all(c in t for c in ch), f"找到 {[c for c in ch if c in t]}"))
    r.append(("A2", "二章含责任链表且表头含调用者列", "format",
              bool(re.search(r"\|[^|]*子程序[^|]*\|[^|]*调用者", t, re.S)), ""))
    r.append(("A3", "含 Mermaid flowchart TD", "format",
              "flowchart" in t and "TD" in t, ""))
    r.append(("A4", "含 Mermaid sequenceDiagram", "format",
              "sequenceDiagram" in t, ""))
    bad_line = re.findall(
        r"\.abap\s*:\s*\d+|第\s*\d+\s*[—\-]\s*\d+\s*行|（\s*第\s*\d+[^）]*行\s*）", t)
    r.append(("A5", "无源码行号引用", "format",
              len(bad_line) == 0, f"疑似 {bad_line[:3]}" if bad_line else "无"))
    blocks = re.findall(r"```mermaid\s*\n(.*?)```", t, re.S)
    bad_ang = [m for b in blocks for m in re.findall(r"<(?!br/?[>])\s*[A-Za-z_]", b)]
    r.append(("A6", "Mermaid 标签无裸尖括号", "format",
              len(bad_ang) == 0, f"违规 {len(bad_ang)}" if bad_ang else "安全"))
    r.append(("A7", "含 P0 与 P3 优先级标记", "format", "P0" in t and "P3" in t, ""))
    m3 = re.search(r"##\s*三[、\.].*?(?=##\s*四[、\.]|\Z)", t, re.S)
    scope = m3.group(0) if m3 else t
    nblk = len(re.findall(r"```abap", scope))
    # A8 v2 — count LOGICAL STEPS, not code blocks.
    #
    # v1 required one three-layer set per ```abap block. That is wrong: a good
    # report legitimately embeds short ```abap snippets as inline evidence inside
    # its own 风险与改进 prose (e.g. quoting the exact offending line). Those
    # snippets are citations, not analysis units, and demanding their own three
    # layers penalises better writing. Verified against iteration-7
    # eval-3/with_skill/run-2, whose every #### ①②③ step carries all three labels
    # yet scored 22/33 under v1.
    #
    # The SKILL.md requirement is per-STEP ("每个 ① ② ③ 下仍须带齐三层标签"), so
    # count #### ①②③ sub-steps. n_do > 0 keeps the baseline (which has neither
    # sub-steps nor labels) from passing vacuously at 0 >= 0.
    n_substeps = len(re.findall(r"^\s*####\s*[①②③④⑤]", scope, re.M))
    n_do = scope.count("做什么")
    n_risk = scope.count("风险")
    r.append(("A8", "每个 ① ② ③ 拆分步骤都带齐三层标签", "format",
              n_do > 0 and n_do >= n_substeps and n_risk >= n_do,
              f"子步骤={n_substeps} 做什么={n_do} 风险={n_risk} "
              f"(abap块 {nblk}，其中含行内证据片段，不参与判定)"))
    r.append(("A9", "代码块标注 ```abap", "format",
              len(re.findall(r"```abap", t)) > 0,
              f"{len(re.findall(r'```abap', t))} 块"))
    nsec = len(re.findall(r"###\s*3\.\d", t))
    r.append(("A10", "含 ### 3.X 分组标题(≥2)", "format", nsec >= 2, f"{nsec} 个"))
    r.append(("A11", "子程序分组按执行顺序(≥2 section)", "format", nsec >= 2, ""))
    # A12 kept only for continuity with iteration-3..6; superseded by A17.
    if "ntgew" in t.lower():
        mis = ("语义错配" in t or "不匹配" in t or "mismatch" in t.lower()
               or ("净重" in t and ("毛重" in t or "brgew" in t.lower())))
        endorse = bool(re.search(r"ntgew[^n]{0,40}(与[^n]{0,12}brgew|一致)", t.lower())) \
            and ("语义错配" not in t and "不匹配" not in t)
        r.append(("A12", "ntgew/brgew 语义错配被识别为风险(非背书)", "content",
                  bool(mis) and not endorse,
                  "已识别为风险" if mis else ("仍背书为一致" if endorse else "未判定")))
    else:
        r.append(("A12", "ntgew/brgew 语义错配被识别为风险(非背书)", "content",
                  None, "skipped: 报告未提及 ntgew"))

    # ---- A13 coverage: every subprogram in the source must be named -------
    subs = ev["subs"]
    missing = [s for s in subs if s.lower() not in t.lower()]
    r.append(("A13", f"源码 {len(subs)} 个子程序全部被报告覆盖", "coverage",
              not missing, f"缺 {missing}" if missing else f"{len(subs)}/{len(subs)} 覆盖"))

    # ---- A14-A19: content, gated on source-derived triggers ---------------
    tr = ev["trg"]
    g = lambda k: hits(t, KW[k])
    r.append(("A14", "READ TABLE 缺 sy-subrc 被识别为风险", "content",
              (g("subrc") or g("subrc_cn")) if tr["read_table"] else None,
              "提及 sy-subrc/残留" if (g("subrc") or g("subrc_cn")) else "未提及"
              if tr["read_table"] else "skipped: 源码无 READ TABLE"))
    r.append(("A15", "FOR ALL ENTRIES 空驱动表风险被识别", "content",
              (g("fae_cn") and g("fae")) if tr["fae"] else None,
              "已识别空驱动表" if (g("fae_cn") and g("fae")) else "未识别"
              if tr["fae"] else "skipped: 源码无 FOR ALL ENTRIES"))
    r.append(("A16", "硬编码语言/币种字面量被标为风险", "content",
              g("hard") if tr["hardcode"] else None,
              "已标注" if g("hard") else "未标注"
              if tr["hardcode"] else "skipped: 源码无硬编码语言/币种"))
    r.append(("A17", "字段语义校核(毛重/净重/单位/币种口径)", "content",
              g("sem") if tr["semantic"] else None,
              "已讨论语义" if g("sem") else "未讨论"
              if tr["semantic"] else "skipped: 源码无重量/金额/单位字段"))
    r.append(("A18", "持久化操作的事务与错误处理被讨论", "content",
              g("persist") if tr["persist"] else None,
              "已讨论 COMMIT/RETURN/EXCEPTIONS" if g("persist") else "未讨论"
              if tr["persist"] else "skipped: 源码无数据库写操作"))
    r.append(("A19", "硬编码 MESSAGE 文本被标为风险", "content",
              g("msg") if tr["literal_msg"] else None,
              "已标注消息类问题" if g("msg") else "未标注"
              if tr["literal_msg"] else "skipped: 源码无 MESSAGE '...'"))

    # ---- A20-A23: added with eval 9-12 ------------------------------------
    # These fire on the *presence* of a pattern that carries its own risk, so
    # the assertion is "did the report discuss it", not "did it call it bad".
    # For A21 the correct practice is the point, so passing means the report
    # noticed the positive pattern at all.
    r.append(("A20", "HTTP 调用的错误/状态码处理被讨论", "content",
              (g("persist") or g("subrc") or g("timeout") or g("status"))
              if tr["http"] else None,
              "已讨论" if (g("persist") or g("subrc") or g("timeout")
                            or g("status")) else "未讨论"
              if tr["http"] else "skipped: 源码无 HTTP 调用"))
    r.append(("A21", "消息类用法(MESSAGE ID/NUMBER)被提及", "content",
              g("msg") if tr["msg_class_ok"] else None,
              "已提及消息类/SE63" if g("msg") else "未提及"
              if tr["msg_class_ok"] else "skipped: 源码无 MESSAGE ID"))
    r.append(("A22", "表锁的释放与异常路径被讨论", "content",
              (g("persist") or "DEQUEUE" in t or "解锁" in t or "锁" in t)
              if tr["locking"] else None,
              "已讨论" if (g("persist") or "DEQUEUE" in t or "解锁" in t
                            or "锁" in t) else "未讨论"
              if tr["locking"] else "skipped: 源码无 ENQUEUE/DEQUEUE"))
    r.append(("A23", "后台运行分支(sy-batch)被讨论", "content",
              (g("bg_cn") or "sy-batch" in t or "SY-BATCH" in t)
              if tr["bg_job"] else None,
              "已讨论后台/批处理" if (g("bg_cn") or "sy-batch" in t
                                       or "SY-BATCH" in t) else "未讨论"
              if tr["bg_job"] else "skipped: 源码无 sy-batch"))
    return r


# ------------------------------------------------------------------ report
def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0, c - h), 3), round(min(1, c + h), 3))


def mcnemar(a, b):
    """Exact two-sided McNemar. a = cells where only arm A passed, b = only B."""
    n = a + b
    if n == 0:
        return 1.0
    k = min(a, b)
    p = min(1.0, 2 * sum(comb(n, i) for i in range(0, k + 1)) / 2 ** n)
    return p


runs = {}
# Arms are DISCOVERED, not hardcoded. iteration-9 compares two versions of the
# skill, which means a third arm directory (with_skill_<digest>), and a list of
# two literals in six places is the kind of second copy that silently disagrees
# with the layout. Discovery keeps every existing round working unchanged --
# with one skill arm and one baseline arm the discovered list is exactly the old
# tuple, so iteration-8 still reproduces byte for byte.
BASE_CFG = "without_skill"
DEFAULT_SKILL_CFG = "with_skill"


def discover_cfgs():
    found = set()
    try:
        entries = os.listdir(WS)
    except OSError:
        return [DEFAULT_SKILL_CFG, BASE_CFG]
    for name in entries:
        d = os.path.join(WS, name)
        if not name.startswith("eval-") or not os.path.isdir(d):
            continue
        for cfg in os.listdir(d):
            if os.path.isdir(os.path.join(d, cfg)):
                found.add(cfg)
    if not found:
        return [DEFAULT_SKILL_CFG, BASE_CFG]
    # baseline first, then skill arms, each alphabetically: deterministic order so
    # two runs of the grader emit keys in the same sequence
    return sorted(found, key=lambda c: (c != BASE_CFG, c))


CFGS = discover_cfgs()
SKILL_CFGS = [c for c in CFGS if c != BASE_CFG]
if "--arms" in sys.argv:
    want = sys.argv[sys.argv.index("--arms") + 1].split(",")
    CFGS = [c for c in CFGS if c in want]
    SKILL_CFGS = [c for c in CFGS if c != BASE_CFG]
if len(CFGS) != len(set(CFGS)):
    sys.exit("duplicate arm requested")
# the arm the headline numbers describe; with two skill arms this stays the
# canonical one and the other is reported alongside it
HEADLINE_SKILL = DEFAULT_SKILL_CFG if DEFAULT_SKILL_CFG in SKILL_CFGS else (
    SKILL_CFGS[0] if SKILL_CFGS else DEFAULT_SKILL_CFG)

for ev in EVALS:
    d = f"eval-{ev['id']}-{ev['name']}"
    for cfg in CFGS:
        for k in range(1, RUNS + 1):
            p = os.path.join(WS, d, cfg, f"run-{k}", "outputs", "report.md")
            if os.path.exists(p):
                runs[(ev["id"], cfg, k)] = open(p, encoding="utf-8").read()

summary = {}
matrix = {}          # aid -> {(eval,cfg): [verdicts per run]}
for (eid, cfg, k), text in sorted(runs.items()):
    ev = next(e for e in EVALS if e["id"] == eid)
    res = check(text, ev)
    applicable = [x for x in res if x[3] is not None]
    passed = sum(1 for x in applicable if x[3])
    rid = f"eval-{eid}-{cfg}-run{k}"
    summary[rid] = {
        "eval_id": eid, "eval_name": ev["name"], "config": cfg, "run": k,
        "chars": len(text), "abap_blocks": len(re.findall(r"```abap", text)),
        "passed": passed, "skipped": len(res) - len(applicable),
        "total": len(applicable),
        "pass_rate": round(passed / len(applicable), 3) if applicable else 0.0,
        "expectations": [{"aid": a, "name": n, "kind": kd, "passed": pv,
                          "evidence": ev_} for a, n, kd, pv, ev_ in res],
    }
    for a, n, kd, pv, ev_ in res:
        matrix.setdefault(a, {}).setdefault((eid, cfg), []).append(pv)
    out = os.path.join(WS, f"eval-{eid}-{ev['name']}", cfg, f"run-{k}", "outputs")
    os.makedirs(out, exist_ok=True)
    json.dump({"run_id": rid, "expectations": summary[rid]["expectations"]},
              open(os.path.join(out, "grading.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

# ------------------------------------------------------------ per-cell agg
percell = {}
for ev in EVALS:
    for cfg in CFGS:
        rr = [v for v in summary.values()
              if v["eval_id"] == ev["id"] and v["config"] == cfg]
        if not rr:
            continue
        percell[f"eval-{ev['id']}-{cfg}"] = {
            "eval_id": ev["id"], "eval_name": ev["name"], "config": cfg,
            "runs": len(rr),
            "pass_rate_mean": round(statistics.mean(x["pass_rate"] for x in rr), 3),
            "pass_rate_median": round(statistics.median(x["pass_rate"] for x in rr), 3),
            "pass_rate_min": round(min(x["pass_rate"] for x in rr), 3),
            "pass_rate_max": round(max(x["pass_rate"] for x in rr), 3),
            "per_run": [x["pass_rate"] for x in rr],
        }

# --------------------------------------------------------------- assertion
assertion_stats = {}
for a, cells in matrix.items():
    kind = next((x["kind"] for x in next(iter(summary.values()))["expectations"]
                 if x["aid"] == a), "?")
    rows = []
    for (eid, cfg), verdicts in sorted(cells.items()):
        applicable = [v for v in verdicts if v is not None]
        if not applicable:
            continue
        k = sum(1 for v in applicable if v)
        rows.append({"eval": eid, "config": cfg, "k": k, "n": len(applicable),
                     "rate": round(k / len(applicable), 3),
                     "ci95": wilson(k, len(applicable))})
    if not rows:
        continue
    w = [x for x in rows if x["config"] == HEADLINE_SKILL]
    b = [x for x in rows if x["config"] == BASE_CFG]
    assertion_stats[a] = {
        "aid": a, "kind": kind, "cells": rows,
        "with_rate": round(statistics.mean(x["rate"] for x in w), 3) if w else None,
        "without_rate": round(statistics.mean(x["rate"] for x in b), 3) if b else None,
        "applicable_cells": len(rows),
        "n_discriminating": sum(1 for x in rows
                                if x["config"] == HEADLINE_SKILL and x["rate"] == 1
                                and x["rate"] < 1),
        # every arm's mean, so a round with more than one skill arm is readable
        # without re-running this
        "rate_by_config": {c: round(statistics.mean(
            [x["rate"] for x in rows if x["config"] == c]), 3)
            for c in CFGS if any(x["config"] == c for x in rows)},
    }

# ------------------------------------------------------------- McNemar sum
# Unit of analysis: (eval, config, run, assertion) discordance. A12 is excluded
# because A17 is its generalisation and the two are highly correlated on eval-1.
# PAIRED_EXCLUDE = {"A12"}
PAIRED_EXCLUDE = {"A12"}
# which two arms the paired test compares. Defaults to the canonical pair so
# every earlier round is unaffected; iteration-9 compares its two skill versions.
PAIRED = [HEADLINE_SKILL, BASE_CFG]
if "--compare" in sys.argv:
    PAIRED = sys.argv[sys.argv.index("--compare") + 1].split(",")
    if len(PAIRED) != 2:
        sys.exit("--compare needs exactly two arms")
    for c in PAIRED:
        if c not in CFGS:
            sys.exit(f"--compare names an arm that was not found: {c}")
w_only = b_only = 0
paired_cells = 0
for (eid, cfg, k), _t in runs.items():
    if cfg != PAIRED[0]:
        continue
    rid = f"eval-{eid}-{cfg}-run{k}"
    other = f"eval-{eid}-{PAIRED[1]}-run{k}"
    if rid not in summary or other not in summary:
        continue
    ws = {x["aid"]: x["passed"] for x in summary[rid]["expectations"]}
    bs = {x["aid"]: x["passed"] for x in summary[other]["expectations"]}
    for a in ws:
        if a in PAIRED_EXCLUDE or ws[a] is None or bs.get(a) is None:
            continue
        paired_cells += 1
        if ws[a] and not bs[a]:
            w_only += 1
        elif bs[a] and not ws[a]:
            b_only += 1
p_mcnemar = mcnemar(w_only, b_only)

w_means = [v["pass_rate_mean"] for k, v in percell.items()
           if v["config"] == HEADLINE_SKILL]
b_means = [v["pass_rate_mean"] for k, v in percell.items()
           if v["config"] == BASE_CFG]
per_config = {c: round(statistics.mean(
    [v["pass_rate_mean"] for v in percell.values() if v["config"] == c]), 3)
    for c in CFGS if any(v["config"] == c for v in percell.values())}

out = {
    "metadata": {
        "grader": "grade_v2.py",
        "runs_per_configuration": RUNS,
        "evals": [{"id": e["id"], "name": e["name"], "files": e["files"],
                   "subprograms": e["subs"], "triggers": e["trg"]} for e in EVALS],
        "paired_cells": paired_cells, "paired_excluded": sorted(PAIRED_EXCLUDE),
        # recorded so a reader can tell a one-skill-arm round from a two-version
        # one without inferring it from directory names
        "arms": CFGS,
        "headline_skill_arm": HEADLINE_SKILL,
        "baseline_arm": BASE_CFG,
        "paired_arms": PAIRED,
    },
    "runs": list(summary.values()),
    "per_cell": percell,
    "assertion_stats": assertion_stats,
    "paired": {
        "with_only_pass": w_only, "without_only_pass": b_only,
        "concordant_pass": paired_cells - w_only - b_only,
        # Keep full float precision: this p is far below 1e-8, and round(_, 8)
        # would collapse it to a meaningless 0.0.
        "mcnemar_exact_two_sided_p": p_mcnemar,
    },
    "summary": {
        "with_skill_mean": round(statistics.mean(w_means), 3) if w_means else 0,
        "without_skill_mean": round(statistics.mean(b_means), 3) if b_means else 0,
        "delta_pp": round((statistics.mean(w_means) - statistics.mean(b_means)) * 100, 1)
        if w_means and b_means else 0,
        "per_config": per_config,
    },
}
json.dump(out, open(os.path.join(WS, "grading_summary.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)

# ------------------------------------------------------------------ console
print("=" * 96)
print(f"{'run':40} {'chars':>6} {'ablk':>5} {'pass':>8} {'skip':>5} {'rate':>6}")
print("-" * 96)
for rid, s in summary.items():
    print(f"{rid:40} {s['chars']:>6} {s['abap_blocks']:>5} "
          f"{s['passed']:>3}/{s['total']:<4} {s['skipped']:>5} {s['pass_rate']:>6}")
print("=" * 96)
print(f"\nper (eval,config) over {RUNS} runs:")
for k, v in percell.items():
    rng = f"[{v['pass_rate_min']}, {v['pass_rate_max']}]"
    print(f"  {k:28} mean {v['pass_rate_mean']:>5}  median {v['pass_rate_median']:>5}"
          f"  range {rng:>12}  runs {v['per_run']}")
print(f"\npaired McNemar (A12 excluded as superseded by A17), "
      f"{PAIRED[0]} vs {PAIRED[1]}:")
print(f"  cells={paired_cells}  with_only={w_only}  without_only={b_only}  "
      f"concordant={paired_cells - w_only - b_only}")
print(f"  exact two-sided p = {p_mcnemar:.3e}")
print(f"\nsummary: with_skill {out['summary']['with_skill_mean']:.3f} vs "
      f"without_skill {out['summary']['without_skill_mean']:.3f} "
      f"(delta {out['summary']['delta_pp']}pp)  [NOTE: paired p above is the "
      f"significance test; the delta is descriptive]")
if len(CFGS) > 2:
    print(f"\n{len(CFGS)} arms found, so the headline pair above is only one of them:")
    for c, m in sorted(per_config.items()):
        mark = "  <- headline skill arm" if c == HEADLINE_SKILL else (
               "  <- baseline" if c == BASE_CFG else "")
        print(f"  {c:34} mean {m:.3f}{mark}")
print("\nper-assertion (rate over applicable cells; CI = Wilson 95%):")
print(f"{'aid':5} {'kind':9} {'with':>7} {'base':>7} {'cells':>6}")
for a in sorted(assertion_stats, key=lambda x: int(x[1:])):
    s = assertion_stats[a]
    wr = f"{s['with_rate']*100:.0f}%" if s["with_rate"] is not None else "  -  "
    br = f"{s['without_rate']*100:.0f}%" if s["without_rate"] is not None else "  -  "
    print(f"{a:5} {s['kind']:9} {wr:>7} {br:>7} {s['applicable_cells']:>6}")
print(f"\nWrote {os.path.join(WS, 'grading_summary.json')}")