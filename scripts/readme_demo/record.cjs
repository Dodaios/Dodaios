// Records the README demo: one continuous take of the real app, driven through
// its own interface, captured with the Chrome DevTools screencast.
//
//   node scripts/readme_demo/record.cjs <output folder>
//
// It expects a first-run Dodaios instance (nothing set up yet) at DEMO_URL and
// the sample project from sample-project.sh in that instance's home folder.
// assets/demo/readme/README.md has the whole procedure.
//
// The window is 1280 x 720 at a device scale of 1.5, so the frames are
// 1920 x 1080 and the interface stays readable when the video is shown small.
// The pointer is drawn into the page because a headless browser has none.
// The folder gets the frames and list.txt, an ffmpeg concat list that keeps
// every frame on screen for as long as it was during the take.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const OUT = process.argv[2];
const URL = process.env.DEMO_URL || 'http://127.0.0.1:47990/';
if (!OUT) { console.error('usage: node record.cjs <output folder>'); process.exit(2); }
const W = 1280, H = 720;

const CURSOR = `(() => {
  const install = () => {
    if (document.getElementById('__demo_cursor')) return;
    const c = document.createElement('div');
    c.id = '__demo_cursor';
    c.innerHTML = '<svg width="20" height="20" viewBox="0 0 26 26"><path d="M4 2 L4 20.5 L8.6 16.4 L11.9 23.6 L15 22.2 L11.8 15.2 L18 15.2 Z" fill="#fff" stroke="#000" stroke-width="1.5" stroke-linejoin="round"/></svg>';
    Object.assign(c.style, { position: 'fixed', left: '0', top: '0', zIndex: '2147483647', pointerEvents: 'none', transform: 'translate(-200px,-200px)' });
    document.documentElement.appendChild(c);
    const svg = c.firstChild; svg.style.transition = 'transform 90ms'; svg.style.transformOrigin = '3px 2px';
    addEventListener('mousemove', (e) => { c.style.transform = 'translate(' + (e.clientX - 3) + 'px,' + (e.clientY - 1.5) + 'px)'; }, true);
    addEventListener('mousedown', () => { svg.style.transform = 'scale(0.82)'; }, true);
    addEventListener('mouseup', () => { svg.style.transform = ''; }, true);
  };
  if (document.documentElement) install();
  document.addEventListener('DOMContentLoaded', install);
})();`;

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({ args: ['--force-device-scale-factor=1.5', `--window-size=${W},${H}`, '--force-color-profile=srgb'] });
  const ctx = await browser.newContext({ viewport: null, colorScheme: 'dark', timezoneId: 'Europe/Berlin', locale: 'en-US' });
  await ctx.addInitScript(CURSOR);
  const page = await ctx.newPage();
  page.setDefaultTimeout(15000);
  const log = (...a) => console.log(new Date().toISOString().slice(17, 23), ...a);

  // ---- pointer helpers -------------------------------------------------
  let cx = W / 2, cy = H * 0.66;
  const sleep = (ms) => page.waitForTimeout(ms);
  const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
  // Time-based, so a move lasts as long as asked whatever one step costs.
  async function moveTo(x, y, ms) {
    const dist = Math.hypot(x - cx, y - cy);
    const dur = ms ?? Math.min(780, Math.max(230, dist * 0.95));
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
  const press = async () => { await page.mouse.down(); await sleep(70); await page.mouse.up(); };
  // Wheel the element into the window the way a person would, then return its box.
  async function reveal(el) {
    for (let i = 0; i < 60; i++) {
      const b = await el.boundingBox();
      if (!b) { await sleep(100); continue; }
      const mid = b.y + b.height / 2;
      if (mid >= 8 && mid <= H - 26) return b;
      const px = Math.min(W - 60, Math.max(60, b.x + b.width / 2));
      if (Math.abs(cx - px) > 6 || Math.abs(cy - H * 0.55) > 160) await moveTo(px, H * 0.55, 380);
      await page.mouse.wheel(0, mid > H - 26 ? 52 : -52);
      await sleep(42);
    }
    return el.boundingBox();
  }
  async function point(loc, { dx = 0, dy = 0, ms } = {}) {
    const el = typeof loc === 'string' ? page.locator(loc).first() : loc;
    await el.waitFor({ state: 'visible' });
    const b = await reveal(el);
    await moveTo(b.x + b.width / 2 + dx, b.y + b.height / 2 + dy, ms);
    return el;
  }
  async function click(loc, opts = {}) {
    await point(loc, opts);
    await sleep(opts.pre ?? 130);
    await press();
    await sleep(opts.post ?? 350);
  }
  const type = async (text, delay = 70) => { await page.keyboard.type(text, { delay }); };
  const btn = (name) => page.getByRole('button', { name });

  // ---- screencast ------------------------------------------------------
  const client = await ctx.newCDPSession(page);
  const frames = []; let idx = 0; let recording = false;
  client.on('Page.screencastFrame', (f) => {
    client.send('Page.screencastFrameAck', { sessionId: f.sessionId }).catch(() => {});
    if (!recording) return;
    const name = String(idx++).padStart(6, '0') + '.jpg';
    fs.writeFileSync(path.join(OUT, name), Buffer.from(f.data, 'base64'));
    frames.push({ name, ts: f.metadata.timestamp });
  });
  const finish = async () => {
    recording = false;
    await client.send('Page.stopScreencast').catch(() => {});
    const lines = ['ffconcat version 1.0'];
    frames.forEach((frame, i) => {
      const next = frames[i + 1];
      lines.push(`file '${frame.name}'`, `duration ${(next ? Math.max(next.ts - frame.ts, 0.001) : 1.2).toFixed(4)}`);
    });
    if (frames.length) lines.push(`file '${frames[frames.length - 1].name}'`);
    fs.writeFileSync(path.join(OUT, 'list.txt'), lines.join('\n') + '\n');
  };

  await page.goto(URL, { waitUntil: 'domcontentloaded' });
  const dlg = page.locator('[role=dialog]').first();
  await dlg.locator('input').first().waitFor({ state: 'visible', timeout: 30000 });
  await sleep(2500);
  await page.mouse.move(cx, cy);
  await client.send('Page.startScreencast', { format: 'jpeg', quality: 93, maxWidth: 1920, maxHeight: 1080, everyNthFrame: 1 });
  recording = true;
  const t0 = Date.now();
  const mark = (name) => log(`[${((Date.now() - t0) / 1000).toFixed(1)}s]`, name);

  try {
    // ---- 1. first run: name, connect, voice -----------------------------
    mark('onboarding');
    await moveTo(cx + 6, cy + 4, 200);            // wake the first frame
    await sleep(800);
    await click(dlg.locator('input').first(), { post: 250 });
    await type('Dodaios', 90);
    await sleep(400);
    await click(btn(/Continue/), { post: 600 });
    await page.getByText('Connect your AI').waitFor();
    mark('connect');
    await point(page.getByText('Claude Pro').first(), { dx: -60, ms: 550 });
    await sleep(350);
    await point(page.getByText('Use a free local model').first(), { ms: 850 });
    await sleep(600);
    await click(btn(/Skip for now/), { post: 600 });
    await page.getByText(/How you'll talk to/).waitFor();
    mark('voice');
    await point(page.getByText(/Wake word: Hey/).first(), { ms: 550 });
    await sleep(1100);
    await click(btn(/Show me around/), { post: 600 });

    // ---- 2. the app's own guided walk -------------------------------------
    mark('walk');
    const next = btn(/^Next$/);
    // The bubble types its text; wait until it stops growing, then leave time to read.
    const bubbleLength = () => next.evaluate((n) => { let e = n; while (e.parentElement && (e.innerText || '').length < 60) e = e.parentElement; return (e.innerText || '').length; });
    async function bubbleSettled() {
      let last = -1, same = 0;
      for (let i = 0; i < 60 && same < 3; i++) { const len = await bubbleLength().catch(() => -1); same = len === last ? same + 1 : 0; last = len; await sleep(140); }
    }
    for (let stop = 0; stop < 2; stop++) {
      await next.waitFor({ state: 'visible' });
      await sleep(500);
      await bubbleSettled();
      await sleep(900);
      mark('walk stop ' + stop);
      if (stop < 1) await click(next, { post: 300 });
    }
    await click(btn(/^Skip$/), { post: 500 });

    // ---- 3. plugins -------------------------------------------------------
    mark('plugins');
    await click('[aria-label="Plugins"]', { post: 900 });
    await page.getByText('Connect your tools so your agents can work across them').waitFor();
    await moveTo(700, 400, 450);
    for (let i = 0; i < 15; i++) { await page.mouse.wheel(0, 40); await sleep(34); }
    await sleep(950);

    // ---- 4. agentic IDE: connect a project, run its tests -----------------
    mark('ide');
    await click('[aria-label="Agentic IDE"]', { post: 900 });
    await click(btn(/Connect folder/).first(), { post: 500 });
    await click(btn(/Choose folder/), { post: 650 });
    const picker = page.locator('[role=dialog]').last();
    await click(picker.getByText('Home', { exact: true }).first(), { post: 450 });
    await click(picker.getByText('projects', { exact: true }).first(), { post: 450 });
    await click(picker.getByText('trailhead', { exact: true }).first(), { post: 450 });
    await click(btn(/Use this folder/), { post: 450 });
    await click(btn(/^Connect project$/), { post: 1300 });
    mark('terminal');
    await click('[aria-label="Show terminal"]', { post: 1400 });
    await click('[aria-label="Terminal input"]', { post: 250 });
    await type('python -m pytest -q', 55);
    await sleep(250);
    await page.keyboard.press('Enter');
    await sleep(1700);

    // ---- 5. memory --------------------------------------------------------
    mark('memory');
    await click('[aria-label="Profile"]', { post: 900 });
    await click(page.getByRole('button', { name: /^Memory/ }).first(), { post: 1200 });
    await click(btn(/^New$/).first(), { post: 600 });
    await type('I prefer short answers.', 45);
    await sleep(300);
    await click(page.getByText('Preferences', { exact: true }).first(), { post: 300 });
    await click(page.getByText('Remember', { exact: true }).first(), { post: 200 });
    await page.getByText('New memory').waitFor({ state: 'hidden' });
    await page.getByText('I prefer short answers.').first().waitFor({ state: 'visible', timeout: 30000 });
    mark('memory saved');
    await moveTo(cx - 150, cy + 40, 500);
    await sleep(1400);

    // ---- 6. pets ----------------------------------------------------------
    mark('pets');
    await click('[aria-label="Go back"]', { post: 900 });
    await click(page.getByPlaceholder(/Search settings/), { post: 200 });
    await type('pets', 75);
    await sleep(450);
    await click(page.getByRole('button', { name: /My Pets/ }).first(), { post: 1200 });
    await click(page.getByText('Ember', { exact: true }).first(), { dy: -60, post: 700 });
    for (let i = 0; i < 30; i++) { await page.mouse.wheel(0, -52); await sleep(30); }
    await sleep(1500);

    // ---- 7. sections side by side -----------------------------------------
    mark('layout');
    await click('[aria-label="Agentic IDE"]', { post: 1200 });
    const menuOpen = () => page.getByText('Arrange sections').isVisible().catch(() => false);
    await point('[aria-label="Layout"]');
    await sleep(350);
    if (!(await menuOpen())) await press();
    await page.getByText('Arrange sections').waitFor();
    await sleep(450);
    await click('[aria-label="Two side by side"]', { post: 1000 });
    await point('[aria-label="Layout"]');
    await sleep(200);
    if (await menuOpen()) await press();
    await sleep(500);
    // highlight the right tile
    const title = page.locator('[data-testid="tile-section-button"]').nth(1);
    const tb = await title.boundingBox();
    await moveTo(tb.x + tb.width + 170, tb.y + tb.height / 2, 600);
    await press();
    await sleep(600);
    await moveTo(W * 0.73, H * 0.62, 700);

    mark('end');
    await sleep(1900);
    await finish();
    log('frames', frames.length, 'seconds', (frames[frames.length - 1].ts - frames[0].ts).toFixed(1));
  } catch (e) {
    await finish().catch(() => {});
    await page.screenshot({ path: path.join(OUT, 'failure.png') }).catch(() => {});
    console.error('FAILED:', e.message.split('\n').slice(0, 6).join('\n'));
    process.exitCode = 1;
  }
  await browser.close();
})();
