// Smoke-test iteration-8 benchmark.html: run its inline script against a stub
// DOM + stub ECharts and assert every region populated and both verdict layers
// are rendered as SEPARATE blocks.
const fs = require('fs');
const html = fs.readFileSync(process.argv[2], 'utf8');

const pm = html.match(/<script id="payload" type="application\/json">([\s\S]*?)<\/script>/);
if (!pm) throw new Error('payload not found');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
if (!scripts.length) throw new Error('no inline script');

const written = {}, nodes = {};
function node(raw) {
  const id = String(raw).replace(/^#/, '');
  if (!nodes[id]) nodes[id] = {
    id, _html: '',
    get textContent() { return pm[1].replace(/<\\\//g, '</'); },
    set innerHTML(v) { this._html = String(v); written[id] = String(v); },
    get innerHTML() { return this._html; },
    set textContent(v) { this._html = String(v); written[id] = String(v); },
    querySelectorAll: () => [], addEventListener: () => {},
  };
  return nodes[id];
}
global.document = { getElementById: node, querySelector: node, addEventListener: () => {} };
global.window = { addEventListener: () => {} };
const charts = {};
global.echarts = {
  init: (el) => ({ setOption: (o) => { charts[el.id] = o; return this; }, resize: () => {} }),
  getInstanceByDom: () => null,
  graphic: { LinearGradient: function () { return {}; } },
};

new Function(scripts[scripts.length - 1][1])();

let bad = 0;
const ok = (c, m) => { if (!c) bad++; console.log(`  ${c ? 'OK  ' : 'FAIL'}  ${m}`); };

console.log('iteration-8 benchmark.html smoke test');
console.log('-'.repeat(72));
for (const r of ['verdicts', 'kpis', 't-cells', 't-defect', 't-assert',
                 'findings', 'caveats', 'recs', 'foot']) {
  const v = written[r];
  ok(typeof v === 'string' && v.trim().length > 0,
     `#${r.padEnd(11)} ${String(v ? v.length : 0).padStart(6)} chars`);
}

// the two verdict cards must BOTH exist and stay distinct
const vd = written.verdicts || '';
ok((vd.match(/class="vd /g) || []).length === 2, 'two separate verdict cards rendered');
ok(vd.includes('格式合规性') && vd.includes('预埋缺陷'), 'both layers labelled in verdicts');
ok(/配对检验 p = [0-9.e+-]+/.test(vd), 'both p-values present in verdicts');

// charts have series
for (const [id, opt] of Object.entries(charts)) {
  const s = Array.isArray(opt.series) ? opt.series : (opt.series ? [opt.series] : []);
  ok(s.length > 0, `${id.padEnd(11)} ${s.length} series`);
}

// data integrity: no NaN / undefined leakage
// chart containers legitimately stay empty: ECharts draws into a <canvas>,
// not innerHTML. Assert via the charts map instead (done above).
const regions = ['verdicts', 'kpis', 't-cells', 't-defect', 't-assert',
                 'findings', 'caveats', 'recs', 'foot'];
const nan = regions.filter(r => /NaN|undefined|\[object Object\]/.test(written[r] || ''));
ok(nan.length === 0, `no NaN/undefined in rendered regions${nan.length ? ' — ' + nan.join(',') : ''}`);

// Row counts come from the payload, never from a literal. The previous version
// hardcoded 24 defects / 19 assertions and silently rotted when the eval set
// grew from 5 to 13 — the smoke test passed against a stale expectation.
const P = JSON.parse(pm[1].replace(/<\\\//g, '</'));
const nDef = P.judge.perDefect.length, nAsrt = P.assertions.length;

const dr = (written['t-defect'].match(/<tr>/g) || []).length;
ok(dr === nDef + 1, `t-defect has ${nDef} data rows + header (got ${dr})`);

const ar = (written['t-assert'].match(/<tr>/g) || []).length;
ok(ar === nAsrt + 1, `t-assert has ${nAsrt} data rows + header (got ${ar})`);

// cell table must cover every (eval, config) pair
const cr = (written['t-cells'].match(/<tr>/g) || []).length;
ok(cr === P.format.cells.length + 1,
   `t-cells has ${P.format.cells.length} data rows + header (got ${cr})`);

// the sign test must cover one pair per (eval, run) — not one per report.
// Double-counting here previously forced with_higher == baseline_higher.
ok(P.judge.sign.n_paired === P.meta.nEvals * P.meta.runs,
   `sign test covers ${P.meta.nEvals} evals x ${P.meta.runs} runs = ${P.judge.sign.n_paired} pairs`);

// every planted defect in the payload must actually reach the DOM table,
// otherwise a silently dropped row would still satisfy a row-count check
const missing = P.judge.perDefect.filter(d => !written['t-defect'].includes(d.key));
ok(missing.length === 0,
   `all ${nDef} defect keys present in t-defect${missing.length ? ' — missing ' + missing.map(d => d.key).join(',') : ''}`);

console.log('-'.repeat(72));
console.log(bad ? `${bad} FAILURE(S)` : 'SMOKE TEST PASSED');
process.exit(bad ? 1 : 0);