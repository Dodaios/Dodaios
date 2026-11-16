// Films the second Assistant clip of the README: a question about a file on
// the computer, answered in the chat with a chart.
//
//   node scripts/readme_demo/clip-assistant2-assistant.cjs <take folder>
//
// It expects a demo instance that clip-assistant2-setup.cjs set up and warmed
// up, with Documents/bank-2026.csv in its home folder (clip-assistant2-bank.py).
// No plugin and no outside account: the assistant reads the file on the
// computer and works the numbers out itself. The footage, in this order
// (clip-assistant2-cut.cjs cuts the clip from it):
//
//   ask      the pointer goes to the field, the question is typed and sent
//   wait     the assistant at work: its first message ("said"), the chart
//            card ("chart"), its last message ("answer"), the turn over
//            ("over"); every line the panel shows under its name is a moment
//            "line" too, with the text in the notes
//   answer   the answer is read: the pointer goes along the chart's columns,
//            which show their values on hover
//
//   DEMO_ASK   the question (default: groceries per month, from the bank export)
const { open } = require('./clip-assistant2-common.cjs');

const OUT = process.argv[2];
if (!OUT) { console.error('usage: node clip-assistant2-assistant.cjs <take folder>'); process.exit(2); }
const ASK = process.env.DEMO_ASK || 'How much did I spend on groceries each month this year? The bank export is in Documents.';

(async () => {
  const rig = await open(OUT);
  const { page, sleep, click, look, log, W, H } = rig;
  try {
    await page.goto(rig.URL, { waitUntil: 'domcontentloaded' });
    await sleep(3500);
    const intro = page.getByText('Skip introduction').first();
    if (await intro.waitFor({ state: 'visible', timeout: 3000 }).then(() => true, () => false)) await click(intro, { post: 800 });
    await rig.closeBanner(6000);
    await rig.chatInput().waitFor({ state: 'visible' });
    await rig.toEnd();
    await rig.moveTo(W * 0.42, H * 0.36, 400);
    await sleep(1500);
    await look('0-start');
    // What the window says in words, at a few moments: clip-assistant2-ocr.py
    // looks through it for text that must not be in the picture.
    const texts = [];
    const snap = async (when) => texts.push({ when, text: await page.evaluate(() => document.body.innerText).catch(() => '') });
    await snap('start');
    const bubbles0 = await rig.bubbles();
    const charts0 = await page.locator('[data-testid="chart-fence"]').count();

    // ---- ask ----------------------------------------------------------------
    await rig.film('ask');
    await sleep(300);
    await click(rig.chatInput(), { post: 260 });
    await rig.type('ask', ASK);
    await sleep(420);
    await page.keyboard.press('Enter');
    rig.moment('sent');

    // ---- wait ---------------------------------------------------------------
    await rig.film('wait');
    const t0 = Date.now();
    const seen = {};
    const lines = [];
    let lastBubbles = bubbles0, lastBubbleAt = null, lastLine = '';
    let fullUntil = Date.now() + 900;
    const full = (ms) => { fullUntil = Math.max(fullUntil, Date.now() + ms); rig.rate(60); };
    for (;;) {
      if (Date.now() > fullUntil) rig.rate(5);
      const s = await page.evaluate(() => ({
        bubbles: document.querySelectorAll('[data-testid="lead-bubble"]').length,
        charts: document.querySelectorAll('[data-testid="chart-fence"]').length,
        pending: document.querySelectorAll('[data-testid="chart-fence-pending"]').length,
        line: ((document.querySelector('[data-testid="assistant-panel-status"]') || {}).innerText || '').trim(),
      }));
      if (s.line && s.line !== lastLine) { lastLine = s.line; lines.push({ at: rig.now(), line: s.line }); rig.moment('line'); full(1500); log('panel:', s.line); }
      if (!seen.said && s.bubbles > bubbles0) { seen.said = true; full(2500); rig.moment('said'); log('said'); }
      if (!seen.pending && s.pending) { seen.pending = true; full(3000); rig.moment('pending'); log('chart pending'); }
      if (!seen.chart && s.charts > charts0) { seen.chart = true; full(3500); rig.moment('chart'); log('chart'); await snap('chart'); }
      if (s.bubbles > lastBubbles) { full(3000); lastBubbleAt = rig.now(); log('message'); }
      lastBubbles = Math.max(lastBubbles, s.bubbles);
      if (Date.now() - t0 > 6000) {
        const lead = await rig.api('api/agent-chat/lead');
        if (lead && !lead.running) { rig.rate(60); rig.moment('over'); log('over'); break; }
      }
      await rig.noFailedTurn();
      if (Date.now() - t0 > 6 * 60 * 1000) throw new Error('the turn did not end within 6 minutes');
      await sleep(80);
    }
    // The chart card is drawn a moment after the turn is over.
    for (let i = 0; i < 60 && !seen.chart; i++) {
      if ((await page.locator('[data-testid="chart-fence"]').count()) > charts0) { seen.chart = true; rig.moment('chart'); log('chart'); await snap('chart'); }
      else await sleep(80);
    }
    if (!seen.chart) throw new Error('the answer has no chart');
    if (lastBubbleAt !== null) rig.moment('answer', lastBubbleAt);
    await sleep(900);
    await look('2-answered');

    // ---- answer -------------------------------------------------------------
    await rig.film('answer');
    const chart = page.locator('[data-testid="chart-fence"]').last();
    const plot = chart.locator('[data-testid="chart-fence-plot"]').first();
    const b = await plot.boundingBox();
    if (!b) throw new Error('the chart is not on screen');
    if (b.y < 30 || b.y + b.height > H - 10) log('warning: the chart is not wholly in the window', JSON.stringify(b));
    // To the chart's first column, then along the columns at a reader's
    // pace: each one shows its value on hover.
    const y = b.y + b.height * 0.55;
    await rig.moveTo(b.x + b.width * 0.07, y, 900);
    rig.moment('hover');
    await sleep(350);
    await rig.glide(b.x + b.width * 0.66, y, 2300);
    await sleep(900);
    await look('3-read');
    await snap('end');
    rig.notes.ask = ASK;
    rig.notes.panel_lines = lines.map((l) => l.line);
    rig.notes.answer_text = (await page.locator('[data-testid="lead-bubble"]').last().innerText().catch(() => '')).slice(0, 2000);
    rig.notes.chart_box = b;
    rig.notes.texts = texts;
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
