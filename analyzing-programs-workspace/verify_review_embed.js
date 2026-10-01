// Verify review.html embeds each report.md byte-for-byte (head + tail present,
// no truncation, no extra content).
const fs = require('fs'), path = require('path');
const htmlPath = process.argv[2], WS = process.argv[3];
const ROUND = process.argv[4] || 'latest';
const t = fs.readFileSync(htmlPath, 'utf8');
const panels = [...t.matchAll(/<div class="md">([\s\S]*?)<\/div>\s*<\/div>/g)];
const dec = (s) => s.replace(/&lt;/g, '<').replace(/&gt;/g, '>')
  .replace(/&quot;/g, '"').replace(/&#x27;/g, "'").replace(/&#39;/g, "'")
  .replace(/&amp;/g, '&');

const runs = [
  ['eval-1-alv-editable-total-poc', 'with_skill'],
  ['eval-1-alv-editable-total-poc', 'without_skill'],
  ['eval-2-procedural-vendor-report', 'with_skill'],
  ['eval-2-procedural-vendor-report', 'without_skill'],
];

let bad = 0;
runs.forEach(([d, c], i) => {
  const src = fs.readFileSync(path.join(WS, ROUND, d, c, 'outputs', 'report.md'), 'utf8')
    .replace(/\r\n/g, '\n');
  const emb = dec(panels[i][1]).replace(/\r\n/g, '\n');
  const head = src.slice(0, 150), tail = src.slice(-150);
  const headOk = emb.includes(head), tailOk = emb.includes(tail);
  // every non-trivial source line must appear somewhere in the embedded blob
  const lines = src.split('\n').filter((l) => l.trim().length > 20);
  const missing = lines.filter((l) => !emb.includes(l));
  const okAll = headOk && tailOk && missing.length === 0;
  if (!okAll) bad++;
  console.log(`  ${okAll ? 'OK  ' : 'FAIL'}  ${c.padEnd(14)} embedded=${String(emb.length).padStart(6)}` +
    `  source=${String(src.length).padStart(6)}  head=${headOk} tail=${tailOk}` +
    `  lines=${lines.length} missing=${missing.length}`);
  if (missing.length) console.log('        first missing: ' + JSON.stringify(missing[0].slice(0, 90)));
});
console.log('\n' + (bad ? `${bad} INTEGRITY FAILURE(S)` : 'EMBEDDED CONTENT INTACT'));
process.exit(bad ? 1 : 0);