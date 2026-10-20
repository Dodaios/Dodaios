import { describe, expect, it } from "vitest";
import type { PlateCamera } from "./plateMath";
import { ViewController } from "./viewController";
import {
  clampView, damp, density, panBy, plateToScreen, scaleLimits, screenToPlate, settled, viewRect, zoomAt, MAX_DENSITY,
  type View, type Viewport,
} from "./view";

const cam: PlateCamera = { center: [0, 0, 0], pitchDeg: 60, frameW: 120, frameH: 50, pxPerMetre: 96 };
const wide: Viewport = { width: 1600, height: 900, dpr: 1 };
const tall: Viewport = { width: 380, height: 1100, dpr: 2 };

function covers(view: View, vp: Viewport): boolean {
  const r = viewRect(view, vp);
  const eps = 1e-9;
  return r.u0 >= -cam.frameW / 2 - eps && r.u1 <= cam.frameW / 2 + eps && r.v0 >= -cam.frameH / 2 - eps && r.v1 <= cam.frameH / 2 + eps;
}

describe("scale limits", () => {
  it("stops zoom-out where the plate covers the viewport", () => {
    const { min } = scaleLimits(cam, wide);
    expect(min).toBeCloseTo(Math.max(1600 / 120, 900 / 50), 10);
  });

  it("stops zoom-in at 1.25× native density in device pixels", () => {
    expect(scaleLimits(cam, wide).max).toBeCloseTo(MAX_DENSITY * 96, 10);
    expect(scaleLimits(cam, tall).max).toBeCloseTo((MAX_DENSITY * 96) / 2, 10);
  });

  it("lets coverage win when the plate is too small for the viewport", () => {
    const tiny: PlateCamera = { ...cam, frameW: 8, frameH: 4 };
    const { min, max } = scaleLimits(tiny, wide);
    expect(max).toBe(min);
  });
});

describe("clamping", () => {
  it("never shows anything outside the plate, at any zoom and pan, wide or tall", () => {
    for (const vp of [wide, tall]) {
      for (const scale of [0.1, 5, 18, 40, 200]) {
        for (const [cu, cv] of [[0, 0], [-500, 0], [500, 500], [59, -24], [-3, 1e6]]) {
          const v = clampView(cam, vp, { cu, cv, scale });
          expect(covers(v, vp), `${vp.width}x${vp.height} ${scale} ${cu},${cv}`).toBe(true);
          expect(density(cam, vp, v)).toBeLessThanOrEqual(MAX_DENSITY + 1e-9);
        }
      }
    }
  });

  it("keeps an in-bounds view as it is", () => {
    const v: View = { cu: 3, cv: -2, scale: 60 };
    expect(clampView(cam, wide, v)).toEqual(v);
  });
});

describe("screen ↔ plate", () => {
  it("round-trips", () => {
    const view: View = { cu: 7, cv: 3, scale: 50 };
    const p = screenToPlate(view, wide, 123, 456);
    const s = plateToScreen(view, wide, p.u, p.v);
    expect(s.x).toBeCloseTo(123, 9);
    expect(s.y).toBeCloseTo(456, 9);
  });

  it("puts the view centre in the middle of the screen, +v up", () => {
    const view: View = { cu: 7, cv: 3, scale: 50 };
    expect(plateToScreen(view, wide, 7, 3)).toEqual({ x: 800, y: 450 });
    expect(plateToScreen(view, wide, 7, 4).y).toBeCloseTo(400, 9);
  });

  it("zooms toward the cursor: the point under it stays put", () => {
    const view: View = { cu: 2, cv: -1, scale: 40 };
    const before = screenToPlate(view, wide, 300, 200);
    const after = zoomAt(view, wide, 300, 200, 1.7);
    const p = screenToPlate(after, wide, 300, 200);
    expect(p.u).toBeCloseTo(before.u, 10);
    expect(p.v).toBeCloseTo(before.v, 10);
    expect(after.scale).toBeCloseTo(68, 10);
  });

  it("pans with the drag: content follows the pointer", () => {
    const view: View = { cu: 0, cv: 0, scale: 50 };
    const grabbed = screenToPlate(view, wide, 500, 500);
    const moved = panBy(view, 30, -20);
    const now = plateToScreen(moved, wide, grabbed.u, grabbed.v);
    expect(now.x).toBeCloseTo(530, 9);
    expect(now.y).toBeCloseTo(480, 9);
  });
});

describe("damping", () => {
  it("closes half the gap per half-life and is frame-rate independent", () => {
    const a: View = { cu: 0, cv: 0, scale: 10 };
    const b: View = { cu: 10, cv: -10, scale: 40 };
    const half = damp(a, b, 0.2, 0.2);
    expect(half.cu).toBeCloseTo(5, 9);
    expect(half.scale).toBeCloseTo(20, 9);
    let stepped = a;
    for (let i = 0; i < 10; i++) stepped = damp(stepped, b, 0.02, 0.2);
    expect(stepped.cu).toBeCloseTo(5, 9);
  });

  it("jumps with no half-life (reduced motion) and reports settling", () => {
    const b: View = { cu: 1, cv: 2, scale: 30 };
    expect(damp({ cu: 0, cv: 0, scale: 10 }, b, 0.016, 0)).toEqual(b);
    expect(settled(b, b)).toBe(true);
    expect(settled({ ...b, cu: 1.1 }, b)).toBe(false);
  });
});

describe("third-person and bird's-eye camera", () => {
  function settle(v: ViewController) {
    for (let i = 0; i < 200; i++) v.step(0.05);
  }

  it("closes in on a figure: closer than the first framing, inside the plate's limits", () => {
    const v = new ViewController();
    v.setPlate(cam, { u: 0, v: 0 });
    v.resize(wide);
    const { min, max } = scaleLimits(cam, wide);
    const s = v.followScale();
    expect(s).toBeGreaterThan(Math.sqrt(min * max));
    expect(s).toBeLessThanOrEqual(max);
    expect(s).toBeGreaterThanOrEqual(min);
  });

  it("follows a moving point at the zoom it has, and never past the plate's edge", () => {
    const v = new ViewController();
    v.setPlate(cam, { u: 0, v: 0 });
    v.resize(wide);
    v.focus(0, 0, v.followScale());
    settle(v);
    const scale = v.current.scale;
    v.follow(12, -3);
    settle(v);
    expect(v.current.cu).toBeCloseTo(12, 6);
    expect(v.current.cv).toBeCloseTo(-3, 6);
    expect(v.current.scale).toBeCloseTo(scale, 6);
    v.follow(1000, 0);
    settle(v);
    expect(covers(v.current, wide)).toBe(true);
  });

  it("pulls all the way back for the bird's-eye view", () => {
    const v = new ViewController();
    v.setPlate(cam, { u: 0, v: 0 });
    v.resize(wide);
    v.focus(20, 5, v.followScale());
    settle(v);
    v.overview();
    settle(v);
    expect(v.current.scale).toBeCloseTo(scaleLimits(cam, wide).min, 6);
    expect(covers(v.current, wide)).toBe(true);
  });
});

describe("first framing", () => {
  it("frames a plate set before the viewport was measured on the first real size (regression: first open fully zoomed out)", () => {
    const v = new ViewController();
    v.setPlate(cam, { u: 10, v: 5 });
    v.resize(wide);
    const { min, max } = scaleLimits(cam, wide);
    expect(v.current.scale).toBeCloseTo(Math.sqrt(min * max), 6);
    expect(v.current.cu).toBeCloseTo(10, 6);
    // Later resizes only clamp; they do not re-frame.
    v.zoomAt(800, 450, 1.5);
    for (let i = 0; i < 100; i++) v.step(0.05);
    const zoomed = v.current.scale;
    v.resize({ ...wide, width: 1500 });
    expect(v.current.scale).toBeCloseTo(zoomed, 6);
  });
});
