// A copy of nodes-plugins-common.cjs for the second Nodes clip
// (clip-nodes2-*.cjs), with closeNotice() added.
//
// What the Nodes clip and the Assistant clip of the README share: the window,
// the pointer, the typing, the filming and the questions to the app's API.
//
//   const { open } = require('./nodes-plugins-common.cjs');
//   const rig = await open('/tmp/take');
//
// It is the same way of filming as record.cjs (the helpers are copied from it,
// so that a change there does not move these clips): the real app in an
// installed or bundled Chromium, driven through its own interface, captured
// with the DevTools screencast in named stretches, with a pointer drawn into
// the page because a headless browser has none. take.json gets every frame's
// time, the stretches, the moments the cut needs and the time of every typed
// key; nodes-plugins-cut.cjs makes the video from it.
//
//   DEMO_URL      the instance (default http://127.0.0.1:47990/)
//   DEMO_WINDOW   the window in CSS pixels (default 1024x576)
//   DEMO_SCALE    device scale (default 1.875: frames of 1920 x 1080)
//   DEMO_JPEG     quality of the filmed pictures (default 93)
//   DEMO_BROWSER  an installed browser instead of Playwright's own ("chrome")
//   DEMO_SCRUB    "text=replacement,text=replacement": words that must not be
//                 in the picture (the name and the login of a GitHub account)
//   DEMO_LOCK     a folder another recorder on the same computer makes while
//                 it films, with its name in the file "owner". While the
//                 folder is there and the name is not DEMO_LOCK_OWNER, nothing
//                 is driven: every click and every typed text waits, so the
//                 other take keeps the computer to itself
const { chromium } = require('playwright');
const fs = require('fs');
const os = require('os');
const path = require('path');

const LOCK = process.env.DEMO_LOCK || '';
const LOCK_OWNER = process.env.DEMO_LOCK_OWNER || '';
const lockedOut = () => {
  if (!LOCK || !fs.existsSync(LOCK)) return false;
  try { return fs.readFileSync(path.join(LOCK, 'owner'), 'utf8').trim() !== LOCK_OWNER; } catch { return true; }
};

const URL = (process.env.DEMO_URL || 'http://127.0.0.1:47990/').replace(/\/?$/, '/');
const ORIGIN = URL.replace(/\/$/, '');
const [W, H] = (process.env.DEMO_WINDOW || '1024x576').split('x').map(Number);
const SCALE = Number(process.env.DEMO_SCALE || 1.875);
const JPEG = Number(process.env.DEMO_JPEG || 93);
const BROWSER = process.env.DEMO_BROWSER || '';
const MODEL_WAIT = 6 * 60 * 1000;
const TYPING = 34;   // milliseconds between two keys, the same everywhere

// The computer's own name, and the home folder and the account name of
// whoever records, never belong in the picture.
const host = os.hostname();
const SCRUB = [
  [host, 'MacBook-Pro'],
  [host.replace(/\.(local|lan|home|fritz\.box)$/i, ''), 'MacBook-Pro'],
  [os.homedir(), '/Users/alex'],
  [os.userInfo().username, 'alex'],
].filter(([from], i, all) => from && from.length > 3 && all.findIndex(([f]) => f === from) === i);
// DEMO_SCRUB's pairs come first and in their own order: give a whole name
// before its parts, or the part is replaced and the rest of the name stays.
SCRUB.unshift(...(process.env.DEMO_SCRUB || '').split(',').filter(Boolean)
  .map((pair) => [pair.slice(0, pair.indexOf('=')), pair.slice(pair.indexOf('=') + 1)])
  .filter(([from]) => from));

// A model that read a name from GitHub may write it in another case, without
// its accents, or with German umlauts written out: every spelling is matched,
// without regard to case.
const spellings = (s) => [...new Set([
  s,
  s.normalize('NFD').replace(/[̀-ͯ]/g, ''),
  s.replace(/ä/g, 'ae').replace(/ö/g, 'oe').replace(/ü/g, 'ue').replace(/Ä/g, 'Ae').replace(/Ö/g, 'Oe').replace(/Ü/g, 'Ue').replace(/ß/g, 'ss'),
])];
// Longest first: where two values start at the same place, the longer one
// wins (a computer's name with its ".local", a whole name before its parts).
const SCRUB_PAIRS = SCRUB.flatMap(([from, to]) => spellings(from).map((v) => [v, to]))
  .filter(([from], i, all) => all.findIndex(([f]) => f.toLowerCase() === from.toLowerCase()) === i)
  .sort((a, b) => b[0].length - a[0].length);
const SCRUB_SOURCE = SCRUB_PAIRS.map(([from]) => from.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|');
// Whether a text holds a value that must not be in the picture: for text the
// page draws on a canvas, which no page helper can change. It says yes or no
// and never which value.
const SCRUB_TEST = SCRUB_SOURCE ? new RegExp(SCRUB_SOURCE, 'i') : null;
const leaky = (text) => Boolean(SCRUB_TEST && text && SCRUB_TEST.test(String(text)));

// Runs in every document of the window, frames included. It changes only what
// is drawn: no input or change event is sent, so no page takes it for an edit.
const PAGE_HELPERS = `(() => {
  const source = ${JSON.stringify(SCRUB_SOURCE)};
  const to = new Map(${JSON.stringify(SCRUB_PAIRS)}.map(([a, b]) => [a.toLowerCase(), b]));
  const all = source ? new RegExp(source, 'gi') : null;
  const one = source ? new RegExp(source, 'i') : null;
  const fix = (s) => (all && one.test(s) ? s.replace(all, (m) => to.get(m.toLowerCase()) ?? m) : s);
  window.__demoMasked = 0;
  // Text nodes and the attributes a page shows. A rich editor's own text
  // (contenteditable) is left alone: the editor would read a change there as
  // typing. The sweep below masks such an editor instead.
  const walk = (n) => {
    if (n.nodeType === 3) {
      if (n.parentElement && n.parentElement.isContentEditable) return;
      // A stylesheet or a script is no text in the picture: replacing the
      // login "root" there turned a node page's ":root" rules into nothing.
      if (n.parentElement && /^(STYLE|SCRIPT)$/.test(n.parentElement.tagName)) return;
      const v = fix(n.nodeValue); if (v !== n.nodeValue) n.nodeValue = v; return;
    }
    if (n.nodeType !== 1) return;
    if (/^(STYLE|SCRIPT)$/.test(n.tagName)) return;
    for (const a of ['title', 'aria-label', 'placeholder', 'alt', 'value']) { const v = n.getAttribute(a); if (v) { const f = fix(v); if (f !== v) n.setAttribute(a, f); } }
    for (const c of n.childNodes) walk(c);
  };
  if (source) {
    new MutationObserver((ms) => { for (const m of ms) { if (m.type === 'characterData') walk(m.target); for (const n of m.addedNodes) walk(n); } })
      .observe(document, { subtree: true, childList: true, characterData: true });
    // A field's text is no text node: it is scrubbed where the page sets it
    // (a React-controlled field sets .value), and a sweep catches the rest.
    for (const proto of [HTMLInputElement.prototype, HTMLTextAreaElement.prototype]) {
      const d = Object.getOwnPropertyDescriptor(proto, 'value');
      if (!d || !d.get || !d.set) continue;
      Object.defineProperty(proto, 'value', {
        configurable: true, enumerable: d.enumerable,
        get() { return d.get.call(this); },
        set(v) { d.set.call(this, typeof v === 'string' ? fix(v) : v); },
      });
    }
    const sweep = () => {
      for (const f of document.querySelectorAll('input, textarea')) {
        const v = f.value;
        if (v && one.test(v)) { f.value = fix(v); window.__demoMasked++; }
      }
      // A rich editor that shows such a value is hidden while it does, by a
      // mark on its parent (outside the editor, which watches its own nodes).
      for (const ed of document.querySelectorAll('[contenteditable]:not([contenteditable="false"])')) {
        const host = ed.parentElement;
        if (!host) continue;
        const leaks = one.test(ed.textContent || '');
        if (leaks && !host.hasAttribute('data-demo-mask')) { host.setAttribute('data-demo-mask', ''); window.__demoMasked++; }
        else if (!leaks && host.hasAttribute('data-demo-mask')) host.removeAttribute('data-demo-mask');
      }
    };
    setInterval(sweep, 120);
  }
  // How much of the recording person's plan is used is nobody's business.
  const hide = () => {
    if (document.getElementById('__demo_hide') || !document.head) return;
    const st = document.createElement('style');
    st.id = '__demo_hide';
    st.textContent = '[data-testid="thread-plan-usage"], [data-demo-mask] > [contenteditable] { visibility: hidden !important; }';
    document.head.appendChild(st);
  };
  hide();
  document.addEventListener('DOMContentLoaded', hide);
  // One pointer, drawn in the window's own document. A page inside a frame
  // (a node's page) gets the mouse events itself, so it passes them on.
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
  addEventListener('pointermove', (e) => place(e.clientX, e.clientY), true);
  addEventListener('mousedown', () => squeeze(true), true);
  addEventListener('pointerdown', () => squeeze(true), true);
  addEventListener('mouseup', () => squeeze(false), true);
  addEventListener('pointerup', () => squeeze(false), true);
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

// A state-changing call must come from the app's own origin.
async function send(method, route, body) {
  const res = await fetch(URL + route.replace(/^\//, ''), {
    method,
    headers: { Origin: ORIGIN, ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) throw new Error(`${method} ${route}: HTTP ${res.status} ${typeof data === 'string' ? data.slice(0, 200) : JSON.stringify(data).slice(0, 200)}`);
  return data;
}
const api = async (route) => {
  try { return await (await fetch(URL + route.replace(/^\//, ''))).json(); } catch { return null; }
};

async function open(OUT) {
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
  // A picture of the window for whoever writes the script, never for the clip.
  // The screencast would pass it on as a frame of another size: no frame is
  // kept while it is taken.
  const look = async (name) => {
    const was = recording; recording = false;
    await page.screenshot({ path: path.join(OUT, `look-${name}.png`), scale: 'css' }).catch(() => {});
    await sleep(60);
    recording = was;
  };
  // Wait while another recorder films (DEMO_LOCK).
  async function clear() {
    if (!lockedOut()) return;
    log('another recorder films: waiting');
    while (lockedOut()) await new Promise((r) => setTimeout(r, 2000));
    log('going on');
  }

  // ---- pointer ----------------------------------------------------------
  let cx = W * 0.55, cy = H * 0.6;
  const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
  // A person's pace: about a second across the window, never a jump.
  const pace = (x, y) => Math.min(1050, Math.max(430, Math.hypot(x - cx, y - cy) * 1.5));
  // Time-based, so a move lasts as long as asked whatever one step costs.
  async function moveTo(x, y, ms) {
    const dur = ms ?? pace(x, y);
    const sx = cx, sy = cy, start = Date.now();
    for (;;) {
      const t = Math.min(1, (Date.now() - start) / dur);
      const k = ease(t);
      await page.mouse.move(sx + (x - sx) * k, sy + (y - sy) * k);
      if (t >= 1) break;
      await sleep(6);
    }
    cx = x; cy = y;
  }
  // The same way at an even speed: a drag, where easing would look like a throw.
  async function glide(x, y, ms) {
    const sx = cx, sy = cy, start = Date.now();
    for (;;) {
      const t = Math.min(1, (Date.now() - start) / ms);
      const k = 0.5 - Math.cos(Math.PI * t) / 2;
      await page.mouse.move(sx + (x - sx) * k, sy + (y - sy) * k);
      if (t >= 1) break;
      await sleep(6);
    }
    cx = x; cy = y;
  }
  const press = async () => { await page.mouse.down(); await sleep(70); await page.mouse.up(); };
  const first = (loc) => (typeof loc === 'string' ? page.locator(loc).first() : loc);
  // Wheel the element into the window the way a person would, then return its box.
  async function reveal(el, top = 60) {
    for (let i = 0; i < 80; i++) {
      const b = await el.boundingBox();
      if (!b) { await sleep(100); continue; }
      const mid = b.y + b.height / 2;
      if (mid >= top && mid <= H - 26) return b;
      const px = Math.min(W - 60, Math.max(60, b.x + b.width / 2));
      if (Math.abs(cx - px) > 6 || Math.abs(cy - H * 0.55) > 160) await moveTo(px, H * 0.55, 380);
      await page.mouse.wheel(0, mid > H - 26 ? 40 : -40);
      await sleep(40);
    }
    return el.boundingBox();
  }
  // `top`: the highest place a target may stand without being wheeled down
  // first (below the window's caption; a dialog's close button stands higher).
  async function point(loc, { dx = 0, dy = 0, ms, top = 60 } = {}) {
    const el = first(loc);
    await el.waitFor({ state: 'visible' });
    const b = await reveal(el, top);
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
    await clear();
    await point(loc, opts);
    await sleep(opts.pre ?? 160);
    await press();
    await sleep(opts.post ?? 350);
  }
  // A click at a place of the window (a canvas has no elements to name).
  async function clickAt(x, y, opts = {}) {
    await clear();
    await moveTo(x, y, opts.ms);
    await sleep(opts.pre ?? 160);
    await press();
    await sleep(opts.post ?? 350);
  }
  async function wheel(total, step = 3, pause = 14) {
    for (let done = 0; Math.abs(done) < Math.abs(total); done += step) {
      await page.mouse.wheel(0, Math.sign(total) * step);
      await sleep(pause);
    }
  }

  // ---- what the app is doing, asked of its API ---------------------------
  const busy = async () => {
    const lead = await api('api/agent-chat/lead');
    const threads = await api('api/agent-chat/sessions?surface=agent');
    return Boolean(lead?.running) || (threads?.sessions || []).some((s) => s.running);
  };
  // A turn that could not reach its model says so in the conversation. Such a
  // take is of no use: stop at once instead of waiting for an answer.
  async function noFailedTurn() {
    const failure = page.getByText(/API Error|Failed to authenticate|hit your .* limit|usage limit/i).first();
    if (await failure.isVisible().catch(() => false)) throw new Error('a turn failed: ' + (await failure.innerText()).slice(0, 160));
  }
  async function until(done, what, timeout = MODEL_WAIT, every = 250) {
    const end = Date.now() + timeout;
    while (!(await done())) {
      await noFailedTurn();
      if (Date.now() > end) throw new Error(`waited ${Math.round(timeout / 1000)} s in vain for ${what}`);
      await sleep(every);
    }
  }
  // Nothing runs, and nothing has for `calm` ms.
  async function settled(what, { calm = 5000, startsWithin = 30000, timeout = MODEL_WAIT } = {}) {
    const t0 = Date.now();
    while (!(await busy()) && Date.now() - t0 < startsWithin) await sleep(300);
    let idleSince = 0;
    for (;;) {
      if (Date.now() - t0 > timeout) throw new Error(`still working after ${Math.round(timeout / 1000)} s (${what})`);
      await noFailedTurn();
      if (await busy()) idleSince = 0;
      else if (!idleSince) idleSince = Date.now();
      else if (Date.now() - idleSince >= calm) break;
      await sleep(400);
    }
    log('settled:', what);
    return idleSince / 1000;
  }

  // ---- the app's own controls ----------------------------------------------
  // The Agentic IDE stays mounted behind the chat, so only a visible field counts.
  const chatInput = () => page.locator('[data-testid="composer-row"] [contenteditable=true]:visible, [data-testid="composer-row"] textarea:visible').first();
  const bubbles = () => page.locator('[data-testid="lead-bubble"]').count();
  const btn = (name) => page.getByRole('button', { name });
  const rail = (id) => page.locator(`[data-testid="sidebar-shortcut-${id}"]:visible`).first();
  // The conversation at its newest message, without a wheel in the picture.
  // Only the conversation scrolls: the assistant panel beside it stays at its
  // top, where its header says what the assistant is doing.
  const toEnd = () => page.evaluate(() => {
    const chat = document.querySelector('[data-testid="assistant-chat"]') || document.body;
    for (const el of chat.querySelectorAll('*')) {
      if (el.scrollHeight > el.clientHeight + 40 && /(auto|scroll)/.test(getComputedStyle(el).overflowY)) el.scrollTop = el.scrollHeight;
    }
    const panel = document.querySelector('[data-testid="assistant-panel"]');
    if (panel) panel.scrollTop = 0;
  });

  // ---- screencast -----------------------------------------------------------
  let idx = 0; let recording = false; let gap = 0; let kept = 0; let casting = false;
  const frames = [];
  const stretches = [];   // the footage in order: a name, when it began
  const marks = [];       // a moment the cut needs: a name, when
  const typed = {};       // for each typed text, when each of its keys was pressed
  const notes = {};       // whatever else the notes of a clip should say
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
    fs.writeFileSync(path.join(OUT, 'take.json'), JSON.stringify({ window: { width: W, height: H, scale: SCALE }, jpeg: JPEG, stretches, marks, typed, notes, frames }));
  };
  // A frame comes only when the picture changes: move the pointer by a hair,
  // so that a stretch begins with a frame of its own.
  const kick = async () => { await page.mouse.move(cx + 0.6, cy); await sleep(30); await page.mouse.move(cx, cy); await sleep(30); };
  // From here on the footage is called `name`; `fps` frames a second are kept
  // (a wait for a model needs few, a click or typing needs them all).
  async function film(name, fps = 60) {
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
  // A wait of unknown length: a stretch of its own with few frames, which the cut leaves out.
  const hold = (name) => film('hold-' + name, 5);
  // Within a stretch: from now on keep `fps` frames a second (a long wait is
  // filmed with few, and with all of them around the moments the cut shows).
  const rate = (fps) => { gap = 1 / fps - 0.004; };
  const cut = () => { if (recording) stretches.push({ name: '', at: now() }); recording = false; };
  const moment = (name, at = now()) => marks.push({ name, at });
  // How often a page had to mask or rewrite a field or an editor that showed a
  // value that must not be in the picture, over all its frames. Not zero: look
  // at those frames before the take is used.
  const masked = async () => {
    let n = 0;
    for (const f of page.frames()) n += Number(await f.evaluate(() => window.__demoMasked || 0).catch(() => 0)) || 0;
    return n;
  };
  const finish = async () => {
    cut();
    if (casting) await client.send('Page.stopScreencast').catch(() => {});
    casting = false;
    notes.masked = Math.max(notes.masked || 0, await masked().catch(() => 0));
    save();
  };
  // A text typed key by key. The time of every key is written down: the cut
  // plays the typing at an even pace, whatever the computer was busy with.
  async function type(name, text, delay = TYPING) {
    await clear();
    const keys = [];
    for (const ch of text) { await page.keyboard.type(ch); keys.push(now()); await sleep(delay); }
    if (name) typed[name] = keys;
  }

  // The administrator notice (the app runs as root here): closed with a real
  // click on its own close button. A new browser context forgets that it was
  // closed, so every script closes it before anything is filmed.
  async function closeNotice() {
    const x = page.locator('button[aria-label="Hide this notice"]:visible').first();
    if (await x.waitFor({ state: 'visible', timeout: 6000 }).then(() => true, () => false)) {
      await click(x, { post: 500 });
      log('closed the administrator notice');
    }
  }

  return {
    closeNotice,
    OUT, URL, W, H, SCALE, browser, ctx, page, client, log, sleep, look, clear,
    pos: () => [cx, cy], pace, moveTo, glide, press, first, reveal, point, click, clickAt, wheel,
    api, send, busy, until, settled, noFailedTurn, masked, leaky,
    chatInput, bubbles, btn, rail, toEnd,
    film, hold, rate, cut, moment, finish, type, notes, now, save,
    frames, stretches,
    async fail(e) {
      await finish().catch(() => {});
      await page.screenshot({ path: path.join(OUT, 'failure.png') }).catch(() => {});
      console.error('FAILED:', String(e && e.message || e).split('\n').slice(0, 6).join('\n'));
      process.exitCode = 1;
    },
    async close() { await finish().catch(() => {}); await browser.close(); },
  };
}

module.exports = { open, api, send, leaky, URL, ORIGIN, W, H, SCALE, TYPING };
