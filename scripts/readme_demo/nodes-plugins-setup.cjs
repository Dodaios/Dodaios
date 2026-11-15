// Sets up the demo instance for the Nodes clip and the Assistant clip of the
// README. Nothing here is filmed.
//
//   node scripts/readme_demo/nodes-plugins-setup.cjs <folder for its pictures>
//
// It expects a first-run instance of demo-instance.sh at DEMO_URL and does
// what a person did on their first morning with the app:
//
//   setup    the first-run dialog (the assistant gets its name, DEMO_NAME),
//            the guided walk skipped, both sample projects connected
//   warmup   four requests to the assistant, so the clips show a
//            conversation that is in use: how long its answers should be and
//            a first question about the GitHub repository (answered with the
//            GitHub plugin, which plugins_connect.py connected before), a
//            first node, a small errand in a project, and three short
//            questions in one
//
// DEMO_PARTS names the parts to run (default "setup,warmup"). DEMO_MODEL is
// the assistant's model. Every request of the warm-up is a real turn of a
// real model.
const { open } = require('./nodes-plugins-common.cjs');

const OUT = process.argv[2];
if (!OUT) { console.error('usage: node nodes-plugins-setup.cjs <folder for its pictures>'); process.exit(2); }
const PARTS = (process.env.DEMO_PARTS || 'setup,warmup').split(',');
const NAME = process.env.DEMO_NAME || 'Nova';
const MODEL = process.env.DEMO_MODEL || 'Claude Opus 5.5';
// The repository the Assistant clip asks about, as owner/name.
const REPO = process.env.DEMO_REPO || 'Dodaios/acme-notes';

// The requests use the GitHub plugin once and several different tools, so the
// app's achievements for a first plugin call and for five different tools
// ("First MCP Connection", "Tool Dabbler", "Triple Combo") come up here and
// not as a toast in a clip. The last one is short: its answer is what the
// clips open on.
const WARMUP = [
  `From now on, answer me in two sentences unless I ask for more. Our notes app lives on GitHub in ${REPO}: what was the last commit on main?`,
  "Write a short doc for Thursday's launch review: status, risks, open questions. A few lines each, made up from what a small notes app would have.",
  'Run the tests of the trailhead project, tell me the result in one line, and remind me tomorrow at 9 to check the month-end numbers.',
  'Which plugins are connected, what is my wake word, and which reminders are set? One line each.',
];

(async () => {
  const rig = await open(OUT);
  const { page, sleep, click, btn, log, look } = rig;
  try {
    await page.goto(rig.URL, { waitUntil: 'domcontentloaded' });
    await sleep(3000);

    if (PARTS.includes('setup')) {
      log('setup');
      const dlg = page.locator('[role=dialog]').first();
      await dlg.locator('input').first().waitFor({ state: 'visible', timeout: 30000 });
      await click(dlg.locator('input').first(), { post: 200 });
      await page.keyboard.type(NAME, { delay: 20 });
      await look('setup-1-name');
      await click(btn(/Continue/), { post: 500 });
      await page.getByText('Connect your AI').waitFor();
      await page.getByText(/^Signed in/).first().waitFor({ timeout: 30000 });
      await click(btn(/^Continue/), { post: 500 });
      await page.getByText(/How you'll talk to/).waitFor();
      await click(btn(/Show me around/), { post: 600 });
      // The guided walk: its bubble takes a moment to listen.
      const next = btn(/^Next$/);
      await next.waitFor({ state: 'visible' });
      await sleep(1500);
      for (let i = 0; i < 4 && (await next.isVisible().catch(() => false)); i++) {
        await click(page.getByText('Skip', { exact: true }).last(), { post: 1000 });
      }
      const intro = page.getByText('Skip introduction').first();
      if (await intro.waitFor({ state: 'visible', timeout: 2500 }).then(() => true, () => false)) await click(intro, { post: 500 });
      await look('setup-2-after-walk');

      // Both sample projects, in the Agentic IDE.
      const connectProject = async (name) => {
        const empty = btn(/^Connect folder$/).first();
        if (await empty.isVisible().catch(() => false)) await click(empty, { post: 500 });
        else await click('[aria-label="Connect project"]', { post: 500 });
        await click(btn(/Choose folder/), { post: 650 });
        const picker = page.locator('[role=dialog]').last();
        for (const step of ['Home', 'projects', name]) await click(picker.getByText(step, { exact: true }).first(), { post: 450 });
        await click(btn(/Use this folder/), { post: 450 });
        await click(btn(/^Connect project$/), { post: 1200 });
      };
      await click('[data-testid="surface-ide"]', { post: 1200 });
      await connectProject('ledger');
      await connectProject('trailhead');
      await look('setup-3-projects');
      await click('[data-testid="surface-dodaios"]', { post: 900 });
      await rig.chatInput().waitFor({ state: 'visible' });
      const again = page.getByText('Skip introduction').first();
      if (await again.waitFor({ state: 'visible', timeout: 6000 }).then(() => true, () => false)) {
        await click(again, { post: 800 });
        await again.waitFor({ state: 'hidden', timeout: 8000 }).catch(() => {});
      }
      await look('setup-4-chat');
    }

    if (PARTS.includes('warmup')) {
      log('warm-up');
      const railChats = rig.rail('chats');
      if (await railChats.isVisible().catch(() => false)) await click(railChats, { post: 800 });
      await rig.chatInput().waitFor({ state: 'visible' });
      const intro = page.getByText('Skip introduction').first();
      if (await intro.waitFor({ state: 'visible', timeout: 6000 }).then(() => true, () => false)) {
        await click(intro, { post: 800 });
        await intro.waitFor({ state: 'hidden', timeout: 8000 }).catch(() => {});
      }
      // The assistant's model.
      await click('[aria-label="Model"]:visible', { post: 600 });
      await click(page.getByText(MODEL, { exact: true }).last(), { post: 450 });
      const only = process.env.DEMO_WARMUP ? process.env.DEMO_WARMUP.split(',').map(Number) : WARMUP.map((_, i) => i);
      for (const i of only) {
        await click(rig.chatInput(), { post: 200 });
        await page.keyboard.type(WARMUP[i], { delay: 4 });
        await page.keyboard.press('Enter');
        await rig.settled('warm-up request ' + (i + 1), { startsWithin: 25000 });
        await sleep(1500);
        await look('warmup-' + (i + 1));
      }
      const unlocked = ((await rig.api('api/board/achievements'))?.items || []).filter((a) => a.unlocked || a.unlocked_at).map((a) => a.id);
      log('achievements so far:', unlocked.join(', ') || 'none');
      for (const id of ['tool_dabbler', 'triple_combo']) {
        if (!unlocked.includes(id)) log(`warning: the achievement "${id}" is still to come and may show as a toast in a clip`);
      }
    }
  } catch (e) {
    await rig.fail(e);
  }
  await rig.close();
})();
