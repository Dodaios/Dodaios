// Takes the README screenshots from the demo instance.
//
//   node scripts/readme_demo/stills.cjs <output folder> [memory plugins pets ide connect]
//
// Run it after record.cjs, against the same instance: the project is connected
// and a pet is chosen then. "connect" is the setup step and needs a first-run
// instance, so take it separately after a reset.
// The window is 1280 x 853 at a device scale of 1.5: 1920 x 1280 pictures.
const { chromium } = require('playwright');
const OUT = process.argv[2];
const URL = process.env.DEMO_URL || 'http://127.0.0.1:47990/';
if (!OUT) { console.error('usage: node stills.cjs <output folder> [names]'); process.exit(2); }
(async () => {
  const browser = await chromium.launch({ args: ['--force-device-scale-factor=1.5', '--window-size=1280,853', '--force-color-profile=srgb'] });
  const ctx = await browser.newContext({ viewport: null, colorScheme: 'dark', timezoneId: 'Europe/Berlin', locale: 'en-US' });
  const page = await ctx.newPage();
  page.setDefaultTimeout(15000);
  const sleep = (ms) => page.waitForTimeout(ms);
  const go = async (view) => { await page.goto(URL + '?view=' + view, { waitUntil: 'domcontentloaded' }); await sleep(4500); };
  const shot = async (name) => { await page.mouse.move(1279, 852); await sleep(300); await page.screenshot({ path: `${OUT}/${name}.png` }); console.log('shot', name); };
  const only = process.argv.slice(3);
  const want = (n) => !only.length || only.includes(n);

  if (want('memory')) {
    await go('memory');
    const memories = [
      ['I work mostly in Python and TypeScript.', 'About you'],
      ['trailhead is my hike-planning command-line tool; its tests run with pytest.', 'Projects'],
      ['Always run the tests before you call something done.', 'Standing instructions'],
      ['Sam reviews my pull requests.', 'People'],
      ['The staging server restarts every night at 02:00.', 'Facts & things'],
    ];
    for (const [text, kind] of memories) {
      if (await page.getByText(text).count()) continue;
      await page.getByText('New', { exact: true }).first().click(); await sleep(600);
      await page.keyboard.type(text, { delay: 5 });
      await page.getByText(kind, { exact: true }).first().click(); await sleep(200);
      await page.getByText('Remember', { exact: true }).first().click();
      await page.getByText('New memory').waitFor({ state: 'hidden' }); await sleep(900);
    }
    await go('memory');
    await page.getByText('Always run the tests before you call something done.').first().click(); await sleep(1200);
    await shot('memory');
  }
  if (want('plugins')) { await go('plugins'); await shot('plugins'); }
  if (want('pets')) {
    await go('pets');
    await page.mouse.move(800, 500); await page.mouse.wheel(0, 118); await sleep(900);
    await shot('pets');
  }
  if (want('ide')) {
    await go('agentic-ide');
    await page.locator('[aria-label="Show terminal"]').click(); await sleep(2500);
    await page.locator('[aria-label="Terminal input"]').click(); await sleep(300);
    await page.keyboard.type('clear && git log --oneline && python -m pytest -q', { delay: 10 }); await page.keyboard.press('Enter'); await sleep(2500);
    await shot('agentic-ide');
    await page.locator('[aria-label="Layout"]').first().click(); await sleep(900);
    await page.locator('[aria-label="Two side by side"]').first().click(); await sleep(1500);
    await page.locator('[aria-label="Layout"]').first().click(); await sleep(900);
    // The right tile: pick the CLIs section from the tile's own section menu.
    const title = page.locator('[data-testid="tile-section-button"]').nth(1);
    const picker = page.locator('[data-testid="section-picker"]');
    await title.click(); await sleep(500);
    if (!(await picker.isVisible().catch(() => false))) { await title.click(); await sleep(500); }
    await page.locator('[data-testid="section-pick-clis"]').click(); await sleep(2500);
    await shot('side-by-side');
  }
  if (want('connect')) {   // needs a first-run instance
    await page.goto(URL, { waitUntil: 'domcontentloaded' });
    const dlg = page.locator('[role=dialog]').first();
    await dlg.locator('input').first().waitFor({ timeout: 30000 }); await sleep(2000);
    await dlg.locator('input').first().fill('Dodaios');
    await page.getByRole('button', { name: /Continue/ }).click();
    await page.getByText('Connect your AI').waitFor(); await sleep(1500);
    await shot('connect');
  }
  await browser.close();
})().catch((e) => { console.error('FAILED', e.message.split('\n').slice(0, 5).join('\n')); process.exit(1); });
