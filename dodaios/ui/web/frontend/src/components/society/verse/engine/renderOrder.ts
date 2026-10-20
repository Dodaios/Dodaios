/**
 * Draw order of the hybrid frame (BRIEF §3), in three passes (StageRenderer):
 *
 * 1. the backdrop layer: the plate with no depth, then the occluders into the
 *    depth buffer only;
 * 2. the x-ray layer: actor bodies as faint silhouettes wherever an occluder
 *    is in front of them (depth test GREATER against the occluders alone, so
 *    one crew member standing behind another never shows through);
 * 3. everything live on the default layer, which the occluders hide where the
 *    photograph has a wall or console in front, and which covers its own
 *    silhouette wherever it is in plain view.
 *
 * Within a pass, renderOrder sorts; transparent effects come after opaque
 * draws (three.js keeps them in their own list).
 */
export const RENDER_ORDER = {
  plate: -1000,
  plateTile: -999,
  occluder: -500,
  actor: 0,
  screen: 10,
  /** Transparent list. */
  contactShadow: -10,
  holo: 20,
  flicker: 30,
  beacon: 100,
} as const;

/** The plate and the occluders. */
export const BACKDROP_LAYER = 4;
/** The parts of actors' bodies that make their silhouette. */
export const XRAY_LAYER = 1;
/** Development overlays (socket markers, occluder wireframes). */
export const DEBUG_LAYER = 2;
