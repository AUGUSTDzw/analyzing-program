// Smoke-test review.html: run its inline markdown-render loop against stub
// marked/DOMPurify, and verify all four reports were embedded intact.
const fs = require('fs');
const htmlPath = process.argv[2];
const t = fs.readFileSync(htmlPath, 'utf8');

// ---- extract the render loop -------------------------------------------
const scripts = [...t.matchAll(/<script>([\s\S]*?)<\/script>/g)];
if (!scripts.length) throw new Error('no inline <script> found');
const code = scripts[scripts.length - 1][1];

// ---- pull the raw markdown out of each .md panel -----------------------
const panels = [...t.matchAll(/<div class="md">([\s\S]*?)<\/div>\s*<\/div>/g)];
const decode = (s) => s.replace(/&lt;/g, '<').replace(/&gt;/g, '>')
  .replace(/&quot;/g, '"').replace(/&#x27;/g, "'").replace(/&#39;/g, "'")
  .replace(/&amp;/g, '&');

// ---- stub marked + DOMPurify ------------------------------------------
let renderCalls = 0;
global.marked = {
  parse: (md) => { renderCalls++; return `<rendered>${md.length}</rendered>`; },
};
global.DOMPurify = { sanitize: (h) => h };

let queried = 0;
const panelsStub = [];
global.document = {
  querySelectorAll: (sel) => {
    if (sel !== '.md') throw new Error('unexpected selector ' + sel);
    queried++;
    return panelsStub;
  },
};

panelsStub.push(...panels.map((m) => ({
  textContent: decode(m[1]),
  set innerHTML(v) { this._html = v; },
  get innerHTML() { return this._html; },
  querySelectorAll: () => [],
})));

new Function(code)();

let bad = 0;
const ok = (c, m) => { if (!c) bad++; console.log(`  ${c ? 'OK  ' : 'FAIL'}  ${m}`); };

ok(panels.length === 4, `4 report panels embedded (${panels.length})`);
ok(queried === 1, `querySelectorAll('.md') called once (${queried})`);
ok(renderCalls === 4, `marked.parse invoked 4× (${renderCalls})`);

panelsStub.forEach((p, i) => {
  ok(typeof p.innerHTML === 'string' && p.innerHTML.startsWith('<rendered>'),
     `panel ${i + 1} rendered, markdown ${p.textContent.length} chars`);
});

const scores = [...t.matchAll(/<span class="score ([pf]?)">([^<]+)<\/span>/g)].map(m => m[2]);
ok(scores.length === 4, `4 score badges present (${scores.length}): ${scores.join(' | ')}`);

const withScores = scores.filter(s => s.includes('12/12') || s.includes('11/11'));
ok(withScores.length === 2, `both with_skill runs at full score (${withScores.length}/2)`);

const failRows = (t.match(/未通过断言 \((\d+)\)/) || [])[1];
ok(failRows !== undefined, `failed-assertion summary present (${failRows} rows)`);

console.log('\n' + (bad ? `${bad} FAILURE(S)` : 'SMOKE TEST PASSED'));
process.exit(bad ? 1 : 0);