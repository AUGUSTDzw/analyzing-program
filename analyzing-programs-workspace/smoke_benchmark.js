// Smoke-test benchmark.html: run its inline script against a stub DOM + stub
// ECharts, then assert every generated region actually got populated.
const fs = require('fs');
const path = process.argv[2];
const html = fs.readFileSync(path, 'utf8');

// ---- extract payload + the main inline script -------------------------
const payloadMatch = html.match(
  /<script id="payload" type="application\/json">([\s\S]*?)<\/script>/);
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
if (!payloadMatch) throw new Error('payload script tag not found');
if (!scripts.length) throw new Error('no inline <script> found');
const code = scripts[scripts.length - 1][1];

// ---- stub DOM ---------------------------------------------------------
const written = {};
const nodes = {};
function node(rawId) {
  // getElementById('x') and querySelector('#x') must hit the SAME stub node.
  const id = String(rawId).replace(/^#/, '');
  if (!nodes[id]) {
    nodes[id] = {
      id,
      _html: '',
      get textContent() { return payloadMatch[1].replace(/<\\\//g, '</'); },
      set innerHTML(v) { this._html = String(v); written[id] = String(v); },
      get innerHTML() { return this._html; },
      // #foot-r is populated via textContent, not innerHTML.
      set textContent(v) { this._html = String(v); written[id] = String(v); },
      querySelectorAll: () => [],
      addEventListener: () => {},
    };
  }
  return nodes[id];
}
global.document = {
  getElementById: node,
  querySelector: node,
  addEventListener: () => {},
};
global.window = { addEventListener: () => {} };

// ---- stub ECharts: record every option object handed to setOption -------
const charts = {};
global.echarts = {
  init: (el) => ({
    setOption: (o) => { charts[el.id] = o; return this; },
    resize: () => {},
  }),
  getInstanceByDom: () => null,
  // Real ECharts exposes the gradient factory as echarts.graphic.LinearGradient,
  // and it IS a constructor (used with `new`).
  graphic: { LinearGradient: function () { return { __gradient: true }; } },
};

// ---- run ---------------------------------------------------------------
new Function(code)();

// ---- assert ------------------------------------------------------------
const regions = ['kpis', 't-scores', 't-matrix', 't-flips', 't-notes', 't-size',
                 'analysis', 'findings', 'caveats', 'recs', 'foot-r'];
let bad = 0;
for (const r of regions) {
  const v = written[r];
  const ok = typeof v === 'string' && v.trim().length > 0;
  if (!ok) bad++;
  console.log(`  ${ok ? 'OK  ' : 'FAIL'}  #${r.padEnd(10)} ${String(v ? v.length : 0).padStart(6)} chars`);
}

console.log('\n  charts initialised: ' + Object.keys(charts).sort().join(', '));
for (const [id, opt] of Object.entries(charts)) {
  const s = Array.isArray(opt.series) ? opt.series : (opt.series ? [opt.series] : []);
  const summary = s.map(x => `${x.name || x.type}:${(x.data || []).length}pt`).join(' ');
  console.log(`    ${id.padEnd(10)} ${String(s.length).padStart(2)} series  ${summary}`);
  if (!s.length) { bad++; console.log(`    FAIL ${id} has no series`); }
}

const anyNaN = Object.values(written).some(v => /NaN|undefined%|\[object Object\]/.test(v));
if (anyNaN) { bad++; console.log('  FAIL  NaN / undefined / [object Object] found in output'); }
else console.log('  OK    no NaN / undefined / [object Object] in rendered output');

console.log('\n' + (bad ? `${bad} FAILURE(S)` : 'SMOKE TEST PASSED'));
process.exit(bad ? 1 : 0);