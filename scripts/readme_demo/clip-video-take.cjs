// Films the video at the top of the README: it opens in the Agentic IDE's
// chat, where Claude Code builds a change; the assistant turns that change
// into a slide for a colleague (an artifact, opened large) and hands the next
// task to a chat of its own in the Agentic IDE, which is then watched at work.
// Real turns of real models.
//
//   node scripts/readme_demo/clip-video-take.cjs <take folder>
//
// It expects the instance that clip-video-setup.cjs warmed up (window
// 1280x720 at device scale 1.5: DEMO_WINDOW=1280x720 DEMO_SCALE=1.5) with
// trailhead connected and no chat in trailhead yet. The footage, in order:
//
//   ide-ask     the IDE's chat in trailhead (the first frame); the request is
//               typed and sent
//   ide-work    Claude Code at work until its turn is over ("ide-done")
//   to-chat     the switch to the assistant
//   sam-ask     "Make the release note for Sam."
//   sam-wait    the card of the slide comes in ("card")
//   sam-deck    the slide opened large ("page"), back to the chat
//   hand-ask    the assistant is asked to have the IDE do the next step
//   hand-wait   its answer ("said")
//   to-ide      the switch to the IDE, the chat the assistant started
//   hand-work   that chat at work until its turn is over ("hand-done")
//   back        back to the assistant, its report ("report")
//
// Waits are filmed at 60 frames a second, but only the seconds around the
// moments above are kept; clip-video-cut.cjs makes the video.
//
//   DEMO_DRY    "1": everything up to the first request, without sending it
const { open } = require('./clip-reel-common.cjs');
const fs = require('fs');
const path = require('path');

const OUT = process.argv[2];
if (!OUT) { console.error('usage: node clip-video-take.cjs <take folder>'); process.exit(2); }
const ASK_IDE = process.env.DEMO_ASK_IDE || 'Add a --json flag to the plan command, with tests.';
const ASK_SAM = process.env.DEMO_ASK_SAM || 'I just added --json to trailhead in the IDE. Make the release note for Sam.';
const ASK_HAND = process.env.DEMO_ASK_HAND || 'Now have the IDE bump trailhead to 0.4 and add a changelog entry.';
const KEY = Number(process.env.DEMO_KEY || 42);
const WAIT = 10 * 60 * 1000;
const QUIET = Number(process.env.DEMO_QUIET || 20000);

(async () => {
  const rig = await open(OUT);
  const { page, sleep, click, look, log, W, H } = rig;

  const keep = [];
  const waits = [];
  const prune = (before) => {
    const frames = rig.frames;
    for (let i = frames.length - 1; i >= 0; i--) {
      const f = frames[i];
      if (f.ts >= before) continue;
      if (!waits.some(([a, b]) => f.ts >= a && f.ts <= b)) continue;
      if (keep.some(([a, b]) => f.ts >= a && f.ts <= b)) continue;
      try { fs.unlinkSync(path.join(OUT, f.name)); } catch { /* gone */ }
      frames.splice(i, 1);
    }
  };
  const note = (name, before = 1.5, after = 3) => { const at = rig.now(); rig.moment(name); keep.push([at - before, at + after]); log(name); };
  async function wait(what, step, { head = 1.5, every = 90 } = {}) {
    const from = rig.now();
    const span = [from, Infinity];
    waits.push(span);
    keep.push([from - 0.1, from + head]);
    const t0 = Date.now();
    let last = Date.now();
    for (;;) {
      if (await step()) break;
      await rig.noFailedTurn();
      if (Date.now() - t0 > WAIT) throw new Error('waited in vain for ' + what);
      if (Date.now() - last > 2000) { prune(rig.now() - 3); last = Date.now(); }
      await sleep(every);
    }
    const to = rig.now();
    keep.push([to - 2.5, to + 0.5]);
    span[1] = to;
    prune(to - 3);
  }
  const drift = (x, y, ms = 900) => rig.moveTo(x, y, ms);
  const leadRunning = async () => Boolean((await rig.api('api/agent-chat/lead'))?.running);
  const threads = async () => ((await rig.api('api/agent-chat/sessions?surface=agent'))?.sessions || []);
  const counts = () => page.evaluate(() => ({
    bubbles: document.querySelectorAll('[data-testid="lead-bubble"]').length,
    cards: document.querySelectorAll('[data-testid="page-card"]').length,
    approvals: [...document.querySelectorAll('[data-testid="thread-approval"]')].filter((e) => e.offsetParent).length,
  }));
  // The assistant's turn is over and stays over for `calm` ms (or no new
  // message for QUIET ms while its turn stays open to wait for a chat).
  const turnOver = (calm = 5000) => {
    let at = 0, still = 0, seen = -1;
    return async () => {
      const n = (await counts()).bubbles;
      if (n !== seen) { seen = n; still = Date.now(); }
      if (Date.now() - still > QUIET) return true;
      if (await leadRunning()) { at = 0; return false; }
      if (!at) at = Date.now();
      return Date.now() - at > calm;
    };
  };
  // The thread on screen in the IDE: its last turn is over and nothing works.
  const ideIdle = () => page.evaluate(() => {
    const view = [...document.querySelectorAll('[data-testid="thread-view"]')].find((e) => e.offsetParent);
    if (!view) return false;
    const turns = view.querySelectorAll('[data-testid="thread-turn"]');
    if (!turns.length) return false;
    if ([...view.querySelectorAll('[data-testid="thread-working"], [data-testid="thread-stop"]')].some((e) => e.offsetParent)) return false;
    return !/running|streaming|pending/.test(turns[turns.length - 1].getAttribute('data-status') || '');
  });
  // The IDE's thread at its newest line.
  const ideToEnd = () => page.evaluate(() => {
    for (const el of document.querySelectorAll('[data-testid="thread-timeline"]')) if (el.offsetParent) el.scrollTop = el.scrollHeight;
  });
  async function otherCard(card, text) {
    log('another card:', text.slice(0, 200));
    rig.notes.other = [...(rig.notes.other || []), text.slice(0, 300)];
    await rig.film('other-card');
    await click(card.locator('[data-testid="action-card-allow"]'), { post: 1200 });
  }
  async function ask(name, text, field = () => rig.chatInput()) {
    await rig.film(name);
    await sleep(500);
    await click(field(), { post: 280 });
    await rig.type(name, text, KEY);
    await sleep(500);
    const el = field();
    const typedText = ((await el.inputValue().catch(() => null)) ?? (await el.innerText())).replace(/\s+/g, ' ').trim();
    if (typedText !== text) throw new Error(`the field holds "${typedText}", not the request`);
    await page.keyboard.press('Enter');
    rig.moment(name + '-sent');
    await sleep(1200);
  }
  async function toChat() {
    await rig.point('[data-testid="surface-dodaios"]', { top: 0 });
    await sleep(200);
    await rig.press();
    await rig.chatInput().waitFor({ state: 'visible' });
    await sleep(300);
    await rig.toEnd();
    await drift(W * 0.4, H * 0.55, 750);
  }
  const ideInput = () => page.locator('[data-testid="thread-composer-input"]:visible').first();
  const trailheadHeader = () => page.locator('[data-testid^="thread-project-header-"]:visible').filter({ hasText: 'trailhead' }).first();

  try {
    await page.goto(rig.URL, { waitUntil: 'domcontentloaded' });
    await sleep(3500);
    await rig.closeNotice();
    const intro = page.getByText('Skip introduction').first();
    if (await intro.waitFor({ state: 'visible', timeout: 3000 }).then(() => true, () => false)) await click(intro, { post: 800 });
    const memories = ((await rig.api('api/memory/vault/items'))?.items || []).map((m) => m.text || '');
    if (!memories.some((m) => /\bSam\b/.test(m))) throw new Error('the memory holds nothing about Sam: ' + JSON.stringify(memories));
    // The assistant's chat at its end, so the switch to it lands there.
    await rig.chatInput().waitFor({ state: 'visible' });
    await rig.toEnd();
    // The IDE, its chat, a new chat in trailhead: the first frame.
    await click('[data-testid="surface-ide"]', { post: 1200 });
    await click(page.locator('button:visible').filter({ hasText: /^\s*Chat\s*$/ }).first(), { post: 900 });
    const pid = ((await trailheadHeader().getAttribute('data-testid')) || '').replace('thread-project-header-', '');
    if (!pid) throw new Error('no project trailhead in the IDE');
    await trailheadHeader().hover();
    await click(`[data-testid="thread-new-${pid}"]`, { post: 1200 });
    await ideInput().waitFor({ state: 'visible', timeout: 10000 });
    if (!(await page.getByText(/What should we build in trailhead/).first().isVisible().catch(() => false))) throw new Error('the IDE does not show a new chat in trailhead');
    await rig.moveTo(W * 0.55, H * 0.7, 400);
    await sleep(1500);
    await look('0-start');
    if (await page.getByText(/run(s)? as administrator/).first().isVisible().catch(() => false)) throw new Error('the administrator notice is still there');
    if (process.env.DEMO_DRY) { log('dry run'); await rig.close(); return; }

    // ---- 1. Claude Code in the IDE's chat ------------------------------------------
    const before = new Set((await threads()).map((s) => s.session_id));
    await ask('ide-ask', ASK_IDE, ideInput);
    await rig.film('ide-work');
    {
      let n = 0, lastDrift = Date.now(), files = false;
      const spots = [[0.55, 0.45], [0.7, 0.6], [0.5, 0.35], [0.65, 0.5]];
      await wait('Claude Code in the IDE', async () => {
        await ideToEnd();
        if (!files && await page.locator('[data-testid="thread-changed-files"]:visible').first().isVisible().catch(() => false)) { files = true; note('ide-files', 1, 3); }
        if (Date.now() - lastDrift > 6000) { lastDrift = Date.now(); const [x, y] = spots[n++ % spots.length]; await drift(W * x, H * y, 1200); }
        const t = (await threads()).filter((s) => !before.has(s.session_id));
        return t.length > 0 && !t.some((s) => s.running) && await ideIdle();
      }, { head: 6 });
      await ideToEnd();
      note('ide-done', 1, 4);
    }
    await sleep(3500);
    await look('1-ide-done');
    const mine = new Set((await threads()).map((s) => s.session_id));

    // ---- 2. the slide for Sam ---------------------------------------------------------
    await rig.film('to-chat');
    await toChat();
    let c = await counts();
    await ask('sam-ask', ASK_SAM);
    await rig.film('sam-wait');
    await drift(W * 0.48, H * 0.5, 700);
    await wait('the slide card', async () => { const n = await counts(); if (n.cards > c.cards) { await rig.toEnd(); note('card', 1, 4); return true; } return false; });
    await sleep(1500);
    await rig.toEnd();
    await look('2-card');
    await rig.film('sam-deck');
    {
      const preview = page.locator('[data-testid="page-card-preview"]:visible').last();
      await rig.point(preview);
      await sleep(250);
      await rig.press();
      rig.moment('clicked');
      const frame = page.frameLocator('[data-testid="visualization-frame"]');
      await page.locator('[data-testid="visualization-frame"]:visible').first().waitFor({ state: 'visible', timeout: 30000 });
      await frame.locator('.dk.is-ready').first().waitFor({ state: 'visible', timeout: 30000 });
      rig.moment('page');
      await drift(W * 0.62, H * 0.62, 900);
      await sleep(3200);
      await look('3-deck');
      await rig.point(rig.rail('chats'), { top: 20 });
      await sleep(200); await rig.press();
      await rig.chatInput().waitFor({ state: 'visible', timeout: 10000 });
      await sleep(300);
      await rig.toEnd();
      await drift(W * 0.4, H * 0.55, 700);
    }
    await rig.film('sam-settle');
    {
      const over = turnOver(4000);
      for (;;) {
        let card = null;
        await wait('the assistant to be quiet', async () => {
          if ((await counts()).approvals > 0) { card = page.locator('[data-testid="thread-approval"]:visible').last(); return true; }
          return over();
        });
        if (!card) break;
        await rig.toEnd();
        await otherCard(card, (await card.innerText().catch(() => '')).replace(/\s+/g, ' '));
        await rig.film('sam-settle-2');
      }
    }
    await rig.toEnd();

    // ---- 3. the assistant hands the next step to the IDE ------------------------------
    c = await counts();
    await ask('hand-ask', ASK_HAND);
    await rig.film('hand-wait');
    await drift(W * 0.48, H * 0.5, 700);
    let handed = null;
    {
      let said = false;
      await wait('the answer and a chat of its own in the IDE', async () => {
        const n = await counts();
        if (!said && n.bubbles > c.bubbles) { said = true; await rig.toEnd(); note('said', 1, 3); }
        handed = (await threads()).find((s) => !mine.has(s.session_id)) || null;
        return said && handed && handed.running;
      });
    }
    await sleep(1500);
    await rig.toEnd();
    const saidCount = (await counts()).bubbles;
    await look('4-said');
    await rig.film('to-ide');
    await rig.point('[data-testid="surface-ide"]', { top: 0 });
    await sleep(200); await rig.press();
    await sleep(700);
    const row = page.locator(`[data-testid="thread-row-${handed.session_id}"]:visible`).first();
    await row.waitFor({ state: 'visible', timeout: 10000 });
    await rig.point(row); await sleep(200); await rig.press();
    await page.locator('[data-testid="thread-view"]:visible').first().waitFor({ state: 'visible', timeout: 10000 });
    await ideToEnd();
    rig.moment('ide-handed');
    await drift(W * 0.6, H * 0.5, 900);
    await sleep(1200);
    await look('5-handed');
    await rig.film('hand-work');
    {
      let n = 0, lastDrift = Date.now();
      const spots = [[0.55, 0.45], [0.7, 0.6], [0.5, 0.35]];
      await wait('the chat the assistant started', async () => {
        await ideToEnd();
        if (Date.now() - lastDrift > 6000) { lastDrift = Date.now(); const [x, y] = spots[n++ % spots.length]; await drift(W * x, H * y, 1200); }
        const s = (await threads()).find((x) => x.session_id === handed.session_id);
        return s && !s.running && await ideIdle();
      }, { head: 5 });
      await ideToEnd();
      note('hand-done', 1, 4);
    }
    await sleep(3000);
    await look('6-hand-done');

    // ---- 4. back to the assistant ---------------------------------------------------
    await rig.film('back');
    await toChat();
    await rig.film('back-wait');
    await wait('the assistant\'s report', async () => {
      const n = await counts();
      if (n.bubbles > saidCount && !(await leadRunning())) return true;
      return false;
    }, { head: 2 });
    await rig.toEnd();
    note('report', 1, 5);
    await sleep(5000);
    await look('7-report');
    await rig.finish();

    rig.notes.asks = { ide: ASK_IDE, sam: ASK_SAM, hand: ASK_HAND };
    rig.notes.said = await page.evaluate(() => [...document.querySelectorAll('[data-testid="lead-bubble"]')].slice(-6).map((b) => b.innerText).join('\n---\n')).catch(() => '');
    rig.notes.threads = (await threads()).map((s) => ({ id: s.session_id, title: s.title, model: s.model, agent: s.agent || s.cli }));
    rig.save();
  } catch (e) {
    await rig.fail(e);
  }
  await rig.close();
})();
