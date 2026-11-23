import { BoxGeometry, BufferAttribute, ExtrudeGeometry, type BufferGeometry } from "three";
import { SVGLoader } from "three/examples/jsm/loaders/SVGLoader.js";

import type { MascotSpec } from "./mascotSpecs";

/**
 * Turns a mark's file into the solid the simulation draws.
 *
 * The outline is extruded as the file states it, in the file's own units, and
 * only then brought to the figure's size: one transform for every part, so a
 * glyph stays where it sits on its tile.
 */

/** The side of every shipped mark's view box. */
const VIEW = 24;
/** How thick a figure is, in the file's units, and how far a relief stands out. */
const DEPTH = 5;
const RELIEF = 1.1;
const BEVEL = 0.22;
/** A figure's height in metres: the mark's full view box. */
export const MASCOT_HEIGHT_M = 1;

export interface MascotPart {
  geometry: BufferGeometry;
  /** The path's own fill colour as the file states it, or null (ink, gradient). */
  fill: string | null;
  /** A pane behind an eye opening: drawn dark, whatever the mark's paint. */
  eye: boolean;
}

export interface MascotSolid {
  parts: MascotPart[];
  /** The figure's width and thickness in metres; its height is `MASCOT_HEIGHT_M`. */
  widthM: number;
  depthM: number;
}

/** Lay the file over the solid: one flat projection, so the sides take the colour of the edge. */
function projectPicture(geometry: BufferGeometry): void {
  const position = geometry.getAttribute("position");
  const uv = new Float32Array(position.count * 2);
  for (let index = 0; index < position.count; index += 1) {
    uv[index * 2] = position.getX(index) / VIEW;
    uv[index * 2 + 1] = 1 - position.getY(index) / VIEW;
  }
  geometry.setAttribute("uv", new BufferAttribute(uv, 2));
}

function solidColour(fill: unknown): string | null {
  return typeof fill === "string" && /^#[0-9a-f]{3,8}$/i.test(fill) ? fill : null;
}

/** Build the solid for one mark. The caller keeps it: the result is not cached here. */
export function buildMascot(spec: MascotSpec): MascotSolid {
  const { paths } = new SVGLoader().parse(spec.svg);
  const parts: MascotPart[] = [];
  const relief = new Set(spec.relief ?? []);
  for (const index of [...spec.body, ...relief]) {
    const path = paths[index];
    if (!path) continue;
    const raised = relief.has(index);
    const depth = DEPTH + (raised ? 2 * RELIEF : 0);
    const geometry = new ExtrudeGeometry(SVGLoader.createShapes(path), {
      depth,
      bevelEnabled: true,
      bevelThickness: BEVEL,
      bevelSize: BEVEL * 0.8,
      // The bevel grows the outline; taking it back keeps the mark's own size.
      bevelOffset: -BEVEL * 0.8,
      bevelSegments: 2,
      curveSegments: 14,
    });
    geometry.translate(0, 0, -depth / 2);
    projectPicture(geometry);
    parts.push({ geometry, fill: solidColour((path.userData as { style?: { fill?: unknown } } | undefined)?.style?.fill), eye: false });
  }
  for (const eye of spec.eyes ?? []) {
    const geometry = new BoxGeometry(eye.width, eye.height, DEPTH * 0.55);
    geometry.translate(eye.x + eye.width / 2, eye.y + eye.height / 2, 0);
    parts.push({ geometry, fill: null, eye: true });
  }

  // The file's y runs down and its origin is a corner: turn it upright,
  // centre it and stand it on the floor.
  const scale = MASCOT_HEIGHT_M / VIEW;
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxZ = 0;
  for (const part of parts) {
    part.geometry.translate(-VIEW / 2, -VIEW / 2, 0);
    part.geometry.rotateX(Math.PI);
    part.geometry.scale(scale, scale, scale);
    part.geometry.computeBoundingBox();
    const box = part.geometry.boundingBox;
    if (!box) continue;
    minX = Math.min(minX, box.min.x);
    maxX = Math.max(maxX, box.max.x);
    minY = Math.min(minY, box.min.y);
    maxZ = Math.max(maxZ, box.max.z);
  }
  if (!Number.isFinite(minY)) return { parts: [], widthM: 0, depthM: 0 };
  for (const part of parts) {
    part.geometry.translate(-(minX + maxX) / 2, -minY, 0);
    part.geometry.computeVertexNormals();
    part.geometry.computeBoundingBox();
    part.geometry.computeBoundingSphere();
  }
  return { parts, widthM: maxX - minX, depthM: maxZ * 2 };
}

/** The figure of an agent without a mark of its own: a plain block. */
export function buildPlainMascot(): MascotSolid {
  const side = MASCOT_HEIGHT_M * 0.7;
  const geometry = new BoxGeometry(side, side, DEPTH * (MASCOT_HEIGHT_M / VIEW));
  geometry.translate(0, side / 2, 0);
  return { parts: [{ geometry, fill: null, eye: false }], widthM: side, depthM: DEPTH * (MASCOT_HEIGHT_M / VIEW) };
}
