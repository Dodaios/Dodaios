import { describe, expect, it } from "vitest";
import {
  columnCount,
  insertBeside,
  leaf,
  leaves,
  normalize,
  parseLayout,
  placeLayout,
  prune,
  removeLeaf,
  resizeAt,
  zoneAt,
  type LayoutNode,
} from "./sidePanelLayout";

const tabsOf = (node: LayoutNode | null) => leaves(node).map((entry) => entry.tab);
const isTab = (value: unknown): value is string => typeof value === "string";

describe("side panel layout", () => {
  it("splits a pane and shares the slot with a sibling in the same direction", () => {
    const a = leaf("a", "A");
    let tree: LayoutNode = insertBeside(a, "A", "b", "right", leaf("b", "B"));
    expect(tree).toMatchObject({ kind: "split", direction: "row", sizes: [0.5, 0.5] });
    tree = insertBeside(tree, "B", "c", "right", leaf("c", "C"));
    // Flat: three panes in one row, C taking half of B's slot.
    expect(tree).toMatchObject({ kind: "split", direction: "row", sizes: [0.5, 0.25, 0.25] });
    expect(tabsOf(tree)).toEqual(["a", "b", "c"]);
    tree = insertBeside(tree, "A", "d", "top", leaf("d", "D"));
    expect(tabsOf(tree)).toEqual(["d", "a", "b", "c"]);
    expect(columnCount(tree)).toBe(3);
  });

  it("closes up when a pane goes and drops the split at one pane", () => {
    let tree: LayoutNode | null = insertBeside(insertBeside(leaf("a", "A"), "A", "b", "right", leaf("b", "B")), "B", "c", "bottom", leaf("c", "C"));
    tree = removeLeaf(tree, "C");
    expect(tree).toMatchObject({ kind: "split", direction: "row" });
    expect(tabsOf(tree)).toEqual(["a", "b"]);
    tree = removeLeaf(tree, "A");
    expect(tree).toMatchObject({ kind: "leaf", tab: "b" });
  });

  it("flattens a split nested in one of the same direction", () => {
    const inner: LayoutNode = { kind: "split", id: "i", direction: "row", children: [leaf("b", "B"), leaf("c", "C")], sizes: [0.5, 0.5] };
    const outer: LayoutNode = { kind: "split", id: "o", direction: "row", children: [leaf("a", "A"), inner], sizes: [0.5, 0.5] };
    expect(normalize(outer)).toMatchObject({ children: [{ id: "A" }, { id: "B" }, { id: "C" }], sizes: [0.5, 0.25, 0.25] });
  });

  it("moves a divider between two panes only, within limits", () => {
    const tree = insertBeside(insertBeside(leaf("a", "A"), "A", "b", "right", leaf("b", "B")), "B", "c", "right", leaf("c", "C"));
    const id = (tree as { id: string }).id;
    const moved = resizeAt(tree, id, 1, 0.8);
    expect((moved as { sizes: number[] }).sizes.map((size) => Math.round(size * 100))).toEqual([50, 30, 20]);
    const clamped = resizeAt(tree, id, 0, 0);
    expect((clamped as { sizes: number[] }).sizes[0]).toBeCloseTo(0.1);
  });

  it("places panes and dividers in shares of the area", () => {
    const tree = insertBeside(insertBeside(leaf("a", "A"), "A", "b", "right", leaf("b", "B")), "B", "c", "bottom", leaf("c", "C"));
    const { leaves: placed, dividers } = placeLayout(tree);
    expect(placed.map(({ leaf: entry, rect }) => [entry.tab, rect])).toEqual([
      ["a", { x: 0, y: 0, w: 0.5, h: 1 }],
      ["b", { x: 0.5, y: 0, w: 0.5, h: 0.5 }],
      ["c", { x: 0.5, y: 0.5, w: 0.5, h: 0.5 }],
    ]);
    expect(dividers.map((divider) => [divider.direction, divider.at])).toEqual([["row", 0.5], ["column", 0.5]]);
  });

  it("reads the drop zone from the pointer's place in a pane", () => {
    expect(zoneAt(0.5, 0.5, true)).toBe("center");
    expect(zoneAt(0.05, 0.5, true)).toBe("left");
    expect(zoneAt(0.95, 0.4, true)).toBe("right");
    expect(zoneAt(0.5, 0.1, true)).toBe("top");
    expect(zoneAt(0.4, 0.9, true)).toBe("bottom");
    expect(zoneAt(0.05, 0.5, false)).toBe("center");
  });

  it("drops stored layouts that are malformed, and panes of closed or repeated tabs", () => {
    expect(parseLayout({ kind: "split", id: "x", direction: "diagonal", children: [], sizes: [] }, isTab)).toBeNull();
    expect(parseLayout("nope", isTab)).toBeNull();
    const stored = { kind: "split", id: "s", direction: "row", sizes: [1, 1, 1], children: [
      { kind: "leaf", id: "A", tab: "a" }, { kind: "leaf", id: "B", tab: "b" }, { kind: "leaf", id: "C", tab: 7 },
    ] };
    const parsed = parseLayout(stored, isTab);
    expect(tabsOf(parsed)).toEqual(["a", "b"]);
    expect(tabsOf(prune(parsed, (tab) => tab !== "b"))).toEqual(["a"]);
    const twice = { kind: "split", id: "s", direction: "row", sizes: [1, 1], children: [
      { kind: "leaf", id: "A", tab: "a" }, { kind: "leaf", id: "B", tab: "a" },
    ] };
    expect(tabsOf(prune(parseLayout(twice, isTab), () => true))).toEqual(["a"]);
  });
});
