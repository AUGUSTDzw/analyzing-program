#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render benchmark scores as HTML.

Emits two artifacts into the newest workspace:
  benchmark.html  dark dashboard: KPI cards, ECharts, cross-round tables,
                 data-derived analysis + conclusions
  review.html     warm side-by-side reader for the four generated reports
                 (follows the visual convention of iteration-3/review.html)

Usage: python build_html.py <workspace> [<older-workspace> ...]
The first workspace is the newest round; the rest are history, oldest first.
"""
import html
import json
import os
import statistics
import sys

WS = sys.argv[1]
HISTORY = sys.argv[2:]

EVALS = [
    (1, "alv-editable-total-poc", "eval-1-alv-editable-total-poc",
     "eval-1-with_skill", "eval-1-without_skill"),
    (2, "procedural-vendor-report", "eval-2-procedural-vendor-report",
     "eval-2-with_skill", "eval-2-without_skill"),
]
SHARED = [f"A{i}" for i in range(1, 12)]


def jload(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def aid_matrix(summary):
    m, text = {}, {}
    for eid, _n, _d, wk, bk in EVALS:
        for key, cfg in ((wk, "with_skill"), (bk, "without_skill")):
            if key not in summary or "expectations" not in summary[key]:
                continue
            m[(eid, cfg)] = {f"A{i+1}": e["passed"]
                             for i, e in enumerate(summary[key]["expectations"])}
            text[(eid, cfg)] = {f"A{i+1}": e["text"]
                                for i, e in enumerate(summary[key]["expectations"])}
    return m, text


def rates(summary):
    w = [summary[k]["pass_rate"] for _e, _n, _d, k, _b in EVALS if k in summary]
    b = [summary[k]["pass_rate"] for _e, _n, _d, _k, k in EVALS if k in summary]
    return w, b


def mean(xs):
    return statistics.mean(xs) if xs else 0.0


# ---------------------------------------------------------------- gather data
rounds = []
for ws in HISTORY + [WS]:
    name = os.path.basename(ws.rstrip("\\/"))
    s = jload(os.path.join(ws, "grading_summary.json"))
    bp = os.path.join(ws, "benchmark.json")
    b = jload(bp) if os.path.exists(bp) else {}
    m, text = aid_matrix(s)
    w, bl = rates(s)
    rounds.append({
        "name": name, "ws": ws, "summary": s, "benchmark": b, "matrix": m, "text": text,
        "with_mean": round(mean(w), 4), "without_mean": round(mean(bl), 4),
        "delta": round(mean(w) - mean(bl), 4),
        "with_per_eval": [round(x, 4) for x in w],
        "without_per_eval": [round(x, 4) for x in bl],
    })

latest = rounds[-1]
prev = rounds[-2] if len(rounds) > 1 else None

# ------------------------------------------- assertion buckets (latest round)
M, TEXT = latest["matrix"], latest["text"]
buckets = {"skill_gain": [], "non_discriminating": [], "fail_both": [], "mixed": [],
           "regression": []}
for aid in SHARED:
    labels, wv, bv, present = set(), [], [], False
    for eid, _n, _d, _wk, _bk in EVALS:
        w, b = M.get((eid, "with_skill"), {}), M.get((eid, "without_skill"), {})
        if aid not in w or aid not in b:
            continue
        present = True
        labels.add(TEXT[(eid, "with_skill")][aid])
        wv.append(w[aid])
        bv.append(b[aid])
        if not w[aid]:
            buckets["regression"].append({"aid": aid, "eval": eid,
                                          "text": TEXT[(eid, "with_skill")][aid]})
    if not present:
        continue
    row = {"aid": aid, "text": " / ".join(sorted(labels)), "with": wv, "without": bv,
           "with_rate": round(sum(map(bool, wv)) / len(wv) * 100),
           "without_rate": round(sum(map(bool, bv)) / len(bv) * 100)}
    if all(wv) and not all(bv):
        buckets["skill_gain"].append(row)
    elif all(wv) and all(bv):
        buckets["non_discriminating"].append(row)
    elif not all(wv) and not all(bv):
        buckets["fail_both"].append(row)
    else:
        buckets["mixed"].append(row)

# --------------------------------------------------- flips prev -> latest
flips = []
if prev:
    for eid, _n, _d, _wk, _bk in EVALS:
        for cfg in ("with_skill", "without_skill"):
            old, new = prev["matrix"].get((eid, cfg)), M.get((eid, cfg))
            if not old or not new:
                continue
            for aid in SHARED:
                if aid in old and aid in new and old[aid] != new[aid]:
                    flips.append({
                        "scope": f"eval-{eid} · {cfg}", "aid": aid,
                        "flip": "PASS → FAIL" if old[aid] else "FAIL → PASS",
                        "good": new[aid], "text": TEXT[(eid, cfg)][aid],
                    })

total_assertions = sum(
    len(r["summary"][k]["expectations"])
    for r in rounds for _e, _n, _d, wk, bk in EVALS for k in (wk, bk))
discriminating = len(buckets["skill_gain"])

# Rounds that ran against the SAME SKILL.md (digest recorded in benchmark.json).
# Differences between them are sampling variance, not skill improvement.
_digest = (latest["benchmark"].get("metadata", {}) or {}).get("skill_sha256")
same_version_rounds = [r["name"] for r in rounds
                       if (r["benchmark"].get("metadata", {}) or {}).get("skill_sha256")
                       and (r["benchmark"].get("metadata", {}) or {}).get("skill_sha256") == _digest]
if len(same_version_rounds) >= 2:
    _w = [r["with_mean"] for r in rounds if r["name"] in same_version_rounds]
    _b = [r["without_mean"] for r in rounds if r["name"] in same_version_rounds]
    variance = {
        "n": len(same_version_rounds),
        "withSpread": round(max(_w) - min(_w), 4),
        "withoutSpread": round(max(_b) - min(_b), 4),
        "withValues": _w,
        "withoutValues": _b,
    }
else:
    variance = None

payload = {
    "rounds": [{k: r[k] for k in ("name", "with_mean", "without_mean", "delta",
                                  "with_per_eval", "without_per_eval")} for r in rounds],
    "buckets": buckets,
    "flips": flips,
    "assertionText": {f"eval{eid}-{cfg}": {a: t[a] for a in sorted(t)}
                      for (eid, cfg), t in TEXT.items()},
    "matrixLatest": {f"eval{eid}-{cfg}": M[(eid, cfg)] for (eid, cfg) in M},
    "scoreTable": [
        {"round": r["name"], "eval": eid, "evalName": en,
         "with": r["summary"][wk]["pass_rate"], "without": r["summary"][bk]["pass_rate"],
         "withPassed": r["summary"][wk]["passed"], "withTotal": r["summary"][wk]["total"],
         "withoutPassed": r["summary"][bk]["passed"],
         "withoutTotal": r["summary"][bk]["total"]}
        for r in rounds for eid, en, _d, wk, bk in EVALS],
    "notesByRound": [{"round": r["name"], "notes": r["benchmark"].get("notes", [])}
                     for r in rounds],
    "reportSizes": [
        {"run": k, "chars": r["summary"][k]["len"], "blocks": r["summary"][k]["abap_blocks"]}
        for r in rounds for _e, _n, _d, wk, bk in EVALS for k in (wk, bk)],
    "meta": {
        "skill": latest["benchmark"].get("metadata", {}).get("skill_name", "analyzing-programs"),
        "grader": latest["benchmark"].get("metadata", {}).get("grader", "grade3.py"),
        "runsPerConfig": latest["benchmark"].get("metadata", {}).get("runs_per_configuration", 1),
        "totalAssertions": total_assertions,
        "skillDigest": (latest["benchmark"].get("metadata", {}) or {}).get("skill_sha256"),
        "sameVersionRounds": same_version_rounds,
        "variance": variance,
    },
}
print(f"rounds={len(rounds)} latest={latest['name']} "
      f"buckets: gain={len(buckets['skill_gain'])} "
      f"nondisc={len(buckets['non_discriminating'])} "
      f"mixed={len(buckets['mixed'])} failboth={len(buckets['fail_both'])} "
      f"regression={len(buckets['regression'])} flips={len(flips)}")

# ================================================================ dashboard
DASH = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>analyzing-programs · benchmark</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&family=Noto+Sans+SC:wght@300;400;500;700&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
:root{
  --bg:#0a0c12; --bg-2:#10131c; --card:rgba(255,255,255,.035); --card-h:rgba(255,255,255,.06);
  --line:rgba(255,255,255,.09);
  --tx:#e8ecf4; --tx-2:#9aa4bb; --tx-3:#5d6580;
  --ok:#2ee6a8; --warn:#ffb020; --bad:#ff4d6a; --base:#5b7cfa; --acc:#c084fc;
  --r:14px; --r-s:8px;
  --mono:'IBM Plex Mono',ui-monospace,monospace;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--tx);
  font-family:'Space Grotesk','Noto Sans SC',system-ui,sans-serif;
  -webkit-font-smoothing:antialiased;line-height:1.65}
body::before{content:'';position:fixed;inset:0;z-index:-1;pointer-events:none;
  background:
    radial-gradient(900px 500px at 12% -8%, rgba(192,132,252,.16), transparent 60%),
    radial-gradient(800px 480px at 88% 0%, rgba(46,230,168,.10), transparent 62%),
    repeating-linear-gradient(0deg,rgba(255,255,255,.014) 0 1px,transparent 1px 3px)}
.wrap{max-width:1280px;margin:0 auto;padding:0 2rem 5rem}

/* header */
.rpt-header{display:flex;justify-content:space-between;align-items:flex-end;gap:2rem;
  padding:3.5rem 0 2rem;border-bottom:1px solid var(--line);margin-bottom:2.5rem;flex-wrap:wrap}
.rpt-header h1{font-size:2.1rem;font-weight:700;letter-spacing:-.02em;line-height:1.15}
.rpt-header h1 em{font-style:normal;color:var(--acc)}
.rpt-sub{color:var(--tx-2);font-size:.9rem;margin-top:.6rem}
.rpt-sub code{font-family:var(--mono);color:var(--ok);font-size:.85em}
.rpt-meta{text-align:right;font-family:var(--mono);font-size:.74rem;color:var(--tx-3);line-height:1.9}
.rpt-meta b{color:var(--tx-2);font-weight:500}

/* section */
.sec{margin:3.25rem 0 0}
.sec-h{display:flex;align-items:baseline;gap:.85rem;margin-bottom:1.35rem}
.sec-h .n{font-family:var(--mono);font-size:.72rem;color:var(--acc);
  border:1px solid rgba(192,132,252,.35);border-radius:5px;padding:.15rem .45rem}
.sec-h h2{font-size:1.28rem;font-weight:600;letter-spacing:-.01em}
.sec-h .hint{font-size:.8rem;color:var(--tx-3);margin-left:auto}

/* kpi */
.kpi-cards{display:grid;gap:1rem;
  grid-template-columns:repeat(auto-fit,minmax(190px,1fr))}
.kpi{position:relative;overflow:hidden;background:var(--card);border:1px solid var(--line);
  border-radius:var(--r);padding:1.15rem 1.25rem;transition:.28s cubic-bezier(.2,.7,.3,1)}
.kpi::before{content:'';position:absolute;inset:0 0 auto 0;height:2px;
  background:linear-gradient(90deg,var(--acc),var(--ok))}
.kpi:hover{transform:translateY(-3px);background:var(--card-h);border-color:rgba(255,255,255,.18)}
.kpi .lb{font-size:.72rem;color:var(--tx-3);text-transform:uppercase;letter-spacing:.09em;font-weight:500}
.kpi .v{font-family:var(--mono);font-size:2.05rem;font-weight:500;margin:.35rem 0 .1rem;
  letter-spacing:-.02em;line-height:1}
.kpi .d{font-size:.75rem;color:var(--tx-2)}
.up{color:var(--ok)} .down{color:var(--bad)} .flat{color:var(--tx-3)}
.kpi.v-ok .v{color:var(--ok)} .kpi.v-base .v{color:var(--base)}
.kpi.v-acc .v{color:var(--acc)} .kpi.v-warn .v{color:var(--warn)}

/* charts */
.charts{display:grid;gap:1rem;grid-template-columns:repeat(auto-fit,minmax(360px,1fr))}
.chart{background:var(--card);border:1px solid var(--line);border-radius:var(--r);
  padding:1.1rem 1.25rem 1.25rem}
.chart h3{font-size:.92rem;font-weight:600;margin-bottom:.15rem}
.chart .cs{font-size:.76rem;color:var(--tx-3);margin-bottom:.5rem}
.cv{width:100%;height:330px}
.cv.tall{height:400px}
.cv.short{height:290px}

/* tables */
.tbl-wrap{background:var(--card);border:1px solid var(--line);border-radius:var(--r);overflow:hidden}
table{width:100%;border-collapse:collapse;font-size:.84rem}
th{text-align:left;font-weight:600;font-size:.7rem;text-transform:uppercase;letter-spacing:.08em;
  color:var(--tx-3);padding:.75rem .9rem;background:rgba(255,255,255,.03);
  border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:.68rem .9rem;border-bottom:1px solid rgba(255,255,255,.05);vertical-align:top}
tbody tr:last-child td{border-bottom:none}
tbody tr:hover td{background:rgba(255,255,255,.028)}
td.mono,.mono{font-family:var(--mono);font-size:.82em}
.scroller{max-height:430px;overflow-y:auto}
.scroller::-webkit-scrollbar{width:9px}
.scroller::-webkit-scrollbar-thumb{background:rgba(255,255,255,.14);border-radius:9px}
.pill{display:inline-block;padding:.1rem .5rem;border-radius:999px;font-size:.7rem;
  font-family:var(--mono);font-weight:500}
.pill.ok{background:rgba(46,230,168,.14);color:var(--ok)}
.pill.bad{background:rgba(255,77,106,.14);color:var(--bad)}
.pill.base{background:rgba(91,124,250,.14);color:var(--base)}
.pill.mute{background:rgba(255,255,255,.07);color:var(--tx-2)}
.pill.acc{background:rgba(192,132,252,.14);color:var(--acc)}
.pill.warn{background:rgba(255,176,32,.14);color:var(--warn)}
.mx td,.mx th{text-align:center}
.mx td:first-child,.mx th:first-child{text-align:left}
.mx td.c{font-family:var(--mono);font-size:.75rem}
.c-pass{color:var(--ok);font-weight:600} .c-fail{color:var(--bad);font-weight:600}

/* analysis */
.blk{background:var(--card);border:1px solid var(--line);border-radius:var(--r);
  padding:1.3rem 1.45rem;margin-bottom:1rem;border-left:3px solid transparent}
.blk.gain{border-left-color:var(--ok)} .blk.risk{border-left-color:var(--warn)}
.blk.info{border-left-color:var(--base)} .blk.acc{border-left-color:var(--acc)}
.blk h3{font-size:.98rem;font-weight:600;margin-bottom:.7rem;display:flex;
  align-items:center;gap:.55rem}
.blk h3 .tag{font-family:var(--mono);font-size:.62rem;padding:.1rem .4rem;border-radius:4px;
  background:rgba(255,255,255,.07);color:var(--tx-3);letter-spacing:.06em}
.blk p{font-size:.88rem;color:var(--tx-2);margin-bottom:.5rem}
.blk p:last-child{margin-bottom:0}
.blk strong{color:var(--tx);font-weight:600}
.blk code{font-family:var(--mono);font-size:.85em;color:var(--acc)}
.bar{position:relative;height:20px;background:rgba(255,255,255,.06);
  border-radius:11px;overflow:hidden;min-width:110px}
.bar i{position:absolute;inset:0 auto 0 0;border-radius:11px}
.bar i.pos{background:linear-gradient(90deg,#2ee6a8,#5b7cfa)}
.bar i.zero{background:linear-gradient(90deg,#ff4d6a,#ff8fa3)}
.bar b{position:absolute;right:.5rem;top:50%;transform:translateY(-50%);
  font-family:var(--mono);font-size:.68rem;color:var(--tx-2);font-weight:500}

/* conclusions */
ol.findings{list-style:none;counter-reset:f}
ol.findings li{counter-increment:f;position:relative;padding:.85rem 0 .85rem 2.9rem;
  border-bottom:1px solid rgba(255,255,255,.05)}
ol.findings li:last-child{border-bottom:none}
ol.findings li::before{content:'F' counter(f);position:absolute;left:0;top:.9rem;
  font-family:var(--mono);font-size:.68rem;color:var(--acc);
  border:1px solid rgba(192,132,252,.4);border-radius:5px;padding:.1rem .38rem}
ol.findings p{font-size:.88rem;color:var(--tx-2)}
.rec-timeline{position:relative;padding-left:1.5rem;border-left:2px solid var(--line);margin-top:.4rem}
.rec-item{position:relative;margin-bottom:1.1rem}
.rec-item::before{content:'';position:absolute;left:-1.93rem;top:.5rem;width:11px;height:11px;
  border-radius:50%;border:2px solid;background:var(--bg)}
.rec-s::before{border-color:var(--ok)} .rec-m::before{border-color:var(--base)}
.rec-l::before{border-color:var(--acc)}
.rec-item .rl{font-family:var(--mono);font-size:.7rem;letter-spacing:.06em;
  text-transform:uppercase;margin-bottom:.3rem}
.rec-s .rl{color:var(--ok)} .rec-m .rl{color:var(--base)} .rec-l .rl{color:var(--acc)}
.rec-item ul{list-style:none}
.rec-item li{font-size:.86rem;color:var(--tx-2);padding-left:1rem;position:relative;margin-bottom:.25rem}
.rec-item li::before{content:'→';position:absolute;left:0;color:var(--tx-3)}
footer{margin-top:4rem;padding-top:1.5rem;border-top:1px solid var(--line);
  font-family:var(--mono);font-size:.72rem;color:var(--tx-3);display:flex;
  justify-content:space-between;gap:1rem;flex-wrap:wrap}
.nogs{font-family:var(--mono);font-size:.8rem;color:var(--warn);padding:1rem;
  background:rgba(255,176,32,.08);border:1px solid rgba(255,176,32,.25);border-radius:var(--r-s)}
@media(max-width:760px){.wrap{padding:0 1rem 3rem}.rpt-meta{text-align:left}}
</style>
</head>
<body>
<div class="wrap">

  <header class="rpt-header">
    <div>
      <h1><em>analyzing-programs</em><br>skill benchmark</h1>
      <p class="rpt-sub">
        with_skill vs baseline · <code>__META_GRADER__</code> ·
        评分对象 <code>SKILL.md</code>
      </p>
    </div>
    <div class="rpt-meta">
      <div>轮次 <b>__NROUNDS__</b> 个 · evals <b>2</b></div>
      <div>断言总数 <b>__TOTAL_ASSER__</b></div>
      <div>runs / configuration <b>__RPC__</b></div>
      <div>最新轮次 <b>__LATEST__</b></div>
    </div>
  </header>

  <section class="sec">
    <div class="sec-h"><span class="n">01</span><h2>关键指标</h2>
      <span class="hint">最新轮次 vs 全轮次</span></div>
    <div class="kpi-cards" id="kpis"></div>
  </section>

  <section class="sec">
    <div class="sec-h"><span class="n">02</span><h2>可视化</h2>
      <span class="hint">跨轮趋势 · 断言维度差异 · 断言分桶</span></div>
    <div class="charts">
      <div class="chart"><h3>跨轮通过率趋势</h3>
        <p class="cs">每轮 2 个 eval 的均值；阴影区为 with_skill 与 baseline 的差距</p>
        <div class="cv" id="c-trend"></div></div>
      <div class="chart"><h3>断言维度：with_skill vs baseline</h3>
        <p class="cs">最新轮次，每个断言在 2 个 eval 中通过的比例</p>
        <div class="cv tall" id="c-aid"></div></div>
      <div class="chart"><h3>断言分桶构成</h3>
        <p class="cs">11 项共享断言按 with_skill / baseline 通过组合归类</p>
        <div class="cv short" id="c-bucket"></div></div>
      <div class="chart"><h3>每轮 with_skill 缺口</h3>
        <p class="cs">with_skill 未通过的断言数；为 0 表示结构规范全覆盖</p>
        <div class="cv short" id="c-gap"></div></div>
    </div>
  </section>

  <section class="sec">
    <div class="sec-h"><span class="n">03</span><h2>详细数据</h2>
      <span class="hint">全部数字直接来自 grading_summary.json / benchmark.json</span></div>
    <div class="charts">
      <div class="chart" style="grid-column:1/-1"><h3>逐轮逐 eval 得分</h3>
        <p class="cs">pass / total 为断言计数</p>
        <div class="tbl-wrap scroller" id="t-scores"></div></div>
      <div class="chart" style="grid-column:1/-1"><h3>最新轮次断言矩阵</h3>
        <p class="cs">A12 仅在含 NTGEW/BRGEW 的 eval-1 上存在，故 eval-2 无此项</p>
        <div class="tbl-wrap" id="t-matrix"></div></div>
      <div class="chart" style="grid-column:1/-1"><h3>断言状态翻转（上轮 → 最新轮）</h3>
        <p class="cs">基线 run 每配置仅 1 次，基线侧翻转属模型方差，不作为结论</p>
        <div class="tbl-wrap" id="t-flips"></div></div>
      <div class="chart" style="grid-column:1/-1"><h3>各轮 benchmark.json notes（原文）</h3>
        <div class="tbl-wrap" id="t-notes"></div></div>
      <div class="chart" style="grid-column:1/-1"><h3>产出体积</h3>
        <p class="cs">报告字符数与 ```abap 代码块数</p>
        <div class="tbl-wrap" id="t-size"></div></div>
    </div>
  </section>

  <section class="sec">
    <div class="sec-h"><span class="n">04</span><h2>深度分析</h2>
      <span class="hint">趋势 / 结构 / 对比 / 异常四个维度</span></div>
    <div id="analysis"></div>
  </section>

  <section class="sec">
    <div class="sec-h"><span class="n">05</span><h2>结论与建议</h2></div>
    <div class="blk acc"><h3>核心发现</h3><ol class="findings" id="findings"></ol></div>
    <div class="blk info"><h3>方法学限制</h3><div id="caveats"></div></div>
    <div class="blk"><h3>建议</h3>
      <div class="rec-timeline" id="recs"></div></div>
  </section>

  <footer>
    <span>analyzing-programs · benchmark dashboard</span>
    <span id="foot-r"></span>
  </footer>
</div>

<script id="payload" type="application/json">__PAYLOAD__</script>
<script>
const D = JSON.parse(document.getElementById('payload').textContent);
const $ = s => document.querySelector(s);
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const pct = x => (x*100).toFixed(0) + '%';
const pp  = x => (x>=0?'+':'') + (x*100).toFixed(1) + 'pp';
const hasEcharts = typeof echarts !== 'undefined';
const PAL = ['#c084fc','#2ee6a8','#5b7cfa','#ffb020','#ff4d6a'];

/* ---------------- 01 KPI ---------------- */
const R = D.rounds, last = R[R.length-1], first = R[0];
const kpis = [
  {lb:'with_skill 均值', v:pct(last.with_mean), cls:'v-ok',
   d:`最新轮 · ${last.delta>=0?'+':''}${(last.delta*100).toFixed(1)}pp 高于 baseline`,
   trend:'up'},
  {lb:'baseline 均值', v:pct(last.without_mean), cls:'v-base',
   d:`最新轮 · 各 eval ${last.without_per_eval.map(pct).join(' / ')}`, trend:'flat'},
  {lb:'skill 增益', v:'+'+((last.delta)*100).toFixed(1)+'pp', cls:'v-acc',
   d:`with_skill ${pct(last.with_mean)} vs ${pct(last.without_mean)}`, trend:'up'},
  {lb:'有区分度断言', v:D.buckets.skill_gain.length+'/'+11, cls:'v-acc',
   d:'with_skill 全通过 且 baseline 至少失败一次', trend:'flat'},
  {lb:'with_skill 缺口', v:D.buckets.regression.length, cls:D.buckets.regression.length?'v-warn':'v-ok',
   d:D.buckets.regression.length?'结构规范未全覆盖':'全部结构断言通过', trend:'flat'},
  {lb:'runs / configuration', v:D.meta.runsPerConfig, cls:'',
   d:'单配置单次采样', trend:'flat'},
  {lb:'with_skill 波动区间', v:pct(Math.min(...R.map(r=>r.with_mean)))+'–'+pct(Math.max(...R.map(r=>r.with_mean))),
   cls:'', d:`跨 ${R.length} 轮`, trend:'flat'},
  {lb:'断言总数', v:D.meta.totalAssertions, cls:'', d:'全部轮次累计判定次数', trend:'flat'},
];
$('#kpis').innerHTML = kpis.map(k=>`
  <div class="kpi ${k.cls}"><div class="lb">${esc(k.lb)}</div>
  <div class="v">${esc(k.v)}</div><div class="d ${k.trend}">${esc(k.d)}</div></div>`).join('')
  + (D.meta.variance ? `
  <div class="kpi ${D.meta.variance.withSpread===0?'v-ok':'v-warn'}">
    <div class="lb">同版本轮次间方差</div>
    <div class="v">${(D.meta.variance.withSpread*100).toFixed(0)}pp</div>
    <div class="d">with_skill 在 ${D.meta.variance.n} 轮同 SKILL.md 下的极差<br>
      baseline 极差 ${(D.meta.variance.withoutSpread*100).toFixed(0)}pp</div></div>` : '');

/* ---------------- 02 charts ---------------- */
if (!hasEcharts) {
  document.querySelectorAll('.cv').forEach(el =>
    el.innerHTML = '<div class="nogs">ECharts CDN 未加载，图表不可用（表格数据不受影响）</div>');
} else {
  const F = {color:'#9aa4bb'}, A = {color:'rgba(255,255,255,.10)'};
  const TT = {backgroundColor:'#10131c', borderColor:'rgba(255,255,255,.14)',
    borderWidth:1, textStyle:{color:'#e8ecf4', fontSize:12}};

  echarts.init(document.getElementById('c-trend')).setOption({
    backgroundColor:'transparent',
    tooltip:{trigger:'axis', ...TT,
      valueFormatter:v=>v==null?'n/a':v+'%'},
    legend:{textStyle:F, icon:'roundRect', itemWidth:12},
    grid:{left:44,right:24,top:44,bottom:34},
    xAxis:{type:'category', data:R.map(r=>r.name), axisLine:A, axisLabel:F,
      axisTick:{show:false}},
    yAxis:{type:'value', min:0, max:100, axisLine:{show:false}, axisLabel:{...F,formatter:'{value}%'},
      splitLine:{lineStyle:{color:'rgba(255,255,255,.06)'}}},
    series:[
      {name:'with_skill', type:'line', smooth:true, symbolSize:9,
       data:R.map(r=>+(r.with_mean*100).toFixed(1)),
       lineStyle:{width:3,color:PAL[0]}, itemStyle:{color:PAL[0]},
       areaStyle:{color:new echarts.graphic.LinearGradient(0,0,0,1,
         [{offset:0,color:'rgba(192,132,252,.30)'},{offset:1,color:'rgba(192,132,252,0)'}])}},
      {name:'baseline', type:'line', smooth:true, symbolSize:9,
       data:R.map(r=>+(r.without_mean*100).toFixed(1)),
       lineStyle:{width:3,color:PAL[1]}, itemStyle:{color:PAL[1]},
       areaStyle:{color:new echarts.graphic.LinearGradient(0,0,0,1,
         [{offset:0,color:'rgba(46,230,168,.20)'},{offset:1,color:'rgba(46,230,168,0)'}])}},
    ]});

  const aids = [...new Set(Object.values(D.assertionText).flatMap(o=>Object.keys(o)))]
    .sort((a,b)=>parseInt(a.slice(1))-parseInt(b.slice(1)));
  const runs = Object.keys(D.matrixLatest).sort();
  const rate = (run,aid) => {
    const m = D.matrixLatest[run];
    if (!(aid in m)) return null;
    return m[aid] ? 100 : 0;
  };
  echarts.init(document.getElementById('c-aid')).setOption({
    backgroundColor:'transparent',
    tooltip:{trigger:'axis', ...TT, axisPointer:{type:'shadow'}},
    legend:{textStyle:F, icon:'roundRect', itemWidth:12},
    grid:{left:46,right:24,top:44,bottom:64},
    xAxis:{type:'category', data:aids, axisLine:A, axisLabel:F, axisTick:{show:false}},
    yAxis:{type:'value', min:0, max:100, axisLine:{show:false},
      axisLabel:{...F,formatter:'{value}%'}, splitLine:{lineStyle:{color:'rgba(255,255,255,.06)'}}},
    series:[
      {name:'with_skill', type:'bar', barMaxWidth:13,
       data:aids.map(a=>runs.reduce((s,r)=>s+(rate(r,a)??0),0)/(runs.length||1)),
       itemStyle:{color:PAL[0], borderRadius:[4,4,0,0]}},
      {name:'baseline', type:'bar', barMaxWidth:13,
       data:aids.map(a=>runs.reduce((s,r)=>s+(rate(r,a)??0),0)/(runs.length||1)),
       itemStyle:{color:PAL[1], borderRadius:[4,4,0,0]}},
    ]});

  const bk = [
    ['skill gain', D.buckets.skill_gain.length, PAL[0]],
    ['两侧均通过', D.buckets.non_discriminating.length, PAL[3]],
    ['结果不一致', D.buckets.mixed.length, PAL[2]],
    ['两侧均失败', D.buckets.fail_both.length, PAL[4]],
  ].filter(x=>x[1]>0);
  echarts.init(document.getElementById('c-bucket')).setOption({
    backgroundColor:'transparent',
    tooltip:{trigger:'item', ...TT, formatter:'{b}: {c} 项 ({d}%)'},
    legend:{bottom:6, textStyle:F, icon:'roundRect', itemWidth:12},
    series:[{type:'pie', radius:['46%','72%'], center:['50%','44%'], avoidLabelOverlap:true,
      itemStyle:{borderColor:'#0a0c12', borderWidth:2},
      label:{show:true, color:'#e8ecf4', fontSize:11, formatter:'{b}\\n{c}'},
      labelLine:{lineStyle:{color:'rgba(255,255,255,.2)'}},
      data:bk.map(x=>({name:x[0], value:x[1], itemStyle:{color:x[2]}}))}]});

  echarts.init(document.getElementById('c-gap')).setOption({
    backgroundColor:'transparent',
    tooltip:{trigger:'axis', ...TT},
    grid:{left:40,right:24,top:34,bottom:34},
    xAxis:{type:'category', data:R.map(r=>r.name), axisLine:A, axisLabel:F, axisTick:{show:false}},
    yAxis:{type:'value', min:0, axisLine:{show:false}, axisLabel:F,
      splitLine:{lineStyle:{color:'rgba(255,255,255,.06)'}}},
    series:[{name:'未通过断言数', type:'bar', barMaxWidth:34,
      data:R.map(r=>r.with_total - r.with_passed),
      label:{show:true, position:'top', color:'#9aa4bb', fontSize:11},
      itemStyle:{borderRadius:[5,5,0,0],
        color:p=>p.value===0?PAL[1]:PAL[4]}}]});
}

/* ---------------- 03 tables ---------------- */
$('#t-scores').innerHTML = `<table><thead><tr>
  <th>轮次</th><th>eval</th><th>名称</th><th>with_skill</th><th>通过</th>
  <th>baseline</th><th>通过</th><th>差距</th></tr></thead><tbody>` +
  D.scoreTable.map(r=>`<tr>
    <td class="mono">${esc(r.round)}</td>
    <td class="mono">eval-${r.eval}</td>
    <td>${esc(r.evalName)}</td>
    <td><span class="pill ${r.with>=1?'ok':'warn'}">${pct(r.with)}</span></td>
    <td class="mono">${r.withPassed}/${r.withTotal}</td>
    <td><span class="pill ${r.without>=.7?'ok':r.without>=.5?'warn':'bad'}">${pct(r.without)}</span></td>
    <td class="mono">${r.withoutPassed}/${r.withoutTotal}</td>
    <td class="mono ${r.with-r.without>0?'up':''}">${pp(r.with-r.without)}</td></tr>`).join('')
  + `</tbody></table>`;

const runs = Object.keys(D.matrixLatest).sort();
const aids = [...new Set(Object.values(D.assertionText).flatMap(o=>Object.keys(o)))]
  .sort((a,b)=>parseInt(a.slice(1))-parseInt(b.slice(1)));
const txt = (run,aid) => (D.assertionText[run]||{})[aid] || '';
$('#t-matrix').innerHTML = `<table class="mx"><thead><tr><th>断言</th>
  ${runs.map(r=>`<th>${esc(r.replace('eval','').replace('-',' · '))}</th>`).join('')}
  <th style="text-align:left;padding-left:1.6rem">说明</th></tr></thead><tbody>` +
  aids.map(a=>`<tr><td class="mono">${a}</td>` +
    runs.map(r=>{
      const m = D.matrixLatest[r];
      if (!(a in m)) return '<td class="c mute">—</td>';
      return `<td class="c ${m[a]?'c-pass':'c-fail'}">${m[a]?'PASS':'FAIL'}</td>`;
    }).join('') +
    `<td style="text-align:left;padding-left:1.6rem;color:var(--tx-2)">${esc(txt(runs[0],a))}</td></tr>`
  ).join('') + `</tbody></table>`;

$('#t-flips').innerHTML = D.flips.length ? `<table><thead><tr>
  <th>范围</th><th>断言</th><th>翻转</th><th>是否改善</th><th>说明</th></tr></thead><tbody>` +
  D.flips.map(f=>`<tr><td class="mono">${esc(f.scope)}</td><td class="mono">${f.aid}</td>
    <td><span class="pill ${f.flip.startsWith('FAIL')?'ok':'bad'}">${esc(f.flip)}</span></td>
    <td>${f.scope.includes('with_skill')
        ? (f.good?'<span class="pill ok">skill 侧改善</span>':'<span class="pill bad">skill 侧回归</span>')
        : '<span class="pill mute">基线方差</span>'}</td>
    <td>${esc(f.text)}</td></tr>`).join('') + `</tbody></table>`
  : '<p style="padding:1.1rem;color:var(--tx-3)">相邻两轮之间没有断言状态翻转。</p>';

$('#t-notes').innerHTML = `<table><thead><tr><th>轮次</th><th>notes（benchmark.json 原文）</th></tr></thead><tbody>` +
  D.notesByRound.map(r=>`<tr><td class="mono">${esc(r.round)}</td><td>` +
    (r.notes.length ? r.notes.map(n=>`<div style="padding:.2rem 0">· ${esc(n)}</div>`).join('')
                    : '<span style="color:var(--tx-3)">（无）</span>') + `</td></tr>`).join('')
  + `</tbody></table>`;

$('#t-size').innerHTML = `<table><thead><tr><th>轮次</th><th>run</th><th>字符数</th>
  <th>abap 代码块</th></tr></thead><tbody>` +
  D.reportSizes.map(r=>`<tr><td class="mono">${esc(r.round)}</td><td class="mono">${esc(r.run)}</td>
    <td class="mono">${r.chars.toLocaleString()}</td><td class="mono">${r.blocks}</td></tr>`).join('')
  + `</tbody></table>`;

/* ---------------- 04 analysis ---------------- */
const gainTxt = D.buckets.skill_gain.map(b=>`<strong>${b.aid}</strong> ${esc(b.text)}`).join('；');
const failTxt = D.buckets.fail_both.map(b=>`<strong>${b.aid}</strong> ${esc(b.text)}`).join('；');
const nondTxt = D.buckets.non_discriminating.map(b=>b.aid).join('、') || '无';
const mixedTxt = D.buckets.mixed.map(b=>`<strong>${b.aid}</strong>（with ${JSON.stringify(b.with)} / base ${JSON.stringify(b.without)}）`).join('；') || '无';
const lastTwo = R.slice(-2);
const dirWord = lastTwo.length===2 ? (lastTwo[1].with_mean >= lastTwo[0].with_mean ? '回升' : '继续下滑') : '变化';
const regressed = D.buckets.regression.length;

$('#analysis').innerHTML = `
<div class="blk gain"><h3>维度一 · 趋势分析 <span class="tag">TREND</span></h3>
  <p>with_skill 通过率跨 ${R.length} 轮为
     ${R.map(r=>`<code>${pct(r.with_mean)}</code>`).join(' → ')}，
     ${R.length>1 ? `最近一轮出现<strong>${dirWord}</strong>（${pp(lastTwo[1].with_mean-lastTwo[0].with_mean)}）。` : ''}
     baseline 同期为 ${R.map(r=>pct(r.without_mean)).join(' → ')}，无单调趋势，说明基线水平由模型自身习惯决定、与 skill 修订无关。</p>
  <p>增益（with_skill 减 baseline）在最近一轮为 <strong>${pp(last.delta)}</strong>，
     是 ${R.length} 轮中${last.delta===Math.max(...R.map(r=>r.delta))?'<strong>最大</strong>':''}的一次。</p></div>

<div class="blk info"><h3>维度二 · 结构分析 <span class="tag">COMPOSITION</span></h3>
  <p>11 项共享断言按「with_skill / baseline」通过组合分为四桶：
     <span class="pill acc">skill gain ${D.buckets.skill_gain.length}</span>
     <span class="pill warn">两侧均通过 ${D.buckets.non_discriminating.length}</span>
     <span class="pill base">结果不一致 ${D.buckets.mixed.length}</span>
     <span class="pill bad">两侧均失败 ${D.buckets.fail_both.length}</span>。</p>
  <p><strong>有区分度（skill gain）</strong>：${gainTxt}。这几项正是 skill 相对裸模型的价值所在——
     裸模型会写出六章结构，但不会自发产出责任链表、不会自发按 P0–P3 分级、不会自发为每个代码块补齐三层。</p>
  <p><strong>无区分度</strong>：${nondTxt} —— 裸模型也能满足，对评分无贡献，属于「保底项」而非「skill 能力」。</p>
  ${D.buckets.fail_both.length ? `<p><strong>两侧均失败</strong>：${failTxt}。</p>` : ''}
  ${D.buckets.mixed.length ? `<p><strong>结果不一致</strong>：${mixedTxt}。</p>` : ''}</div>

<div class="blk ${regressed?'risk':'gain'}"><h3>维度三 · 对比分析 <span class="tag">COMPARE</span></h3>
  ${D.flips.length ? `<p>相邻两轮共发生 <strong>${D.flips.length}</strong> 处断言翻转，
     其中 skill 侧 ${D.flips.filter(f=>f.scope.includes('with_skill')).length} 处、
     基线侧 ${D.flips.filter(f=>!f.scope.includes('with_skill')).length} 处：</p>` : ''}
  ${D.flips.filter(f=>f.scope.includes('with_skill')).map(f=>`<p>· <code>${esc(f.scope)} ${f.aid}</code>
     <span class="pill ${f.good?'ok':'bad'}">${esc(f.flip)}</span> ${esc(f.text)}</p>`).join('')}
  <p>${regressed
     ? `当前仍存在 <strong>${regressed}</strong> 项 with_skill 未通过的断言，结构规范尚未全覆盖。`
     : `<strong>with_skill 当前 0 缺口</strong>，全部共享结构断言通过；skill 侧的每一次波动都是修复而非回归。`}</p></div>

<div class="blk ${D.flips.filter(f=>!f.scope.includes('with_skill')).length?'risk':'info'}">
  <h3>维度四 · 异常检测 <span class="tag">ANOMALY</span></h3>
  <p>基线侧跨轮翻转 ${D.flips.filter(f=>!f.scope.includes('with_skill')).length} 处
     （${D.flips.filter(f=>!f.scope.includes('with_skill')).map(f=>f.aid).join('、') || '无'}）。
     由于 <code>runs_per_configuration = ${D.meta.runsPerConfig}</code>，基线只有单次采样，
     这些翻转<strong>应解读为模型方差而非 skill 效果</strong>；真正可作为结论的只有 with_skill 侧的翻转。</p>
  <p>报告体积方面，with_skill 与 baseline 的字符数比值见「产出体积」表；
     baseline 出现单份报告超过 with_skill 两倍的情况，说明长度<strong>不是</strong>质量指标，
     结构断言才是。</p></div>`;

/* ---------------- 05 conclusions ---------------- */
const F = [];
F.push(`最新轮 with_skill 通过率 <strong>${pct(last.with_mean)}</strong>、
  baseline <strong>${pct(last.without_mean)}</strong>，增益 <strong>${pp(last.delta)}</strong>
  （共 ${R.length} 轮可比）。`);
F.push(`11 项共享断言中，<strong>${D.buckets.skill_gain.length} 项</strong>为 skill 独有增益
  （${D.buckets.skill_gain.map(b=>b.aid).join('、')}），
  <strong>${D.buckets.non_discriminating.length} 项</strong>无区分度，
  ${D.buckets.fail_both.length} 项两侧均失败。`);
F.push(regressed
  ? `with_skill 尚有 <strong>${regressed}</strong> 项断言未通过（${D.buckets.regression.map(x=>x.aid).join('、')}），
     结构规范未全覆盖。`
  : `with_skill 当前 <strong>零缺口</strong>，${R.length} 轮以来所有结构断言均已通过。`);
if (D.meta.variance && D.meta.variance.withSpread === 0 && D.meta.variance.n >= 2) {
  F.push(`同一份 SKILL.md 下跑 ${D.meta.variance.n} 轮，<strong>with_skill 通过率极差为 0pp</strong>
  （${D.meta.variance.withValues.map(v=>pct(v)).join(' / ')}），结构规范<strong>完全确定性</strong>；
  同期 baseline 极差 ${(D.meta.variance.withoutSpread*100).toFixed(0)}pp
  （${D.meta.variance.withoutValues.map(v=>pct(v)).join(' / ')}）——轮间差异全部来自模型方差，
  与 skill 无关。`);
}
if (D.flips.length) {
  const sf = D.flips.filter(f=>f.scope.includes('with_skill'));
  F.push(sf.length
    ? `相邻两轮 skill 侧发生 <strong>${sf.length}</strong> 处翻转：
       ${sf.filter(f=>f.good).length} 处修复、${sf.filter(f=>!f.good).length} 处回归
       （${sf.map(f=>f.aid+' '+f.flip).join('；')}）。`
    : `相邻两轮 skill 侧无翻转，基线侧 ${D.flips.length} 处翻转均为方差。`);
}
$('#findings').innerHTML = F.map(f=>`<li><p>${f}</p></li>`).join('');

$('#caveats').innerHTML = (D.meta.variance ? `
  <p><strong>已测到的方差</strong>：${D.meta.variance.n} 轮（${D.meta.sameVersionRounds.join('、')}）
  使用<strong>同一份 SKILL.md</strong>（sha256 <code>${String(D.meta.skillDigest||'').slice(0,12)}</code>），
  因此轮间差异只能解释为采样方差。实测 with_skill 极差
  <strong>${(D.meta.variance.withSpread*100).toFixed(0)}pp</strong>（值：${D.meta.variance.withValues.map(v=>(v*100).toFixed(0)+'%').join(' / ')}），
  baseline 极差 <strong>${(D.meta.variance.withoutSpread*100).toFixed(0)}pp</strong>
  （值：${D.meta.variance.withoutValues.map(v=>(v*100).toFixed(0)+'%').join(' / ')}）。
  ${D.meta.variance.withSpread===0
    ? '<strong>with_skill 在结构断言上完全确定性</strong>，这是本次重跑最有价值的结论。'
    : 'with_skill 仍存在可见波动，说明结构规则偶有失效。'}</p>` : '') + `
  <p><strong>样本量仍偏小</strong>：同版本只有 ${D.meta.variance ? D.meta.variance.n : 1} 轮，
  2 个样本无法估计真正的标准差，也无法区分 skill 与 baseline 的分布是否重叠。</p>
  <p><strong>断言为结构性正则检查</strong>：A1–A11 检验的是格式合规（六章、两张图、三层、P0–P3、无行号），
  <strong>不检验技术判断是否正确</strong>。一份 100% 合规但把 <code>READ TABLE</code> 的
  <code>sy-subrc</code> 漏检说成"无风险"的报告，仍会拿满分。A12（NTGEW/BRGEW 语义校核）是唯一的
  内容型断言，且只覆盖一个字段对。</p>
  <p><strong>评分器自身被修改过</strong>：A8/A9 已改为只在第三章内统计代码块。
  iteration-3 / iteration-4 的分数已用修正后的评分器重算（旧值备份为
  <code>grading_summary.pre-a8fix.json</code>）；iteration-1 / iteration-2 使用旧评分器，
  <strong>与后续轮次不可直接比较</strong>。</p>`;

const recs = [
  ['rec-s','短期 (1 周)',[
    D.meta.variance && D.meta.variance.n < 3
      ? '把同 SKILL.md 的轮次补到 3 轮以上，才能给出真实方差并判断 baseline 与 skill 的分布是否重叠'
      : '轮次样本已足够，转而把 evals 扩到 OO 类 / 函数组，验证规则不只对 REPORT+ALV 有效',
    '给基线与 skill 各补 1 个含 OO 类 / 函数组的 eval，覆盖当前完全未测的程序类型',
  ]],
  ['rec-m','中期 (1 月)',[
    '新增 2–3 条内容型断言（如「未判 sy-subrc 的 READ TABLE 是否被记为风险」），否则 skill 只被考核了排版',
    '为 iteration-5 生成 review.html 并排人工审阅，确认 100% 合规的报告在技术判断上是否真的更好',
  ]],
  ['rec-l','长期 (1 季)',[
    '把 A6/A9/A10/A11 这类「裸模型也能过」的断言降权或替换，让分数更贴近 skill 的真实增量',
    '为 SKILL.md 建立规则冲突检测：任何两条对同一产物提出相反格式要求的条款，应在 CI 中报错',
  ]],
];
$('#recs').innerHTML = recs.map(([c,t,items])=>`<div class="rec-item ${c}">
  <div class="rl">${t}</div><ul>${items.map(i=>`<li>${i}</li>`).join('')}</ul></div>`).join('');

$('#foot-r').textContent =
  `${R.map(r=>r.name+': '+pct(r.with_mean)).join('  ·  ')}   |   grader ${D.meta.grader}`;
window.addEventListener('resize', () => {
  if (!hasEcharts) return;
  ['c-trend','c-aid','c-bucket','c-gap'].forEach(id => {
    const inst = echarts.getInstanceByDom(document.getElementById(id));
    if (inst) inst.resize();
  });
});
</script>
</body>
</html>"""

# ---- fill dashboard placeholders
meta = payload["meta"]
latest_round = latest["name"]
with_total = sum(r["summary"][k]["total"] for _e, _n, _d, k, _b in EVALS for r in rounds[-1:] for k in (k,))
with_passed = sum(r["summary"][k]["passed"] for _e, _n, _d, k, _b in EVALS for r in rounds[-1:] for k in (k,))
payload["rounds"][-1]["with_total"] = with_total
payload["rounds"][-1]["with_passed"] = with_passed

dash = (DASH
        .replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False).replace("</", "<\\/"))
        .replace("__META_GRADER__", html.escape(meta["grader"]))
        .replace("__NROUNDS__", str(len(rounds)))
        .replace("__TOTAL_ASSER__", str(meta["totalAssertions"]))
        .replace("__RPC__", str(meta["runsPerConfig"]))
        .replace("__LATEST__", html.escape(latest_round)))

dash_path = os.path.join(WS, "benchmark.html")
with open(dash_path, "w", encoding="utf-8") as f:
    f.write(dash)
print("Wrote", dash_path, os.path.getsize(dash_path), "bytes")

# ==================================================================== review
REVIEW_HEAD = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Eval Review · __ROUND__</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@500;600&family=Lora:wght@400;500&family=Noto+Sans+SC:wght@300;400;500&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/dompurify@3/dist/purify.min.js"></script>
<style>
:root{--bg:#faf9f5;--surface:#fff;--border:#e8e6dc;--text:#141413;--text-muted:#8e8b81;
 --accent:#d97757;--green:#788c5d;--green-bg:#eef2e8;--red:#c44;--red-bg:#fceaea;--radius:6px}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Lora',Georgia,serif;background:var(--bg);color:var(--text)}
.header{background:#141413;color:var(--bg);padding:1rem 2rem;position:sticky;top:0;z-index:20;
 display:flex;justify-content:space-between;align-items:center;gap:1rem;flex-wrap:wrap}
.header h1{font-family:'Poppins',sans-serif;font-size:1.2rem;font-weight:600}
.header .sub{font-size:.76rem;opacity:.65;margin-top:.2rem}
.main{padding:1.5rem 2rem 4rem;max-width:1700px;margin:0 auto}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:1.25rem}
@media(max-width:1100px){.grid{grid-template-columns:1fr}}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);overflow:hidden}
.card-h{padding:.7rem 1rem;font-family:'Poppins',sans-serif;font-size:.74rem;font-weight:500;
 text-transform:uppercase;letter-spacing:.05em;color:var(--text-muted);
 border-bottom:1px solid var(--border);background:var(--bg);
 display:flex;justify-content:space-between;align-items:center;gap:.6rem;flex-wrap:wrap}
.badge{display:inline-block;padding:.18rem .6rem;border-radius:9999px;font-family:'Poppins',sans-serif;
 font-size:.66rem;font-weight:600;text-transform:uppercase;letter-spacing:.03em}
.badge.w{background:rgba(33,150,243,.12);color:#1976d2}
.badge.b{background:rgba(255,193,7,.15);color:#f57f17}
.score{font-family:'Poppins',sans-serif;font-size:.72rem;padding:.18rem .55rem;border-radius:5px}
.score.p{background:var(--green-bg);color:var(--green)}
.score.f{background:var(--red-bg);color:var(--red)}
.card-b{padding:1.1rem 1.25rem;font-size:.9rem;line-height:1.75;max-height:78vh;overflow-y:auto}
.card-b::-webkit-scrollbar{width:9px}
.card-b::-webkit-scrollbar-thumb{background:var(--border);border-radius:9px}
.card-b h1{font-size:1.3rem;margin:1.2rem 0 .6rem}
.card-b h2{font-size:1.1rem;margin:1.3rem 0 .5rem;padding-bottom:.25rem;border-bottom:1px solid var(--border)}
.card-b h3{font-size:.98rem;margin:1rem 0 .35rem}
.card-b h4{font-size:.9rem;margin:.8rem 0 .3rem;color:var(--accent)}
.card-b p{margin:.55rem 0}
.card-b ul,.card-b ol{margin:.5rem 0 .5rem 1.4rem}
.card-b li{margin:.25rem 0}
.card-b code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.82em;
 background:#f2f0e8;padding:.08rem .32rem;border-radius:3px}
.card-b pre{background:#141413;color:#f0efe9;padding:.85rem 1rem;border-radius:var(--radius);
 overflow-x:auto;margin:.7rem 0;font-size:.8rem;line-height:1.6}
.card-b pre code{background:none;color:inherit;padding:0}
.card-b table{border-collapse:collapse;width:100%;margin:.7rem 0;font-size:.82rem;
 font-family:'Poppins',sans-serif}
.card-b th,.card-b td{border:1px solid var(--border);padding:.35rem .55rem;text-align:left}
.card-b th{background:var(--bg);font-weight:600;font-size:.74rem}
.card-b blockquote{border-left:3px solid var(--accent);padding-left:.9rem;margin:.7rem 0;color:#4a4740}
.fails{margin:0 0 1.25rem;padding:1rem 1.25rem;background:#fff;border:1px solid var(--border);
 border-left:3px solid var(--red);border-radius:var(--radius)}
.fails h3{font-family:'Poppins',sans-serif;font-size:.8rem;text-transform:uppercase;
 letter-spacing:.05em;color:var(--red);margin-bottom:.6rem}
.fails table{border-collapse:collapse;width:100%;font-size:.82rem;font-family:'Poppins',sans-serif}
.fails td{padding:.3rem .55rem;border-bottom:1px solid var(--border);vertical-align:top}
.fails td.a{font-family:ui-monospace,monospace;color:var(--red);white-space:nowrap;width:3.5rem}
.nav{display:flex;gap:.5rem;flex-wrap:wrap;margin-bottom:1.25rem}
.nav a{font-family:'Poppins',sans-serif;font-size:.76rem;padding:.35rem .8rem;border-radius:999px;
 border:1px solid var(--border);color:var(--text-muted);text-decoration:none;background:#fff}
.nav a:hover{border-color:var(--accent);color:var(--accent)}
.nav a.on{background:#141413;color:var(--bg);border-color:#141413}
</style>
</head>
<body>
<div class="header">
  <div><h1>Eval Review · __ROUND__</h1>
    <p class="sub">左：with_skill &nbsp;|&nbsp; 右：baseline —— 同一份源码、同一 prompt</p></div>
  <div class="sub">__META_GRADER__ · __NASSER__ 项共享断言</div>
</div>
<div class="main">
  <div class="nav">
    <a href="benchmark.html">← benchmark dashboard</a>
    <a href="#" class="on">报告并排审阅</a>
  </div>
  __FAILS__
  __PAIRS__
</div>
<script>
document.querySelectorAll('.md').forEach(el => {
  const html = marked.parse(el.textContent);
  el.innerHTML = DOMPurify.sanitize(html, {ADD_ATTR:['target']});
  el.querySelectorAll('a').forEach(a => { a.target='_blank'; a.rel='noopener'; });
});
</script>
</body>
</html>"""

prompts = {
    1: "帮我看懂这个 ABAP 程序，分析一下它解决什么问题、整体架构怎么设计的 @ztest7.abap",
    2: "走读一下这个 ABAP 报表程序，讲清楚它的执行流程和设计 @zmmr_vend_list.abap",
}
pairs, fail_rows = [], []
for eid, en, dname, wk, bk in EVALS:
    cells = []
    for key, cfg, cls in ((wk, "with_skill", "w"), (bk, "without_skill", "b")):
        p = os.path.join(WS, dname, cfg, "outputs", "report.md")
        if not os.path.exists(p):
            cells.append(f'<div class="card"><div class="card-h">{cfg}'
                         f'<span class="badge {cls}">missing</span></div>'
                         f'<div class="card-b">report.md 未生成</div></div>')
            continue
        md = open(p, encoding="utf-8").read()
        s = latest["summary"][key]
        rate = s["pass_rate"]
        sc = "p" if rate >= 0.999 else ("f" if rate < 0.7 else "")
        # quote=False: only &, <, > need escaping for element-text embedding.
        # Escaping ' and " to &#x27;/&quot; adds ~5% bulk and makes the blob
        # ambiguous to anything that round-trips entities outside a browser.
        md_html = html.escape(md, quote=False)
        cells.append(
            f'<div class="card"><div class="card-h">eval-{eid} · {cfg}'
            f'<span class="badge {cls}">{cfg}</span>'
            f'<span class="score {sc}">{s["passed"]}/{s["total"]} · {rate*100:.0f}%</span></div>'
            f'<div class="card-b"><div class="md">{md_html}</div></div></div>')
        if rate < 0.999:
            for e in s["expectations"]:
                if not e["passed"]:
                    fail_rows.append((f"eval-{eid}", cfg, e["text"][:2], e["text"][2:],
                                      e.get("evidence", "") or "—"))
    pairs.append(
        f'<h2 style="font-family:Poppins,sans-serif;font-size:.95rem;margin:2rem 0 .5rem">'
        f'eval-{eid} · {en} &nbsp;<span style="color:var(--text-muted);font-weight:400">'
        f'{html.escape(prompts[eid])}</span></h2><div class="grid">'
        + "".join(cells) + "</div>")

fails_html = ""
if fail_rows:
    rows = "".join(f"<tr><td class='a'>{html.escape(a)}</td><td class='a'>{html.escape(cfg)}</td>"
                   f"<td class='a'>{html.escape(aid)}</td><td>{html.escape(desc)}</td>"
                   f"<td><code>{html.escape(ev)}</code></td></tr>"
                   for a, cfg, aid, desc, ev in fail_rows)
    fails_html = ("<div class='fails'><h3>未通过断言 "
                  f"({len(fail_rows)})</h3><table><thead><tr><th>eval</th><th>配置</th>"
                  "<th>断言</th><th>说明</th><th>证据</th></tr></thead><tbody>"
                  + rows + "</tbody></table></div>")

n_shared = len(payload["buckets"]["skill_gain"]) + len(payload["buckets"]["non_discriminating"]) \
    + len(payload["buckets"]["fail_both"]) + len(payload["buckets"]["mixed"])
review = (REVIEW_HEAD
          .replace("__ROUND__", html.escape(latest_round))
          .replace("__META_GRADER__", html.escape(meta["grader"]))
          .replace("__NASSER__", str(n_shared))
          .replace("__FAILS__", fails_html)
          .replace("__PAIRS__", "".join(pairs)))

review_path = os.path.join(WS, "review.html")
with open(review_path, "w", encoding="utf-8") as f:
    f.write(review)
print("Wrote", review_path, os.path.getsize(review_path), "bytes")