/**
 * How a clip (Clips, type `motion`) is revealed while an agent builds it.
 *
 * The agent works the way a person at a video editor does: media lands in the
 * bin, then the main track fills left to right, then each track in turn gets
 * its clips left to right. Each step grows a clip from its start to its
 * length (a trim or a move glides from where it was), a new track slides in,
 * and the playhead moves onto the clip being placed. The preview is not a step:
 * it refreshes once per batch and crossfades (`ClipPreview`).
 *
 * The steps come from a comparison of the spec before and after, not from the
 * ops, so they are right however the agent wrote the change. The timeline
 * marks its blocks with `data-live-path` (`/scenes/2`, `/tracks/1`,
 * `/tracks/1/items/0`, `/captions/items/3`, `/media/<id>`).
 */
import { CLIP_LIVE_SEEK, type ClipLiveSeekDetail } from "../../editors/motion/clipLive";
import type { MotionSpec, Scene, Track, TrackItem } from "../../editors/motion/motionModel";
import type { RevealAdapter, RevealInput, RevealStep } from "../reveal";

/** A clip as it stood: where it started and how long it ran, in seconds. */
interface Span {
  start: number;
  seconds: number;
}

const EMPTY: MotionSpec = { format: "wide", theme: "dark", accent: "", loop: false, scenes: [] };

function same(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

function finite(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

/** A scene's identity: its id, or its place when the spec has none. */
function sceneKey(scene: Scene, index: number): string {
  return scene.id || `#${index}`;
}

function sceneSpans(scenes: readonly Scene[]): Map<string, Span> {
  const spans = new Map<string, Span>();
  let at = 0;
  scenes.forEach((scene, index) => {
    const seconds = finite(scene.seconds);
    spans.set(sceneKey(scene, index), { start: at, seconds });
    at += seconds;
  });
  return spans;
}

/** The playhead moves onto the clip being placed. */
function seekTo(t: number): (el: Element) => void {
  return (el) => {
    el.dispatchEvent(new CustomEvent<ClipLiveSeekDetail>(CLIP_LIVE_SEEK, { bubbles: true, detail: { t } }));
  };
}

/** A clip appears: it grows from its start to its length. */
function grow(): Keyframe[] {
  return [{ clipPath: "inset(0 100% 0 0)" }, { clipPath: "inset(0 0 0 0)" }];
}

/** A clip that was already there glides from where it was: a move shifts it, a trim stretches it. */
function glide(before: Span, after: Span): (el: Element) => Keyframe[] | null {
  return (el) => {
    if (after.seconds <= 0) return null;
    const box = el.getBoundingClientRect();
    const pps = box.width / after.seconds;
    if (!(pps > 0)) return null;
    const shift = (before.start - after.start) * pps;
    const grew = box.width - before.seconds * pps;
    if (Math.abs(shift) < 1 && Math.abs(grew) < 1) return null;
    const from: Keyframe = {};
    const to: Keyframe = {};
    if (Math.abs(shift) >= 1) {
      from.transform = `translateX(${shift.toFixed(1)}px)`;
      to.transform = "translateX(0)";
    }
    if (Math.abs(grew) >= 1) {
      from.width = `${Math.max(4, before.seconds * pps).toFixed(1)}px`;
      to.width = `${box.width.toFixed(1)}px`;
    }
    return [from, to];
  };
}

/** A track slides in from just above its place. */
function slideIn(): Keyframe[] {
  return [{ transform: "translateY(-8px)" }, { transform: "translateY(0)" }];
}

function itemSteps(track: Track, trackIndex: number, before: Track | undefined): RevealStep[] {
  const old = new Map((before?.items ?? []).map((item) => [item.id, item]));
  const order = track.items.map((item, index) => ({ item, index })).sort((a, b) => finite(a.item.start) - finite(b.item.start) || a.index - b.index);
  const steps: RevealStep[] = [];
  for (const { item, index } of order) {
    const was: TrackItem | undefined = old.get(item.id);
    if (was && same(was, item)) continue;
    const after = { start: finite(item.start), seconds: finite(item.seconds) };
    const step: RevealStep = {
      target: { path: `/tracks/${trackIndex}/items/${index}` },
      onReveal: seekTo(after.start),
    };
    step.enter = was ? glide({ start: finite(was.start), seconds: finite(was.seconds) }, after) : grow;
    steps.push(step);
  }
  return steps;
}

/** The reveal steps for one batch, from the spec before and the spec now. */
export function clipSteps(previous: MotionSpec | null, next: MotionSpec): RevealStep[] {
  const before = previous ?? EMPTY;
  const steps: RevealStep[] = [];

  // Media dropped into the bin: each card fades in over its thumbnail skeleton.
  const known = before.media ?? {};
  for (const [id, entry] of Object.entries(next.media ?? {})) {
    if (!(id in known) || !same(known[id], entry)) steps.push({ target: { path: `/media/${id}` } });
  }

  // The main track, left to right.
  const spans = sceneSpans(before.scenes ?? []);
  const was = new Map((before.scenes ?? []).map((scene, index) => [sceneKey(scene, index), scene]));
  const now = sceneSpans(next.scenes ?? []);
  (next.scenes ?? []).forEach((scene, index) => {
    const key = sceneKey(scene, index);
    const old = was.get(key);
    if (old && same(old, scene)) return;
    const after = now.get(key)!;
    const prior = spans.get(key);
    steps.push({
      target: { path: `/scenes/${index}` },
      onReveal: seekTo(after.start),
      enter: old && prior ? glide(prior, after) : grow,
    });
  });

  // Each track in turn: a new one slides in, then its clips land left to right.
  const oldTracks = new Map((before.tracks ?? []).map((track) => [track.id, track]));
  (next.tracks ?? []).forEach((track, trackIndex) => {
    const old = oldTracks.get(track.id);
    if (!old) steps.push({ target: { path: `/tracks/${trackIndex}` }, enter: slideIn, framed: false });
    steps.push(...itemSteps(track, trackIndex, old));
  });

  // Captions, in order.
  const lines = before.captions?.items ?? [];
  (next.captions?.items ?? []).forEach((line, index) => {
    if (lines[index] && same(lines[index], line)) return;
    steps.push({ target: { path: `/captions/items/${index}` }, onReveal: seekTo(finite(line.start)), enter: lines[index] ? undefined : grow });
  });

  return steps;
}

export const motionReveal: RevealAdapter = {
  steps: (input: RevealInput) => {
    const { previous, next } = input as RevealInput<MotionSpec>;
    if (!next || typeof next !== "object" || !Array.isArray(next.scenes)) return [];
    return clipSteps(previous && typeof previous === "object" ? previous : null, next);
  },
};
