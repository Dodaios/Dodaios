import { describe, expect, it } from "vitest";
import { speakableText, speechStretches } from "./readAloud";

describe("speakableText", () => {
  it("leaves out code blocks, tables and link addresses", () => {
    const text = [
      "## Done",
      "",
      "I changed **two** files, see [the diff](https://example.com/diff).",
      "",
      "```ts",
      "const x = 1;",
      "```",
      "",
      "| file | lines |",
      "|------|-------|",
      "| a.ts | 3 |",
      "",
      "- `readAloud.ts` is new",
      "- Tests pass",
    ].join("\n");
    const spoken = speakableText(text);
    expect(spoken).toContain("Done.");
    expect(spoken).toContain("I changed two files, see the diff.");
    expect(spoken).toContain("readAloud.ts is new.");
    expect(spoken).toContain("Tests pass.");
    expect(spoken).not.toMatch(/const x|example\.com|a\.ts \||\*\*|```|`/);
  });

  it("reads inline HTML by its words and skips autolinks", () => {
    expect(speakableText("Press <kbd>Ctrl</kbd> &amp; see <https://example.com> now.")).toBe("Press Ctrl & see now.");
    expect(speakableText("<script>alert(1)</script>Safe.")).toBe("Safe.");
  });

  it("keeps snake_case words and plain sentences as they are", () => {
    expect(speakableText("Rename file_name_here now.")).toBe("Rename file_name_here now.");
  });
});

describe("speechStretches", () => {
  it("starts with a short stretch and cuts only at sentence ends", () => {
    const sentence = "This is a sentence of about forty chars. ";
    const stretches = speechStretches(sentence.repeat(40));
    expect(stretches[0].length).toBeLessThanOrEqual(220);
    expect(stretches.slice(1).every((part) => part.length <= 900)).toBe(true);
    expect(stretches.every((part) => part.endsWith("."))).toBe(true);
    expect(stretches.join(" ")).toBe(sentence.repeat(40).trim());
  });

  it("cuts a run-on sentence at a space", () => {
    const stretches = speechStretches("word ".repeat(200));
    expect(stretches.every((part) => part.length <= 900 && !part.startsWith(" "))).toBe(true);
    expect(stretches.join(" ").split(" ").length).toBe(200);
  });

  it("gives nothing for empty text", () => {
    expect(speechStretches("  ")).toEqual([]);
  });
});
