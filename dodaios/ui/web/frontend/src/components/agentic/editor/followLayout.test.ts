import { describe, expect, it } from "vitest";

import {
  FOLLOW_COLUMNS_MAX,
  clampFollowTop,
  followColumnCount,
  followColumnOf,
  followOffset,
  followStep,
} from "./followLayout";

describe("follow mode layout", () => {
  it("fits as many columns as the width allows, at least two and at most the cap", () => {
    expect(followColumnCount(300)).toBe(2);
    expect(followColumnCount(1000)).toBe(2);
    expect(followColumnCount(1800)).toBe(4);
    expect(followColumnCount(20000)).toBe(FOLLOW_COLUMNS_MAX);
  });

  it("steps each column by the full lines that fit one column below the space above the first line", () => {
    expect(followStep(610, 20)).toBe(600);
    expect(followStep(600, 20)).toBe(600);
    expect(followStep(610, 20, 8)).toBe(600);
    expect(followStep(605, 20, 8)).toBe(580);
    // A column shorter than a line still moves the next one by a line.
    expect(followStep(12, 20)).toBe(20);
  });

  it("starts every later column on a line boundary, skipping the space above the first line", () => {
    // Lines start at 8, 28, 48, …: 8 px of blank space above the first line.
    expect(followOffset(0, 0, 600, 8)).toBe(0);
    expect(followOffset(0, 1, 600, 8)).toBe(608);
    expect(followOffset(0, 2, 600, 8)).toBe(1208);
    expect(followOffset(100, 1, 600, 8)).toBe(708);
  });

  it("keeps the first column between the file's start and the point where its end fills the last column", () => {
    // 100 lines of 20 px, 3 columns of 200 px each.
    expect(clampFollowTop(-50, 2000, 200, 200, 3)).toBe(0);
    expect(clampFollowTop(500, 2000, 200, 200, 3)).toBe(500);
    expect(clampFollowTop(5000, 2000, 200, 200, 3)).toBe(1400);
    expect(clampFollowTop(5000, 2016, 200, 180, 3, 8)).toBe(1448);
    // A file shorter than the surface never scrolls.
    expect(clampFollowTop(300, 400, 200, 200, 3)).toBe(0);
  });

  it("names the column a line is shown in", () => {
    // First column scrolled to 100 px, columns 200 px apart.
    expect(followColumnOf(100, 100, 200, 3)).toBe(0);
    expect(followColumnOf(299, 100, 200, 3)).toBe(0);
    expect(followColumnOf(300, 100, 200, 3)).toBe(1);
    expect(followColumnOf(699, 100, 200, 3)).toBe(2);
    // Above the first column and below the last one: off the surface.
    expect(followColumnOf(80, 100, 200, 3)).toBeNull();
    expect(followColumnOf(700, 100, 200, 3)).toBeNull();
  });

  it("gives the first column the space above the first line as well", () => {
    // Unscrolled, 8 px lead: the first column shows lines starting at 8 … 588.
    expect(followColumnOf(588, 0, 600, 2, 8)).toBe(0);
    expect(followColumnOf(608, 0, 600, 2, 8)).toBe(1);
    expect(followColumnOf(1188, 0, 600, 2, 8)).toBe(1);
    expect(followColumnOf(1208, 0, 600, 2, 8)).toBeNull();
  });
});
