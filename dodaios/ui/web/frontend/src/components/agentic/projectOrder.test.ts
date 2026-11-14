import { describe, expect, it } from "vitest";
import { projectNeighbour, projectOrderAfterMove, sortByIds } from "./projectOrder";

const list = [
  { id: "pin", pinned: true },
  { id: "a" },
  { id: "b" },
  { id: "c" },
];

describe("projectOrderAfterMove", () => {
  it("puts the folder before or after the one it is dropped on", () => {
    expect(projectOrderAfterMove(list, "c", "a", true)).toEqual(["pin", "c", "a", "b"]);
    expect(projectOrderAfterMove(list, "a", "b", false)).toEqual(["pin", "b", "a", "c"]);
  });

  it("returns null when nothing would change", () => {
    expect(projectOrderAfterMove(list, "a", "a", true)).toBeNull();
    expect(projectOrderAfterMove(list, "a", "b", true)).toBeNull();
    expect(projectOrderAfterMove(list, "x", "b", true)).toBeNull();
  });

  it("keeps a folder inside its own section", () => {
    expect(projectOrderAfterMove(list, "pin", "a", false)).toBeNull();
    expect(projectOrderAfterMove(list, "a", "pin", true)).toBeNull();
  });
});

describe("projectNeighbour", () => {
  it("finds the folder above or below in the same section only", () => {
    expect(projectNeighbour(list, "b", true)?.id).toBe("a");
    expect(projectNeighbour(list, "b", false)?.id).toBe("c");
    expect(projectNeighbour(list, "a", true)).toBeNull();
    expect(projectNeighbour(list, "pin", false)).toBeNull();
  });
});

describe("sortByIds", () => {
  it("follows the given order and keeps unnamed items at the end", () => {
    const items = [{ id: "hidden" }, { id: "a" }, { id: "b" }];
    expect(sortByIds(items, ["b", "a"]).map((item) => item.id)).toEqual(["b", "a", "hidden"]);
  });
});
