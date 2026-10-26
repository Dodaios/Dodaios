import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { Ray, ShaderLib, Vector3 } from "three";
import { parseDeckManifest, ManifestError } from "../../content/manifest";
import { realtimeContent } from "../../content/loadDeck";
import { CommanderControl } from "../../life/control";
import { arrivalYaw } from "../../actors/ActorsLayer";
import { SHOULDER, ShoulderRig, verticalFov, type SegmentTest } from "./shoulderRig";
import { needsPhysical, patchDeckShader } from "./deckMaterial";
import { eyePick, rayCylinder } from "./eyePick";

const BRIDGE = resolve(__dirname, "../../../../../../public/verse/decks/bridge/manifest.json");

const body = (x: number, z: number, heading = Math.PI, moving = false) => ({ x, y: 0, z, heading, moving });

describe("shoulder rig", () => {
  it("frames the commander from behind, offset so they stand right of centre", () => {
    const rig = new ShoulderRig();
    rig.snapBehind(Math.PI); // facing −Z
    rig.update(1 / 60, body(0, 0));
    // Behind (+Z), above the head, a little to the left (−X) of the commander.
    expect(rig.position.z).toBeGreaterThan(1.8);
    expect(rig.position.z).toBeLessThan(2.6);
    expect(rig.position.x).toBeCloseTo(SHOULDER.side, 5);
    expect(rig.position.y).toBeGreaterThan(SHOULDER.pivotHeight);
    expect(rig.position.y).toBeLessThan(2.3);
    // The commander (x = 0) is right of the view axis: positive along the camera's right.
    const right = rig.right();
    const toBody = { x: 0 - rig.position.x, z: 0 - rig.position.z };
    expect(toBody.x * right.x + toBody.z * right.z).toBeGreaterThan(0.3);
    // Looking slightly down.
    expect(rig.target.y).toBeLessThan(rig.position.y);
  });

  it("walks W away from the camera and D to its right", () => {
    const rig = new ShoulderRig();
    rig.snapBehind(Math.PI);
    const w = rig.walkDirection(0, -1)!;
    expect(w.x).toBeCloseTo(0);
    expect(w.z).toBeCloseTo(-1);
    const d = rig.walkDirection(1, 0)!;
    expect(d.x).toBeCloseTo(1);
    expect(d.z).toBeCloseTo(0);
    rig.yaw = Math.PI / 2; // looking toward +X
    const w2 = rig.walkDirection(0, -1)!;
    expect(w2.x).toBeCloseTo(1);
    expect(rig.walkDirection(0, 0)).toBeNull();
  });

  it("turns with the mouse and clamps the pitch", () => {
    const rig = new ShoulderRig();
    const yaw = rig.yaw;
    rig.look(100, 0);
    expect(rig.yaw).toBeCloseTo(yaw - 100 * SHOULDER.dragRate);
    rig.look(0, 1e6);
    expect(rig.pitch).toBeCloseTo(SHOULDER.maxPitch);
    rig.look(0, -1e6);
    expect(rig.pitch).toBeCloseTo(SHOULDER.minPitch);
  });

  it("pulls in at once in front of a wall and eases back out", () => {
    const rig = new ShoulderRig();
    rig.snapBehind(Math.PI);
    let wall = true;
    // A wall 1.2 m behind the commander (z = 1.2).
    const test: SegmentTest = (from, to) => {
      if (!wall || to.z <= 1.2 || from.z >= 1.2) return null;
      return (1.2 - from.z) / (to.z - from.z);
    };
    rig.update(1 / 60, body(0, 0), test);
    expect(rig.position.z).toBeLessThan(1.2);
    wall = false;
    rig.update(1 / 60, body(0, 0), test);
    const after = rig.actual;
    expect(after).toBeLessThan(SHOULDER.distance);
    for (let i = 0; i < 120; i++) rig.update(1 / 60, body(0, 0), test);
    expect(rig.actual).toBeCloseTo(SHOULDER.distance);
  });

  it("follows smoothly without jumping and never turns the view on its own", () => {
    const rig = new ShoulderRig();
    rig.snapBehind(Math.PI);
    rig.update(1 / 60, body(0, 0));
    rig.update(1 / 60, body(1, 0));
    expect(rig.position.x).toBeLessThan(SHOULDER.side + 1); // lags behind the 1 m jump
    // Shooter look: only the mouse turns the view, however the commander walks.
    for (let i = 0; i < 300; i++) rig.update(1 / 60, body(1, 0, Math.PI / 2, true));
    expect(rig.yaw).toBeCloseTo(Math.PI);
  });

  it("keeps a 70 degree horizontal field of view on wide frames", () => {
    const aspect = 2560 / 1392;
    const v = (verticalFov(aspect) * Math.PI) / 180;
    expect((2 * Math.atan(Math.tan(v / 2) * aspect) * 180) / Math.PI).toBeCloseTo(70, 1);
    expect(verticalFov(0.6)).toBeGreaterThanOrEqual(SHOULDER.minVfovDeg);
  });
});

describe("camera-relative keys", () => {
  it("turns the held keys into a floor direction relative to the camera", () => {
    const control = new CommanderControl();
    const rig = new ShoulderRig();
    rig.yaw = Math.PI / 2;
    control.setKey("up", true);
    const dir = control.directionFrom(rig)!;
    expect(dir.x).toBeCloseTo(1);
    expect(dir.z).toBeCloseTo(0);
  });
});

describe("deck shader patch", () => {
  const physical = ShaderLib.physical;

  it("adds baked radiance, box projection and the plate detail to the physical shader", () => {
    const { vertexShader, fragmentShader } = patchDeckShader(physical.vertexShader, physical.fragmentShader);
    expect(vertexShader).toContain("vVerseWorld = ( modelMatrix * vec4( transformed, 1.0 ) ).xyz;");
    expect(fragmentShader).toContain("totalEmissiveRadiance += verseDecode( texture2D( lightMap, vLightMapUv ) ) * verseBakedGain;");
    expect(fragmentShader).toContain("reflectVec = verseBoxProject( reflectVec, roughness );");
    expect(fragmentShader).toContain("float verseJoint = verseSeam( vVerseWorld );");
    // A fragment just past its room's box grows the box: no jump to the unprojected direction.
    expect(fragmentShader).toContain("vec3 boxMin = min( verseBoxMin, p - 0.02 );");
    expect(fragmentShader).not.toMatch(/lessThan\( p, verseBoxMin/);
    // The lightmap never adds irradiance, and the environment adds no diffuse: the bake holds it.
    expect(fragmentShader).not.toContain("#include <lights_fragment_maps>");
    expect(fragmentShader).not.toContain("irradiance += lightMapIrradiance");
    expect(fragmentShader).not.toContain("iblIrradiance += getIBLIrradiance");
  });

  it("fails loudly when three's templates change", () => {
    expect(() => patchDeckShader("void main() {}", physical.fragmentShader)).toThrow(/not found/);
  });

  it("uses the physical material only where a coat, a specular level or glass needs it", () => {
    const base = { roughness: 0.4, metalness: 0, color: [0, 0, 0] as const, clearcoat: 0, clearcoatRoughness: 0, specular: 0.5, detail: "none", transparent: false, opacity: 1, collide: true };
    expect(needsPhysical(base)).toBe(false);
    expect(needsPhysical({ ...base, clearcoat: 1 })).toBe(true);
    expect(needsPhysical({ ...base, specular: 0.12 })).toBe(true);
    expect(needsPhysical({ ...base, transparent: true })).toBe(true);
  });
});

describe("eye-level picking", () => {
  it("enters an upright body cylinder from the side and from above", () => {
    expect(rayCylinder({ x: -5, y: 1, z: 0 }, { x: 1, y: 0, z: 0 }, 0, 0, 0.3, 0, 1.8)).toBeCloseTo(4.7);
    expect(rayCylinder({ x: 0, y: 5, z: 0 }, { x: 0, y: -1, z: 0 }, 0, 0, 0.3, 0, 1.8)).toBeCloseTo(3.2);
    expect(rayCylinder({ x: -5, y: 3, z: 0 }, { x: 1, y: 0, z: 0 }, 0, 0, 0.3, 0, 1.8)).toBeNull();
    expect(rayCylinder({ x: -5, y: 1, z: 1 }, { x: 1, y: 0, z: 0 }, 0, 0, 0.3, 0, 1.8)).toBeNull();
  });

  it("picks the nearest crew member in the way, and nothing without geometry or bodies", () => {
    const ray = new Ray(new Vector3(0, 1.6, 5), new Vector3(0, 0, -1));
    const bodies = [
      { id: "far", x: 0, y: 0, z: -3, height: 1.8 },
      { id: "near", x: 0.1, y: 0, z: 0, height: 1.8 },
    ];
    expect(eyePick(ray, [], bodies, () => true, null)).toEqual({ kind: "crew", id: "near" });
    expect(eyePick(ray, [], bodies, (id) => id === "far", null)).toEqual({ kind: "crew", id: "far" });
    expect(eyePick(ray, [], [], () => true, null)).toBeNull();
  });
});

describe("spawn facing", () => {
  it("faces a body along the spawn or lift it stands at, else toward the deck's forward", () => {
    const sockets = [
      { kind: "spawn", x: 0, z: 0, yaw: 1 },
      { kind: "lift", x: 10, z: 0, yaw: 2 },
    ] as unknown as Parameters<typeof arrivalYaw>[0]["sockets"];
    expect(arrivalYaw({ sockets }, 0.3, 0)).toBe(1);
    expect(arrivalYaw({ sockets }, 9.5, 0.5)).toBe(2);
    expect(arrivalYaw({ sockets }, 5, 5)).toBeCloseTo(Math.PI);
  });
});

describe("realtime manifest block", () => {
  const bridge = existsSync(BRIDGE) ? JSON.parse(readFileSync(BRIDGE, "utf8")) : null;
  const run = bridge?.realtime ? it : it.skip;

  run("reads the cooked bridge's realtime block with absolute URLs", () => {
    const m = parseDeckManifest(bridge);
    const content = realtimeContent(m.realtime, (r) => `/verse/decks/bridge/${r}`);
    expect(content).not.toBeNull();
    expect(content!.sceneUrl).toBe("/verse/decks/bridge/realtime/scene.glb");
    expect(content!.pages.length).toBeGreaterThan(0);
    expect(content!.materials.M_Floor_GlossBlack.detail).toBe("deck_plates");
    expect(content!.probes.map((p) => p.room)).toContain("bridge");
  });

  run("names the bad field of a broken realtime block, and ignores a newer version", () => {
    const broken = structuredClone(bridge);
    broken.realtime.lightmaps.encoding = "rgbe";
    expect(() => parseDeckManifest(broken)).toThrow(ManifestError);
    expect(() => parseDeckManifest(broken)).toThrow(/realtime\.lightmaps\.encoding/);
    const newer = structuredClone(bridge);
    newer.realtime.version = 2;
    expect(realtimeContent(parseDeckManifest(newer).realtime, (r) => r)).toBeNull();
  });

  it("leaves decks without a realtime block on the plate", () => {
    expect(realtimeContent(undefined, (r) => r)).toBeNull();
  });
});
