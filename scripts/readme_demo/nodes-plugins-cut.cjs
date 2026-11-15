// Cuts the Nodes clip or the Assistant clip of the README from its footage.
//
//   node scripts/readme_demo/nodes-plugins-cut.cjs <take folder> <nodes|assistant> <output.mp4>
//
// The take folder is what clip-nodes.cjs or clip-assistant.cjs filmed: the
// frames and take.json. The cut is in nodes-plugins-edit.cjs: which stretch of
// footage is shown when. This script turns it into a video and nothing else:
//
//   - a frame of the video is a frame of the footage, pixel for pixel: the
//     one that was on screen at that moment (the newest one not after it);
//   - where the cut leaves a wait out, the picture before it dissolves into
//     the one after it (0.3 s);
//   - 1920 x 1080, 60 frames a second, H.264, no sound.
//
// It also writes <output>.cut.json: every shot with its seconds in the video
// and in the take, and how fast the whole cut plays. Needs ffmpeg.
//
//   CUT_CRF     x264's quality number (default 14)
//   CUT_STILLS  "0,3.5,12": write only these seconds as PNG files beside the
//               output, to look at a cut without encoding it
//   CUT_PLAN    "1": print the shots and how fast they play, and nothing else
const { spawnSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const EDITS = require('./nodes-plugins-edit.cjs');

const TAKE_DIR = path.resolve(process.argv[2] || '');
const CLIP = process.argv[3];
const OUT = path.resolve(process.argv[4] || '');
if (!process.argv[4] || !EDITS[CLIP] || !fs.existsSync(path.join(TAKE_DIR, 'take.json'))) {
  console.error('usage: node nodes-plugins-cut.cjs <take folder> <nodes|assistant> <output.mp4>');
  process.exit(2);
}
const FPS = 60;
const DISSOLVE = 0.3;
const CRF = process.env.CUT_CRF || '14';

const take = JSON.parse(fs.readFileSync(path.join(TAKE_DIR, 'take.json'), 'utf8'));

// A frame of another size than the window's (a picture taken for a look while
// the screencast ran) is left out: the frame before it stays on screen.
const WIDTH = Math.round(take.window.width * take.window.scale), HEIGHT = Math.round(take.window.height * take.window.scale);
function jpegSize(file) {
  const fd = fs.openSync(file, 'r');
  const buf = Buffer.alloc(65536);
  const n = fs.readSync(fd, buf, 0, buf.length, 0);
  fs.closeSync(fd);
  for (let i = 2; i + 9 < n;) {
    if (buf[i] !== 0xff) { i++; continue; }
    const marker = buf[i + 1];
    if (marker >= 0xc0 && marker <= 0xc2) return [buf.readUInt16BE(i + 7), buf.readUInt16BE(i + 5)];
    i += 2 + buf.readUInt16BE(i + 2);
  }
  return null;
}
const odd = take.frames.filter((f) => { const size = jpegSize(path.join(TAKE_DIR, f.name)); return !size || size[0] !== WIDTH || size[1] !== HEIGHT; });
if (odd.length) {
  console.log(`left out ${odd.length} frame(s) of another size than ${WIDTH} x ${HEIGHT}`);
  const skip = new Set(odd.map((f) => f.name));
  take.frames = take.frames.filter((f) => !skip.has(f.name));
}

// ---- the footage ---------------------------------------------------------------
const stretches = take.stretches.map((st, i) => ({ ...st, end: i + 1 < take.stretches.length ? take.stretches[i + 1].at : Infinity }));
const byName = {};
for (const st of stretches) {
  if (!st.name) continue;
  st.frames = take.frames.filter((f) => f.ts >= st.at && f.ts < st.end);
  if (!byName[st.name]) byName[st.name] = st;
}
// The frame on screen `s` seconds into the stretch.
function frameAt(name, s) {
  const st = byName[name];
  if (!st || !st.frames.length) throw new Error('no footage called ' + name);
  const ts = st.at + s;
  let lo = 0, hi = st.frames.length - 1;
  while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (st.frames[mid].ts <= ts) lo = mid; else hi = mid - 1; }
  return st.frames[lo].name;
}
const latest = (name) => take.marks.filter((x) => x.name === name).pop();
const footage = {
  has: (name) => Boolean(byName[name] && byName[name].frames.length),
  // How long a stretch is.
  length: (name) => { const st = byName[name]; return st ? Math.min(st.end, st.frames.length ? st.frames[st.frames.length - 1].ts + 0.5 : st.at) - st.at : 0; },
  // When a moment the take wrote down was, in the stretch's own seconds.
  at: (mark, stretch) => { const m = latest(mark), st = byName[stretch]; return m && st ? m.at - st.at : null; },
  // When each key of a typed text was pressed, in the seconds of a stretch.
  keys: (name, stretch) => { const st = byName[stretch]; return ((take.typed || {})[name] || []).map((ts) => ts - st.at); },
  notes: take.notes || {},
};

// ---- the cut -------------------------------------------------------------------
// A shot: { stretch, src: [{t, v}], seconds, dissolve }. `src` says which
// second of the stretch is shown at which second of the shot.
const film = EDITS[CLIP](footage);
const shots = [];
let t = 0;
for (const shot of film.shots) {
  if (!footage.has(shot.stretch) || shot.seconds <= 0) continue;
  shots.push({ ...shot, t0: t, t1: t + shot.seconds });
  t += shot.seconds;
}
// What the shots are longer than the clip may be is taken off all of them
// alike, never more than a quarter.
const speed = film.max && t > film.max ? t / film.max : 1;
if (speed > 1.25) throw new Error(`the shots are ${t.toFixed(1)} s long: more than a quarter too long for ${film.max} s, shorten a shot`);
for (const shot of shots) {
  shot.t0 /= speed; shot.t1 /= speed;
  shot.src = shot.src.map((key) => ({ ...key, t: key.t / speed }));
}
const duration = t / speed;
const track = (keys, s) => {
  if (s <= keys[0].t) return keys[0].v;
  for (let i = 1; i < keys.length; i++) {
    if (s <= keys[i].t) { const a = keys[i - 1], b = keys[i]; return a.v + (b.v - a.v) * ((s - a.t) / (b.t - a.t || 1)); }
  }
  return keys[keys.length - 1].v;
};
const shotFrame = (shot, s) => frameAt(shot.stretch, track(shot.src, Math.min(Math.max(0, s - shot.t0), shot.t1 - shot.t0)));

// Every frame of the video: the picture, and during a dissolve the picture
// it comes out of (the last one of the shot before) and how far it is.
const total = Math.round(duration * FPS);
const plan = [];
for (let n = 0; n < total; n++) {
  const s = n / FPS;
  let i = shots.findIndex((shot) => s >= shot.t0 && s < shot.t1);
  if (i < 0) i = shots.length - 1;
  const shot = shots[i];
  const frame = shotFrame(shot, s);
  let under = frame, k = 1;
  if (shot.dissolve && i > 0 && s - shot.t0 < DISSOLVE) {
    under = shotFrame(shots[i - 1], shots[i - 1].t1);
    k = (s - shot.t0) / DISSOLVE;
  }
  plan.push({ frame, under, k });
}

const report = {
  clip: CLIP, take: TAKE_DIR, duration: Number(duration.toFixed(3)), fps: FPS, speed: Number(speed.toFixed(4)),
  window: take.window,
  shots: shots.map((shot) => ({
    stretch: shot.stretch, what: shot.what || '', from: Number(shot.t0.toFixed(2)), to: Number(shot.t1.toFixed(2)),
    take_from: Number(shot.src[0].v.toFixed(2)), take_to: Number(shot.src[shot.src.length - 1].v.toFixed(2)),
    dissolve: Boolean(shot.dissolve), typing: Boolean(shot.typing),
  })),
  left_out: film.leftOut || [],
};

if (process.env.CUT_PLAN) {
  // Only the shots: to check a cut before anything is rendered.
  console.log(JSON.stringify({ ...report, seconds: report.duration }, null, 1));
  process.exit(0);
}

// ---- the video ---------------------------------------------------------------------
const work = fs.mkdtempSync(path.join(os.tmpdir(), 'cut-'));
const link = (dir, n, name) => fs.symlinkSync(path.join(TAKE_DIR, name), path.join(dir, String(n).padStart(6, '0') + '.jpg'));
// A screen frame is a full-range JPEG; a video is limited range, BT.709.
const TO_VIDEO = 'scale=in_range=full:in_color_matrix=bt601:out_range=tv:out_color_matrix=bt709:flags=accurate_rnd+full_chroma_int,format=yuv420p';
function ffmpeg(args) {
  const run = spawnSync('ffmpeg', ['-v', 'error', '-y', ...args], { stdio: 'inherit' });
  if (run.status !== 0) throw new Error('ffmpeg failed');
}
try {
  if (process.env.CUT_STILLS) {
    for (const s of process.env.CUT_STILLS.split(',').map(Number)) {
      const p = plan[Math.min(total - 1, Math.max(0, Math.round(s * FPS)))];
      const file = path.join(path.dirname(OUT), `${CLIP}-still-${s.toFixed(2).padStart(6, '0')}.png`);
      if (p.k < 1) {
        ffmpeg(['-i', path.join(TAKE_DIR, p.under), '-i', path.join(TAKE_DIR, p.frame), '-filter_complex', `[0:v][1:v]blend=all_expr='A*(1-${p.k.toFixed(4)})+B*${p.k.toFixed(4)}'`, '-frames:v', '1', file]);
      } else {
        ffmpeg(['-i', path.join(TAKE_DIR, p.frame), '-frames:v', '1', file]);
      }
      console.log(file);
    }
  } else {
    const a = path.join(work, 'a'), b = path.join(work, 'b');
    fs.mkdirSync(a); fs.mkdirSync(b);
    plan.forEach((p, n) => { link(a, n, p.under); link(b, n, p.frame); });
    // The dissolves: between the two rows of pictures, which are the same
    // picture everywhere else.
    const fades = shots.filter((shot, i) => shot.dissolve && i > 0).map((shot) => [shot.t0, Math.min(shot.t1, shot.t0 + DISSOLVE)]);
    const input = (dir) => ['-framerate', String(FPS), '-start_number', '0', '-i', path.join(dir, '%06d.jpg')];
    let graph;
    if (fades.length) {
      const k = fades.reduceRight((rest, [from]) => `if(between(T,${from.toFixed(4)},${(from + DISSOLVE).toFixed(4)}),(T-${from.toFixed(4)})/${DISSOLVE},${rest})`, '1');
      const when = fades.map(([from, to]) => `between(t,${from.toFixed(4)},${to.toFixed(4)})`).join('+');
      graph = `[0:v][1:v]blend=all_expr='A*(1-(${k}))+B*(${k})':enable='${when}'[m];[m]${TO_VIDEO}[v]`;
    } else {
      graph = `[1:v]${TO_VIDEO}[v]`;
    }
    ffmpeg([...input(a), ...input(b), '-filter_complex', graph, '-map', '[v]',
      '-c:v', 'libx264', '-preset', 'slow', '-crf', CRF, '-profile:v', 'high', '-pix_fmt', 'yuv420p',
      '-color_range', 'tv', '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709',
      '-r', String(FPS), '-movflags', '+faststart', '-an', OUT]);
    fs.writeFileSync(OUT.replace(/\.mp4$/, '') + '.cut.json', JSON.stringify(report, null, 2));
    console.log('wrote', OUT, `${duration.toFixed(2)} s, ${total} frames, plays ${speed.toFixed(3)} times as fast as filmed`);
  }
} finally {
  fs.rmSync(work, { recursive: true, force: true });
}
