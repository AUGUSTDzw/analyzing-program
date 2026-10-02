#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build iteration-8 benchmark.html — two independent verdict layers.

The point of this page is that it must NOT average the two layers into one
number. Format compliance and technical correctness are different questions and
the results disagree sharply:

    format      with_skill 0.987 vs baseline 0.546   p = 2.4e-19  SIGNIFICANT
    correctness with_skill 0.766 vs baseline 0.729   p = 1.00     NOT significant

Averaging would hide the second result, which is the one worth acting on.
"""
import json, os, sys

WS = sys.argv[1]
B = json.load(open(os.path.join(WS, "benchmark.json"), encoding="utf-8"))
G = B["judge"]
PC, PS = B["paired_format"], G["paired_sign_test"]

EVAL_NAMES = {e["id"]: e["name"] for e in B["metadata"]["evals"]}
fmt_cells = {k: v for k, v in B["per_cell"].items()}

payload = {
    "evalNames": EVAL_NAMES,
    "format": {
        "cells": [
            {"key": k, "eval": v["eval_id"], "config": v["config"],
             "mean": v["pass_rate_mean"], "runs": v["per_run"],
             "min": v["pass_rate_min"], "max": v["pass_rate_max"]}
            for k, v in fmt_cells.items()],
        "with": B["summary"]["with_skill_mean"],
        "without": B["summary"]["without_skill_mean"],
        "delta": B["summary"]["delta_pp"],
        "paired": B["paired_format"],
        "p": B["paired_format"]["mcnemar_exact_two_sided_p"],
    },
    "judge": {
        "cells": [
            {"key": k, "eval": v["eval_id"], "config": v["config"],
             "mean": v["mean"], "runs": v["per_run"],
             "min": v["min"], "max": v["max"]}
            for k, v in G["per_cell"].items()],
        "with": G["summary"]["with_skill_mean"],
        "without": G["summary"]["without_skill_mean"],
        "delta": G["summary"]["delta_pp"],
        "sign": PS,
        "perDefect": [
            {"key": k, "eval": v["eval"], "defect": v["defect"], "area": v["area"],
             "question": v["question"],
             "with": v["with_skill"]["score"], "base": v["without_skill"]["score"]}
            for k, v in G["per_defect"].items()],
        "runs": [
            {"key": k, "eval": v["eval_id"], "config": v["config"], "run": v["run"],
             "score": v["score"], "found": v["found"], "partial": v["partial"],
             "missed": v["missed"], "total": v["total"]}
            for k, v in G["per_run"].items()],
    },
    "assertions": [
        {"aid": a, "kind": v["kind"], "with": v["with_rate"],
         "base": v["without_rate"], "cells": v["applicable_cells"]}
        for a, v in sorted(B["assertion_stats"].items(),
                           key=lambda x: int(x[0][1:]))],
    "findings": B["headline_findings"],
    "meta": {
        "grader": B["metadata"]["grader"],
        "runs": B["metadata"]["runs_per_configuration"],
        "nEvals": len(EVAL_NAMES),
        "measurement": B["metadata"]["measurement"],
        "stats": B["metadata"]["stats"],
    },
}

HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>analyzing-programs · iteration-8</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&family=Noto+Sans+SC:wght@300;400;500;700&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
:root{--bg:#08090d;--card:rgba(255,255,255,.035);--ch:rgba(255,255,255,.06);
--line:rgba(255,255,255,.09);--tx:#e9edf4;--tx2:#9aa4bb;--tx3:#5f6880;
--ok:#2ee6a8;--bad:#ff4d6a;--warn:#ffb020;--base:#5b7cfa;--acc:#c084fc;
--mono:'IBM Plex Mono',ui-monospace,monospace;--r:14px}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--tx);font-family:'Space Grotesk','Noto Sans SC',system-ui,sans-serif;line-height:1.65;-webkit-font-smoothing:antialiased}
body::before{content:'';position:fixed;inset:0;z-index:-1;pointer-events:none;
background:radial-gradient(900px 480px at 10% -6%,rgba(255,77,106,.13),transparent 60%),
radial-gradient(880px 500px at 90% -4%,rgba(46,230,168,.11),transparent 62%),
repeating-linear-gradient(0deg,rgba(255,255,255,.013) 0 1px,transparent 1px 3px)}
.wrap{max-width:1300px;margin:0 auto;padding:0 2rem 5rem}
.rpt-header{display:flex;justify-content:space-between;align-items:flex-end;gap:2rem;
padding:3.2rem 0 1.8rem;border-bottom:1px solid var(--line);margin-bottom:2.2rem;flex-wrap:wrap}
.rpt-header h1{font-size:2rem;font-weight:700;letter-spacing:-.02em;line-height:1.2}
.rpt-header h1 em{font-style:normal;color:var(--bad)}
.rpt-sub{color:var(--tx2);font-size:.88rem;margin-top:.55rem}
.rpt-sub code{font-family:var(--mono);color:var(--ok);font-size:.85em}
.rpt-meta{text-align:right;font-family:var(--mono);font-size:.73rem;color:var(--tx3);line-height:1.9}
.rpt-meta b{color:var(--tx2);font-weight:500}
.sec{margin:3rem 0 0}
.sec-h{display:flex;align-items:baseline;gap:.8rem;margin-bottom:1.2rem;flex-wrap:wrap}
.sec-h .n{font-family:var(--mono);font-size:.7rem;color:var(--acc);border:1px solid rgba(192,132,252,.35);border-radius:5px;padding:.14rem .42rem}
.sec-h h2{font-size:1.22rem;font-weight:600}
.sec-h .hint{font-size:.79rem;color:var(--tx3);margin-left:auto}
/* verdict banner: the whole point is that the two layers disagree */
.verdicts{display:grid;gap:1rem;grid-template-columns:1fr 1fr}
@media(max-width:900px){.verdicts{grid-template-columns:1fr}}
.vd{position:relative;overflow:hidden;border:1px solid var(--line);border-radius:var(--r);
padding:1.4rem 1.5rem;background:var(--card)}
.vd::before{content:'';position:absolute;inset:0 0 auto 0;height:3px}
.vd.f::before{background:linear-gradient(90deg,var(--ok),#5b7cfa)}
.vd.j::before{background:linear-gradient(90deg,var(--warn),var(--bad))}
.vd .t{font-size:.76rem;text-transform:uppercase;letter-spacing:.1em;color:var(--tx3);font-weight:600}
.vd .rows{margin-top:1rem;display:flex;flex-direction:column;gap:.6rem}
.vd .r{display:flex;align-items:baseline;gap:.7rem}
.vd .r .who{font-family:var(--mono);font-size:.72rem;color:var(--tx3);width:104px;flex-shrink:0}
.vd .r .num{font-family:var(--mono);font-size:1.5rem;font-weight:500}
.vd .r .bars{flex:1;display:flex;flex-direction:column;gap:.22rem;padding-left:.3rem}
.vd .bar{height:7px;background:rgba(255,255,255,.07);border-radius:4px;overflow:hidden}
.vd .bar i{display:block;height:100%;border-radius:4px}
.vd .bar.w i{background:linear-gradient(90deg,var(--acc),#7c5cff)}
.vd .bar.b i{background:linear-gradient(90deg,var(--base),#3d5cd6)}
/* lower bar = worst single run in that arm */
.vd .bar.lo i{opacity:.34}
.vd .concl{margin-top:1.15rem;padding-top:.95rem;border-top:1px solid var(--line);
font-size:.83rem;color:var(--tx2)}
.vd .concl b{color:var(--tx)}
.vd .pv{font-family:var(--mono);font-size:.76rem;padding:.16rem .5rem;border-radius:5px;
display:inline-block;margin-top:.55rem}
.pv.sig{background:rgba(46,230,168,.14);color:var(--ok)}
.pv.nsig{background:rgba(255,176,32,.14);color:var(--warn)}
.kpis{display:grid;gap:1rem;grid-template-columns:repeat(auto-fit,minmax(178px,1fr))}
.kpi{position:relative;overflow:hidden;background:var(--card);border:1px solid var(--line);
border-radius:var(--r);padding:1.05rem 1.15rem;transition:.25s}
.kpi::before{content:'';position:absolute;inset:0 0 auto 0;height:2px;background:linear-gradient(90deg,var(--acc),var(--ok))}
.kpi:hover{transform:translateY(-3px);background:var(--ch)}
.kpi .lb{font-size:.69rem;color:var(--tx3);text-transform:uppercase;letter-spacing:.09em;font-weight:500}
.kpi .v{font-family:var(--mono);font-size:1.85rem;font-weight:500;margin:.3rem 0 .08rem;letter-spacing:-.02em}
.kpi .d{font-size:.73rem;color:var(--tx2)}
.charts{display:grid;gap:1rem;grid-template-columns:repeat(auto-fit,minmax(370px,1fr))}
.chart{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:1.05rem 1.2rem 1.2rem}
.chart h3{font-size:.9rem;font-weight:600}
.chart .cs{font-size:.75rem;color:var(--tx3);margin-bottom:.45rem}
.cv{width:100%;height:340px}
.cv.tall{height:470px}
.cv.short{height:290px}
.tbl{background:var(--card);border:1px solid var(--line);border-radius:var(--r);overflow:hidden}
table{width:100%;border-collapse:collapse;font-size:.83rem}
th{text-align:left;font-weight:600;font-size:.69rem;text-transform:uppercase;letter-spacing:.08em;
color:var(--tx3);padding:.72rem .85rem;background:rgba(255,255,255,.03);border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:.62rem .85rem;border-bottom:1px solid rgba(255,255,255,.05);vertical-align:top}
tbody tr:last-child td{border-bottom:none}
tbody tr:hover td{background:rgba(255,255,255,.028)}
td.mono,.mono{font-family:var(--mono);font-size:.81em}
.pill{display:inline-block;padding:.1rem .48rem;border-radius:999px;font-size:.69rem;font-family:var(--mono);font-weight:500}
.pill.ok{background:rgba(46,230,168,.14);color:var(--ok)}
.pill.bad{background:rgba(255,77,106,.14);color:var(--bad)}
.pill.warn{background:rgba(255,176,32,.14);color:var(--warn)}
.pill.mute{background:rgba(255,255,255,.07);color:var(--tx2)}
.pill.acc{background:rgba(192,132,252,.14);color:var(--acc)}
.pos{color:var(--ok)} .neg{color:var(--bad)} .zero{color:var(--tx3)}
.blk{background:var(--card);border:1px solid var(--line);border-radius:var(--r);
padding:1.25rem 1.4rem;margin-bottom:.9rem;border-left:3px solid transparent}
.blk.r{border-left-color:var(--bad)} .blk.g{border-left-color:var(--ok)}
.blk.w{border-left-color:var(--warn)} .blk.a{border-left-color:var(--acc)}
.blk h3{font-size:.96rem;font-weight:600;margin-bottom:.65rem}
.blk p{font-size:.87rem;color:var(--tx2);margin-bottom:.5rem}
.blk p:last-child{margin-bottom:0}
.blk strong{color:var(--tx)}
.blk code{font-family:var(--mono);font-size:.85em;color:var(--acc)}
ol.find{list-style:none;counter-reset:f}
ol.find li{counter-increment:f;position:relative;padding:.85rem 0 .85rem 2.8rem;border-bottom:1px solid rgba(255,255,255,.05)}
ol.find li:last-child{border-bottom:none}
ol.find li::before{content:'F' counter(f);position:absolute;left:0;top:.92rem;font-family:var(--mono);
font-size:.67rem;color:var(--acc);border:1px solid rgba(192,132,252,.4);border-radius:5px;padding:.09rem .36rem}
ol.find p{font-size:.87rem;color:var(--tx2)}
.rec{position:relative;padding-left:1.4rem;border-left:2px solid var(--line);margin-top:.4rem}
.rec-i{position:relative;margin-bottom:1rem}
.rec-i::before{content:'';position:absolute;left:-1.82rem;top:.48rem;width:10px;height:10px;border-radius:50%;border:2px solid;background:var(--bg)}
.rec-s::before{border-color:var(--ok)} .rec-m::before{border-color:var(--base)} .rec-l::before{border-color:var(--acc)}
.rec-i .rl{font-family:var(--mono);font-size:.69rem;letter-spacing:.06em;text-transform:uppercase;margin-bottom:.28rem}
.rec-s .rl{color:var(--ok)} .rec-m .rl{color:var(--base)} .rec-l .rl{color:var(--acc)}
.rec-i ul{list-style:none} .rec-i li{font-size:.85rem;color:var(--tx2);padding-left:1rem;position:relative;margin-bottom:.22rem}
.rec-i li::before{content:'→';position:absolute;left:0;color:var(--tx3)}
footer{margin-top:3.6rem;padding-top:1.4rem;border-top:1px solid var(--line);
font-family:var(--mono);font-size:.71rem;color:var(--tx3);display:flex;justify-content:space-between;gap:1rem;flex-wrap:wrap}
.nogs{font-family:var(--mono);font-size:.79rem;color:var(--warn);padding:.9rem;background:rgba(255,176,32,.08);border:1px solid rgba(255,176,32,.25);border-radius:8px}
</style>
</head>
<body>
<div class="wrap">
<header class="rpt-header">
  <div>
    <h1><em>analyzing-programs</em><br>iteration-8 · 两个判定层</h1>
    <p class="rpt-sub">格式合规 vs 技术正确性 —— 评分器 <code>__GRADER__</code> ·
      <code>__NEVALS__</code> 个程序类型 × 2 配置 × __RUNS__ 次运行 ·
      LLM judge 逐缺陷三值判定</p>
  </div>
  <div class="rpt-meta">
    <div>格式断言 <b>__NASRT__</b> 项 × 适用格</div>
    <div>预埋缺陷 <b>__NDEF__</b> 项</div>
    <div>judge 报告 <b>__NREPORTS__</b> 份</div>
    <div>配对格 <b>__NCELLS__</b> 个</div>
  </div>
</header>

<section class="sec">
  <div class="sec-h"><span class="n">00</span><h2>两个结论互相矛盾</h2>
    <span class="hint">不要把这两层平均成一个数字</span></div>
  <div class="verdicts" id="verdicts"></div>
</section>

<section class="sec">
  <div class="sec-h"><span class="n">01</span><h2>关键指标</h2></div>
  <div class="kpis" id="kpis"></div>
</section>

<section class="sec">
  <div class="sec-h"><span class="n">02</span><h2>可视化</h2>
    <span class="hint">两层分列 · 每程序类型 · 每缺陷</span></div>
  <div class="charts">
    <div class="chart"><h3>两层通过率并列</h3>
      <p class="cs">格式层与 judge 层各自计算，不合并</p>
      <div class="cv" id="c-layers"></div></div>
    <div class="chart"><h3>逐缺陷召回：with_skill vs baseline</h3>
      <p class="cs">__NDEF__ 个预埋缺陷，正值表示 skill 更强</p>
      <div class="cv tall" id="c-defect"></div></div>
    <div class="chart"><h3>每份报告的 judge 分数</h3>
      <p class="cs">20 份报告，2 轮 × 5 eval × 2 配置</p>
      <div class="cv short" id="c-runs"></div></div>
    <div class="chart"><h3>__NASRT__ 项格式断言的区分度</h3>
      <p class="cs">两侧都 100% 的项对区分无贡献</p>
      <div class="cv" id="c-assert"></div></div>
  </div>
</section>

<section class="sec">
  <div class="sec-h"><span class="n">03</span><h2>详细数据</h2></div>
  <div class="charts">
    <div class="chart" style="grid-column:1/-1"><h3>逐 eval × 配置：两层分数</h3>
      <div class="tbl" id="t-cells"></div></div>
    <div class="chart" style="grid-column:1/-1"><h3>逐缺陷判定明细</h3>
      <p class="cs">yes = 1.0，partial = 0.5，no = 0；分数为该配置下 2 次运行的加权命中率</p>
      <div class="tbl" id="t-defect"></div></div>
    <div class="chart" style="grid-column:1/-1"><h3>__NASRT__ 项格式断言</h3>
      <div class="tbl" id="t-assert"></div></div>
  </div>
</section>

<section class="sec">
  <div class="sec-h"><span class="n">04</span><h2>核心发现</h2></div>
  <ol class="find" id="findings"></ol>
</section>

<section class="sec">
  <div class="sec-h"><span class="n">05</span><h2>方法学与建议</h2></div>
  <div class="blk w"><h3>方法学限制（必须先读）</h3><div id="caveats"></div></div>
  <div class="blk a"><h3>建议</h3><div class="rec" id="recs"></div></div>
</section>

<footer><span>analyzing-programs · iteration-8 benchmark</span><span id="foot"></span></footer>
</div>
<script id="payload" type="application/json">__PAYLOAD__</script>
<script>
const D=JSON.parse(document.getElementById('payload').textContent);
const $=s=>document.querySelector(s);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const pct=x=>x==null?'—':(x*100).toFixed(1)+'%';
const bar=v=>`<div class="bar"><i style="width:${(v*100).toFixed(1)}%"></i></div>`;
const sci=p=>p==null?'—':(p===0?'0':(p<1e-4?p.toExponential(2):p.toFixed(4)));

/* ---- 00 the two verdicts, deliberately not averaged ---- */
const F=D.format,J=D.judge;
function vd(cls,title,rows,p,concl,sig){
  return `<div class="vd ${cls}"><div class="t">${title}</div><div class="rows">`+
   rows.map(r=>`<div class="r"><div class="who">${r.who}</div>
     <div class="num">${pct(r.v)}</div>
     <div class="bars"><div class="bar ${r.k}"><i style="width:${(r.v*100).toFixed(1)}%"></i></div>
     <div class="bar ${r.k2}"><i style="width:${(r.v2*100).toFixed(1)}%"></i></div></div></div>`).join('')+
   `</div><div class="concl">${concl}<br><span class="pv ${sig?'sig':'nsig'}">配对检验 p = ${sci(p)}${sig?'':' — 不显著'}</span></div></div>`;
}
// Each card shows two stacked bars per arm: solid = the headline mean,
// faded = the same arm's per-eval spread midpoint. Keeps one number per arm
// (no undefined aggregates) while still showing run-to-run variation.
function vd(cls,title,arms,p,concl,sig){
 return `<div class="vd ${cls}"><div class="t">${title}</div><div class="rows">`+
  arms.map(a=>`<div class="r"><div class="who">${a.who}</div>
    <div class="num">${pct(a.v)}</div>
    <div class="bars">
      <div class="bar ${a.k}"><i style="width:${(a.v*100).toFixed(1)}%"></i></div>
      <div class="bar ${a.k} lo"><i style="width:${(a.lo*100).toFixed(1)}%"></i></div>
    </div></div>`).join('')+
  `</div><div class="concl">${concl}<br><span class="pv ${sig?'sig':'nsig'}">配对检验 p = ${sci(p)}${sig?'':' — 不显著'}</span></div></div>`;
}
const loOf=(cells,cfg)=>{const v=cells.filter(c=>c.config===cfg).map(c=>c.min);
 return v.length?Math.min(...v):0;};
$('#verdicts').innerHTML =
 vd('f','① 格式合规性（__NASRT__ 项结构断言）',[
   {who:'with_skill',k:'w',v:F.with,lo:loOf(D.format.cells,'with_skill')},
   {who:'baseline',k:'b',v:F.without,lo:loOf(D.format.cells,'without_skill')}],
  F.p,
  `with_skill 在 <strong>${F.paired.with_only_pass}</strong> 个配对格上单独通过，baseline 只在
   <strong>${F.paired.without_only_pass}</strong> 个格上单独通过（${F.paired.concordant_pass} 格一致）。
   结构性收益<strong>真实且显著</strong>。`,true)+
 vd('j','② 技术正确性（${D.judge.perDefect.length} 个预埋缺陷 · LLM judge）',[
   {who:'with_skill',k:'w',v:J.with,lo:loOf(J.cells,'with_skill')},
   {who:'baseline',k:'b',v:J.without,lo:loOf(J.cells,'without_skill')}],
  J.sign.exact_two_sided_p,
  `with_skill 高于 baseline <strong>${J.sign.with_higher}</strong> 次、低于 <strong>${J.sign.baseline_higher}</strong> 次、
   持平 <strong>${J.sign.ties}</strong> 次。差值 ${J.delta>0?'+':''}${J.delta}pp，
   <strong>统计上无差异</strong>。`,false);

/* ---- 01 KPIs ---- */
const kp=[
 {lb:'格式层 with_skill',v:pct(F.with),d:`baseline ${pct(F.without)} · Δ ${F.delta}pp`,c:'v-ok'},
 {lb:'技术层 with_skill',v:pct(J.with),d:`baseline ${pct(J.without)} · Δ ${J.delta}pp`,c:'v-warn'},
 {lb:'程序类型覆盖',v:D.meta.nEvals,d:'__EVALKIND__',c:''},
 {lb:'每配置运行次数',v:D.meta.runs,d:'配对设计，可做符号检验',c:''},
 {lb:'预埋缺陷',v:D.judge.perDefect.length,d:'每缺陷 judge 三值判定',c:''},
 {lb:'格式断言',v:D.assertions.length,d:'__KINDDESC__',c:''},
 {lb:'死断言（无区分度）',v:D.assertions.filter(a=>a.with===1&&a.base===1).length,
  d:'两侧都 100%，需降权',c:'v-bad'},
 {lb:'有效断言',v:D.assertions.filter(a=>(a.with??0)>(a.base??0)).length,
  d:'with_skill 严格优于 baseline',c:'v-acc'},
];
$('#kpis').innerHTML=kp.map(k=>`<div class="kpi ${k.c}"><div class="lb">${esc(k.lb)}</div>
 <div class="v">${esc(k.v)}</div><div class="d">${esc(k.d)}</div></div>`).join('');

/* ---- 02 charts ---- */
if(typeof echarts==='undefined'){
 document.querySelectorAll('.cv').forEach(e=>e.innerHTML=
  '<div class="nogs">ECharts CDN 未加载（表格数据不受影响）</div>');
}else{
 const TX={color:'#9aa4bb'},LN={color:'rgba(255,255,255,.10)'};
 const TT={backgroundColor:'#10131c',borderColor:'rgba(255,255,255,.14)',borderWidth:1,
  textStyle:{color:'#e9edf4',fontSize:12}};
 const evs=[...new Set(D.format.cells.map(c=>c.eval))].sort();
 const g=(k,cfg)=>D.format.cells.find(c=>c.key===k);
 const wv=evs.map(e=>g(`eval-${e}-with_skill`)?.mean??null);
 const bv=evs.map(e=>g(`eval-${e}-without_skill`)?.mean??null);
 const jw=evs.map(e=>J.cells.find(c=>c.key===`eval-${e}-with_skill`)?.mean??null);
 const jb=evs.map(e=>J.cells.find(c=>c.key===`eval-${e}-without_skill`)?.mean??null);
 const en=x=>x==null?'':evs[x];

 echarts.init($('#c-layers')).setOption({backgroundColor:'transparent',
  tooltip:{trigger:'axis',...TT,axisPointer:{type:'shadow'}},legend:{textStyle:TX,icon:'roundRect',itemWidth:12},
  grid:{left:42,right:18,top:40,bottom:34},
  xAxis:{type:'category',data:evs.map(en),axisLine:LN,axisLabel:TX,axisTick:{show:false}},
  yAxis:{type:'value',min:0,max:1,axisLine:{show:false},axisLabel:{...TX,formatter:v=>(v*100).toFixed(0)+'%'},
   splitLine:{lineStyle:{color:'rgba(255,255,255,.06)'}}},
  series:[
   {name:'格式 with_skill',type:'bar',data:wv,barMaxWidth:16,itemStyle:{color:'#c084fc',borderRadius:[4,4,0,0]}},
   {name:'格式 baseline',type:'bar',data:bv,barMaxWidth:16,itemStyle:{color:'#5b7cfa',borderRadius:[4,4,0,0]}},
   {name:'技术 with_skill',type:'bar',data:jw,barMaxWidth:16,itemStyle:{color:'#2ee6a8',borderRadius:[4,4,0,0]}},
   {name:'技术 baseline',type:'bar',data:jb,barMaxWidth:16,itemStyle:{color:'#ffb020',borderRadius:[4,4,0,0]}},
  ]});

 const dds=J.perDefect.slice().sort((a,b)=>(a.with??0)-(b.with??0));
 echarts.init($('#c-defect')).setOption({backgroundColor:'transparent',
  tooltip:{trigger:'axis',...TT,axisPointer:{type:'shadow'},valueFormatter:v=>(v*100).toFixed(0)+'%'},
  legend:{textStyle:TX,icon:'roundRect',itemWidth:12},
  grid:{left:110,right:22,top:40,bottom:40},
  xAxis:{type:'value',min:0,max:1,axisLine:{show:false},axisLabel:{...TX,formatter:'{value}'},
   splitLine:{lineStyle:{color:'rgba(255,255,255,.06)'}}},
  yAxis:{type:'category',data:dds.map(d=>`${d.key} ${d.area}`),axisLine:LN,axisLabel:{...TX,fontSize:10}},
  series:[
   {name:'with_skill',type:'bar',data:dds.map(d=>d.with),barMaxWidth:9,
    itemStyle:{color:'#c084fc',borderRadius:[0,4,4,0]}},
   {name:'baseline',type:'bar',data:dds.map(d=>d.base),barMaxWidth:9,
    itemStyle:{color:'#5b7cfa',borderRadius:[0,4,4,0]}},
  ]});

 echarts.init($('#c-runs')).setOption({backgroundColor:'transparent',
  tooltip:{trigger:'axis',...TT,valueFormatter:v=>(v*100).toFixed(0)+'%'},
  legend:{textStyle:TX,icon:'roundRect',itemWidth:12},
  grid:{left:40,right:18,top:40,bottom:62},
  xAxis:{type:'category',data:J.runs.map(r=>`e${r.eval}·${r.config==='with_skill'?'W':'B'}·r${r.run}`),
   axisLine:LN,axisLabel:{...TX,fontSize:9,rotate:52},axisTick:{show:false}},
  yAxis:{type:'value',min:0,max:1,axisLine:{show:false},axisLabel:{...TX,formatter:v=>(v*100).toFixed(0)+'%'},
   splitLine:{lineStyle:{color:'rgba(255,255,255,.06)'}}},
  series:[
   {name:'judge 分数',type:'bar',barMaxWidth:18,data:J.runs.map(r=>r.score),
    itemStyle:{color:p=>p.value>=0.85?'#2ee6a8':p.value>=0.6?'#c084fc':'#ff4d6a',borderRadius:[4,4,0,0]}},
  ]});

 echarts.init($('#c-assert')).setOption({backgroundColor:'transparent',
  tooltip:{trigger:'axis',...TT,axisPointer:{type:'shadow'},valueFormatter:v=>(v*100).toFixed(0)+'%'},
  legend:{textStyle:TX,icon:'roundRect',itemWidth:12},
  grid:{left:40,right:18,top:40,bottom:40},
  xAxis:{type:'category',data:D.assertions.map(a=>a.aid),axisLine:LN,axisLabel:TX,axisTick:{show:false}},
  yAxis:{type:'value',min:0,max:1,axisLine:{show:false},axisLabel:{...TX,formatter:v=>(v*100).toFixed(0)+'%'},
   splitLine:{lineStyle:{color:'rgba(255,255,255,.06)'}}},
  series:[
   {name:'with_skill',type:'bar',barMaxWidth:11,data:D.assertions.map(a=>a.with),
    itemStyle:{color:'#c084fc',borderRadius:[3,3,0,0]}},
   {name:'baseline',type:'bar',barMaxWidth:11,data:D.assertions.map(a=>a.base),
    itemStyle:{color:'#5b7cfa',borderRadius:[3,3,0,0]}},
  ]});
}

/* ---- 03 tables ---- */
$('#t-cells').innerHTML=`<table><thead><tr><th>eval</th><th>名称</th><th>配置</th>
 <th>格式层</th><th>2 次运行</th><th>技术层</th><th>2 次运行</th></tr></thead><tbody>`+
 D.format.cells.map(f=>{
  const j=J.cells.find(c=>c.key===f.key);
  return `<tr><td class="mono">eval-${f.eval}</td><td>${esc(D.evalNames[f.eval])}</td>
   <td>${f.config==='with_skill'?'<span class="pill acc">with_skill</span>':'<span class="pill base">baseline</span>'}</td>
   <td class="mono">${pct(f.mean)}</td><td class="mono">${f.runs.map(x=>(x*100).toFixed(0)+'%').join(' / ')}</td>
   <td class="mono">${j?pct(j.mean):'—'}</td><td class="mono">${j?j.runs.map(x=>(x*100).toFixed(0)+'%').join(' / '):'—'}</td></tr>`;
 }).join('')+`</tbody></table>`;

$('#t-defect').innerHTML=`<table><thead><tr><th>缺陷</th><th>领域</th><th>with_skill</th>
 <th>baseline</th><th>Δ</th><th>判据</th></tr></thead><tbody>`+
 J.perDefect.map(d=>{
  const dl=(d.with??0)-(d.base??0),cls=dl>0.05?'pos':dl<-0.05?'neg':'zero';
  return `<tr><td class="mono">${esc(d.key)}</td><td>${esc(d.area)}</td>
   <td class="mono">${pct(d.with)}</td><td class="mono">${pct(d.base)}</td>
   <td class="mono ${cls}">${dl>0?'+':''}${(dl*100).toFixed(0)}pp</td>
   <td style="color:var(--tx2)">${esc(d.question)}</td></tr>`;
 }).join('')+`</tbody></table>`;

$('#t-assert').innerHTML=`<table><thead><tr><th>断言</th><th>类别</th><th>with_skill</th>
 <th>baseline</th><th>适用格</th><th>区分度</th></tr></thead><tbody>`+
 D.assertions.map(a=>{
  const dead=(a.with===1&&a.base===1);
  return `<tr><td class="mono">${a.aid}</td><td>${esc(a.kind)}</td>
   <td class="mono">${pct(a.with)}</td><td class="mono">${pct(a.base)}</td>
   <td class="mono">${a.cells}</td>
   <td>${dead?'<span class="pill bad">无区分度</span>'
     :(a.with>a.base?'<span class="pill ok">有效</span>':'<span class="pill warn">反向</span>')}</td></tr>`;
 }).join('')+`</tbody></table>`;

/* ---- 04 findings ---- */
$('#findings').innerHTML=D.findings.map(f=>`<li><p>${esc(f)}</p></li>`).join('');

/* ---- 05 caveats + recs ---- */
$('#caveats').innerHTML=`
 <p><strong>两层不可合并。</strong>格式层 p = ${sci(F.p)}（显著），技术层 p = ${sci(J.sign.exact_two_sided_p)}（不显著）。
 合并成单一分数会同时掩盖"结构收益真实"和"技术无增益"这两个相反事实。</p>
 <p><strong>judge 是单点评审。</strong>每个 eval 的 2 份报告由同一个 judge 一次性判定，
 无 judge 间一致性数据；judge 自身可能与出题者共享盲点。__NDEF__ 个缺陷的判据用关键词辅助，
 但最终是语义判断，优于正则。</p>
 <p><strong>缺陷是预埋的。</strong>真实代码的缺陷分布未必如此集中（每个 fixture __DEFMIN__–__DEFMAX__ 个刻意缺陷），
 因此技术层的绝对值不可外推，只可用于 with/baseline 的<strong>相对</strong>比较。</p>
 <p><strong>n = 2。</strong>每格 2 次运行足以做符号检验，但不足以估计方差。
 这正是上一轮「2 个样本算不出标准差」问题的诚实答案：<strong>放弃方差，改用配对检验</strong>。</p>
 <p><strong>耗时与 token 未采集。</strong>${esc(D.meta.measurement.time_seconds)}
  ${esc(D.meta.measurement.tokens)}</p>`;

$('#recs').innerHTML=[['rec-s','短期',[
  `删掉或降权两侧都 100% 的断言（本轮 ${D.assertions.filter(a=>a.with===1&&a.base===1).length}/${D.assertions.length} 条）—— 它们不产生任何信号，只让分数好看`,
  `关键词断言（A14–A23）已由 judge 取代，从评分器中移除，避免再次误导`,
  `judge 子代理产出的 evidence 文本必须 JSON 转义：本轮 __NBADJSON__ 份文件因裸双引号无法解析，需在派发模板里给出转义要求或加一道解析校验`,
]],
['rec-m','中期',[
  `把 runs_per_configuration 提到 3，配合符号检验做 power 分析——但先修判分层饱和，否则加样本只是把噪声估得更准`,
  `给 judge 加 2 名独立评审，报告 Cohen kappa，验证判定本身可靠`,
  `把 skill 净失分的缺陷逐条做成 SKILL.md 的反例清单（当前 __NLOSERS__）`,
]],
['rec-l','长期',[
  `SKILL.md 的定位应显式收敛为「结构与完整性保障」，而不是「更准的代码评审」—— 两轮数据都支持这个定位`,
  `为每个程序类型维护缺陷清单，随 fixture 演进而非一次性预埋，避免 fixture 与断言同时腐化`,
  `判分层需要难度阶梯：当前 __NSAT__/__NDEF__ 个缺陷双组满分，基准已无区分度，必须加入更隐蔽的缺陷才能继续度量`,
]]].map(([c,t,its])=>`<div class="rec-i ${c}"><div class="rl">${t}</div><ul>${
 its.map(i=>`<li>${esc(i)}</li>`).join('')}</ul></div>`).join('');

$('#foot').textContent=`格式 ${pct(F.with)} vs ${pct(F.without)} (p=${sci(F.p)}) · 技术 ${pct(J.with)} vs ${pct(J.without)} (p=${sci(J.sign.exact_two_sided_p)}) · grader ${D.meta.grader}`;
window.addEventListener('resize',()=>{if(typeof echarts==='undefined')return;
 ['c-layers','c-defect','c-runs','c-assert'].forEach(id=>{
  const i=echarts.getInstanceByDom(document.getElementById(id)); if(i)i.resize();});});
</script>
</body>
</html>"""

NDEF = len(G["per_defect"])
NASRT = len(payload["assertions"])

# assertion mix, derived rather than hardcoded ("11 结构 + 1 覆盖 + 7 关键词")
_kinds = {}
for a in payload["assertions"]:
    _kinds[a["kind"]] = _kinds.get(a["kind"], 0) + 1
KINDDESC = " + ".join(f"{v} {k}" for k, v in _kinds.items())

# planted defects per fixture — the caveats text quotes this range
_per = sorted(len([1 for v in G["per_defect"].values() if v["eval"] == e])
              for e in EVAL_NAMES)
DEFMIN, DEFMAX = _per[0], _per[-1]

# one-word program-type summary from the eval names themselves
_KW = [("OO", "类"), ("CL_SALV", "SALV"), ("CDS", "CDS+HTTP"), ("BAPI", "BAPI+RFC"),
       ("FUNCTION", "函数组"), ("DIALOG", "对话框"), ("BATCH", "批处理"),
       ("CLASS-EVENTS", "发布订阅"), ("INHERITANCE", "继承多态"), ("ALV", "ALV"),
       ("MODERN", "现代语法"), ("REPORT", "报表"), ("PROCEDURAL", "过程式报表")]
_seen, EVALKIND = set(), []
for e in sorted(EVAL_NAMES):
    u = EVAL_NAMES[e].upper()
    for k, lab in _KW:
        if k in u and lab not in _seen:
            _seen.add(lab)
            EVALKIND.append(lab)
            break

# narrative counters, all read off the data
_d = G["per_defect"].values()
_SAT = sum(1 for v in _d if v["with_skill"]["score"] >= 0.99
           and v["without_skill"]["score"] >= 0.99)
_LOSERS = sum(1 for v in _d
              if v["with_skill"]["score"] < v["without_skill"]["score"])
_BADJSON = B["metadata"].get("judge_hygiene", {}).get("needing_json_repair", 0)
_NREPORTS = len(G["per_run"])
_NCELLS = (PS.get("concordant_pass", 0) + PS.get("with_only_pass", 0)
           + PS.get("without_only_pass", 0)) or (
    B["paired_format"]["concordant_pass"] + B["paired_format"]["with_only_pass"]
    + B["paired_format"]["without_only_pass"])

js = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
out = (HTML.replace("__PAYLOAD__", js)
       .replace("__GRADER__", payload["meta"]["grader"])
       .replace("__NEVALS__", str(payload["meta"]["nEvals"]))
       .replace("__RUNS__", str(payload["meta"]["runs"]))
       .replace("__NDEF__", str(NDEF))
       .replace("__NASRT__", str(NASRT))
       .replace("__NREPORTS__", str(_NREPORTS))
       .replace("__NCELLS__", str(_NCELLS))
       .replace("__NBADJSON__", str(_BADJSON))
       .replace("__NLOSERS__", str(_LOSERS))
       .replace("__NSAT__", str(_SAT))
       .replace("__KINDDESC__", KINDDESC)
       .replace("__DEFMIN__", str(DEFMIN))
       .replace("__DEFMAX__", str(DEFMAX))
       .replace("__EVALKIND__", " / ".join(EVALKIND)))
for tok in ("__NDEF__", "__NASRT__", "__KINDDESC__", "__DEFMIN__", "__DEFMAX__",
            "__NREPORTS__", "__NCELLS__", "__NBADJSON__", "__NLOSERS__", "__NSAT__",
            "__EVALKIND__", "__PAYLOAD__", "__NEVALS__", "__RUNS__", "__GRADER__"):
    assert tok not in out, f"unsubstituted placeholder {tok}"
p = os.path.join(WS, "benchmark.html")
open(p, "w", encoding="utf-8").write(out)
print(f"Wrote {p} ({os.path.getsize(p)} bytes)")