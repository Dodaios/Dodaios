/**
 * The first-person arms cut from the commander's own body (docs/verse/realtime.md,
 * "First-person viewmodel"): the triangles of the character's skinned mesh
 * that hang on the arm bones (upper arm down to the fingertips), with their
 * painted atlas, their baked ambient occlusion and their real skin weights,
 * so elbows, wrists and knuckles bend the surface the way the body's do.
 *
 * The shared character skeleton has one bone for the four fingers and one for
 * the thumb. The cut re-rigs the hand from its own geometry: the finger
 * vertices are sorted into index, middle, ring and little finger by where
 * they sit across the hand, each finger's axis and length are measured, and
 * the finger bone's weight is shared out along three phalanges (and the
 * thumb's along three bones of its own), blended over a few millimetres at
 * each knuckle. The forearm gets a twist bone: the weight of the forearm runs
 * from its hinge at the elbow to its twist at the wrist, so turning the hand
 * over rolls the forearm as a radius does instead of wringing the elbow.
 *
 * Both arms come out as one indexed geometry whose bind space is the
 * character's model space (metres, Y up, facing +Z) and one bone list per
 * arm with its bind frames (`ArmRig`). The material colours (uniform, trim,
 * skin) are multiplied into the vertex colours over the baked occlusion, so
 * one material with the character's atlas draws everything: one draw call.
 *
 * Bone frames (bind and posed alike):
 * - upper arm and forearm hinge: origin at the joint, +Y along the bone, +Z
 *   toward the point of the elbow (backward at rest);
 * - forearm twist: origin at the elbow, +Y along the forearm, +Z toward the
 *   back of the hand;
 * - hand: origin at the wrist, +Z to the knuckles, +Y the back of the hand,
 *   +X = Y × Z (the thumb's side on the right hand, the little finger's on
 *   the left: the left hand is the right one mirrored);
 * - finger and thumb bones: origin at the joint, +Z along the finger, a
 *   positive turn about +X curls it toward the palm.
 */
import { BufferAttribute, BufferGeometry, Color, Matrix4, Vector3, type Material, type MeshStandardMaterial, type SkinnedMesh, type Texture } from "three";

export type Side = "right" | "left";

/** One arm's bones in bind space (model metres): where its joints are and how its bones are turned. */
export interface ArmRig {
  side: Side;
  /** Joint positions at rest. */
  shoulder: Vector3;
  elbow: Vector3;
  wrist: Vector3;
  /** Bone lengths: shoulder to elbow, elbow to wrist. */
  upper: number;
  fore: number;
  /** Bind frames (world = model space at rest) of the arm's bones, in `BONES` order. */
  bind: Matrix4[];
  /** Landmarks in the hand's bind frame: the knuckle line's middle on the back of the hand, the index finger's pad. */
  knuckles: Vector3;
  indexTip: Vector3;
  /** Each finger's tip (index .. little), in its end bone's bind frame. */
  tips: Vector3[];
  /** Where on the forearm's back the shield emitter sits: share of the forearm from the elbow, height over its axis. */
  emitterAt: number;
  emitterLift: number;
  /** The forearm's radius at the wrist (the cuff), metres. */
  wristRadius: number;
}

/** Bones per arm, in order: upper arm, forearm hinge, forearm twist, hand, four fingers × three, thumb × three. */
export const BONES = 19;
export const B_UPPER = 0;
export const B_FORE = 1;
export const B_TWIST = 2;
export const B_HAND = 3;
/** First bone of finger `f` (0 index .. 3 little); its phalanges follow. */
export const fingerBone = (f: number): number => 4 + f * 3;
export const B_THUMB = 16;

/** Material slots of the cut: their authored colours, unless the look repaints them. */
export type ArmSlot = "uniform" | "trim" | "skin" | "other";

export interface ArmsSource {
  geometry: BufferGeometry;
  right: ArmRig;
  left: ArmRig;
  /** The character's atlas (shared with the body: never disposed here). */
  map: Texture | null;
  normalMap: Texture | null;
  roughnessMap: Texture | null;
  normalScale: [number, number];
  /** Per vertex: the baked occlusion (linear) and the slot whose colour multiplies it. */
  occlusion: Float32Array;
  slots: Uint8Array;
  /** The authored colours of the slots (linear), before the look. */
  authored: Record<ArmSlot, Color>;
  /** The cut's triangles. */
  triangles: number;
}

/** The layout of the cut: phalanx joints as shares of a finger's length from its knuckle, and blend widths. */
export const CUT = {
  /** A triangle stays when every corner hangs this much or more on its arm's bones. */
  armWeight: 0.5,
  /** Finger joints (PIP, DIP) as shares of the finger from the knuckle (MCP) to its tip. */
  fingerJoints: [0.47, 0.75] as [number, number],
  /** Thumb joints (MCP, IP) as shares from the thumb bone's root to its tip. */
  thumbJoints: [0.42, 0.72] as [number, number],
  /** Half-width of the blend across a finger joint, as a share of the finger. */
  blend: 0.065,
  /** The forearm's twist weight ramps in over this span of the forearm (shares from the elbow). */
  twist: [0.2, 0.95] as [number, number],
  /**
   * The cuffs' trim band covers the sleeve's ragged end; its own edge toward the elbow is a sawtooth (unseen at the
   * deck camera's distance, plain a hand's breadth from the eye). It is lifted off the cloth along its normals,
   * metres, and the viewmodel paints it in the uniform's cloth so the sawtooth never shows as a change of tone.
   */
  trimLift: 0.0018,
  /** The shield emitter's seat: share of the forearm from the elbow. */
  emitterAt: 0.66,
};

const SLOT_CODES: ArmSlot[] = ["uniform", "trim", "skin", "other"];

function slotOf(name: string): ArmSlot {
  if (name === "M_Uniform" || name === "M_Undersuit" || name === "M_SovRobe") return "uniform";
  if (name === "M_Trim" || name === "M_SovTrim") return "trim";
  if (name === "M_Skin" || name === "M_Gloves") return "skin";
  return "other";
}

function smoothstep(a: number, b: number, v: number): number {
  const t = Math.min(1, Math.max(0, (v - a) / (b - a)));
  return t * t * (3 - 2 * t);
}

const SUFFIX: Record<Side, string> = { right: "_R", left: "_L" };
const ARM_BONES = ["UpperArm", "ForeArm", "Hand", "Fingers", "Thumb"] as const;

/** The bind frame with origin `o` and axes `x`, `y`, `z` (orthonormal). */
function frame(o: Vector3, x: Vector3, y: Vector3, z: Vector3): Matrix4 {
  return new Matrix4().makeBasis(x, y, z).setPosition(o);
}

/** A frame from its +Y axis and a hint for +Z (made perpendicular): X = Y × Z. */
function frameYZ(o: Vector3, y: Vector3, zHint: Vector3): Matrix4 {
  const Y = y.clone().normalize();
  const Z = zHint.clone().addScaledVector(Y, -zHint.dot(Y)).normalize();
  return frame(o, new Vector3().crossVectors(Y, Z), Y, Z);
}

/** A frame from its +Z axis and a hint for +Y (made perpendicular): X = Y × Z. */
function frameZY(o: Vector3, z: Vector3, yHint: Vector3): Matrix4 {
  const Z = z.clone().normalize();
  const Y = yHint.clone().addScaledVector(Z, -yHint.dot(Z)).normalize();
  return frame(o, new Vector3().crossVectors(Y, Z), Y, Z);
}

/** The principal direction of a point cloud (power iteration on its covariance). */
function principal(points: Vector3[], hint: Vector3): Vector3 {
  const c = new Vector3();
  for (const p of points) c.add(p);
  c.multiplyScalar(1 / Math.max(1, points.length));
  const m = [0, 0, 0, 0, 0, 0];
  for (const p of points) {
    const x = p.x - c.x, y = p.y - c.y, z = p.z - c.z;
    m[0] += x * x; m[1] += x * y; m[2] += x * z; m[3] += y * y; m[4] += y * z; m[5] += z * z;
  }
  const v = hint.clone().normalize();
  for (let i = 0; i < 32; i++) {
    const nx = m[0] * v.x + m[1] * v.y + m[2] * v.z;
    const ny = m[1] * v.x + m[3] * v.y + m[4] * v.z;
    const nz = m[2] * v.x + m[4] * v.y + m[5] * v.z;
    v.set(nx, ny, nz);
    const l = v.length();
    if (l < 1e-12) return hint.clone().normalize();
    v.multiplyScalar(1 / l);
  }
  return v.dot(hint) < 0 ? v.negate() : v;
}

/** 1-D k-means of `values` into `k` clusters (seeded at evenly spaced quantiles); the cluster centres, sorted descending. */
export function kMeans1D(values: number[], k: number): number[] {
  const sorted = [...values].sort((a, b) => a - b);
  if (!sorted.length) return [];
  const centres = Array.from({ length: k }, (_, i) => sorted[Math.min(sorted.length - 1, Math.floor(((i + 0.5) / k) * sorted.length))]);
  for (let iter = 0; iter < 40; iter++) {
    const sum = new Array(k).fill(0);
    const n = new Array(k).fill(0);
    for (const v of sorted) {
      let best = 0;
      for (let j = 1; j < k; j++) if (Math.abs(v - centres[j]) < Math.abs(v - centres[best])) best = j;
      sum[best] += v;
      n[best]++;
    }
    let moved = 0;
    for (let j = 0; j < k; j++) {
      if (!n[j]) continue;
      const c = sum[j] / n[j];
      moved = Math.max(moved, Math.abs(c - centres[j]));
      centres[j] = c;
    }
    if (moved < 1e-7) break;
  }
  return centres.sort((a, b) => b - a);
}

interface SourceVertex {
  p: Vector3;
  n: Vector3;
  uv: [number, number];
  ao: number;
  slot: number;
  /** Weights by source bone name. */
  w: Map<string, number>;
}

interface Finger { base: Vector3; dir: Vector3; length: number }

/**
 * Cut both arms out of a character's skinned meshes (the commander's body, in its bind pose). Throws when the body
 * lacks the arm bones or the cut comes out empty.
 */
export function cutArms(meshes: readonly SkinnedMesh[]): ArmsSource {
  const verts: SourceVertex[] = [];
  const tris: number[] = [];
  const sideOf: Side[] = [];
  let atlas: MeshStandardMaterial | null = null;
  const authored: Record<ArmSlot, Color> = { uniform: new Color(0.1, 0.1, 0.1), trim: new Color(0.08, 0.08, 0.08), skin: new Color(0.62, 0.38, 0.27), other: new Color(0.2, 0.2, 0.2) };
  const boneBind = new Map<string, Matrix4>();
  const normalM = new Matrix4();

  for (const mesh of meshes) {
    if (!mesh.isSkinnedMesh) continue;
    const material = (Array.isArray(mesh.material) ? mesh.material[0] : mesh.material) as Material;
    const std = material as MeshStandardMaterial;
    const slot = slotOf(material.name);
    const geo = mesh.geometry;
    const pos = geo.getAttribute("position");
    const nor = geo.getAttribute("normal");
    const uv = geo.getAttribute("uv");
    const col = geo.getAttribute("color");
    const si = geo.getAttribute("skinIndex");
    const sw = geo.getAttribute("skinWeight");
    if (!pos || !si || !sw) continue;
    const bones = mesh.skeleton.bones;
    const names = bones.map((b) => b.name);
    for (let i = 0; i < bones.length; i++) {
      if (!boneBind.has(names[i])) boneBind.set(names[i], mesh.skeleton.boneInverses[i].clone().invert());
    }
    // Which side each vertex hangs on, and how much of it hangs on that arm.
    const armOf = (v: number): { side: Side; weight: number } => {
      let r = 0;
      let l = 0;
      for (let j = 0; j < 4; j++) {
        const w = sw.getComponent(v, j);
        if (w <= 0) continue;
        const name = names[si.getComponent(v, j)];
        for (const b of ARM_BONES) {
          if (name === b + "_R") r += w;
          else if (name === b + "_L") l += w;
        }
      }
      return r >= l ? { side: "right", weight: r } : { side: "left", weight: l };
    };
    const index = geo.index;
    const count = index ? index.count : pos.count;
    const map = new Map<number, number>();
    normalM.copy(mesh.bindMatrix);
    for (let t = 0; t + 2 < count; t += 3) {
      const corners = [0, 1, 2].map((k) => (index ? index.getX(t + k) : t + k));
      const arms = corners.map(armOf);
      if (slot === "other" || arms.some((a) => a.weight < CUT.armWeight || a.side !== arms[0].side)) continue;
      // Every material of a character samples the same atlas: any of them lends it.
      if (!atlas?.map && std.map) atlas = std;
      for (const c of corners) {
        let id = map.get(c);
        if (id === undefined) {
          id = verts.length;
          map.set(c, id);
          const w = new Map<string, number>();
          for (let j = 0; j < 4; j++) {
            const x = sw.getComponent(c, j);
            if (x > 0) {
              const name = names[si.getComponent(c, j)];
              w.set(name, (w.get(name) ?? 0) + x);
            }
          }
          verts.push({
            p: new Vector3().fromBufferAttribute(pos, c).applyMatrix4(mesh.bindMatrix),
            n: nor ? new Vector3().fromBufferAttribute(nor, c).transformDirection(normalM) : new Vector3(0, 1, 0),
            uv: uv ? [uv.getX(c), uv.getY(c)] : [0, 0],
            // The baked occlusion lives in the colour's red (grey: every channel the same).
            ao: col ? col.getX(c) : 1,
            slot: SLOT_CODES.indexOf(slot),
            w,
          });
        }
        tris.push(id);
      }
      sideOf.push(arms[0].side);
    }
    if (slot !== "other" && std.color) authored[slot].copy(std.color);
    atlas ??= slot !== "other" ? std : null;
  }
  if (!tris.length) throw new Error("arm cut: no triangles hang on the arm bones");

  const sides: Record<Side, ArmRig> = {
    right: rigSide("right", verts, tris, sideOf, boneBind),
    left: rigSide("left", verts, tris, sideOf, boneBind),
  };

  // The geometry: one bone list for both arms (right 0..18, left 19..37).
  const n = verts.length;
  const position = new Float32Array(n * 3);
  const normal = new Float32Array(n * 3);
  const uvs = new Float32Array(n * 2);
  const occlusion = new Float32Array(n);
  const slots = new Uint8Array(n);
  const skinIndex = new Uint16Array(n * 4);
  const skinWeight = new Float32Array(n * 4);
  const vertSide = new Array<Side | null>(n).fill(null);
  for (let t = 0; t < tris.length; t += 3) for (let k = 0; k < 3; k++) vertSide[tris[t + k]] = sideOf[t / 3];
  const weights = new Map<Side, (v: SourceVertex) => Map<number, number>>([
    ["right", (sides.right as RigWithWeights).weigh],
    ["left", (sides.left as RigWithWeights).weigh],
  ]);
  for (let i = 0; i < n; i++) {
    const v = verts[i];
    if (SLOT_CODES[v.slot] === "trim") v.p.addScaledVector(v.n, CUT.trimLift);
    position.set([v.p.x, v.p.y, v.p.z], i * 3);
    normal.set([v.n.x, v.n.y, v.n.z], i * 3);
    uvs.set(v.uv, i * 2);
    occlusion[i] = v.ao;
    slots[i] = v.slot;
    const side = vertSide[i] ?? "right";
    const offset = side === "right" ? 0 : BONES;
    const w = [...(weights.get(side) as (v: SourceVertex) => Map<number, number>)(v).entries()].sort((a, b) => b[1] - a[1]).slice(0, 4);
    const total = w.reduce((s, [, x]) => s + x, 0) || 1;
    for (let j = 0; j < w.length; j++) {
      skinIndex[i * 4 + j] = w[j][0] + offset;
      skinWeight[i * 4 + j] = w[j][1] / total;
    }
  }
  const geometry = new BufferGeometry();
  geometry.name = "ViewmodelArms";
  geometry.setAttribute("position", new BufferAttribute(position, 3));
  geometry.setAttribute("normal", new BufferAttribute(normal, 3));
  geometry.setAttribute("uv", new BufferAttribute(uvs, 2));
  geometry.setAttribute("color", new BufferAttribute(new Float32Array(n * 3), 3));
  geometry.setAttribute("skinIndex", new BufferAttribute(skinIndex, 4));
  geometry.setAttribute("skinWeight", new BufferAttribute(skinWeight, 4));
  geometry.setIndex(n > 65535 ? new BufferAttribute(new Uint32Array(tris), 1) : new BufferAttribute(new Uint16Array(tris), 1));
  const ns = atlas?.normalScale;
  return {
    geometry,
    right: sides.right,
    left: sides.left,
    map: atlas?.map ?? null,
    normalMap: atlas?.normalMap ?? null,
    roughnessMap: atlas?.roughnessMap ?? null,
    normalScale: ns ? [ns.x, ns.y] : [1, 1],
    occlusion,
    slots,
    authored,
    triangles: tris.length / 3,
  };
}

interface RigWithWeights extends ArmRig {
  weigh: (v: SourceVertex) => Map<number, number>;
}

/** One arm: its joints and bind frames, and how a vertex's source weights map onto its bones. */
function rigSide(side: Side, verts: SourceVertex[], tris: number[], sideOf: Side[], boneBind: Map<string, Matrix4>): RigWithWeights {
  const sfx = SUFFIX[side];
  const at = (name: string): Vector3 => {
    const m = boneBind.get(name + sfx);
    if (!m) throw new Error(`arm cut: the body has no bone ${name}${sfx}`);
    return new Vector3().setFromMatrixPosition(m);
  };
  const shoulder = at("UpperArm");
  const elbow = at("ForeArm");
  const wrist = at("Hand");
  const knuckle = at("Fingers");
  const thumbRoot = at("Thumb");
  const mine = new Set<number>();
  for (let t = 0; t < tris.length; t += 3) if (sideOf[t / 3] === side) for (let k = 0; k < 3; k++) mine.add(tris[t + k]);
  const pts = (bone: string, min = 0.5) => [...mine].filter((i) => (verts[i].w.get(bone + sfx) ?? 0) >= min).map((i) => verts[i].p);

  // The hand's frame: knuckles from the wrist; across the hand from the spread of the fingers; the thumb's side.
  const z = knuckle.clone().sub(wrist).normalize();
  const fingerPts = pts("Fingers");
  const thumbPts = pts("Thumb");
  if (fingerPts.length < 16 || thumbPts.length < 4) throw new Error(`arm cut: the ${side} hand has too few finger vertices`);
  const flat = fingerPts.map((p) => p.clone().sub(knuckle).addScaledVector(z, -p.clone().sub(knuckle).dot(z)));
  const thumbC = thumbPts.reduce((s, p) => s.add(p), new Vector3()).multiplyScalar(1 / thumbPts.length);
  const thumbSide = thumbC.clone().sub(wrist);
  thumbSide.addScaledVector(z, -thumbSide.dot(z));
  const across = principal(flat, thumbSide);
  const X = side === "right" ? across.clone() : across.clone().negate();
  const Y = new Vector3().crossVectors(z, X).normalize();
  X.crossVectors(Y, z).normalize();
  const handBind = frame(wrist, X, Y, z);

  // Fingers: sorted across the hand (index on the thumb's side), each with its own axis and length.
  const lateral = (p: Vector3) => p.clone().sub(knuckle).dot(across);
  const along = (p: Vector3) => p.clone().sub(knuckle).dot(z);
  const beyond = fingerPts.filter((p) => along(p) > 0.012);
  const centres = kMeans1D(beyond.map(lateral), 4);
  const fingerOf = (p: Vector3): number => {
    const l = lateral(p);
    let best = 0;
    for (let j = 1; j < centres.length; j++) if (Math.abs(l - centres[j]) < Math.abs(l - centres[best])) best = j;
    return best;
  };
  const fingers: Finger[] = [];
  for (let f = 0; f < 4; f++) {
    const own = beyond.filter((p) => fingerOf(p) === f);
    const c = own.reduce((s, p) => s.add(p), new Vector3()).multiplyScalar(1 / Math.max(1, own.length));
    const dir = principal(own, z);
    // The knuckle joint: where the finger's axis crosses the knuckle plane.
    const k = knuckle.clone().sub(c).dot(z) / Math.max(0.2, dir.dot(z));
    const base = c.clone().addScaledVector(dir, k);
    let length = 0;
    for (const p of own) length = Math.max(length, p.clone().sub(base).dot(dir));
    fingers.push({ base, dir, length: Math.max(0.03, length) });
  }

  // The thumb: from its bone's root to its farthest point.
  let thumbTip = thumbRoot.clone();
  for (const p of thumbPts) if (p.distanceToSquared(thumbRoot) > thumbTip.distanceToSquared(thumbRoot)) thumbTip = p;
  const thumbDir = principal(thumbPts, thumbTip.clone().sub(thumbRoot));
  let thumbLength = 0;
  for (const p of thumbPts) thumbLength = Math.max(thumbLength, p.clone().sub(thumbRoot).dot(thumbDir));
  thumbLength = Math.max(0.03, thumbLength);
  // The thumb flexes toward the palm's middle (below the middle finger's root).
  const palm = fingers[1].base.clone().lerp(wrist, 0.5).addScaledVector(Y, -0.02);
  const thumbFlex = palm.sub(thumbRoot);
  const thumbBack = thumbFlex.addScaledVector(thumbDir, -thumbFlex.dot(thumbDir)).normalize().negate();

  // Bind frames. Elbows point backward at rest (the character faces +Z).
  const back = new Vector3(0, 0, -1);
  const bind: Matrix4[] = new Array(BONES);
  bind[B_UPPER] = frameYZ(shoulder, elbow.clone().sub(shoulder), back);
  bind[B_FORE] = frameYZ(elbow, wrist.clone().sub(elbow), back);
  bind[B_TWIST] = frameYZ(elbow, wrist.clone().sub(elbow), Y);
  bind[B_HAND] = handBind;
  for (let f = 0; f < 4; f++) {
    const { base, dir, length } = fingers[f];
    const joints = [0, CUT.fingerJoints[0], CUT.fingerJoints[1]];
    for (let j = 0; j < 3; j++) bind[fingerBone(f) + j] = frameZY(base.clone().addScaledVector(dir, joints[j] * length), dir, Y);
  }
  const tj = [0, CUT.thumbJoints[0], CUT.thumbJoints[1]];
  for (let j = 0; j < 3; j++) bind[B_THUMB + j] = frameZY(thumbRoot.clone().addScaledVector(thumbDir, tj[j] * thumbLength), thumbDir, thumbBack);

  // Landmarks in the hand's frame.
  const toHand = handBind.clone().invert();
  const knuckles = fingers[1].base.clone().lerp(fingers[2].base, 0.5).addScaledVector(Y, 0.012).applyMatrix4(toHand);
  const idx = fingers[0];
  const indexTip = idx.base.clone().addScaledVector(idx.dir, idx.length - 0.008).addScaledVector(Y, -0.006).applyMatrix4(toHand);
  const tips = fingers.map((f, i) => f.base.clone().addScaledVector(f.dir, f.length - 0.005).applyMatrix4(bind[fingerBone(i) + 2].clone().invert()));

  // The forearm's back for the emitter: how far the sleeve stands off the axis toward the back of the hand.
  const foreAxis = wrist.clone().sub(elbow);
  const foreLength = foreAxis.length();
  foreAxis.multiplyScalar(1 / foreLength);
  const twistZ = new Vector3().setFromMatrixColumn(bind[B_TWIST], 2);
  const emitterAt = CUT.emitterAt;
  let lift = 0.03;
  let wristRadius = 0.03;
  for (const i of mine) {
    const v = verts[i];
    const d = v.p.clone().sub(elbow);
    const t = d.dot(foreAxis) / foreLength;
    const radial = d.addScaledVector(foreAxis, -d.dot(foreAxis));
    if (Math.abs(t - emitterAt) < 0.08) lift = Math.max(lift, radial.dot(twistZ));
    if (Math.abs(t - 0.97) < 0.05) wristRadius = Math.max(wristRadius, radial.length());
  }

  const weigh = (v: SourceVertex): Map<number, number> => {
    const out = new Map<number, number>();
    const add = (bone: number, w: number) => { if (w > 0) out.set(bone, (out.get(bone) ?? 0) + w); };
    for (const [name, w] of v.w) {
      if (name === "ForeArm" + sfx) {
        // The forearm's weight runs from its hinge at the elbow to its twist at the wrist.
        const t = v.p.clone().sub(elbow).dot(foreAxis) / foreLength;
        const s = smoothstep(CUT.twist[0], CUT.twist[1], t);
        add(B_FORE, w * (1 - s));
        add(B_TWIST, w * s);
      } else if (name === "Hand" + sfx) {
        add(B_HAND, w);
      } else if (name === "Fingers" + sfx) {
        const f = fingerOf(v.p);
        const { base, dir, length } = fingers[f];
        const u = v.p.clone().sub(base).dot(dir) / length;
        const [j1, j2] = CUT.fingerJoints;
        const h = CUT.blend;
        const s2 = smoothstep(j1 - h, j1 + h, u);
        const s3 = smoothstep(j2 - h, j2 + h, u);
        add(fingerBone(f), w * (1 - s2));
        add(fingerBone(f) + 1, w * (s2 - s3));
        add(fingerBone(f) + 2, w * s3);
      } else if (name === "Thumb" + sfx) {
        const u = v.p.clone().sub(thumbRoot).dot(thumbDir) / thumbLength;
        const [j1, j2] = CUT.thumbJoints;
        const h = CUT.blend;
        const s2 = smoothstep(j1 - h, j1 + h, u);
        const s3 = smoothstep(j2 - h, j2 + h, u);
        add(B_THUMB, w * (1 - s2));
        add(B_THUMB + 1, w * (s2 - s3));
        add(B_THUMB + 2, w * s3);
      } else {
        // The upper arm, and whatever of the shoulder and chest reaches into the sleeve's top.
        add(B_UPPER, w);
      }
    }
    return out;
  };

  return {
    side, shoulder, elbow, wrist, upper: elbow.distanceTo(shoulder), fore: foreLength, bind, knuckles, indexTip, tips,
    emitterAt, emitterLift: lift, wristRadius, weigh,
  };
}
