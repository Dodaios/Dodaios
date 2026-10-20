import { describe, expect, it, vi } from "vitest";
import { syntheticDeck } from "../testing/syntheticDeck";
import { sniffImage } from "./imageFetch";
import { needsFullResolution, tileRect, tilesInRect } from "./tiles";
import { TileStreamer } from "./tileStreamer";

const deck = syntheticDeck();
const { plate, camera } = deck;

function bytes(...parts: (string | number[])[]): Uint8Array {
  const out: number[] = [];
  for (const p of parts) {
    if (typeof p === "string") for (const ch of p) out.push(ch.charCodeAt(0));
    else out.push(...p);
  }
  return new Uint8Array(out);
}

describe("image sniffing", () => {
  it("recognises AVIF, PNG, JPEG and WebP by their bytes", () => {
    expect(sniffImage(bytes([0, 0, 0, 28], "ftypavif", [0, 0, 0, 0], "mif1"))).toBe("image/avif");
    expect(sniffImage(bytes([0, 0, 0, 28], "ftypmif1", [0, 0, 0, 0], "miafavif"))).toBe("image/avif");
    expect(sniffImage(bytes([0x89], "PNG", [13, 10, 26, 10, 0, 0, 0, 13]))).toBe("image/png");
    expect(sniffImage(bytes([0xff, 0xd8, 0xff, 0xe0, 0, 0, 0, 0, 0, 0, 0, 0]))).toBe("image/jpeg");
    expect(sniffImage(bytes("RIFF", [0, 0, 0, 0], "WEBPVP8 "))).toBe("image/webp");
  });

  it("rejects the app's index.html and anything else", () => {
    expect(sniffImage(bytes("<!doctype html><html>"))).toBeNull();
    expect(sniffImage(bytes([0, 0, 0, 28], "ftypisom", [0, 0, 0, 0], "mp41"))).toBeNull();
    expect(sniffImage(new Uint8Array(4))).toBeNull();
  });
});

describe("tile geometry", () => {
  it("covers the plate exactly, edge tiles cut to the plate", () => {
    let area = 0;
    for (let r = 0; r < plate.rows; r++) for (let c = 0; c < plate.cols; c++) {
      const t = tileRect(plate, camera, c, r);
      area += t.w * t.h;
      expect(t.u1 - t.u0).toBeCloseTo(t.w / camera.pxPerMetre, 9);
    }
    expect(area).toBe(plate.width * plate.height);
    const first = tileRect(plate, camera, 0, 0);
    expect(first.u0).toBeCloseTo(-camera.frameW / 2, 9);
    expect(first.v1).toBeCloseTo(camera.frameH / 2, 9);
  });

  it("finds the tiles a view touches, nearest first, and grows by a ring", () => {
    const t = tileRect(plate, camera, 1, 0);
    const inside = { u0: t.u0 + 1, u1: t.u0 + 2, v0: t.v1 - 2, v1: t.v1 - 1 };
    expect(tilesInRect(plate, camera, inside)).toEqual([{ col: 1, row: 0, level: 0 }]);
    const ringed = tilesInRect(plate, camera, inside, 1);
    expect(ringed[0]).toEqual({ col: 1, row: 0, level: 0 });
    expect(ringed).toHaveLength(6);
    const all = tilesInRect(plate, camera, { u0: -1e3, u1: 1e3, v0: -1e3, v1: 1e3 });
    expect(all).toHaveLength(plate.cols * plate.rows);
  });

  it("streams L0 only once the overview would be magnified", () => {
    expect(needsFullResolution(plate, 0.2)).toBe(false);
    expect(needsFullResolution(plate, 0.25)).toBe(false);
    expect(needsFullResolution(plate, 0.5)).toBe(true);
  });
});

function fakeBitmap(): ImageBitmap {
  return { width: 4, height: 4, close: vi.fn() } as unknown as ImageBitmap;
}

describe("tile streamer", () => {
  it("loads wanted tiles a few at a time and hands them over for upload", async () => {
    const load = vi.fn(async () => fakeBitmap());
    const s = new TileStreamer(plate, camera, { load, maxInFlight: 2, maxResident: 6 });
    s.update([{ col: 0, row: 0 }, { col: 1, row: 0 }, { col: 2, row: 0 }], 0);
    expect(load).toHaveBeenCalledTimes(2);
    await Promise.resolve(); await Promise.resolve();
    expect(s.residentCount).toBe(2);
    const up = s.nextUpload();
    expect(up).not.toBeNull();
    up!.uploaded = true;
    expect(s.drawable([{ col: 0, row: 0 }, { col: 1, row: 0 }])).toHaveLength(1);
    s.update([{ col: 0, row: 0 }, { col: 1, row: 0 }, { col: 2, row: 0 }], 1);
    expect(load).toHaveBeenCalledTimes(3);
    s.dispose();
  });

  it("aborts loads that are no longer wanted", () => {
    const signals: AbortSignal[] = [];
    const load = vi.fn((_url: string, signal: AbortSignal) => { signals.push(signal); return new Promise<ImageBitmap>(() => undefined); });
    const s = new TileStreamer(plate, camera, { load });
    s.update([{ col: 0, row: 0 }], 0);
    s.update([{ col: 2, row: 1 }], 1);
    expect(signals[0].aborted).toBe(true);
    expect(s.inFlightCount).toBe(1);
    s.dispose();
    expect(signals[1].aborted).toBe(true);
  });

  it("keeps GPU memory bounded and frees idle tiles", async () => {
    const bitmaps: ImageBitmap[] = [];
    const load = vi.fn(async () => { const b = fakeBitmap(); bitmaps.push(b); return b; });
    const s = new TileStreamer(plate, camera, { load, maxResident: 2, maxInFlight: 4, idleMs: 1000 });
    s.update([{ col: 0, row: 0 }, { col: 1, row: 0 }], 0);
    await Promise.resolve(); await Promise.resolve();
    expect(s.residentCount).toBe(2);
    // New tiles wanted: the old ones go to make room.
    s.update([{ col: 2, row: 1 }], 10);
    expect(s.residentCount + s.inFlightCount).toBeLessThanOrEqual(2);
    await Promise.resolve(); await Promise.resolve();
    expect(s.residentCount).toBeLessThanOrEqual(2);
    // Nothing wanted for longer than idleMs: everything is freed.
    s.update([], 1e9);
    expect(s.residentCount).toBe(0);
    expect(bitmaps.every((b) => (b.close as ReturnType<typeof vi.fn>).mock.calls.length === 1)).toBe(true);
  });

  it("does not retry a failed tile at once", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const load = vi.fn(async () => { throw new Error("404"); });
    const s = new TileStreamer(plate, camera, { load, retryMs: 5000 });
    s.update([{ col: 0, row: 0 }], 0);
    await Promise.resolve(); await Promise.resolve();
    s.update([{ col: 0, row: 0 }], 1);
    expect(load).toHaveBeenCalledTimes(1);
    warn.mockRestore();
    s.dispose();
  });
});
