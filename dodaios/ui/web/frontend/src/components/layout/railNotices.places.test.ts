import { describe, expect, test } from "vitest";

import { noticePlaces } from "@/components/layout/railNotices";

describe("noticePlaces", () => {
  test("every notice gets a tile while they all fit", () => {
    // 344 px hold seven 44 px tiles with six 6 px gaps.
    expect(noticePlaces(344, 7)).toEqual({ tiles: 7, more: 0 });
    expect(noticePlaces(600, 3)).toEqual({ tiles: 3, more: 0 });
  });

  test("when they do not fit, the last place becomes the count", () => {
    expect(noticePlaces(344, 8)).toEqual({ tiles: 6, more: 2 });
    expect(noticePlaces(343, 7)).toEqual({ tiles: 5, more: 2 });
  });

  test("a smaller window shows fewer tiles", () => {
    expect(noticePlaces(150, 6)).toEqual({ tiles: 2, more: 4 });
    expect(noticePlaces(100, 6)).toEqual({ tiles: 1, more: 5 });
  });

  test("a rail with no room left still shows the count", () => {
    expect(noticePlaces(0, 5)).toEqual({ tiles: 0, more: 5 });
    expect(noticePlaces(0, 1)).toEqual({ tiles: 1, more: 0 });
  });
});
