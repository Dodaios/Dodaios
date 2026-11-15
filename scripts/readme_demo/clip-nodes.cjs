// Films the Nodes clip of the README: a request in the chat becomes a
// whiteboard, the whiteboard is opened from its card in the chat and changed
// by hand, and it saves itself.
//
//   node scripts/readme_demo/clip-nodes.cjs <take folder>
//
// It expects a demo instance that nodes-plugins-setup.cjs set up and warmed up:
// a conversation in use, the assistant named DEMO_NAME, no whiteboard yet.
// The footage, in this order (nodes-plugins-cut.cjs cuts the clip from it):
//
//   ask    the pointer goes to the field; the request is typed and sent
//   wait   the assistant at work: its first message ("said"), the card of
//          the whiteboard ("card"), its answer ("answer"), the turn over ("over")
//   open   the whiteboard is opened from its card in the chat
//   edit   one box is dragged to another place, another box is renamed by
//          typing into it, and the board says it saved itself ("saved")
//
//   DEMO_ASK   the request (default: a launch plan on a whiteboard)
//   DEMO_DRY   "1": everything up to the request, without sending it
// The rest is the environment of nodes-plugins-common.cjs.
const { open } = require('./nodes-plugins-common.cjs');
const fs = require('fs');
const path = require('path');

const OUT = process.argv[2];
if (!OUT) { console.error('usage: node clip-nodes.cjs <take folder>'); process.exit(2); }
const ASK = process.env.DEMO_ASK || 'Put our launch plan on a whiteboard: research, build, beta, launch';
const RENAME = { from: /^beta$/i, to: 'Private beta' };
const MOVE = /^launch$/i;

(async () => {
  const rig = await open(OUT);
  const { page, sleep, click, look, log, W, H } = rig;

  // The editor's own scene: where each element stands on the canvas and how
  // the canvas is scrolled and zoomed, read from the embedded editor's state.
  const board = () => page.evaluate(() => {
    const root = document.querySelector('.excalidraw');
    if (!root) return null;
    const key = Object.keys(root).find((k) => k.startsWith('__reactFiber$'));
    let fiber = key ? root[key] : null;
    for (let i = 0; fiber && i < 80; i++, fiber = fiber.return) {
      const inst = fiber.stateNode;
      if (inst && inst.state && inst.state.zoom && typeof inst.state.scrollX === 'number' && inst.scene) {
        const s = inst.state;
        const els = inst.scene.getNonDeletedElements().map((e) => ({ id: e.id, type: e.type, x: e.x, y: e.y, w: e.width, h: e.height, text: e.text || '', containerId: e.containerId || null }));
        return { zoom: s.zoom.value, scrollX: s.scrollX, scrollY: s.scrollY, left: s.offsetLeft, top: s.offsetTop, editing: Boolean(s.editingTextElement || s.editingElement), els };
      }
    }
    return null;
  });
  const centre = (b, el) => [(el.x + el.w / 2 + b.scrollX) * b.zoom + b.left, (el.y + el.h / 2 + b.scrollY) * b.zoom + b.top];
  const boxLabelled = (b, re) => {
    const label = b.els.find((e) => e.type === 'text' && e.containerId && re.test(e.text.trim()));
    return label ? b.els.find((e) => e.id === label.containerId) : null;
  };
  const saveState = () => page.locator('[data-testid="whiteboard-save-state"]').first().getAttribute('data-state').catch(() => null);

  try {
    await page.goto(rig.URL, { waitUntil: 'domcontentloaded' });
    await sleep(3500);
    const intro = page.getByText('Skip introduction').first();
    if (await intro.waitFor({ state: 'visible', timeout: 3000 }).then(() => true, () => false)) await click(intro, { post: 800 });
    await rig.chatInput().waitFor({ state: 'visible' });
    await rig.toEnd();
    // The pointer waits on an empty stretch of the rail: over the conversation
    // it would bring up the conversation's scrollbar.
    await rig.moveTo(44, 396, 400);
    await sleep(1500);
    await look('0-start');
    const cards0 = await page.locator('[data-testid="page-card"]').count();
    const bubbles0 = await rig.bubbles();
    if (process.env.DEMO_DRY) { log('dry run: the start looks like look-0-start.png'); await rig.close(); return; }

    // ---- ask --------------------------------------------------------------
    await rig.film('ask');
    await sleep(300);
    await click(rig.chatInput(), { post: 280 });
    await rig.type('ask', ASK);
    await sleep(520);
    await page.keyboard.press('Enter');
    rig.moment('sent');

    // ---- wait -------------------------------------------------------------
    await rig.film('wait');
    const t0 = Date.now();
    const seen = {};
    let cardBubbles = null;
    for (;;) {
      const s = await page.evaluate(() => ({
        bubbles: document.querySelectorAll('[data-testid="lead-bubble"]').length,
        cards: document.querySelectorAll('[data-testid="page-card"]').length,
      }));
      if (!seen.said && s.bubbles > bubbles0) { seen.said = true; rig.moment('said'); log('said'); }
      if (!seen.card && s.cards > cards0) { seen.card = true; cardBubbles = s.bubbles; rig.moment('card'); log('card'); }
      if (seen.card && !seen.answer && s.bubbles > cardBubbles) { seen.answer = true; rig.moment('answer'); log('answer'); }
      if (Date.now() - t0 > 6000) {
        const lead = await rig.api('api/agent-chat/lead');
        if (lead && !lead.running) { rig.moment('over'); log('over'); break; }
      }
      await rig.noFailedTurn();
      if (Date.now() - t0 > 5 * 60 * 1000) throw new Error('the turn did not end within 5 minutes');
      await sleep(80);
    }
    if (!seen.card) throw new Error('the turn ended without the card of a node');
    // The answer is read for a moment before the card is opened.
    await sleep(700);
    await look('1-answered');

    // ---- open -------------------------------------------------------------
    await rig.film('open');
    await click(page.locator('[data-testid="page-card-title"]:visible').last(), { post: 120 });
    await page.locator('[data-testid="whiteboard-editor"]').waitFor({ state: 'visible', timeout: 20000 });
    // While the editor draws the board, the pointer goes over to it.
    let b = null;
    const drift = rig.moveTo(W * 0.62, H * 0.74, 1000);
    for (let i = 0; i < 100; i++) {
      b = await board();
      if (b && boxLabelled(b, MOVE) && boxLabelled(b, RENAME.from)) break;
      await sleep(100);
    }
    await drift;
    if (!b || !boxLabelled(b, MOVE) || !boxLabelled(b, RENAME.from)) throw new Error('the board has no boxes labelled as expected: ' + JSON.stringify((b?.els || []).filter((e) => e.type === 'text').map((e) => e.text)));
    // The board draws its labels on a canvas, where no page helper can
    // change them: a label with a value that must not be in the picture ends the take.
    if (b.els.some((e) => rig.leaky(e.text))) throw new Error('a label on the board holds a value that must not be in the picture');
    await sleep(250);
    await look('2-board');
    fs.writeFileSync(path.join(OUT, 'board-before.json'), JSON.stringify(b, null, 1));

    // ---- edit -------------------------------------------------------------
    await rig.film('edit');
    // The last box goes under the one before it.
    const moving = boxLabelled(b, MOVE), before = boxLabelled(b, RENAME.from);
    const [mx, my] = centre(b, moving);
    const [px, py] = centre(b, before);
    const tx = px, ty = Math.min(H - 116, py + before.h * b.zoom + 55 + (moving.h * b.zoom) / 2 - 2);
    await rig.moveTo(mx, my);
    await sleep(160);
    await page.mouse.down();
    await sleep(110);
    await rig.glide(tx, ty, 1000);
    await sleep(110);
    await page.mouse.up();
    rig.moment('moved');
    await sleep(380);
    // The box before it gets a new name, typed into it.
    b = await board();
    const [rx, ry] = centre(b, boxLabelled(b, RENAME.from));
    await rig.moveTo(rx, ry);
    await sleep(140);
    await page.mouse.dblclick(rx, ry);
    await sleep(420);
    const field = await page.evaluate(() => { const t = document.querySelector('textarea.excalidraw-wysiwyg'); return t ? { value: t.value, from: t.selectionStart, to: t.selectionEnd } : null; });
    if (!field) throw new Error('the double-click did not open the label for editing');
    if (field.from !== 0 || field.to !== field.value.length) await page.keyboard.press(process.platform === 'darwin' ? 'Meta+A' : 'Control+A');
    await rig.type('label', RENAME.to, 58);
    await sleep(320);
    await page.keyboard.press('Escape');
    rig.moment('renamed');
    // The pointer moves off the board's boxes while the board saves itself.
    const away = rig.moveTo(W * 0.70, H * 0.33, 900);
    const t1 = Date.now();
    let state = null;
    for (;;) {
      state = await saveState();
      if (state === 'saved' && Date.now() - t1 > 900) break;
      if (Date.now() - t1 > 8000) throw new Error('the board did not say it saved (state ' + state + ')');
      await sleep(60);
    }
    rig.moment('saved');
    await away;
    await sleep(1100);
    await look('3-saved');
    await rig.finish();

    // What the board holds now, as the app stored it.
    const nodes = await rig.api('api/nodes');
    const wb = (nodes?.nodes || []).find((x) => x.type === 'whiteboard');
    if (wb) {
      const scene = await rig.api(`api/nodes/${wb.id}/scene`);
      rig.notes.node = { id: wb.id, title: wb.title, version: scene?.version, labels: (scene?.scene?.elements || []).filter((e) => e.type === 'text' && !e.isDeleted).map((e) => e.text) };
      log('stored:', JSON.stringify(rig.notes.node));
    }
    rig.notes.ask = ASK;
    rig.save();
  } catch (e) {
    await rig.fail(e);
  }
  await rig.close();
})();
