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
