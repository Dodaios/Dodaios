import { describe, expect, it, vi } from "vitest";
import type { Mesh, WebGLRenderer } from "three";
import type { Deck } from "../content/deck";
import { syntheticDeck, syntheticPlate } from "../testing/syntheticDeck";
import { PlateLayer } from "./plateLayer";
import { RENDER_ORDER } from "./renderOrder";
import { OVERVIEW_LEVEL, OVERVIEW_MAGNIFY_LIMIT, plateLevelFor, tileRange, tileRect, tilesInRect } from "./tiles";
import { TileStreamer } from "./tileStreamer";
import type { View, Viewport } from "./view";

// Every image the plate layer fetches waits here until the test delivers it.
const loads = vi.hoisted(() => new Map<string, (bitmap: ImageBitmap) => void>());
vi.mock("./imageFetch", () => ({
  fetchImageBitmap: (url: string, signal?: AbortSignal) => new Promise<ImageBitmap>((resolve, reject) => {
    loads.set(url, resolve);
    signal?.addEventListener("abort", () => { loads.delete(url); reject(new DOMException("aborted", "AbortError")); });
  }),
}));

const base = syntheticDeck();
const cam = { ...base.camera, pxPerMetre: 192 };
/** The close-up layout: L0 at 192 px/m, M2, M4, the overview at 1/8. */
const plate = syntheticPlate(192, true);
/** An older deck: 96 px/m, L0 only, the overview at 1/4. */
const oldPlate = syntheticPlate(96, false);

function fakeBitmap(): ImageBitmap {
  return { width: 4, height: 4, close: vi.fn() } as unknown as ImageBitmap;
}

const flush = async () => { for (let i = 0; i < 4; i++) await Promise.resolve(); };

describe("plate levels", () => {
  it("lays out the close-up plate as L0, M2 and M4 with the overview at 1/8", () => {
    expect(plate.levels.map((l) => [l.divisor, l.cols, l.rows])).toEqual([[1, 5, 3], [2, 3, 2], [4, 2, 1]]);
    expect(plate.overview.width).toBe(1152);
  });

  it("picks the coarsest image that is still sharp: overview, then M4, M2, L0", () => {
    expect(plateLevelFor(plate, 0.1)).toBe(OVERVIEW_LEVEL);
    expect(plateLevelFor(plate, OVERVIEW_MAGNIFY_LIMIT / 8)).toBe(OVERVIEW_LEVEL);
    expect(plateLevelFor(plate, 0.2)).toBe(2);
    expect(plateLevelFor(plate, OVERVIEW_MAGNIFY_LIMIT / 4)).toBe(2);
    expect(plateLevelFor(plate, 0.3)).toBe(1);
    expect(plateLevelFor(plate, 0.5)).toBe(1);
    expect(plateLevelFor(plate, 0.6)).toBe(0);
    // The close follow camera on a 2560 px window: about 205 px/m on a 192 px/m plate.
    expect(plateLevelFor(plate, 204.8 / 192)).toBe(0);
    expect(plateLevelFor(plate, 1.25)).toBe(0);
  });

  it("never magnifies the chosen image past the limit while a finer one exists, and never picks a finer one than needed", () => {
    const scale = (level: number) => (level === OVERVIEW_LEVEL ? plate.width / plate.overview.width : plate.width / plate.levels[level].width);
    const order = [OVERVIEW_LEVEL, 2, 1, 0];
    for (let d = 0.02; d <= 1.25; d += 0.01) {
      const level = plateLevelFor(plate, d);
      if (level !== 0) expect(d * scale(level)).toBeLessThanOrEqual(OVERVIEW_MAGNIFY_LIMIT);
      const coarser = order[order.indexOf(level) - 1];
      if (coarser !== undefined) expect(d * scale(coarser)).toBeGreaterThan(OVERVIEW_MAGNIFY_LIMIT);
    }
  });

  it("keeps the old rule for a deck without mips: the overview until it is magnified, then L0", () => {
    expect(oldPlate.levels).toHaveLength(1);
    expect(plateLevelFor(oldPlate, 0.25)).toBe(OVERVIEW_LEVEL);
    expect(plateLevelFor(oldPlate, 0.3)).toBe(0);
    expect(plateLevelFor(oldPlate, 0.6)).toBe(0);
  });

  it("puts every mip tile exactly over the L0 tiles it was made from, edge tiles to the plate's edge", () => {
    for (let level = 1; level < plate.levels.length; level++) {
      const lv = plate.levels[level];
      const d = lv.divisor;
      let area = 0;
      for (let r = 0; r < lv.rows; r++) for (let c = 0; c < lv.cols; c++) {
        const t = tileRect(plate, cam, c, r, level);
        area += (t.u1 - t.u0) * (t.v1 - t.v0);
        expect(t.u0).toBeCloseTo(tileRect(plate, cam, c * d, 0).u0, 9);
        expect(t.v1).toBeCloseTo(tileRect(plate, cam, 0, r * d).v1, 9);
      }
      expect(area).toBeCloseTo((plate.width / 192) * (plate.height / 192), 6);
      expect(tileRect(plate, cam, lv.cols - 1, 0, level).u1).toBeCloseTo(cam.frameW / 2, 9);
    }
  });

  it("finds a level's tiles under a view, nearest first, with its level", () => {
    const rect = { u0: 17, u1: 20, v0: -1, v1: 1 };
    expect(tilesInRect(plate, cam, rect, 0, 2)).toEqual([{ col: 0, row: 0, level: 2 }, { col: 1, row: 0, level: 2 }]);
    const r = tileRange(plate, cam, rect, 1, 1);
    expect([r.c0, r.c1, r.r0, r.r1]).toEqual([0, 2, 0, 1]);
  });
});

describe("tile streamer across levels", () => {
  it("loads each level from its own tiles", async () => {
    const urls: string[] = [];
    const s = new TileStreamer(plate, cam, { load: async (url) => { urls.push(url); return fakeBitmap(); } });
    s.update([{ col: 1, row: 0, level: 1 }, { col: 1, row: 0, level: 2 }, { col: 1, row: 0 }], 0);
    await flush();
    expect(urls).toEqual(["/synthetic/M2_1_0.avif", "/synthetic/M4_1_0.avif", "/synthetic/L0_1_0.avif"]);
    expect(s.tileAt(1, 1, 0)?.level).toBe(1);
    expect(s.tileAt(2, 1, 0)?.rect.u1).toBeCloseTo(cam.frameW / 2, 9);
    expect(s.tileAt(0, 1, 0)).toBeDefined();
    expect(s.tileAt(0, 2, 0)).toBeUndefined();
    s.dispose();
  });

  it("lets a needed tile push out a prefetched one, never the other way round", async () => {
    const bitmaps = new Map<string, ImageBitmap>();
    const load = vi.fn(async (url: string) => { const b = fakeBitmap(); bitmaps.set(url, b); return b; });
    const s = new TileStreamer(plate, cam, { load, maxResident: 3, maxInFlight: 4 });
    const [a, b, c, d, e] = [0, 1, 2, 3, 4].map((col) => ({ col, row: 0 }));
    s.update([a, b, c], 0, 1);
    await flush();
    expect(s.residentCount).toBe(3);
    // d is needed now: the least wanted prefetched tile (c) makes room.
    s.update([a, d, b, c], 1, 2);
    await flush();
    expect(bitmaps.get("/synthetic/L0_2_0.avif")!.close).toHaveBeenCalled();
    expect(s.tileAt(0, 3, 0)).toBeDefined();
    // e is only prefetch: with no unwanted tile to replace it waits.
    s.update([a, d, b, e], 2, 2);
    await flush();
    expect(load).not.toHaveBeenCalledWith("/synthetic/L0_4_0.avif", expect.anything());
    expect(s.residentCount).toBe(3);
    s.dispose();
  });

  it("gives a needed tile the slot of a prefetch on its way", () => {
    const signals = new Map<string, AbortSignal>();
    const s = new TileStreamer(plate, cam, {
      load: (url, signal) => { signals.set(url, signal); return new Promise<ImageBitmap>(() => undefined); },
      maxInFlight: 1,
    });
    s.update([{ col: 4, row: 2 }], 0, 0);
    s.update([{ col: 0, row: 0 }, { col: 4, row: 2 }], 1, 1);
    expect(signals.get("/synthetic/L0_4_2.avif")?.aborted).toBe(true);
    expect(signals.has("/synthetic/L0_0_0.avif")).toBe(true);
    expect(s.inFlightCount).toBe(1);
    s.dispose();
  });

  it("never lets a kept fallback go, and fits what the view needs past the budget", async () => {
    const s = new TileStreamer(plate, cam, { load: async () => fakeBitmap(), maxResident: 2, maxInFlight: 4 });
    s.update([{ col: 0, row: 0, level: 1 }], 0);
    await flush();
    const keep = new Set([s.keyFor(1, 0, 0)]);
    s.update([{ col: 0, row: 0 }, { col: 1, row: 0 }], 1, 2, keep);
    expect(s.inFlightCount).toBe(2);
    await flush();
    expect(s.residentCount).toBe(3);
    expect(s.tileAt(1, 0, 0)).toBeDefined();
    // Nothing kept or wanted any more for longer than the idle time: everything goes.
    s.update([], 1e9);
    expect(s.residentCount).toBe(0);
    s.dispose();
  });
});

// ------------------------------------------------------------------ the plate layer

const gl = { initTexture: vi.fn() } as unknown as WebGLRenderer;
const vp: Viewport = { width: 1280, height: 720, dpr: 1 };
const at = (scale: number): View => ({ cu: 0, cv: 0, scale });

async function openLayer(deck: Deck): Promise<PlateLayer> {
  loads.clear();
  const layer = new PlateLayer(deck);
  const ready = layer.load();
  loads.get(deck.plate.overview.url)!(fakeBitmap());
  loads.delete(deck.plate.overview.url);
  await ready;
  return layer;
}

/** Deliver every pending tile and run frames until the layer has uploaded them all. */
async function settle(layer: PlateLayer, view: View, revision: number): Promise<void> {
  for (let frame = 0; frame < 60; frame++) {
    for (const [url, resolve] of [...loads]) { loads.delete(url); resolve(fakeBitmap()); }
    await flush();
    layer.update(view, vp, revision, gl, frame);
  }
}

/** Visible tile meshes by level (render order: L0 on top). */
function shown(layer: PlateLayer): Map<number, number> {
  const out = new Map<number, number>();
  const levels = (layer as unknown as { ranges: unknown[] }).ranges.length;
  for (const child of layer.group.children as Mesh[]) {
    if (!child.visible || child.renderOrder === RENDER_ORDER.plate) continue;
    const level = levels - 1 - (child.renderOrder - RENDER_ORDER.plateTile);
    out.set(level, (out.get(level) ?? 0) + 1);
  }
  return out;
}

describe("plate layer", () => {
  const deck: Deck = { ...base, camera: cam, plate };

  it("keeps the coarser level drawn while the finer one loads, then draws the finer one alone", async () => {
    const layer = await openLayer(deck);
    // 76.8 px/m: density 0.4, M2.
    layer.update(at(76.8), vp, 1, gl, 0);
    expect(layer.level).toBe(1);
    expect([...loads.keys()].every((url) => url.includes("/M2_"))).toBe(true);
    await settle(layer, at(76.8), 1);
    expect(shown(layer)).toEqual(new Map([[1, 2]]));
    // The follow camera closes in: L0 is wanted, M2 stays on screen until it is there.
    layer.update(at(192), vp, 2, gl, 100);
    expect(layer.level).toBe(0);
    expect(shown(layer).get(1)).toBe(2);
    expect([...loads.keys()].some((url) => url.includes("/L0_"))).toBe(true);
    await settle(layer, at(192), 2);
    // 1280 × 720 L0 pixels around the plate centre touch four L0 tiles; the prefetch ring is not drawn.
    expect(shown(layer)).toEqual(new Map([[0, 4]]));
    layer.dispose();
  });

  it("keeps the finer level drawn while zooming out to a coarser one", async () => {
    const layer = await openLayer(deck);
    layer.update(at(192), vp, 1, gl, 0);
    await settle(layer, at(192), 1);
    expect(shown(layer)).toEqual(new Map([[0, 4]]));
    // 38.4 px/m: density 0.2, M4. Before M4 arrives the L0 tiles stay.
    layer.update(at(38.4), vp, 2, gl, 100);
    expect(layer.level).toBe(2);
    expect(shown(layer).get(0)).toBeGreaterThanOrEqual(4);
    await settle(layer, at(38.4), 2);
    expect(shown(layer)).toEqual(new Map([[2, 1]]));
    // Bird's-eye: the overview alone.
    layer.update(at(20), vp, 3, gl, 200);
    expect(layer.level).toBe(OVERVIEW_LEVEL);
    expect(shown(layer).size).toBe(0);
    layer.dispose();
  });

  it("streams an older deck exactly as before: the overview, then L0 tiles", async () => {
    const old: Deck = { ...base, plate: oldPlate };
    const layer = await openLayer(old);
    layer.update(at(20), vp, 1, gl, 0);
    expect(layer.level).toBe(OVERVIEW_LEVEL);
    expect(loads.size).toBe(0);
    layer.update(at(96), vp, 2, gl, 10);
    expect(layer.level).toBe(0);
    expect([...loads.keys()].every((url) => url.includes("/L0_"))).toBe(true);
    await settle(layer, at(96), 2);
    expect([...shown(layer).keys()]).toEqual([0]);
    layer.dispose();
  });

  it("gives every tile back when trimmed and asks again on the next frame", async () => {
    const layer = await openLayer(deck);
    layer.update(at(192), vp, 1, gl, 0);
    await settle(layer, at(192), 1);
    expect(layer.resident).toBeGreaterThan(0);
    layer.trim();
    expect(layer.resident).toBe(0);
    expect(shown(layer).size).toBe(0);
    layer.update(at(192), vp, 1, gl, 1000);
    expect(layer.inFlight).toBeGreaterThan(0);
    layer.dispose();
  });
});
