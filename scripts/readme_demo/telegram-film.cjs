// Films the desktop side of the README's Telegram clip: the conversation with
// the assistant in a throwaway instance while a message sent from Telegram
// arrives in it and the assistant answers. Nobody sits at the desk in this
// clip, so nothing is driven: no pointer, no typing. The page is opened at
// the conversation's newest message and filmed.
//
//   node scripts/readme_demo/telegram-film.cjs <output folder>
//
// telegram_take.py starts it and steers it with one line at a time on the
// standard input; each command is answered with one line on the output:
//
//   arm            start the screencast and keep only the last few seconds
//                  in memory (nothing is written yet)        -> "armed"
//   record <t>     keep the footage from <t> minus DEMO_PREROLL on (t in
//                  seconds since the epoch), on disk          -> "recording"
//   scrub <file>   more "text=replacement" lines to replace in the picture
//                  from now on (a Telegram sender's names)    -> "scrubbed <n>"
//   mark <name>    note a moment (now) in take.json            -> "marked"
//   look <name>    a screenshot for whoever checks the script, never
//                  footage                                     -> "looked"
//   reload         open the conversation again (after the instance was
//                  restarted)                                  -> "ready"
//   stop           stop filming, write take.json and quit      -> "stopped"
//
// It prints "ready" once the conversation is on screen, and "error <text>"
// when something fails.
//
//   DEMO_URL         the instance (default http://127.0.0.1:47993/)
//   DEMO_WINDOW      the window in CSS pixels (default 1200x675)
//   DEMO_SCALE       device scale (default 1.6: frames of 1920 x 1080)
//   DEMO_JPEG        quality of the filmed pictures (default 90)
//   DEMO_FPS         frames a second kept at most (default 60)
//   DEMO_PREROLL     seconds kept from before the moment `record` names (default 2)
//   DEMO_BROWSER     an installed browser instead of Playwright's own ("chrome")
//   DEMO_SCRUB_FILE  a file of "text=replacement" lines: words that must not
//                    be in the picture. Only what is drawn changes: no input or
//                    change event is sent, so the app never sees or saves it.
//
// The page helpers are copied from nodes-plugins-common.cjs (which copied
// them from record.cjs), without the drawn pointer, so a change there does not
// move this clip. take.json gets every frame's time; telegram_take.py turns
// the frames into a video and cuts it.
const { chromium } = require('playwright');
const fs = require('fs');
const os = require('os');
const path = require('path');
const readline = require('readline');

const OUT = process.argv[2];
if (!OUT) { console.error('usage: node telegram-film.cjs <output folder>'); process.exit(2); }
const URL = (process.env.DEMO_URL || 'http://127.0.0.1:47993/').replace(/\/?$/, '/');
const [W, H] = (process.env.DEMO_WINDOW || '1200x675').split('x').map(Number);
const SCALE = Number(process.env.DEMO_SCALE || 1.6);
const JPEG = Number(process.env.DEMO_JPEG || 90);
const FPS = Number(process.env.DEMO_FPS || 60);
const PREROLL = Number(process.env.DEMO_PREROLL || 2);
const BROWSER = process.env.DEMO_BROWSER || '';

// The computer's own name and the home folder and account name of whoever
// records never belong in the picture.
const host = os.hostname();
const BASE_SCRUB = [
  [host, 'MacBook-Pro'],
  [host.replace(/\.(local|lan|home|fritz\.box)$/i, ''), 'MacBook-Pro'],
  [os.homedir(), '/Users/alex'],
  [os.userInfo().username, 'alex'],
].filter(([from], i, all) => from && from.length > 3 && all.findIndex(([f]) => f === from) === i);

function readPairs(file) {
  if (!file || !fs.existsSync(file)) return [];
  return fs.readFileSync(file, 'utf8').split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && line.includes('='))
    .map((line) => [line.slice(0, line.indexOf('=')), line.slice(line.indexOf('=') + 1)])
    .filter(([from]) => from.length >= 2);
}

// A name may be written in another case, without its accents, or with
// German umlauts written out: every spelling is matched, without regard to case.
const spellings = (s) => [...new Set([
  s,
  s.normalize('NFD').replace(/[̀-ͯ]/g, ''),
  s.replace(/ä/g, 'ae').replace(/ö/g, 'oe').replace(/ü/g, 'ue').replace(/Ä/g, 'Ae').replace(/Ö/g, 'Oe').replace(/Ü/g, 'Ue').replace(/ß/g, 'ss'),  // i18n-allow: umlaut spellings to match, not German text
])];
// Longest first: a whole name is replaced before its parts.
const expand = (pairs) => pairs.flatMap(([from, to]) => spellings(from).map((v) => [v, to]))
  .filter(([from], i, all) => all.findIndex(([f]) => f.toLowerCase() === from.toLowerCase()) === i)
  .sort((a, b) => b[0].length - a[0].length);

// Runs in every document of the window. `window.__demoScrub(pairs)` adds pairs
// later; what is already drawn is then gone through again.
const PAGE_HELPERS = (pairs) => `(() => {
  let to = new Map(), all = null, one = null;
  const fix = (s) => (all && one.test(s) ? s.replace(all, (m) => to.get(m.toLowerCase()) ?? m) : s);
  const walk = (n) => {
    if (n.nodeType === 3) {
      if (n.parentElement && n.parentElement.isContentEditable) return;
      const v = fix(n.nodeValue); if (v !== n.nodeValue) n.nodeValue = v; return;
    }
    if (n.nodeType === 11) { for (const c of n.childNodes) walk(c); return; }
    if (n.nodeType !== 1) return;
    for (const a of ['title', 'aria-label', 'placeholder', 'alt']) { const v = n.getAttribute(a); if (v) { const f = fix(v); if (f !== v) n.setAttribute(a, f); } }
    for (const c of n.childNodes) walk(c);
    if (n.shadowRoot) walk(n.shadowRoot);
  };
  const known = [];
  window.__demoMasked = 0;
  window.__demoScrub = (more) => {
    for (const p of more) if (!known.some(([a]) => a.toLowerCase() === p[0].toLowerCase())) known.push(p);
    known.sort((a, b) => b[0].length - a[0].length);
    to = new Map(known.map(([a, b]) => [a.toLowerCase(), b]));
    // Whole words only: a short first name must not change part of another word.
    const source = known.map(([a]) => a.replace(/[.*+?^\${}()|[\\]\\\\]/g, '\\\\$&')).join('|');
    const word = source ? '(?<![\\\\p{L}\\\\p{N}_])(?:' + source + ')(?![\\\\p{L}\\\\p{N}_])' : '';
    all = word ? new RegExp(word, 'giu') : null;
    one = word ? new RegExp(word, 'iu') : null;
    if (document.documentElement) walk(document.documentElement);
    return known.length;
  };
  new MutationObserver((ms) => { for (const m of ms) { if (m.type === 'characterData') walk(m.target); for (const n of m.addedNodes) walk(n); } })
    .observe(document, { subtree: true, childList: true, characterData: true });
  // A field's text is no text node: it is replaced where the page sets it.
  for (const proto of [HTMLInputElement.prototype, HTMLTextAreaElement.prototype]) {
    const d = Object.getOwnPropertyDescriptor(proto, 'value');
    if (!d || !d.get || !d.set) continue;
    Object.defineProperty(proto, 'value', {
      configurable: true, enumerable: d.enumerable,
      get() { return d.get.call(this); },
      set(v) { d.set.call(this, typeof v === 'string' ? fix(v) : v); },
    });
  }
  // A rich editor that shows such a value is hidden while it does (a mark on
  // its parent, outside the editor, which watches its own nodes).
  setInterval(() => {
    if (!one) return;
    for (const ed of document.querySelectorAll('[contenteditable]:not([contenteditable="false"])')) {
      const host = ed.parentElement;
      if (!host) continue;
      const leaks = one.test(ed.textContent || '');
      if (leaks && !host.hasAttribute('data-demo-mask')) { host.setAttribute('data-demo-mask', ''); window.__demoMasked++; }
      else if (!leaks && host.hasAttribute('data-demo-mask')) host.removeAttribute('data-demo-mask');
    }
  }, 120);
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
  window.__demoScrub(${JSON.stringify(pairs)});
})();`;

const say = (line) => process.stdout.write(line + '\n');
const now = () => Date.now() / 1000;

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({
    ...(BROWSER ? { channel: BROWSER } : {}),
    args: [`--force-device-scale-factor=${SCALE}`, `--window-size=${W},${H}`, '--force-color-profile=srgb', '--hide-scrollbars'],
  });
  const ctx = await browser.newContext({ viewport: null, colorScheme: 'dark', timezoneId: 'Europe/Berlin', locale: 'en-US' });
  const startPairs = expand([...BASE_SCRUB, ...readPairs(process.env.DEMO_SCRUB_FILE)]);
  await ctx.addInitScript(PAGE_HELPERS(startPairs));
  const page = await ctx.newPage();
  page.setDefaultTimeout(20000);
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
  const sleep = (ms) => page.waitForTimeout(ms);

  // ---- screencast ---------------------------------------------------------
  let armed = false, recording = false, casting = false, kept = 0, idx = 0;
  const gap = 1 / FPS - 0.004;
  const pre = [];        // while armed: the newest frames, in memory
  const frames = [];     // on disk: a name and the time it was drawn
  const marks = [];      // a name and when
  const times = {};
  const write = (ts, data) => {
    const name = String(idx++).padStart(6, '0') + '.jpg';
    fs.writeFileSync(path.join(OUT, name), Buffer.from(data, 'base64'));
    frames.push({ name, ts });
  };
  client.on('Page.screencastFrame', (f) => {
    client.send('Page.screencastFrameAck', { sessionId: f.sessionId }).catch(() => {});
    const ts = f.metadata.timestamp;
    if (recording) {
      if (ts - kept < gap) return;
      kept = ts;
      write(ts, f.data);
    } else if (armed) {
      pre.push({ ts, data: f.data });
      // Keep the frames of the pre-roll and the newest one before them: it is
      // the picture that stood on screen when the pre-roll began.
      while (pre.length > 2 && pre[1].ts < ts - PREROLL - 1) pre.shift();
    }
  });
  const save = () => {
    fs.writeFileSync(path.join(OUT, 'take.json'), JSON.stringify({
      window: { width: W, height: H, scale: SCALE }, jpeg: JPEG, fps: FPS, preroll: PREROLL,
      url: URL, times, marks, frames,
    }));
  };
  // A frame comes only when the picture changes. This repaints one invisible
  // pixel, so that the screencast hands over the picture as it stands.
  const repaint = () => page.evaluate(() => {
    let dot = document.getElementById('__demo_repaint');
    if (!dot) {
      dot = document.createElement('div');
      dot.id = '__demo_repaint';
      Object.assign(dot.style, { position: 'fixed', left: '0', top: '0', width: '1px', height: '1px', pointerEvents: 'none', zIndex: '2147483646' });
      document.documentElement.appendChild(dot);
    }
    dot.style.background = dot.style.background === 'rgba(0, 0, 0, 0.004)' ? 'rgba(0, 0, 0, 0.002)' : 'rgba(0, 0, 0, 0.004)';
  }).catch(() => {});

  // ---- the conversation -----------------------------------------------------
  const skipIntro = async (wait) => {
    const intro = page.getByText('Skip introduction').first();
    if (await intro.waitFor({ state: 'visible', timeout: wait }).then(() => true, () => false)) {
      await intro.click();
      await intro.waitFor({ state: 'hidden', timeout: 8000 }).catch(() => {});
    }
  };
  const openChat = async () => {
    await page.goto(URL, { waitUntil: 'domcontentloaded' });
    await sleep(3000);
    await skipIntro(2500);
    const rail = page.locator('[data-testid="sidebar-shortcut-chats"]:visible').first();
    if (await rail.isVisible().catch(() => false)) await rail.click();
    else {
      const surface = page.locator('[data-testid="surface-dodaios"]:visible').first();
      if (await surface.isVisible().catch(() => false)) await surface.click();
    }
    await page.locator('[data-testid="composer-row"]').first().waitFor({ state: 'visible', timeout: 30000 });
    await skipIntro(6000);
    // Nobody is at the desk: the mouse leaves the window, so nothing shows a hover.
    await page.mouse.move(W / 2, H / 2);
    await page.mouse.move(-20, -20);
    // The conversation at its newest message; the panel beside it at its top.
    await page.evaluate(() => {
      const chat = document.querySelector('[data-testid="assistant-chat"]') || document.body;
      for (const el of chat.querySelectorAll('*')) {
        if (el.scrollHeight > el.clientHeight + 40 && /(auto|scroll)/.test(getComputedStyle(el).overflowY)) el.scrollTop = el.scrollHeight;
      }
      const panel = document.querySelector('[data-testid="assistant-panel"]');
      if (panel) panel.scrollTop = 0;
    });
    await sleep(800);
  };
  try {
    await openChat();
    times.ready = now();
    say('ready');
  } catch (e) {
    await page.screenshot({ path: path.join(OUT, 'failure.png') }).catch(() => {});
    say('error ' + String(e && e.message || e).split('\n')[0]);
    await browser.close().catch(() => {});
    process.exit(1);
  }

  // ---- commands -------------------------------------------------------------
  const lines = readline.createInterface({ input: process.stdin });
  let stopping = false;
  const stop = async () => {
    if (stopping) return;
    stopping = true;
    recording = false; armed = false;
    times.stopped = now();
    if (casting) await client.send('Page.stopScreencast').catch(() => {});
    save();
    say('stopped');
    // Closing the browser can take long; the take is written already.
    await Promise.race([browser.close().catch(() => {}), new Promise((r) => setTimeout(r, 4000))]);
    process.exit(0);
  };
  lines.on('close', stop);
  for await (const raw of lines) {
    const [cmd, ...rest] = raw.trim().split(' ');
    const arg = rest.join(' ');
    try {
      if (cmd === 'arm') {
        if (!casting) {
          await client.send('Page.startScreencast', { format: 'jpeg', quality: JPEG, maxWidth: Math.round(W * SCALE), maxHeight: Math.round(H * SCALE), everyNthFrame: 1 });
          casting = true;
        }
        armed = true;
        times.armed = now();
        // The picture as it stands, for a take that begins on a page that has not
        // changed since (the screencast hands over a frame only on a change).
        const shot = await client.send('Page.captureScreenshot', { format: 'jpeg', quality: JPEG }).catch(() => null);
        if (shot && shot.data && !pre.length) pre.push({ ts: times.armed, data: shot.data });
        await repaint();
        say('armed');
      } else if (cmd === 'record') {
        const from = (Number(arg) || now()) - PREROLL;
        times.record_from = from;
        times.recorded = now();
        // The newest frame drawn before `from` stands at `from`; the rest as drawn.
        let held = null;
        const after = [];
        for (const f of pre) { if (f.ts <= from) held = f; else after.push(f); }
        pre.length = 0;
        if (held) { kept = from; write(from, held.data); }
        for (const f of after) { if (f.ts - kept >= gap) { kept = f.ts; write(f.ts, f.data); } }
        recording = true; armed = false;
        await repaint();
        save();
        say('recording');
      } else if (cmd === 'scrub') {
        const pairs = expand(readPairs(arg));
        const counts = [];
        for (const f of page.frames()) counts.push(await f.evaluate((p) => (window.__demoScrub ? window.__demoScrub(p) : 0), pairs).catch(() => 0));
        say('scrubbed ' + Math.max(0, ...counts));
      } else if (cmd === 'mark') {
        marks.push({ name: arg, at: now() });
        say('marked');
      } else if (cmd === 'look') {
        // A screenshot would reach the screencast as a frame of another size.
        const was = recording; recording = false;
        await page.screenshot({ path: path.join(OUT, `look-${arg || 'now'}.png`), scale: 'css' }).catch(() => {});
        await sleep(60);
        recording = was;
        say('looked');
      } else if (cmd === 'reload') {
        // The instance was restarted: the conversation is opened afresh.
        await openChat();
        if (casting) await repaint();
        say('ready');
      } else if (cmd === 'stop') {
        await stop();
      } else if (cmd) {
        say('error unknown command ' + cmd);
      }
    } catch (e) {
      say('error ' + String(e && e.message || e).split('\n')[0]);
    }
  }
})();
