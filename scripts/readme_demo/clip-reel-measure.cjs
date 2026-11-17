// Measures how a clip moves, and makes its contact sheet.
//
// A copy of nodes-plugins-measure.cjs for the second Nodes clip.
//
//   node scripts/readme_demo/clip-reel-measure.cjs <video.mp4> [contact.png] [take folder]
//
// A screen recording must move the way the app does on a screen: stills show
// what is in the picture, not how it moves. So the video is decoded to small
// gray frames, and each frame is compared with the one before it. The script
// prints, for every second, how many of its frames differ from the frame
// before, and the longest stretch in which nothing in the picture changed.
// The contact sheet holds one frame for every second, at most 2000 px wide.
// With the take folder it also prints, for each stretch of the footage, how
// many frames the screencast gave and how far apart they came while the
// picture moved (a frame comes only when the picture changes, so a gap longer
// than a quarter of a second is a still picture, not a lost frame).
// Needs ffmpeg and ffprobe.
const { spawnSync } = require('child_process');
const path = require('path');

const VIDEO = process.argv[2];
if (!VIDEO) { console.error('usage: node clip-reel-measure.cjs <video.mp4> [contact.png]'); process.exit(2); }
const SHEET = process.argv[3] || VIDEO.replace(/(-master)?\.mp4$/, '') + '-contact.png';
const TAKE = process.argv[4] || '';
const W = 480, H = 270;
// A pixel counts as changed from 10 grey levels: the encoder's own noise in a
// standing picture stays below that, the edge of a moving pointer does not.
const LEVEL = 10;

const probe = spawnSync('ffprobe', ['-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height,avg_frame_rate,nb_frames,pix_fmt,codec_name:format=duration,size', '-of', 'json', VIDEO], { encoding: 'utf8' });
const info = JSON.parse(probe.stdout || '{}');
const stream = (info.streams || [])[0] || {};
const [num, den] = String(stream.avg_frame_rate || '60/1').split('/').map(Number);
const fps = num / (den || 1);

const raw = spawnSync('ffmpeg', ['-v', 'error', '-i', VIDEO, '-vf', `scale=${W}:${H}:flags=area,format=gray`, '-f', 'rawvideo', '-'], { maxBuffer: 1 << 30 });
if (raw.status !== 0) { console.error('ffmpeg could not decode', VIDEO); process.exit(1); }
const size = W * H;
const count = Math.floor(raw.stdout.length / size);
const changed = [false];   // frame n differs from frame n - 1
for (let n = 1; n < count; n++) {
  const a = raw.stdout.subarray((n - 1) * size, n * size), b = raw.stdout.subarray(n * size, (n + 1) * size);
  let differs = false;
  for (let i = 0; i < size; i++) { if (Math.abs(a[i] - b[i]) >= LEVEL) { differs = true; break; } }
  changed.push(differs);
}
const seconds = Math.ceil(count / fps);
const perSecond = [];
for (let s = 0; s < seconds; s++) {
  let moved = 0, frames = 0;
  for (let n = Math.round(s * fps); n < Math.min(count, Math.round((s + 1) * fps)); n++) { frames++; if (changed[n]) moved++; }
  perSecond.push({ second: s, frames, moved });
}
// The longest standstill: frames in a row that are the same as the one before.
let longest = 0, longestAt = 0, run = 0;
for (let n = 1; n < count; n++) {
  if (!changed[n]) { run++; if (run > longest) { longest = run; longestAt = n - run + 1; } } else run = 0;
}
// The same for the clip played in a loop: the standstill at its end and the one at its start add up.
let head = 0; while (head + 1 < count && !changed[head + 1]) head++;
let tail = 0; while (count - 1 - tail > 0 && !changed[count - 1 - tail]) tail++;
const movedAll = changed.filter(Boolean).length;

console.log(`${path.basename(VIDEO)}: ${stream.codec_name} ${stream.pix_fmt} ${stream.width}x${stream.height}, ${fps} frames a second, ${count} frames, ${(count / fps).toFixed(2)} s, ${(Number(info.format?.size || 0) / 1e6).toFixed(1)} MB`);
console.log('frames that differ from the one before, per second:');
for (const row of perSecond) console.log(`  ${String(row.second).padStart(2)} s  ${String(row.moved).padStart(2)} of ${row.frames}  ${'#'.repeat(Math.round(row.moved / 2))}`);
console.log(`in all ${movedAll} of ${count} frames differ (${(100 * movedAll / count).toFixed(0)} %)`);
console.log(`longest standstill: ${(longest / fps).toFixed(2)} s, from ${(longestAt / fps).toFixed(2)} s`);
console.log(`standing picture at the start ${(head / fps).toFixed(2)} s, at the end ${(tail / fps).toFixed(2)} s (in a loop they follow each other: ${((head + tail) / fps).toFixed(2)} s)`);

const columns = 4;
const rows = Math.ceil(seconds / columns);
const sheet = spawnSync('ffmpeg', ['-v', 'error', '-y', '-i', VIDEO, '-vf', `fps=1:start_time=0:round=down,scale=480:-1:flags=lanczos,tile=${columns}x${rows}:padding=4:margin=4:color=0x202020`, '-frames:v', '1', SHEET], { stdio: 'inherit' });
if (sheet.status === 0) console.log('contact sheet:', SHEET, `(${columns} x ${rows}, one frame a second)`);

if (TAKE) {
  const fs = require('fs');
  const take = JSON.parse(fs.readFileSync(path.join(TAKE, 'take.json'), 'utf8'));
  console.log('footage, per stretch (gaps over 0.25 s are still pictures and not counted):');
  take.stretches.forEach((st, i) => {
    if (!st.name) return;
    const end = i + 1 < take.stretches.length ? take.stretches[i + 1].at : Infinity;
    const ts = take.frames.filter((f) => f.ts >= st.at && f.ts < end).map((f) => f.ts);
    const gaps = ts.slice(1).map((t, k) => t - ts[k]).filter((g) => g <= 0.25).sort((a, b) => a - b);
    const moving = gaps.reduce((a, g) => a + g, 0);
    const pct = (q) => (gaps.length ? gaps[Math.min(gaps.length - 1, Math.floor(q * gaps.length))] * 1000 : 0);
    const len = (end === Infinity ? (ts[ts.length - 1] || st.at) : end) - st.at;
    console.log(`  ${st.name.padEnd(8)} ${len.toFixed(2).padStart(6)} s, ${String(ts.length).padStart(4)} frames; while moving ${moving ? (gaps.length / moving).toFixed(1) : '-'} frames a second, gap median ${pct(0.5).toFixed(0)} ms, 95th ${pct(0.95).toFixed(0)} ms, longest ${pct(1).toFixed(0)} ms`);
  });
}
