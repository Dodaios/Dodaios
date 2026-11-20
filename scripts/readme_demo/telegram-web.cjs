// The phone side of the README's Telegram clip without a phone in anyone's hand:
// Telegram's own web app (Telegram Web K, https://web.telegram.org/k/) in a
// phone-sized Chrome, signed in to the maintainer's Telegram account once with a
// QR code. telegram_take.py drives it with --web-phone.
//
//   node telegram-web.cjs login                 a small window with Telegram's QR code:
//                                               scan it once with Telegram on the phone
//                                               (Settings > Devices > Link Desktop Device)
//   node telegram-web.cjs status                prints "signed-in" or "signed-out"
//   node telegram-web.cjs newbot <file> [name]  a new bot made with @BotFather; its token
//                                               goes into <file> (mode 0600), never to the
//                                               output; prints "bot @<username>"
//   node telegram-web.cjs film <bot> <folder>   the chat with @<bot>, filmed, steered on stdin
//   node telegram-web.cjs logout                signs this web session out of Telegram and
//                                               removes the browser profile
//
// The profile is DEMO_TG_PROFILE (default ~/Library/Application Support/
// dodaios-demo/telegram-web), a folder only the account can read. It holds the
// web session, so `logout` ends it on Telegram's side and deletes the folder.
//
// film answers each command with one line, like telegram-film.cjs:
//
//   arm            start the screencast, keep the last seconds in memory  -> "armed"
//   record <t>     keep the footage from <t> minus DEMO_PREROLL on          -> "recording"
//   start          tap Start if the bot chat offers it (first contact)     -> "started" | "no-start"
//   type <text>    type <text> at a person's pace and send it              -> "sent <t>"
//   reply <s>      wait up to <s> seconds for the bot's next message       -> "replied <t>" | "no-reply"
//   scrub <file>   more "text=replacement" lines to replace in the picture -> "scrubbed <n>"
//   mark <name>    note a moment in take.json                              -> "marked"
//   look <name>    a screenshot for whoever checks the script              -> "looked"
//   stop           stop filming, write take.json and quit                  -> "stopped"
//
// It prints "ready" once the chat is on screen and "error <text>" when
// something fails. Times are seconds since the epoch.
//
//   DEMO_TG_VIEW     the phone's screen in CSS pixels (default 390x844)
//   DEMO_TG_SCALE    device scale (default 2: frames of 780 x 1688)
//   DEMO_JPEG        quality of the filmed pictures (default 90)
//   DEMO_FPS         frames a second kept at most (default 60)
//   DEMO_PREROLL     seconds kept from before the moment `record` names (default 2)
//   DEMO_SCRUB_FILE  "text=replacement" lines: words that must not be in the picture
//
// The page helpers (scrub) are copied from telegram-film.cjs, so a change there
// does not move this clip.
const { chromium } = require('playwright');
const fs = require('fs');
const os = require('os');
const path = require('path');
const readline = require('readline');

const [CMD, ARG1, ARG2] = process.argv.slice(2);
const PROFILE = process.env.DEMO_TG_PROFILE
  || path.join(os.homedir(), 'Library', 'Application Support', 'dodaios-demo', 'telegram-web');
const WEB = 'https://web.telegram.org/k/';
const [VW, VH] = (process.env.DEMO_TG_VIEW || '390x844').split('x').map(Number);
const SCALE = Number(process.env.DEMO_TG_SCALE || 2);
const JPEG = Number(process.env.DEMO_JPEG || 90);
const FPS = Number(process.env.DEMO_FPS || 60);
const PREROLL = Number(process.env.DEMO_PREROLL || 2);
const UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1';
const TOKEN_RE = /\b\d{6,12}:[A-Za-z0-9_-]{30,64}\b/;

const say = (line) => process.stdout.write(line + '\n');
const now = () => Date.now() / 1000;

function ensureProfile() {
  fs.mkdirSync(PROFILE, { recursive: true });
  fs.chmodSync(PROFILE, 0o700);
}

async function open({ headless = true, extraArgs = [] } = {}) {
  ensureProfile();
  const ctx = await chromium.launchPersistentContext(PROFILE, {
    channel: 'chrome',
    headless,
    viewport: { width: VW, height: VH },
    deviceScaleFactor: SCALE,
    isMobile: true,
    hasTouch: true,
    userAgent: UA,
    locale: 'en-US',
    timezoneId: 'Europe/Berlin',
    colorScheme: 'dark',
    args: ['--force-color-profile=srgb', '--hide-scrollbars', ...extraArgs],
  });
  const page = ctx.pages()[0] || (await ctx.newPage());
  page.setDefaultTimeout(20000);
  return { ctx, page };
}

const bodyText = (page) => page.evaluate(() => (document.body ? document.body.innerText : '')).catch(() => '');

// Signed in: the page draws the chat list or a chat; signed out: the sign-in pages.
async function state(page, wait = 30000) {
  const end = Date.now() + wait;
  while (Date.now() < end) {
    const signedIn = await page.locator('#column-left .chatlist, .chatlist-container, .chat-input, .input-message-input').first().isVisible().catch(() => false);
    if (signedIn) return 'signed-in';
    const t = await bodyText(page);
    if (/Log in to Telegram by QR Code|Sign in to Telegram|Scan from mobile|Enter Your Password|Your Password/i.test(t)) return /Password/i.test(t) ? 'password' : 'signed-out';
    await page.waitForTimeout(400);
  }
  return 'unknown';
}

// ---- login -------------------------------------------------------------------
// A visible window, so the person sees what they scan and can type the account's
// password there if it has one. A line on top says what it is for.
const BANNER = `(() => {
  const add = () => {
    if (!document.body || document.getElementById('__demo_banner')) return;
    const b = document.createElement('div');
    b.id = '__demo_banner';
    b.textContent = 'Dodaios README clip: scan this code with Telegram on your phone (Settings > Devices > Link Desktop Device). This window closes by itself.';
    Object.assign(b.style, { position: 'fixed', left: '0', right: '0', top: '0', zIndex: '2147483647', padding: '8px 10px', font: '13px/1.35 -apple-system, sans-serif', background: '#111', color: '#fff', textAlign: 'center' });
    document.body.appendChild(b);
  };
  document.addEventListener('DOMContentLoaded', add);
  setInterval(add, 1000);
})();`;

async function login() {
  const { ctx, page } = await open({ headless: false, extraArgs: [`--window-size=${VW + 40},${VH + 120}`] });
  await page.addInitScript(BANNER);
  await page.goto(WEB, { waitUntil: 'domcontentloaded' });
  let s = await state(page, 60000);
  if (s === 'signed-in') { say('signed-in'); await ctx.close(); return; }
  // The QR code page, not the phone-number page.
  const qr = page.getByText(/log in by qr code/i).first();
  if (await qr.isVisible().catch(() => false)) await qr.click().catch(() => {});
  say('waiting');
  const end = Date.now() + 6 * 60 * 60 * 1000;
  let lastReload = Date.now();
  while (Date.now() < end) {
    s = await state(page, 5000);
    if (s === 'signed-in') { say('signed-in'); await page.waitForTimeout(4000); await ctx.close(); return; }
    // A QR page that stood for a long time is opened afresh (its code renews itself, but
    // a page left alone for hours may stop doing so).
    if (s === 'signed-out' && Date.now() - lastReload > 20 * 60 * 1000) {
      lastReload = Date.now();
      await page.reload({ waitUntil: 'domcontentloaded' }).catch(() => {});
    }
  }
  say('error not signed in within 6 hours');
  await ctx.close();
  process.exit(1);
}

// ---- status --------------------------------------------------------------------
async function status() {
  if (!fs.existsSync(PROFILE)) { say('signed-out'); return; }
  const { ctx, page } = await open();
  await page.goto(WEB, { waitUntil: 'domcontentloaded' });
  const s = await state(page, 45000);
  say(s === 'signed-in' ? 'signed-in' : 'signed-out');
  await ctx.close();
}

// ---- chats -----------------------------------------------------------------------
async function openChat(page, username) {
  await page.goto(`${WEB}#@${username}`, { waitUntil: 'domcontentloaded' });
  if ((await state(page, 45000)) !== 'signed-in') throw new Error('Telegram Web is not signed in (run: telegram-web.cjs login)');
  const input = page.locator('.input-message-input:visible').first();
  const start = page.locator('.chat-input .btn-primary:visible, button:has-text("START"):visible, button:has-text("Start"):visible').first();
  const end = Date.now() + 30000;
  while (Date.now() < end) {
    if (await input.isVisible().catch(() => false)) return 'input';
    if (await start.isVisible().catch(() => false)) return 'start';
    await page.waitForTimeout(300);
  }
  throw new Error(`the chat with @${username} did not open`);
}

// Bubbles of the open chat: { out, text } from the oldest to the newest.
const bubbles = (page) => page.evaluate(() => [...document.querySelectorAll('.bubbles .bubble')]
  .filter((b) => !b.classList.contains('service') && !b.classList.contains('is-date'))
  .map((b) => ({ out: b.classList.contains('is-out'), text: (b.querySelector('.message') || b).innerText || '' })));

async function waitIncoming(page, after, seconds) {
  const end = Date.now() + seconds * 1000;
  while (Date.now() < end) {
    const list = await bubbles(page).catch(() => []);
    const fresh = list.slice(after).filter((b) => !b.out && b.text.trim());
    if (fresh.length) return fresh;
    await page.waitForTimeout(250);
  }
  return [];
}

async function typeAndSend(page, text) {
  const input = page.locator('.input-message-input:visible').first();
  await input.tap().catch(() => input.click());
  for (const ch of text) {
    await page.keyboard.type(ch);
    // A person types unevenly: quicker inside a word, a little pause after one.
    const base = /[ ,.]/.test(ch) ? 150 : 85;
    await page.waitForTimeout(base + Math.random() * 70);
  }
  await page.waitForTimeout(450);
  const send = page.locator('.btn-send:visible').first();
  if (await send.isVisible().catch(() => false)) await send.tap().catch(() => send.click());
  else await page.keyboard.press('Enter');
  return now();
}

// ---- newbot ----------------------------------------------------------------------
async function newbot(file, name) {
  if (!file) throw new Error('usage: telegram-web.cjs newbot <token file> [name]');
  const { ctx, page } = await open();
  try {
    if ((await openChat(page, 'BotFather')) === 'start') {
      await page.locator('.chat-input .btn-primary:visible, button:has-text("START"):visible').first().tap();
      await page.locator('.input-message-input:visible').first().waitFor({ state: 'visible', timeout: 20000 });
    }
    const ask = async (text, seconds = 40) => {
      const before = (await bubbles(page)).length;
      await typeAndSend(page, text);
      const fresh = await waitIncoming(page, before, seconds);
      if (!fresh.length) throw new Error(`@BotFather did not answer "${text.slice(0, 20)}"`);
      // BotFather may answer in two messages; the newest says what it wants.
      await page.waitForTimeout(1200);
      const all = await bubbles(page);
      return all.slice(before).filter((b) => !b.out).map((b) => b.text).join('\n');
    };
    let answer = await ask('/newbot');
    if (!/call it|name/i.test(answer)) throw new Error('@BotFather did not ask for a name');
    answer = await ask(name || 'Nova');
    if (!/username/i.test(answer)) throw new Error('@BotFather did not ask for a username');
    for (let i = 0; i < 6; i++) {
      const username = `nova_demo_${Math.random().toString(36).slice(2, 7)}_bot`;
      answer = await ask(username);
      const token = (answer.match(TOKEN_RE) || [])[0];
      if (token) {
        fs.writeFileSync(file, token + '\n', { mode: 0o600 });
        fs.chmodSync(file, 0o600);
        say(`bot @${username}`);
        return;
      }
      if (!/taken|invalid|sorry/i.test(answer)) throw new Error('@BotFather answered without a token');
    }
    throw new Error('no free username after six tries');
  } finally {
    await ctx.close().catch(() => {});
  }
}

// ---- logout ------------------------------------------------------------------------
async function logout() {
  if (fs.existsSync(PROFILE)) {
    const { ctx, page } = await open();
    try {
      await page.goto(WEB, { waitUntil: 'domcontentloaded' });
      if ((await state(page, 45000)) === 'signed-in') {
        // Telegram Web's own way out: the menu, Settings, the menu there, Log Out.
        await page.locator('.sidebar-tools-button, .btn-menu-toggle').first().tap();
        await page.getByText('Settings', { exact: true }).first().tap();
        await page.locator('#column-left .sidebar-header .btn-menu-toggle:visible').last().tap();
        await page.getByText(/^Log ?Out$/i).first().tap();
        await page.locator('.popup-button:has-text("Log Out"), .popup-button.danger').first().tap();
        await page.waitForTimeout(4000);
        say(((await state(page, 20000)) === 'signed-in') ? 'error still signed in' : 'signed-out');
      } else {
        say('signed-out');
      }
    } catch (e) {
      say('error ' + String(e && e.message || e).split('\n')[0] + ' (end the session in Telegram: Settings > Devices)');
    } finally {
      await ctx.close().catch(() => {});
    }
  } else {
    say('signed-out');
  }
  fs.rmSync(PROFILE, { recursive: true, force: true });
}

// ---- film ----------------------------------------------------------------------------
function readPairs(file) {
  if (!file || !fs.existsSync(file)) return [];
  return fs.readFileSync(file, 'utf8').split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && line.includes('='))
    .map((line) => [line.slice(0, line.indexOf('=')), line.slice(line.indexOf('=') + 1)])
    .filter(([from]) => from.length >= 2);
}
const spellings = (s) => [...new Set([
  s,
  s.normalize('NFD').replace(/[̀-ͯ]/g, ''),
  s.replace(/ä/g, 'ae').replace(/ö/g, 'oe').replace(/ü/g, 'ue').replace(/Ä/g, 'Ae').replace(/Ö/g, 'Oe').replace(/Ü/g, 'Ue').replace(/ß/g, 'ss'),  // i18n-allow: umlaut spellings to match, not German text
])];
const expand = (pairs) => pairs.flatMap(([from, to]) => spellings(from).map((v) => [v, to]))
  .filter(([from], i, all) => all.findIndex(([f]) => f.toLowerCase() === from.toLowerCase()) === i)
  .sort((a, b) => b[0].length - a[0].length);

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
  window.__demoScrub = (more) => {
    for (const p of more) if (!known.some(([a]) => a.toLowerCase() === p[0].toLowerCase())) known.push(p);
    known.sort((a, b) => b[0].length - a[0].length);
    to = new Map(known.map(([a, b]) => [a.toLowerCase(), b]));
    const source = known.map(([a]) => a.replace(/[.*+?^\${}()|[\\]\\\\]/g, '\\\\$&')).join('|');
    const word = source ? '(?<![\\\\p{L}\\\\p{N}_])(?:' + source + ')(?![\\\\p{L}\\\\p{N}_])' : '';
    all = word ? new RegExp(word, 'giu') : null;
    one = word ? new RegExp(word, 'iu') : null;
    if (document.documentElement) walk(document.documentElement);
    return known.length;
  };
  new MutationObserver((ms) => { for (const m of ms) { if (m.type === 'characterData') walk(m.target); for (const n of m.addedNodes) walk(n); } })
    .observe(document, { subtree: true, childList: true, characterData: true });
  // Telegram Web's own counters and notices of other chats are nobody's business:
  // the unread badge on the back button and the pop-up notices are hidden.
  const hide = () => {
    if (document.getElementById('__demo_hide') || !document.head) return;
    const st = document.createElement('style');
    st.id = '__demo_hide';
    st.textContent = '.sidebar-close-button .badge, .btn-icon .badge, .notification, .toast, .tooltip { visibility: hidden !important; }';
    document.head.appendChild(st);
  };
  hide();
  document.addEventListener('DOMContentLoaded', hide);
  window.__demoScrub(${JSON.stringify(pairs)});
})();`;

async function film(username, out) {
  if (!username || !out) throw new Error('usage: telegram-web.cjs film <bot username> <folder>');
  fs.mkdirSync(out, { recursive: true });
  const host = os.hostname();
  const base = [
    [host, 'MacBook-Pro'],
    [host.replace(/\.(local|lan|home|fritz\.box)$/i, ''), 'MacBook-Pro'],
    [os.userInfo().username, 'alex'],
  ].filter(([from], i, list) => from && from.length > 3 && list.findIndex(([f]) => f === from) === i);
  const { ctx, page } = await open();
  await ctx.addInitScript(PAGE_HELPERS(expand([...base, ...readPairs(process.env.DEMO_SCRUB_FILE)])));
  const client = await ctx.newCDPSession(page);
  let armed = false, recording = false, casting = false, kept = 0, idx = 0;
  const gap = 1 / FPS - 0.004;
  const pre = [], frames = [], marks = [], times = {};
  const write = (ts, data) => {
    const name = String(idx++).padStart(6, '0') + '.jpg';
    fs.writeFileSync(path.join(out, name), Buffer.from(data, 'base64'));
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
      while (pre.length > 2 && pre[1].ts < ts - PREROLL - 1) pre.shift();
    }
  });
  const save = () => fs.writeFileSync(path.join(out, 'take.json'), JSON.stringify({
    window: { width: VW, height: VH, scale: SCALE }, jpeg: JPEG, fps: FPS, preroll: PREROLL,
    url: `${WEB}#@${username}`, times, marks, frames,
  }));
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

  try {
    times.mode = await openChat(page, username);
    await page.waitForTimeout(1500);
    times.ready = now();
    say('ready');
  } catch (e) {
    await page.screenshot({ path: path.join(out, 'failure.png') }).catch(() => {});
    say('error ' + String(e && e.message || e).split('\n')[0]);
    await ctx.close().catch(() => {});
    process.exit(1);
  }

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
    await Promise.race([ctx.close().catch(() => {}), new Promise((r) => setTimeout(r, 4000))]);
    process.exit(0);
  };
  lines.on('close', stop);
  let seenBefore = (await bubbles(page).catch(() => [])).length;
  for await (const raw of lines) {
    const [cmd, ...rest] = raw.trim().split(' ');
    const arg = rest.join(' ');
    try {
      if (cmd === 'arm') {
        if (!casting) {
          await client.send('Page.startScreencast', { format: 'jpeg', quality: JPEG, maxWidth: Math.round(VW * SCALE), maxHeight: Math.round(VH * SCALE), everyNthFrame: 1 });
          casting = true;
        }
        armed = true;
        times.armed = now();
        const shot = await client.send('Page.captureScreenshot', { format: 'jpeg', quality: JPEG }).catch(() => null);
        if (shot && shot.data && !pre.length) pre.push({ ts: times.armed, data: shot.data });
        await repaint();
        say('armed');
      } else if (cmd === 'record') {
        const from = (Number(arg) || now()) - PREROLL;
        times.record_from = from;
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
      } else if (cmd === 'start') {
        const start = page.locator('.chat-input .btn-primary:visible, button:has-text("START"):visible').first();
        if (await start.isVisible().catch(() => false)) {
          seenBefore = (await bubbles(page).catch(() => [])).length;
          await start.tap().catch(() => start.click());
          await page.locator('.input-message-input:visible').first().waitFor({ state: 'visible', timeout: 20000 }).catch(() => {});
          times.started = now();
          say('started');
        } else {
          say('no-start');
        }
      } else if (cmd === 'type') {
        seenBefore = (await bubbles(page).catch(() => [])).length;
        times.typing = now();
        const at = await typeAndSend(page, arg);
        times.sent = at;
        say(`sent ${at.toFixed(3)}`);
      } else if (cmd === 'reply') {
        const fresh = await waitIncoming(page, seenBefore, Number(arg) || 60);
        if (fresh.length) {
          times.replied = now();
          say(`replied ${times.replied.toFixed(3)}`);
        } else {
          say('no-reply');
        }
      } else if (cmd === 'scrub') {
        const pairs = expand(readPairs(arg));
        const n = await page.evaluate((p) => (window.__demoScrub ? window.__demoScrub(p) : 0), pairs).catch(() => 0);
        say('scrubbed ' + n);
      } else if (cmd === 'mark') {
        marks.push({ name: arg, at: now() });
        say('marked');
      } else if (cmd === 'look') {
        const was = recording; recording = false;
        await page.screenshot({ path: path.join(out, `look-${arg || 'now'}.png`), scale: 'css' }).catch(() => {});
        await page.waitForTimeout(60);
        recording = was;
        say('looked');
      } else if (cmd === 'stop') {
        await stop();
      } else if (cmd) {
        say('error unknown command ' + cmd);
      }
    } catch (e) {
      say('error ' + String(e && e.message || e).split('\n')[0]);
    }
  }
}

(async () => {
  try {
    if (CMD === 'login') await login();
    else if (CMD === 'status') await status();
    else if (CMD === 'newbot') await newbot(ARG1, ARG2);
    else if (CMD === 'film') await film(ARG1, ARG2);
    else if (CMD === 'logout') await logout();
    else { console.error('usage: telegram-web.cjs login | status | newbot <file> [name] | film <bot> <folder> | logout'); process.exit(2); }
  } catch (e) {
    say('error ' + String(e && e.message || e).split('\n')[0]);
    process.exit(1);
  }
})();

