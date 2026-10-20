/**
 * Figures as one skinned mesh each (every part rigidly bound to its bone),
 * plus a face display on the head. `CrewFigure` is an imperative object the
 * crew system poses every frame; React only mounts it.
 *
 * Two bodies share the skeleton: the android crew (ceramic shell, graphite
 * joints, shoulder caps in the division's colour, rank pips at the collar)
 * and the captain (a charcoal flight suit with gold shoulders, a helmet with
 * a gold visor and a pack).
 */
import {
  Bone, BoxGeometry, BufferAttribute, BufferGeometry, Color, CylinderGeometry, Group, Matrix4, Mesh, MeshBasicMaterial,
  MeshStandardMaterial, Skeleton, SkinnedMesh, SphereGeometry, Uint16BufferAttribute, Float32BufferAttribute, Euler, Quaternion, Vector3,
  type Material,
} from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import { BONES, blendPose, OFFSET, PARENT, pose, restPositions, type BoneName, type PoseFrame, type PoseInput } from "./rig";

type V3 = [number, number, number];

interface Part { bone: BoneName; geo: BufferGeometry; color: string }

const REST = restPositions();
const tmp = new Color();

function part(bone: BoneName, geo: BufferGeometry, color: string, at: V3 = [0, 0, 0], scale?: V3, rot?: V3): Part {
  const m = new Matrix4();
  const q = new Quaternion().setFromEuler(new Euler(...(rot ?? [0, 0, 0])));
  const p = REST[bone];
  m.compose(new Vector3(p[0] + at[0], p[1] + at[1], p[2] + at[2]), q, new Vector3(...(scale ?? [1, 1, 1])));
  const g = geo.index ? geo.toNonIndexed() : geo;
  if (g !== geo) geo.dispose();
  g.applyMatrix4(m);
  return { bone, geo: g, color };
}

/** A capsule-ish limb segment from y=top down to y=bottom (bone-local), radius r0 at the top and r1 at the bottom. */
function limb(bone: BoneName, top: number, bottom: number, r0: number, r1: number, color: string): Part {
  const h = top - bottom;
  const g = new CylinderGeometry(r0, r1, h, 12, 1);
  return part(bone, g, color, [0, (top + bottom) / 2, 0]);
}

function ball(bone: BoneName, r: number, color: string, at: V3 = [0, 0, 0], scale?: V3, seg = 12): Part {
  return part(bone, new SphereGeometry(r, seg, Math.max(6, seg * 0.66)), color, at, scale);
}

function block(bone: BoneName, w: number, h: number, d: number, color: string, at: V3 = [0, 0, 0], rot?: V3): Part {
  return part(bone, new BoxGeometry(w, h, d), color, at, undefined, rot);
}

export interface AndroidLook {
  /** Shoulder caps and wrist bands: the division's colour. */
  accent: string;
  /** Rank pips at the collar (0–4) and whether they are gold (officers) or silver. */
  pips: number;
  gold: boolean;
  /** A small gold bar for a division lead. */
  lead: boolean;
  /** Decorations earned (the level system's agent `decoration` rewards), worn as ribbon bars over the left breast. */
  ribbons?: number;
}

/** The ribbons' colours, in the order they are earned. */
const RIBBON_COLOURS = ["#3c7fd0", "#c0392b", "#e1b04f", "#2e8b57"] as const;

const SHELL = "#e9e8e4";
const JOINT = "#2b2f36";
const DARK = "#1c1f24";

export function androidParts(look: AndroidLook): Part[] {
  const a = look.accent;
  const parts: Part[] = [
    // Hips and abdomen.
    block("hips", 0.29, 0.13, 0.17, JOINT, [0, -0.05, 0]),
    ball("hips", 0.07, SHELL, [0, -0.06, 0.06], [1.6, 0.8, 0.6]),
    limb("chest", 0.16, 0.0, 0.1, 0.11, JOINT),
    // Torso shell, chest plate, collar and the back's spine.
    ball("chest", 1, SHELL, [0, 0.29, 0], [0.19, 0.23, 0.125], 18),
    ball("chest", 1, "#d9d7d2", [0, 0.31, 0.035], [0.15, 0.15, 0.1], 14),
    block("chest", 0.05, 0.3, 0.05, JOINT, [0, 0.26, -0.11]),
    part("chest", new CylinderGeometry(0.075, 0.09, 0.05, 16), JOINT, [0, 0.43, 0]),
    // Shoulder caps in the division colour.
    ball("chest", 0.078, a, [0.2, 0.37, -0.01], [1, 0.85, 1]),
    ball("chest", 0.078, a, [-0.2, 0.37, -0.01], [1, 0.85, 1]),
    // Neck and head.
    limb("neck", 0.09, 0.0, 0.034, 0.042, JOINT),
    ball("head", 1, SHELL, [0, 0.11, -0.005], [0.112, 0.132, 0.124], 20),
    part("head", new CylinderGeometry(0.03, 0.03, 0.02, 12), JOINT, [0.112, 0.1, -0.01], undefined, [0, 0, Math.PI / 2]),
    part("head", new CylinderGeometry(0.03, 0.03, 0.02, 12), JOINT, [-0.112, 0.1, -0.01], undefined, [0, 0, Math.PI / 2]),
    // Arms.
    ball("armL", 0.055, JOINT), ball("armR", 0.055, JOINT),
    limb("armL", -0.02, -0.27, 0.047, 0.04, SHELL), limb("armR", -0.02, -0.27, 0.047, 0.04, SHELL),
    ball("forearmL", 0.043, JOINT), ball("forearmR", 0.043, JOINT),
    limb("forearmL", -0.02, -0.24, 0.04, 0.033, SHELL), limb("forearmR", -0.02, -0.24, 0.04, 0.033, SHELL),
    limb("forearmL", -0.19, -0.23, 0.037, 0.037, a), limb("forearmR", -0.19, -0.23, 0.037, 0.037, a),
    block("handL", 0.035, 0.1, 0.07, JOINT, [0, -0.05, 0.005]), block("handR", 0.035, 0.1, 0.07, JOINT, [0, -0.05, 0.005]),
    // Legs.
    ball("thighL", 0.062, JOINT), ball("thighR", 0.062, JOINT),
    limb("thighL", -0.02, -0.42, 0.066, 0.052, SHELL), limb("thighR", -0.02, -0.42, 0.066, 0.052, SHELL),
    ball("shinL", 0.05, JOINT), ball("shinR", 0.05, JOINT),
    limb("shinL", -0.02, -0.41, 0.05, 0.038, SHELL), limb("shinR", -0.02, -0.41, 0.05, 0.038, SHELL),
    block("footL", 0.09, 0.06, 0.21, DARK, [0, -0.02, 0.045]), block("footR", 0.09, 0.06, 0.21, DARK, [0, -0.02, 0.045]),
  ];
  // Rank pips on the right of the collar.
  const pip = look.gold ? "#e1b04f" : "#c9cdd3";
  for (let k = 0; k < Math.min(4, look.pips); k += 1) {
    parts.push(ball("chest", 0.013, pip, [-0.05 - k * 0.032, 0.41, 0.095], [1, 1, 0.5], 8));
  }
  if (look.lead) parts.push(block("chest", 0.09, 0.018, 0.01, "#e1b04f", [0.06, 0.39, 0.1]));
  // Ribbon bars on the figure's left breast, two to a row.
  for (let k = 0; k < Math.min(4, look.ribbons ?? 0); k += 1) {
    parts.push(block("chest", 0.034, 0.014, 0.01, RIBBON_COLOURS[k], [0.045 + (k % 2) * 0.037, 0.33 - Math.floor(k / 2) * 0.018, 0.118]));
  }
  return parts;
}

/** `cut` is a suit unlocked by rank: null (the duty suit), field_armor, command_coat, dress_whites, admiral_coat. */
export interface CaptainLook { suit: string; trim: string; visor: string; pips: number; cut?: string | null }

export function captainParts(look: CaptainLook): Part[] {
  const cut = look.cut ?? null;
  // Dress whites recolour the suit; the trim stays the captain's choice.
  const s = cut === "dress_whites" ? "#e6e6e3" : look.suit, t = look.trim;
  const parts: Part[] = [
    block("hips", 0.32, 0.15, 0.2, s, [0, -0.05, 0]),
    block("hips", 0.33, 0.04, 0.21, t, [0, 0.01, 0]),
    limb("chest", 0.16, 0.0, 0.12, 0.125, s),
    ball("chest", 1, s, [0, 0.29, 0], [0.205, 0.24, 0.14], 18),
    // Chest plate with a gold rule, and the pack on the back.
    ball("chest", 1, "#3a4252", [0, 0.31, 0.045], [0.16, 0.16, 0.11], 14),
    block("chest", 0.2, 0.012, 0.01, t, [0, 0.25, 0.15]),
    block("chest", 0.25, 0.3, 0.1, "#3d4554", [0, 0.28, -0.15]),
    block("chest", 0.2, 0.02, 0.02, "#8fd6ff", [0, 0.2, -0.2]),
    ball("chest", 0.088, t, [0.21, 0.37, -0.01], [1, 0.8, 1]),
    ball("chest", 0.088, t, [-0.21, 0.37, -0.01], [1, 0.8, 1]),
    part("chest", new CylinderGeometry(0.09, 0.1, 0.06, 16), "#252a33", [0, 0.43, 0]),
    limb("neck", 0.09, 0.0, 0.045, 0.05, "#252a33"),
    // Helmet shell (the visor is its own mesh).
    ball("head", 1, "#e8e9ec", [0, 0.11, -0.01], [0.135, 0.15, 0.142], 20),
    part("head", new CylinderGeometry(0.035, 0.035, 0.03, 12), t, [0.135, 0.1, -0.02], undefined, [0, 0, Math.PI / 2]),
    part("head", new CylinderGeometry(0.035, 0.035, 0.03, 12), t, [-0.135, 0.1, -0.02], undefined, [0, 0, Math.PI / 2]),
    ball("armL", 0.062, s), ball("armR", 0.062, s),
    limb("armL", -0.02, -0.27, 0.055, 0.047, s), limb("armR", -0.02, -0.27, 0.055, 0.047, s),
    ball("forearmL", 0.048, "#252a33"), ball("forearmR", 0.048, "#252a33"),
    limb("forearmL", -0.02, -0.24, 0.047, 0.04, s), limb("forearmR", -0.02, -0.24, 0.047, 0.04, s),
    limb("forearmL", -0.17, -0.24, 0.05, 0.05, "#e8e9ec"), limb("forearmR", -0.17, -0.24, 0.05, 0.05, "#e8e9ec"),
    block("handL", 0.04, 0.1, 0.075, "#252a33", [0, -0.05, 0.005]), block("handR", 0.04, 0.1, 0.075, "#252a33", [0, -0.05, 0.005]),
    ball("thighL", 0.07, s), ball("thighR", 0.07, s),
    limb("thighL", -0.02, -0.42, 0.072, 0.058, s), limb("thighR", -0.02, -0.42, 0.072, 0.058, s),
    ball("shinL", 0.056, "#252a33"), ball("shinR", 0.056, "#252a33"),
    limb("shinL", -0.02, -0.33, 0.056, 0.05, s), limb("shinR", -0.02, -0.33, 0.056, 0.05, s),
    limb("shinL", -0.28, -0.42, 0.06, 0.058, "#e8e9ec"), limb("shinR", -0.28, -0.42, 0.06, 0.058, "#e8e9ec"),
    block("footL", 0.1, 0.07, 0.23, "#1b1e24", [0, -0.02, 0.045]), block("footR", 0.1, 0.07, 0.23, "#1b1e24", [0, -0.02, 0.045]),
  ];
  for (let k = 0; k < Math.min(4, look.pips); k += 1) parts.push(ball("chest", 0.014, "#f0c060", [-0.06 - k * 0.034, 0.41, 0.11], [1, 1, 0.5], 8));
  if (cut === "field_armor") {
    // Armour plates over the suit: chest, shoulders and knees.
    parts.push(ball("chest", 1, "#4a5363", [0, 0.3, 0.06], [0.19, 0.17, 0.11], 14));
    parts.push(ball("chest", 0.105, "#4a5363", [0.23, 0.38, 0], [1, 0.7, 1.1]), ball("chest", 0.105, "#4a5363", [-0.23, 0.38, 0], [1, 0.7, 1.1]));
    parts.push(ball("shinL", 0.07, "#4a5363", [0, -0.02, 0.03], [1, 1, 0.7]), ball("shinR", 0.07, "#4a5363", [0, -0.02, 0.03], [1, 1, 0.7]));
  } else if (cut === "command_coat" || cut === "admiral_coat") {
    // A coat skirt from the waist; the admiral's reaches the knees and carries gold epaulettes.
    const long = cut === "admiral_coat";
    const coat = cut === "admiral_coat" ? "#1a2030" : s;
    const g = new CylinderGeometry(0.17, long ? 0.25 : 0.21, long ? 0.62 : 0.36, 18, 1, true);
    parts.push(part("hips", g, coat, [0, long ? -0.29 : -0.16, -0.005]));
    parts.push(block("chest", 0.012, 0.42, 0.01, t, [0.05, 0.22, 0.14]));
    if (long) parts.push(block("chest", 0.13, 0.025, 0.11, t, [0.22, 0.44, -0.01]), block("chest", 0.13, 0.025, 0.11, t, [-0.22, 0.44, -0.01]));
  } else if (cut === "dress_whites") {
    parts.push(block("chest", 0.22, 0.03, 0.02, t, [0, 0.4, 0.13]), block("hips", 0.33, 0.05, 0.21, t, [0, 0.0, 0]));
  }
  return parts;
}

/** Merge the parts into one geometry bound rigidly to its bones. */
export function skinnedGeometry(parts: Part[]): BufferGeometry {
  const geos = parts.map(({ bone, geo, color }) => {
    for (const name of Object.keys(geo.attributes)) if (name !== "position" && name !== "normal") geo.deleteAttribute(name);
    const n = geo.attributes.position.count;
    const idx = BONES.indexOf(bone);
    const colors = new Float32Array(n * 3);
    tmp.set(color).convertSRGBToLinear();
    for (let i = 0; i < n; i += 1) { colors[i * 3] = tmp.r; colors[i * 3 + 1] = tmp.g; colors[i * 3 + 2] = tmp.b; }
    geo.setAttribute("color", new BufferAttribute(colors, 3));
    const si = new Uint16Array(n * 4), sw = new Float32Array(n * 4);
    for (let i = 0; i < n; i += 1) { si[i * 4] = idx; sw[i * 4] = 1; }
    geo.setAttribute("skinIndex", new Uint16BufferAttribute(si, 4));
    geo.setAttribute("skinWeight", new Float32BufferAttribute(sw, 4));
    return geo;
  });
  const merged = mergeGeometries(geos, false);
  for (const g of geos) g.dispose();
  if (!merged) throw new Error("figure geometry failed to merge");
  merged.computeBoundingSphere();
  if (merged.boundingSphere) merged.boundingSphere.radius = 1.4;
  return merged;
}

let bodyMaterial: MeshStandardMaterial | null = null;
export function figureMaterial(): MeshStandardMaterial {
  if (!bodyMaterial) bodyMaterial = new MeshStandardMaterial({ vertexColors: true, roughness: 0.42, metalness: 0.08, envMapIntensity: 0.9 });
  return bodyMaterial;
}

const visorMaterials = new Map<string, MeshStandardMaterial>();
function visorMat(colour: string): MeshStandardMaterial {
  let m = visorMaterials.get(colour);
  if (!m) {
    m = new MeshStandardMaterial({ color: colour, roughness: 0.12, metalness: 1, envMapIntensity: 1.8, emissive: new Color(colour).multiplyScalar(0.12) });
    visorMaterials.set(colour, m);
  }
  return m;
}

/** The face display: the front of the head, uv-mapped to one atlas cell. */
export function faceGeometry(uv: [number, number, number, number], captain = false): BufferGeometry {
  const r = captain ? 1.035 : 1.03;
  const g = new SphereGeometry(r, 18, 12, Math.PI / 2 - 0.95, 1.9, Math.PI / 2 - 0.62, 1.12);
  // phi runs round y from +x; the front (+z) is at phi = pi/2. Map the patch onto the cell.
  const uvs = g.attributes.uv as BufferAttribute;
  for (let i = 0; i < uvs.count; i += 1) {
    const u = uvs.getX(i), v = uvs.getY(i);
    // Sphere uvs over the patch run 0..1 in u (phi, from the figure's right = the viewer's left) and v (top = 1).
    uvs.setXY(i, uv[0] + u * (uv[2] - uv[0]), uv[1] + v * (uv[3] - uv[1]));
  }
  const s = captain ? [0.135, 0.15, 0.142] : [0.112, 0.132, 0.124];
  g.applyMatrix4(new Matrix4().compose(new Vector3(0, 0.11 + (captain ? 0.0 : -0.005), captain ? -0.01 : -0.005), new Quaternion(), new Vector3(s[0], s[1], s[2])));
  return g;
}

export interface FigureOptions {
  kind: "android" | "captain";
  android?: AndroidLook;
  captain?: CaptainLook;
  /** Face material (the shared atlas) and this figure's cell. */
  face?: { material: Material; uv: [number, number, number, number] };
}

const BLEND_S = 0.32;

/**
 * One figure: a group at the figure's feet (position and yaw set by the
 * owner), its skinned body and its face. `apply(input, dt)` poses it,
 * blending over a third of a second whenever the activity changes.
 */
export class CrewFigure {
  readonly group = new Group();
  readonly bones: Record<BoneName, Bone>;
  private readonly body: SkinnedMesh;
  private readonly face: Mesh | null;
  private readonly root: Group;
  private from: PoseFrame | null = null;
  private current: PoseFrame | null = null;
  private activity: PoseInput["activity"] | null = null;
  private blend = 1;

  constructor(opts: FigureOptions) {
    const parts = opts.kind === "captain" ? captainParts(opts.captain ?? { suit: "#2c3340", trim: "#d9a441", visor: "#d6a440", pips: 0 })
      : androidParts(opts.android ?? { accent: "#5fd4ff", pips: 0, gold: false, lead: false });
    const geometry = skinnedGeometry(parts);
    const bones = {} as Record<BoneName, Bone>;
    for (const name of BONES) {
      const bone = new Bone();
      bone.name = name;
      const o = OFFSET[name];
      bone.position.set(o[0], o[1], o[2]);
      bones[name] = bone;
    }
    for (const name of BONES) {
      const parent = PARENT[name];
      if (parent) bones[parent].add(bones[name]);
    }
    this.bones = bones;
    this.body = new SkinnedMesh(geometry, figureMaterial());
    this.body.castShadow = true;
    this.body.frustumCulled = false;
    // Picking uses a simple hit volume; a skinned raycast is far too costly.
    this.body.raycast = () => undefined;
    this.root = new Group();
    this.root.add(bones.hips);
    this.root.add(this.body);
    this.group.add(this.root);
    // The skeleton takes its inverse bind matrices from the bones' world matrices: update them first.
    this.group.updateMatrixWorld(true);
    const skeleton = new Skeleton(BONES.map((n) => bones[n]));
    this.body.bind(skeleton);
    if (opts.face) {
      this.face = new Mesh(faceGeometry(opts.face.uv, opts.kind === "captain"), opts.face.material);
      this.face.frustumCulled = false;
      // Built in the head bone's own frame, so it turns with the head.
      bones.head.add(this.face);
    } else if (opts.kind === "captain") {
      this.face = new Mesh(faceGeometry([0, 0, 1, 1], true), visorMat(opts.captain?.visor ?? "#d6a440"));
      this.face.castShadow = false;
      bones.head.add(this.face);
    } else {
      this.face = null;
    }
    if (this.face) this.face.raycast = () => undefined;
  }

  /** Re-point the face at another cell (a new look). */
  setFaceUv(uv: [number, number, number, number]): void {
    if (!this.face) return;
    const old = this.face.geometry;
    this.face.geometry = faceGeometry(uv);
    old.dispose();
  }

  apply(input: PoseInput, dt: number): void {
    const next = pose(input);
    if (this.activity !== input.activity) {
      this.from = this.current ?? next;
      this.activity = input.activity;
      this.blend = 0;
    }
    this.blend = Math.min(1, this.blend + dt / BLEND_S);
    const k = this.blend * this.blend * (3 - 2 * this.blend);
    const frame = this.from && this.blend < 1 ? blendPose(this.from, next, k) : next;
    this.current = frame;
    const hips = this.bones.hips;
    hips.position.set(frame.root[0], frame.root[1], frame.root[2]);
    this.root.rotation.set(frame.rootRot[0], frame.rootRot[1], frame.rootRot[2]);
    for (const name of BONES) {
      const r = frame.bones[name];
      if (r) this.bones[name].rotation.set(r[0], r[1], r[2]);
      else this.bones[name].rotation.set(0, 0, 0);
    }
  }

  /** World position of the head (for name plates and bubbles). */
  headWorld(out: Vector3): Vector3 {
    return this.bones.head.getWorldPosition(out);
  }

  dispose(): void {
    this.body.geometry.dispose();
    this.body.skeleton.dispose();
    this.face?.geometry.dispose();
  }
}

/** The shared face material for an atlas texture. */
export function faceMaterial(map: MeshBasicMaterial["map"]): MeshBasicMaterial {
  return new MeshBasicMaterial({ map, toneMapped: false, color: new Color(1.35, 1.35, 1.35) });
}
