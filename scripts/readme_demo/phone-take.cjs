// Films the footage of the PHONE clip of the README: the phone app (the
// installable web app the desktop serves at /m/), paired with a throwaway
// instance, in a phone-sized browser. One request is typed on the phone, the
// assistant waits for the person's yes on an approval card, a tap on Allow
// lets it go on, and its answer arrives.
//
//   node scripts/readme_demo/phone-take.cjs <output folder>
//
// It is the same way of filming as record.cjs and nodes-plugins-common.cjs
// (the helpers are copied, so a change there does not move this clip): the
// real app in an installed or bundled Chromium, driven through its own
// interface, captured with the DevTools screencast in named stretches. A
// phone has no pointer, so a tap is drawn the way a phone shows touches when
// asked to: a round mark where the finger is, for as long as it touches.
//
// The window is 390 x 844 CSS pixels at a device scale of 2 (the frames are
// 780 x 1688), emulated as a phone: touch, a phone's user agent, the page's
// own viewport tag. Chrome draws no window narrower than 500 pixels, so the
// browser window is wider and the phone's screen is emulated inside it; the
// screencast films only that screen.
//
// Two parts (PHONE_PARTS, default "take"):
//
//   pair   not filmed: the desktop makes a pairing code (as Settings ->
//          Phone does) and the phone app opens with it, the way the code's
//          link opens it. The device token the phone gets is kept in
//          PHONE_TOKEN (a file outside the repository) for the take.
//   take   the phone app opens on the conversation that is already there,
//          the thumb drags it back to what was said at the desk and down
//          again, the request is typed and sent, every approval card that comes is
//          allowed with a tap, and the answer is filmed. A wait for the
//          model is a stretch of its own with few frames ("hold-..."), which
//          the cut leaves out.
//
//   DEMO_URL      the instance (default http://127.0.0.1:47992/)
//   PHONE_TOKEN   the file the device token is kept in (required)
//   PHONE_ASK     the request typed on the phone
//   PHONE_MODE    the permission mode the conversation is set to before the
//                 take, through the desktop's own API (default "ask": "Ask
//                 before acting", in which an action waits for a card)
//   PHONE_DRY     1: a rehearsal of the take up to the typed request, which
//                 is taken out again instead of sent (no model works)
//   DEMO_JPEG     quality of the filmed pictures (default 92)
//   DEMO_BROWSER  an installed browser instead of Playwright's own ("chrome")
//   DEMO_SCRUB    "text=replacement,...": words that must not be in the picture
//
// The folder gets the frames and take.json: every frame's time, the
// stretches in order, the moments the cut needs and the time of every typed
// key. edit-phone.js is the cut; phone-render.cjs makes the video.
const { chromium } = require('playwright');
const fs = require('fs');
const os = require('os');
const path = require('path');

const OUT = process.argv[2];
if (!OUT) { console.error('usage: node phone-take.cjs <output folder>'); process.exit(2); }
const URL = (process.env.DEMO_URL || 'http://127.0.0.1:47992/').replace(/\/?$/, '/');
const ORIGIN = URL.replace(/\/$/, '');
const PARTS = (process.env.PHONE_PARTS || 'take').split(',');
const TOKEN_FILE = process.env.PHONE_TOKEN || '';
const ASK = process.env.PHONE_ASK || 'Yes, fix it before the invoices go out.';
const MODE = process.env.PHONE_MODE || 'ask';
const JPEG = Number(process.env.DEMO_JPEG || 92);
const BROWSER = process.env.DEMO_BROWSER || '';
const W = 390, H = 844, SCALE = 2;
const UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1';
const TOKEN_KEY = 'dodaios.mobile.token';   // src/mobile/api.ts
const MODEL_WAIT = 6 * 60 * 1000;
const TYPING = 70;   // milliseconds between two keys while filming; the cut evens them out
const MAX_CARDS = 4;

if (!TOKEN_FILE) { console.error('PHONE_TOKEN must name the file the device token is kept in'); process.exit(2); }

// The computer's own name and the home folder of whoever records never
// belong in the picture.
const host = os.hostname();
const SCRUB = [
  [host, 'MacBook-Pro'],
  [host.replace(/\.(local|lan|home|fritz\.box)$/i, ''), 'MacBook-Pro'],
  [os.homedir(), '/Users/alex'],
].filter(([from], i, all) => from && from.length > 3 && all.findIndex(([f]) => f === from) === i);
SCRUB.unshift(...(process.env.DEMO_SCRUB || '').split(',').filter(Boolean)
  .map((pair) => [pair.slice(0, pair.indexOf('=')), pair.slice(pair.indexOf('=') + 1)])
  .filter(([from]) => from));

// Runs in the phone app's document before the app does.
const PAGE_HELPERS = (token) => `(() => {
  ${token ? `try { localStorage.setItem(${JSON.stringify(TOKEN_KEY)}, ${JSON.stringify(token)}); } catch {}` : ''}
  const pairs = ${JSON.stringify(SCRUB)};
  const fix = (s) => { for (const [a, b] of pairs) if (s.includes(a)) s = s.split(a).join(b); return s; };
  const walk = (n) => {
    if (n.nodeType === 3) { const v = fix(n.nodeValue); if (v !== n.nodeValue) n.nodeValue = v; return; }
    if (n.nodeType !== 1) return;
    for (const a of ['title', 'aria-label', 'placeholder', 'alt']) { const v = n.getAttribute(a); if (v) { const f = fix(v); if (f !== v) n.setAttribute(a, f); } }
    for (const c of n.childNodes) walk(c);
  };
  if (pairs.length) {
    new MutationObserver((ms) => { for (const m of ms) { if (m.type === 'characterData') walk(m.target); for (const n of m.addedNodes) walk(n); } })
      .observe(document, { subtree: true, childList: true, characterData: true });
    // The value of a field is no text node: what a field shows is rewritten
    // in place, for the picture only (no input or change event is sent).
    const fixValue = (el) => {
      if (!el || typeof el.value !== 'string' || !el.value) return;
      const v = fix(el.value);
      if (v === el.value) return;
      const s = el.selectionStart, e = el.selectionEnd;
      el.value = v;
      try { el.setSelectionRange(s, e); } catch { /* not a text field */ }
    };
    addEventListener('input', (e) => fixValue(e.target), true);
    setInterval(() => { for (const el of document.querySelectorAll('input, textarea')) fixValue(el); }, 50);
  }
  // A touch, drawn where the finger is while it touches the glass. The
  // place follows the finger at once; only the mark itself fades and
  // shrinks, so it never travels from one tap to the next.
  const install = () => {
    if (document.getElementById('__demo_touch')) return;
    const place = document.createElement('div');
    place.id = '__demo_touch';
    Object.assign(place.style, {
      position: 'fixed', left: '0', top: '0', width: '0', height: '0', pointerEvents: 'none',
      zIndex: '2147483647', transform: 'translate(-200px,-200px)',
    });
    const mark = document.createElement('div');
    Object.assign(mark.style, {
      position: 'absolute', left: '-22px', top: '-22px', width: '44px', height: '44px', borderRadius: '50%',
      background: 'rgba(255,255,255,0.30)', border: '2px solid rgba(255,255,255,0.75)', boxSizing: 'border-box',
      opacity: '0', transform: 'scale(0.6)',
    });
    place.appendChild(mark);
    document.documentElement.appendChild(place);
    const at = (e) => {
      const p = e.touches && e.touches[0] || e.changedTouches && e.changedTouches[0];
      if (p) place.style.transform = 'translate(' + p.clientX + 'px,' + p.clientY + 'px)';
    };
    addEventListener('touchstart', (e) => {
      at(e);
      mark.style.transition = 'none'; mark.style.opacity = '0'; mark.style.transform = 'scale(0.6)';
      void mark.offsetWidth;   // start the fade from nothing, whatever the last touch left
      mark.style.transition = 'opacity 60ms ease-out, transform 90ms ease-out';
      mark.style.opacity = '1'; mark.style.transform = 'scale(1)';
    }, { capture: true, passive: true });
    addEventListener('touchmove', at, { capture: true, passive: true });
    const up = () => {
      mark.style.transition = 'opacity 220ms ease-in, transform 220ms ease-in';
      mark.style.opacity = '0'; mark.style.transform = 'scale(0.8)';
    };
    addEventListener('touchend', up, { capture: true, passive: true });
    addEventListener('touchcancel', up, { capture: true, passive: true });
  };
  if (document.documentElement) install();
  document.addEventListener('DOMContentLoaded', install);
})();`;

// A state-changing call to the desktop's API must come from the app's own origin.
async function send(method, route, body) {
  const res = await fetch(URL + route.replace(/^\//, ''), {
    method,
    headers: { Origin: ORIGIN, ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) throw new Error(`${method} ${route}: HTTP ${res.status} ${String(text).slice(0, 200)}`);
  return data;
}
const api = async (route) => {
  try { return await (await fetch(URL + route.replace(/^\//, ''))).json(); } catch { return null; }
};

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const token = fs.existsSync(TOKEN_FILE) ? fs.readFileSync(TOKEN_FILE, 'utf8').trim() : '';
  if (PARTS.includes('take') && !token && !PARTS.includes('pair')) throw new Error(`no device token in ${TOKEN_FILE}: run the "pair" part first`);
  const browser = await chromium.launch({
    ...(BROWSER ? { channel: BROWSER } : {}),
    args: [`--force-device-scale-factor=${SCALE}`, '--window-size=500,900', '--force-color-profile=srgb', '--hide-scrollbars'],
  });
  const ctx = await browser.newContext({
    viewport: { width: W, height: H }, deviceScaleFactor: SCALE, isMobile: true, hasTouch: true,
    userAgent: UA, colorScheme: 'dark', locale: 'en-US', timezoneId: 'Europe/Berlin',
  });
  const page = await ctx.newPage();
  page.setDefaultTimeout(15000);
  const client = await ctx.newCDPSession(page);
  const started = Date.now();
  const log = (...a) => console.log(`[${((Date.now() - started) / 1000).toFixed(1).padStart(6)}s]`, ...a);
  const sleep = (ms) => page.waitForTimeout(ms);
  const look = async (name) => { await page.screenshot({ path: path.join(OUT, `look-${name}.png`) }).catch(() => {}); };

  // ---- screencast -----------------------------------------------------------
  let idx = 0; let recording = false; let gap = 0; let kept = 0; let casting = false;
  const frames = [];
  const stretches = [];   // the footage in order: a name, when it began
  const marks = [];       // a moment the cut needs: a name, when
  const typed = {};       // for each typed text, when each of its keys was pressed
  const notes = {};       // what the take was: the request, the cards, the answer
  const now = () => Date.now() / 1000;
  // A frame comes only when the picture changes, and a phone has no pointer
  // that would change it at the start of a stretch. So the last frame a
  // slow stretch let pass is kept aside: when the next stretch begins it is
  // written after all, with its own time, and the picture on screen at that
  // moment is never lost.
  let passed = null;
  const keep = (f) => {
    const name = String(idx++).padStart(6, '0') + '.jpg';
    fs.writeFileSync(path.join(OUT, name), Buffer.from(f.data, 'base64'));
    frames.push({ name, ts: f.metadata.timestamp });
  };
  const flush = () => { if (passed) { keep(passed); passed = null; } };
  client.on('Page.screencastFrame', (f) => {
    client.send('Page.screencastFrameAck', { sessionId: f.sessionId }).catch(() => {});
    const ts = f.metadata.timestamp;
    if (!recording) return;
    if (ts - kept < gap) { passed = f; return; }
    passed = null;
    kept = ts;
    keep(f);
  });
  const save = () => {
    fs.writeFileSync(path.join(OUT, 'take.json'), JSON.stringify({ window: { width: W, height: H, scale: SCALE }, jpeg: JPEG, stretches, marks, typed, notes, frames }));
  };
  async function film(name, fps = 60) {
    if (!casting) {
      await client.send('Page.startScreencast', { format: 'jpeg', quality: JPEG, maxWidth: W * SCALE, maxHeight: H * SCALE, everyNthFrame: 1 });
      casting = true;
    }
    flush();
    gap = 1 / fps - 0.004; kept = 0; recording = true;
    stretches.push({ name, at: now() });
    save();
    log('film:', name);
  }
  // A wait of unknown length: a stretch of its own with few frames, which the cut leaves out.
  const hold = (name) => film('hold-' + name, 5);
  const moment = (name, at = now()) => marks.push({ name, at });
  const finish = async () => {
    flush();
    if (recording) stretches.push({ name: '', at: now() });
    recording = false;
    if (casting) await client.send('Page.stopScreencast').catch(() => {});
    casting = false;
    save();
  };

  // ---- the finger -----------------------------------------------------------
  // A tap: the finger rests on the glass for a moment, as a thumb does.
  async function tapAt(x, y, holdMs = 120) {
    await client.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y, radiusX: 11, radiusY: 11, force: 1 }] });
    await sleep(holdMs);
    await client.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  }
  async function tap(locator, { dy = 0, post = 300 } = {}) {
    const el = typeof locator === 'string' ? page.locator(locator).first() : locator;
    await el.waitFor({ state: 'visible' });
    const b = await el.boundingBox();
    if (!b) throw new Error('nothing to tap');
    // Not the dead centre: a thumb lands a little below and beside it.
    await tapAt(Math.round(b.x + b.width * 0.52), Math.round(b.y + b.height * 0.56 + dy));
    await sleep(post);
  }
  // A drag of the thumb: it speeds up and slows down as a thumb does, and it
  // comes to rest before it lifts, so the list stops where the thumb stopped
  // instead of flying on.
  async function drag(x, y0, y1, ms) {
    const point = (y) => ({ x, y: Math.round(y), radiusX: 11, radiusY: 11, force: 1 });
    await client.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [point(y0)] });
    const start = Date.now();
    for (;;) {
      const t = Math.min(1, (Date.now() - start) / ms);
      await client.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [point(y0 + (y1 - y0) * (0.5 - Math.cos(Math.PI * t) / 2))] });
      if (t >= 1) break;
      await sleep(8);
    }
    await sleep(110);
    await client.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  }
  async function type(name, text, delay = TYPING) {
    const keys = [];
    for (const ch of text) { await page.keyboard.type(ch); keys.push(now()); await sleep(delay); }
    if (name) typed[name] = keys;
  }

  // ---- what the conversation is doing --------------------------------------
  const rowIds = () => page.locator('[data-timeline] > li').evaluateAll((els) => els.map((e) => e.getAttribute('data-id') || ''));
  const openCards = () => page.locator('[data-approve][data-decision="allow"]:visible');
  const leadRunning = async () => Boolean((await api('api/agent-chat/lead'))?.running);
  // A turn that failed, or a question only the desktop can answer, ends the take.
  async function noTrouble() {
    const err = page.locator('.row-notice.is-error').last();
    if (await err.isVisible().catch(() => false)) {
      const id = await err.getAttribute('data-id');
      if (!before.has(id)) throw new Error('the turn failed: ' + (await err.innerText()).slice(0, 200));
    }
    const q = page.locator('.row-card.is-open .card-hint').last();
    if (await q.isVisible().catch(() => false)) throw new Error('a question card came, which the phone cannot answer');
  }
  async function until(done, what, timeout = MODEL_WAIT, every = 200) {
    const end = Date.now() + timeout;
    while (!(await done())) {
      await noTrouble();
      if (Date.now() > end) throw new Error(`waited ${Math.round(timeout / 1000)} s in vain for ${what}`);
      await sleep(every);
    }
  }
  let before = new Set();

  try {
    // ---- pair: not filmed ----------------------------------------------------
    if (PARTS.includes('pair')) {
      log('pair');
      await ctx.addInitScript(PAGE_HELPERS(''));
      const issued = await send('POST', 'api/mobile/pair/code');
      await page.goto(`${URL}m/#pair=${issued.code}`, { waitUntil: 'domcontentloaded' });
      await page.locator('.bar-title').waitFor({ state: 'visible', timeout: 20000 });
      const kept = await page.evaluate((k) => localStorage.getItem(k), TOKEN_KEY);
      if (!kept) throw new Error('the phone app did not keep a device token');
      fs.writeFileSync(TOKEN_FILE, kept + '\n', { mode: 0o600 });
      log('paired as', await page.locator('.bar-title').innerText(), '- token kept in', TOKEN_FILE);
      await look('paired');
    }

    // ---- take ------------------------------------------------------------------
    if (PARTS.includes('take')) {
      const tok = fs.readFileSync(TOKEN_FILE, 'utf8').trim();
      if (!PARTS.includes('pair')) await ctx.addInitScript(PAGE_HELPERS(tok));
      if (MODE) {
        const lead = await api('api/agent-chat/lead');
        if (!lead?.session_id) throw new Error('no lead conversation');
        if (lead.running) throw new Error('the lead conversation is working: wait until it is idle');
        if (lead.permission_mode !== MODE) {
          await send('PATCH', `api/agent-chat/sessions/${lead.session_id}`, { permission_mode: MODE });
          log('permission mode:', lead.permission_mode, '->', MODE);
        }
        notes.model = lead.model; notes.permission_mode = MODE;
      }
      await page.goto(`${URL}m/`, { waitUntil: 'domcontentloaded' });
      await page.locator('.bar-title').waitFor({ state: 'visible', timeout: 20000 });
      await page.locator('[data-timeline] > li').first().waitFor({ state: 'visible' });
      await sleep(2500);
      before = new Set(await rowIds());
      notes.rows_before = before.size;
      notes.request = ASK;
      log('the phone shows', before.size, 'rows');
      await look('before');

      // The phone in the hand: a look back at what was said at the desk and
      // down again, then the request.
      const wrap = page.locator('.timeline-wrap');
      const scrolled = () => wrap.evaluate((el) => Math.round(el.scrollHeight - el.scrollTop - el.clientHeight));
      await film('open', 60);
      await sleep(500);
      moment('look');
      await drag(262, 330, 600, 760);
      notes.looked_back_px = await scrolled();
      await sleep(420);
      await drag(250, 610, 300, 640);
      await sleep(300);
      if ((await scrolled()) > 40) throw new Error(`the conversation did not come back down (${await scrolled()} px above its end)`);
      moment('looked');
      await tap('textarea[name="text"]', { post: 450 });
      moment('typing');
      await type('ask', ASK);
      await sleep(420);
      if (process.env.PHONE_DRY) {
        // A rehearsal: everything but sending. The text is taken out again.
        await page.locator('textarea[name="text"]').fill('');
        await page.evaluate(() => document.activeElement && document.activeElement.blur());
        await finish();
        log('rehearsal: looked back', notes.looked_back_px, 'px; frames', frames.length);
        return;
      }
      moment('send');
      await tap('[data-send]', { post: 0 });
      // The request in the conversation, "Working..." under the title.
      await until(async () => (await rowIds()).some((id) => !before.has(id) && id.startsWith('u-')), 'the request in the timeline', 20000, 50);
      moment('sent');
      await sleep(1600);

      // Every card that comes is allowed: read for a moment, then a tap.
      // The answer is on the phone when its row is there and the line under
      // the title no longer says "Working..." (the app's live dot keeps the
      // colour of its first paint, so it cannot tell).
      const answerShown = async () => {
        const ids = await rowIds();
        const answered = ids.some((id) => !before.has(id) && id.startsWith('a-'));
        const status = (await page.locator('[data-status]').innerText().catch(() => 'x')).trim();
        return answered && !status && !(await leadRunning());
      };
      const cards = [];
      for (let n = 1; ; n++) {
        // A card that came while the last one settled is on screen already:
        // the footage goes straight on. Otherwise the wait is left out.
        if (!(await openCards().count())) {
          await hold('wait-' + n);
          let outcome = '';
          await until(async () => {
            if (await openCards().count()) { outcome = 'card'; return true; }
            if (await answerShown()) { outcome = 'answer'; return true; }
            return false;
          }, n === 1 ? 'a card or the answer' : 'the next card or the answer');
          if (outcome === 'answer') break;
        }
        if (n > MAX_CARDS) throw new Error(`more than ${MAX_CARDS} cards: not a clip`);
        const button = openCards().first();
        const id = await button.getAttribute('data-approve');
        const card = page.locator(`[data-timeline] > li[data-id="ap-${id}"]`);
        const text = await card.innerText().catch(() => '');
        cards.push(text.replace(/\s+/g, ' ').trim());
        log('card', n + ':', cards[cards.length - 1].slice(0, 200));
        await film('card-' + n, 60);
        await sleep(1700);
        moment('allow-' + n);
        await tap(card.locator('[data-decision="allow"]'), { post: 0 });
        await until(async () => (await card.locator('.card-decided').count()) > 0, 'the card to settle', 20000, 50);
        moment('allowed-' + n);
        // "Allowed" for a moment; the next card or the answer may come meanwhile.
        const end = Date.now() + 1500;
        while (Date.now() < end && !(await openCards().count())) await sleep(50);
        if (await openCards().count()) moment('next-' + n);
      }
      notes.cards = cards;
      // The answer: the phone polls every few seconds, so it is on screen now.
      await film('answer', 60);
      moment('answer');
      await sleep(3400);
      const ids = await rowIds();
      notes.rows_after = ids.length;
      notes.answer = await page.locator('.row-assistant .bubble').last().innerText().catch(() => '');
      log('answer:', notes.answer.slice(0, 240));
      await finish();
      await look('after');
      log('frames', frames.length, 'stretches', stretches.filter((s) => s.name).map((s) => s.name).join(', '));
    }
    await finish();
  } catch (e) {
    await finish().catch(() => {});
    await page.screenshot({ path: path.join(OUT, 'failure.png') }).catch(() => {});
    console.error('FAILED:', String(e && e.message || e).split('\n').slice(0, 6).join('\n'));
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();
