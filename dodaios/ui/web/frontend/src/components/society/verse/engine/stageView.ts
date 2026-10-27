/**
 * Which view the stage shows (docs/verse/realtime.md): the eye-level 3D view
 * behind the commander's shoulder, or the deck's plate. The plate is the
 * bird's-eye view, the view of an IDE side panel too small to walk in, and
 * the fallback for decks without an eye-level export or whose export failed
 * to load. Pure.
 */
import type { ControlMode } from "../life/control";

export type StageView = "eye" | "plate";

/**
 * The smallest compact stage (CSS px) that offers third and first person at
 * eye level; a smaller IDE side panel keeps the overhead follow camera.
 */
export const COMPACT_EYE_MIN = { width: 480, height: 360 } as const;

export interface ViewInputs {
  /** The compact IDE side panel. */
  compact: boolean;
  /** The stage's size in CSS px (only the compact stage reads it; unknown counts as too small). */
  width?: number;
  height?: number;
  /** The deck has an eye-level export this runtime reads. */
  realtime: boolean;
  /** Its eye-level scene failed to load on this stage. */
  failed: boolean;
  /** Third person ("follow") or bird's-eye ("overview"). */
  mode: ControlMode;
}

/** The compact stage is large enough to walk at eye level. */
export function roomyEnough(width = 0, height = 0): boolean {
  return width >= COMPACT_EYE_MIN.width && height >= COMPACT_EYE_MIN.height;
}

/** The deck can be walked at eye level on this stage; its scene stays loaded while the bird's-eye view is on. */
export function eyeCapable(v: Omit<ViewInputs, "mode">): boolean {
  return v.realtime && !v.failed && (!v.compact || roomyEnough(v.width, v.height));
}

export function stageView(v: ViewInputs): StageView {
  return eyeCapable(v) && v.mode === "follow" ? "eye" : "plate";
}
