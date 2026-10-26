/**
 * Which view the stage shows (docs/verse/realtime.md): the eye-level 3D view
 * behind the commander's shoulder, or the deck's plate. The plate is the
 * bird's-eye view, the compact IDE panel's view, and the fallback for decks
 * without an eye-level export or whose export failed to load. Pure.
 */
import type { ControlMode } from "../life/control";

export type StageView = "eye" | "plate";

export interface ViewInputs {
  /** The compact IDE side panel. */
  compact: boolean;
  /** The deck has an eye-level export this runtime reads. */
  realtime: boolean;
  /** Its eye-level scene failed to load on this stage. */
  failed: boolean;
  /** Third person ("follow") or bird's-eye ("overview"). */
  mode: ControlMode;
}

/** The deck can be walked at eye level on this stage; its scene stays loaded while the bird's-eye view is on. */
export function eyeCapable(v: Omit<ViewInputs, "mode">): boolean {
  return !v.compact && v.realtime && !v.failed;
}

export function stageView(v: ViewInputs): StageView {
  return eyeCapable(v) && v.mode === "follow" ? "eye" : "plate";
}
