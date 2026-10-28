// @vitest-environment node
/**
 * The duel's look and feel, the pure parts: which bolts and flashes get the
 * few moving lights, the knockout's slow motion and camera beat, reduced
 * motion, the crosshair's gauges and the edge glow of a hit, the knockout
 * call-outs and the countdown's match point.
 */
import { describe, expect, it } from "vitest";
import type { CombatEvent } from "../combat/types";
import type { PlayerView } from "../combat/view";
import { DuelCamera, DUEL_CAMERA, knockoutBeat } from "./duelCamera";
import { SLOW_MOTION, slowMotionScale } from "./duelController";
import { arcPath, DuelHudFeed, edgePoint, gaugeAngle, GAUGES } from "./duelHud";
import { pickLights, type LightRequest } from "./lights";

const req = (x: number, intensity: number, life = Infinity, total = 1): LightRequest => ({ x, y: 1, z: 0, r: 1, g: 1, b: 1, intensity, life, total });

describe("duel lights", () => {
  it("gives the few lights to the brightest requests near the camera", () => {
    const requests = [req(2, 2), req(25, 2), req(4, 9), req(1, 0.001), req(60, 50), req(3, 3)];
    expect(pickLights(requests, 0, 1, 0, 2)).toEqual([2, 5]);
    // Too dim or too far never gets one; never more than asked.
    expect(pickLights(requests, 0, 1, 0, 10)).not.toContain(3);
    expect(pickLights(requests, 0, 1, 0, 10)).not.toContain(4);
    expect(pickLights(requests, 0, 1, 0, 10).length).toBe(4);
  });

  it("weighs a flash by the life it has left", () => {
    const fresh = req(3, 6, 0.1, 0.1);
    const fading = req(3, 6, 0.01, 0.1);
    expect(pickLights([fading, fresh], 0, 1, 0, 1)).toEqual([1]);
  });
});

describe("knockout slow motion and camera beat", () => {
  it("slows the match at once and eases back to full speed", () => {
    expect(slowMotionScale(0)).toBe(1);
    expect(slowMotionScale(SLOW_MOTION.ms)).toBeCloseTo(SLOW_MOTION.scale);
    const easing = SLOW_MOTION.ms * SLOW_MOTION.easeShare;
    expect(slowMotionScale(easing * 0.5)).toBeGreaterThan(SLOW_MOTION.scale);
    expect(slowMotionScale(easing * 0.5)).toBeLessThan(1);
    expect(slowMotionScale(1)).toBeCloseTo(1, 1);
  });

  it("shapes the beat as a smooth bump that ends at rest", () => {
    expect(knockoutBeat(0)).toBe(0);
    expect(knockoutBeat(0.4)).toBe(1);
    expect(knockoutBeat(1)).toBe(0);
    expect(knockoutBeat(0.4, false)).toBe(0);
  });

  const me = (over: Partial<PlayerView> = {}): PlayerView => ({
    slot: 0, id: "a", local: true, side: 0, x: 50, z: 20, yaw: 0, pitch: 0, aimYaw: 0, aimPitch: 0, vx: 0, vz: 0, speed: 0, alive: true,
    health: 100, healthMax: 100, shieldUp: false, shieldEnergy: 1, shieldBroken: false, parrying: false, ads: 0, sprinting: false,
    dodging: false, dodgeProgress: 0, venting: false, overheated: false, heat: 0, ...over,
  });

  it("pulls the camera back and narrows it during a knockout, then settles", () => {
    const cam = new DuelCamera();
    const rest = { ...cam.update(1 / 60, me()) };
    const restPos = { ...rest.position };
    cam.knockout();
    let deepest = 0;
    let fov = rest.fovDeg;
    for (let i = 0; i < 40; i++) {
      const p = cam.update(1 / 60, me());
      deepest = Math.max(deepest, Math.hypot(p.position.x - restPos.x, p.position.z - restPos.z));
      fov = Math.min(fov, p.fovDeg);
    }
    expect(deepest).toBeGreaterThan(DUEL_CAMERA.knockoutBack * 0.6);
    expect(fov).toBeLessThan(rest.fovDeg);
    for (let i = 0; i < 120; i++) cam.update(1 / 60, me());
    expect(cam.knockoutShare).toBe(0);
    expect(cam.update(1 / 60, me()).fovDeg).toBeCloseTo(rest.fovDeg, 3);
  });

  it("keeps only a trace of the shake with reduced motion", () => {
    const shaken = (reduced: boolean) => {
      const cam = new DuelCamera();
      cam.reducedMotion = reduced;
      const still = { ...cam.update(1 / 60, me()).dir };
      cam.kick(3);
      const d = cam.update(1 / 60, me()).dir;
      return Math.hypot(d.x - still.x, d.y - still.y, d.z - still.z);
    };
    expect(shaken(true)).toBeLessThan(shaken(false) * 0.5);
  });
});

describe("duel HUD gauges and damage edges", () => {
  it("draws arcs clockwise from straight up", () => {
    expect(arcPath(10, 0, 90)).toBe("M 0.00 -10.00 A 10 10 0 0 1 10.00 0.00");
    expect(arcPath(10, 90, 0)).toBe("M 10.00 0.00 A 10 10 0 0 0 0.00 -10.00");
  });

  it("fills heat up the right side and shield up the left", () => {
    expect(gaugeAngle(GAUGES.heat, 0)).toBe(GAUGES.heat.from);
    expect(gaugeAngle(GAUGES.heat, 1)).toBeLessThan(90);
    expect(gaugeAngle(GAUGES.shield, 1)).toBeGreaterThan(270);
    expect(gaugeAngle(GAUGES.heat, 2)).toBe(gaugeAngle(GAUGES.heat, 1));
  });

  it("puts the damage glow on the edge the hit came from", () => {
    expect(edgePoint(0).y).toBeLessThan(0);
    expect(edgePoint(0).x).toBeCloseTo(50);
    expect(edgePoint(90).x).toBeGreaterThan(100);
    expect(edgePoint(-90).x).toBeLessThan(0);
    expect(edgePoint(180).y).toBeGreaterThan(100);
  });
});

describe("duel HUD knockout call-outs", () => {
  const death = (player: number, killer: number): CombatEvent => ({ type: "death", tick: 1, player, killer });

  it("calls a knockout for the person's kill and their own fall", () => {
    const feed = new DuelHudFeed();
    feed.ingest([death(1, 0)], 0, 0);
    expect(feed.callout?.key).toBe("knockout");
    feed.ingest([death(0, 1)], 0, 10);
    expect(feed.callout?.key).toBe("down");
  });
});
