// Not filmed: sends one request to the assistant and writes down what the app
// does with it, with a picture every few seconds. For finding out how a
// request for the clip at the top of the README really goes before it is
// filmed (clip-reel-take.cjs).
//
//   DEMO_SAY=... node scripts/readme_demo/clip-reel-probe.cjs <folder>
//
//   DEMO_SAY        the request ("" sends nothing and only looks)
//   DEMO_APPROVE    "1": an approval card is answered with "Allow once";
//                   "always": with "Always allow" where the card offers it;
//                   "look": not answered, the probe stops 8 s after it came
//   DEMO_STANCE     set the chat's permission stance first ("Auto-accept edits")
//   DEMO_PROBE_SECS how long to watch at most (default 600)
//   DEMO_VIEW       "ide": watch the Agentic IDE instead of the chat
const { open } = require('./clip-reel-common.cjs');

const OUT = process.argv[2];
if (!OUT) { console.error('usage: node clip-reel-probe.cjs <folder>'); process.exit(2); }
const SAY = process.env.DEMO_SAY || '';
const SECS = Number(process.env.DEMO_PROBE_SECS || 600);

(async () => {
  const rig = await open(OUT);
  const { page, sleep, click, log, look } = rig;
  try {
    await page.goto(rig.URL, { waitUntil: 'domcontentloaded' });
    await sleep(3500);
    await rig.closeNotice();
    const intro = page.getByText('Skip introduction').first();
    if (await intro.waitFor({ state: 'visible', timeout: 3000 }).then(() => true, () => false)) await click(intro, { post: 800 });
    await rig.chatInput().waitFor({ state: 'visible' });
    await rig.toEnd();
    if (process.env.DEMO_STANCE) {
      // The chat's permission stance, by its own menu in the message field.
      await click('[data-testid="composer-permission"]:visible', { post: 600 });
      await click(page.getByText(process.env.DEMO_STANCE, { exact: true }).last(), { post: 600 });
      log('stance:', await page.locator('[data-testid="composer-permission"]:visible').first().getAttribute('aria-label'));
    }
    await look('p-000-start');
    if (SAY) {
      await click(rig.chatInput(), { post: 200 });
      await page.keyboard.type(SAY, { delay: 4 });
      await page.keyboard.press('Enter');
    }
    if (process.env.DEMO_VIEW === 'ide') { await sleep(Number(process.env.DEMO_VIEW_AFTER || 45) * 1000); await click('[data-testid="surface-ide"]', { post: 1500 }); }
    const t0 = Date.now();
    let lastLook = 0; let last = '', n = 0, idle = 0, approved = 0;
    while (Date.now() - t0 < SECS * 1000) {
      const lead = await rig.api('api/agent-chat/lead');
      const threads = ((await rig.api('api/agent-chat/sessions?surface=agent'))?.sessions || []);
      const s = await page.evaluate(() => ({
        bubbles: document.querySelectorAll('[data-testid="lead-bubble"]').length,
        cards: document.querySelectorAll('[data-testid="page-card"]').length,
        links: document.querySelectorAll('[data-testid="coding-agent-link"]').length,
        approvals: document.querySelectorAll('[data-testid="thread-approval"]').length,
        outcomes: document.querySelectorAll('[data-testid="approval-outcome"]').length,
      }));
      const state = JSON.stringify({ lead: Boolean(lead?.running), threads: threads.map((t) => `${t.title?.slice(0, 30)}|${t.model}|${t.running ? 'run' : 'idle'}`), ...s });
      if (state !== last) {
        last = state;
        log(state);
        if (process.env.DEMO_VIEW !== 'ide') await rig.toEnd();
        await sleep(400);
        await look('p-' + String(++n).padStart(3, '0'));
      } else if (process.env.DEMO_VIEW === 'ide' && Date.now() - lastLook > 12000) { lastLook = Date.now(); await look('p-ide-' + String(++n).padStart(3, '0')); }
      if (s.approvals > 0 && process.env.DEMO_APPROVE && approved < 8) {
        approved++;
        const card = page.locator('[data-testid="thread-approval"]:visible').last();
        log('approval card:', (await card.innerText().catch(() => '')).replace(/\s+/g, ' ').slice(0, 500));
        await sleep(1500);
        if (process.env.DEMO_APPROVE === 'look') { await sleep(6500); await look('p-card'); break; }
        const always = card.locator('[data-testid="action-card-always"]');
        if (process.env.DEMO_APPROVE === 'always' && (await always.count())) {
          await click(always, { post: 900 });
          await look('p-always-' + approved);
          log('chooser:', (await card.innerText().catch(() => '')).replace(/\s+/g, ' ').slice(0, 500));
          // The wide rule: every command of this chat, not only this one.
          const wide = card.getByRole('radio', { name: /^All of / }).first();
          if (await wide.count()) { await click(wide, { post: 600 }); await look('p-wide-' + approved); log('wide:', (await card.innerText().catch(() => '')).replace(/\s+/g, ' ').slice(-260)); }
          const save = card.locator('[data-testid="action-card-rule-save"]');
          if (await save.count()) await click(save, { post: 800 });
        } else await click(card.locator('[data-testid="action-card-allow"]'), { post: 800 });
        await look('p-approved-' + approved);
      }
      if (!lead?.running && !threads.some((t) => t.running)) { if (!idle) idle = Date.now(); else if (Date.now() - idle > 12000 && Date.now() - t0 > 25000) break; } else idle = 0;
      await sleep(700);
    }
    await rig.toEnd();
    await sleep(500);
    await look('p-end');
    const said = await page.evaluate(() => [...document.querySelectorAll('[data-testid="lead-bubble"]')].slice(-4).map((b) => b.innerText).join('\n---\n'));
    log('said:', said.replace(/\s+/g, ' ').slice(0, 1500));
  } catch (e) {
    await rig.fail(e);
  }
  await rig.close();
})();
