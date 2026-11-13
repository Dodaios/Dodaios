// Cuts the README video from the footage of record.cjs.
//
//   node scripts/readme_demo/render.cjs <take folder> [output.mp4]
//
// film.html draws the picture for any second of the film and edit.js says
// what is shown when. This script asks for every frame in turn, takes a
// picture of the page and hands the pictures to ffmpeg, then lays the music
// under them. Needs Node.js with Playwright, ffmpeg, and the frontend's
// node_modules for the two fonts (FILM_FONTS names another node_modules that
// has @fontsource-variable/inter and @fontsource/jetbrains-mono).
//
//   FILM_FPS      frames a second (default 30)
//   FILM_STILLS   "3,12.5,40": write only these seconds as PNG files, to
//                 look at a cut without rendering the film
//   FILM_RANGE    "10-20": render only these seconds, without music
//   FILM_MUSIC    the music file; without it the film is silent
//   FILM_PLAIN    1: a plain stage without the drifting lights (for the GIF)
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
const REPO = path.resolve(HERE, '..', '..');
const FPS = Number(process.env.FILM_FPS || 30);
const MUSIC = process.env.FILM_MUSIC || '';
const BROWSER = process.env.DEMO_BROWSER || '';

function fontFolder() {
  const tried = [process.env.FILM_FONTS, path.join(REPO, 'dodaios/ui/web/frontend/node_modules')].filter(Boolean);
  for (const dir of tried) if (fs.existsSync(path.join(dir, '@fontsource-variable/inter/files/inter-latin-opsz-normal.woff2'))) return dir;
  throw new Error('the fonts are missing: run npm install in dodaios/ui/web/frontend, or set FILM_FONTS (tried ' + tried.join(', ') + ')');
}
const dataUrl = (file) => 'data:font/woff2;base64,' + fs.readFileSync(file).toString('base64');

(async () => {
  const fonts = fontFolder();
  const take = JSON.parse(fs.readFileSync(path.join(TAKE_DIR, 'take.json'), 'utf8'));
  take.dir = TAKE_DIR;
  const logo = fs.readFileSync(path.join(REPO, 'assets/brand/dodaios-logo.svg'), 'utf8');

  const browser = await chromium.launch({
    ...(BROWSER ? { channel: BROWSER } : {}),
    args: ['--force-device-scale-factor=1', '--force-color-profile=srgb', '--hide-scrollbars', '--allow-file-access-from-files'],
  });
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => { console.error('page error:', e.message); process.exitCode = 1; });
  await page.addInitScript(({ take, logo, plain }) => { window.TAKE = take; window.LOGO_SVG = logo; window.PLAIN = plain; }, { take, logo, plain: Boolean(process.env.FILM_PLAIN) });
  await page.goto('file://' + path.join(HERE, 'film.html'));
  await page.addStyleTag({ content: `
    @font-face { font-family: "Film Sans"; font-weight: 100 900; src: url(${dataUrl(path.join(fonts, '@fontsource-variable/inter/files/inter-latin-opsz-normal.woff2'))}) format("woff2"); }
    @font-face { font-family: "Film Mono"; font-weight: 500; src: url(${dataUrl(path.join(fonts, '@fontsource/jetbrains-mono/files/jetbrains-mono-latin-500-normal.woff2'))}) format("woff2"); }` });
  await page.evaluate(() => Promise.all([document.fonts.load('640 66px "Film Sans"'), document.fonts.load('500 30px "Film Mono"')]));
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
