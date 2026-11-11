import { describe, expect, it } from "vitest";
import { hasMagicWord, splitMagicWords } from "./magicWords";

describe("magic words", () => {
  it("finds ultrathink and ultracode as whole words in any case", () => {
    expect(hasMagicWord("fix it, ultrathink")).toBe(true);
    expect(hasMagicWord("UltraCode the migration")).toBe(true);
    expect(hasMagicWord("ultrathinking about it")).toBe(false);
    expect(hasMagicWord("an ultra thin case")).toBe(false);
  });

  it("cuts the text into plain stretches and the words, losing nothing", () => {
    const text = "ultrathink: fix the test, then ultracode\nthe rest";
    const parts = splitMagicWords(text);
    expect(parts).toEqual([
      { text: "ultrathink", magic: true },
      { text: ": fix the test, then ", magic: false },
      { text: "ultracode", magic: true },
      { text: "\nthe rest", magic: false },
    ]);
    expect(parts.map((part) => part.text).join("")).toBe(text);
    expect(splitMagicWords("plain")).toEqual([{ text: "plain", magic: false }]);
  });
});
