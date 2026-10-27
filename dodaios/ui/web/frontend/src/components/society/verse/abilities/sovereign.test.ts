import { describe, expect, it } from "vitest";
import { Bone, Group, Vector3 } from "three";
import { boltPoints, rng } from "./arcStorm";
import { CloakRig, cloakTarget } from "../actors/cloak";

describe("Arc Storm bolts", () => {
  it("run from the hand to the target with the asked number of segments", () => {
    const a = new Vector3(0, 1.3, 0);
    const b = new Vector3(0, 1, 5);
    const pts = boltPoints(a, b, 16, 0.3, rng(7));
    expect(pts).toHaveLength(17);
    expect(pts[0].equals(a)).toBe(true);
    expect(pts[16].equals(b)).toBe(true);
  });

  it("stay near the line between the ends", () => {
    const a = new Vector3(0, 0, 0);
    const b = new Vector3(0, 0, 4);
    for (const p of boltPoints(a, b, 16, 0.3, rng(3))) {
      expect(Math.hypot(p.x, p.y)).toBeLessThan(4 * 0.3);
      expect(p.z).toBeGreaterThan(-0.5);
      expect(p.z).toBeLessThan(4.5);
    }
  });

  it("are the same for the same seed", () => {
    const a = new Vector3(1, 1, 1);
    const b = new Vector3(3, 0, 2);
    const p = boltPoints(a, b, 8, 0.3, rng(11));
    const q = boltPoints(a, b, 8, 0.3, rng(11));
    expect(p.map((v) => v.toArray())).toEqual(q.map((v) => v.toArray()));
  });
});

describe("the Sovereign's cloak", () => {
  it("hangs still when the body stands", () => {
    const t = cloakTarget(0, 0, 0, 0);
    expect(t.pitch).toBeCloseTo(0, 5);
    expect(t.roll).toBeCloseTo(0, 5);
  });

  it("lifts behind a walking body and swings against a strafe", () => {
    expect(cloakTarget(1.4, 0, 0, 0).pitch).toBeGreaterThan(0.3);
    expect(cloakTarget(0, 1, 0, 0).roll).toBeLessThan(0);
    expect(cloakTarget(0, -1, 0, 0).roll).toBeGreaterThan(0);
    // never swings forward into the legs much when backing off
    expect(cloakTarget(-2, 0, 0, 0).pitch).toBeGreaterThanOrEqual(-0.08);
  });

  it("is found on a skeleton with cloak bones and poses them while walking", () => {
    const root = new Group();
    const chest = new Bone();
    chest.name = "Chest";
    root.add(chest);
    for (const c of ["R", "C", "L"]) {
      const up = new Bone();
      up.name = `Cloak_${c}1`;
      const low = new Bone();
      low.name = `Cloak_${c}2`;
      low.position.set(0, -0.6, 0);
      up.add(low);
      chest.add(up);
    }
    const rig = CloakRig.find(root);
    expect(rig).not.toBeNull();
    const up = root.getObjectByName("Cloak_C1") as Bone;
    const rest = up.quaternion.clone();
    for (let i = 0; i < 60; i++) rig!.update(1 / 60, 0, i * (1.4 / 60), 0);
    expect(up.quaternion.angleTo(rest)).toBeGreaterThan(0.1);
    rig!.reset();
    expect(up.quaternion.angleTo(rest)).toBeCloseTo(0, 6);
  });

  it("is absent on a body without cloak bones", () => {
    const root = new Group();
    const chest = new Bone();
    chest.name = "Chest";
    root.add(chest);
    expect(CloakRig.find(root)).toBeNull();
  });
});

describe("character file URLs", () => {
  it("carry the file size as a version", async () => {
    const { versionedUrl } = await import("../actors/characters");
    expect(versionedUrl("/verse/a.glb", 123)).toBe("/verse/a.glb?v=123");
    expect(versionedUrl("/verse/a.glb?x=1", 5)).toBe("/verse/a.glb?x=1&v=5");
    expect(versionedUrl("/verse/a.glb", undefined)).toBe("/verse/a.glb");
  });
});
