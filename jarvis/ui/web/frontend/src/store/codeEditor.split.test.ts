import { beforeEach, describe, expect, it } from "vitest";

import { fileKeyOf, tabKeyOf, useCodeEditorStore } from "./codeEditor";

const store = () => useCodeEditorStore.getState();
const edit = (path: string) => tabKeyOf("edit", fileKeyOf("w1", path));

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
    side: {},
    sideFocused: false,
  });
});

describe("two editors side by side", () => {
  it("opens a file beside the active one and gives it the keyboard", () => {
    store().openFile("w1", "a.ts", { preview: false });
    store().openToSide("w1", "b.ts");
    expect(store().active.w1).toBe(edit("a.ts"));
    expect(store().side.w1).toBe(edit("b.ts"));
    expect(store().sideFocused).toBe(true);
    expect(store().tabs.map((tab) => tab.path)).toEqual(["a.ts", "b.ts"]);
    expect(store().tabs[1].preview).toBe(false);
  });

  it("simply opens the file when nothing is open yet", () => {
    store().openToSide("w1", "a.ts");
    expect(store().active.w1).toBe(edit("a.ts"));
    expect(store().side.w1 ?? null).toBeNull();
    expect(store().sideFocused).toBe(false);
  });

  it("shows the same file twice when the active file is opened to the side", () => {
    store().openFile("w1", "a.ts", { preview: false });
    store().openToSide("w1", "a.ts");
    expect(store().active.w1).toBe(edit("a.ts"));
    expect(store().side.w1).toBe(edit("a.ts"));
    expect(store().tabs).toHaveLength(1);
  });

  it("sends the next opened file to the editor that has the keyboard", () => {
    store().openFile("w1", "a.ts", { preview: false });
    store().openToSide("w1", "b.ts");
    store().openFile("w1", "c.ts");
    expect(store().side.w1).toBe(edit("c.ts"));
    expect(store().active.w1).toBe(edit("a.ts"));

    store().focusGroup(false);
    store().openFile("w1", "d.ts", { preview: false });
    expect(store().active.w1).toBe(edit("d.ts"));
    expect(store().side.w1).toBe(edit("c.ts"));
  });

  it("never lets a preview replace the tab the other editor shows", () => {
    store().openFile("w1", "a.ts");
    store().openToSide("w1", "b.ts");
    expect(store().tabs.map((tab) => tab.path)).toEqual(["a.ts", "b.ts"]);
    // The first editor still shows its preview tab.
    expect(store().active.w1).toBe(edit("a.ts"));

    store().focusGroup(false);
    store().openFile("w1", "c.ts");
    // c replaces the preview a in the first editor, never b on the right.
    expect(store().tabs.map((tab) => tab.path)).toEqual(["c.ts", "b.ts"]);
    expect(store().side.w1).toBe(edit("b.ts"));
  });

  it("ends the split when its tab closes, or when one tab would be left twice", () => {
    store().openFile("w1", "a.ts", { preview: false });
    store().openToSide("w1", "b.ts");
    store().closeTab(edit("b.ts"));
    expect(store().side.w1).toBeNull();
    expect(store().active.w1).toBe(edit("a.ts"));

    store().openToSide("w1", "b.ts");
    store().closeTab(edit("a.ts"));
    expect(store().active.w1).toBe(edit("b.ts"));
    expect(store().side.w1).toBeNull();
  });

  it("closes the split and keeps the tab", () => {
    store().openFile("w1", "a.ts", { preview: false });
    store().openToSide("w1", "b.ts");
    store().closeSide("w1");
    expect(store().side.w1).toBeNull();
    expect(store().sideFocused).toBe(false);
    expect(store().tabs.map((tab) => tab.path)).toEqual(["a.ts", "b.ts"]);
  });

  it("gives the keyboard back to the first editor when a tab is clicked", () => {
    store().openFile("w1", "a.ts", { preview: false });
    store().openToSide("w1", "b.ts");
    store().activate(edit("b.ts"));
    expect(store().active.w1).toBe(edit("b.ts"));
    expect(store().sideFocused).toBe(false);
  });

  it("steps through the tabs of the editor that has the keyboard", () => {
    store().openFile("w1", "a.ts", { preview: false });
    store().openFile("w1", "b.ts", { preview: false });
    store().openToSide("w1", "c.ts");
    store().cycle("w1", 1);
    expect(store().side.w1).toBe(edit("a.ts"));
    expect(store().active.w1).toBe(edit("b.ts"));

    store().focusGroup(false);
    store().cycle("w1", 1);
    expect(store().active.w1).toBe(edit("c.ts"));
  });

  it("follows a rename of the file it shows", () => {
    store().openFile("w1", "a.ts", { preview: false });
    store().openToSide("w1", "src/b.ts");
    store().renamePath("w1", "src", "lib");
    expect(store().side.w1).toBe(edit("lib/b.ts"));
  });
});
