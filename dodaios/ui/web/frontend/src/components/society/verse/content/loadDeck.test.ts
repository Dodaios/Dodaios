import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { deckFromManifest, DeckLoadError, navFromCodes, socketGroup } from "./loadDeck";

// The shipped bridge deck doubles as the fixture: real cook output, kept in the repo.
const BRIDGE = join(__dirname, "../../../../../public/verse/decks/bridge/manifest.json");

function bridge(): unknown {
  return JSON.parse(readFileSync(BRIDGE, "utf8"));
}

describe("deck loading", () => {
  it("turns a cooked deck into a runtime deck with absolute URLs", () => {
    const deck = deckFromManifest(bridge(), "/verse/decks/bridge/manifest.json", "bridge", "bridge");
    expect(deck.camera.pitchDeg).toBe(60);
    expect(deck.plate.overview.url).toBe("/verse/decks/bridge/plate/L1.avif");
    expect(deck.plate.tileUrl(1, 0)).toBe("/verse/decks/bridge/plate/L0_1_0.avif");
    expect(deck.occludersUrl).toBe("/verse/decks/bridge/occluders.glb");
    expect(deck.navUrl).toBe("/verse/decks/bridge/nav.png");
    // Every socket kept, yaw in radians, groups and orders from the id.
    const seat = deck.sockets.find((s) => s.kind === "seat" && s.id === "brief_1");
    expect(seat).toBeDefined();
    expect(seat!.yaw).toBeCloseTo(Math.PI, 9);
    expect(deck.stations.length).toBeGreaterThan(0);
  });

  it("reads a socket's group and order from kit and hand-placed ids", () => {
    expect(socketGroup("brief__01")).toEqual({ group: "brief", order: 1 });
    expect(socketGroup("pit_p__table__12")).toEqual({ group: "pit_p__table", order: 12 });
    expect(socketGroup("pit_p_3")).toEqual({ group: "pit_p", order: 3 });
    expect(socketGroup("console_a")).toEqual({ group: "console_a", order: 0 });
    expect(socketGroup("mess__corner")).toEqual({ group: "mess", order: 0 });
  });

  it("names the bad field of a broken manifest", () => {
    const broken = bridge() as Record<string, unknown>;
    delete (broken.camera as Record<string, unknown>).px_per_m;
    expect(() => deckFromManifest(broken, "/m.json", "bridge", "bridge")).toThrow(DeckLoadError);
    expect(() => deckFromManifest(broken, "/m.json", "bridge", "bridge")).toThrow(/px_per_m/);
  });

  it("reads walkable cells and floor heights from the nav grey values", () => {
    const meta = { url: "", origin_x: -1, origin_z: -2, cell: 0.2, w: 3, h: 1, height_zero: 128, height_step: 0.025, max_step: 0.3, clearance: 0.25, walkable_cells: 2 };
    // RGBA pixels: blocked, deck level, 1.4 m down.
    const rgba = new Uint8Array([0, 0, 0, 255, 128, 128, 128, 255, 72, 72, 72, 255]);
    const nav = navFromCodes(rgba, 4, meta);
    expect([...nav.walkable]).toEqual([0, 1, 1]);
    expect(nav.heights[1]).toBe(0);
    expect(nav.heights[2]).toBeCloseTo(-1.4, 6);
    expect(nav).toMatchObject({ x0: -1, z0: -2, cols: 3, rows: 1, maxStep: 0.3 });
  });
});

describe("plate levels", () => {
  function withMips(): Record<string, Record<string, unknown>> {
    const m = bridge() as Record<string, Record<string, unknown>>;
    const w = 14016;
    const h = 8096;
    m.camera = { ...m.camera, px_per_m: 192, plate_w_px: w, plate_h_px: h };
    m.plate = {
      format: "avif", tile_px: 2048, cols: 7, rows: 4, tile_url: "plate/L0_{col}_{row}.avif",
      // Listed coarsest first on purpose: the runtime orders them itself.
      mips: [
        { divisor: 4, w_px: 3504, h_px: 2024, cols: 2, rows: 1, tile_url: "plate/M4_{col}_{row}.avif" },
        { divisor: 2, w_px: 7008, h_px: 4048, cols: 4, rows: 2, tile_url: "plate/M2_{col}_{row}.avif" },
      ],
      l1_url: "plate/L1.avif", l1_w_px: 1752, l1_h_px: 1012,
    };
    return m;
  }

  it("has just L0 for a deck cooked without mips", () => {
    const old = bridge() as Record<string, Record<string, unknown>>;
    delete old.plate.mips;
    const deck = deckFromManifest(old, "/verse/decks/bridge/manifest.json", "bridge", "bridge");
    expect(deck.plate.levels).toHaveLength(1);
    expect(deck.plate.levels[0]).toMatchObject({ divisor: 1, width: deck.plate.width, height: deck.plate.height, cols: deck.plate.cols, rows: deck.plate.rows });
    expect(deck.plate.levels[0].tileUrl(1, 0)).toBe("/verse/decks/bridge/plate/L0_1_0.avif");
  });

  it("orders L0 and the mips finest first, with their own tile URLs", () => {
    const deck = deckFromManifest(withMips(), "/verse/decks/bridge/manifest.json", "bridge", "bridge");
    expect(deck.camera.pxPerMetre).toBe(192);
    expect(deck.plate.levels.map((l) => [l.divisor, l.width, l.cols, l.rows])).toEqual([[1, 14016, 7, 4], [2, 7008, 4, 2], [4, 3504, 2, 1]]);
    expect(deck.plate.levels[1].tileUrl(3, 1)).toBe("/verse/decks/bridge/plate/M2_3_1.avif");
    expect(deck.plate.levels[2].tileUrl(1, 0)).toBe("/verse/decks/bridge/plate/M4_1_0.avif");
    expect(deck.plate.overview).toEqual({ url: "/verse/decks/bridge/plate/L1.avif", width: 1752, height: 1012 });
  });

  it("drops a mip no finer than the overview (the overview covers it)", () => {
    const m = withMips();
    (m.plate.mips as unknown[]).push({ divisor: 8, w_px: 1752, h_px: 1012, cols: 1, rows: 1, tile_url: "plate/M8_{col}_{row}.avif" });
    const deck = deckFromManifest(m, "/m.json", "bridge", "bridge");
    expect(deck.plate.levels.map((l) => l.divisor)).toEqual([1, 2, 4]);
  });
});
