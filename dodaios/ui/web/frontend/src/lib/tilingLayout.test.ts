import { describe, expect, it } from "vitest";

import { isSectionId } from "@/store/events";
import {
  clampRatio,
  dwindleDir,
  layoutLeaves,
  layoutSplits,
  leaf,
  leafForSection,
  leaves,
  parseTree,
  pickSections,
  PRESETS,
  removeLeaf,
  setRatio,
  split,
  splitLeaf,
  swapLeaves,
} from "@/lib/tilingLayout";

describe("tiling layout", () => {
  it("lays a 2x2 grid out in four equal quarters", () => {
    const grid = PRESETS.find((preset) => preset.id === "grid-4")!.build(["chats", "agents", "memory", "docs"]);
    const rects = layoutLeaves(grid).map(({ leaf: item, rect }) => [item.section, rect]);
    expect(rects).toEqual([
      ["chats", { x: 0, y: 0, w: 0.5, h: 0.5 }],
      ["agents", { x: 0.5, y: 0, w: 0.5, h: 0.5 }],
      ["memory", { x: 0, y: 0.5, w: 0.5, h: 0.5 }],
      ["docs", { x: 0.5, y: 0.5, w: 0.5, h: 0.5 }],
    ]);
    expect(layoutSplits(grid)).toHaveLength(3);
  });

  it("splits a leaf and collapses back when one side closes", () => {
    const start = leaf("chats");
    const { tree, added } = splitLeaf(start, start.id, "agents", "row");
    expect(leaves(tree).map((item) => item.section)).toEqual(["chats", "agents"]);
    const back = removeLeaf(tree, added.id);
    expect(back).toEqual(start);
    expect(removeLeaf(start, start.id)).toBeNull();
  });

  it("swaps sections while the tiles keep their places", () => {
    const tree = split("row", leaf("chats"), leaf("agents"));
    const [a, b] = leaves(tree);
    const swapped = swapLeaves(tree, a.id, b.id);
    expect(leaves(swapped).map((item) => item.section)).toEqual(["agents", "chats"]);
    expect(leaves(swapped).map((item) => item.id)).toEqual([a.id, b.id]);
  });

  it("clamps resizing so no tile collapses to nothing", () => {
    const tree = split("row", leaf("chats"), leaf("agents"));
    expect((setRatio(tree, tree.id, 0.01) as typeof tree).ratio).toBe(0.15);
    expect(clampRatio(Number.NaN)).toBe(0.5);
  });

  it("finds a hub's tile from any of its tabs", () => {
    const tree = split("row", leaf("clis"), leaf("agentic-ide"));
    expect(leafForSection(tree, "cli-test-hub")?.section).toBe("clis");
    expect(leafForSection(tree, "agentic-ide-classic")?.section).toBe("agentic-ide");
    expect(leafForSection(tree, "memory")).toBeUndefined();
  });

  it("fills new tiles with distinct sections and never a dialog section", () => {
    expect(pickSections(["agentic-ide-classic", "settings"], 3)).toEqual(["agentic-ide-classic", "agents", "chats"]);
  });

  it("splits along the longer side", () => {
    expect(dwindleDir({ x: 0, y: 0, w: 1, h: 1 }, 16 / 9)).toBe("row");
    expect(dwindleDir({ x: 0, y: 0, w: 0.3, h: 1 }, 16 / 9)).toBe("column");
  });

  it("restores a stored layout and rejects broken or duplicate ones", () => {
    const stored = { kind: "split", dir: "row", ratio: 0.4, a: { kind: "leaf", section: "chats" }, b: { kind: "leaf", section: "agents" } };
    const tree = parseTree(stored, isSectionId);
    expect(leaves(tree).map((item) => item.section)).toEqual(["chats", "agents"]);
    expect(parseTree({ ...stored, b: { kind: "leaf", section: "nope" } }, isSectionId)).toBeNull();
    expect(parseTree({ ...stored, b: { kind: "leaf", section: "chats" } }, isSectionId)).toBeNull();
    expect(parseTree({ ...stored, b: { kind: "leaf", section: "profile" } }, isSectionId)).toBeNull();
    expect(parseTree("garbage", isSectionId)).toBeNull();
  });
});
