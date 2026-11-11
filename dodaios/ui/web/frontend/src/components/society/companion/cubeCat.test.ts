import { describe, expect, it } from "vitest";
import { CUBE_CLIPS, CUBE_RUN_SPEED, CUBE_WALK_SPEED, cubeClipFor, cubeClipForState } from "./cubeCat";

describe("cubeClipFor", () => {
  it("holds still when motion is reduced", () => {
    expect(cubeClipFor(3, true)).toBe("static");
  });

  it("idles, walks, then runs as the pace picks up", () => {
    expect(cubeClipFor(0, false)).toBe("idle");
    expect(cubeClipFor(CUBE_WALK_SPEED - 0.01, false)).toBe("idle");
    expect(cubeClipFor(CUBE_WALK_SPEED, false)).toBe("walk");
    expect(cubeClipFor(CUBE_RUN_SPEED - 0.01, false)).toBe("walk");
    expect(cubeClipFor(CUBE_RUN_SPEED, false)).toBe("run");
    expect(cubeClipFor(Number.NaN, false)).toBe("static");
  });

  it("picks a different clip as the pet's activity changes", () => {
    expect(cubeClipForState("idle")).toBe("idle");
    expect(cubeClipForState("talking")).toBe("gesture-positive");
    expect(cubeClipForState("success")).toBe("dance");
    expect(cubeClipForState("error")).toBe("gesture-negative");
    expect(cubeClipForState("sleeping")).toBe("static");
    expect(cubeClipForState("searching")).toBe("run");
  });

  it("names every clip the cat file ships", () => {
    expect(CUBE_CLIPS).toContain("run");
    expect(CUBE_CLIPS).toContain("walk");
    expect(CUBE_CLIPS).toContain("idle");
  });
});
