// Capture console screenshots for the docs (Chrome DevTools Protocol over Node's built-in WebSocket; no packages).
//
//   python3 docs/screenshots/serve_demo.py &        # demo data on :8790 (needs the local decider for the Test tab)
//   node docs/screenshots/capture.mjs [--url http://127.0.0.1:8790] [--chrome PATH]
//
// Writes docs/images/console-<shot>-<lang>.png for lang in en, ko.
import { spawn } from 'node:child_process';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const arg = (k, d) => { const i = process.argv.indexOf(k); return i > 0 ? process.argv[i + 1] : d; };
const BASE = arg('--url', 'http://127.0.0.1:8790');
const CHROME = arg('--chrome', process.platform === 'darwin'
  ? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' : 'google-chrome');
const OUT = join(dirname(fileURLToPath(import.meta.url)), '..', 'images');
const PORT = 9333;
const sleep = ms => new Promise(r => setTimeout(r, ms));

// Each shot: tab to open, optional actions run in the page, and the cards to crop to (union of their .card boxes).
const SHOTS = [
  { name: 'overview', tab: 'overview', wait: 2500, crop: ['#t-overview'] },
  { name: 'policy-sensitivity', tab: 'policy', crop: ['#sens', '#patterns'] },
  { name: 'policy-types', tab: 'policy', crop: ['#cats'] },
  { name: 'policy-rules', tab: 'policy', crop: ['#rules'] },
  { name: 'policy-evidence', tab: 'policy', crop: ['#message', '#evidence'] },
  { name: 'test', tab: 'test', wait: 4000, crop: ['#t-test'],
    act: `document.querySelector('#samples [data-s="1"]').click(); document.querySelector('#run-test').click();` },
  { name: 'logs', tab: 'logs', wait: 2500, crop: ['#logs'], until: 'tr.detail',
    act: `const row = [...document.querySelectorAll('#logs tr.clickable')].slice(0, 12).reverse().find(r => r.textContent.includes('📄'))
            || [...document.querySelectorAll('#logs tr.clickable')].find(r => r.textContent.includes('📄'));
          row.click(); await new Promise(r => setTimeout(r, 300)); row.nextElementSibling.querySelector('[data-evidence]').click();` },
  { name: 'activity', tab: 'logs', wait: 2500, crop: ['#activity'] },
  { name: 'users', tab: 'users', wait: 1500, crop: ['#t-users'] },
  { name: 'alerts', tab: 'alerts', wait: 1500, crop: ['#t-alerts'] },
  { name: 'history', tab: 'history', wait: 1500, crop: ['#t-history'],
    act: `document.querySelector('[data-compare]').click();` },
];

const chrome = spawn(CHROME, ['--headless=new', `--remote-debugging-port=${PORT}`, '--hide-scrollbars', '--disable-gpu',
  `--user-data-dir=${mkdtempSync(join(tmpdir(), 'cdp-'))}`, 'about:blank'], { stdio: 'ignore' });
let target;
for (let i = 0; i < 50 && !target; i++) {
  await sleep(200);
  target = await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: 'PUT' }).then(r => r.json()).catch(() => null);
}
if (!target) throw new Error('Chrome did not start');

const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise(r => ws.addEventListener('open', r, { once: true }));
let seq = 0;
const pending = new Map();
ws.addEventListener('message', e => { const m = JSON.parse(e.data); pending.get(m.id)?.(m); pending.delete(m.id); });
const cdp = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++seq;
  pending.set(id, m => (m.error ? reject(new Error(`${method}: ${m.error.message}`)) : resolve(m.result)));
  ws.send(JSON.stringify({ id, method, params }));
});
const run = async expr => {
  const r = await cdp('Runtime.evaluate', { expression: `(async () => { ${expr} })()`, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || 'page error');
  return r.result.value;
};

await cdp('Emulation.setDeviceMetricsOverride', { width: 1280, height: 1000, deviceScaleFactor: 1.5, mobile: false });
for (const lang of ['en', 'ko']) {
  for (const s of SHOTS) {
    await cdp('Page.navigate', { url: `${BASE}/?lang=${lang}&shot=${s.name}#${s.tab}` });   // new query = full reload
    await sleep(s.wait || 1200);
    if (s.act) { await run(s.act); await sleep(s.wait || 1200); }
    const box = await run(`
      const els = ${JSON.stringify(s.crop)}.map(q => document.querySelector(q)).filter(Boolean)
        .map(el => el.closest('.card') && !el.matches('section') ? el.closest('.card') : el);
      const rs = els.map(el => el.getBoundingClientRect());
      const x = Math.min(...rs.map(r => r.left)), y = Math.min(...rs.map(r => r.top)) + scrollY;
      const stop = ${JSON.stringify(s.until || null)} && document.querySelector(${JSON.stringify(s.until || 'x')});
      const bottom = stop ? stop.getBoundingClientRect().bottom : Math.max(...rs.map(r => r.bottom));   // 'until': crop below a row
      return { x: x - 12, y: y - 12, width: Math.max(...rs.map(r => r.right)) - x + 24, height: bottom + scrollY - y + 24 };`);
    const shot = await cdp('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true, clip: { ...box, scale: 1 } });
    const file = join(OUT, `console-${s.name}-${lang}.png`);
    writeFileSync(file, Buffer.from(shot.data, 'base64'));
    console.log(file.replace(process.cwd() + '/', ''), `${Math.round(box.width)}x${Math.round(box.height)}`);
  }
}
ws.close();
chrome.kill();
