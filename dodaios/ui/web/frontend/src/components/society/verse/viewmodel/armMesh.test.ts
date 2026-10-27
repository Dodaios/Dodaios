/**
 * The first-person arms cut from the commander's body (SK_Officer_M.glb, read
 * from disk): what the cut keeps, the weights it gives the re-rigged hand and
 * forearm, and that posing the arm bends the surface smoothly (no torn or
 * collapsed triangles at the elbow, the wrist or the knuckles).
 */
import { beforeAll, describe, expect, it } from "vitest";
import { Bone, Matrix4, Quaternion, Skeleton, SkinnedMesh, Vector3, type BufferGeometry } from "three";
import { B_FORE, B_HAND, B_THUMB, B_TWIST, B_UPPER, BONES, cutArms, fingerBone, kMeans1D, type ArmsSource } from "./armMesh";
import { handPose, ViewArm } from "./arms";
import { loadBody } from "./armFixture.test-util";

let meshes: Awaited<ReturnType<typeof loadBody>>;
beforeAll(async () => { meshes = await loadBody(); });

/** Skinned positions of `geometry` for `bones` posed (bind inverses from the cut). */
function skinned(geometry: BufferGeometry, bones: Bone[], inverses: Matrix4[]): Vector3[] {
  const mesh = new SkinnedMesh(geometry);
  for (const b of bones) if (!b.parent) mesh.add(b);
  mesh.bind(new Skeleton(bones, inverses), new Matrix4());
  mesh.updateMatrixWorld(true);
  mesh.skeleton.update();
  const out: Vector3[] = [];
  for (let i = 0; i < geometry.getAttribute("position").count; i++) out.push(mesh.getVertexPosition(i, new Vector3()));
  for (const b of bones) if (b.parent === mesh) mesh.remove(b);
  return out;
}

/** The ratio of every edge's posed length to its bind length, worst stretch and worst squash. */
function edgeRatios(geometry: BufferGeometry, posed: Vector3[]): { max: number; min: number } {
  const pos = geometry.getAttribute("position");
  const index = geometry.getIndex();
  const bind = (i: number) => new Vector3().fromBufferAttribute(pos, i);
  let max = 0;
  let min = Infinity;
  if (!index) return { max, min };
  for (let t = 0; t < index.count; t += 3) {
    for (let k = 0; k < 3; k++) {
      const a = index.getX(t + k);
      const b = index.getX(t + ((k + 1) % 3));
      const rest = bind(a).distanceTo(bind(b));
      if (rest < 1e-4) continue;
      const r = posed[a].distanceTo(posed[b]) / rest;
      max = Math.max(max, r);
      min = Math.min(min, r);
    }
  }
  return { max, min };
}

describe("arm cut", () => {
  let src: ArmsSource;
  beforeAll(() => { src = cutArms(meshes); });

  it("keeps both arms from the upper arm to the fingertips, within the budget", () => {
    expect(src.triangles).toBeGreaterThan(2000);
    expect(src.triangles).toBeLessThanOrEqual(4500);
    // The body's own proportions: an upper arm of ~29 cm and a forearm of ~24 cm.
    for (const side of [src.right, src.left]) {
      expect(side.upper).toBeGreaterThan(0.25);
      expect(side.upper).toBeLessThan(0.34);
      expect(side.fore).toBeGreaterThan(0.2);
      expect(side.fore).toBeLessThan(0.3);
    }
    // Sleeves, cuffs and hands, all drawn with the body's atlas.
    const kinds = new Set(src.slots);
    expect(kinds.size).toBeGreaterThanOrEqual(3);
    expect(src.geometry.getAttribute("uv")).toBeTruthy();
  });

  it("gives every vertex at most four normalised weights on its own arm's bones", () => {
    const si = src.geometry.getAttribute("skinIndex");
    const sw = src.geometry.getAttribute("skinWeight");
    const pos = src.geometry.getAttribute("position");
    for (let i = 0; i < si.count; i++) {
      let sum = 0;
      for (let j = 0; j < 4; j++) {
        const w = sw.getComponent(i, j);
        sum += w;
        if (w > 0) {
          // Right arm bones 0..18 (the character's right is −X), left 19..37.
          const b = si.getComponent(i, j);
          expect(b < BONES).toBe(pos.getX(i) < 0);
        }
      }
      expect(sum).toBeCloseTo(1, 5);
    }
  });

  it("blends the elbow and the wrist, and splits each finger into three phalanges", () => {
    const si = src.geometry.getAttribute("skinIndex");
    const sw = src.geometry.getAttribute("skinWeight");
    const count = new Map<number, number>();
    const blended = { elbow: 0, wrist: 0, knuckle: 0 };
    for (let i = 0; i < si.count; i++) {
      const bones = new Set<number>();
      for (let j = 0; j < 4; j++) {
        if (sw.getComponent(i, j) < 0.05) continue;
        const b = si.getComponent(i, j) % BONES;
        bones.add(b);
        count.set(b, (count.get(b) ?? 0) + 1);
      }
      if (bones.has(B_UPPER) && (bones.has(B_FORE) || bones.has(B_TWIST))) blended.elbow++;
      if (bones.has(B_HAND) && bones.has(B_TWIST)) blended.wrist++;
      if (bones.has(B_HAND) && [0, 1, 2, 3].some((f) => bones.has(fingerBone(f)))) blended.knuckle++;
    }
    expect(blended.elbow).toBeGreaterThan(10);
    expect(blended.wrist).toBeGreaterThan(10);
    expect(blended.knuckle).toBeGreaterThan(10);
    // Every phalanx of every finger, and of the thumb, carries vertices of its own.
    for (let f = 0; f < 4; f++) for (let j = 0; j < 3; j++) expect(count.get(fingerBone(f) + j) ?? 0).toBeGreaterThan(4);
    for (let j = 0; j < 3; j++) expect(count.get(B_THUMB + j) ?? 0).toBeGreaterThan(4);
  });

  it("sorts the fingers across the hand: the index next to the thumb, the little finger outside", () => {
    for (const side of [src.right, src.left]) {
      const toHand = side.bind[B_HAND].clone().invert();
      const across = [0, 1, 2, 3].map((f) => new Vector3().setFromMatrixPosition(side.bind[fingerBone(f)]).applyMatrix4(toHand).x);
      const thumb = new Vector3().setFromMatrixPosition(side.bind[B_THUMB]).applyMatrix4(toHand).x;
      // The right hand's thumb is on +X, the left's (mirrored) on −X.
      const s = side.side === "right" ? 1 : -1;
      for (let f = 0; f < 3; f++) expect(s * across[f]).toBeGreaterThan(s * across[f + 1]);
      expect(s * thumb).toBeGreaterThan(s * across[3]);
      // Fingers 1.5–3.5 cm apart at the knuckles.
      for (let f = 0; f < 3; f++) {
        expect(Math.abs(across[f] - across[f + 1])).toBeGreaterThan(0.012);
        expect(Math.abs(across[f] - across[f + 1])).toBeLessThan(0.035);
      }
    }
  });

  it("clusters values in one dimension", () => {
    const c = kMeans1D([0, 0.1, 0.2, 1, 1.1, 2, 2.1, 3, 3.2], 4);
    expect(c).toHaveLength(4);
    expect(c[0]).toBeCloseTo(3.1, 6);
    expect(c[3]).toBeCloseTo(0.1, 6);
  });

  it("bends the elbow, turns the wrist over and closes the fist without tearing the surface", () => {
    const src2 = cutArms(meshes);
    const right = new ViewArm(src2.right);
    const left = new ViewArm(src2.left);
    const bones = [...right.bones, ...left.bones];
    const inverses = [...right.inverses(), ...left.inverses()];
    // A held pose: the elbow bent ~90°, the hand palm-in ahead of the chest, a closed fist.
    const shoulder = new Vector3(-0.17, 1.41, 0);
    const wrist = new Vector3(-0.2, 1.2, 0.26);
    const q = ViewArm.handFrame(new Vector3(0.2, 0.1, 1), new Vector3(-1, 0.3, 0), new Quaternion());
    right.pose(shoulder, wrist, q, new Vector3(-0.3, -1, -0.4).normalize());
    right.curl(handPose(1.5, 1.6, 0.9, [1.5, 1.6], 0.4));
    left.pose(new Vector3(0.17, 1.41, 0), new Vector3(0.2, 0.92, 0.1), ViewArm.handFrame(new Vector3(0, -1, 0.1), new Vector3(1, 0, 0), new Quaternion()), new Vector3(0.3, -0.2, -1).normalize());
    left.curl(handPose(0.3, 0.3, 0.2));
    for (const g of [right.group, left.group]) g.updateMatrixWorld(true);
    const posed = skinned(src2.geometry, bones, inverses);
    const { max, min } = edgeRatios(src2.geometry, posed);
    // A fist stretches the skin over the knuckles about twofold and folds the palm side; a vertex hung on the wrong
    // finger, or a joint without a blend, would tear its triangles far wider or collapse them to a point.
    expect(max).toBeLessThan(2.5);
    expect(min).toBeGreaterThan(0.03);
    // The hand ends at the wrist (the sleeve never parts from the glove).
    expect(right.hand.position.distanceTo(wrist)).toBeLessThan(1e-9);
    src2.geometry.dispose();
  });

  it("keeps the bind pose exactly when the bones sit at their bind frames", () => {
    const src3 = cutArms(meshes);
    const arm = new ViewArm(src3.right);
    const other = new ViewArm(src3.left);
    const bones = [...arm.bones, ...other.bones];
    for (const [i, b] of bones.entries()) {
      const side = i < BONES ? src3.right : src3.left;
      if (b.parent && b.parent !== arm.group && b.parent !== other.group) continue;
      side.bind[i % BONES].decompose(b.position, b.quaternion, b.scale);
    }
    // Chain bones keep their rest placement when uncurled.
    arm.curl(handPose(0, 0, 0));
    other.curl(handPose(0, 0, 0));
    for (const g of [arm.group, other.group]) g.updateMatrixWorld(true);
    const posed = skinned(src3.geometry, bones, [...arm.inverses(), ...other.inverses()]);
    const pos = src3.geometry.getAttribute("position");
    let worst = 0;
    for (let i = 0; i < pos.count; i++) worst = Math.max(worst, posed[i].distanceTo(new Vector3().fromBufferAttribute(pos, i)));
    expect(worst).toBeLessThan(1e-4);
    src3.geometry.dispose();
  });
});
