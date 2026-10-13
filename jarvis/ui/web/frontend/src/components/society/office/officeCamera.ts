/**
 * The office camera: a three-quarter view from the south-east, looking down
 * at about 40°, framed so the whole floor fits the viewport. Pure and tested.
 */
export const CAMERA_FOV = 35;

export const CAMERA_LIMITS = {
  /** Polar angle from straight down: ~20° (near top-down) to ~72° (near eye level). */
  minPolar: 0.35,
  maxPolar: 1.25,
  /** Close enough to read a desk or a wardrobe shelf, far enough to stay outside the character. */
  minDistance: 2.5,
  maxDistance: 140,
} as const;

/** Near clip plane up close, and the most it may grow to when zoomed out (a whole campus in view). */
const NEAR_MIN = 0.2;
const NEAR_MAX = 20;
/** Near plane per metre of orbit distance: the closest geometry is always far more than this in front. */
const NEAR_PER_METRE = 0.04;

/**
 * The near clip plane for a camera this far from its orbit target. Depth
 * precision falls with distance squared over the near plane: with a fixed
 * 0.2 m near plane, the oak floor 1 mm above the dark slab fought it in black
 * bands once the camera was zoomed out (~0.6 cm of precision at 140 m).
 * Growing the near plane with the zoom keeps it under a millimetre everywhere.
 */
export function depthNear(distance: number): number {
  return Math.min(NEAR_MAX, Math.max(NEAR_MIN, distance * NEAR_PER_METRE));
}

/**
 * A press that travelled further than this (CSS px) turned the camera; the
 * click it ends in is not a click. Measured over the whole press, so a drag
 * that comes back to where it started still counts as a drag.
 */
export const DRAG_CLICK_PX = 6;

/** One mouse-wheel notch, in CSS px, as browsers report it in pixel mode. */
const WHEEL_NOTCH_PX = 100;
/** How far one notch zooms, as OrbitControls' zoomSpeed: 0.95^2.4 ≈ 12 % closer or further. */
const ZOOM_SPEED_PER_NOTCH = 2.4;
/** From this orbit distance on a notch zooms further, up to FAR_ZOOM.boost times as far at FAR_ZOOM.full metres. */
const FAR_ZOOM = { from: 15, full: 90, boost: 3.5 } as const;

/** How much further one wheel notch zooms at this orbit distance than up close: 1 near the character, 3.5 from the overview of a campus. */
export function farZoomBoost(distance: number): number {
  const t = Math.min(1, Math.max(0, (distance - FAR_ZOOM.from) / (FAR_ZOOM.full - FAR_ZOOM.from)));
  return 1 + (FAR_ZOOM.boost - 1) * t;
}

/**
 * OrbitControls' zoomSpeed for one wheel event, proportional to how far the
 * wheel turned. The controls zoom a fixed step per event whatever its size:
 * a mouse notch crawled (~20 notches from the overview to the character) and
 * a trackpad, which sends dozens of tiny events, raced. `deltaMode` 1 is
 * lines, 2 pages (Firefox, some mice).
 *
 * `distance` is the camera's orbit distance: far out a notch covers more of
 * the way (12 % up close, 35 % from a campus overview), so zooming from the
 * overview of a large floor down to a studio takes a few notches, and the
 * last metres stay fine.
 */
export function wheelZoomSpeed(deltaY: number, deltaMode = 0, distance = 0): number {
  const px = Math.abs(deltaY) * (deltaMode === 1 ? 40 : deltaMode === 2 ? 800 : 1);
  const perNotch = ZOOM_SPEED_PER_NOTCH * farZoomBoost(distance);
  return Math.min(perNotch * 2.5, Math.max(0.02, (px / WHEEL_NOTCH_PX) * perNotch));
}

/** Look-down angle below the horizon and yaw east of south for the home view. */
export const HOME_PITCH_RAD = (40 * Math.PI) / 180;
export const HOME_YAW_RAD = (38 * Math.PI) / 180;

export interface Bounds { minX: number; maxX: number; minZ: number; maxZ: number }
export interface CameraPose { position: [number, number, number]; target: [number, number, number] }

/** Distance that fits a floor of this footprint into a viewport of this aspect. */
export function fitDistance(bounds: Bounds, aspect: number, fovDeg = CAMERA_FOV, tightness = 0.62, maxDistance: number = CAMERA_LIMITS.maxDistance): number {
  const width = bounds.maxX - bounds.minX;
  const depth = bounds.maxZ - bounds.minZ;
  // Seen diagonally, the floor's screen width is roughly its diagonal; its
  // screen height is the diagonal foreshortened by the look-down angle.
  const diagonal = Math.hypot(width, depth);
  const vHalf = ((fovDeg * Math.PI) / 180) / 2;
  const hHalf = Math.atan(Math.tan(vHalf) * Math.max(0.3, aspect));
  const needH = (diagonal * 0.5) / Math.tan(hHalf);
  const needV = (diagonal * Math.sin(HOME_PITCH_RAD) * 0.5 + 1.5) / Math.tan(vHalf);
  return Math.min(maxDistance, Math.max(CAMERA_LIMITS.minDistance, Math.max(needH, needV) * tightness));
}

/** How much of the viewport the overview fills: a margin stays for the HUD cards round the edge. */
const OVERVIEW_FILL = 0.9;
/** The overview also keeps what stands this high on the floor's edge in view (walls, signs, name plates). */
const OVERVIEW_HEADROOM_M = 3;

/** The home view's unit vectors: from the target towards the camera, and the camera's right and up. */
function homeAxes(): { back: [number, number, number]; right: [number, number, number]; up: [number, number, number] } {
  const cp = Math.cos(HOME_PITCH_RAD), sp = Math.sin(HOME_PITCH_RAD);
  const sy = Math.sin(HOME_YAW_RAD), cy = Math.cos(HOME_YAW_RAD);
  return { back: [sy * cp, sp, cy * cp], right: [cy, 0, -sy], up: [-sy * sp, cp, -cy * sp] };
}

/**
 * The distance from which the home view holds every corner of `bounds` (on
 * the floor and `headroom` above it) inside the viewport: the exact fit, by
 * projecting the corners, for a floor of any size and shape.
 */
export function frameDistance(bounds: Bounds, aspect: number, fovDeg = CAMERA_FOV, fill = OVERVIEW_FILL, headroom = OVERVIEW_HEADROOM_M): number {
  const { back, right, up } = homeAxes();
  const tanV = Math.tan((fovDeg * Math.PI) / 360) * fill;
  const tanH = Math.tan((fovDeg * Math.PI) / 360) * Math.max(0.3, aspect) * fill;
  const cx = (bounds.minX + bounds.maxX) / 2, cz = (bounds.minZ + bounds.maxZ) / 2;
  let need: number = CAMERA_LIMITS.minDistance;
  for (const x of [bounds.minX, bounds.maxX]) {
    for (const z of [bounds.minZ, bounds.maxZ]) {
      for (const y of [0, headroom]) {
        const p: [number, number, number] = [x - cx, y, z - cz];
        const dot = (a: [number, number, number]) => p[0] * a[0] + p[1] * a[1] + p[2] * a[2];
        // A point this far towards the camera is that much closer to it than the target is.
        const towards = dot(back);
        need = Math.max(need, Math.abs(dot(right)) / tanH + towards, Math.abs(dot(up)) / tanV + towards);
      }
    }
  }
  return need;
}

/** How much of the viewport's binding axis the floor spans in the overview. */
export const OVERVIEW_SPAN = 0.85;

/**
 * Where the corners of `bounds` (on the floor and `headroom` above it) land
 * in the view of a home-angle camera looking at `target` from `distance`:
 * the box they span, in viewport units from -1 to 1.
 */
function projectedBox(bounds: Bounds, target: readonly [number, number], distance: number, aspect: number, fovDeg: number, headroom: number) {
  const { back, right, up } = homeAxes();
  const tanV = Math.tan((fovDeg * Math.PI) / 360);
  const tanH = tanV * Math.max(0.3, aspect);
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const x of [bounds.minX, bounds.maxX]) {
    for (const z of [bounds.minZ, bounds.maxZ]) {
      for (const y of [0, headroom]) {
        const p: [number, number, number] = [x - target[0], y, z - target[1]];
        const dot = (a: [number, number, number]) => p[0] * a[0] + p[1] * a[1] + p[2] * a[2];
        const depth = Math.max(0.01, distance - dot(back));
        const sx = dot(right) / (depth * tanH), sy = dot(up) / (depth * tanV);
        minX = Math.min(minX, sx); maxX = Math.max(maxX, sx); minY = Math.min(minY, sy); maxY = Math.max(maxY, sy);
      }
    }
  }
  return { minX, maxX, minY, maxY };
}

/**
 * The overview: the whole floor, railing included, from the home angle,
 * fitted to the viewport. The near corner of a floor seen at an angle looms
 * larger than the far one, so looking at the floor's middle leaves the upper
 * part of the view empty and the plan small; instead the look-at point is
 * moved until the plan sits in the middle of the view, and the camera comes
 * as close as the plan allows: it spans `OVERVIEW_SPAN` of whichever axis of
 * the viewport binds (the height in a wide window, the width in a narrow
 * panel).
 */
export function campusOverview(bounds: Bounds, aspect: number, fovDeg = CAMERA_FOV): CameraPose {
  const { back, right } = homeAxes();
  const tanV = Math.tan((fovDeg * Math.PI) / 360);
  const tanH = tanV * Math.max(0.3, aspect);
  // The horizontal direction the camera looks along: moving the look-at point this way slides the plan down the view.
  const ahead: [number, number] = [-Math.sin(HOME_YAW_RAD), -Math.cos(HOME_YAW_RAD)];
  const target: [number, number] = [(bounds.minX + bounds.maxX) / 2, (bounds.minZ + bounds.maxZ) / 2];
  let distance = frameDistance(bounds, aspect, fovDeg);
  for (let i = 0; i < 12; i += 1) {
    const box = projectedBox(bounds, target, distance, aspect, fovDeg, OVERVIEW_HEADROOM_M);
    // Centre the plan: sideways along the camera's right, up and down along the floor.
    const offX = (box.minX + box.maxX) / 2, offY = (box.minY + box.maxY) / 2;
    target[0] += right[0] * offX * distance * tanH + (ahead[0] * offY * distance * tanV) / Math.sin(HOME_PITCH_RAD);
    target[1] += right[2] * offX * distance * tanH + (ahead[1] * offY * distance * tanV) / Math.sin(HOME_PITCH_RAD);
    // Then come as close as the plan allows.
    const centred = projectedBox(bounds, target, distance, aspect, fovDeg, OVERVIEW_HEADROOM_M);
    const span = Math.max(centred.maxX - centred.minX, centred.maxY - centred.minY) / 2;
    distance = Math.max(CAMERA_LIMITS.minDistance, distance * (span / OVERVIEW_SPAN));
  }
  return {
    target: [target[0], 0, target[1]],
    position: [target[0] + back[0] * distance, back[1] * distance, target[1] + back[2] * distance],
  };
}

/**
 * Zoom limits for a floor: the wheel may always back away far enough for the
 * overview (and a little beyond), never less than the default. A small floor
 * keeps the default; a campus several times larger gets the room it needs.
 */
export function cameraLimitsFor(bounds: Bounds, aspect: number): { minPolar: number; maxPolar: number; minDistance: number; maxDistance: number } {
  return { ...CAMERA_LIMITS, maxDistance: Math.max(CAMERA_LIMITS.maxDistance, Math.ceil(frameDistance(bounds, aspect) * 1.15)) };
}

/** The distance the camera follows the character from when nothing else is known. */
export const FOLLOW_DISTANCE_M = 15;
/** A view from further away than this is an overview, not a view to walk in. */
export const WALK_VIEW_MAX_M = 36;

/**
 * The distance following glides back to after the overview: what it was
 * before the overview when that was a view to walk in, else the default.
 * Without this "follow me" re-centred on the character but stayed a campus
 * away from it.
 */
export function followDistanceAfterOverview(before: number | null): number {
  return before !== null && before <= WALK_VIEW_MAX_M ? Math.max(CAMERA_LIMITS.minDistance, before) : FOLLOW_DISTANCE_M;
}

/** A camera this low can stand inside a wall; higher it looks over every wall of the floor. */
const WALL_TOP_M = 3.8;
/** How close to a wall's footprint the camera may stand. */
const WALL_CLEAR_M = 0.35;

/**
 * A remembered view checked against the floor it is restored on (the plan
 * may have been rebuilt meanwhile): null when it looks at a point outside
 * the floor, so the caller starts from the character instead; otherwise the
 * view, with a camera that would stand inside a wall backed away from its
 * target until it is clear.
 */
export function settleView(pose: CameraPose, bounds: Bounds, walls: readonly Bounds[]): CameraPose | null {
  const [tx, , tz] = pose.target;
  if (tx < bounds.minX || tx > bounds.maxX || tz < bounds.minZ || tz > bounds.maxZ) return null;
  const inWall = (x: number, y: number, z: number) => y < WALL_TOP_M
    && walls.some((w) => x > w.minX - WALL_CLEAR_M && x < w.maxX + WALL_CLEAR_M && z > w.minZ - WALL_CLEAR_M && z < w.maxZ + WALL_CLEAR_M);
  let [x, y, z] = pose.position;
  if (!inWall(x, y, z)) return pose;
  const dx = x - pose.target[0], dy = y - pose.target[1], dz = z - pose.target[2];
  const length = Math.hypot(dx, dy, dz) || 1;
  for (let back = 0.5; back <= 12; back += 0.5) {
    const k = (length + back) / length;
    x = pose.target[0] + dx * k; y = pose.target[1] + dy * k; z = pose.target[2] + dz * k;
    if (!inWall(x, y, z)) break;
  }
  return { target: pose.target, position: [x, y, z] };
}

/** Further than this from the character, re-entering follow glides over like a fly-to instead of snapping across the floor. */
export const FOLLOW_CATCH_UP_M = 12;
/** How fast the view closes on the character while following (per second, exponential). */
export const FOLLOW_RATE = 8;

/**
 * One frame of following: the share of the remaining gap the view closes.
 * Exponential, so it is the same motion at any frame rate, and it eases out
 * instead of stopping dead when the character does.
 */
export function followBlend(dt: number): number {
  return 1 - Math.exp(-FOLLOW_RATE * Math.max(0, dt));
}

/** Smallest area the home view frames, so a lone agent still shows its neighbourhood. */
const MIN_FOCUS_W = 18;
const MIN_FOCUS_D = 14;

/** Pad the occupied area to a readable neighbourhood around it. */
export function focusBounds(points: readonly { x: number; z: number }[]): Bounds | null {
  if (points.length === 0) return null;
  const xs = points.map((p) => p.x), zs = points.map((p) => p.z);
  const cx = (Math.min(...xs) + Math.max(...xs)) / 2, cz = (Math.min(...zs) + Math.max(...zs)) / 2;
  const w = Math.max(MIN_FOCUS_W, Math.max(...xs) - Math.min(...xs) + 6);
  const d = Math.max(MIN_FOCUS_D, Math.max(...zs) - Math.min(...zs) + 6);
  return { minX: cx - w / 2, maxX: cx + w / 2, minZ: cz - d / 2, maxZ: cz + d / 2 };
}

/** Home view: frame where the agents sit, or the whole floor when nobody does. */
export function cameraHome(bounds: Bounds, aspect: number, focus: Bounds | null = null): CameraPose {
  const frame = focus ?? bounds;
  const target: [number, number, number] = [(frame.minX + frame.maxX) / 2, 0, (frame.minZ + frame.maxZ) / 2];
  // The whole floor must fit edge to edge; a focus area may crop its padding.
  const distance = fitDistance(frame, aspect, CAMERA_FOV, focus ? 0.62 : 0.9);
  const horizontal = Math.cos(HOME_PITCH_RAD) * distance;
  return {
    target,
    position: [
      target[0] + Math.sin(HOME_YAW_RAD) * horizontal,
      Math.sin(HOME_PITCH_RAD) * distance,
      target[2] + Math.cos(HOME_YAW_RAD) * horizontal,
    ],
  };
}
