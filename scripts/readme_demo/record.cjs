// Records the README demo: one continuous take of the real app, driven through
// its own interface, captured with the Chrome DevTools screencast.
//
//   node scripts/readme_demo/record.cjs <output folder>
//
// It expects a first-run Dodaios instance (nothing set up yet) at DEMO_URL,
// started by demo-instance.sh with its sample project, on a computer where
// Claude Code is installed and signed in. The model answers for real:
// assets/demo/readme/README.md has the whole procedure.
//
// The take: the first-run setup and two stops of the guided walk; a routine
// asked of Dodaios in its chat; the sample project connected in the Agentic
// IDE, a coding agent prompted in a thread and its changes reviewed; then
// Dodaios hands a fix to a coding agent itself, the thread it started is
// opened, and Dodaios reports back when the agent is done.
//
// The window is 1280 x 720 at a device scale of 1.5, so the frames are
// 1920 x 1080 and the interface stays readable when the video is shown small.
// The pointer is drawn into the page because a headless browser has none.
// The folder gets the frames and list.txt, an ffmpeg concat list that keeps
// every frame on screen for as long as it was during the take, played SPEED
// times faster; while the take only waits for a model, FAST times faster.
// timeline.json lists those stretches.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const OUT = process.argv[2];
const URL = process.env.DEMO_URL || 'http://127.0.0.1:47990/';
// The model every turn uses. Claude Code must be signed in to a plan that has it.
const MODEL = process.env.DEMO_MODEL || 'Claude Opus 5.5';
const SPEED = Number(process.env.DEMO_SPEED || 1.4);
const FAST = Number(process.env.DEMO_FAST || 7);
if (!OUT) { console.error('usage: node record.cjs <output folder>'); process.exit(2); }
const W = 1280, H = 720;
const MODEL_WAIT = 5 * 60 * 1000;
// Dodaios runs on Claude Code too: ask for a thread, or it may do the work itself.
const HANDOFF = 'Open a Claude Code thread in trailhead on Opus 5.5 to fix the bug where a time just under a whole hour reads 1 h 60 min. Tell me when it is done.';

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
    // A dialog that was still settling moves its buttons: follow them.
    for (let i = 0; i < 3; i++) {
      const a = await el.boundingBox();
      if (!a) break;
      const x = a.x + a.width / 2 + dx, y = a.y + a.height / 2 + dy;
      if (Math.hypot(x - cx, y - cy) < 4) break;
      await moveTo(x, y, 180);
    }
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
  // Stretches of the take, by frame index, and how fast each one plays.
  const stretches = [{ from: 0, speed: SPEED, what: 'start' }];
  client.on('Page.screencastFrame', (f) => {
    client.send('Page.screencastFrameAck', { sessionId: f.sessionId }).catch(() => {});
    if (!recording) return;
    const name = String(idx++).padStart(6, '0') + '.jpg';
    fs.writeFileSync(path.join(OUT, name), Buffer.from(f.data, 'base64'));
    frames.push({ name, ts: f.metadata.timestamp });
  });
  // From the next frame on, the take only waits for the model (or no longer).
  const waiting = (what) => stretches.push({ from: idx, speed: FAST, what: 'wait: ' + what });
  const acting = (what) => stretches.push({ from: idx, speed: SPEED, what });
  const finish = async () => {
    recording = false;
    await client.send('Page.stopScreencast').catch(() => {});
    const speedAt = (i) => { let s = SPEED; for (const st of stretches) if (st.from <= i) s = st.speed; return s; };
    const lines = ['ffconcat version 1.0'];
    let played = 0;
    frames.forEach((frame, i) => {
      const next = frames[i + 1];
      const real = next ? Math.max(next.ts - frame.ts, 0.001) : 1.2;
      const shown = real / speedAt(i);
      played += shown;
      lines.push(`file '${frame.name}'`, `duration ${shown.toFixed(4)}`);
    });
    if (frames.length) lines.push(`file '${frames[frames.length - 1].name}'`);
    fs.writeFileSync(path.join(OUT, 'list.txt'), lines.join('\n') + '\n');
    const t0 = frames.length ? frames[0].ts : 0;
    fs.writeFileSync(path.join(OUT, 'timeline.json'), JSON.stringify(stretches.map((st) => ({
      ...st, at: frames[Math.min(st.from, frames.length - 1)] ? +(frames[Math.min(st.from, frames.length - 1)].ts - t0).toFixed(2) : null,
    })), null, 1));
    return played;
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

  // The Dodaios chat has no stop button (a turn is stopped by writing "stop"),
  // so a running turn is read from the transcript: the typing dots before the
  // turn starts, then the turn itself while it runs.
  const chatWorking = page.locator('[data-testid="agent-turn-awaiting"]:visible, [data-testid="agent-turn"][data-status="running"]:visible');
  // The Agentic IDE stays mounted behind the chat, so only a visible field counts.
  const chatInput = () => page.locator('[data-testid="composer-row"] [contenteditable=true]:visible, [data-testid="composer-row"] textarea:visible').first();
  async function chatTurnEnds(what, startsWithin = 30000) {
    await chatWorking.first().waitFor({ state: 'visible', timeout: startsWithin }).catch(() => {});
    await chatWorking.first().waitFor({ state: 'hidden', timeout: MODEL_WAIT });
    log('turn ended:', what);
  }
  // A thread's turn ends with "Worked for <time>".
  const workedCount = () => page.getByText(/^Worked for /).count();
  async function threadTurnEnds(nBefore, what) {
    const until = Date.now() + MODEL_WAIT;
    while ((await workedCount()) <= nBefore) {
      if (Date.now() > until) throw new Error(`the coding agent did not finish (${what})`);
      await sleep(400);
    }
    log('thread turn ended:', what);
  }
  const thoughts = () => page.getByText(/^Thought for /).count();
  // The caption's switch between Dodaios (a new chat) and the Agentic IDE.
  const toIde = () => click('[data-testid="surface-ide"]', { post: 900 });
  const toNewChat = () => click('[data-testid="surface-dodaios"]', { post: 900 });

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
    await point(page.getByText('Signed in', { exact: true }).first(), { dx: -40, ms: 550 });
    await sleep(700);
    await point(page.getByText('Use a free local model').first(), { ms: 850 });
    await sleep(600);
    await click(btn(/^Continue/), { post: 600 });
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

    // ---- 3. Dodaios: pick the model, let it run something on the computer ---
    mark('dodaios');
    const skipIntro = page.getByText('Skip introduction').first();
    if (await skipIntro.waitFor({ state: 'visible', timeout: 1500 }).then(() => true, () => false)) {
      await click(skipIntro, { post: 500 });
    }
    await click('[aria-label="Model"]:visible', { post: 600 });
    await click(page.getByText(MODEL, { exact: true }).last(), { post: 500 });
    await click(chatInput(), { post: 200 });
    await type('What does ~/projects/trailhead do? Run it for a 14.5 km hike with 820 m of climb and answer in two sentences.', 30);
    await sleep(350);
    await page.keyboard.press('Enter');
    await moveTo(W * 0.5, H * 0.42, 600);
    waiting('first answer');
    await chatTurnEnds('first answer');
    acting('answered');
    await sleep(900);
    await point(page.getByText(/about \d+ h \d+ min/).last(), { ms: 650 });
    await sleep(2200);

    // ---- 4. Agentic IDE: connect the project, prompt a coding agent --------
    mark('ide');
    await toIde();
    await click(btn(/Connect folder/).first(), { post: 500 });
    await click(btn(/Choose folder/), { post: 650 });
    const picker = page.locator('[role=dialog]').last();
    await click(picker.getByText('Home', { exact: true }).first(), { post: 450 });
    await click(picker.getByText('projects', { exact: true }).first(), { post: 450 });
    await click(picker.getByText('trailhead', { exact: true }).first(), { post: 450 });
    await click(btn(/Use this folder/), { post: 450 });
    await click(btn(/^Connect project$/), { post: 1100 });
    mark('thread');
    await click('[aria-label="Coding agent and model"]', { post: 600 });
    await click(page.getByText(MODEL, { exact: true }).last(), { post: 450 });
    await click('[aria-label="Message the coding agent"]', { post: 200 });
    const worked0 = await workedCount();
    await type('Add a --pace option (relaxed, steady, fast) that scales the walking speed, with a test for each pace. Run the tests and keep the summary short.', 28);
    await sleep(350);
    await page.keyboard.press('Enter');
    await moveTo(W * 0.62, H * 0.3, 700);
    waiting('coding agent');
    await threadTurnEnds(worked0, 'pace');
    acting('pace done');
    await sleep(2200);
    mark('review');
    await click('[aria-label="Review changes"]', { post: 1500 });
    const review = page.locator('[role=dialog]').last();
    await moveTo(W * 0.6, H * 0.6, 500);
    for (let i = 0; i < 14; i++) { await page.mouse.wheel(0, 45); await sleep(40); }
    await sleep(1600);
    const closeReview = review.getByRole('button', { name: /Close/ }).first();
    if (await closeReview.isVisible().catch(() => false)) await click(closeReview, { post: 500 });
    else { await page.keyboard.press('Escape'); await sleep(500); }

    // ---- 5. Dodaios hands a fix to a coding agent ---------------------------
    mark('handoff');
    await toNewChat();
    await click(chatInput(), { post: 200 });
    await type(HANDOFF, 28);
    await sleep(350);
    await page.keyboard.press('Enter');
    await moveTo(W * 0.5, H * 0.4, 600);
    waiting('handoff');
    const openThread = page.getByText('Open thread', { exact: true });
    await openThread.first().waitFor({ state: 'visible', timeout: MODEL_WAIT });
    await chatTurnEnds('handoff');
    const thoughtsAfterHandoff = await thoughts();
    acting('thread started');
    await sleep(900);
    await click(openThread.first(), { post: 1200 });
    mark('delegated thread');
    await point(page.getByText('Written by Dodaios').first(), { ms: 600 });
    await sleep(1600);
    await moveTo(W * 0.62, H * 0.3, 600);
    waiting('delegated coding agent');
    await threadTurnEnds(0, 'fix');
    acting('fix done');
    await sleep(1000);
    // The turn ends with a card of the files it changed: open its diff.
    const showChanges = btn(/^Show changes$/).last();
    if (await showChanges.waitFor({ state: 'visible', timeout: 6000 }).then(() => true, () => false)) {
      await click(showChanges, { post: 900 });
      await sleep(1900);
    }
    mark('report');
    // Back to the chat that started the thread (the switch would open a new one).
    await click('[aria-label="Go back"]', { post: 700 });
    await page.getByText(HANDOFF).first().waitFor({ state: 'visible' });
    waiting('report');
    await page.getByText(/finished in/).first().waitFor({ state: 'visible', timeout: MODEL_WAIT });
    // A finished answer folds its reasoning into "Thought for <time>": the
    // report is the answer after the hand-off's.
    const until = Date.now() + MODEL_WAIT;
    while (!((await thoughts()) >= thoughtsAfterHandoff + 1 && !(await chatWorking.first().isVisible().catch(() => false)))) {
      if (Date.now() > until) throw new Error('Dodaios did not report back');
      await sleep(400);
    }
    log('report written');
    acting('report');
    await sleep(600);
    // Wheel back to where the report begins, under the "finished" line.
    await moveTo(W * 0.42, H * 0.5, 500);
    const finished = page.getByText(/finished in/).last();
    for (let i = 0; i < 40; i++) {
      const b = await finished.boundingBox();
      if (!b || b.y >= 40) break;
      await page.mouse.wheel(0, -40);
      await sleep(45);
    }
    await sleep(1800);
    await moveTo(W * 0.73, H * 0.62, 900);

    mark('end');
    await sleep(3000);
    const played = await finish();
    log('frames', frames.length, 'take seconds', (frames[frames.length - 1].ts - frames[0].ts).toFixed(1), 'video seconds', played.toFixed(1));
  } catch (e) {
    await finish().catch(() => {});
    await page.screenshot({ path: path.join(OUT, 'failure.png') }).catch(() => {});
    console.error('FAILED:', e.message.split('\n').slice(0, 6).join('\n'));
    process.exitCode = 1;
  }
  await browser.close();
})();
