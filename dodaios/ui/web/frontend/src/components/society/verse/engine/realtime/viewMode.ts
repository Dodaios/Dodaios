/**
 * The three ways to see the deck and how they hand over to each other
 * (docs/verse/realtime.md, "Views"):
 *
 * - bird's-eye (`overview`): the plate from above, WASD pans, clicks walk;
 * - third person (`third`): over the commander's shoulder, shooter mouse look;
 * - first person (`first`): through the commander's eyes, shooter mouse look.
 *
 * V cycles bird's-eye → third → first → bird's-eye; 1, 2 and 3 pick one
 * directly. The wheel moves the third-person camera in and out; pushing on
 * past the closest distance hands over to first person, and scrolling out of
 * first person comes back to third. Where a deck has no eye-level scene (the
 * compact panel, decks without an export) first person is not offered and
 * third person is the plate's follow camera.
 *
 * Pure: the stage keeps the chosen view and the rig its distance.
 */
import type { ControlMode } from "../../life/control";

export type VerseView = "overview" | "third" | "first";

/** The order of the tool rail's switch and of V's cycle. */
export const VIEW_ORDER: readonly VerseView[] = ["overview", "third", "first"];

/** The keys that pick a view directly (top row and keypad). */
const DIRECT_KEYS: Readonly<Record<string, VerseView>> = {
  Digit1: "overview", Numpad1: "overview",
  Digit2: "third", Numpad2: "third",
  Digit3: "first", Numpad3: "first",
};

/** The view a key picks directly, or null. Pure. */
export function viewForKey(code: string): VerseView | null {
  return DIRECT_KEYS[code] ?? null;
}

/** The key shown on each view's button. */
export function keyForView(view: VerseView): string {
  return String(VIEW_ORDER.indexOf(view) + 1);
}

/** The view that can actually be shown: first person needs the eye-level scene. Pure. */
export function resolveView(wanted: VerseView, eyeCapable: boolean): VerseView {
  return wanted === "first" && !eyeCapable ? "third" : wanted;
}

/** The view after V: the next one in VIEW_ORDER that can be shown. Pure. */
export function cycleView(current: VerseView, eyeCapable: boolean): VerseView {
  const from = VIEW_ORDER.indexOf(resolveView(current, eyeCapable));
  for (let i = 1; i <= VIEW_ORDER.length; i++) {
    const next = VIEW_ORDER[(from + i) % VIEW_ORDER.length];
    if (resolveView(next, eyeCapable) === next) return next;
  }
  return current;
}

/** How the movement keys work in a view: the commander's (third, first) or the map's (bird's-eye). Pure. */
export function controlModeOf(view: VerseView): ControlMode {
  return view === "overview" ? "overview" : "follow";
}

/** The views with shooter mouse look (pointer lock, a centre crosshair). Pure. */
export function isShooterView(view: VerseView, eyeCapable: boolean): boolean {
  return eyeCapable && view !== "overview";
}

/** Anything stored as a view, valid (third person when unknown). Pure. */
export function normalizeView(raw: unknown): VerseView {
  return raw === "overview" || raw === "third" || raw === "first" ? raw : "third";
}

/** The person (camera) of the eye-level views. */
export type Person = "third" | "first";

export interface ZoomState {
  person: Person;
  /** The wanted third-person distance, metres. */
  distance: number;
  /** How far the wheel has pushed past a hand-over point, as a log of the zoom factor (in: negative, out: positive). */
  push: number;
}

export interface ZoomLimits {
  min: number;
  max: number;
  /** Log zoom past the end that hands over (about one wheel notch). */
  handover: number;
}

/**
 * One wheel or key zoom step: `factor` < 1 moves in, > 1 moves out. Third
 * person scales the distance inside [min, max]; pushing in past `min` by
 * `handover` goes to first person (at `min`, so the way back starts there),
 * and in first person a push out of `handover` returns to third person at
 * `min`. A step the other way clears the push. Pure.
 */
export function zoomStep(s: ZoomState, factor: number, limits: ZoomLimits): ZoomState {
  if (!(factor > 0) || !Number.isFinite(factor) || factor === 1) return s;
  const log = Math.log(factor);
  if (s.person === "first") {
    if (log < 0) return { person: "first", distance: limits.min, push: 0 };
    const push = Math.max(0, s.push) + log;
    return push >= limits.handover ? { person: "third", distance: limits.min, push: 0 } : { person: "first", distance: limits.min, push };
  }
  const wanted = s.distance * factor;
  if (wanted >= limits.min) return { person: "third", distance: Math.min(limits.max, wanted), push: 0 };
  // Already at (or pushed past) the closest distance: what is left of the step pushes toward first person.
  const over = Math.log(wanted / limits.min);
  const push = Math.min(0, s.push) + over;
  return push <= -limits.handover ? { person: "first", distance: limits.min, push: 0 } : { person: "third", distance: limits.min, push };
}

/** How far off the view direction the body may face while walking (radians): a strafe leans into it, no more. */
export const STRAFE_LEAN = (45 * Math.PI) / 180;
/** Moving further off the view than this (radians) is walking backwards. */
const BACKPEDAL_BEYOND = (110 * Math.PI) / 180;

function wrap(a: number): number {
  return Math.atan2(Math.sin(a), Math.cos(a));
}

/**
 * Which way a body walking along `move` (unit, on the floor) faces in a
 * shooter view looking along `viewYaw`: toward the view, leaning at most
 * STRAFE_LEAN into a sideways step; walking backwards it keeps facing the
 * view and plays its walk in reverse (`reverse`). Written into `out` when
 * given (the frame loop allocates nothing). Pure.
 */
export function bodyFacing(
  viewYaw: number, move: { x: number; z: number }, out?: { yaw: number; reverse: boolean },
): { yaw: number; reverse: boolean } {
  const o = out ?? { yaw: 0, reverse: false };
  const off = wrap(Math.atan2(move.x, move.z) - viewYaw);
  o.reverse = Math.abs(off) > BACKPEDAL_BEYOND;
  const lean = o.reverse ? wrap(off - Math.PI) : off;
  o.yaw = wrap(viewYaw + Math.max(-STRAFE_LEAN, Math.min(STRAFE_LEAN, lean)));
  return o;
}
