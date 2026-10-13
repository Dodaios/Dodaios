/**
 * Puts an agent's shape together for the CPU renderer (figureRender.ts):
 * the body, its eyes and whatever it wears, from the same meshes and the
 * same catalog the map companion uses (AgentFollower.tsx), so a profile
 * face and the figure on the map always show the same look.
 */
import { ACCESSORY_CATALOG, resolveFill, slotDepthM, wornAccessories, type AccessoryChoice } from "./accessories";
import type { SymbolShape } from "./appearance";
import type { FigureMesh, LinearRgb } from "./figureGlb";
import { projectFigure, type FigureFrame, type FigurePaint, type FigurePart } from "./figureRender";

/** Everything that decides what a figure looks like; plain data, so it can cross to a worker. */
export interface FigureLook {
  shape: SymbolShape;
  color: string;
  eyes: "dots" | "lines";
  accessories?: AccessoryChoice;
  /** A colour design, already resolved: its effect as an index in SKIN_EFFECTS. */
  skin?: { colors: string[]; radial: boolean; angle: number; effect: number; highlight: string };
  /** Leaves the eyes out, for a face that draws moving eyes on top. */
  blind?: boolean;
}

const INK: LinearRgb = [0.0052, 0.0052, 0.007];
/** Indices in SKIN_EFFECTS of the two effects that move across the body. */
export const EFFECT_SHIMMER = 2, EFFECT_FLOW = 3;

/** True when a moving layer is cut to the body's outline, so the picture needs its cover. */
export function bodyEffectMoves(look: FigureLook): boolean {
  return look.skin?.effect === EFFECT_SHIMMER || look.skin?.effect === EFFECT_FLOW;
}

/** A plume of smoke over the picture: where it rises, pixels, and how large one symbol unit is there. */
export interface FigureSmoke { x: number; y: number; scale: number; size: number; fill: string }

/** A `#rrggbb` colour in linear light. */
export function linearRgb(hex: string): LinearRgb {
  const value = parseInt(hex.slice(1), 16);
  const channel = (shift: number) => {
    const c = ((value >> shift) & 255) / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return [channel(16), channel(8), channel(0)];
}

/**
 * An item worn on the face wins against the face within this depth, metres.
 * Glasses are wrapped onto each body, but an eye or a ridge of the body can
 * still reach through a lens; the flat symbol paints them over the eyes too.
 */
const FACE_LIFT_M = 0.08;

/** True when the look needs the accessory meshes as well as the bodies. */
export function wearsAccessories(look: FigureLook): boolean {
  return wornAccessories(look.accessories).length > 0;
}

/**
 * The parts of one figure. `bodies` are the meshes of companions.glb by
 * node name, `worn` those of accessories.glb (only read when something is
 * worn). An item the files do not know is skipped, like on the map.
 */
export function figureParts(look: FigureLook, bodies: ReadonlyMap<string, FigureMesh[]>, worn?: ReadonlyMap<string, FigureMesh[]>): FigurePart[] {
  const parts: FigurePart[] = [];
  const color = linearRgb(look.color);
  const paint: FigurePaint | undefined = look.skin && {
    colors: look.skin.colors.map(linearRgb), radial: look.skin.radial, angle: look.skin.angle,
    effect: look.skin.effect, highlight: linearRgb(look.skin.highlight),
  };
  // Flowing colours are laid over the picture as a moving layer (ShapeFigure), which
  // multiplies a white body: the picture carries only its light and shade.
  const flowing = paint?.effect === EFFECT_FLOW;
  for (const mesh of bodies.get(`${look.shape}.Body`) ?? []) {
    // A soft vinyl sheen lets the light show the volume; a shimmering design is glossier.
    parts.push({
      mesh, color: flowing ? [1, 1, 1] : color, finish: "matte", roughness: paint?.effect === EFFECT_SHIMMER ? 0.38 : 0.62,
      paint: flowing ? undefined : paint, body: true,
    });
  }
  const kind = look.eyes === "dots" ? "Dots" : "Lines";
  const eyes = [0, 1].flatMap(side => bodies.get(`${look.shape}.${kind}.${side}`) ?? []);
  if (!look.blind) for (const mesh of eyes) parts.push({ mesh, color: INK, finish: "ink", roughness: 1 });
  if (!worn) return parts;

  const meta = ACCESSORY_CATALOG.shapes[look.shape];
  const unit = 1 / (meta.bottom - meta.top);
  const add = (meshes: FigureMesh[] | undefined, lift: number, offset?: readonly [number, number, number], scale?: number) => {
    for (const mesh of meshes ?? []) {
      // A material named `acc:<token>` takes a tint of the agent's own colour.
      const token = mesh.material.name.split(":")[1] ?? "";
      parts.push({
        mesh, offset, scale, lift,
        color: token && !token.startsWith("#") ? linearRgb(resolveFill(token, look.color)) : mesh.material.color,
        finish: mesh.material.glow ? "glow" : "matte", roughness: mesh.material.roughness,
      });
    }
  };
  for (const item of wornAccessories(look.accessories)) {
    // Items worn on the body come pre-fitted to each silhouette's curved surface.
    const fitted = worn.get(`acc_${item.id}__${look.shape}__fit`);
    const lift = item.slot === "face" ? FACE_LIFT_M : 0;
    if (fitted) add(fitted, lift);
    else {
      const [x, y, k] = meta.anchors[item.slot];
      add(worn.get(`acc_${item.id}`), lift, [(x - 20) * unit, (meta.bottom - y) * unit, slotDepthM(look.shape, item.slot)], k * (item.scale ?? 1) * unit);
    }
    // Clothing is authored per silhouette, already in the body's frame.
    if (item.regions) add(worn.get(`acc_${item.id}__${look.shape}`), lift);
  }
  return parts;
}

/**
 * Where the eyes lie, as an SVG matrix from the flat symbol's units (40 wide,
 * eyes at the shape's `eyeY`) to the picture's pixels. A face that draws
 * moving eyes on top of a figure places them with it.
 */
export function figureFaceMatrix(look: FigureLook, bodies: ReadonlyMap<string, FigureMesh[]>, frame: FigureFrame): [number, number, number, number, number, number] {
  const meta = ACCESSORY_CATALOG.shapes[look.shape];
  const unit = 1 / (meta.bottom - meta.top);
  let depth = -Infinity;
  for (const side of [0, 1]) for (const mesh of bodies.get(`${look.shape}.${look.eyes === "dots" ? "Dots" : "Lines"}.${side}`) ?? []) {
    for (let i = 2; i < mesh.positions.length; i += 3) if (mesh.positions[i]! > depth) depth = mesh.positions[i]!;
  }
  if (!Number.isFinite(depth)) depth = slotDepthM(look.shape, "face");
  const at = (x: number, y: number) => projectFigure(frame, (x - 20) * unit, (meta.bottom - y) * unit, depth);
  const origin = at(0, 0), right = at(1, 0), down = at(0, 1);
  return [right[0] - origin[0], right[1] - origin[1], down[0] - origin[0], down[1] - origin[1], origin[0], origin[1]];
}

/**
 * Where worn items smoke (a cigar), placed like the map companion places its
 * plume: the picture shows the item, the face draws the moving puffs on top.
 */
export function figureSmoke(look: FigureLook, frame: FigureFrame): FigureSmoke[] {
  const meta = ACCESSORY_CATALOG.shapes[look.shape];
  const unit = 1 / (meta.bottom - meta.top);
  const plumes: FigureSmoke[] = [];
  for (const item of wornAccessories(look.accessories)) {
    const [x, y, k] = meta.anchors[item.slot];
    const size = k * (item.scale ?? 1) * unit;
    const depth = slotDepthM(look.shape, item.slot);
    for (const part of item.parts) {
      if (part.t !== "smoke") continue;
      const [px, py] = projectFigure(frame, (x - 20) * unit + part.c[0] * size, (meta.bottom - y) * unit - part.c[1] * size, depth + part.c[2] * size);
      plumes.push({ x: px, y: py, scale: frame.k * size, size: part.size, fill: part.fill });
    }
  }
  return plumes;
}

/** Names what a figure is made of, whatever its colours: equal keys trace alike. */
export function figureTraceKey(look: FigureLook, pixels: number): string {
  return `${look.shape}|${look.blind ? "blind" : look.eyes}|${wornAccessories(look.accessories).map(item => item.id).join(",")}|${pixels}`;
}

/** One line that names a look and a size: equal keys draw equal pictures. */
export function figureKey(look: FigureLook, pixels: number): string {
  const worn = wornAccessories(look.accessories).map(item => item.id).join(",");
  const skin = look.skin ? `${look.skin.colors.join("")}${look.skin.radial ? "r" : "l"}${look.skin.angle}e${look.skin.effect}` : "";
  return `${look.shape}|${look.color.toLowerCase()}|${look.blind ? "blind" : look.eyes}|${worn}|${skin}|${pixels}`;
}
