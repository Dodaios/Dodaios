import { describe, expect, it } from "vitest";
import { BoxGeometry, Group, Matrix3, Mesh, PerspectiveCamera, PlaneGeometry, Vector3 } from "three";
import { SPACE_LOOK, SpaceView, spaceTextureUrls, starField } from "./spaceView";
import { outwardOf } from "./realtimeScene";

describe("star field", () => {
  it("is the same sky on every visit, on the sphere, mostly faint", () => {
    const a = starField(2000);
    const b = starField(2000);
    expect(Array.from(a.positions)).toEqual(Array.from(b.positions));
    const p = new Vector3();
    let faint = 0;
    for (let i = 0; i < 2000; i++) {
      p.fromArray(a.positions, i * 3);
      expect(p.length()).toBeCloseTo(50, 3);
      if (a.colours[i * 3 + 1] < 0.3) faint++;
    }
    expect(faint / 2000).toBeGreaterThan(0.5);
  });
});

describe("viewport direction", () => {
  it("follows the big forward viewport, not a small porthole at the back", () => {
    const group = new Group();
    group.add(new Mesh(new BoxGeometry(40, 6, 40)));
    const hero = new Mesh(new PlaneGeometry(30, 5));
    hero.position.set(0, 3, -19);
    const porthole = new Mesh(new PlaneGeometry(2, 1));
    porthole.position.set(0, 3, 19);
    group.add(hero, porthole);
    group.updateMatrixWorld(true);
    const out = outwardOf(group, [hero, porthole])!;
    expect(out.z).toBeLessThan(-0.99);
    expect(out.y).toBe(0);
    expect(outwardOf(group, [])).toBeNull();
  });
});

describe("space view", () => {
  it("puts the Earth below the windows, with the chosen place facing them", () => {
    const view = new SpaceView(4);
    view.setOutward(new Vector3(0, 0, -1));
    const camera = new PerspectiveCamera(50, 16 / 9, 0.05, 500);
    camera.lookAt(0, 0, -1);
    camera.updateMatrixWorld();
    view.update(camera, 0, 1);
    const uniforms = (view as unknown as { planet: { uniforms: Record<string, { value: unknown }> } }).planet.uniforms;
    const centre = uniforms.earthCentre.value as Vector3;
    expect(centre.y).toBeLessThan(0);
    expect(centre.z).toBeLessThan(0);
    expect(centre.length()).toBeCloseTo(1 + SPACE_LOOK.altitudeKm / 6371, 5);
    // The ground point straight out of the windows maps to the chosen latitude and longitude.
    const out = new Vector3(0, 0, -1);
    const b = centre.dot(out);
    const h = b * b - (centre.lengthSq() - 1);
    expect(h).toBeGreaterThan(0);
    const normal = out.multiplyScalar(b - Math.sqrt(h)).sub(centre).normalize();
    const local = normal.applyMatrix3(uniforms.worldToEarth.value as Matrix3);
    const lat = (Math.asin(local.y) * 180) / Math.PI;
    const lon = (Math.atan2(-local.z, local.x) * 180) / Math.PI;
    expect(lat).toBeCloseTo(SPACE_LOOK.latDeg, 3);
    expect(lon).toBeCloseTo(SPACE_LOOK.lonDeg, 3);
    view.dispose();
  });

  it("serves its textures next to the decks", () => {
    expect(spaceTextureUrls("/").day).toBe("/verse/space/earth_day.webp");
  });
});
