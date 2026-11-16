// Films the second Nodes clip of the README: one sentence to the assistant
// becomes a slide deck, the deck is opened from its card in the chat, a click
// on its title opens the deck's editor, and the title is typed over by hand.
//
//   node scripts/readme_demo/clip-nodes2-take.cjs <take folder>
//
// It expects a demo instance that clip-nodes2-setup.cjs set up and warmed up:
// a conversation in use, the assistant named Nova. The footage, in this order
// (clip-nodes2-cut.cjs cuts the clip from it):
//
//   ask    the pointer goes to the field; the request is typed and sent
//   wait   the assistant at work: its first message ("said"), the card of
//          the deck ("card"), its answer ("answer"), the turn over ("over").
//          Filmed at 60 frames a second, but only the frames around these
//          moments are kept: the rest is a wait the cut leaves out, and a
//          wait of minutes at 60 frames would fill the disk.
//   open   the deck is opened from its card: its page on the stage
//   edit   a click on the first slide's title opens the deck's editor; the
//          title is selected and typed over, and the editor saves ("saved")
//
//   DEMO_ASK    the request (default: a deck for a coffee workshop)
//   DEMO_TITLE  what is typed over the first slide's title
//   DEMO_DRY    "1": everything up to the request, without sending it
// The rest is the environment of clip-nodes2-common.cjs (DEMO_URL, DEMO_LOCK,
// DEMO_LOCK_OWNER, ...).
const { open } = require('./clip-nodes2-common.cjs');
const fs = require('fs');
const path = require('path');

const OUT = process.argv[2];
if (!OUT) { console.error('usage: node clip-nodes2-take.cjs <take folder>'); process.exit(2); }
const ASK = process.env.DEMO_ASK || 'Make a four-slide deck on brewing pour-over coffee';
const TITLE = process.env.DEMO_TITLE || 'Pour-over, step by step';
const HAND = 62;   // ms between two keys typed into the slide, a person's pace
const CHAT = 55;   // ms between two keys of the request

(async () => {
  const rig = await open(OUT);
  const { page, sleep, click, look, log, W, H } = rig;

  // Frames of the wait that the cut never shows are deleted as the take goes:
  // everything older than a few seconds, except the first second and the
  // seconds around a moment the cut needs.
  const keep = [];   // [from, to] in screencast seconds
  let pruneFrom = Infinity;   // the start of the wait: nothing before it is touched
  const prune = (before) => {
    const frames = rig.frames;
    for (let i = frames.length - 1; i >= 0; i--) {
      const f = frames[i];
      if (f.ts >= before || f.ts < pruneFrom) continue;
      if (keep.some(([a, b]) => f.ts >= a && f.ts <= b)) continue;
      try { fs.unlinkSync(path.join(OUT, f.name)); } catch { /* gone */ }
      frames.splice(i, 1);
    }
  };

  try {
    await page.goto(rig.URL, { waitUntil: 'domcontentloaded' });
    await sleep(3500);
    await rig.closeNotice();
    const intro = page.getByText('Skip introduction').first();
    if (await intro.waitFor({ state: 'visible', timeout: 3000 }).then(() => true, () => false)) await click(intro, { post: 800 });
    await rig.chatInput().waitFor({ state: 'visible' });
    await rig.toEnd();
    // The pointer waits on an empty stretch of the rail: over the conversation
    // it would bring up the conversation's scrollbar.
    await rig.moveTo(44, 368, 400);
    await sleep(1500);
    await look('0-start');
    if (await page.getByText(/run(s)? as administrator/).first().isVisible().catch(() => false)) throw new Error('the administrator notice is still there');
    const cards0 = await page.locator('[data-testid="page-card"]').count();
    const bubbles0 = await rig.bubbles();
    const decksBefore = new Set(((await rig.api('api/nodes'))?.nodes || []).map((n) => n.id));
    if (process.env.DEMO_DRY) { log('dry run: the start looks like look-0-start.png'); await rig.close(); return; }

    // ---- ask --------------------------------------------------------------
    await rig.film('ask');
    await sleep(300);
    await click(rig.chatInput(), { post: 280 });
    await rig.type('ask', ASK, CHAT);
    await sleep(520);
    await page.keyboard.press('Enter');
    rig.moment('sent');

    // ---- wait -------------------------------------------------------------
    await rig.film('wait');
    const w0 = rig.now();
    pruneFrom = w0;
    keep.push([w0 - 0.1, w0 + 1.5]);
    const t0 = Date.now();
    const seen = {};
    let cardBubbles = null;
    let lastPrune = Date.now();
    for (;;) {
      const s = await page.evaluate(() => ({
        bubbles: document.querySelectorAll('[data-testid="lead-bubble"]').length,
        cards: document.querySelectorAll('[data-testid="page-card"]').length,
      }));
      const at = rig.now();
      if (!seen.said && s.bubbles > bubbles0) { seen.said = true; rig.moment('said'); keep.push([at - 1.5, at + 2]); log('said'); }
      if (!seen.card && s.cards > cards0) { seen.card = true; cardBubbles = s.bubbles; rig.moment('card'); keep.push([at - 1.5, at + 3]); log('card'); }
      if (seen.card && !seen.answer && s.bubbles > cardBubbles) { seen.answer = true; rig.moment('answer'); keep.push([at - 1.5, Infinity]); log('answer'); }
      if (Date.now() - t0 > 6000) {
        const lead = await rig.api('api/agent-chat/lead');
        if (lead && !lead.running) { rig.moment('over'); keep.push([at - 1.5, Infinity]); log('over'); break; }
      }
      if (Date.now() - lastPrune > 2000) { prune(rig.now() - 2.5); lastPrune = Date.now(); }
      await rig.noFailedTurn();
      if (Date.now() - t0 > 6 * 60 * 1000) throw new Error('the turn did not end within 6 minutes');
      await sleep(80);
    }
    if (!seen.card) throw new Error('the turn ended without the card of a node');
    const decks = ((await rig.api('api/nodes'))?.nodes || []).filter((n) => n.type === 'slides' && !decksBefore.has(n.id));
    if (!decks.length) throw new Error('the turn made no new slide deck');
    log('decks:', decks.map((d) => d.title).join(' | '));
    // The answer is read for a moment before the card is opened.
    await sleep(900);
    await look('1-answered');

    // ---- open -------------------------------------------------------------
    await rig.film('open');
    const preview = page.locator('[data-testid="page-card-preview"]:visible').last();
    await rig.clear();
    await rig.point(preview);
    await sleep(160);
    await rig.press();
    // The stage shows nothing for a moment before the deck's page is drawn
    // (an empty "Nothing here yet" flashes): the cut leaves that out.
    rig.moment('clicked');
    await sleep(120);
    const stage = page.locator('[data-testid="visualization-frame"]:visible').first();
    await stage.waitFor({ state: 'visible', timeout: 30000 });
    const frame = page.frameLocator('[data-testid="visualization-frame"]');
    await frame.locator('.dk.is-ready').first().waitFor({ state: 'visible', timeout: 30000 });
    rig.moment('page');
    const heading = frame.locator('.dk-cell.is-current [data-at="/slides/0/title"]').first();
    await heading.waitFor({ state: 'visible', timeout: 10000 });
    await sleep(250);
    await look('2-page');

    // ---- edit -------------------------------------------------------------
    await rig.film('edit');
    // A click on the title's words opens the editor on that slide. It goes
    // into the middle of the slide: further left or right would turn it.
    {
      const frameBox = await stage.boundingBox();
      const words = await heading.evaluate((el) => {
        const range = document.createRange();
        range.selectNodeContents(el);
        const r = range.getClientRects()[0] || el.getBoundingClientRect();
        return { x: r.left, y: r.top, w: r.width, h: r.height };
      });
      const x = Math.min(Math.max(frameBox.x + frameBox.width * 0.42, frameBox.x + words.x + 12), frameBox.x + words.x + words.w - 12);
      const y = frameBox.y + words.y + words.h / 2;
      // The way there is a person's: the slide is looked at on the way.
      await rig.moveTo(x, y, 1000);
      await sleep(350);
      await rig.press();
      await sleep(100);
    }
    const field = page.locator('[data-testid="slides-editor"] [data-field="title"]:visible').first();
    await field.waitFor({ state: 'visible', timeout: 20000 });
    rig.moment('editor');
    await sleep(300);
    const before = (await field.innerText()).trim();
    // Into the title on the slide, all of it selected, and the new one typed.
    {
      const box = await field.boundingBox();
      const words = await field.evaluate((el) => {
        const range = document.createRange();
        range.selectNodeContents(el);
        const all = range.getClientRects();
        const r = all[all.length - 1] || el.getBoundingClientRect();
        return { right: r.right, y: r.top + r.height / 2 };
      });
      await rig.clickAt(Math.min(box.x + box.width - 6, words.right - 4), words.y, { ms: 520, pre: 160, post: 220 });
      await page.keyboard.press('ControlOrMeta+a');
      await sleep(330);
      rig.moment('selected');
      await rig.type('title', TITLE, HAND);
      rig.moment('typed');
    }
    // The pointer moves off the slide while the editor saves by itself.
    const away = rig.moveTo(W * 0.5, H * 0.86, 900);
    const saveState = page.locator('[data-testid="node-editor-save-state"]').first();
    await rig.until(async () => (await saveState.getAttribute('data-state').catch(() => '')) === 'saved', 'the editor to save the title', 15000, 100);
    rig.moment('saved');
    await away;
    await sleep(1400);
    await look('3-saved');
    await rig.finish();

    const deck = decks[0];
    const nodes = await rig.api('api/nodes');
    const kept = (nodes?.nodes || []).filter((n) => n.type === 'slides');
    const latest = kept.find((n) => n.id === deck.id);
    if (latest) {
      const full = await rig.api('api/nodes/' + latest.id);
      rig.notes.node = { id: latest.id, title: latest.title, version: full?.version, layouts: (full?.spec?.slides || []).map((sl) => sl.layout || ''), titles: (full?.spec?.slides || []).map((sl) => sl.title || '') };
      log('stored:', JSON.stringify(rig.notes.node));
    }
    rig.notes.ask = ASK;
    rig.notes.title_before = before;
    rig.notes.title_typed = TITLE;
    rig.save();
  } catch (e) {
    await rig.fail(e);
  }
  await rig.close();
})();
