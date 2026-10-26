/**
 * The per-stage runtime: everything that changes every frame and must not go
 * through React state — the camera view, the deck on screen, where each
 * actor stands, the frame statistics. One instance per mounted stage (the
 * Agents view and the IDE side panel each have their own), handed to the
 * scene and the HUD by reference.
 *
 * Two views share it: the plate (the deck's photograph, bird's-eye and the
 * compact panel) and, on decks exported for it, the eye-level 3D view behind
 * the commander's shoulder (`eye`, set while that view is on screen).
 */
import { DoubleSide, Ray, Raycaster, Vector2, Vector3, type PerspectiveCamera } from "three";
import type { MeshBVH } from "three-mesh-bvh";
import type { Deck } from "./content/deck";
import { worldToPlate } from "./engine/plateMath";
import { plateToScreen } from "./engine/view";
import { ViewController } from "./engine/viewController";
import { ShoulderRig, type SegmentTest, type Vec3 } from "./engine/realtime/shoulderRig";
import { CommanderControl } from "./life/control";

/** Where a body is; updated in place every frame. */
export interface ActorPose {
  id: string;
  x: number;
  y: number;
  z: number;
  /** Facing, radians about +Y (0 faces +Z). */
  yaw: number;
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
  /** The plate level the view streams: "overview", "M4", "M2" or "L0"; "3D" in the eye-level view. */
  plateLevel: string;
  actors: number;
  /** The eye-level view's quality tier ("high", "low"), empty on the plate. */
  tier: string;
}

/** The eye-level view while it is on screen: its camera and the deck's collision. */
export interface EyeView {
  camera: PerspectiveCamera;
  collider: MeshBVH | null;
  /** Segment test against the deck's collision (first hit as a fraction of the segment), when there is collision. */
  test?: SegmentTest | null;
}

/** A camera another mode drives (the duel's shoulder camera): world position, a point it looks at, vertical field of view. */
export interface CameraOverride {
  position: Vec3;
  target: Vec3;
  fovDeg: number;
}

/** A screen point (CSS px). */
export interface ScreenPoint { x: number; y: number }

/**
 * Geometry this close in front of a point (metres) still counts as seeing it:
 * a name plate on a head against a wall, a station label above a console.
 */
export const SIGHT_SLACK_M = 0.25;

export class StageRuntime {
  readonly view = new ViewController();
  /** Third person or bird's-eye, and the movement keys held for the commander. */
  readonly control = new CommanderControl();
  /** The over-the-shoulder camera of the eye-level view (kept across view switches). */
  readonly shoulder = new ShoulderRig();
  deck: Deck | null = null;
  /** The eye-level view, while it is the one on screen. */
  eye: EyeView | null = null;
  /** The eye-level camera is so close behind the commander (a wall pushed it in) that their body would fill the frame. */
  commanderHidden = false;
  /** While set, the eye-level view renders from this camera instead of the shoulder rig (a duel). */
  cameraOverride: CameraOverride | null = null;
  /** A duel holds the commander: the deck neither walks nor shows their usual body. */
  duelActive = false;
  /** The duel's hall while a duel runs: crew standing in it are not drawn (nobody walks into the line of fire). */
  duelArea: { x0: number; x1: number; z0: number; z1: number } | null = null;
  /** Put the commander here on the next frame (a duel ended), snapped onto the deck's nav grid. */
  placeCommander: { x: number; z: number; yaw: number } | null = null;
  /** Live poses of every actor on the deck, crew and commander alike, by id. */
  readonly poses = new Map<string, ActorPose>();
  readonly stats: FrameStats = { drawCalls: 0, triangles: 0, frameMs: 0, cpuMs: 0, tiles: 0, tilesLoading: 0, plateLevel: "overview", actors: 0, tier: "" };
  /** Called after each rendered frame (the HUD moves its plates here). */
  readonly afterFrame = new Set<() => void>();
  private readonly projected = new Vector3();
  private readonly raycaster = new Raycaster();
  private readonly ndc = new Vector2();
  private readonly sight = new Ray();

  /**
   * Screen position (CSS px) of a world point under the view on screen: the
   * eye-level camera's perspective or the plate's projection. Null when the
   * point is behind the eye-level camera (or nearer than its near plane).
   * Written into `out` when given, so per-frame callers allocate nothing.
   */
  toScreen(x: number, y: number, z: number, out?: ScreenPoint): ScreenPoint | null {
    if (!this.deck) return null;
    const o = out ?? { x: 0, y: 0 };
    if (this.eye) {
      const p = this.projected.set(x, y, z).project(this.eye.camera);
      if (!(p.z >= -1 && p.z <= 1)) return null;
      o.x = ((p.x + 1) / 2) * this.view.vp.width;
      o.y = ((1 - p.y) / 2) * this.view.vp.height;
      return o;
    }
    const p = worldToPlate(this.deck.camera, x, y, z);
    const s = plateToScreen(this.view.current, this.view.vp, p.u, p.v);
    o.x = s.x;
    o.y = s.y;
    return o;
  }

  /**
   * The eye-level camera sees the world point: none of the deck's geometry
   * lies on the line between them (up to `slack` short of the point). Always
   * true on the plate, where labels ride over the photograph, and while the
   * deck has no collision geometry.
   */
  inSight(x: number, y: number, z: number, slack = SIGHT_SLACK_M): boolean {
    const eye = this.eye;
    if (!eye?.collider) return true;
    const from = eye.camera.position;
    const ray = this.sight;
    ray.origin.copy(from);
    ray.direction.set(x - from.x, y - from.y, z - from.z);
    const length = ray.direction.length();
    if (length <= slack + 1e-3) return true;
    ray.direction.multiplyScalar(1 / length);
    return !eye.collider.raycastFirst(ray, DoubleSide, 0, length - slack);
  }

  /** The eye-level camera's ray through a screen point (CSS px), or null on the plate. */
  ray(sx: number, sy: number): Raycaster | null {
    if (!this.eye) return null;
    const { width, height } = this.view.vp;
    this.ndc.set((sx / Math.max(1, width)) * 2 - 1, 1 - (sy / Math.max(1, height)) * 2);
    this.raycaster.setFromCamera(this.ndc, this.eye.camera);
    return this.raycaster;
  }
}
