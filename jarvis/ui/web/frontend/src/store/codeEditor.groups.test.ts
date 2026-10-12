import { beforeEach, describe, expect, it } from "vitest";

import { fileKeyOf, groupsOf, tabKeyOf, useCodeEditorStore } from "./codeEditor";

const store = () => useCodeEditorStore.getState();
const edit = (path: string, group = 0) => tabKeyOf("edit", fileKeyOf("w1", path), group);
/** Each group's tabs, left to right, the shown one in brackets, the focused group starred. */
const layout = () =>
  groupsOf(store(), "w1").map(
    (group) => `${group.focused ? "*" : ""}${group.tabs.map((tab) => (tab.key === group.active?.key ? `[${tab.path}]` : tab.path)).join(" ")}`,
  );

beforeEach(() => {
  useCodeEditorStore.setState({
    tabs: [],
    active: {},
    files: {},
    visible: false,
    quickOpen: false,
    cursor: null,
    reveal: null,
    closed: [],
    groupOrder: {},
    groupActive: {},
    focusedGroup: {},
  });
});

describe("editor groups side by side", () => {
  it("starts as one empty group", () => {
    expect(layout()).toEqual(["*"]);
    expect(store().active.w1 ?? null).toBeNull();
  });

  it("opens a file in a new group to the right and hands it the keyboard", () => {
    store().openFile("w1", "a.ts", { preview: false });
    store().openToSide("w1", "b.ts");
    expect(layout()).toEqual(["[a.ts]", "*[b.ts]"]);
    expect(store().active.w1).toBe(edit("b.ts", 1));
    expect(store().tabs.find((tab) => tab.path === "b.ts")?.preview).toBe(false);
  });

  it("simply opens the file when nothing is open yet", () => {
    store().openToSide("w1", "a.ts");
    expect(layout()).toEqual(["*[a.ts]"]);
  });

  it("shows the same file in two groups as two tabs", () => {
    store().openFile("w1", "a.ts", { preview: false });
    store().openToSide("w1", "a.ts");
    expect(layout()).toEqual(["[a.ts]", "*[a.ts]"]);
    expect(store().tabs).toHaveLength(2);
    expect(Object.keys(store().files)).toHaveLength(1);
  });

  it("opens to the side into the group on the right when there is one, else adds a third", () => {
    store().openFile("w1", "a.ts", { preview: false });
    store().openToSide("w1", "b.ts");
    store().focusGroup("w1", 0);
    store().openToSide("w1", "c.ts");
    // From the first group: the existing second group takes it.
    expect(layout()).toEqual(["[a.ts]", "*b.ts [c.ts]"]);
    // From the last group: a new one.
    store().openToSide("w1", "d.ts");
    expect(layout()).toEqual(["[a.ts]", "b.ts [c.ts]", "*[d.ts]"]);
  });

  it("splits a tab into a new group right beside its own, whichever group has the keyboard", () => {
    store().openFile("w1", "a.ts", { preview: false });
    store().openToSide("w1", "b.ts");
    // The keyboard is in the second group; the split still stands beside the first.
    store().splitRight(edit("a.ts"));
    expect(layout()).toEqual(["[a.ts]", "*[a.ts]", "[b.ts]"]);
    expect(store().tabs).toHaveLength(3);
  });

  it("keeps a compare's other file when its diff tab is split", () => {
    const base = { ref: "file:b.ts", path: "b.ts", label: "b.ts ↔ a.ts" };
    store().openFile("w1", "a.ts", { mode: "diff", preview: false, base });
    store().splitRight(tabKeyOf("diff", fileKeyOf("w1", "a.ts")));
    expect(store().diffBases[fileKeyOf("w1", "a.ts")]).toEqual(base);
    expect(groupsOf(store(), "w1")).toHaveLength(2);
  });

  it("opens the next file in the group that has the keyboard", () => {
    store().openFile("w1", "a.ts", { preview: false });
    store().openToSide("w1", "b.ts");
    store().openFile("w1", "c.ts", { preview: false });
    expect(layout()).toEqual(["[a.ts]", "*b.ts [c.ts]"]);
    store().focusGroup("w1", 0);
    store().openFile("w1", "d.ts", { preview: false });
    expect(layout()).toEqual(["*a.ts [d.ts]", "b.ts [c.ts]"]);
  });

  it("keeps one preview tab per group", () => {
    store().openFile("w1", "a.ts");
    store().openToSide("w1", "b.ts");
    store().openFile("w1", "c.ts");
    store().openFile("w1", "d.ts");
    // d replaces the preview c on the right; the preview a on the left stays.
    expect(layout()).toEqual(["[a.ts]", "*b.ts [d.ts]"]);
  });

  it("closes a group with its last tab and moves the keyboard to the neighbour", () => {
    store().openFile("w1", "a.ts", { preview: false });
    store().openToSide("w1", "b.ts");
    store().openToSide("w1", "c.ts");
    expect(layout()).toEqual(["[a.ts]", "[b.ts]", "*[c.ts]"]);
    store().closeTab(edit("c.ts", 2));
    expect(layout()).toEqual(["[a.ts]", "*[b.ts]"]);
    store().focusGroup("w1", 0);
    store().closeTab(edit("a.ts"));
    expect(layout()).toEqual(["*[b.ts]"]);
    expect(store().active.w1).toBe(edit("b.ts", 1));
  });

  it("closing a tab in one group leaves the same file open in the other", () => {
    store().openFile("w1", "a.ts", { preview: false });
    store().openToSide("w1", "a.ts");
    store().closeTab(edit("a.ts", 1));
    expect(layout()).toEqual(["*[a.ts]"]);
    expect(Object.keys(store().files)).toHaveLength(1);
  });

  it("a click on a tab shows it in its own group and focuses that group", () => {
    store().openFile("w1", "a.ts", { preview: false });
    store().openFile("w1", "b.ts", { preview: false });
    store().openToSide("w1", "c.ts");
    store().activate(edit("a.ts"));
    expect(layout()).toEqual(["*[a.ts] b.ts", "[c.ts]"]);
  });

  it("steps through the tabs of the group that has the keyboard", () => {
    store().openFile("w1", "a.ts", { preview: false });
    store().openFile("w1", "b.ts", { preview: false });
    store().openToSide("w1", "c.ts");
    store().openFile("w1", "d.ts", { preview: false });
    store().cycle("w1", 1);
    expect(layout()).toEqual(["a.ts [b.ts]", "*[c.ts] d.ts"]);
    store().focusGroup("w1", 0);
    store().cycle("w1", 1);
    expect(layout()).toEqual(["*[a.ts] b.ts", "[c.ts] d.ts"]);
  });

  it("moves a dragged tab into another group", () => {
    store().openFile("w1", "a.ts", { preview: false });
    store().openFile("w1", "b.ts", { preview: false });
    store().openToSide("w1", "c.ts");
    store().moveTab(edit("b.ts"), 1);
    expect(layout()).toEqual(["[a.ts]", "*c.ts [b.ts]"]);
    // The last tab of a group moved away closes that group.
    store().moveTab(edit("a.ts"), 1);
    expect(layout()).toEqual(["*c.ts b.ts [a.ts]"]);
  });

  it("merges a dragged tab into the same file already open there", () => {
    store().openFile("w1", "a.ts", { preview: false });
    store().openFile("w1", "b.ts", { preview: false });
    store().openToSide("w1", "a.ts");
    store().moveTab(edit("a.ts"), 1);
    expect(layout()).toEqual(["[b.ts]", "*[a.ts]"]);
  });

  it("follows a rename of the files it shows", () => {
    store().openFile("w1", "src/a.ts", { preview: false });
    store().openToSide("w1", "src/b.ts");
    store().renamePath("w1", "src", "lib");
    expect(layout()).toEqual(["[lib/a.ts]", "*[lib/b.ts]"]);
    expect(store().active.w1).toBe(edit("lib/b.ts", 1));
  });

  it("restores remembered tabs into the first group", () => {
    store().restoreTabs("w1", [{ path: "a.ts", mode: "edit", preview: false }, { path: "b.ts", mode: "edit", preview: false }], "b.ts");
    expect(layout()).toEqual(["*a.ts [b.ts]"]);
    expect(store().active.w1).toBe(edit("b.ts"));
  });
});
