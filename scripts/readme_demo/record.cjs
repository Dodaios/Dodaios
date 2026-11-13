// Records the README demo: one continuous take of the real app, driven through
// its own interface, captured with the Chrome DevTools screencast.
//
//   node scripts/readme_demo/record.cjs <output folder>
//
// It expects a first-run Dodaios instance (nothing set up yet) at DEMO_URL,
// started by demo-instance.sh with its sample projects, on a computer where
// Claude Code is installed and signed in. The model answers for real:
// assets/demo/readme/README.md has the whole procedure.
//
// The script works in three parts. Only the last one is recorded.
//
//   setup    the first-run dialog, and both sample projects connected
//   warm-up  a morning's work, so the take starts in a workspace that is in
//            use: two threads in the Agentic IDE, then two requests to Dodaios
//            (a coding agent for one project, an artifact from the other)
//   take     Dodaios is asked about a wrong invoice. It finds the cause and
//            starts a coding agent; the agent's thread is opened while it
//            works and the change it made is shown; Dodaios checks the result
//            and reports; then it builds an incident report as an artifact.
//
// DEMO_PARTS names the parts to run (default "setup,warmup,take").
//
// The window is 1200 x 675 at a device scale of 1.6, so the frames are
// 1920 x 1080. The picture moves in on the part of the window that matters
// (a transform on the page itself, so the text stays sharp), because a README
// shows the video at about two thirds of that width. The pointer is drawn
// into the page because a headless browser has none.
//
// The folder gets the frames and list.txt, an ffmpeg concat list that keeps
// every frame on screen for as long as it was during the take, played SPEED
// times faster. A stretch in which the take only waits for a model is
// shortened to the length given to waiting(). timeline.json lists the
// stretches and how fast each one plays; frames.json has every frame's time.
const { chromium } = require('playwright');
const fs = require('fs');
const os = require('os');
const path = require('path');

const OUT = process.argv[2];
const URL = (process.env.DEMO_URL || 'http://127.0.0.1:47990/').replace(/\/?$/, '/');
// The model of Dodaios itself and of the coding agent it starts in the take.
// Claude Code must be signed in to a plan that has it.
const MODEL = process.env.DEMO_MODEL || 'Claude Fable 5.2';
const MODEL_SPOKEN = MODEL.replace(/^Claude /, '');
// Models of the warm-up's threads: any two the picker offers.
const WARM_MODELS = (process.env.DEMO_WARM_MODELS || 'Claude Sonnet 5.5,Claude Haiku 5.5').split(',');
const PARTS = (process.env.DEMO_PARTS || 'setup,warmup,take').split(',');
// An installed browser to use instead of Playwright's own ("chrome", "msedge").
const BROWSER = process.env.DEMO_BROWSER || '';
if (!OUT) { console.error('usage: node record.cjs <output folder>'); process.exit(2); }
const W = 1200, H = 675, SCALE = 1.6;
const MODEL_WAIT = 6 * 60 * 1000;
const BUILD_WAIT = 20 * 60 * 1000;   // an artifact took two to nine minutes
const TYPING = 24;   // milliseconds a key, the same everywhere
const SPEED = Number(process.env.DEMO_SPEED || 1.15);

// The take as ffmpeg's concat list: every frame with the time it stays on
// screen. `stretches` are the parts of the take in order, each with the time
// it began (`at`, seconds, the clock of the frames); one with a `target` only
// waits for a model and is played in that many seconds, the others `speed`
// times faster. A picture that stands still across the start of a stretch
// belongs to both, each part at its own speed. Fills in what each stretch
// lasted and how fast it plays, and returns the lines and the video's length.
function playlist(frames, stretches, end, speed) {
  const start = frames[0].ts;
  const marks = stretches.map((st) => Math.min(end, Math.max(start, st.at)));
  marks[0] = start;
  const until = (n) => (n + 1 < marks.length ? marks[n + 1] : end);
  stretches.forEach((st, n) => {
    st.seconds = +(until(n) - marks[n]).toFixed(2);
    st.speed = +(st.target ? Math.max(speed, st.seconds / st.target) : speed).toFixed(2);
  });
  const lines = ['ffconcat version 1.0'];
  let played = 0;
  frames.forEach((frame, i) => {
    const from = frame.ts, to = i + 1 < frames.length ? frames[i + 1].ts : end;
    let shown = 0;
    stretches.forEach((st, n) => {
      const part = Math.min(to, until(n)) - Math.max(from, marks[n]);
      if (part > 0) shown += part / st.speed;
    });
    shown = Math.max(shown, 0.00001);
    played += shown;
    lines.push(`file '${frame.name}'`, `duration ${shown.toFixed(6)}`);
  });
  lines.push(`file '${frames[frames.length - 1].name}'`);
  return { lines, played };
}

const WARM_THREADS = [
  ['trailhead', WARM_MODELS[0], 'Add a --json flag to the plan command that prints the estimate as JSON, with a test.'],
  ['ledger', WARM_MODELS[1] || WARM_MODELS[0], 'Where is the billing export read, and what happens when a line has no quantity? A few lines, change nothing.'],
];
const WARM_AGENT = 'Put a Sonnet agent on trailhead: add a --pace option (relaxed, steady, fast) that scales the walking speed, with a test for each pace.';
const WARM_ARTIFACT = "Make an artifact: October's invoices by customer as a bar chart, from ledger's export.";
const ASK = `Brightwell Dental says invoice INV-2041 is one cent too high. Check it in ledger, then put a ${MODEL_SPOKEN} agent on the fix. No commit yet, I want to review the diff.`;
const ASK_ARTIFACT = 'Make an artifact for finance: a one-page incident report with the three invoices before and after, and the fix.';

// The computer's own name and the home folder of whoever records never
// belong in the picture. Everything else on screen is shown as it is.
const host = os.hostname();
const SCRUB = [
  [host, 'MacBook-Pro'],
  [host.replace(/\.(local|lan|home|fritz\.box)$/i, ''), 'MacBook-Pro'],
  [os.homedir(), '/Users/demo'],
].filter(([from], i, all) => from && from.length > 3 && all.findIndex(([f]) => f === from) === i);
for (const pair of (process.env.DEMO_SCRUB || '').split(',').filter(Boolean)) SCRUB.push(pair.split('='));

const PAGE_HELPERS = `(() => {
  const pairs = ${JSON.stringify(SCRUB)};
  const fix = (s) => { for (const [a, b] of pairs) if (s.includes(a)) s = s.split(a).join(b); return s; };
  const walk = (n) => {
    if (n.nodeType === 3) { const v = fix(n.nodeValue); if (v !== n.nodeValue) n.nodeValue = v; return; }
    if (n.nodeType !== 1) return;
    for (const a of ['title', 'aria-label']) { const v = n.getAttribute(a); if (v) { const f = fix(v); if (f !== v) n.setAttribute(a, f); } }
    for (const c of n.childNodes) walk(c);
  };
  if (pairs.length) {
    new MutationObserver((ms) => { for (const m of ms) { if (m.type === 'characterData') walk(m.target); for (const n of m.addedNodes) walk(n); } })
      .observe(document, { subtree: true, childList: true, characterData: true });
  }
  // One pointer, drawn in the window's own document. A page inside a frame
  // (an artifact) gets the mouse events itself, so it passes them on.
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
    // Beside the body, so the camera's transform on the body leaves it alone.
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
    const k = frame.clientWidth ? r.width / frame.clientWidth : 1;   // the camera's zoom
    if (m.__demo === 'mousemove') place(r.left + m.x * k, r.top + m.y * k);
    else squeeze(m.__demo === 'mousedown');
  });
  if (document.documentElement) install();
  document.addEventListener('DOMContentLoaded', install);
})();`;

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({
    ...(BROWSER ? { channel: BROWSER } : {}),
    args: [`--force-device-scale-factor=${SCALE}`, `--window-size=${W},${H}`, '--force-color-profile=srgb', '--hide-scrollbars'],
  });
  const ctx = await browser.newContext({ viewport: null, colorScheme: 'dark', timezoneId: 'Europe/Berlin', locale: 'en-US' });
  await ctx.addInitScript(PAGE_HELPERS);
  const page = await ctx.newPage();
  page.setDefaultTimeout(15000);
  const client = await ctx.newCDPSession(page);
  // An installed browser counts its own frame into --window-size: make the
  // page itself W x H, or the frames come out lower than 1080.
  {
    const [w, h] = await page.evaluate(() => [innerWidth, innerHeight]);
    if (w !== W || h !== H) {
      const { windowId, bounds } = await client.send('Browser.getWindowForTarget');
      await client.send('Browser.setWindowBounds', { windowId, bounds: { width: bounds.width + W - w, height: bounds.height + H - h } });
      await page.waitForTimeout(500);
    }
  }
  const started = Date.now();
  const log = (...a) => console.log(`[${((Date.now() - started) / 1000).toFixed(1).padStart(6)}s]`, ...a);
  const sleep = (ms) => page.waitForTimeout(ms);
  const debug = async (name) => { await page.screenshot({ path: path.join(OUT, `debug-${name}.png`), scale: 'css' }).catch(() => {}); };

  // ---- pointer ----------------------------------------------------------
  let cx = W * 0.55, cy = H * 0.6;
  const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
  // Time-based, so a move lasts as long as asked whatever one step costs.
  async function moveTo(x, y, ms) {
    const dist = Math.hypot(x - cx, y - cy);
    const dur = ms ?? Math.min(760, Math.max(240, dist * 0.95));
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
  const first = (loc) => (typeof loc === 'string' ? page.locator(loc).first() : loc);
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
    const el = first(loc);
    await el.waitFor({ state: 'visible' });
    const b = await reveal(el);
    await moveTo(b.x + b.width / 2 + dx, b.y + b.height / 2 + dy, ms);
    // Something that was still settling moves its buttons: follow them.
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
    await sleep(opts.pre ?? 140);
    await press();
    await sleep(opts.post ?? 350);
  }
  const type = async (text, delay = TYPING) => { await page.keyboard.type(text, { delay }); };
  const btn = (name) => page.getByRole('button', { name });
  async function wheel(total, step = 40, pause = 16) {
    for (let done = 0; Math.abs(done) < Math.abs(total); done += Math.sign(total) * step) {
      await page.mouse.wheel(0, Math.sign(total) * step);
      await sleep(pause);
    }
  }

  // ---- camera -------------------------------------------------------------
  // A transform on the body: zoom z with the layout point (fx, fy) in the
  // middle of the window, as far as the window's edges allow.
  const cam = { z: 1, tx: 0, ty: 0 };
  async function camera(z, fx = W / 2, fy = H / 2, ms = 850) {
    const tx = Math.min(0, Math.max(W - W * z, W / 2 - fx * z));
    const ty = Math.min(0, Math.max(H - H * z, H / 2 - fy * z));
    // The pointer stays on the spot of the page it was on.
    const px = (cx - cam.tx) / cam.z, py = (cy - cam.ty) / cam.z;
    Object.assign(cam, { z, tx, ty });
    await page.evaluate(({ z, tx, ty, ms }) => {
      const b = document.body;
      b.style.transformOrigin = '0 0';
      b.style.transition = `transform ${ms}ms cubic-bezier(0.45, 0, 0.2, 1)`;
      b.style.transform = z === 1 ? '' : `translate(${tx}px, ${ty}px) scale(${z})`;
    }, { z, tx, ty, ms });
    await moveTo(Math.min(W - 4, Math.max(4, px * z + tx)), Math.min(H - 4, Math.max(4, py * z + ty)), ms);
    await sleep(60);
  }
  // Where an element is in the layout, whatever the camera shows right now.
  async function layoutBox(loc) {
    const b = await first(loc).boundingBox();
    if (!b) return null;
    return { x: (b.x - cam.tx) / cam.z, y: (b.y - cam.ty) / cam.z, width: b.width / cam.z, height: b.height / cam.z };
  }
  const wide = (ms) => camera(1, W / 2, H / 2, ms);

  // ---- what the app is doing, asked of its API ---------------------------
  const api = async (route) => {
    try { return await (await fetch(URL + route.replace(/^\//, ''))).json(); } catch { return null; }
  };
  const busy = async () => {
    const lead = await api('api/agent-chat/lead');
    const threads = await api('api/agent-chat/sessions?surface=agent');
    return Boolean(lead?.running) || (threads?.sessions || []).some((s) => s.running);
  };
  // A turn that could not reach its model says so in the conversation. Such a
  // take is of no use: stop at once instead of waiting for an answer.
  async function noFailedTurn() {
    const failure = page.getByText(/API Error|Failed to authenticate/).first();
    if (await failure.isVisible().catch(() => false)) throw new Error('a turn failed: ' + (await failure.innerText()).slice(0, 160));
  }
  // Poll until `done()` says so.
  async function until(done, what, timeout = MODEL_WAIT, every = 300) {
    const end = Date.now() + timeout;
    while (!(await done())) {
      await noFailedTurn();
      if (Date.now() > end) throw new Error(`waited ${Math.round(timeout / 1000)} s in vain for ${what}`);
      await sleep(every);
    }
  }
  // Nothing runs, and nothing has for `calm` ms: Dodaios is told when a coding
  // agent finishes and then takes a turn of its own, so one idle moment is not the end.
  async function settled(what, { calm = 7000, startsWithin = 45000, timeout = MODEL_WAIT } = {}) {
    const t0 = Date.now();
    while (!(await busy()) && Date.now() - t0 < startsWithin) await sleep(400);
    let idleSince = 0;
    for (;;) {
      if (Date.now() - t0 > timeout) throw new Error(`still working after ${Math.round(timeout / 1000)} s (${what})`);
      await noFailedTurn();
      if (await busy()) idleSince = 0;
      else if (!idleSince) idleSince = Date.now();
      else if (Date.now() - idleSince >= calm) break;
      await sleep(500);
    }
    log('settled:', what);
  }
  const missions = async () => (await api('api/missions'))?.missions || [];
  // A build of an artifact is a mission. Wait for the one started after `known`.
  async function built(known, what) {
    const t0 = Date.now();
    for (;;) {
      const fresh = (await missions()).filter((m) => !known.has(m.id));
      const failed = fresh.find((m) => /FAIL|CANCEL|TIMED_OUT/i.test(m.state));
      if (failed) throw new Error(`the build failed (${what}): ${failed.state}`);
      await noFailedTurn();
      if (fresh.length && fresh.every((m) => m.state === 'APPROVED')) break;
      if (Date.now() - t0 > BUILD_WAIT) throw new Error(`no finished build after ${BUILD_WAIT / 60000} min (${what}): ${fresh.map((m) => m.state).join(', ') || 'none started'}`);
      await sleep(1000);
    }
    log('built:', what);
  }

  // ---- the app's own controls ----------------------------------------------
  // The Agentic IDE stays mounted behind the chat, so only a visible field counts.
  const chatInput = () => page.locator('[data-testid="composer-row"] [contenteditable=true]:visible, [data-testid="composer-row"] textarea:visible').first();
  const threadInput = () => page.locator('[aria-label="Message the coding agent"]:visible').first();
  const agentLinks = () => page.locator('[data-testid="coding-agent-link"]:visible');
  const threadIds = async () => new Set(((await api('api/agent-chat/sessions?surface=agent'))?.sessions || []).map((s) => s.session_id));
  // The thread started after `known` has finished its turn, and the window says so.
  async function threadDone(known, what) {
    await until(async () => {
      const fresh = ((await api('api/agent-chat/sessions?surface=agent'))?.sessions || []).filter((t) => !known.has(t.session_id));
      return fresh.length && fresh.every((t) => !t.running) && (await page.locator('button:visible', { hasText: /^Worked for / }).count()) > 0;
    }, `the coding agent (${what})`);
    log('thread done:', what);
  }
  // To the conversation with Dodaios: by the section rail, or from the Agentic
  // IDE, which has no rail, by the switch in the window's caption.
  async function toChat() {
    const rail = page.locator('[data-testid="sidebar-shortcut-chats"]:visible').first();
    await click((await rail.isVisible().catch(() => false)) ? rail : '[data-testid="surface-dodaios"]', { post: 900 });
    await chatInput().waitFor({ state: 'visible' });
  }
  const onArtifact = () => page.locator('iframe[src*="/api/outputs/"]:visible').first();
  async function pick(control, name) {
    await click(control, { post: 600 });
    await click(page.getByText(name, { exact: true }).last(), { post: 450 });
  }
  async function connectProject(name) {
    const empty = btn(/^Connect folder$/).first();
    if (await empty.isVisible().catch(() => false)) await click(empty, { post: 500 });
    else await click('[aria-label="Connect project"]', { post: 500 });
    await click(btn(/Choose folder/), { post: 650 });
    const picker = page.locator('[role=dialog]').last();
    for (const step of ['Home', 'projects', name]) await click(picker.getByText(step, { exact: true }).first(), { post: 450 });
    await click(btn(/Use this folder/), { post: 450 });
    await click(btn(/^Connect project$/), { post: 1200 });
  }

  // ---- screencast -----------------------------------------------------------
  const frames = []; let idx = 0; let recording = false;
  // The parts of the take, see playlist().
  const stretches = [];
  client.on('Page.screencastFrame', (f) => {
    client.send('Page.screencastFrameAck', { sessionId: f.sessionId }).catch(() => {});
    if (!recording) return;
    const name = String(idx++).padStart(6, '0') + '.jpg';
    fs.writeFileSync(path.join(OUT, name), Buffer.from(f.data, 'base64'));
    frames.push({ name, ts: f.metadata.timestamp });
  });
  const acting = (what) => { stretches.push({ at: Date.now() / 1000, what }); log('take:', what); };
  const waiting = (what, target) => { stretches.push({ at: Date.now() / 1000, what: 'wait: ' + what, target }); log('take: waiting for', what); };
  const finish = async () => {
    recording = false;
    await client.send('Page.stopScreencast').catch(() => {});
    if (!frames.length || !stretches.length) return 0;
    const { lines, played } = playlist(frames, stretches, frames[frames.length - 1].ts + 1.2, SPEED);
    fs.writeFileSync(path.join(OUT, 'list.txt'), lines.join('\n') + '\n');
    fs.writeFileSync(path.join(OUT, 'timeline.json'), JSON.stringify(stretches, null, 1));
    fs.writeFileSync(path.join(OUT, 'frames.json'), JSON.stringify(frames));
    return played;
  };

  try {
    await page.goto(URL, { waitUntil: 'domcontentloaded' });
    await sleep(3000);
    await page.mouse.move(cx, cy);

    // ---- setup: the first-run dialog, both projects ---------------------------
    if (PARTS.includes('setup')) {
      log('setup');
      const dlg = page.locator('[role=dialog]').first();
      await dlg.locator('input').first().waitFor({ state: 'visible', timeout: 30000 });
      await click(dlg.locator('input').first(), { post: 200 });
      await type('Dodaios');
      await click(btn(/Continue/), { post: 500 });
      await page.getByText('Connect your AI').waitFor();
      await page.getByText(/^Signed in/).first().waitFor({ timeout: 30000 });
      await click(btn(/^Continue/), { post: 500 });
      await page.getByText(/How you'll talk to/).waitFor();
      await click(btn(/Show me around/), { post: 600 });
      // The guided walk: its bubble takes a moment to listen.
      const next = btn(/^Next$/);
      await next.waitFor({ state: 'visible' });
      await sleep(1500);
      for (let i = 0; i < 4 && (await next.isVisible().catch(() => false)); i++) {
        await click(page.getByText('Skip', { exact: true }).last(), { post: 1000 });
      }
      const intro = page.getByText('Skip introduction').first();
      if (await intro.waitFor({ state: 'visible', timeout: 2500 }).then(() => true, () => false)) await click(intro, { post: 500 });
      await click('[data-testid="surface-ide"]', { post: 1200 });
      await connectProject('ledger');
      await connectProject('trailhead');
    }

    // ---- warm-up: a morning's work, not recorded ------------------------------
    if (PARTS.includes('warmup')) {
      log('warm-up: two threads in the Agentic IDE');
      await click('[data-testid="surface-ide"]', { post: 1200 });
      for (const [project, model, prompt] of WARM_THREADS) {
        await click(`[aria-label="New thread in ${project}"]`, { post: 900 });
        await pick('[aria-label="Coding agent and model"]', model);
        await click(threadInput(), { post: 200 });
        await type(prompt, 4);
        await page.keyboard.press('Enter');
        await sleep(2500);
      }
      await settled('the two threads', { calm: 4000 });
      await debug('warm-threads');

      log('warm-up: Dodaios starts a coding agent');
      await toChat();
      await pick('[aria-label="Model"]:visible', MODEL);
      await click(chatInput(), { post: 200 });
      await type(WARM_AGENT, 4);
      await page.keyboard.press('Enter');
      await until(async () => (await agentLinks().count()) > 0, 'Dodaios to start the earlier coding agent');
      await settled('the earlier coding agent and its report');
      await debug('warm-agent');

      log('warm-up: Dodaios builds an artifact');
      const known = new Set((await missions()).map((m) => m.id));
      await click(chatInput(), { post: 200 });
      await type(WARM_ARTIFACT, 4);
      await page.keyboard.press('Enter');
      await built(known, 'the earlier artifact');
      await settled('the earlier artifact', { startsWithin: 8000 });
      await debug('warm-artifact');
      log('warm-up done, the window shows', page.url());
    }

    if (!PARTS.includes('take')) { await browser.close(); return; }

    // ---- the take ---------------------------------------------------------------
    await toChat();
    const intro = page.getByText('Skip introduction').first();
    if (await intro.isVisible().catch(() => false)) await click(intro, { post: 500 });
    await moveTo(W * 0.5, H * 0.5, 300);
    await wheel(4000, 400, 10);
    await sleep(700);
    // The take opens on a request that is already being typed.
    const lead = Math.round(ASK.length * 0.3);
    await click(chatInput(), { post: 150 });
    await type(ASK.slice(0, lead));
    const stage = await layoutBox('[data-testid="chat-stage"]');
    const chatX = stage ? stage.x + stage.width / 2 : W * 0.42;
    await client.send('Page.startScreencast', { format: 'jpeg', quality: 93, maxWidth: Math.round(W * SCALE), maxHeight: Math.round(H * SCALE), everyNthFrame: 1 });
    recording = true;
    const known = new Set((await missions()).map((m) => m.id));
    const threadsBefore = await threadIds();
    const agentsBefore = await agentLinks().count();

    // 1. The request. The picture moves in on the conversation while it is typed.
    acting('the request');
    const typing = type(ASK.slice(lead));
    await sleep(500);
    await camera(1.36, chatX, H, 1100);
    await typing;
    await sleep(450);
    await page.keyboard.press('Enter');
    await moveTo(Math.min(W - 40, cx + 150), cy - 70, 500);

    // 2. Dodaios looks into it and starts the coding agent.
    waiting('Dodaios finding the cause and starting the agent', 4);
    let threadId = '';
    await until(async () => {
      threadId = [...(await threadIds())].find((id) => !threadsBefore.has(id)) || '';
      return Boolean(threadId);
    }, 'Dodaios to start the coding agent');
    // Its message names the agent, sometimes only after the agent is done.
    const agentLink = agentLinks().nth(agentsBefore);
    const named = await agentLink.waitFor({ state: 'visible', timeout: 2500 }).then(() => true, () => false);
    acting('the agent is started');
    await sleep(named ? 1200 : 300);

    // 3. Into the agent's thread while it works: by its name in the message,
    //    or by its line under "Recent activity" beside the conversation.
    if (named) {
      await click(agentLink, { pre: 320, post: 500 });
      await wide(650);
    } else {
      await wide(750);
      await sleep(500);
      await click(`[data-testid="assistant-activity-${threadId}"]`, { pre: 420, post: 600 });
    }
    await threadInput().waitFor({ state: 'visible' });
    await sleep(900);
    const thread = await layoutBox(threadInput());
    const threadX = thread ? thread.x + thread.width / 2 : W * 0.6;
    await camera(1.3, threadX, H * 0.52, 900);
    await moveTo(Math.min(W - 60, cx + 260), H * 0.36, 600);
    waiting('the coding agent', 8);
    await threadDone(threadsBefore, 'the fix');
    acting('the agent is done');
    await sleep(2200);

    // 4. Its changes: the turn ends with a card of the files it changed.
    const showChanges = btn(/^Show changes$/).last();
    if (await showChanges.waitFor({ state: 'visible', timeout: 6000 }).then(() => true, () => false)) {
      await click(showChanges, { post: 900 });
      const diff = await layoutBox(btn(/^Hide changes$/).last());
      if (diff) await camera(1.3, threadX, diff.y + 60, 700);
      await sleep(2800);
    } else {
      // No card (the agent committed, or changed files by a command): the review of the whole thread.
      await wide(600);
      await click('[aria-label="Review changes"]', { post: 1300 });
      await sleep(2600);
      const closeReview = page.locator('[role=dialog]').last().getByRole('button', { name: /Close/ }).first();
      if (await closeReview.isVisible().catch(() => false)) await click(closeReview, { post: 500 });
      else { await page.keyboard.press('Escape'); await sleep(500); }
    }

    // 5. Back to Dodaios, which checks the result itself and reports.
    await wide(600);
    await click('[aria-label="Go back"]', { post: 700 });
    await chatInput().waitFor({ state: 'visible' });
    await moveTo(chatX + 120, H * 0.5, 500);
    waiting("Dodaios's check and report", 2);
    await settled('the report', { startsWithin: 20000 });
    acting('the report');
    await sleep(400);
    await camera(1.36, chatX, H, 900);
    await sleep(2600);

    // 6. The incident report, as an artifact. The app shows the build, then the page.
    await click(chatInput(), { post: 150 });
    await type(ASK_ARTIFACT);
    await sleep(450);
    await page.keyboard.press('Enter');
    await moveTo(Math.min(W - 40, cx + 150), cy - 70, 500);
    waiting('Dodaios starting the build', 2.5);
    const inArtifacts = () => /view=visualization/.test(page.url());
    let ready = false;
    const build = built(known, 'the incident report').then(() => { ready = true; });
    await until(async () => ready || inArtifacts() || !(await chatInput().isVisible().catch(() => false)), 'the build to start', BUILD_WAIT);
    acting('the build');
    await sleep(300);
    await wide(800);
    await moveTo(W * 0.56, H * 0.62, 600);
    waiting('the artifact being built', 2.5);
    await build;
    if (!inArtifacts()) {
      // The app did not open it by itself: open the newest one in Artifacts.
      acting('opening the artifact');
      await click('[data-testid="sidebar-shortcut-visualization"]', { post: 1200 });
      await click(page.getByText(/incident report/i).first(), { post: 1200 });
    }
    await onArtifact().waitFor({ state: 'visible', timeout: 30000 });
    acting('the artifact');
    await sleep(2400);
    await wheel(430, 16, 24);
    await sleep(600);
    await camera(1.2, W * 0.52, H * 0.56, 900);
    await sleep(3000);

    // 7. Back where it began, so the loop restarts without a jump. Dodaios
    //    reads the page back first; the picture does not change meanwhile.
    waiting("Dodaios's last word", 0.4);
    await settled('the last word', { startsWithin: 5000 });
    acting('back to the conversation');
    await wide(700);
    await toChat();
    await moveTo(chatX + 140, H * 0.56, 500);
    await sleep(2200);

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
