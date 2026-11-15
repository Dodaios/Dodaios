// Cuts the PHONE clip from the footage of phone-take.cjs: render.cjs for a
// portrait frame (render.cjs is fixed at 1920 x 1080).
//
//   node scripts/readme_demo/phone-render.cjs <take folder> [output.mp4]
//
// phone-film.html draws the picture for any second of the video and
// edit-phone.js says what is shown when. This script asks for every frame in
// turn, takes a picture of the page and hands the pictures to ffmpeg. The
// video is as large as the phone's screen was filmed (780 x 1688) and has no
// sound. Needs Node.js with Playwright, and ffmpeg.
//
//   FILM_EDIT     the cut (default edit-phone.js)
//   FILM_FPS      frames a second (default 60)
//   FILM_CRF      x264's quality number (default 14; smaller is better and larger)
//   FILM_STILLS   "3,7.5,11": write only these seconds as PNG files, to look
//                 at a cut without rendering the video
//   FILM_RANGE    "4-8": render only these seconds
const { chromium } = require('playwright');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const TAKE_DIR = path.resolve(process.argv[2] || '');
const OUT = path.resolve(process.argv[3] || path.join(TAKE_DIR, 'phone.mp4'));
if (!process.argv[2] || !fs.existsSync(path.join(TAKE_DIR, 'take.json'))) {
  console.error('usage: node phone-render.cjs <take folder> [output.mp4]');
  process.exit(2);
}
const HERE = __dirname;
const EDIT = path.resolve(HERE, process.env.FILM_EDIT || 'edit-phone.js');
const FPS = Number(process.env.FILM_FPS || 60);
const BROWSER = process.env.DEMO_BROWSER || '';

(async () => {
  const take = JSON.parse(fs.readFileSync(path.join(TAKE_DIR, 'take.json'), 'utf8'));
  take.dir = TAKE_DIR;
  const width = Math.round(take.window.width * take.window.scale);
  const height = Math.round(take.window.height * take.window.scale);

  const browser = await chromium.launch({
    ...(BROWSER ? { channel: BROWSER } : {}),
    args: ['--force-device-scale-factor=1', '--force-color-profile=srgb', '--hide-scrollbars', '--allow-file-access-from-files'],
  });
  const ctx = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => { console.error('page error:', e.message); process.exitCode = 1; });
  await page.addInitScript((t) => { window.TAKE = t; }, take);
  await page.addInitScript({ path: EDIT });
  await page.goto('file://' + path.join(HERE, 'phone-film.html'));
  const duration = await page.evaluate(() => window.DURATION);
  if (!duration) throw new Error('phone-film.html did not come up');
  const seek = (t) => page.evaluate((s) => window.seek(s), t);
  console.log(`cut: ${duration.toFixed(2)} s, ${width} x ${height}`);

  if (process.env.FILM_STILLS) {
    for (const s of process.env.FILM_STILLS.split(',').map(Number)) {
      await seek(s);
      const file = path.join(path.dirname(OUT), `still-${s.toFixed(2).padStart(6, '0')}.png`);
      await page.screenshot({ path: file });
      console.log(file);
    }
    await browser.close();
    return;
  }

  const [from, to] = process.env.FILM_RANGE ? process.env.FILM_RANGE.split('-').map(Number) : [0, duration];
  // PNG pictures keep the flat surfaces flat, which the video codec thanks
  // with a smaller file.
  const ffmpeg = spawn('ffmpeg', ['-v', 'error', '-y', '-f', 'image2pipe', '-framerate', String(FPS), '-c:v', 'png', '-i', '-',
    '-vf', 'format=yuv420p', '-c:v', 'libx264', '-preset', 'slow', '-crf', process.env.FILM_CRF || '14',
    '-r', String(FPS), '-movflags', '+faststart', '-an', OUT],
  { stdio: ['pipe', 'inherit', 'inherit'] });
  const total = Math.round((to - from) * FPS);
  const started = Date.now();
  for (let n = 0; n < total; n++) {
    await seek(from + n / FPS);
    const shot = await page.screenshot({ type: 'png' });
    if (!ffmpeg.stdin.write(shot)) await new Promise((r) => ffmpeg.stdin.once('drain', r));
    if (n % 120 === 0) console.log(`frame ${n} of ${total}, ${((Date.now() - started) / 1000).toFixed(0)} s`);
  }
  ffmpeg.stdin.end();
  const code = await new Promise((r) => ffmpeg.on('close', r));
  await browser.close();
  if (code !== 0) throw new Error('ffmpeg failed');
  console.log('wrote', OUT);
})().catch((e) => { console.error('FAILED:', e.message); process.exit(1); });
