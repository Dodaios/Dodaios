// @vitest-environment node
import { describe, expect, it } from "vitest";
import { closestApproachXZ, sweepBox, sweepCapsule, sweepCylinder, sweepOut, sweepSphere } from "./raycast";
import { hash32, rand01, Rng } from "./rng";

describe("segment sweeps", () => {
  const o = sweepOut();

  it("enters a box at the near face with its normal", () => {
    const t = sweepBox(0, 1, 0, 10, 0, 0, 4, 0, -1, 6, 2, 1, o);
    expect(t).toBeCloseTo(0.4, 9);
    expect([o.nx, o.ny, o.nz]).toEqual([-1, 0, 0]);
    expect(sweepBox(0, 3, 0, 10, 0, 0, 4, 0, -1, 6, 2, 1, o)).toBe(-1);
    expect(sweepBox(0, 1, 0, 3, 0, 0, 4, 0, -1, 6, 2, 1, o)).toBe(-1);
  });

  it("hits a vertical cylinder's side and its top cap", () => {
    expect(sweepCylinder(-5, 1, 0, 10, 0, 0, 0, 0, 1, 0, 2, o)).toBeCloseTo(0.4, 9);
    expect(o.nx).toBeCloseTo(-1, 9);
    const t = sweepCylinder(0.2, 5, 0, 0, -10, 0, 0, 0, 1, 0, 2, o);
    expect(t).toBeCloseTo(0.3, 9);
    expect(o.ny).toBe(1);
    expect(sweepCylinder(-5, 3, 0, 10, 0, 0, 0, 0, 1, 0, 2, o)).toBe(-1);
  });

  it("hits a capsule on its side and its rounded ends", () => {
    expect(sweepCapsule(-5, 1, 0, 10, 0, 0, 0, 0, 0.5, 1.5, 0.4, o)).toBeCloseTo(0.46, 9);
    // Just over the top segment end: the cap still catches it.
    expect(sweepCapsule(-5, 1.7, 0, 10, 0, 0, 0, 0, 0.5, 1.5, 0.4, o)).toBeGreaterThan(0);
    expect(sweepCapsule(-5, 2.0, 0, 10, 0, 0, 0, 0, 0.5, 1.5, 0.4, o)).toBe(-1);
    expect(sweepSphere(-5, 0, 0, 10, 0, 0, 0, 0, 0, 1, o)).toBeCloseTo(0.4, 9);
  });

  it("reports the closest approach of a moving point", () => {
    const c = closestApproachXZ(-10, 1, 10, 0, 0, 0);
    expect(c.t).toBeCloseTo(1, 9);
    expect(c.dist).toBeCloseTo(1, 9);
  });
});

describe("seeded randomness", () => {
  it("hashes are stable and spread", () => {
    expect(hash32(1)).toBe(hash32(1));
    expect(hash32(1)).not.toBe(hash32(2));
    let sum = 0;
    for (let i = 0; i < 2000; i++) sum += rand01(7, i, 3, 1);
    expect(sum / 2000).toBeGreaterThan(0.45);
    expect(sum / 2000).toBeLessThan(0.55);
  });

  it("a generator replays from its state", () => {
    const a = new Rng(42);
    a.next();
    const copy = new Rng(0);
    copy.state = a.state;
    expect([a.next(), a.next()]).toEqual([copy.next(), copy.next()]);
    const n = new Rng(3);
    let s = 0;
    let s2 = 0;
    for (let i = 0; i < 4000; i++) { const v = n.normal(); s += v; s2 += v * v; }
    expect(Math.abs(s / 4000)).toBeLessThan(0.06);
    expect(Math.sqrt(s2 / 4000)).toBeGreaterThan(0.93);
    expect(Math.sqrt(s2 / 4000)).toBeLessThan(1.07);
  });
});
