// Films the one clip at the top of the README: one request to the assistant,
// and everything it sets off, in one piece of work.
//
//   node scripts/readme_demo/clip-reel-take.cjs <take folder>
//
// It expects the instance that clip-reel-setup.cjs warmed up: a conversation
// in use, the assistant named Nova, the chat's permissions on "Auto-accept
// edits" with its shell commands always allowed (clip-reel-probe.cjs with
// DEMO_STANCE and DEMO_APPROVE=always did that), and a folder old-exports in
// the ledger project. The footage, in the order things really happen:
//
//   ask       the request is typed and sent
//   start     the assistant answers and starts two coding agents: their two
//             chips come into the conversation ("said", "agents")
//   to-ide    a click on the first chip: its thread in the Agentic IDE
//   beside    the second agent's thread is opened beside it ("columns")
//   work      both at work until both have finished ("one-done", "both-done")
//   to-chat   back to the conversation by the switch in the window's caption
//   chat      the assistant goes on: the card of the slide deck ("card") and
//             the approval card of the deletion ("approval") come in
//   deck      the deck is opened from its card ("clicked", "page"); back to the
//             conversation by the section rail ("closed", "chat-again")
//   approve   the pointer goes to "Allow once" and clicks ("allowed")
//   report    the assistant's report ("report"), until its turn is over
//
// "deck" and "approve" are filmed in the order the two cards arrive. A wait
// is filmed at 60 frames a second too, but only the seconds around the
// moments above are kept.
//
//   DEMO_ASK    the request
//   DEMO_DRY    "1": everything up to the request, without sending it
const { open } = require('./clip-reel-common.cjs');
const fs = require('fs');
const path = require('path');

const OUT = process.argv[2];
if (!OUT) { console.error('usage: node clip-reel-take.cjs <take folder>'); process.exit(2); }
const ASK = process.env.DEMO_ASK
  || "Add --csv to ledger list with two agents (code, tests), put a release note on a slide, and delete ledger's old-exports folder for good.";
const KEY = Number(process.env.DEMO_KEY || 38);   // ms between two keys of the request
const WAIT = 8 * 60 * 1000;

(async () => {
  const rig = await open(OUT);
  const { page, sleep, click, look, log, W, H } = rig;

  // ---- waits: only the seconds around a moment are kept ---------------------
  const keep = [];      // [from, to] in screencast seconds
  const waits = [];     // [from, to]: only frames inside a wait are ever deleted
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
  // Poll `step` until it returns true; frames of the wait are thinned out.
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
  // The pointer rests somewhere else now and then, the way a reader's hand does.
  const drift = (x, y, ms = 900) => rig.moveTo(x, y, ms);

  const sessions = async () => ((await rig.api('api/agent-chat/sessions?surface=agent'))?.sessions || []);
  const leadRunning = async () => Boolean((await rig.api('api/agent-chat/lead'))?.running);
  const counts = () => page.evaluate(() => ({
    bubbles: document.querySelectorAll('[data-testid="lead-bubble"]').length,
    cards: document.querySelectorAll('[data-testid="page-card"]').length,
    links: [...document.querySelectorAll('[data-testid="coding-agent-link"]')].filter((e) => e.offsetParent).length,
    approvals: [...document.querySelectorAll('[data-testid="thread-approval"]')].filter((e) => e.offsetParent).length,
  }));

  try {
    await page.goto(rig.URL, { waitUntil: 'domcontentloaded' });
    await sleep(3500);
    await rig.closeNotice();
    const intro = page.getByText('Skip introduction').first();
    if (await intro.waitFor({ state: 'visible', timeout: 3000 }).then(() => true, () => false)) await click(intro, { post: 800 });
    // The Agentic IDE loads its projects when it is first opened in a window:
    // open it once before the film, so the clip does not show it filling up.
    await click('[data-testid="surface-ide"]', { post: 800 });
    await page.locator('[data-testid^="thread-project-"]').first().waitFor({ state: 'visible', timeout: 20000 });
    await sleep(1500);
    await click('[data-testid="surface-dodaios"]', { post: 900 });
    await rig.chatInput().waitFor({ state: 'visible' });
    await rig.toEnd();
    await rig.moveTo(W * 0.42, H * 0.62, 400);
    await sleep(1500);
    await rig.toEnd();
    await look('0-start');
    if (await page.getByText(/run(s)? as administrator/).first().isVisible().catch(() => false)) throw new Error('the administrator notice is still there');
    // The chat asks before consequential actions ("Auto-accept edits"): on
    // "Bypass permissions", the default, nothing asks, not even a deletion.
    const stanceOf = () => page.locator('[data-testid="composer-permission"]:visible').first().getAttribute('aria-label');
    if (!/Auto-accept edits/.test((await stanceOf()) || '')) {
      await click('[data-testid="composer-permission"]:visible', { post: 600 });
      await click(page.getByText('Auto-accept edits', { exact: true }).last(), { post: 600 });
      await rig.moveTo(W * 0.42, H * 0.62, 400);
      await sleep(800);
    }
    log('stance:', await stanceOf());
    if (!/Auto-accept edits/.test((await stanceOf()) || '')) throw new Error('the chat is not on "Auto-accept edits"');
    await look('0-start');
    const c0 = await counts();
    const known = new Set((await sessions()).map((s) => s.session_id));
    const fresh = async () => (await sessions()).filter((s) => !known.has(s.session_id));
    const nodesBefore = new Set(((await rig.api('api/nodes'))?.nodes || []).map((n) => n.id));
    if (process.env.DEMO_DRY) { log('dry run: the start looks like look-0-start.png'); await rig.close(); return; }

    // ---- ask ----------------------------------------------------------------
    await rig.film('ask');
    await sleep(350);
    await click(rig.chatInput(), { post: 260 });
    await rig.type('ask', ASK, KEY);
    await sleep(450);
    await page.keyboard.press('Enter');
    rig.moment('sent');

    // ---- start: the answer, and the two agents ----------------------------------
    await rig.film('start');
    const seen = {};
    const away = drift(W * 0.5, H * 0.45, 700);
    await wait('the assistant to start two coding agents', async () => {
      const c = await counts();
      if (!seen.said && c.bubbles > c0.bubbles) { seen.said = true; note('said', 1.5, 2.5); }
      if (!seen.agents && c.links >= c0.links + 2 && (await fresh()).length >= 2) { seen.agents = true; note('agents', 2, 4); return true; }
      return false;
    });
    await away;
    const agents = (await fresh()).sort((a, b) => (a.created_ms || 0) - (b.created_ms || 0));
    log('agents:', agents.map((a) => `${a.title} (${a.model})`).join(' | '));
    await sleep(700);
    await look('1-agents');

    // ---- to-ide: the first chip ---------------------------------------------------
    await rig.film('to-ide');
    const chips = page.locator('[data-testid="coding-agent-link"]:visible');
    const chip = chips.nth((await chips.count()) - 2);
    await rig.point(chip, { dx: -40 });
    await sleep(260);
    await rig.press();
    rig.moment('chip-clicked');
    const threadInput = page.locator('[aria-label="Message the coding agent"]:visible').first();
    await threadInput.waitFor({ state: 'visible' });
    rig.moment('ide');
    await sleep(650);
    // Which of the two is open now, and the other one's row in the thread list.
    const openId = await page.evaluate((ids) => {
      for (const id of ids) { const row = document.querySelector(`[data-testid="thread-row-${id}"]`); if (row && (row.getAttribute('aria-current') || row.getAttribute('data-active') === 'true' || /bg-/.test(row.className) && row.matches('[data-selected="true"], .is-active'))) return id; }
      return '';
    }, agents.map((a) => a.session_id));
    await look('2-ide');

    // ---- beside: the other agent's thread next to it -------------------------------
    await rig.film('beside');
    let other = null;
    for (const a of agents) {
      const column = page.locator(`[data-testid="thread-column-${a.session_id}"]:visible`);
      const shown = openId ? a.session_id === openId : false;
      if (!shown && !(await column.count())) { other = a; }
    }
    // Without a mark on the open row: the open one is the one whose title is in the header.
    {
      const header = await page.locator('[data-testid="thread-column-main"]:visible').first().innerText().catch(() => '');
      const byTitle = agents.find((a) => a.title && header.includes(a.title));
      if (byTitle) other = agents.find((a) => a.session_id !== byTitle.session_id);
    }
    if (!other) other = agents[1];
    const row = page.locator(`[data-testid="thread-row-${other.session_id}"]`).first();
    await row.waitFor({ state: 'visible', timeout: 15000 });
    await rig.point(row);
    await sleep(220);
    const item = page.getByText('Open side by side', { exact: true }).first();
    for (let attempt = 0; attempt < 3; attempt++) {
      const at = await row.boundingBox();
      await rig.moveTo(at.x + at.width - 17, at.y + at.height / 2, 320);
      await sleep(170);
      await rig.press();
      if (await item.waitFor({ state: 'visible', timeout: 1500 }).then(() => true, () => false)) break;
    }
    rig.moment('menu');
    await rig.point(item);
    await sleep(170);
    await rig.press();
    const column = page.locator(`[data-testid="thread-column-${other.session_id}"]`).first();
    await column.waitFor({ state: 'visible', timeout: 10000 });
    rig.moment('columns');
    {
      const at = await column.boundingBox();
      await drift(at.x + at.width * 0.45, H * 0.42, 800);
    }
    await sleep(500);
    await look('3-columns');

    // ---- work: both agents, until both have finished ---------------------------------
    await rig.film('work');
    {
      const ids = agents.map((a) => a.session_id);
      let done = 0, n = 0, lastDrift = Date.now();
      const spots = [[0.5, 0.36], [0.76, 0.48], [0.55, 0.5], [0.8, 0.38]];
      await wait('the two coding agents to finish', async () => {
        const mine = (await sessions()).filter((s) => ids.includes(s.session_id));
        const idle = mine.filter((s) => !s.running).length;
        if (idle > done) { done = idle; note(done >= ids.length ? 'both-idle' : 'one-done', 2, 3); }
        if (Date.now() - lastDrift > 7000) { lastDrift = Date.now(); const [x, y] = spots[n++ % spots.length]; await drift(W * x, H * y, 1100); rig.moment('rest'); }
        return idle >= ids.length && (await page.locator('button:visible', { hasText: /^Worked for / }).count()) >= ids.length;
      }, { head: 6 });
      note('both-done', 2.5, 4);
    }
    await sleep(1700);
    await look('4-done');

    // ---- to-chat ------------------------------------------------------------------------
    await rig.film('to-chat');
    await rig.point('[data-testid="surface-dodaios"]', { top: 0 });
    await sleep(200);
    await rig.press();
    rig.moment('chat');
    await rig.chatInput().waitFor({ state: 'visible' });
    await drift(W * 0.42, H * 0.5, 750);
    await sleep(300);

    // ---- chat: the deck and the approval, in the order they come ----------------------------
    const did = { deck: false, approve: false };
    let cardsSeen = c0.cards;
    let stretchNo = 0;
    for (let round = 0; round < 2; round++) {
      await rig.film('chat-' + (++stretchNo));
      let next = '';
      let overAt = 0;
      await wait('the deck or the approval card', async () => {
        const c = await counts();
        if (!did.approve && c.approvals > 0) { next = 'approve'; note('approval', 2, 60); return true; }
        if (!did.deck && c.cards > cardsSeen) { next = 'deck'; cardsSeen = c.cards; note('card', 2, 60); return true; }
        if (!(await leadRunning())) { if (!overAt) overAt = Date.now(); else if (Date.now() - overAt > 8000) return true; } else overAt = 0;
        return false;
      });
      if (!next) { log('the turn ended without', did.deck ? 'an approval card' : 'a deck'); break; }
      await rig.toEnd();
      await sleep(900);
      if (next === 'deck') {
        await look('5-card');
        await rig.film('deck');
        const preview = page.locator('[data-testid="page-card-preview"]:visible').last();
        await rig.point(preview);
        await sleep(200);
        await rig.press();
        rig.moment('clicked');
        await sleep(120);
        const stage = page.locator('[data-testid="visualization-frame"]:visible').first();
        await stage.waitFor({ state: 'visible', timeout: 30000 });
        const frame = page.frameLocator('[data-testid="visualization-frame"]');
        await frame.locator('.dk.is-ready').first().waitFor({ state: 'visible', timeout: 30000 });
        rig.moment('page');
        await drift(W * 0.62, H * 0.62, 900);
        await sleep(1300);
        await look('6-deck');
        // Back to the conversation by the section rail (the deck's own
        // close button leads to the Nodes section, not to the chat).
        const back = rig.rail('chats');
        await rig.point(back, { top: 20 });
        await sleep(200);
        await rig.press();
        rig.moment('closed');
        await rig.chatInput().waitFor({ state: 'visible', timeout: 10000 });
        rig.moment('chat-again');
        await sleep(400);
        await rig.toEnd();
        await drift(W * 0.4, H * 0.5, 700);
        did.deck = true;
      } else {
        const card = page.locator('[data-testid="thread-approval"]:visible').last();
        const text = (await card.innerText().catch(() => '')).replace(/\s+/g, ' ').slice(0, 600);
        if (!/deletes for good/.test(text)) {
          // Some other command asks first: it gets "Always allow", for all of
          // this chat's shell commands. The cut leaves this stretch out.
          log('another card first:', text.slice(0, 200));
          await rig.film('other-card');
          await click(card.locator('[data-testid="action-card-always"]'), { post: 800 });
          const wide = card.getByRole('radio', { name: /^All of / }).first();
          if (await wide.count()) await click(wide, { post: 500 });
          await click(card.locator('[data-testid="action-card-rule-save"]'), { post: 800 });
          round--;
          continue;
        }
        await look('7-approval');
        await rig.film('approve');
        rig.notes.approval = text;
        log('approval card:', text);
        const allow = card.locator('[data-testid="action-card-allow"]');
        await sleep(1100);   // the card is read
        await rig.point(allow);
        await sleep(350);
        await rig.press();
        rig.moment('allowed');
        await sleep(900);
        did.approve = true;
      }
    }

    // ---- report ----------------------------------------------------------------------------
    await rig.film('report');
    {
      const cb = await counts();
      let bubbles = cb.bubbles, overAt = 0;
      await drift(W * 0.45, H * 0.56, 800);
      await wait('the report', async () => {
        const c = await counts();
        if (c.bubbles > bubbles) { bubbles = c.bubbles; note('report', 2, 5); await rig.toEnd(); }
        if (c.approvals > 0) { note('approval-again', 2, 5); const again = page.locator('[data-testid="thread-approval"]:visible').last(); log('another approval card:', (await again.innerText()).replace(/\s+/g, ' ').slice(0, 300)); await sleep(1200); await rig.point(again.locator('[data-testid="action-card-allow"]')); await sleep(300); await rig.press(); await sleep(800); }
        if (!(await leadRunning())) { if (!overAt) overAt = Date.now(); else if (Date.now() - overAt > 6000) return true; } else overAt = 0;
        return false;
      });
    }
    await sleep(1500);
    await look('8-report');
    await rig.finish();

    const said = await page.evaluate(() => [...document.querySelectorAll('[data-testid="lead-bubble"]')].slice(-6).map((b) => b.innerText).join('\n---\n'));
    log('said:', said.replace(/\s+/g, ' ').slice(0, 2500));
    rig.notes.ask = ASK;
    rig.notes.said = said;
    rig.notes.agents = (await sessions()).filter((s) => !known.has(s.session_id)).map((s) => ({ id: s.session_id, title: s.title, model: s.model, cwd: s.cwd }));
    rig.notes.nodes = ((await rig.api('api/nodes'))?.nodes || []).filter((n) => !nodesBefore.has(n.id)).map((n) => ({ id: n.id, type: n.type, title: n.title }));
    rig.notes.did = did;
    rig.save();
  } catch (e) {
    await rig.fail(e);
  }
  await rig.close();
})();
