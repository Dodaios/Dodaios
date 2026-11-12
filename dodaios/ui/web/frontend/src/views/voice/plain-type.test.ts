import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * The Voice section has no small print. Its screens use four type sizes
 * (display, title, reading, body) and nothing below body; a row does not carry
 * a caption. This reads the section's own source so the rule holds for every
 * tab, including ones added later.
 */
const ROOTS = [__dirname, join(__dirname, "..", "VoiceHubView.tsx")];

function sources(path: string): string[] {
  if (statSync(path).isFile()) return [path];
  return readdirSync(path).flatMap((name) => sources(join(path, name)));
}

const FILES = ROOTS.flatMap(sources).filter(
  (file) => file.endsWith(".tsx") && !file.endsWith(".test.tsx"),
);

const BANNED: readonly [RegExp, string][] = [
  [/\btext-(meta|micro|xs|sm)\b/, "a type size below body"],
  [/\btext-\[\d+px\]/, "a literal type size"],
  [/\buppercase\b/, "an uppercase label"],
  [/size=["']sm["']/, "a small control"],
  [/from "@\/components\/ui\/badge"/, "a badge"],
];

describe("voice section type", () => {
  it("finds the section's files", () => {
    expect(FILES.length).toBeGreaterThan(1);
  });

  it.each(FILES)("%s has no small print", (file) => {
    const text = readFileSync(file, "utf8");
    for (const [pattern, what] of BANNED) {
      expect(pattern.test(text), `${what} in ${file}`).toBe(false);
    }
  });
});
