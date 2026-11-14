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
// The script works in three parts. The first two are not filmed.
//
//   setup    the first-run dialog, and both sample projects connected
//   warm-up  a morning's work, so the footage shows a workspace that is in
//            use: two threads in the Agentic IDE and a request to Dodaios
//            that it hands to a coding agent
//   take     four requests to Dodaios, one after the other: a question it
//            answers from a file on the computer, a page it builds from the
//            answer, a task it keeps looking after, and a fault it checks
//            and hands to a coding agent. The agent's thread in the Agentic
//            IDE is opened from the conversation and its changes are
//            reviewed; then back to Dodaios, which reports.
//
// Two more parts film the shorter clip at the top of the README instead of
// the take ("setup,warmup,warmup-agents,agents"):
//
//   warmup-agents  two more requests to Dodaios, not filmed: how long its
//                  answers should be, and a short report on the day so far
//   agents         one request to Dodaios: review the open pull requests of
//                  a project, a coding agent for each. The agents come up
//                  beside the conversation; the first one's thread is opened
//                  in the Agentic IDE and two more beside it, so three are
//                  seen at work at once. Back in the conversation Dodaios
//                  answers with a report, which is opened. It needs the
//                  third project (DEMO_PR_REPO of demo-instance.sh,
//                  DEMO_PR_PROJECT here).
//
// DEMO_PARTS names the parts to run (default "setup,warmup,take").
//
// The window is 1200 x 675 at a device scale of 2.4, so the frames are
// 2880 x 1620: the video is 1920 x 1080 and stays sharp when the picture
// moves in a little. DEMO_WINDOW and DEMO_SCALE change that: the agents clip
// is filmed at a scale of 1.6, which gives 1920 x 1080 without moving in, and
// at 60 frames a second (DEMO_FPS) where something moves. The pointer is
// drawn into the page because a headless browser has none.
//
// The folder gets the frames and take.json: every frame's time, the
// stretches of footage in order (a name and the time each began), and the
// moments and places the cut needs. render.cjs cuts the video from that.
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
// The folder of the project with open pull requests, when demo-instance.sh
// was started with DEMO_PR_REPO. The setup connects it as a third project.
const PR_PROJECT = process.env.DEMO_PR_PROJECT || '';
// An installed browser to use instead of Playwright's own ("chrome", "msedge").
const BROWSER = process.env.DEMO_BROWSER || '';
if (!OUT) { console.error('usage: node record.cjs <output folder>'); process.exit(2); }
const [W, H] = (process.env.DEMO_WINDOW || '1200x675').split('x').map(Number);
const SCALE = Number(process.env.DEMO_SCALE || 2.4);
// How good the filmed pictures are (JPEG quality). At 60 frames a second a
// take is two to three times the size, and 86 is still clean in a video.
const JPEG = Number(process.env.DEMO_JPEG || 92);
const MODEL_WAIT = 6 * 60 * 1000;
const BUILD_WAIT = 20 * 60 * 1000;   // an artifact took two to nine minutes
const TYPING = 30;   // milliseconds a key, the same everywhere

const WARM_THREADS = [
  ['trailhead', WARM_MODELS[0], 'Add a --json flag to the plan command that prints the estimate as JSON, with a test.'],
  ['ledger', WARM_MODELS[1] || WARM_MODELS[0], 'Where is the billing export read, and what happens when a line has no quantity? A few lines, change nothing.'],
];
const WARM_AGENT = 'Put a Haiku agent on trailhead: describe the --json flag in the README, in two lines.';
// Two more requests in the warm-up of the agents clip. The first says how
// long an answer should be, as a person would have said long ago. Together
// they use enough different tools that the app's "Tool Dabbler" achievement
// (five different tools) comes up here and not as a toast in the clip.
const WARM_AGENTS = [
  'Remind me at 5 pm to check the month-end numbers. And from now on, answer me in two sentences unless I ask for more.',
  'What did the agents change in trailhead and ledger today? Put it in a short report.',
];
// The take's four requests to Dodaios.
const ASK_NUMBERS = 'How much did we invoice in October, by customer? The billing export is in the ledger project.';
const ASK_PAGE = 'Make that a page I can send to finance.';
// No time of day in it: with one, Dodaios sets up a routine instead of taking the task on itself.
const ASK_TASK = "Look after ledger's tests for me and tell me if one fails.";
const ASK_FIX = `Brightwell Dental says invoice INV-2041 is one cent too high. Check it, then put a ${MODEL_SPOKEN} agent on the fix. No commit, I want to review it.`;

// The agents clip's one request. It names the model of the agents, so the
// clip does not depend on which one a new thread starts on.
const AGENTS_MODEL = process.env.DEMO_AGENTS_MODEL || 'Sonnet';
const ASK_REVIEW = `Review the new PRs in ${PR_PROJECT || 'the project'}, one ${AGENTS_MODEL} agent per PR, and write me a report.`;
// How many of the agents' threads are opened beside the first one, each in a
// column of its own. Three columns need a window at least 1140 wide.
const AGENTS_BESIDE = 2;
// How many agents the request will start (the number of open pull requests).
// Dodaios may start them many seconds apart: without the number, a moment in
// which the first ones are done and the last ones not yet started looks like
// the end of their work.
const AGENTS_EXPECTED = Number(process.env.DEMO_AGENTS || 0);
// Frames a second for the agents clip's stretches with movement in them.
const AGENTS_FPS = Number(process.env.DEMO_FPS || 60);

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
    return idleSince / 1000;
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
  const frames = [];
  const stretches = [];   // the footage in order: a name, when it began
  const marks = [];       // a moment or a place the cut needs: a name, when, and where in the window
  const threads = [];     // the coding agents the take started
  const typed = {};       // for each request, when each of its keys was pressed
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
    fs.writeFileSync(path.join(OUT, 'take.json'), JSON.stringify({ window: { width: W, height: H, scale: SCALE }, model: MODEL, stretches, marks, threads, typed, frames }));
  };
  // A frame comes only when the picture changes: move the pointer by a hair,
  // so that a stretch begins with a frame of its own.
  const kick = async () => { await page.mouse.move(cx + 0.6, cy); await sleep(30); await page.mouse.move(cx, cy); await sleep(30); };
  // From here on the footage is called `name`; `fps` frames a second are kept
  // (a wait for a model needs few, a click or typing needs them all).
  async function film(name, fps = 30) {
    if (!casting) {
      await client.send('Page.startScreencast', { format: 'jpeg', quality: JPEG, maxWidth: Math.round(W * SCALE), maxHeight: Math.round(H * SCALE), everyNthFrame: 1 });
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
      // The project with the pull requests first: the thread list shows the
      // projects in this order, and its threads must not fall below the window.
      if (PR_PROJECT) await connectProject(PR_PROJECT);
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

      log('warm-up done, the window shows', page.url());
    }

    // ---- more warm-up before the agents clip, not recorded -------------------------
    if (PARTS.includes('warmup-agents')) {
      log('warm-up: two more requests before the agents clip');
      await toChat();
      const intro = page.getByText('Skip introduction').first();
      if (await intro.waitFor({ state: 'visible', timeout: 5000 }).then(() => true, () => false)) await click(intro, { post: 800 });
      for (const [i, request] of WARM_AGENTS.entries()) {
        await click(chatInput(), { post: 200 });
        await type(request, 4);
        await page.keyboard.press('Enter');
        await settled('warm-up request ' + (i + 1), { startsWithin: 20000 });
      }
      await debug('warm-requests');
      const unlocked = ((await api('api/board/achievements'))?.items || []).filter((a) => a.unlocked || a.unlocked_at).map((a) => a.id);
      log('achievements so far:', unlocked.join(', ') || 'none');
      if (!unlocked.includes('tool_dabbler')) log('warning: "Tool Dabbler" is still to come and may show as a toast in the clip');
    }

    // ---- what the take and the agents clip share ---------------------------------
    const moment = (name, at = now()) => marks.push({ name, at, box: null });
    // To the conversation with Dodaios, at its newest message.
    async function openChat() {
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
    }
    // A request, typed and sent. The footage after it is "wait-<name>".
    async function ask(name, text, fps = 30) {
      await film('ask-' + name, fps);
      await sleep(600);
      await click(chatInput(), { post: 280 });
      // The time of every key: the cut plays the typing at an even pace,
      // whatever the computer was busy with meanwhile.
      const keys = [];
      for (const ch of text) { await page.keyboard.type(ch); keys.push(now()); await sleep(TYPING); }
      typed[name] = keys;
      await sleep(500);
      moment('sent-' + name);
      await page.keyboard.press('Enter');
      await moveTo(Math.min(W - 40, cx + 130), cy - 95, 550);
      await film('wait-' + name, 12);
    }

    // ---- the take ---------------------------------------------------------------
    if (PARTS.includes('take')) {
      await openChat();
      const known = new Set((await missions()).map((m) => m.id));
      const threadsBefore = await threadIds();
      const fresh = async () => ((await api('api/agent-chat/sessions?surface=agent'))?.sessions || []).filter((t) => !threadsBefore.has(t.session_id));
      await mark('stage', '[data-testid="chat-stage"]');
      await mark('panel', '[data-testid="assistant-panel"]');

      // 1. A question Dodaios answers from a file on the computer.
      await ask('numbers', ASK_NUMBERS);
      moment('done-numbers', await settled('the numbers', { startsWithin: 20000 }));
      await film('answer-numbers');
      await sleep(1300);
      // The answer is longer than the window: up to its chart, the way a reader would.
      await moveTo(W * 0.4, H * 0.45, 500);
      await wheel(-190, 6, 16);
      await sleep(2600);

      // 2. The answer as a page. Dodaios writes a small page itself, and the
      //    conversation gets a card of it; a larger one is built by a worker,
      //    and the app shows the build and then the page.
      const cards = () => page.locator('[data-testid="page-card"]').count();
      const cardsBefore = await cards();
      await ask('page', ASK_PAGE);
      const inArtifacts = () => /view=visualization/.test(page.url());
      const building = async () => (await missions()).some((m) => !known.has(m.id));
      await until(async () => (await cards()) > cardsBefore || inArtifacts() || (await building()), 'the page', BUILD_WAIT);
      if (inArtifacts() || (await building())) {
        moment('build-shown');
        await film('build', 2);
        await moveTo(W * 0.56, H * 0.62, 600);
        await built(known, 'the page');
        if (inArtifacts()) {
          await onArtifact().waitFor({ state: 'visible', timeout: 30000 });
          await film('page');
          await mark('page', onArtifact());
          await sleep(2400);
          await wheel(380, 7, 16);
          await sleep(2200);
          await film('page-word', 4);
          await settled('the word about the page', { startsWithin: 6000 });
          await film('to-chat');
          await toChat();
          await moveTo(W * 0.5, H * 0.55, 500);
          await sleep(600);
        } else {
          await film('page-word', 6);
          moment('done-page', await settled('the word about the page', { startsWithin: 8000 }));
        }
      } else {
        moment('done-page', await settled('the word about the page', { startsWithin: 8000 }));
      }
      // The card of the page in the conversation, and the page behind it.
      const lookAtPage = async () => {
        await onArtifact().waitFor({ state: 'visible', timeout: 30000 });
        await film('page');
        await mark('page', onArtifact());
        await moveTo(W * 0.58, H * 0.6, 600);
        await sleep(2000);
        await wheel(430, 7, 16);
        await sleep(2400);
        await film('to-chat');
        await toChat();
        await moveTo(W * 0.5, H * 0.55, 500);
        await sleep(600);
      };
      const card = page.locator('[data-testid="page-card"]:visible').last();
      if (await card.waitFor({ state: 'visible', timeout: 8000 }).then(() => true, () => false)) {
        await film('card');
        await sleep(900);
        // Its answer below pushed the card half out of the window: back up to it.
        const box = await card.boundingBox();
        if (box && box.y < 60) { await moveTo(W * 0.4, H * 0.45, 500); await wheel(box.y - 64, 6, 16); }
        await mark('card', card);
        await sleep(2400);
        if (!stretches.some((st) => st.name === 'page')) {
          await click(page.locator('[data-testid="page-card-preview"]:visible').last(), { pre: 300, post: 600 });
          await lookAtPage();
        }
      }

      // 3. Something it keeps looking after: the panel beside the conversation lists it.
      await ask('task', ASK_TASK);
      moment('done-task', await settled('the standing task', { startsWithin: 20000 }));
      await film('answer-task');
      const standing = page.locator('[data-testid^="assistant-standing-task-"]:visible').first();
      if (await standing.isVisible().catch(() => false)) {
        await mark('standing', standing);
        await sleep(700);
        await point(standing, { ms: 800 });
      }
      await sleep(2600);

      // 4. A fault: Dodaios checks it and hands the fix to a coding agent.
      await ask('fix', ASK_FIX);
      await until(async () => (await fresh()).length >= 1, 'Dodaios to start the coding agent');
      for (const t of await fresh()) threads.push({ id: t.session_id, title: t.title, model: t.model, cwd: t.cwd });
      log('agent:', threads.map((t) => `${t.model} in ${path.basename(t.cwd || '')}`).join(', '));
      //    Into the agent's thread while it works, by its line under "Recent
      //    activity" beside the conversation. (Dodaios's message names the agent
      //    too, but only when the agent is nearly done.)
      const entry = first(`[data-testid="assistant-activity-${threads[0].id}"]`);
      await entry.waitFor({ state: 'visible', timeout: 20000 });
      await film('started');
      await sleep(1200);
      await mark('agent-link', entry);
      moment('clicked');
      await click(entry, { pre: 380, post: 400 });
      await threadInput().waitFor({ state: 'visible' });
      await film('thread', 15);
      await mark('thread-input', threadInput());
      await moveTo(W * 0.8, H * 0.4, 600);
      await threadDone(threadsBefore, 'the fix');
      moment('agent-done');
      await film('done');
      await sleep(1800);

      //    Its changes: the review of everything the thread changed.
      await film('review');
      await click('[aria-label="Review changes"]', { pre: 300, post: 1200 });
      const dialog = page.locator('[role=dialog]').last();
      if (await mark('review', dialog)) {
        await moveTo(W * 0.62, H * 0.6, 500);
        await sleep(2200);
        await wheel(240, 6, 16);
        await sleep(2400);
        const close = dialog.getByRole('button', { name: /Close/ }).first();
        if (await close.isVisible().catch(() => false)) await click(close, { post: 500 });
        else { await page.keyboard.press('Escape'); await sleep(500); }
      }

      // 5. Back to Dodaios, which checks the result itself and reports.
      await film('to-report');
      await toChat();
      await moveTo(W * 0.5, H * 0.5, 500);
      await film('report-wait', 8);
      moment('done-report', await settled('the report', { startsWithin: 20000 }));
      await film('report');
      await sleep(3500);
      cut();
      save();
    }

    // ---- the agents clip ----------------------------------------------------------
    if (PARTS.includes('agents')) {
      if (!PR_PROJECT) throw new Error('the agents clip needs DEMO_PR_PROJECT, the folder of the project with open pull requests');
      // The Agentic IDE loads its projects when it is first opened in a window:
      // open it once before the film, so the clip does not show it filling up.
      await click('[data-testid="surface-ide"]', { post: 800 });
      await first('[data-testid^="thread-project-"]').waitFor({ state: 'visible', timeout: 20000 });
      await sleep(1500);
      await openChat();
      const threadsBefore = await threadIds();
      const fresh = async () => ((await api('api/agent-chat/sessions?surface=agent'))?.sessions || []).filter((t) => !threadsBefore.has(t.session_id));
      const byStart = (a, b) => (a.created_ms || 0) - (b.created_ms || 0);
      const bubbles = () => page.locator('[data-testid="lead-bubble"]').count();
      const cards = () => page.locator('[data-testid="page-card"]').count();
      const bubblesBefore = await bubbles();
      const cardsBefore = await cards();
      await mark('stage', '[data-testid="chat-stage"]');

      // The clip must look like the app does on a screen. An earlier cut of it
      // looked like a slide show: filmed at 30 frames, played faster, with a
      // pointer that jumped and stood still in between. So every stretch with
      // movement in it is filmed at 60 frames a second, the cut plays it at its
      // own speed, and the pointer travels at a person's pace and keeps moving.
      const FPS = AGENTS_FPS;
      // A wait of unknown length is not worth that many frames: it is filmed
      // as a stretch of its own, which the cut leaves out.
      const hold = (name) => film('hold-' + name, 6);
      const pace = (x, y) => Math.min(1050, Math.max(430, Math.hypot(x - cx, y - cy) * 1.5));
      // The pointer's way to an element, at that pace.
      async function way(loc, { dx = 0, dy = 0 } = {}) {
        const el = first(loc);
        await el.waitFor({ state: 'visible' });
        const b = await reveal(el);
        return { el, ms: pace(b.x + b.width / 2 + dx, b.y + b.height / 2 + dy) };
      }
      const go = async (loc, opts = {}) => { const { el, ms } = await way(loc, opts); await click(el, { ms, pre: 200, ...opts }); };
      const over = async (loc, opts = {}) => { const { el, ms } = await way(loc, opts); await point(el, { ms, ...opts }); };
      const drift = async (x, y, ms) => moveTo(x, y, ms ?? pace(x, y));

      // 1. The request, and the first words of Dodaios.
      await ask('review', ASK_REVIEW, FPS);
      await until(async () => (await bubbles()) > bubblesBefore, 'the first words of Dodaios');
      moment('ack');
      await film('ack', FPS);
      await drift(W * 0.5, H * 0.52, 700);
      await sleep(500);

      // 2. The agents come up beside the conversation, under "Recent activity":
      //    the pointer goes to the first of them while the next ones arrive.
      await film('starting', 20);
      await until(async () => (await fresh()).length >= 1, 'Dodaios to start the first coding agent');
      const leader = (await fresh()).sort(byStart)[0];
      const entry = first(`[data-testid="assistant-activity-${leader.session_id}"]`);
      await entry.waitFor({ state: 'visible', timeout: 20000 });
      moment('first-agent');
      await film('agents-in', FPS);
      await sleep(350);
      await over(entry);
      await sleep(1300);

      // 3. Into the Agentic IDE by that one: its thread opens while it works.
      await film('to-ide', FPS);
      await go(entry, { pre: 120, post: 500 });
      await threadInput().waitFor({ state: 'visible' });
      await mark('thread-input', threadInput());
      await drift(W * 0.5, H * 0.42);
      await sleep(700);
      await hold('ide');

      // 4. Two more of them beside it, each in a column of its own, by the
      //    "Open side by side" of a thread's menu: one that is still at work each
      //    time, the one started first, which has the most to show.
      const shown = [leader.session_id];
      for (let i = 0; i < AGENTS_BESIDE; i++) {
        let next = null;
        await until(async () => {
          const others = (await fresh()).filter((t) => !shown.includes(t.session_id));
          next = others.filter((t) => t.running).sort(byStart)[0] || others.sort(byStart)[0] || null;
          return Boolean(next);
        }, 'another coding agent', MODEL_WAIT, 200);
        shown.push(next.session_id);
        const row = first(`[data-testid="thread-row-${next.session_id}"]`);
        await row.waitFor({ state: 'visible', timeout: 15000 });
        await film('beside-' + (i + 1), FPS);
        await over(row);
        await sleep(200);
        // The row shows its menu button at its right end only while the
        // pointer is over it, and the list moves when a thread gets its title:
        // aim by the row, and look whether the menu came.
        const item = page.getByText('Open side by side', { exact: true }).first();
        for (let attempt = 0; attempt < 3; attempt++) {
          const at = await row.boundingBox();
          await moveTo(at.x + at.width - 17, at.y + at.height / 2, 300);
          await sleep(150);
          await press();
          if (await item.waitFor({ state: 'visible', timeout: 1500 }).then(() => true, () => false)) break;
        }
        await go(item, { pre: 150, post: 300 });
        const column = first(`[data-testid="thread-column-${next.session_id}"]`);
        await column.waitFor({ state: 'visible', timeout: 10000 });
        const at = await column.boundingBox();
        await drift(at.x + at.width / 2, H * 0.42);
        await sleep(350);
        await hold('beside-' + (i + 1));
      }

      // 5. All of them at work: the pointer goes from one column to the next.
      await film('watching', FPS);
      const columns = [];
      for (const id of shown) {
        const box = await first(id === leader.session_id ? '[data-testid="thread-column-main"]' : `[data-testid="thread-column-${id}"]`).boundingBox().catch(() => null);
        if (box) columns.push(box);
      }
      columns.sort((a, b) => a.x - b.x);
      for (const box of [...columns].reverse()) {
        await drift(box.x + box.width / 2, H * 0.4, 1500);
        await sleep(500);
      }
      await film('finishing', 20);
      await until(async () => { const all = await fresh(); return all.length >= Math.max(1, AGENTS_EXPECTED) && all.every((t) => !t.running); }, 'the coding agents to finish');
      // The thread list hears of it a moment later: wait until none of its rows turns any more.
      const turning = () => page.locator('[data-testid^="thread-row-"] .animate-spin').count();
      for (const limit = Date.now() + 20000; Date.now() < limit && (await turning()) > 0;) await sleep(200);
      for (const t of await fresh()) threads.push({ id: t.session_id, title: t.title, model: t.model, cwd: t.cwd });
      log('agents:', threads.length, threads.map((t) => t.model).join(', '));
      moment('agents-done');
      await film('done', FPS);
      await drift(W * 0.62, H * 0.5, 1100);
      await sleep(500);

      // 6. Back to Dodaios, which reads the reviews and writes the report.
      await film('to-chat', FPS);
      await go('[data-testid="surface-dodaios"]', { post: 600 });
      await chatInput().waitFor({ state: 'visible' });
      await drift(W * 0.4, H * 0.6);
      await film('wait-report', 8);
      await until(async () => (await cards()) > cardsBefore, 'the report');
      moment('card');
      await film('report', FPS);
      // Its answer stands under the card of the report: there once the text
      // after the card has stood still for a moment.
      const answer = () => page.evaluate(() => {
        const card = [...document.querySelectorAll('[data-testid="page-card"]')].pop();
        if (!card) return '';
        return [...document.querySelectorAll('[data-testid="lead-bubble"]')]
          .filter((b) => card.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING)
          .map((b) => b.innerText).join('\n');
      });
      let text = '', still = Date.now();
      await until(async () => {
        const t = await answer();
        if (t !== text) { text = t; still = Date.now(); }
        return text.length > 40 && Date.now() - still > 1200;
      }, 'the answer of Dodaios', MODEL_WAIT, 150);
      moment('answer');
      await sleep(1900);

      // 7. The report itself, opened from its card. The answer under the card
      //    has pushed it up: wheel it well into the conversation first, so the
      //    click does not land on the window's caption above it.
      await film('open-report', FPS);
      const preview = page.locator('[data-testid="page-card-preview"]:visible').last();
      for (let i = 0; i < 240; i++) {
        const box = await preview.boundingBox();
        if (!box) break;
        const mid = box.y + box.height / 2;
        if (mid >= 120 && mid <= H - 160) break;
        await page.mouse.wheel(0, mid < 120 ? -9 : 9);
        await sleep(14);
      }
      await sleep(250);
      await go(preview, { post: 400 });
      await onArtifact().waitFor({ state: 'visible', timeout: 30000 });
      await film('page', FPS);
      await mark('page', onArtifact());
      await drift(W * 0.6, H * 0.6);
      await sleep(800);
      await wheel(560, 3, 14);   // down to its figures and its table, at an even pace
      await sleep(1300);
      cut();
      save();
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
