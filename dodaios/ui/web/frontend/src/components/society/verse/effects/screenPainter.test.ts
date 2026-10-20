import { describe, expect, it } from "vitest";
import { screenCanvasSize, wrapTail } from "./screenPainter";

describe("screen painting", () => {
  it("wraps long lines and keeps the newest rows", () => {
    expect(wrapTail(["abcdefghij", "xy"], 4, 10)).toEqual(["abcd", "efgh", "ij", "xy"]);
    expect(wrapTail(["one", "two", "three"], 10, 2)).toEqual(["two", "three"]);
    expect(wrapTail(["a   b\tc"], 10, 5)).toEqual(["a b c"]);
  });

  it("sizes the canvas by the screen's metres within bounds", () => {
    expect(screenCanvasSize(1.5, 0.42)).toEqual({ width: 480, height: 134 });
    expect(screenCanvasSize(10, 10)).toEqual({ width: 768, height: 512 });
    expect(screenCanvasSize(0.05, 0.05)).toEqual({ width: 96, height: 48 });
  });
});
