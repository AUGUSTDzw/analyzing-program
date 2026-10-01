// Smoke-test iteration-7 benchmark.html: run its inline script against a stub
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

console.log('iteration-7 benchmark.html smoke test');
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

// per-defect table must have 24 rows
const dr = (written['t-defect'].match(/<tr>/g) || []).length;
ok(dr === 25, `t-defect has 24 data rows + header (got ${dr})`);

// assertions table: 19 assertions
const ar = (written['t-assert'].match(/<tr>/g) || []).length;
ok(ar === 20, `t-assert has 19 data rows + header (got ${ar})`);

console.log('-'.repeat(72));
console.log(bad ? `${bad} FAILURE(S)` : 'SMOKE TEST PASSED');
process.exit(bad ? 1 : 0);