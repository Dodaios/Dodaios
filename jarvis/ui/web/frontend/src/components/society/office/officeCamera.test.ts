import { describe, expect, it } from "vitest";
import {
  cameraHome, CAMERA_LIMITS, depthNear, farZoomBoost, FOLLOW_DISTANCE_M, followDistanceAfterOverview, frameDistance, settleView, WALK_VIEW_MAX_M, wheelZoomSpeed,
} from "./officeCamera";

/** OrbitControls' dolly factor for one wheel event at this zoom speed. */
const step = (speed: number) => 1 / Math.pow(0.95, speed);
/** Wheel events of this size needed to zoom from `from` to `to` metres. */
const eventsFor = (from: number, to: number, deltaY: number, deltaMode = 0) =>
  Math.ceil(Math.log(from / to) / Math.log(step(wheelZoomSpeed(deltaY, deltaMode))));

describe("office wheel zoom", () => {
  it("brings the overview down to the character in a handful of mouse notches", () => {
    const overview = cameraHome({ minX: -14, maxX: 14, minZ: -22, maxZ: 22 }, 16 / 9);
    const distance = Math.hypot(...overview.position.map((v, i) => v - overview.target[i]) as [number, number, number]);
    expect(eventsFor(distance, 15, 100)).toBeLessThanOrEqual(12);
  });

  it("zooms by how far the wheel turned, so a trackpad's small steps stay small", () => {
    expect(wheelZoomSpeed(4)).toBeLessThan(wheelZoomSpeed(100) / 10);
    expect(wheelZoomSpeed(-100)).toBe(wheelZoomSpeed(100));
    // A whole trackpad swipe of 100 px moves about as far as one notch.
    const swipe = Math.pow(step(wheelZoomSpeed(4)), 25);
    expect(swipe).toBeCloseTo(step(wheelZoomSpeed(100)), 1);
  });

  it("reads line and page wheel modes and caps a single huge event", () => {
    expect(wheelZoomSpeed(3, 1)).toBeGreaterThan(wheelZoomSpeed(100));
    expect(wheelZoomSpeed(1, 2)).toBe(wheelZoomSpeed(100_000));
    expect(step(wheelZoomSpeed(100_000))).toBeLessThan(1.4);
    expect(wheelZoomSpeed(0)).toBeGreaterThan(0);
  });

  it("lets the camera come close enough to read a desk, and never inside the character", () => {
    expect(CAMERA_LIMITS.minDistance).toBeLessThanOrEqual(3);
    expect(CAMERA_LIMITS.minDistance).toBeGreaterThanOrEqual(2);
  });
});

/** Smallest depth step a 24-bit buffer resolves at `depth` metres with this near plane. */
const depthStep = (depth: number, near: number) => (depth * depth) / (near * 2 ** 24);

describe("office depth precision", () => {
  it("keeps the oak floor 1 mm above the slab resolvable at every zoom", () => {
    for (const distance of [CAMERA_LIMITS.minDistance, 15, 40, 90, CAMERA_LIMITS.maxDistance]) {
      // The far edge of the floor lies up to ~30 m behind the orbit target.
      expect(depthStep(distance + 30, depthNear(distance))).toBeLessThan(0.001);
    }
  });

  it("never clips the floor or the walls in front of the camera", () => {
    for (const distance of [CAMERA_LIMITS.minDistance, 15, 40, 90, CAMERA_LIMITS.maxDistance]) {
      // At the flattest allowed tilt the camera still stands this high above the floor.
      const height = distance * Math.cos(CAMERA_LIMITS.maxPolar);
      expect(depthNear(distance)).toBeLessThan(Math.max(0.5, height - 3));
    }
    expect(depthNear(CAMERA_LIMITS.minDistance)).toBe(0.2);
  });
});

describe("wheel zoom on a large floor", () => {
  /** Mouse notches from `from` metres until the camera is within `to`, each notch zooming for the distance it starts at. */
  const notches = (from: number, to: number) => {
    let distance = from, count = 0;
    while (distance > to && count < 100) { distance /= step(wheelZoomSpeed(100, 0, distance)); count += 1; }
    return count;
  };
  // The overview of a campus of sixty agents in six teams.
  const overview = frameDistance({ minX: -29.2, maxX: 29.2, minZ: -33.2, maxZ: 33.2 }, 16 / 9);

  it("comes down from the overview of a campus to a studio in a few notches", () => {
    expect(overview).toBeGreaterThan(80);
    expect(notches(overview, 30)).toBeLessThanOrEqual(5);
    expect(notches(overview, FOLLOW_DISTANCE_M)).toBeLessThanOrEqual(10);
    // The same way took more than twice as many notches at one fixed step.
    expect(Math.ceil(Math.log(overview / FOLLOW_DISTANCE_M) / Math.log(step(wheelZoomSpeed(100))))).toBeGreaterThan(14);
  });

  it("stays as fine as it was near the character", () => {
    expect(farZoomBoost(0)).toBe(1);
    expect(farZoomBoost(FOLLOW_DISTANCE_M)).toBe(1);
    expect(wheelZoomSpeed(100, 0, 10)).toBe(wheelZoomSpeed(100));
    expect(wheelZoomSpeed(4, 0, 10)).toBe(wheelZoomSpeed(4));
    // Further out each notch reaches further, smoothly, and no further than a third of the way.
    for (let d = 10; d < 200; d += 5) expect(farZoomBoost(d + 5)).toBeGreaterThanOrEqual(farZoomBoost(d));
    expect(step(wheelZoomSpeed(100, 0, 400))).toBeLessThan(1.6);
    // A trackpad's small steps stay small far out, too.
    expect(wheelZoomSpeed(4, 0, 100)).toBeLessThan(wheelZoomSpeed(100, 0, 100) / 10);
  });
});

describe("following after the overview", () => {
  it("returns to the distance the person walked at, or to the default when that was no walking view", () => {
    expect(followDistanceAfterOverview(11)).toBe(11);
    expect(followDistanceAfterOverview(WALK_VIEW_MAX_M)).toBe(WALK_VIEW_MAX_M);
    expect(followDistanceAfterOverview(80)).toBe(FOLLOW_DISTANCE_M);
    expect(followDistanceAfterOverview(null)).toBe(FOLLOW_DISTANCE_M);
    expect(followDistanceAfterOverview(0.5)).toBe(CAMERA_LIMITS.minDistance);
  });
});

describe("a remembered view on a rebuilt floor", () => {
  const bounds = { minX: -20, maxX: 20, minZ: -20, maxZ: 20 };
  const wall = { minX: 4.94, maxX: 5.06, minZ: -10, maxZ: 10 };

  it("is kept as it is when it still fits", () => {
    const pose = { position: [10, 9, 10] as [number, number, number], target: [0, 0.8, 0] as [number, number, number] };
    expect(settleView(pose, bounds, [wall])).toBe(pose);
    // High above a wall is not inside it.
    const above = { position: [5, 6, 0] as [number, number, number], target: [0, 0.8, 0] as [number, number, number] };
    expect(settleView(above, bounds, [wall])).toBe(above);
  });

  it("is dropped when it looks at a place the floor no longer has", () => {
    expect(settleView({ position: [40, 9, 40], target: [30, 0.8, 30] }, bounds, [])).toBeNull();
  });

  it("backs a camera out of a wall along its line of sight", () => {
    const settled = settleView({ position: [5, 2, 0], target: [1, 0.8, 0] }, bounds, [wall])!;
    expect(settled.target).toEqual([1, 0.8, 0]);
    // Outside the wall and its margin, further from the target, on the same line.
    expect(settled.position[0]).toBeGreaterThan(5.06 + 0.35);
    expect(settled.position[0]).toBeLessThan(7);
    expect(settled.position[2]).toBeCloseTo(0);
    expect((settled.position[1] - 0.8) / (settled.position[0] - 1)).toBeCloseTo((2 - 0.8) / (5 - 1), 6);
  });
});
