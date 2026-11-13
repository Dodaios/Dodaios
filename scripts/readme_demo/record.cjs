// Films the README video's footage: the real app, driven through its own
// interface, captured with the Chrome DevTools screencast.
//
//   node scripts/readme_demo/record.cjs <output folder>
//
// It expects a first-run Dodaios instance (nothing set up yet) at DEMO_URL,
// started by demo-instance.sh with its sample projects, on a computer where
// Claude Code is installed and signed in. The model answers for real:
// assets/demo/readme/README.md has the whole procedure.
//
// The script works in four parts. The first two are not filmed.
//
//   setup    the first-run dialog, and both sample projects connected
//   warm-up  a morning's work, so the footage shows a workspace that is in
//            use: two threads in the Agentic IDE, then requests to Dodaios
//            (a coding agent, a standing task, an artifact)
//   take     Dodaios is asked about a wrong invoice and for an option in the
//            other project. It finds the cause and starts two coding agents;
//            their threads are opened while they work and their changes are
//            shown; Dodaios checks the results and reports; then it builds a
//            dashboard as an artifact.
//   tour     a few seconds each of plugins, memory, the model picker, the
//            pet and the conversation the take ended in
//
// DEMO_PARTS names the parts to run (default "setup,warmup,take,tour").
//
// The window is 1200 x 675 at a device scale of 2.4, so the frames are
// 2880 x 1620: the film is cut in 1920 x 1080 and moves in on parts of the
// window, which stay sharp that way. The pointer is drawn into the page
// because a headless browser has none.
//
// The folder gets the frames and take.json: every frame's time, the
// stretches of footage in order (a name and the time each began), and the
// places of the parts of the window the film moves in on. render.cjs cuts
// the film from that.
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
const PARTS = (process.env.DEMO_PARTS || 'setup,warmup,take,tour').split(',');
// An installed browser to use instead of Playwright's own ("chrome", "msedge").
const BROWSER = process.env.DEMO_BROWSER || '';
if (!OUT) { console.error('usage: node record.cjs <output folder>'); process.exit(2); }
const W = 1200, H = 675, SCALE = Number(process.env.DEMO_SCALE || 2.4);
const MODEL_WAIT = 6 * 60 * 1000;
const BUILD_WAIT = 20 * 60 * 1000;   // an artifact took two to nine minutes
const TYPING = 24;   // milliseconds a key, the same everywhere

const WARM_THREADS = [
  ['trailhead', WARM_MODELS[0], 'Add a --json flag to the plan command that prints the estimate as JSON, with a test.'],
  ['ledger', WARM_MODELS[1] || WARM_MODELS[0], 'Where is the billing export read, and what happens when a line has no quantity? A few lines, change nothing.'],
];
const WARM_AGENT = 'Put a Haiku agent on trailhead: describe the --json flag in the README, in two lines.';
const WARM_TASK = 'Look after ledger: every weekday at 9:00, run its tests and tell me if one fails.';
const WARM_ARTIFACT = "Make an artifact: October's invoices by customer as a bar chart, from ledger's export.";
// The second agent of the take: any model of the picker but MODEL.
const SECOND = process.env.DEMO_SECOND_MODEL || 'Sonnet 5.5';
const ASK = `Invoice INV-2041 is one cent too high. Check it in ledger, then put a ${MODEL_SPOKEN} agent on the fix and a ${SECOND} agent on a --pace option for trailhead.`;
const ASK_ARTIFACT = "Make an artifact for finance: a dashboard of October's invoices, a bar per customer, the three corrected invoices marked.";
const MEMORIES = [
  ['I work mostly in Python and TypeScript.', 'About you'],
  ['ledger is the invoicing library; its rounding rule is in docs/rounding.md.', 'Projects'],
  ['Always run the tests before you call something done.', 'Standing instructions'],
  ['Sam reviews my pull requests.', 'People'],
  ['The billing export arrives on the first of the month.', 'Facts & things'],
];

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
  // How much of the recording person's plan is used is nobody's business.
  const hide = () => {
    if (document.getElementById('__demo_hide') || !document.head) return;
    const st = document.createElement('style');
    st.id = '__demo_hide';
    st.textContent = '[data-testid="thread-plan-usage"] { visibility: hidden !important; }';
    document.head.appendChild(st);
  };
  hide();
  document.addEventListener('DOMContentLoaded', hide);
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
    // Beside the body, so nothing the page does to its body moves it.
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
    const k = frame.clientWidth ? r.width / frame.clientWidth : 1;   // a frame the page shows scaled
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
  let idx = 0; let recording = false; let gap = 0; let kept = 0; let casting = false;
  // A part filmed later (the tour alone, after a take) is added to the folder's take.json.
  const earlier = !PARTS.includes('take') && fs.existsSync(path.join(OUT, 'take.json')) ? JSON.parse(fs.readFileSync(path.join(OUT, 'take.json'), 'utf8')) : {};
  const frames = earlier.frames || [];
  const stretches = (earlier.stretches || []).filter((st) => !st.name.startsWith('tour-'));   // the footage in order: a name, when it began
  const marks = earlier.marks || [];       // where a part of the window was, and when
  const threads = earlier.threads || [];   // the coding agents the take started
  if (frames.length) { idx = Number(frames[frames.length - 1].name.slice(0, 6)) + 1; stretches.push({ name: '', at: frames[frames.length - 1].ts + 1 }); }
  const now = () => Date.now() / 1000;
  client.on('Page.screencastFrame', (f) => {
    client.send('Page.screencastFrameAck', { sessionId: f.sessionId }).catch(() => {});
    const ts = f.metadata.timestamp;
    if (!recording || ts - kept < gap) return;
    kept = ts;
    const name = String(idx++).padStart(6, '0') + '.jpg';
    fs.writeFileSync(path.join(OUT, name), Buffer.from(f.data, 'base64'));
    frames.push({ name, ts });
  });
  const save = () => {
    fs.writeFileSync(path.join(OUT, 'take.json'), JSON.stringify({ window: { width: W, height: H, scale: SCALE }, model: MODEL, stretches, marks, threads, frames }));
  };
  // A frame comes only when the picture changes: move the pointer by a hair,
  // so that a stretch begins with a frame of its own.
  const kick = async () => { await page.mouse.move(cx + 0.6, cy); await sleep(30); await page.mouse.move(cx, cy); await sleep(30); };
  // From here on the footage is called `name`; `fps` frames a second are kept
  // (a wait for a model needs few, a click or typing needs them all).
  async function film(name, fps = 30) {
    if (!casting) {
      await client.send('Page.startScreencast', { format: 'jpeg', quality: 92, maxWidth: Math.round(W * SCALE), maxHeight: Math.round(H * SCALE), everyNthFrame: 1 });
      casting = true;
    }
    gap = 1 / fps - 0.004; kept = 0; recording = true;
    stretches.push({ name, at: now() });
    save();   // what is filmed so far can be looked at, and survives a failure
    log('film:', name);
    await kick();
  }
  const cut = () => { if (recording) stretches.push({ name: '', at: now() }); recording = false; };
  async function mark(name, loc) {
    const box = await first(loc).boundingBox().catch(() => null);
    if (box) marks.push({ name, at: now(), box });
    return box;
  }
  const finish = async () => {
    cut();
    if (casting) await client.send('Page.stopScreencast').catch(() => {});
    casting = false;
    save();
  };
  const go = async (view) => {
    await page.goto(URL + (view ? '?view=' + view : ''), { waitUntil: 'domcontentloaded' });
    await sleep(4500);
    await page.mouse.move(cx, cy);
  };

  try {
    await page.goto(URL, { waitUntil: 'domcontentloaded' });
    await sleep(3000);
    await page.mouse.move(cx, cy);
    fs.mkdirSync(OUT, { recursive: true });

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

      log('warm-up: a standing task');
      await click(chatInput(), { post: 200 });
      await type(WARM_TASK, 4);
      await page.keyboard.press('Enter');
      await settled('the standing task', { startsWithin: 20000 });
      await debug('warm-task');

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

    // ---- the take ---------------------------------------------------------------
    if (PARTS.includes('take')) {
      await toChat();
      // The introduction's questions come up a moment after the conversation
      // and take the keyboard: without this the request is typed into them.
      const intro = page.getByText('Skip introduction').first();
      if (await intro.waitFor({ state: 'visible', timeout: 8000 }).then(() => true, () => false)) {
        await click(intro, { post: 800 });
        await intro.waitFor({ state: 'hidden', timeout: 8000 }).catch(() => {});
      }
      await moveTo(W * 0.5, H * 0.5, 300);
      await wheel(4000, 400, 10);
      await sleep(700);
      const known = new Set((await missions()).map((m) => m.id));
      const threadsBefore = await threadIds();
      const agentsBefore = await agentLinks().count();
      const fresh = async () => ((await api('api/agent-chat/sessions?surface=agent'))?.sessions || []).filter((t) => !threadsBefore.has(t.session_id));

      // 1. The request.
      await mark('stage', '[data-testid="chat-stage"]');
      await mark('panel', '[data-testid="assistant-panel"]');
      await mark('composer', '[data-testid="composer-row"]');
      await film('ask');
      await sleep(700);
      await click(chatInput(), { post: 300 });
      await type(ASK);
      await sleep(350);
      await mark('composer-typed', '[data-testid="composer-row"]');
      await sleep(350);
      await page.keyboard.press('Enter');
      await moveTo(Math.min(W - 40, cx + 150), cy - 70, 500);

      // 2. Dodaios looks into it and starts the coding agents. A second one
      //    that has not come a while after the first is not waited for.
      await film('answer', 12);
      let firstSeen = 0;
      await until(async () => {
        const n = (await fresh()).length;
        if (n && !firstSeen) firstSeen = Date.now();
        return n >= 2 || (n === 1 && Date.now() - firstSeen > 75000);
      }, 'Dodaios to start the coding agents');
      for (const t of await fresh()) threads.push({ id: t.session_id, title: t.title, model: t.model, cwd: t.cwd });
      log('agents:', threads.map((t) => `${t.model} in ${path.basename(t.cwd || '')}`).join(', '));
      // Its message names the agents a moment after it started them.
      const agentLink = agentLinks().nth(agentsBefore);
      const named = await agentLink.waitFor({ state: 'visible', timeout: 20000 }).then(() => true, () => false);
      await film('started');
      await sleep(named ? 900 : 300);

      // 3. Into an agent's thread while it works: by its name in the message,
      //    or by its line under "Recent activity" beside the conversation.
      if (named) {
        await mark('agent-link', agentLink);
        await click(agentLink, { pre: 320, post: 400 });
      } else {
        await mark('agent-link', `[data-testid="assistant-activity-${threads[0].id}"]`);
        await click(`[data-testid="assistant-activity-${threads[0].id}"]`, { pre: 420, post: 600 });
      }
      await threadInput().waitFor({ state: 'visible' });
      await film('thread', 15);
      await mark('thread-input', threadInput());
      await mark('thread-tree', '[data-testid="ide-thread-tree"]');
      await moveTo(W * 0.78, H * 0.4, 600);
      await sleep(4500);
      // The other agents' threads, then back to the first: each is seen at work.
      const row = (t) => `[data-testid="thread-row-${t.id}"]`;
      const name = (t) => path.basename(t.cwd || t.id);
      const stillRunning = async (t) => (await fresh()).some((f) => f.session_id === t.id && f.running);
      const byWork = [];
      for (const t of threads) (await stillRunning(t) ? byWork.unshift(t) : byWork.push(t));
      for (const t of byWork) {
        if (!(await page.locator(row(t)).first().isVisible().catch(() => false))) continue;
        await film('thread-' + name(t), 15);
        await click(row(t), { pre: 260, post: 500 });
        await moveTo(W * 0.78, H * 0.42, 500);
        // A thread that is still at work is watched until it is done, at most a minute.
        const deadline = Date.now() + 60000;
        await sleep(4500);
        while (await stillRunning(t) && Date.now() < deadline) await sleep(500);
        await sleep(1200);
      }
      await film('working', 6);
      await threadDone(threadsBefore, 'the agents');
      await film('done');
      await sleep(1200);

      // 4. Their changes: the review of everything a thread changed.
      for (const t of threads) {
        if (!(await page.locator(row(t)).first().isVisible().catch(() => false))) continue;
        await film('review-' + name(t));
        await click(row(t), { pre: 260, post: 900 });
        await click('[aria-label="Review changes"]', { post: 1200 });
        const dialog = page.locator('[role=dialog]').last();
        if (!(await mark('review-' + name(t), dialog))) continue;
        await moveTo(W * 0.62, H * 0.6, 500);
        await sleep(1800);
        await wheel(260, 6, 16);
        await sleep(1800);
        const close = dialog.getByRole('button', { name: /Close/ }).first();
        if (await close.isVisible().catch(() => false)) await click(close, { post: 500 });
        else { await page.keyboard.press('Escape'); await sleep(500); }
      }

      // 5. Back to Dodaios, which checks the results itself and reports.
      await film('to-chat');
      await toChat();
      await moveTo(W * 0.5, H * 0.5, 500);
      await film('report-wait', 8);
      await settled('the report', { startsWithin: 20000 });
      await film('report');
      await mark('stage-report', '[data-testid="chat-stage"]');
      await sleep(3000);

      // 6. The dashboard, as an artifact. The app shows the build, then the page.
      await film('ask-artifact');
      await click(chatInput(), { post: 250 });
      await type(ASK_ARTIFACT);
      await sleep(450);
      await page.keyboard.press('Enter');
      await moveTo(Math.min(W - 40, cx + 150), cy - 70, 500);
      await film('build-wait', 6);
      const inArtifacts = () => /view=visualization/.test(page.url());
      let ready = false;
      const build = built(known, 'the dashboard').then(() => { ready = true; });
      await until(async () => ready || inArtifacts() || !(await chatInput().isVisible().catch(() => false)), 'the build to start', BUILD_WAIT);
      await film('build', 2);
      await moveTo(W * 0.56, H * 0.62, 600);
      await build;
      if (!inArtifacts()) {
        // The app did not open it by itself: open the newest one in Artifacts.
        await film('open-artifact');
        await click('[data-testid="sidebar-shortcut-visualization"]', { post: 1200 });
        await click(page.getByText(/dashboard|invoices/i).first(), { post: 1200 });
      }
      await onArtifact().waitFor({ state: 'visible', timeout: 30000 });
      await film('artifact');
      await mark('artifact', onArtifact());
      await sleep(2600);
      await wheel(420, 7, 16);
      await sleep(1800);
      await wheel(420, 7, 16);
      await sleep(2200);
      await film('last-word', 4);
      await settled('the last word', { startsWithin: 5000 });
      await film('home');
      await toChat();
      await moveTo(W * 0.52, H * 0.5, 500);
      await sleep(2500);
      cut();
      save();
    }

    // ---- the tour: a few seconds of other parts of the app -------------------
    if (PARTS.includes('tour')) {
      const hold = async (name, ms, during) => { await film(name); if (during) await during(); await sleep(ms); cut(); };

      await go('plugins');
      await moveTo(W * 0.68, H * 0.6, 300);
      await hold('tour-plugins', 1200, async () => { await sleep(900); await wheel(330, 5, 16); });

      await go('memory');
      for (const [text, kind] of MEMORIES) {
        if (await page.getByText(text).count()) continue;
        await page.getByText('New', { exact: true }).first().click(); await sleep(600);
        await page.keyboard.type(text, { delay: 5 });
        await page.locator('[role=dialog]').last().getByText(kind, { exact: true }).first().click(); await sleep(200);
        await page.getByText('Remember', { exact: true }).first().click();
        await page.getByText('New memory').waitFor({ state: 'hidden' }); await sleep(900);
      }
      await go('memory');
      await moveTo(W * 0.5, H * 0.75, 300);
      await hold('tour-memory', 1500, async () => {
        await sleep(900);
        await click(page.getByText(MEMORIES[2][0]).first(), { post: 900 });
      });

      await go('pets');
      await moveTo(W * 0.8, H * 0.3, 300);
      await hold('tour-pets', 3500);

      await go('agentic-ide');
      await hold('tour-models', 2600, async () => {
        await sleep(700);
        await click('[aria-label="Coding agent and model"]', { post: 700 });
        await mark('model-picker', '[role=menu]:visible, [role=listbox]:visible, [role=dialog]:visible');
      });
      await page.keyboard.press('Escape');

      await go('');
      await moveTo(W * 0.5, H * 0.55, 300);
      await mark('panel-end', '[data-testid="assistant-panel"]');
      await hold('tour-home', 2500, async () => { await sleep(600); await moveTo(W * 0.82, H * 0.6, 900); });
    }

    await finish();
    log('frames', frames.length, 'stretches', stretches.filter((st) => st.name).length);
  } catch (e) {
    await finish().catch(() => {});
    await page.screenshot({ path: path.join(OUT, 'failure.png') }).catch(() => {});
    console.error('FAILED:', e.message.split('\n').slice(0, 6).join('\n'));
    process.exitCode = 1;
  }
  await browser.close();
})();
