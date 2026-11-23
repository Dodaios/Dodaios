import { Box3 } from "three";
import { describe, expect, it } from "vitest";

import { agentLogoAsset } from "@/components/agentic/AgentMark";

import { buildMascot, buildPlainMascot, MASCOT_HEIGHT_M, type MascotSolid } from "./mascotGeometry";
import { MASCOT_SPECS, mascotSpecFor } from "./mascotSpecs";

/** Every coding agent the app ships a mark for. */
const AGENTS = ["antigravity", "claude", "codex", "cursor", "deepseek-harness", "glm", "grok-build", "kimi", "opencode"];

function boundsOf(solid: MascotSolid): Box3 {
  const box = new Box3();
  for (const part of solid.parts) {
    part.geometry.computeBoundingBox();
    box.union(part.geometry.boundingBox!);
  }
  return box;
}

describe("mascot specs", () => {
  it("has a figure for every agent with a shipped mark, and for no other", () => {
    expect(Object.keys(MASCOT_SPECS).sort()).toEqual([...AGENTS].sort());
    for (const agent of AGENTS) expect(agentLogoAsset(agent)).not.toBeNull();
    expect(mascotSpecFor("my-own-cli")).toBeNull();
    expect(mascotSpecFor("")).toBeNull();
  });

  it("paints a single-colour glyph in the theme's ink and a colour mark in its own colours", () => {
    for (const agent of AGENTS) {
      const ground = agentLogoAsset(agent)!.ground;
      expect(MASCOT_SPECS[agent].paint === "ink").toBe(ground === "ink");
    }
  });
});

describe("buildMascot", () => {
  it.each(AGENTS)("stands the %s mark on the floor, centred, at the figure's height", (agent) => {
    const solid = buildMascot(MASCOT_SPECS[agent]);
    expect(solid.parts.length).toBeGreaterThan(0);
    const box = boundsOf(solid);
    expect(box.min.y).toBeCloseTo(0, 5);
    expect(box.max.y).toBeLessThanOrEqual(MASCOT_HEIGHT_M + 1e-6);
    expect(box.max.y).toBeGreaterThan(MASCOT_HEIGHT_M * 0.5);
    expect(box.min.x + box.max.x).toBeCloseTo(0, 5);
    // It has depth: a solid, not a decal.
    expect(box.max.z - box.min.z).toBeGreaterThan(0.1);
    expect(solid.widthM).toBeCloseTo(box.max.x - box.min.x, 5);
    for (const part of solid.parts) {
      expect(part.geometry.getAttribute("position").count).toBeGreaterThan(0);
      expect(part.geometry.getAttribute("uv").count).toBe(part.geometry.getAttribute("position").count);
    }
  });

  it("builds the Claude Code mascot from the mark's one path, in its own colour, with both eyes", () => {
    const solid = buildMascot(MASCOT_SPECS.claude);
    const body = solid.parts.filter((part) => !part.eye);
    const eyes = solid.parts.filter((part) => part.eye);
    expect(body).toHaveLength(1);
    expect(body[0].fill?.toLowerCase()).toBe("#d97757");
    expect(eyes).toHaveLength(2);
    // The mascot is wider than tall, and its eyes sit inside the body, left and right of the middle.
    const box = boundsOf({ ...solid, parts: body });
    expect(box.max.x - box.min.x).toBeGreaterThan(box.max.y - box.min.y);
    const centres = eyes.map((eye) => {
      eye.geometry.computeBoundingBox();
      const bounds = eye.geometry.boundingBox!;
      expect(bounds.min.y).toBeGreaterThan(box.min.y);
      expect(bounds.max.y).toBeLessThan(box.max.y);
      // Set back: the pane does not reach the body's faces.
      expect(bounds.max.z).toBeLessThan(box.max.z);
      return (bounds.min.x + bounds.max.x) / 2;
    });
    expect(Math.min(...centres)).toBeLessThan(0);
    expect(Math.max(...centres)).toBeGreaterThan(0);
  });

  it("stands the Codex glyph out of its tile on both faces", () => {
    const [tile, glyph] = buildMascot(MASCOT_SPECS.codex).parts;
    tile.geometry.computeBoundingBox();
    glyph.geometry.computeBoundingBox();
    expect(glyph.geometry.boundingBox!.max.z).toBeGreaterThan(tile.geometry.boundingBox!.max.z);
    expect(glyph.geometry.boundingBox!.min.z).toBeLessThan(tile.geometry.boundingBox!.min.z);
    expect(glyph.geometry.boundingBox!.max.x).toBeLessThan(tile.geometry.boundingBox!.max.x);
  });

  it("takes only the arch of the Antigravity mark, not the colour fields behind its mask", () => {
    const solid = buildMascot(MASCOT_SPECS.antigravity);
    expect(solid.parts).toHaveLength(1);
    expect(solid.widthM).toBeLessThanOrEqual(MASCOT_HEIGHT_M + 1e-6);
  });

  it("gives an agent without a mark a plain block that stands on the floor", () => {
    const box = boundsOf(buildPlainMascot());
    expect(box.min.y).toBeCloseTo(0, 5);
    expect(box.max.y).toBeLessThan(MASCOT_HEIGHT_M);
  });
});
