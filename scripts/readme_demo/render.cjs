// Cuts the README video from the footage of record.cjs.
//
//   node scripts/readme_demo/render.cjs <take folder> [output.mp4]
//
// film.html draws the picture for any second of the video and edit.js says
// what is shown when. This script asks for every frame in turn, takes a
// picture of the page and hands the pictures to ffmpeg, then lays the music
// under them. Needs Node.js with Playwright, and ffmpeg.
//
//   FILM_EDIT     the cut: edit.js (default, the longer film) or
//                 edit-agents.js (the agents clip)
//   FILM_FPS      frames a second (default 30)
//   FILM_CRF      x264's quality number (default 21; smaller is better and larger)
//   FILM_STILLS   "3,12.5,40": write only these seconds as PNG files, to
//                 look at a cut without rendering the video
//   FILM_RANGE    "10-20": render only these seconds, without music
//   FILM_MUSIC    the music file; without it the video is silent
//   FILM_DRAFT    1: quicker pictures, for a look at a cut
//
// The music is not in the repository. assets/demo/readme/README.md names the
// piece, its licence and where to download it.
const { chromium } = require('playwright');
const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const TAKE_DIR = path.resolve(process.argv[2] || '');
const OUT = path.resolve(process.argv[3] || path.join(TAKE_DIR, 'dodaios-intro.mp4'));
if (!process.argv[2] || !fs.existsSync(path.join(TAKE_DIR, 'take.json'))) {
  console.error('usage: node render.cjs <take folder> [output.mp4]');
  process.exit(2);
}
const HERE = __dirname;
const EDIT = path.resolve(HERE, process.env.FILM_EDIT || 'edit.js');
const FPS = Number(process.env.FILM_FPS || 30);
const MUSIC = process.env.FILM_MUSIC || '';
const BROWSER = process.env.DEMO_BROWSER || '';

(async () => {
  const take = JSON.parse(fs.readFileSync(path.join(TAKE_DIR, 'take.json'), 'utf8'));
  take.dir = TAKE_DIR;

  const browser = await chromium.launch({
    ...(BROWSER ? { channel: BROWSER } : {}),
    args: ['--force-device-scale-factor=1', '--force-color-profile=srgb', '--hide-scrollbars', '--allow-file-access-from-files'],
  });
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => { console.error('page error:', e.message); process.exitCode = 1; });
  await page.addInitScript((take) => { window.TAKE = take; }, take);
  await page.addInitScript({ path: EDIT });
  await page.goto('file://' + path.join(HERE, 'film.html'));
  const duration = await page.evaluate(() => window.DURATION);
  if (!duration) throw new Error('film.html did not come up');
  const seek = (t) => page.evaluate((s) => window.seek(s), t);

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
  const silent = OUT.replace(/\.mp4$/, '') + '.silent.mp4';
  // PNG pictures keep the flat surfaces flat, which the video codec thanks
  // with a file half the size; JPEG ones are quicker to take.
  const draft = Boolean(process.env.FILM_DRAFT);
  const ffmpeg = spawn('ffmpeg', ['-v', 'error', '-y', '-f', 'image2pipe', '-framerate', String(FPS), '-c:v', draft ? 'mjpeg' : 'png', '-i', '-',
    '-vf', 'format=yuv420p', '-c:v', 'libx264', '-preset', 'slow', '-crf', process.env.FILM_CRF || '21', '-movflags', '+faststart', '-an', silent],
  { stdio: ['pipe', 'inherit', 'inherit'] });
  const total = Math.round((to - from) * FPS);
  const started = Date.now();
  for (let n = 0; n < total; n++) {
    await seek(from + n / FPS);
    const shot = await page.screenshot(draft ? { type: 'jpeg', quality: 95 } : { type: 'png' });
    if (!ffmpeg.stdin.write(shot)) await new Promise((r) => ffmpeg.stdin.once('drain', r));
    if (n % 150 === 0) console.log(`frame ${n} of ${total}, ${((Date.now() - started) / 1000).toFixed(0)} s`);
  }
  ffmpeg.stdin.end();
  await new Promise((r) => ffmpeg.on('close', r));
  await browser.close();

  if (MUSIC && !process.env.FILM_RANGE) {
    // The film ends where the music does.
    const mux = spawnSync('ffmpeg', ['-v', 'error', '-y', '-i', silent, '-i', MUSIC,
      '-filter_complex', `[1:a]atrim=0:${duration},volume=-1dB,afade=t=out:st=${(duration - 0.6).toFixed(2)}:d=0.6[a]`,
      '-map', '0:v', '-map', '[a]', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', '-t', String(duration), OUT], { stdio: 'inherit' });
    if (mux.status !== 0) process.exit(1);
    fs.unlinkSync(silent);
  } else {
    fs.renameSync(silent, OUT);
  }
  console.log('wrote', OUT);
})().catch((e) => { console.error('FAILED:', e.message); process.exit(1); });
