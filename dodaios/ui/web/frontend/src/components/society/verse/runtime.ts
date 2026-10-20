/**
 * The per-stage runtime: everything that changes every frame and must not go
 * through React state — the camera view, the deck on screen, where each
 * actor stands, the frame statistics. One instance per mounted stage (the
 * Agents view and the IDE side panel each have their own), handed to the
 * scene and the HUD by reference.
 */
import type { Deck } from "./content/deck";
import { worldToPlate } from "./engine/plateMath";
import { plateToScreen } from "./engine/view";
import { ViewController } from "./engine/viewController";
import { CommanderControl } from "./life/control";

/** Where a body is; updated in place every frame. */
export interface ActorPose {
  id: string;
  x: number;
  y: number;
  z: number;
  /** Height of the head above the feet, metres (name plates sit above it). */
  height: number;
  moving: boolean;
}

export interface FrameStats {
  drawCalls: number;
  triangles: number;
  /** Time between frames, smoothed. */
  frameMs: number;
  /** Main-thread time of the render passes, smoothed. */
  cpuMs: number;
  tiles: number;
  tilesLoading: number;
  /** The plate level the view streams: "overview", "M4", "M2" or "L0". */
  plateLevel: string;
  actors: number;
}

export class StageRuntime {
  readonly view = new ViewController();
  /** Third person or bird's-eye, and the movement keys held for the commander. */
  readonly control = new CommanderControl();
  deck: Deck | null = null;
  /** Live poses of every actor on the deck, crew and commander alike, by id. */
  readonly poses = new Map<string, ActorPose>();
  readonly stats: FrameStats = { drawCalls: 0, triangles: 0, frameMs: 0, cpuMs: 0, tiles: 0, tilesLoading: 0, plateLevel: "overview", actors: 0 };
  /** Called after each rendered frame (the HUD moves its plates here). */
  readonly afterFrame = new Set<() => void>();

  /** Screen position (CSS px) of a world point under the current view. */
  toScreen(x: number, y: number, z: number): { x: number; y: number } | null {
    if (!this.deck) return null;
    const p = worldToPlate(this.deck.camera, x, y, z);
    return plateToScreen(this.view.current, this.view.vp, p.u, p.v);
  }
}
