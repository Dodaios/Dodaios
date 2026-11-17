/**
 * The clip's timeline as the video editor changes it.
 *
 * `motionModel.ts` reads the spec; this module holds what a video editor does
 * to it: split, trim, move, delete with or without closing the gap, copy and
 * paste, snap, keyframes, the main track's pieces cut around silences. The
 * same moves exist for the assistant in `dodaios/nodes/clip/ops.py`, so a cut
 * the person makes and one the assistant makes leave the same spec.
 *
 * The main track (`scenes`) is magnetic: its pieces always play back to back,
 * so a piece's place is its index and its start is the sum of the lengths
 * before it. Track items stand at a time of their own. Captions follow the
 * main track: when time is cut out of it, the captions after the cut move up
 * with the speech they belong to.
 *
 * Every change is a draft mutator for `useNodeSpecEditor().apply` (one undo
 * step); the functions are pure and React-free.
 */
import {
  MAX_SCENES,
  MIN_PIECE_SECONDS,
  MIN_SECONDS,
  clampPieceSeconds,
  clampSeconds,
  sceneStarts,
  type CaptionLine,
  type Look,
  type MediaEntry,
  type MotionKey,
  type MotionSpec,
  type Scene,
  type Track,
  type TrackItem,
  type TrackKind,
} from "./motionModel";

/** The frame the editor steps by: the export's default rate. */
export const FPS = 30;
export const FRAME = 1 / FPS;
/** A time in the spec is kept to the millisecond. */
export function ms(value: number): number {
  return Math.round(value * 1000) / 1000;
}

// --- ids -----------------------------------------------------------------------

export function allIds(spec: MotionSpec): Set<string> {
  const ids = new Set<string>();
  for (const scene of spec.scenes) if (scene.id) ids.add(scene.id);
  for (const track of spec.tracks ?? []) {
    ids.add(track.id);
    for (const item of track.items) ids.add(item.id);
  }
  return ids;
}

/** The first free id `<prefix><n>`; `taken` is updated. */
export function freshId(taken: Set<string>, prefix: string): string {
  let n = 1;
  while (taken.has(`${prefix}${n}`)) n += 1;
  const id = `${prefix}${n}`;
  taken.add(id);
  return id;
}

/** Give every scene, track and item an id, so a selection can name it. */
export function ensureIds(draft: MotionSpec): void {
  const taken = allIds(draft);
  for (const scene of draft.scenes) if (!scene.id) scene.id = freshId(taken, scene.type === "video" ? "v" : "s");
  for (const track of draft.tracks ?? []) {
    if (!track.id) track.id = freshId(taken, "tr");
    for (const item of track.items) if (!item.id) item.id = freshId(taken, itemPrefix(track.kind));
  }
}

export function itemPrefix(kind: TrackKind): string {
  return kind === "text" ? "t" : kind === "overlay" ? "o" : "a";
}

// --- selection -----------------------------------------------------------------

/** A picked thing on the timeline: a main-track scene, a track item, a caption line. */
export type SelKey = string;
export const sceneKey = (id: string): SelKey => `s:${id}`;
export const itemKey = (id: string): SelKey => `i:${id}`;
export const captionKey = (index: number): SelKey => `c:${index}`;

export interface ParsedKey {
  kind: "scene" | "item" | "caption";
  id: string;
}

export function parseKey(key: SelKey): ParsedKey {
  const kind = key.startsWith("s:") ? "scene" : key.startsWith("i:") ? "item" : "caption";
  return { kind, id: key.slice(2) };
}

// --- reading -------------------------------------------------------------------

/** The clip's whole length: the main track, or a later item or caption. */
export function clipDuration(spec: MotionSpec): number {
  let end = spec.scenes.reduce((sum, scene) => sum + scene.seconds, 0);
  for (const track of spec.tracks ?? []) for (const item of track.items) end = Math.max(end, item.start + item.seconds);
  for (const line of spec.captions?.items ?? []) end = Math.max(end, line.end);
  return ms(end);
}

export function sceneIndex(spec: MotionSpec, id: string): number {
  return spec.scenes.findIndex((scene) => scene.id === id);
}

export interface Located {
  track: Track;
  trackIndex: number;
  item: TrackItem;
  index: number;
}

export function findItem(spec: MotionSpec, id: string): Located | null {
  const tracks = spec.tracks ?? [];
  for (let trackIndex = 0; trackIndex < tracks.length; trackIndex += 1) {
    const track = tracks[trackIndex];
    const index = track.items.findIndex((item) => item.id === id);
    if (index >= 0) return { track, trackIndex, item: track.items[index], index };
  }
  return null;
}

/** The main-track scene under time `t` (the last one past the end). */
export function sceneAtTime(spec: MotionSpec, t: number): number {
  const starts = sceneStarts(spec);
  let index = 0;
  for (let n = 0; n < starts.length; n += 1) if (starts[n] <= t + 1e-6) index = n;
  return index;
}

/** How long a piece may run at most: the rest of its source at its speed. */
export function maxSeconds(spec: MotionSpec, piece: { media?: string; in?: number; speed?: number }): number {
  const entry = piece.media ? spec.media?.[piece.media] : undefined;
  if (!entry || entry.kind === "image" || !entry.seconds) return 3600;
  return Math.max(MIN_PIECE_SECONDS, (entry.seconds - (piece.in ?? 0)) / (piece.speed ?? 1));
}

// --- keys ----------------------------------------------------------------------

export interface Pose {
  zoom: number;
  x: number;
  y: number;
  rotate: number;
  opacity: number;
}

const POSE_FIELDS = ["zoom", "x", "y", "rotate", "opacity"] as const;

function smooth(x: number): number {
  const c = Math.max(0, Math.min(1, x));
  return c * c * (3 - 2 * c);
}

/** Where a picture stands `t` seconds into its piece: its keys eased, as the page eases them. */
export function poseAt(look: Look, t: number): Pose {
  const pose: Pose = {
    zoom: look.zoom ?? 1,
    x: look.x ?? 0,
    y: look.y ?? 0,
    rotate: look.rotate ?? 0,
    opacity: look.opacity ?? 1,
  };
  const keys = look.keys ?? [];
  for (const field of POSE_FIELDS) {
    const list = keys.filter((key) => typeof key[field] === "number");
    if (!list.length) continue;
    if (t <= list[0].t) pose[field] = list[0][field] as number;
    else if (t >= list[list.length - 1].t) pose[field] = list[list.length - 1][field] as number;
    else
      for (let n = 1; n < list.length; n += 1) {
        if (t <= list[n].t) {
          const a = list[n - 1];
          const b = list[n];
          const f = (t - a.t) / Math.max(1e-6, b.t - a.t);
          pose[field] = (a[field] as number) + ((b[field] as number) - (a[field] as number)) * smooth(f);
          break;
        }
      }
  }
  return pose;
}

/** Set a key at `t` (inside the piece) holding `values`; a key already there takes them. */
export function setKey(look: Look, t: number, values: Partial<Pose>): void {
  const at = ms(Math.max(0, t));
  const keys = look.keys ?? [];
  const found = keys.find((key) => Math.abs(key.t - at) < 0.02);
  if (found) Object.assign(found, values);
  else keys.push({ t: at, ...values });
  keys.sort((a, b) => a.t - b.t);
  look.keys = keys;
}

export function removeKey(look: Look, t: number): void {
  if (!look.keys) return;
  look.keys = look.keys.filter((key) => Math.abs(key.t - t) >= 0.02);
  if (!look.keys.length) delete look.keys;
}

/** Keys moved by `shift` seconds and kept inside `[0, length]`. */
function shiftKeys(keys: MotionKey[] | undefined, shift: number, length: number): MotionKey[] | undefined {
  if (!keys) return undefined;
  const moved = keys
    .map((key) => ({ ...key, t: ms(key.t + shift) }))
    .filter((key) => key.t >= -1e-6 && key.t <= length + 1e-6);
  return moved.length ? moved : undefined;
}

/**
 * The keys of a piece cut at `at` (its own clock), as the clip tool cuts them
 * (`ops._cut_keys`): both halves get a key at the cut holding the value the
 * picture had there, so neither half jumps; the right half's clock restarts.
 */
export function cutKeys(keys: MotionKey[], at: number): [MotionKey[], MotionKey[]] {
  const edge: Partial<Pose> = {};
  const pose = poseAt({ keys }, at);
  for (const field of POSE_FIELDS) {
    if (keys.some((key) => typeof key[field] === "number")) edge[field] = Math.round(pose[field] * 1e4) / 1e4;
  }
  const left = keys.filter((key) => key.t < at - 1e-6).map((key) => ({ ...key }));
  const right = keys.filter((key) => key.t > at + 1e-6).map((key) => ({ ...key, t: ms(key.t - at) }));
  return [[...left, { t: ms(at), ...edge }], [{ t: 0, ...edge }, ...right]];
}

function plain<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

// --- a cut of the main track closes up everywhere ------------------------------

/**
 * Take `[at, at + length)` out of every track and the captions, as the clip
 * tool does (`ops._close_gap`): what comes after moves up, what lies inside
 * goes, what starts inside loses its head, what spans the cut gets shorter.
 * So overlays, music and captions stay with the moment they belong to.
 */
export function closeGap(draft: MotionSpec, at: number, length: number): void {
  if (length <= 0) return;
  const end = at + length;
  for (const track of draft.tracks ?? []) {
    const kept: TrackItem[] = [];
    for (const item of track.items) {
      const start = item.start;
      const stop = start + item.seconds;
      if (stop <= at + 1e-9) {
        kept.push(item);
        continue;
      }
      if (start >= end - 1e-9) {
        item.start = ms(start - length);
        kept.push(item);
        continue;
      }
      if (start >= at && stop <= end) continue;
      if (start >= at) {
        const head = end - start;
        item.start = ms(at);
        item.seconds = ms(stop - start - head);
        if (item.media) item.in = ms((item.in ?? 0) + head * (item.speed ?? 1));
      } else {
        item.seconds = ms(item.seconds - Math.min(stop, end) + at);
      }
      if (item.seconds >= MIN_PIECE_SECONDS) kept.push(item);
    }
    track.items = kept;
  }
  pruneTracks(draft);
  if (!draft.captions) return;
  const lines: CaptionLine[] = [];
  for (const line of draft.captions.items) {
    const first = line.start;
    const last = line.end;
    if (last <= at + 1e-9) {
      lines.push(line);
      continue;
    }
    if (first >= end - 1e-9) {
      line.start = ms(first - length);
      line.end = ms(last - length);
      if (line.words) line.words = line.words.map(([a, b]) => [ms(a - length), ms(b - length)] as [number, number]);
      lines.push(line);
      continue;
    }
    if (first >= at && last <= end) continue;
    const nextFirst = first < at ? first : at;
    const nextLast = last - Math.min(length, Math.max(0, last - at));
    delete line.words;
    if (nextLast - nextFirst >= 0.2) {
      line.start = ms(nextFirst);
      line.end = ms(nextLast);
      lines.push(line);
    }
  }
  draft.captions.items = lines;
  if (!lines.length) delete draft.captions;
}

/** Close several cut ranges, the latest first so the earlier times stay true. */
function closeGaps(draft: MotionSpec, ranges: [number, number][]): void {
  for (const [a, b] of [...ranges].sort((x, y) => y[0] - x[0])) closeGap(draft, a, b - a);
}

function sceneRange(spec: MotionSpec, index: number): [number, number] {
  const start = sceneStarts(spec)[index] ?? 0;
  return [start, start + (spec.scenes[index]?.seconds ?? 0)];
}

// --- the main track ------------------------------------------------------------

/** A new piece of a library file, as long as its source (a picture: four seconds). */
export function pieceFromMedia(id: string, mediaId: string, entry: MediaEntry): Scene {
  const seconds = entry.kind === "video" && entry.seconds ? entry.seconds : 4;
  return { id, type: "video", media: mediaId, seconds: clampPieceSeconds(seconds), transition: "cut" };
}

/** A new clip is one blank title card: the first real piece takes its place. */
export function isBlankStarter(spec: MotionSpec): boolean {
  if (spec.scenes.length !== 1) return false;
  const only = spec.scenes[0];
  return only.type === "title" && !only.title && !only.text && !only.kicker;
}

/** The main-track index a piece dropped at time `t` goes to: the nearest boundary. */
export function insertIndexAt(spec: MotionSpec, t: number): number {
  const starts = sceneStarts(spec);
  for (let n = 0; n < spec.scenes.length; n += 1) {
    const mid = starts[n] + spec.scenes[n].seconds / 2;
    if (t < mid) return n;
  }
  return spec.scenes.length;
}

/** Put `scene` into the main track at `index`; a blank starter card makes room. */
export function insertPiece(draft: MotionSpec, index: number, scene: Scene): boolean {
  if (isBlankStarter(draft)) {
    draft.scenes.splice(0, 1, scene);
    return true;
  }
  if (draft.scenes.length >= MAX_SCENES) return false;
  draft.scenes.splice(Math.max(0, Math.min(draft.scenes.length, index)), 0, scene);
  return true;
}

/**
 * Split the main-track scene `index` at timeline time `at`. A video piece is
 * cut in its source; a card becomes two cards. Returns the new right half's
 * id, or null when either half would be too short.
 */
export function splitScene(draft: MotionSpec, index: number, at: number): string | null {
  const scene = draft.scenes[index];
  if (!scene || draft.scenes.length >= MAX_SCENES) return null;
  const [start, end] = sceneRange(draft, index);
  const left = ms(at - start);
  const right = ms(end - at);
  const shortest = scene.type === "video" ? MIN_PIECE_SECONDS : MIN_SECONDS;
  if (left < shortest || right < shortest) return null;
  const taken = allIds(draft);
  const second = plain(scene) as Scene;
  second.id = freshId(taken, scene.type === "video" ? "v" : "s");
  second.transition = "cut";
  if (scene.type === "video") {
    second.in = ms((scene.in ?? 0) + left * (scene.speed ?? 1));
    if (!second.in) delete second.in;
    scene.seconds = clampPieceSeconds(left);
    second.seconds = clampPieceSeconds(right);
    // A sound fades out at the end of the take, not at the cut, and in at its start.
    delete scene.fade_out;
    delete second.fade_in;
  } else {
    scene.seconds = clampSeconds(left);
    second.seconds = clampSeconds(right);
  }
  if (scene.keys?.length) {
    const [a, b] = cutKeys(plain(scene.keys), left);
    scene.keys = a;
    second.keys = b;
  }
  draft.scenes.splice(index + 1, 0, second);
  return second.id ?? null;
}

/**
 * Move a main-track piece's left edge by `delta` seconds of the timeline (a
 * positive delta cuts more off its start). The pieces after it move up.
 */
export function trimSceneStart(draft: MotionSpec, index: number, delta: number): void {
  const scene = draft.scenes[index];
  if (!scene) return;
  const speed = scene.speed ?? 1;
  if (scene.type === "video") {
    const source = scene.in ?? 0;
    const limited = Math.max(-source / speed, Math.min(delta, scene.seconds - MIN_PIECE_SECONDS));
    const nextIn = ms(source + limited * speed);
    if (nextIn > 0) scene.in = nextIn;
    else delete scene.in;
    scene.seconds = clampPieceSeconds(scene.seconds - limited);
    const keys = shiftKeys(scene.keys, -limited, scene.seconds);
    if (keys) scene.keys = keys;
    else delete scene.keys;
  } else {
    scene.seconds = clampSeconds(scene.seconds - delta);
  }
}

/** Set a main-track piece's length (its right edge), kept inside its source. */
export function trimSceneEnd(draft: MotionSpec, index: number, seconds: number): void {
  const scene = draft.scenes[index];
  if (!scene) return;
  if (scene.type === "video") scene.seconds = clampPieceSeconds(Math.min(seconds, maxSeconds(draft, scene)));
  else scene.seconds = clampSeconds(seconds);
}

/** Remove main-track scenes; the track closes up and every track follows (`closeGap`). */
export function removeScenes(draft: MotionSpec, ids: Set<string>): number {
  const ranges: [number, number][] = [];
  draft.scenes.forEach((scene, index) => {
    if (scene.id && ids.has(scene.id)) ranges.push(sceneRange(draft, index));
  });
  if (!ranges.length) return 0;
  draft.scenes = draft.scenes.filter((scene) => !(scene.id && ids.has(scene.id)));
  if (!draft.scenes.length) draft.scenes.push({ type: "title", seconds: 4, transition: "fade", id: freshId(allIds(draft), "s") });
  closeGaps(draft, ranges);
  return ranges.length;
}

/**
 * Cut the silent stretches out of a video piece. `silences` are in source
 * time; what remains becomes pieces of their own, back to back. Returns how
 * many stretches were taken out.
 */
export function removeSilences(draft: MotionSpec, sceneId: string, silences: [number, number][]): number {
  const index = sceneIndex(draft, sceneId);
  const scene = draft.scenes[index];
  if (!scene || scene.type !== "video") return 0;
  const speed = scene.speed ?? 1;
  const from = scene.in ?? 0;
  const to = from + scene.seconds * speed;
  const gaps = silences
    .map(([s, e]) => [Math.max(from, s), Math.min(to, e)] as [number, number])
    .filter(([s, e]) => e - s > 0.05)
    .sort((a, b) => a[0] - b[0]);
  if (!gaps.length) return 0;
  const keep: [number, number][] = [];
  let cursor = from;
  for (const [s, e] of gaps) {
    if (s - cursor >= MIN_PIECE_SECONDS * speed) keep.push([cursor, s]);
    cursor = Math.max(cursor, e);
  }
  if (to - cursor >= MIN_PIECE_SECONDS * speed) keep.push([cursor, to]);
  if (!keep.length || draft.scenes.length - 1 + keep.length > MAX_SCENES) return 0;
  const [pieceStart] = sceneRange(draft, index);
  // The timeline ranges that go: everything of the piece not kept.
  const removed: [number, number][] = [];
  let at = from;
  for (const [s, e] of keep) {
    if (s > at) removed.push([pieceStart + (at - from) / speed, pieceStart + (s - from) / speed]);
    at = e;
  }
  if (to > at) removed.push([pieceStart + (at - from) / speed, pieceStart + (to - from) / speed]);
  const taken = allIds(draft);
  const pieces: Scene[] = keep.map(([s, e], n) => {
    const piece = plain(scene) as Scene;
    if (n > 0) {
      piece.id = freshId(taken, "v");
      piece.transition = "cut";
      delete piece.fade_in;
    }
    if (n < keep.length - 1) delete piece.fade_out;
    piece.in = ms(s);
    if (!piece.in) delete piece.in;
    piece.seconds = clampPieceSeconds((e - s) / speed);
    delete piece.keys;
    return piece;
  });
  draft.scenes.splice(index, 1, ...pieces);
  closeGaps(draft, removed);
  return removed.length;
}

// --- tracks --------------------------------------------------------------------

function overlaps(items: TrackItem[], start: number, end: number, skip?: string): boolean {
  return items.some((item) => item.id !== skip && item.start < end - 1e-6 && item.start + item.seconds > start + 1e-6);
}

function sortTrack(track: Track): void {
  track.items.sort((a, b) => a.start - b.start);
}

/**
 * The track of `kind` an item `[start, end)` fits in: `preferred` when free
 * there, else the first free one, else a new track (text and overlays go on
 * top of the others).
 */
export function trackFor(draft: MotionSpec, kind: TrackKind, start: number, end: number, preferred?: string, skip?: string): Track {
  draft.tracks ??= [];
  const usable = (track: Track) => track.kind === kind && !track.locked && !overlaps(track.items, start, end, skip);
  const wanted = draft.tracks.find((track) => track.id === preferred);
  if (wanted && usable(wanted)) return wanted;
  const free = draft.tracks.find(usable);
  if (free) return free;
  const taken = allIds(draft);
  const track: Track = { id: freshId(taken, "tr"), kind, items: [] };
  draft.tracks.push(track);
  return track;
}

/** Add an item to a track of `kind` (one where it fits); returns its id. */
export function addItem(draft: MotionSpec, kind: TrackKind, item: Omit<TrackItem, "id"> & { id?: string }, trackId?: string): string {
  const taken = allIds(draft);
  const id = item.id && !taken.has(item.id) ? item.id : freshId(taken, itemPrefix(kind));
  const placed: TrackItem = { ...item, id, start: ms(Math.max(0, item.start)), seconds: ms(item.seconds) };
  const track = trackFor(draft, kind, placed.start, placed.start + placed.seconds, trackId);
  track.items.push(placed);
  sortTrack(track);
  return id;
}

/** Move an item to `start` (and to another track of its kind); a busy place takes the next free track. */
export function moveItem(draft: MotionSpec, id: string, start: number, toTrack?: string): void {
  const found = findItem(draft, id);
  if (!found) return;
  const at = ms(Math.max(0, start));
  const end = at + found.item.seconds;
  const target = trackFor(draft, found.track.kind, at, end, toTrack ?? found.track.id, id);
  found.item.start = at;
  if (target !== found.track) {
    found.track.items.splice(found.index, 1);
    target.items.push(found.item);
  }
  sortTrack(target);
  pruneTracks(draft);
}

/** Drop tracks left empty by a move or a delete. */
export function pruneTracks(draft: MotionSpec): void {
  if (!draft.tracks) return;
  draft.tracks = draft.tracks.filter((track) => track.items.length > 0);
  if (!draft.tracks.length) delete draft.tracks;
}

/** Move an item's left edge to `start` (its right edge stays); a media item's source moves with it. */
export function trimItemStart(draft: MotionSpec, id: string, start: number): void {
  const found = findItem(draft, id);
  if (!found) return;
  const { item, track } = found;
  const end = item.start + item.seconds;
  let next = Math.max(0, Math.min(start, end - MIN_PIECE_SECONDS));
  const prev = track.items.filter((other) => other.id !== id && other.start + other.seconds <= item.start + 1e-6);
  const wall = prev.reduce((max, other) => Math.max(max, other.start + other.seconds), 0);
  next = Math.max(next, wall);
  const delta = next - item.start;
  const entry = item.media ? draft.media?.[item.media] : undefined;
  if (entry && entry.kind !== "image") {
    const speed = item.speed ?? 1;
    const source = item.in ?? 0;
    const limited = Math.max(-source / speed, delta);
    next = item.start + limited;
    const nextIn = ms(source + limited * speed);
    if (nextIn > 0) item.in = nextIn;
    else delete item.in;
  }
  const shift = next - item.start;
  item.start = ms(next);
  item.seconds = ms(end - next);
  const keys = shiftKeys(item.keys, -shift, item.seconds);
  if (keys) item.keys = keys;
  else delete item.keys;
}

/** Move an item's right edge to `end`, kept inside its source and before the next item. */
export function trimItemEnd(draft: MotionSpec, id: string, end: number): void {
  const found = findItem(draft, id);
  if (!found) return;
  const { item, track } = found;
  const next = track.items.filter((other) => other.id !== id && other.start >= item.start + item.seconds - 1e-6);
  const wall = next.reduce((min, other) => Math.min(min, other.start), Number.POSITIVE_INFINITY);
  const longest = Math.min(maxSeconds(draft, item), wall - item.start);
  item.seconds = ms(Math.max(MIN_PIECE_SECONDS, Math.min(end - item.start, longest)));
}

/** Split a track item at timeline time `at`; returns the right half's id. */
export function splitItem(draft: MotionSpec, id: string, at: number): string | null {
  const found = findItem(draft, id);
  if (!found) return null;
  const { item, track } = found;
  const left = ms(at - item.start);
  const right = ms(item.start + item.seconds - at);
  if (left < MIN_PIECE_SECONDS || right < MIN_PIECE_SECONDS) return null;
  const second = plain(item) as TrackItem;
  second.id = freshId(allIds(draft), itemPrefix(track.kind));
  second.start = ms(at);
  second.seconds = right;
  item.seconds = left;
  if (item.media && draft.media?.[item.media]?.kind !== "image") {
    second.in = ms((item.in ?? 0) + left * (item.speed ?? 1));
  }
  delete item.fade_out;
  delete second.fade_in;
  if (track.kind === "text") {
    // The first half leaves without its exit, the second arrives without its entrance.
    item.out = "none";
    second.anim = "none";
  }
  if (item.keys?.length) {
    const [a, b] = cutKeys(plain(item.keys), left);
    item.keys = a;
    second.keys = b;
  }
  track.items.splice(found.index + 1, 0, second);
  return second.id;
}

/** Remove track items; with `ripple`, the later items of each track move up by the gap. */
export function removeItems(draft: MotionSpec, ids: Set<string>, ripple: boolean): number {
  let count = 0;
  for (const track of draft.tracks ?? []) {
    const gone = track.items.filter((item) => ids.has(item.id));
    if (!gone.length) continue;
    count += gone.length;
    track.items = track.items.filter((item) => !ids.has(item.id));
    if (ripple)
      for (const item of track.items) {
        const shift = gone
          .filter((removed) => removed.start + removed.seconds <= item.start + 1e-6)
          .reduce((sum, removed) => sum + removed.seconds, 0);
        item.start = ms(Math.max(0, item.start - shift));
      }
  }
  pruneTracks(draft);
  return count;
}

// --- captions ------------------------------------------------------------------

export function removeCaptions(draft: MotionSpec, indexes: Set<number>, ripple: boolean): void {
  if (!draft.captions) return;
  const gone = draft.captions.items.filter((_, n) => indexes.has(n));
  draft.captions.items = draft.captions.items.filter((_, n) => !indexes.has(n));
  if (ripple && gone.length)
    for (const line of draft.captions.items) {
      const shift = gone.filter((g) => g.end <= line.start + 1e-6).reduce((sum, g) => sum + (g.end - g.start), 0);
      line.start = ms(line.start - shift);
      line.end = ms(line.end - shift);
      if (line.words) line.words = line.words.map(([s, e]) => [ms(s - shift), ms(e - shift)] as [number, number]);
    }
  if (!draft.captions.items.length) delete draft.captions;
}

/** Split a caption line at `at`: its words go to the half they are spoken in. */
export function splitCaption(draft: MotionSpec, index: number, at: number): boolean {
  const line = draft.captions?.items[index];
  if (!line || at <= line.start + 0.1 || at >= line.end - 0.1) return false;
  const words = line.text.split(/\s+/).filter(Boolean);
  if (words.length < 2) return false;
  const times =
    line.words && line.words.length === words.length
      ? line.words
      : words.map((_, n) => [line.start + ((line.end - line.start) * n) / words.length, line.start + ((line.end - line.start) * (n + 1)) / words.length] as [number, number]);
  let cut = times.findIndex(([s]) => s >= at);
  if (cut <= 0) cut = Math.max(1, Math.round(words.length / 2));
  const first: CaptionLine = { start: line.start, end: ms(at), text: words.slice(0, cut).join(" ") };
  const second: CaptionLine = { start: ms(at), end: line.end, text: words.slice(cut).join(" ") };
  if (line.words && line.words.length === words.length) {
    first.words = line.words.slice(0, cut);
    second.words = line.words.slice(cut);
  }
  draft.captions!.items.splice(index, 1, first, second);
  return true;
}

/** Keep the caption lines in time order after one moved. */
export function sortCaptions(draft: MotionSpec): void {
  draft.captions?.items.sort((a, b) => a.start - b.start);
}

/** Move a caption line to start at `start` (its words with it). */
export function moveCaption(draft: MotionSpec, index: number, start: number): void {
  const line = draft.captions?.items[index];
  if (!line) return;
  const shift = ms(Math.max(0, start) - line.start);
  line.start = ms(line.start + shift);
  line.end = ms(line.end + shift);
  if (line.words) line.words = line.words.map(([s, e]) => [ms(s + shift), ms(e + shift)] as [number, number]);
}

// --- snapping ------------------------------------------------------------------

/** The times an edge or a moved item snaps to: the start, the playhead, every edge. */
export function snapTargets(spec: MotionSpec, playhead: number, skip: Set<string>): number[] {
  const targets = new Set<number>([0, ms(playhead)]);
  let at = 0;
  for (const scene of spec.scenes) {
    at += scene.seconds;
    if (!(scene.id && skip.has(sceneKey(scene.id)))) targets.add(ms(at));
  }
  for (const track of spec.tracks ?? [])
    for (const item of track.items) {
      if (skip.has(itemKey(item.id))) continue;
      targets.add(ms(item.start));
      targets.add(ms(item.start + item.seconds));
    }
  (spec.captions?.items ?? []).forEach((line, n) => {
    if (skip.has(captionKey(n))) return;
    targets.add(ms(line.start));
    targets.add(ms(line.end));
  });
  return [...targets].sort((a, b) => a - b);
}

/** `t` pulled onto the nearest target within `tolerance` seconds. */
export function snapTime(t: number, targets: number[], tolerance: number): { t: number; to: number | null } {
  let best: number | null = null;
  for (const target of targets) if (Math.abs(target - t) <= tolerance && (best === null || Math.abs(target - t) < Math.abs(best - t))) best = target;
  return best === null ? { t, to: null } : { t: best, to: best };
}

// --- copy and paste ------------------------------------------------------------

export interface ClipBoard {
  scenes: Scene[];
  items: { kind: TrackKind; item: TrackItem; offset: number }[];
  captions: (CaptionLine & { offset: number })[];
}

/** What the selection holds, ready to be put somewhere else. */
export function copySelection(spec: MotionSpec, keys: Set<SelKey>): ClipBoard {
  const board: ClipBoard = { scenes: [], items: [], captions: [] };
  for (const scene of spec.scenes) if (scene.id && keys.has(sceneKey(scene.id))) board.scenes.push(plain(scene));
  const found: { kind: TrackKind; item: TrackItem }[] = [];
  for (const track of spec.tracks ?? [])
    for (const item of track.items) if (keys.has(itemKey(item.id))) found.push({ kind: track.kind, item: plain(item) });
  const lines = (spec.captions?.items ?? []).filter((_, n) => keys.has(captionKey(n)));
  const origin = Math.min(...found.map((f) => f.item.start), ...lines.map((l) => l.start), Number.POSITIVE_INFINITY);
  board.items = found.map((f) => ({ ...f, offset: f.item.start - origin }));
  board.captions = lines.map((line) => ({ ...plain(line), offset: line.start - origin }));
  return board;
}

/** Put a copy at time `at`; returns the keys of what was pasted. */
export function pasteBoard(draft: MotionSpec, board: ClipBoard, at: number): SelKey[] {
  const pasted: SelKey[] = [];
  const taken = allIds(draft);
  if (board.scenes.length) {
    let index = Math.min(draft.scenes.length, sceneAtTime(draft, at) + 1);
    for (const scene of board.scenes) {
      const copy = plain(scene);
      copy.id = freshId(taken, copy.type === "video" ? "v" : "s");
      if (draft.scenes.length >= MAX_SCENES) break;
      draft.scenes.splice(index, 0, copy);
      index += 1;
      pasted.push(sceneKey(copy.id));
    }
  }
  for (const { kind, item, offset } of board.items) {
    const copy = plain(item);
    delete (copy as Partial<TrackItem>).id;
    const id = addItem(draft, kind, { ...copy, start: at + offset });
    pasted.push(itemKey(id));
  }
  if (board.captions.length) {
    draft.captions ??= { style: "karaoke", position: "bottom", size: "m", items: [] };
    for (const line of board.captions) {
      const shift = at + line.offset - line.start;
      const { offset: _offset, ...rest } = line;
      void _offset;
      const copy: CaptionLine = { ...rest, start: ms(rest.start + shift), end: ms(rest.end + shift) };
      if (rest.words) copy.words = rest.words.map(([s, e]) => [ms(s + shift), ms(e + shift)] as [number, number]);
      draft.captions.items.push(copy);
    }
    sortCaptions(draft);
  }
  return pasted;
}

// --- one step for a selection --------------------------------------------------

/**
 * Split at the playhead: the picked things under it, or, when none is
 * picked, the main-track piece under it. Returns the keys of the right halves.
 */
export function splitAt(draft: MotionSpec, keys: Set<SelKey>, at: number): SelKey[] {
  ensureIds(draft);
  const made: SelKey[] = [];
  const picked = [...keys].map(parseKey);
  const targets = picked.length ? picked : [{ kind: "scene" as const, id: draft.scenes[sceneAtTime(draft, at)]?.id ?? "" }];
  for (const target of targets) {
    if (target.kind === "scene") {
      const index = sceneIndex(draft, target.id);
      const [start, end] = index >= 0 ? sceneRange(draft, index) : [0, 0];
      if (index >= 0 && at > start && at < end) {
        const id = splitScene(draft, index, at);
        if (id) made.push(sceneKey(id));
      }
    } else if (target.kind === "item") {
      const found = findItem(draft, target.id);
      if (found && at > found.item.start && at < found.item.start + found.item.seconds) {
        const id = splitItem(draft, target.id, at);
        if (id) made.push(itemKey(id));
      }
    } else {
      const index = Number(target.id);
      if (splitCaption(draft, index, at)) made.push(captionKey(index + 1));
    }
  }
  return made;
}

/** Delete the selection; `ripple` closes the gaps on tracks (the main track always closes). */
export function deleteSelection(draft: MotionSpec, keys: Set<SelKey>, ripple: boolean): void {
  const scenes = new Set<string>();
  const items = new Set<string>();
  const captions = new Set<number>();
  for (const key of keys) {
    const { kind, id } = parseKey(key);
    if (kind === "scene") scenes.add(id);
    else if (kind === "item") items.add(id);
    else captions.add(Number(id));
  }
  if (captions.size) removeCaptions(draft, captions, ripple);
  if (items.size) removeItems(draft, items, ripple);
  if (scenes.size) removeScenes(draft, scenes);
}
