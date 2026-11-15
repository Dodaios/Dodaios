// Films the Assistant clip of the README: the Plugins catalog with GitHub
// connected, then a question in the chat that the assistant answers with the
// GitHub plugin.
//
//   node scripts/readme_demo/clip-assistant.cjs <take folder>
//
// It expects a demo instance that nodes-plugins-setup.cjs set up and warmed up,
// with the GitHub plugin connected (plugins_connect.py). The conversation
// draws none of the assistant's steps (the app's choice since 2026-11-13);
// while it works, the line under its name in the panel says what it does
// ("Working in GitHub"). The footage, in this order (nodes-plugins-cut.cjs
// cuts the clip from it):
//
//   catalog  the Plugins catalog stands open over the chat: the pointer goes
//            to GitHub's row and its "Connected" mark, then closes the catalog
//   ask      the question is typed and sent
//   wait     the assistant at work: its first message ("said"), the panel's
//            line says it works in GitHub ("tool"), every message after that
//            ("bubble"), its last one ("answer"), the turn over ("over")
//   answer   the answer is read: the pointer follows its lines
//
//   DEMO_ASK   the question (default: the open pull requests of acme-notes)
//   DEMO_DRY   "1": the catalog and the start, without asking
const { open } = require('./nodes-plugins-common.cjs');

const OUT = process.argv[2];
if (!OUT) { console.error('usage: node clip-assistant.cjs <take folder>'); process.exit(2); }
const ASK = process.env.DEMO_ASK || 'Which acme-notes PRs are still open, and which should I look at first?';
const APP = /GitHub/;

(async () => {
  const rig = await open(OUT);
  const { page, sleep, click, look, log, W, H } = rig;
  const panelLine = () => page.locator('[data-testid="assistant-panel-status"]').first().innerText().catch(() => '');
  try {
    await page.goto(rig.URL, { waitUntil: 'domcontentloaded' });
    await sleep(3500);
    const intro = page.getByText('Skip introduction').first();
    if (await intro.waitFor({ state: 'visible', timeout: 3000 }).then(() => true, () => false)) await click(intro, { post: 800 });
    await rig.chatInput().waitFor({ state: 'visible' });
    await rig.toEnd();
    // The catalog is opened before the take, so the clip opens on it.
    await click(rig.rail('plugins'), { post: 600 });
    const dialog = page.locator('[data-testid="plugin-catalog-dialog"]');
    const github = dialog.locator('button[aria-label="GitHub"]').first();
    await github.waitFor({ state: 'visible', timeout: 15000 });
    const connected = dialog.locator('[aria-label="Connected"]').first();
    await connected.waitFor({ state: 'visible', timeout: 15000 });
    await rig.moveTo(W * 0.56, H * 0.30, 400);
    await sleep(1500);
    await look('0-catalog');
    const bubbles0 = await rig.bubbles();

    // ---- catalog ------------------------------------------------------------
    await rig.film('catalog');
    await sleep(250);
    await rig.point(connected, { dx: -6 });
    await sleep(500);
    await click(dialog.locator('button[aria-label="Close"]').first(), { post: 250, top: 36 });
    await dialog.waitFor({ state: 'hidden', timeout: 5000 });
    if (process.env.DEMO_DRY) { await sleep(800); await look('1-closed'); log('dry run'); await rig.close(); return; }

    // ---- ask ----------------------------------------------------------------
    await rig.film('ask');
    await click(rig.chatInput(), { post: 260 });
    await rig.type('ask', ASK);
    await sleep(380);
    await page.keyboard.press('Enter');
    rig.moment('sent');

    // ---- wait ---------------------------------------------------------------
    await rig.film('wait');
    const t0 = Date.now();
    const seen = {};
    let lastBubbles = bubbles0, lastBubbleAt = null, drift = null;
    // The wait is filmed with 5 frames a second, and with all of them for a
    // while from each moment the cut shows (the message sent, the assistant's
    // messages, its step with the plugin): a long wait at 60 frames a second
    // would fill the disk of a shared computer.
    let fullUntil = Date.now() + 700;
    const full = (ms) => { fullUntil = Math.max(fullUntil, Date.now() + ms); rig.rate(60); };
    for (;;) {
      if (Date.now() > fullUntil) rig.rate(5);
      const s = await page.evaluate(() => ({
        bubbles: document.querySelectorAll('[data-testid="lead-bubble"]').length,
        line: (document.querySelector('[data-testid="assistant-panel-status"]') || {}).innerText || '',
      }));
      if (!seen.said && s.bubbles > bubbles0) { seen.said = true; full(2500); rig.moment('said'); log('said'); }
      if (!seen.tool && APP.test(s.line)) {
        seen.tool = true; full(2200); rig.moment('tool'); log('tool:', s.line.trim());
        // A person glances at what the assistant is doing: the pointer drifts
        // towards the panel's line, and stops beside it, not on it.
        const end = await page.evaluate(() => {
          const text = document.querySelector('[data-testid="assistant-panel-status"]')?.lastElementChild;
          const r = text?.getBoundingClientRect();
          return r ? { x: r.right, y: r.top + r.height / 2 } : null;
        });
        if (end) drift = rig.moveTo(Math.min(W - 40, end.x + 28), end.y + 12, 1100);
      }
      if (seen.tool && s.bubbles > lastBubbles) { full(3000); rig.moment('bubble'); lastBubbleAt = rig.now(); log('message'); }
      lastBubbles = Math.max(lastBubbles, s.bubbles);
      if (Date.now() - t0 > 6000) {
        const lead = await rig.api('api/agent-chat/lead');
        if (lead && !lead.running) { rig.rate(60); rig.moment('over'); log('over'); break; }
      }
      await rig.noFailedTurn();
      if (Date.now() - t0 > 6 * 60 * 1000) throw new Error('the turn did not end within 6 minutes');
      await sleep(80);
    }
    if (drift) await drift;
    if (!seen.tool) throw new Error('the panel never said the assistant works in GitHub');
    if (lastBubbleAt === null) throw new Error('no answer came after the step with the plugin');
    rig.moment('answer', lastBubbleAt);
    await sleep(450);
    await look('2-answered');

    // ---- answer -------------------------------------------------------------
    await rig.film('answer');
    const last = page.locator('[data-testid="lead-bubble"]').last();
    const b = await last.boundingBox();
    if (b) {
      // Along the lines of the answer, at a reader's pace.
      await rig.moveTo(b.x + 60, b.y + 18, 700);
      await rig.glide(b.x + b.width * 0.62, b.y + b.height - 16, Math.min(2600, 900 + b.height * 7));
      const link = last.locator('a').first();
      if (await link.isVisible().catch(() => false)) {
        const l = await link.boundingBox();
        if (l && l.y > 40 && l.y < H - 40) { await rig.moveTo(l.x + l.width / 2, l.y + l.height / 2, 600); rig.moment('link'); await sleep(700); }
      }
    }
    await sleep(500);
    await look('3-read');
    rig.notes.ask = ASK;
    rig.notes.answer_lines = Math.round((b?.height || 0) / 25);
    rig.notes.panel_line_at_end = (await panelLine()).trim();
    await rig.finish();
    const unlocked = ((await rig.api('api/board/achievements'))?.items || []).filter((a) => a.unlocked || a.unlocked_at).map((a) => a.id);
    rig.notes.achievements = unlocked;
    log('achievements:', unlocked.join(', '));
    rig.save();
  } catch (e) {
    await rig.fail(e);
  }
  await rig.close();
})();
