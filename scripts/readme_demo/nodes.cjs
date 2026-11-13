// Records the README's Nodes clip from a demo instance.
//
//   node scripts/readme_demo/nodes.cjs <output folder>
//
// The instance is the one demo-instance.sh starts, with the seven nodes of
// seed_nodes.py in it (assets/demo/readme/README.md, "The Nodes clip", has the
// order of the steps). The script marks the first-run steps done through the
// app's own API, opens the Nodes section and films it: the top of the section,
// a pass over the type cards, the Analytics card narrowing the list, the
// dashboard opened and scrolled, the slide deck two slides on, and back.
// It writes the WebM of the window and cut.json: the second the film starts
// and ends in it, for ffmpeg.
//
// The window is 1440 x 900: at 1280 the type card "Whiteboard" is cut short.
const { chromium } = require('playwright');
const fs = require('fs');

const OUT = process.argv[2];
const URL = (process.env.DEMO_URL || 'http://127.0.0.1:47990/').replace(/\/?$/, '/');
if (!OUT) { console.error('usage: node nodes.cjs <output folder>'); process.exit(2); }
fs.mkdirSync(OUT, { recursive: true });

// The same pointer as record.cjs: drawn in the window's own document; a node
// is a page in a frame, which gets the mouse events itself and passes them on.
const POINTER = `(() => {
  if (window.top !== window) {
    for (const kind of ['mousemove', 'mousedown', 'mouseup']) {
      addEventListener(kind, (e) => { parent.postMessage({ __demo: kind, x: e.clientX, y: e.clientY }, '*'); }, true);
    }
    return;
  }
  let place = () => {}, squeeze = () => {};
  const install = () => {
    if (document.getElementById('__demo_cursor')) return;
    const c = document.createElement('div');
    c.id = '__demo_cursor';
    c.innerHTML = '<svg width="22" height="22" viewBox="0 0 26 26"><path d="M4 2 L4 20.5 L8.6 16.4 L11.9 23.6 L15 22.2 L11.8 15.2 L18 15.2 Z" fill="#fff" stroke="#000" stroke-width="1.5" stroke-linejoin="round"/></svg>';
    Object.assign(c.style, { position: 'fixed', left: '0', top: '0', zIndex: '2147483647', pointerEvents: 'none', transform: 'translate(-200px,-200px)' });
    document.documentElement.appendChild(c);
    const svg = c.firstChild; svg.style.transition = 'transform 90ms'; svg.style.transformOrigin = '3px 2px';
    place = (x, y) => { c.style.transform = 'translate(' + (x - 3) + 'px,' + (y - 1.5) + 'px)'; };
    squeeze = (down) => { svg.style.transform = down ? 'scale(0.82)' : ''; };
  };
  addEventListener('mousemove', (e) => place(e.clientX, e.clientY), true);
  addEventListener('mousedown', () => squeeze(true), true);
  addEventListener('mouseup', () => squeeze(false), true);
  addEventListener('message', (e) => {
    const m = e.data;
    if (!m || typeof m.__demo !== 'string') return;
    const frame = [...document.querySelectorAll('iframe')].find((f) => f.contentWindow === e.source);
    if (!frame) return;
    const r = frame.getBoundingClientRect();
    const k = frame.clientWidth ? r.width / frame.clientWidth : 1;
    if (m.__demo === 'mousemove') place(r.left + m.x * k, r.top + m.y * k);
    else squeeze(m.__demo === 'mousedown');
  });
  if (document.documentElement) install();
  document.addEventListener('DOMContentLoaded', install);
})();`;

// The first-run steps, marked done the way the app marks them. A state-changing
// call must come from the app's own origin.
async function skipFirstRun() {
  const origin = URL.replace(/\/$/, '');
  for (const [path, body] of [
    ['accept-terms', null],
    ['complete', null],
    ['tour-complete', null],
    ['first-conversation', { outcome: 'skipped' }],
  ]) {
    const res = await fetch(`${URL}api/onboarding/${path}`, {
      method: 'POST',
      headers: { Origin: origin, ...(body ? { 'Content-Type': 'application/json' } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) throw new Error(`onboarding/${path}: HTTP ${res.status}`);
  }
}

function helpers(page, size) {
  let cx = size.width / 2, cy = size.height / 2;
  const sleep = (ms) => page.waitForTimeout(ms);
  const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
  async function moveTo(x, y, ms) {
    const dur = ms ?? Math.min(760, Math.max(240, Math.hypot(x - cx, y - cy) * 0.95));
    const sx = cx, sy = cy, start = Date.now();
    for (;;) {
      const t = Math.min(1, (Date.now() - start) / dur);
      const k = ease(t);
      await page.mouse.move(sx + (x - sx) * k, sy + (y - sy) * k);
      if (t >= 1) break;
      await sleep(8);
    }
    cx = x; cy = y;
  }
  async function point(loc, ms) {
    const el = typeof loc === 'string' ? page.locator(loc).first() : loc;
    await el.waitFor({ state: 'visible' });
    const b = await el.boundingBox();
    await moveTo(b.x + b.width / 2, b.y + b.height / 2, ms);
    return el;
  }
  async function click(loc, ms) {
    await point(loc, ms);
    await sleep(140);
    await page.mouse.down(); await sleep(70); await page.mouse.up();
    await sleep(350);
  }
  async function wheel(total, step = 30, pause = 18) {
    for (let done = 0; Math.abs(done) < Math.abs(total); done += Math.sign(total) * step) {
      await page.mouse.wheel(0, Math.sign(total) * step);
      await sleep(pause);
    }
  }
  return { sleep, moveTo, point, click, wheel };
}

(async () => {
  await skipFirstRun();
  const size = { width: Number(process.env.DEMO_W || 1440), height: Number(process.env.DEMO_H || 900) };
  const browser = await chromium.launch({ args: ['--force-color-profile=srgb'] });
  const ctx = await browser.newContext({
    viewport: size, deviceScaleFactor: 1, colorScheme: 'dark', timezoneId: 'Europe/Berlin', locale: 'en-US',
    recordVideo: { dir: `${OUT}/video`, size },
  });
  const born = Date.now();
  await ctx.addInitScript(POINTER);
  const page = await ctx.newPage();
  page.setDefaultTimeout(20000);
  const h = helpers(page, size);
  const card = (title) => page.locator('[data-testid="node-card"]', { hasText: title }).first();
  const back = () => page.locator('[data-testid="visualization-back"]:visible').first();
  const tile = (type) => page.locator(`[data-testid="nodes-type-${type}"]`).first();

  await page.goto(URL + '?view=visualization', { waitUntil: 'domcontentloaded' });
  await card('Shop sales, October').waitFor({ state: 'visible', timeout: 30000 });
  await h.sleep(2500);
  await page.mouse.move(size.width / 2, size.height / 2);
  const start = Date.now();

  // 1. The top of the section.
  await h.moveTo(size.width * 0.45, 170, 500);
  await h.sleep(1000);
  // 2. Along the type cards.
  for (const type of ['docs', 'slides', 'sheets', 'design', 'data', 'whiteboard', 'motion']) {
    await h.point(tile(type), 260); await h.sleep(170);
  }
  await h.sleep(250);
  // 3. Analytics narrows the list to the dashboard, which opens.
  await h.click(tile('data'), 450);
  await h.sleep(1100);
  await h.point(card('Shop sales, October'), 600);
  await h.sleep(500);
  await h.click(card('Shop sales, October'), 200);
  await h.sleep(2600);
  await h.moveTo(size.width * 0.55, size.height * 0.58, 600);
  await h.wheel(420);
  await h.sleep(1600);
  await h.wheel(-420);
  await h.sleep(700);
  await h.click(back(), 600);
  await h.sleep(900);
  // 4. Analytics again shows every node; the deck opens, two slides on.
  await h.click(tile('data'), 450);
  await h.sleep(1100);
  await h.point(card('Q3 board update'), 600);
  await h.sleep(450);
  await h.click(card('Q3 board update'), 200);
  await h.sleep(2200);
  const frame = page.locator('[data-testid="visualization-frame"]:visible').first();
  const b = await frame.boundingBox();
  await h.moveTo(b.x + b.width * 0.62, b.y + b.height * 0.55, 500);
  await h.click(frame, 300);
  for (let i = 0; i < 2; i++) { await page.keyboard.press('ArrowRight'); await h.sleep(1700); }
  await h.sleep(400);
  await h.click(back(), 600);
  await h.sleep(1500);

  const stop = Date.now();
  await ctx.close();
  const video = fs.readdirSync(`${OUT}/video`).find((f) => f.endsWith('.webm'));
  fs.writeFileSync(`${OUT}/cut.json`, JSON.stringify({ file: `video/${video}`, from: (start - born) / 1000, to: (stop - born) / 1000 }, null, 2));
  console.log('clip', video, ((stop - start) / 1000).toFixed(1), 's');
  await browser.close();
})().catch((e) => { console.error('FAILED', e.message.split('\n').slice(0, 5).join('\n')); process.exit(1); });
