import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { ManifestError, navHeight, parseDeckManifest, tileUrl, worldToPlatePx, type ManifestCamera } from "./manifest";

const DECKS = resolve(__dirname, "../../../../../public/verse/decks");
const BRIDGE = resolve(DECKS, "bridge/manifest.json");

const camera: ManifestCamera = {
  pitch_deg: 60,
  yaw_deg: 0,
  px_per_m: 96,
  centre: [0, 0, -1],
  right: [1, 0, 0],
  up: [0, 0.5, -Math.sqrt(3) / 2],
  forward: [0, -Math.sqrt(3) / 2, -0.5],
  distance: 250,
  frame_w_m: 20,
  frame_h_m: 10,
  plate_w_px: 1920,
  plate_h_px: 960,
  view_transform: "AgX",
  look: "None",
  exposure: 0,
};

describe("worldToPlatePx", () => {
  it("maps the plate centre to the middle pixel", () => {
    expect(worldToPlatePx(camera, [0, 0, -1])).toEqual({ x: 960, y: 480 });
  });

  it("moves right with +X and up the plate with height and with −Z", () => {
    expect(worldToPlatePx(camera, [1, 0, -1]).x).toBeCloseTo(1056);
    expect(worldToPlatePx(camera, [0, 2, -1]).y).toBeCloseTo(480 - 96);
    expect(worldToPlatePx(camera, [0, 0, -3]).y).toBeCloseTo(480 - 2 * (Math.sqrt(3) / 2) * 96);
  });
});

describe("helpers", () => {
  it("decodes nav heights", () => {
    const nav = { height_zero: 128, height_step: 0.025 } as Parameters<typeof navHeight>[0];
    expect(navHeight(nav, 0)).toBeNull();
    expect(navHeight(nav, 128)).toBe(0);
    expect(navHeight(nav, 152)).toBeCloseTo(0.6);
  });

  it("fills the tile pattern", () => {
    const plate = { tile_url: "plate/L0_{col}_{row}.avif" } as Parameters<typeof tileUrl>[0];
    expect(tileUrl(plate, 2, 1)).toBe("plate/L0_2_1.avif");
  });
});

describe("parseDeckManifest", () => {
  it("rejects a wrong schema with a field path", () => {
    expect(() => parseDeckManifest({ schema: "verse.deck/0" })).toThrow(ManifestError);
  });

  it.runIf(existsSync(BRIDGE))("accepts a cooked deck and keeps its sockets on the plate", () => {
    const manifest = parseDeckManifest(JSON.parse(readFileSync(BRIDGE, "utf8")));
    for (const socket of manifest.sockets) {
      const { x, y } = worldToPlatePx(manifest.camera, socket.position);
      expect(x).toBeGreaterThanOrEqual(0);
      expect(x).toBeLessThanOrEqual(manifest.camera.plate_w_px);
      expect(y).toBeGreaterThanOrEqual(0);
      expect(y).toBeLessThanOrEqual(manifest.camera.plate_h_px);
    }
    const screen = manifest.sockets.find((s) => s.kind === "screen");
    expect(screen?.corners).toHaveLength(4);
  });
});
