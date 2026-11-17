// Films the video at the top of the README: the assistant directs two Claude
// Code terminals, makes a slide from what it remembers, asks before a
// permanent deletion, and shows what it remembers. Real turns of real models.
//
//   node scripts/readme_demo/clip-video-take.cjs <take folder>
//
// It expects the instance that clip-video-setup.cjs warmed up (window
// 1280x720 at device scale 1.5: DEMO_WINDOW=1280x720 DEMO_SCALE=1.5), with no
// Grid workspace open yet, a folder build/ in trailhead, and Claude Code's
// bypass warning already accepted in the instance's home (see
// clip-video-start.sh). The footage, in the order things happen:
//
//   grid-ask    the request for two terminals, T1 and T2, is typed and sent
//   grid-said   the assistant's answer ("said")
//   to-grid     IDE, Grid: T1 and T2 at work side by side ("grid")
//   grid-work   both at work until both wait again ("one-done", "both-done")
//   sam-ask     back in the chat: "Make the release note for Sam."
//   sam-wait    the card of the slide comes in ("card")
//   sam-deck    the slide opened large ("page"), back to the chat
//   del-ask     the deletion is asked for
//   del-wait    the confirmation card ("approval")
//   del-allow   "Allow once" ("allowed"), the assistant's answer ("done")
//   memory      Search, "Memory": what the assistant remembers
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
const ASK_GRID = process.env.DEMO_ASK_GRID
  || "T1, add a --json flag to trailhead's plan command. T2, write its tests.";
const ASK_SAM = process.env.DEMO_ASK_SAM || 'T1 and T2 are done. Make the release note for Sam.';
const ASK_DEL = process.env.DEMO_ASK_DEL || '0.4 is out: delete trailhead\'s build folder for good.';
const KEY = Number(process.env.DEMO_KEY || 42);
const WAIT = 8 * 60 * 1000;
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
  const panes = async () => ((await rig.api('api/agentic-ide/panes'))?.panes || []).filter((p) => /trailhead/.test(p.folder || ''));
  const counts = () => page.evaluate(() => ({
    bubbles: document.querySelectorAll('[data-testid="lead-bubble"]').length,
    cards: document.querySelectorAll('[data-testid="page-card"]').length,
    approvals: [...document.querySelectorAll('[data-testid="thread-approval"]')].filter((e) => e.offsetParent).length,
  }));
  // The assistant's turn is over and stays over for `calm` ms.
  // (or, when the turn stays open to wait for the terminals, no new message
  // for QUIET ms: a message sent then reaches it all the same).
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
  // A card for some other command (the assistant tidying up after a turn):
  // allowed once in a stretch of its own, which the cut leaves out.
  async function otherCard(card, text) {
    log('another card:', text.slice(0, 200));
    rig.notes.other = [...(rig.notes.other || []), text.slice(0, 300)];
    await rig.film('other-card');
    await click(card.locator('[data-testid="action-card-allow"]'), { post: 1200 });
  }
  async function ask(name, text) {
    await rig.film(name);
    await sleep(500);
    await click(rig.chatInput(), { post: 280 });
    await rig.type(name, text, KEY);
    await sleep(500);
    const typedText = (await rig.chatInput().innerText()).replace(/\s+/g, ' ').trim();
    if (typedText !== text) throw new Error(`the field holds "${typedText}", not the request`);
    await page.keyboard.press('Enter');
    rig.moment(name + '-sent');
    await page.waitForFunction(() => {
      const f = [...document.querySelectorAll('[data-testid="composer-row"] [contenteditable=true]')].find((e) => e.offsetParent);
      return f && !f.innerText.trim();
    }, null, { timeout: 5000 });
    await sleep(700);
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

  try {
    await page.goto(rig.URL, { waitUntil: 'domcontentloaded' });
    await sleep(3500);
    await rig.closeNotice();
    const intro = page.getByText('Skip introduction').first();
    if (await intro.waitFor({ state: 'visible', timeout: 3000 }).then(() => true, () => false)) await click(intro, { post: 800 });
    // Open the IDE and its Grid once before the film, so neither fills up on camera.
    await click('[data-testid="surface-ide"]', { post: 1200 });
    await click(page.getByText('Grid', { exact: true }).first(), { post: 1500 });
    await click(page.getByText('Chat', { exact: true }).first(), { post: 900 });
    await click('[data-testid="surface-dodaios"]', { post: 900 });
    await rig.chatInput().waitFor({ state: 'visible' });
    // The chat asks before consequential actions ("Auto-accept edits"); in
    // "Bypass permissions", the default, nothing asks.
    const stanceOf = () => page.locator('[data-testid="composer-permission"]:visible').first().getAttribute('aria-label');
    if (!/Auto-accept edits/.test((await stanceOf()) || '')) {
      await click('[data-testid="composer-permission"]:visible', { post: 600 });
      await click(page.getByText('Auto-accept edits', { exact: true }).last(), { post: 600 });
    }
    if (!/Auto-accept edits/.test((await stanceOf()) || '')) throw new Error('the chat is not on "Auto-accept edits"');
    await rig.toEnd();
    await rig.moveTo(W * 0.42, H * 0.62, 400);
    await sleep(1500);
    await rig.toEnd();
    await look('0-start');
    if (await page.getByText(/run(s)? as administrator/).first().isVisible().catch(() => false)) throw new Error('the administrator notice is still there');
    const memories = ((await rig.api('api/memory/vault/items'))?.items || []).map((m) => m.text || '');
    if (!memories.some((m) => /\bSam\b/.test(m))) throw new Error('the memory holds nothing about Sam: ' + JSON.stringify(memories));
    if (process.env.DEMO_DRY) { log('dry run'); await rig.close(); return; }

    // DEMO_FROM=memory: a pick-up of the last part in the same instance, when
    // a take stopped after the deletion. It opens on the chat as it stands
    // (the assistant's answer to the deletion) and goes on with the memory.
    const pickup = process.env.DEMO_FROM === 'memory';
    if (pickup) {
      await rig.film('del-end');
      await drift(W * 0.45, H * 0.5, 900);
      await sleep(3200);
      rig.moment('done');
    }
    if (!pickup) {
    // ---- 1. two terminals --------------------------------------------------------
    let c = await counts();
    await ask('grid-ask', ASK_GRID);
    await rig.film('grid-said');
    {
      const b0 = c.bubbles; let said = false;
      await drift(W * 0.5, H * 0.45, 700);
      await wait('the answer and two terminals at work', async () => {
        const n = await counts();
        if (!said && n.bubbles > b0) { said = true; await rig.toEnd(); note('said', 1, 3); }
        const p = await panes();
        return said && p.length >= 2 && p.every((x) => x.activity === 'working');
      });
    }
    await sleep(1200);
    await look('1-said');

    await rig.film('to-grid');
    await rig.point('[data-testid="surface-ide"]', { top: 0 });
    await sleep(200); await rig.press();
    await sleep(900);
    const gridTab = page.locator('button:visible').filter({ hasText: /^\s*Grid\s*$/ }).first();
    await rig.point(gridTab); await sleep(180); await rig.press();
    await page.locator('[data-testid="workspace-terminal-grid"]:visible').first().waitFor({ state: 'visible', timeout: 10000 });
    rig.moment('grid');
    await sleep(900);
    const ws = page.getByText('trailhead', { exact: true }).first();
    await drift(W * 0.6, H * 0.45, 900);
    await sleep(600);
    await look('2-grid');

    await rig.film('grid-work');
    {
      let done = 0, n = 0, lastDrift = Date.now();
      const spots = [[0.4, 0.4], [0.78, 0.5], [0.55, 0.62], [0.8, 0.36]];
      await wait('T1 and T2 to finish', async () => {
        const p = await panes();
        const idle = p.filter((x) => x.activity !== 'working' && x.worked).length;
        if (idle > done) { done = idle; note(done >= 2 ? 'both-done' : 'one-done', 2, 4); }
        if (Date.now() - lastDrift > 6000) { lastDrift = Date.now(); const [x, y] = spots[n++ % spots.length]; await drift(W * x, H * y, 1200); }
        return p.length >= 2 && idle >= p.length;
      }, { head: 7 });
    }
    await sleep(2500);
    await look('3-done');
    void ws;

    // ---- 2. the slide for Sam -------------------------------------------------------
    await rig.film('to-chat');
    // The assistant tells the chat that both are done: wait for that turn first.
    await toChat();
    await rig.film('chat-settle');
    await wait('the assistant to be quiet', turnOver(4000));
    await rig.toEnd();
    c = await counts();
    await ask('sam-ask', ASK_SAM);
    await rig.film('sam-wait');
    await drift(W * 0.48, H * 0.5, 700);
    await wait('the slide card', async () => { const n = await counts(); if (n.cards > c.cards) { await rig.toEnd(); note('card', 1, 4); return true; } return false; });
    await sleep(1500);
    await rig.toEnd();
    await look('4-card');
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
      await look('5-deck');
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

    // ---- 3. the permanent deletion ----------------------------------------------------
    c = await counts();
    await ask('del-ask', ASK_DEL);
    await rig.film('del-wait');
    await drift(W * 0.48, H * 0.5, 700);
    let card, text;
    for (;;) {
      await wait('the confirmation card', async () => (await counts()).approvals > 0);
      await sleep(800);
      await rig.toEnd();
      card = page.locator('[data-testid="thread-approval"]:visible').last();
      text = (await card.innerText().catch(() => '')).replace(/\s+/g, ' ').slice(0, 600);
      if (/for good/.test(text)) break;
      await otherCard(card, text);
      await rig.film('del-wait-2');
    }
    note('approval', 1, 6);
    log('approval card:', text);
    rig.notes.approval = text;
    if (!/for good/.test(text)) throw new Error('another card came first: ' + text.slice(0, 200));
    await look('6-approval');
    const before = (await counts()).bubbles;
    await rig.film('del-allow');
    await sleep(1600);
    await rig.point(card.locator('[data-testid="action-card-allow"]'));
    await sleep(350);
    await rig.press();
    rig.moment('allowed');
    await sleep(800);
    await drift(W * 0.45, H * 0.5, 800);
    {
      const b0 = before;
      const over = turnOver(2500);
      await wait('the answer after the deletion', async () => {
        const n = await counts();
        if (n.approvals > 0) throw new Error('a second card');
        const quiet = await over();
        return n.bubbles > b0 && quiet;
      });
      await rig.toEnd();
      note('done', 1, 4);
    }
    await sleep(3000);
    await look('7-done');
    await wait('the assistant to be quiet', turnOver(3000));
    }

    // ---- 4. memory ------------------------------------------------------------------------
    await rig.film('memory');
    await sleep(400);
    await click('[data-testid="sidebar-search-row"]:visible', { post: 700 });
    await rig.type('memory', 'Memory', 90);
    await sleep(700);
    await page.keyboard.press('Enter');
    rig.moment('memory-open');
    await page.getByText('All memories').first().waitFor({ state: 'visible', timeout: 10000 });
    // The list can take a moment to fill: that wait is left out.
    await rig.film('memory-list');
    await wait('the memories', async () => page.getByText(/Alex Rivera/).first().isVisible().catch(() => false), { head: 0.3 });
    rig.moment('memory-shown');
    await sleep(900);
    const sam = page.getByText(/Sam /).first();
    if (await sam.isVisible().catch(() => false)) await rig.point(sam, { ms: 1100 });
    else log('warning: no memory about Sam in the list');
    await sleep(3500);
    await look('8-memory');
    await rig.finish();

    rig.notes.asks = { grid: ASK_GRID, sam: ASK_SAM, del: ASK_DEL };
    rig.notes.said = await page.evaluate(() => [...document.querySelectorAll('[data-testid="lead-bubble"]')].slice(-8).map((b) => b.innerText).join('\n---\n')).catch(() => '');
    rig.notes.panes = (await panes()).map((p) => ({ name: p.name, recap: p.recap, prompt: (p.last_prompt || '').slice(0, 300) }));
    rig.notes.nodes = ((await rig.api('api/nodes'))?.nodes || []).map((n) => ({ id: n.id, type: n.type, title: n.title }));
    rig.save();
  } catch (e) {
    await rig.fail(e);
  }
  await rig.close();
})();
