/**
 * Draws an agent's shape as a small 3D figure on the CPU: the same meshes
 * the map uses, turned a little to the side, lit from the upper left and
 * set on a soft ground shadow. The result is a plain RGBA image, so a profile
 * face is real 3D without a WebGL context. Everything here is pure; the
 * worker (figure.worker.ts) calls it off the UI thread.
 *
 * The work is split in two. `traceFigure` finds what every sample sees (the
 * surface, its normal, how much light and sky reach it); that depends only on
 * the meshes and the size. `shadeFigure` turns it into colours, which is
 * cheap, so trying another colour on the same figure costs almost nothing.
 */
import type { FigureMesh, LinearRgb } from "./figureGlb";

/** How far a figure is turned, radians: the same turn a pixel creature has. */
export const FIGURE_YAW = -0.34;
/** How far the viewer looks down on it, radians. */
export const FIGURE_PITCH = 0.3;

/** A colour design over a part; the layout matches the map's body material (skinMaterial.ts). */
export interface FigurePaint {
  colors: LinearRgb[];
  radial: boolean;
  /** CSS angle, degrees (0 = up, 90 = right). */
  angle: number;
  /** Index in SKIN_EFFECTS: none, stars, shimmer, flow, glow, sparkle. */
  effect: number;
  highlight: LinearRgb;
}

export interface FigurePart {
  mesh: FigureMesh;
  color: LinearRgb;
  /** "ink" (eyes) and "glow" (an ember) are drawn unlit. */
  finish: "matte" | "ink" | "glow";
  roughness: number;
  /** Where the mesh sits: model = offset + scale x position. */
  offset?: readonly [number, number, number];
  scale?: number;
  /** Wins against surfaces up to this far in front of it, metres (glasses over the eyes). */
  lift?: number;
  paint?: FigurePaint;
  /** Part of the body itself: the ground shadow follows its footprint. */
  body?: boolean;
}

/** What the look of one part adds to its traced surface. */
export type FigureCoat = Pick<FigurePart, "color" | "finish" | "roughness" | "paint">;

/** How model metres land on the image: `x = ox + xv * k`, `y = oy - yv * k` in view space. */
export interface FigureFrame { k: number; ox: number; oy: number; yaw: number; pitch: number }

export interface FigureImage {
  size: number;
  /** Straight-alpha RGBA, `size` x `size`. */
  data: Uint8ClampedArray;
  frame: FigureFrame;
}

/** Everything about a figure that does not depend on its colours. */
export interface FigureTrace {
  size: number;
  /** Samples per pixel along one axis. */
  samples: number;
  /** In samples, like the buffers below. */
  frame: FigureFrame;
  /** View depth of the nearest surface per sample. */
  depth: Float32Array;
  /** Its view-space normal, three signed bytes. */
  normal: Int8Array;
  /** Its part, counted from 1; 0 where nothing was hit. */
  owner: Uint8Array;
  /** How much of the key light reaches it, 0 to 255. */
  light: Uint8Array;
  /** How much of the sky it sees, 0 to 255. */
  open: Uint8Array;
  /** The body's box in model space: a colour design spans it. */
  box: { min: [number, number, number]; max: [number, number, number] };
  /** The body's footprint on the ground, model x and z; undefined when nothing stands. */
  foot?: { x: number; z: number; rx: number; rz: number };
}

/** Where a model point lands on an image with this frame, pixels. */
export function projectFigure(frame: FigureFrame, x: number, y: number, z: number): [number, number] {
  const cy = Math.cos(frame.yaw), sy = Math.sin(frame.yaw), cp = Math.cos(frame.pitch), sp = Math.sin(frame.pitch);
  const x1 = x * cy + z * sy, z1 = -x * sy + z * cy;
  return [frame.ox + x1 * frame.k, frame.oy - (y * cp - z1 * sp) * frame.k];
}

function normalize(x: number, y: number, z: number): [number, number, number] {
  const length = Math.hypot(x, y, z) || 1;
  return [x / length, y / length, z / length];
}

// View space: x to the right, y up, z toward the viewer.
const KEY = normalize(-0.5, 0.72, 0.5);
const FILL = normalize(0.75, 0.05, 0.6);
const RIM = normalize(0.6, 0.5, -0.6);
const HALF = normalize(KEY[0], KEY[1], KEY[2] + 1);
const KEY_COLOR: LinearRgb = [0.8, 0.77, 0.72];
const SKY: LinearRgb = [0.5, 0.53, 0.6];
const GROUND: LinearRgb = [0.25, 0.23, 0.23];
const FILL_COLOR: LinearRgb = [0.1, 0.12, 0.15];

/** The share of the image left free around the figure and its shadow. */
const PAD = 0.03;
const SHADOW_ALPHA = 0.3;
/** The shadow reaches this far past the footprint, in footprint radii. */
const SHADOW_REACH = 1.18;
/** It lies a little away from the light: this far along x and z, in footprint radii. */
const SHADOW_SHIFT_X = 0.16, SHADOW_SHIFT_Z = -0.1;

const AO_TAPS: readonly (readonly [number, number])[] = Array.from({ length: 10 }, (_, index) => {
  // A golden-angle spiral: even cover of the disc from few taps.
  const radius = Math.sqrt((index + 0.5) / 10), angle = index * 2.399963;
  return [Math.cos(angle) * radius, Math.sin(angle) * radius] as const;
});

function fract(value: number): number { return value - Math.floor(value); }
function hash(x: number, y: number, z: number): number { return fract(Math.sin(x * 127.1 + y * 311.7 + z * 74.7) * 43758.5453); }
function smooth(edge0: number, edge1: number, value: number): number {
  const t = Math.max(0, Math.min(1, (value - edge0) / (edge1 - edge0)));
  return t * t * (3 - 2 * t);
}

/** Bright specks scattered through the body's volume (stars, sparkles). */
function specks(x: number, y: number, z: number, cells: number, density: number): number {
  const qx = x * cells, qy = y * cells, qz = z * cells;
  const cx = Math.floor(qx), cy = Math.floor(qy), cz = Math.floor(qz);
  if (hash(cx, cy, cz) < 1 - density) return 0;
  const dx = qx - cx - 0.5 - (hash(cx + 1.7, cy + 1.7, cz + 1.7) - 0.5) * 0.5;
  const dy = qy - cy - 0.5 - (hash(cx + 4.3, cy + 4.3, cz + 4.3) - 0.5) * 0.5;
  const dz = qz - cz - 0.5 - (hash(cx + 8.9, cy + 8.9, cz + 8.9) - 0.5) * 0.5;
  return smooth(0.24, 0.02, Math.hypot(dx, dy, dz)) * 0.85;
}

function ramp(colors: readonly LinearRgb[], t: number, out: Float32Array): void {
  const at = Math.max(0, Math.min(1, t)) * (colors.length - 1);
  const index = Math.min(colors.length - 2, Math.floor(at)), mix = at - index;
  const a = colors[index]!, b = colors[index + 1]!;
  out[0] = a[0] + (b[0] - a[0]) * mix; out[1] = a[1] + (b[1] - a[1]) * mix; out[2] = a[2] + (b[2] - a[2]) * mix;
}

function ring(colors: readonly LinearRgb[], u: number, out: Float32Array): void {
  const at = fract(u) * colors.length;
  const index = Math.min(colors.length - 1, Math.floor(at)), mix = at - index;
  const a = colors[index]!, b = colors[(index + 1) % colors.length]!;
  out[0] = a[0] + (b[0] - a[0]) * mix; out[1] = a[1] + (b[1] - a[1]) * mix; out[2] = a[2] + (b[2] - a[2]) * mix;
}

const TO_SRGB = new Uint8Array(4097);
for (let i = 0; i <= 4096; i++) {
  const c = i / 4096;
  TO_SRGB[i] = Math.round(255 * (c <= 0.0031308 ? c * 12.92 : 1.055 * c ** (1 / 2.4) - 0.055));
}

/** Bright light rolls off softly instead of clipping to a flat patch. */
function shoulder(value: number): number {
  return value <= 0.8 ? value : 0.8 + 0.2 * Math.tanh((value - 0.8) / 0.2);
}

/**
 * Fills a depth buffer with the nearest surface per cell. `sx`, `sy` are
 * cell coordinates, `sz` grows toward the eye. With `shade`, the winning
 * triangle also leaves its interpolated normal and the part's number.
 */
export function rasterize(
  width: number, depth: Float32Array, indices: Uint16Array | Uint32Array, sx: Float32Array, sy: Float32Array, sz: Float32Array,
  shade?: { nx: Float32Array; ny: Float32Array; nz: Float32Array; id: number; normal: Int8Array; owner: Uint8Array },
): void {
  for (let t = 0; t < indices.length; t += 3) {
    const a = indices[t]!, b = indices[t + 1]!, c = indices[t + 2]!;
    const x0 = sx[a]!, y0 = sy[a]!, x1 = sx[b]!, y1 = sy[b]!, x2 = sx[c]!, y2 = sy[c]!;
    const area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0);
    if (area === 0) continue;
    const minX = Math.max(0, Math.floor(Math.min(x0, x1, x2))), maxX = Math.min(width - 1, Math.ceil(Math.max(x0, x1, x2)));
    const minY = Math.max(0, Math.floor(Math.min(y0, y1, y2))), maxY = Math.min(width - 1, Math.ceil(Math.max(y0, y1, y2)));
    if (minX > maxX || minY > maxY) continue;
    const inv = 1 / area, z0 = sz[a]!, z1 = sz[b]!, z2 = sz[c]!;
    const step0 = (y1 - y2) * inv, step1 = (y2 - y0) * inv;
    for (let py = minY; py <= maxY; py++) {
      const cy = py + 0.5, cx = minX + 0.5;
      let w0 = ((x1 - cx) * (y2 - cy) - (x2 - cx) * (y1 - cy)) * inv;
      let w1 = ((x2 - cx) * (y0 - cy) - (x0 - cx) * (y2 - cy)) * inv;
      let at = py * width + minX;
      for (let px = minX; px <= maxX; px++, at++, w0 += step0, w1 += step1) {
        const w2 = 1 - w0 - w1;
        if (w0 < -1e-4 || w1 < -1e-4 || w2 < -1e-4) continue;
        const z = w0 * z0 + w1 * z1 + w2 * z2;
        if (z <= depth[at]!) continue;
        depth[at] = z;
        if (!shade) continue;
        let nx = w0 * shade.nx[a]! + w1 * shade.nx[b]! + w2 * shade.nx[c]!;
        let ny = w0 * shade.ny[a]! + w1 * shade.ny[b]! + w2 * shade.ny[c]!;
        let nz = w0 * shade.nz[a]! + w1 * shade.nz[b]! + w2 * shade.nz[c]!;
        // A surface seen from behind (an open patch of cloth) is lit like its front.
        const scale = (nz < 0 ? -127 : 127) / (Math.hypot(nx, ny, nz) || 1);
        nx *= scale; ny *= scale; nz *= scale;
        shade.normal[at * 3] = Math.round(nx); shade.normal[at * 3 + 1] = Math.round(ny); shade.normal[at * 3 + 2] = Math.round(nz);
        shade.owner[at] = shade.id;
      }
    }
  }
}

/** The colour-independent half of a picture: see the file comment. */
export function traceFigure(parts: readonly Pick<FigurePart, "mesh" | "offset" | "scale" | "lift" | "body" | "finish">[], size: number, yaw: number = FIGURE_YAW, pitch: number = FIGURE_PITCH): FigureTrace {
  const cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch);
  // Small faces get more samples per pixel: their edges are most of the picture.
  const samples = size <= 48 ? 4 : size <= 110 ? 3 : 2;
  const width = Math.max(1, size) * samples, area = width * width;
  const trace: FigureTrace = {
    size, samples, frame: { k: 1, ox: 0, oy: 0, yaw, pitch },
    depth: new Float32Array(area).fill(-Infinity), normal: new Int8Array(area * 3), owner: new Uint8Array(area),
    light: new Uint8Array(area), open: new Uint8Array(area), box: { min: [0, 0, 0], max: [1, 1, 1] },
  };
  if (!parts.length || size < 1) return trace;

  // 1. Every vertex into view space; the bounds decide the framing.
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity, bodyTop = 0;
  const min: [number, number, number] = [Infinity, Infinity, Infinity], max: [number, number, number] = [-Infinity, -Infinity, -Infinity];
  const placed = parts.map(part => {
    const count = part.mesh.positions.length / 3;
    const out = {
      part, x: new Float32Array(count), y: new Float32Array(count), z: new Float32Array(count),
      nx: new Float32Array(count), ny: new Float32Array(count), nz: new Float32Array(count),
    };
    const scale = part.scale ?? 1, [dx, dy, dz] = part.offset ?? [0, 0, 0];
    const { positions, normals } = part.mesh;
    for (let i = 0; i < count; i++) {
      const mx = dx + positions[i * 3]! * scale, my = dy + positions[i * 3 + 1]! * scale, mz = dz + positions[i * 3 + 2]! * scale;
      const z1 = -mx * sy + mz * cy;
      const xv = mx * cy + mz * sy, yv = my * cp - z1 * sp;
      out.x[i] = xv; out.y[i] = yv; out.z[i] = my * sp + z1 * cp;
      if (xv < minX) minX = xv; if (xv > maxX) maxX = xv; if (yv < minY) minY = yv; if (yv > maxY) maxY = yv;
      const ax = normals[i * 3]!, ay = normals[i * 3 + 1]!, az = normals[i * 3 + 2]!;
      const nz1 = -ax * sy + az * cy;
      out.nx[i] = ax * cy + az * sy; out.ny[i] = ay * cp - nz1 * sp; out.nz[i] = ay * sp + nz1 * cp;
      if (part.body) {
        if (my > bodyTop) bodyTop = my;
        if (mx < min[0]) min[0] = mx; if (mx > max[0]) max[0] = mx;
        if (my < min[1]) min[1] = my; if (my > max[1]) max[1] = my;
        if (mz < min[2]) min[2] = mz; if (mz > max[2]) max[2] = mz;
      }
    }
    return out;
  });
  if (!(maxX > minX) || !(maxY > minY)) return trace;
  if (max[0] > min[0]) trace.box = { min, max };

  // What stands on the ground casts the shadow under it; the picture makes room for it.
  let footMinX = Infinity, footMaxX = -Infinity, footMinZ = Infinity, footMaxZ = -Infinity;
  for (const item of placed) {
    if (!item.part.body) continue;
    const scale = item.part.scale ?? 1, [dx, , dz] = item.part.offset ?? [0, 0, 0];
    const { positions } = item.part.mesh;
    for (let i = 0; i < positions.length; i += 3) {
      if (positions[i + 1]! * scale > bodyTop * 0.3) continue;
      const mx = dx + positions[i]! * scale, mz = dz + positions[i + 2]! * scale;
      if (mx < footMinX) footMinX = mx; if (mx > footMaxX) footMaxX = mx; if (mz < footMinZ) footMinZ = mz; if (mz > footMaxZ) footMaxZ = mz;
    }
  }
  if (sp > 0.05 && footMaxX > footMinX && footMaxZ > footMinZ) {
    const rx = (footMaxX - footMinX) / 2, rz = (footMaxZ - footMinZ) / 2;
    const foot = { x: (footMinX + footMaxX) / 2 + rx * SHADOW_SHIFT_X, z: (footMinZ + footMaxZ) / 2 + rz * SHADOW_SHIFT_Z, rx, rz };
    trace.foot = foot;
    // Only the dense middle of the shadow has to fit; its faint rim may leave the picture.
    for (let step = 0; step < 16; step++) {
      const angle = step / 16 * Math.PI * 2;
      const mx = foot.x + Math.cos(angle) * rx * 0.75, mz = foot.z + Math.sin(angle) * rz * 0.75;
      const z1 = -mx * sy + mz * cy;
      const xv = mx * cy + mz * sy, yv = -z1 * sp;
      if (xv < minX) minX = xv; if (xv > maxX) maxX = xv; if (yv < minY) minY = yv; if (yv > maxY) maxY = yv;
    }
  }

  const spanX = maxX - minX, spanY = maxY - minY, extent = Math.max(spanX, spanY);
  const k = width * (1 - 2 * PAD) / extent;
  const ox = width / 2 - (minX + maxX) / 2 * k, oy = width / 2 + (minY + maxY) / 2 * k;
  trace.frame = { k, ox, oy, yaw, pitch };

  // 2. The nearest surface per sample, with its normal and its part.
  const { depth, normal, owner, light, open } = trace;
  placed.forEach((item, index) => {
    if (index >= 255) return;
    const lift = item.part.lift ?? 0;
    rasterize(width, depth, item.part.mesh.indices, item.x.map(value => ox + value * k), item.y.map(value => oy - value * k), lift ? item.z.map(value => value + lift) : item.z,
      { nx: item.nx, ny: item.ny, nz: item.nz, id: index + 1, normal, owner });
  });

  // 3. The same scene seen from the key light: what it cannot see lies in shadow.
  const lx = normalize(KEY[2], 0, -KEY[0]);
  const ly: [number, number, number] = [KEY[1] * lx[2] - KEY[2] * lx[1], KEY[2] * lx[0] - KEY[0] * lx[2], KEY[0] * lx[1] - KEY[1] * lx[0]];
  let minU = Infinity, maxU = -Infinity, minV = Infinity, maxV = -Infinity;
  const lit = placed.map(item => {
    const count = item.x.length, u = new Float32Array(count), v = new Float32Array(count), d = new Float32Array(count);
    for (let i = 0; i < count; i++) {
      const x = item.x[i]!, y = item.y[i]!, z = item.z[i]!;
      const pu = x * lx[0] + y * lx[1] + z * lx[2], pv = x * ly[0] + y * ly[1] + z * ly[2];
      u[i] = pu; v[i] = pv; d[i] = x * KEY[0] + y * KEY[1] + z * KEY[2];
      if (pu < minU) minU = pu; if (pu > maxU) maxU = pu; if (pv < minV) minV = pv; if (pv > maxV) maxV = pv;
    }
    return { u, v, d };
  });
  const map = Math.min(width, 320);
  const mapScale = (map - 4) / Math.max(maxU - minU, maxV - minV);
  const lightDepth = new Float32Array(map * map).fill(-Infinity);
  placed.forEach((item, index) => {
    // Ink lies on the surface and casts nothing.
    if (item.part.finish === "ink") return;
    const { u, v, d } = lit[index]!;
    rasterize(map, lightDepth, item.part.mesh.indices, u.map(value => 2 + (value - minU) * mapScale), v.map(value => 2 + (value - minV) * mapScale), d);
  });
  const shadowBias = extent * 0.035;

  // 4. Per sample: how much key light arrives, and how much of the sky is in view.
  const aoRadius = width * 0.075, aoReach = extent * 0.16;
  for (let py = 0; py < width; py++) {
    for (let px = 0; px < width; px++) {
      const at = py * width + px;
      if (!owner[at]) continue;
      const zv = depth[at]!;
      const xv = (px + 0.5 - ox) / k, yv = (oy - py - 0.5) / k;
      const lu = 2 + (xv * lx[0] + yv * lx[1] + zv * lx[2] - minU) * mapScale;
      const lv = 2 + (xv * ly[0] + yv * ly[1] + zv * ly[2] - minV) * mapScale;
      const ld = xv * KEY[0] + yv * KEY[1] + zv * KEY[2] + shadowBias;
      let seen = 0;
      for (let tapY = -1; tapY <= 1; tapY++) for (let tapX = -1; tapX <= 1; tapX++) {
        const mu = Math.max(0, Math.min(map - 1, Math.round(lu + tapX * 1.4))), mv = Math.max(0, Math.min(map - 1, Math.round(lv + tapY * 1.4)));
        if (ld >= lightDepth[mv * map + mu]!) seen++;
      }
      light[at] = Math.round(seen / 9 * 255);

      // Ambient occlusion: nearby surface in front of this one darkens the crease.
      const nx = normal[at * 3]! / 127, ny = normal[at * 3 + 1]! / 127, nz = normal[at * 3 + 2]! / 127;
      let occluded = 0;
      const turn = hash(px, py, 1) * 6.2832, tc = Math.cos(turn), ts = Math.sin(turn);
      for (const [tapX, tapY] of AO_TAPS) {
        const ax = Math.round(px + (tapX * tc - tapY * ts) * aoRadius), ay = Math.round(py + (tapX * ts + tapY * tc) * aoRadius);
        if (ax < 0 || ay < 0 || ax >= width || ay >= width) continue;
        const other = ay * width + ax;
        if (!owner[other]) continue;
        const vx = (ax - px) / k, vy = (py - ay) / k, vz = depth[other]! - zv;
        const distance = Math.hypot(vx, vy, vz);
        if (distance < 1e-5 || distance > aoReach) continue;
        occluded += Math.max(0, (vx * nx + vy * ny + vz * nz) / distance - 0.18) * (1 - distance / aoReach);
      }
      open[at] = Math.round((1 - Math.min(0.7, occluded / AO_TAPS.length * 2.4)) * 255);
    }
  }
  return trace;
}

/** The colours of a traced figure: one coat per part, in the order the parts were traced. */
export function shadeFigure(trace: FigureTrace, coats: readonly FigureCoat[]): FigureImage {
  const { size, samples, depth, normal, owner, light, open, box, foot } = trace;
  const { k, ox, oy, yaw, pitch } = trace.frame;
  const cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch);
  const width = size * samples;
  const data = new Uint8ClampedArray(size * size * 4);
  const skin = new Float32Array(3);
  const boxX = Math.max(box.max[0] - box.min[0], 1e-4), boxY = Math.max(box.max[1] - box.min[1], 1e-4), boxZ = Math.max(box.max[2] - box.min[2], 1e-4);
  for (let oyPixel = 0; oyPixel < size; oyPixel++) {
    for (let oxPixel = 0; oxPixel < size; oxPixel++) {
      let sumR = 0, sumG = 0, sumB = 0, hits = 0;
      for (let subY = 0; subY < samples; subY++) {
        for (let subX = 0; subX < samples; subX++) {
          const px = oxPixel * samples + subX, py = oyPixel * samples + subY, at = py * width + px;
          const coat = coats[owner[at]! - 1];
          if (!coat) continue;
          let r: number, g: number, b: number;
          if (coat.finish === "ink") { r = coat.color[0]; g = coat.color[1]; b = coat.color[2]; }
          else if (coat.finish === "glow") { r = coat.color[0] * 1.7; g = coat.color[1] * 1.7; b = coat.color[2] * 1.7; }
          else {
            const nx = normal[at * 3]! / 127, ny = normal[at * 3 + 1]! / 127, nz = normal[at * 3 + 2]! / 127;
            const shadow = light[at]! / 255, ao = open[at]! / 255;
            let cr = coat.color[0], cg = coat.color[1], cb = coat.color[2];
            let er = 0, eg = 0, eb = 0;
            const paint = coat.paint;
            if (paint) {
              // Back from the sample to the body's own space, where the design is laid out.
              const xv = (px + 0.5 - ox) / k, yv = (oy - py - 0.5) / k, zv = depth[at]!;
              const z1 = -yv * sp + zv * cp, my = yv * cp + zv * sp;
              const mx = xv * cy - z1 * sy, mz = xv * sy + z1 * cy;
              const bx = (mx - box.min[0]) / boxX - 0.5, by = (my - box.min[1]) / boxY - 0.5, bz = (mz - box.min[2]) / boxZ - 0.5;
              const rad = paint.angle * Math.PI / 180;
              const along = paint.radial ? Math.hypot(bx + 0.12, by - 0.16, bz - 0.3) * 1.25 : bx * Math.sin(rad) + by * Math.cos(rad) + 0.5;
              if (paint.effect === 3) ring(paint.colors, along * 0.9, skin); else ramp(paint.colors, along, skin);
              cr = skin[0]!; cg = skin[1]!; cb = skin[2]!;
              if (paint.effect === 1) { const s = specks(bx, by, bz, 7, 0.3) * 2.2; er = s; eg = s; eb = s; }
              if (paint.effect === 4) { er = paint.highlight[0] * 0.3; eg = paint.highlight[1] * 0.3; eb = paint.highlight[2] * 0.3; }
              if (paint.effect === 5) { const s = specks(bx, by, bz, 5, 0.18) * 2.2; er = paint.highlight[0] * s; eg = paint.highlight[1] * s; eb = paint.highlight[2] * s; }
            }
            const key = Math.max(0, Math.min(1, (nx * KEY[0] + ny * KEY[1] + nz * KEY[2] + 0.3) / 1.3)) * shadow;
            const sky = 0.5 + 0.5 * ny;
            const fill = Math.max(0, (nx * FILL[0] + ny * FILL[1] + nz * FILL[2] + 0.5) / 1.5);
            const lr = (GROUND[0] + (SKY[0] - GROUND[0]) * sky + FILL_COLOR[0] * fill) * ao + KEY_COLOR[0] * key;
            const lg = (GROUND[1] + (SKY[1] - GROUND[1]) * sky + FILL_COLOR[1] * fill) * ao + KEY_COLOR[1] * key;
            const lb = (GROUND[2] + (SKY[2] - GROUND[2]) * sky + FILL_COLOR[2] * fill) * ao + KEY_COLOR[2] * key;
            // A soft sheen: wide on a rough surface, tight on a glossy one.
            const rough = Math.max(0.2, Math.min(1, coat.roughness));
            const gloss = Math.max(0, nx * HALF[0] + ny * HALF[1] + nz * HALF[2]) ** (2 / (rough * rough * rough * rough) + 4);
            const sheen = gloss * Math.min(0.14, (1 - rough) * 0.4) * shadow;
            // A back light catches the far edge, so a dark body never sinks into a dark page.
            const edge = (1 - Math.min(1, nz)) ** 3 * Math.max(0, (nx * RIM[0] + ny * RIM[1] + nz * RIM[2]) * 0.5 + 0.5) * ao;
            r = cr * lr + er + sheen + (cr * 0.5 + 0.13) * edge * 0.9;
            g = cg * lg + eg + sheen + (cg * 0.5 + 0.13) * edge * 0.9;
            b = cb * lb + eb + sheen + (cb * 0.5 + 0.14) * edge * 0.9;
          }
          sumR += shoulder(r); sumG += shoulder(g); sumB += shoulder(b); hits++;
        }
      }
      const cover = hits / (samples * samples);
      let ground = 0;
      if (foot && cover < 1) {
        // Where this pixel's view ray meets the ground (model y = 0).
        const xv = ((oxPixel + 0.5) * samples - ox) / k, z1 = -((oy - (oyPixel + 0.5) * samples) / k) / sp;
        const qx = (xv * cy - z1 * sy - foot.x) / foot.rx, qz = (xv * sy + z1 * cy - foot.z) / foot.rz;
        ground = SHADOW_ALPHA * smooth(SHADOW_REACH, 0.3, Math.hypot(qx, qz)) * (1 - cover);
      }
      const alpha = cover + ground;
      if (alpha <= 0) continue;
      const out = (oyPixel * size + oxPixel) * 4;
      // The samples carry the figure's light; the shadow under it adds only darkness.
      const weight = 1 / (samples * samples * alpha);
      data[out] = TO_SRGB[Math.round(Math.max(0, Math.min(1, sumR * weight)) * 4096)]!;
      data[out + 1] = TO_SRGB[Math.round(Math.max(0, Math.min(1, sumG * weight)) * 4096)]!;
      data[out + 2] = TO_SRGB[Math.round(Math.max(0, Math.min(1, sumB * weight)) * 4096)]!;
      data[out + 3] = Math.round(alpha * 255);
    }
  }
  return { size, data, frame: { k: k / samples, ox: ox / samples, oy: oy / samples, yaw, pitch } };
}

/**
 * How much of each pixel shows the chosen parts, 0 to 255: the outline a
 * moving effect is cut to (a shine that sweeps the body must not cross the
 * hat). `chosen` holds one flag per part, in the order the parts were traced.
 */
export function figureCover(trace: FigureTrace, chosen: readonly boolean[]): Uint8ClampedArray<ArrayBuffer> {
  const { size, samples, owner } = trace;
  const width = size * samples;
  const cover = new Uint8ClampedArray(size * size);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      let hits = 0;
      for (let subY = 0; subY < samples; subY++) for (let subX = 0; subX < samples; subX++) {
        if (chosen[owner[(y * samples + subY) * width + x * samples + subX]! - 1]) hits++;
      }
      cover[y * size + x] = Math.round(hits * 255 / (samples * samples));
    }
  }
  return cover;
}

/**
 * Renders the parts into a square image `size` pixels wide. The figure is
 * fitted into the square whatever it wears, so a tall hat makes the body a
 * little smaller instead of leaving the picture.
 */
export function renderFigure(parts: readonly FigurePart[], size: number, yaw?: number, pitch?: number): FigureImage {
  return shadeFigure(traceFigure(parts, size, yaw, pitch), parts);
}
