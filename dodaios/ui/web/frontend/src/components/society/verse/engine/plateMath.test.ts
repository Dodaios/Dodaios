import { describe, expect, it } from "vitest";
import { Matrix4, OrthographicCamera, Vector3 } from "three";
import { cameraBasis, pixelToPlate, plateToPixel, plateToWorldAtHeight, worldToPlate, type PlateCamera } from "./plateMath";
import { applyPlateCamera } from "./plateCamera";
import { plateToScreen, type View, type Viewport } from "./view";

const cam: PlateCamera = { center: [12, 0, -3], pitchDeg: 60, frameW: 80, frameH: 40, pxPerMetre: 96 };

describe("plate camera basis", () => {
  it("is orthonormal and right-handed (R × U = −D)", () => {
    const { right, up, dir } = cameraBasis(60);
    const R = new Vector3(...right), U = new Vector3(...up), D = new Vector3(...dir);
    expect(R.length()).toBeCloseTo(1, 12);
    expect(U.length()).toBeCloseTo(1, 12);
    expect(D.length()).toBeCloseTo(1, 12);
    expect(R.dot(U)).toBeCloseTo(0, 12);
    expect(U.dot(D)).toBeCloseTo(0, 12);
    const cross = R.clone().cross(U);
    expect(cross.x).toBeCloseTo(-D.x, 12);
    expect(cross.y).toBeCloseTo(-D.y, 12);
    expect(cross.z).toBeCloseTo(-D.z, 12);
  });

  it("looks toward −Z and down", () => {
    const { dir } = cameraBasis(60);
    expect(dir[1]).toBeLessThan(0);
    expect(dir[2]).toBeLessThan(0);
  });
});

describe("world ↔ plate", () => {
  it("maps the centre to (0, 0) and +X to +u", () => {
    expect(worldToPlate(cam, 12, 0, -3)).toEqual({ u: 0, v: 0 });
    expect(worldToPlate(cam, 13, 0, -3).u).toBeCloseTo(1, 12);
  });

  it("moves a floor point toward the camera (+Z) down the plate", () => {
    expect(worldToPlate(cam, 12, 0, -2).v).toBeCloseTo(-Math.sin(Math.PI / 3), 12);
  });

  it("foreshortens height by cos 60°", () => {
    expect(worldToPlate(cam, 12, 2, -3).v).toBeCloseTo(1, 12);
  });

  it("round-trips through the floor and any height", () => {
    for (const [u, v, y] of [[3, 4, 0], [-10.5, 7.25, 0], [0.3, -2, 1.1], [20, 15, 3.5]]) {
      const [x, wy, z] = plateToWorldAtHeight(cam, u, v, y);
      expect(wy).toBe(y);
      const back = worldToPlate(cam, x, wy, z);
      expect(back.u).toBeCloseTo(u, 10);
      expect(back.v).toBeCloseTo(v, 10);
    }
  });

  it("puts every point of one view ray on one plate point", () => {
    const { dir } = cameraBasis(60);
    const p = [5, 1, 2] as const;
    const a = worldToPlate(cam, ...p);
    const b = worldToPlate(cam, p[0] + dir[0] * 7, p[1] + dir[1] * 7, p[2] + dir[2] * 7);
    expect(b.u).toBeCloseTo(a.u, 12);
    expect(b.v).toBeCloseTo(a.v, 12);
  });
});

describe("plate ↔ pixels", () => {
  it("puts the top-left corner at pixel (0, 0) and the centre in the middle", () => {
    expect(plateToPixel(cam, -40, 20)).toEqual({ x: 0, y: 0 });
    expect(plateToPixel(cam, 0, 0)).toEqual({ x: 40 * 96, y: 20 * 96 });
  });

  it("round-trips", () => {
    const px = plateToPixel(cam, 3.21, -4.56);
    const back = pixelToPlate(cam, px.x, px.y);
    expect(back.u).toBeCloseTo(3.21, 10);
    expect(back.v).toBeCloseTo(-4.56, 10);
  });
});

describe("the three.js camera matches the plate maths to the pixel", () => {
  const vp: Viewport = { width: 1280, height: 720, dpr: 1.5 };
  const view: View = { cu: 4.2, cv: -3.3, scale: 61.7 };

  it("projects world points where the view maths put them on screen", () => {
    const camera = new OrthographicCamera();
    applyPlateCamera(camera, cam, view, vp);
    for (const p of [[12, 0, -3], [20, 0, 4], [3, 1.1, -8], [15.5, 2.4, 1]] as const) {
      const ndc = new Vector3(...p).project(camera);
      const sx = ((ndc.x + 1) / 2) * vp.width;
      const sy = ((1 - ndc.y) / 2) * vp.height;
      const { u, v } = worldToPlate(cam, p[0], p[1], p[2]);
      const want = plateToScreen(view, vp, u, v);
      // A thousandth of a CSS pixel.
      expect(Math.abs(sx - want.x)).toBeLessThan(1e-3);
      expect(Math.abs(sy - want.y)).toBeLessThan(1e-3);
      expect(ndc.z).toBeGreaterThan(-1);
      expect(ndc.z).toBeLessThan(1);
    }
  });

  it("keeps the camera axes on the plate basis", () => {
    const camera = new OrthographicCamera();
    applyPlateCamera(camera, cam, view, vp);
    const m = new Matrix4().extractRotation(camera.matrixWorld);
    const x = new Vector3(1, 0, 0).applyMatrix4(m);
    const y = new Vector3(0, 1, 0).applyMatrix4(m);
    const { right, up } = cameraBasis(60);
    expect(x.toArray().map((n) => +n.toFixed(9))).toEqual([...right].map((n) => +n.toFixed(9)));
    expect(y.toArray().map((n) => +n.toFixed(9))).toEqual([...up].map((n) => +n.toFixed(9)));
  });
});
