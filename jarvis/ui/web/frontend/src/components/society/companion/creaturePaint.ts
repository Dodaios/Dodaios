/**
 * Paints a pixel creature as small cubes on a 2D canvas: a profile face with
 * depth, without WebGL. The cubes are turned a little to the side and seen
 * slightly from above, lit from the front and painted back to front. A
 * roster of faces costs a few hundred filled quads each, and only when a
 * face actually changes.
 */
import {
  creatureBitColor, creatureCubes, mixRgb, STAGE_H, STAGE_W, STAGE_X, STAGE_Y,
  type CreatureBody, type CreaturePose, type Rgb,
} from "./creature";

/** How far a profile face is turned, radians: enough to show one side of the block. */
export const FACE_YAW = -0.34;
/** The share of its square a full 9 x 9 figure fills, leaving the air a shape symbol has. */
const FACE_FILL = 0.88;
/** How far the viewer looks down on it, radians. */
const PITCH = 0.34;

const WHITE: Rgb = [255, 255, 255];
const BLACK: Rgb = [0, 0, 0];

function css(color: Rgb, alpha = 1): string {
  return `rgba(${color[0] | 0},${color[1] | 0},${color[2] | 0},${alpha})`;
}

interface CubeFace {
  normal: readonly [number, number, number];
  corners: readonly (readonly [number, number, number])[];
}

const CUBE_FACES: CubeFace[] = [];
for (const axis of [0, 1, 2]) for (const sign of [1, -1]) {
  const normal: [number, number, number] = [0, 0, 0];
  normal[axis] = sign;
  const [a, b] = [0, 1, 2].filter((index) => index !== axis) as [number, number];
  const corners = ([[-.5, -.5], [.5, -.5], [.5, .5], [-.5, .5]] as const).map(([s, t]) => {
    const corner: [number, number, number] = [0, 0, 0];
    corner[axis] = sign * .5;
    corner[a] = s;
    corner[b] = t;
    return corner;
  });
  CUBE_FACES.push({ normal, corners });
}

interface Quad {
  points: [number, number][];
  depth: number;
  alpha: number;
  color: string;
}

/**
 * Draws one pose into a canvas `width` pixels wide that shows the whole
 * stage (STAGE_W x STAGE_H cells). The figure is centred on its own rows,
 * so a creature without legs or ornaments does not sit off-centre.
 */
export function paintCreature(ctx: CanvasRenderingContext2D, width: number, body: CreatureBody, pose: CreaturePose, yaw: number = FACE_YAW): void {
  const unit = width / STAGE_W, scale = unit * FACE_FILL;
  ctx.clearRect(0, 0, width, Math.round(unit * STAGE_H));
  const cubes = creatureCubes(body, pose);
  const taken = new Set<string>();
  for (const cube of cubes) if (cube.alpha === 1) taken.add(`${cube.x},${cube.y},${cube.z}`);
  const cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(PITCH), sp = Math.sin(PITCH);
  const lift = (body.top + body.bottom) / 2 - 4;
  const ox = (STAGE_X + 4.5) * unit, oy = (STAGE_Y + 4.5) * unit;
  const quads: Quad[] = [];
  for (const cube of cubes) {
    const X = cube.x - 4, Y = 4 + lift - cube.y;
    for (const side of CUBE_FACES) {
      // The pose uses y downwards, the cube faces y upwards.
      if (cube.alpha === 1 && taken.has(`${cube.x + side.normal[0]},${cube.y - side.normal[1]},${cube.z + side.normal[2]}`)) continue;
      const turned = -side.normal[0] * sy + side.normal[2] * cy;
      const ny = side.normal[1] * cp - turned * sp, nz = side.normal[1] * sp + turned * cp;
      if (nz <= .01) continue;
      let depth = 0;
      const points = side.corners.map(([a, b, c]): [number, number] => {
        const x = X + a, y = Y + b, z = cube.z + c, x1 = x * cy + z * sy, z1 = -x * sy + z * cy;
        depth += y * sp + z1 * cp;
        return [ox + x1 * scale, oy - (y * cp - z1 * sp) * scale];
      });
      const light = .7 + .3 * nz + .3 * Math.max(0, ny);
      quads.push({ points, depth, alpha: cube.alpha, color: css(light <= 1 ? mixRgb(BLACK, cube.color, light) : mixRgb(cube.color, WHITE, (light - 1) * 1.5)) });
    }
  }
  quads.sort((a, b) => a.depth - b.depth);
  // Every solid face reaches a little past its edges, which closes the seams
  // between neighbours for the price of one fill (a stroke would double the work).
  const overlap = Math.max(.5, scale * .02);
  for (const quad of quads) {
    const grow = quad.alpha === 1 ? overlap : 0;
    const cx = (quad.points[0]![0] + quad.points[2]![0]) / 2, cy = (quad.points[0]![1] + quad.points[2]![1]) / 2;
    ctx.globalAlpha = quad.alpha;
    ctx.fillStyle = quad.color;
    ctx.beginPath();
    for (let i = 0; i < 4; i++) {
      const dx = quad.points[i]![0] - cx, dy = quad.points[i]![1] - cy;
      const reach = grow / (Math.hypot(dx, dy) || 1);
      const x = quad.points[i]![0] + dx * reach, y = quad.points[i]![1] + dy * reach;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.closePath();
    ctx.fill();
  }
  // Signs and sparks stay flat and upright: they are read, not looked at.
  for (const bit of pose.bits) {
    const x0 = Math.round((STAGE_X + bit.x) * unit), y0 = Math.round((STAGE_Y + bit.y) * unit);
    ctx.globalAlpha = bit.alpha;
    ctx.fillStyle = css(creatureBitColor(body, bit));
    ctx.fillRect(x0, y0, Math.round((STAGE_X + bit.x + 1) * unit) - x0, Math.round((STAGE_Y + bit.y + 1) * unit) - y0);
  }
  ctx.globalAlpha = 1;
}
