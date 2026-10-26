/**
 * The Agents frame decides no colour of its own (index.css: never write a
 * literal colour) and honours reduced motion. Both are read straight from the
 * source, so a regression fails here rather than in one theme only.
 */
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const SOCIETY = join(__dirname);
const FILES = [
  join(SOCIETY, "agentSection.css"),
  join(SOCIETY, "agentTint.ts"),
  join(SOCIETY, "card", "agentChatLayout.css"),
  join(SOCIETY, "card", "AgentChatLayout.tsx"),
  join(SOCIETY, "card", "AgentCardOverlay.tsx"),
  join(SOCIETY, "card", "AgentHeader.tsx"),
  join(SOCIETY, "card", "approvalModes.ts"),
  join(SOCIETY, "card", "shellLayout.ts"),
  ...readdirSync(join(SOCIETY, "roster"))
    .filter((name) => /\.(tsx?|css)$/.test(name) && !/\.test\./.test(name))
    .map((name) => join(SOCIETY, "roster", name)),
  join(SOCIETY, "..", "..", "views", "society", "SocietyView.tsx"),
];

const PALETTE = "slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose";
const LITERALS: [string, RegExp][] = [
  ["hex colour", /#[0-9a-fA-F]{3,8}\b(?![\w-])/],
  ["rgb() with numbers", /\brgba?\(\s*\d/],
  ["hsl() with numbers", /\bhsla?\(\s*\d/],
  ["Tailwind palette colour", new RegExp(`\\b(?:bg|text|ring|border|fill|stroke|from|to|via|outline|shadow)-(?:${PALETTE})-\\d{2,3}\\b`)],
  ["black or white utility", /\b(?:bg|text|ring|border)-(?:black|white)\b/],
];

function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:"'`])\/\/[^\n]*/g, "$1");
}

describe("Agents section design rules", () => {
  it("writes no literal colour anywhere in the frame", () => {
    const offences: string[] = [];
    for (const file of FILES) {
      const text = stripComments(readFileSync(file, "utf8"));
      for (const [label, pattern] of LITERALS) {
        const match = pattern.exec(text);
        if (match) offences.push(`${file.split(/[\\/]/).slice(-2).join("/")}: ${label} "${match[0]}"`);
      }
    }
    expect(offences).toEqual([]);
  });

  it("stops every section animation under reduced motion", () => {
    const css = readFileSync(join(SOCIETY, "agentSection.css"), "utf8");
    const reduced = [...css.matchAll(/@media \(prefers-reduced-motion: reduce\) \{([\s\S]*?)\n\}/g)].map((m) => m[1]).join("\n");
    for (const token of ["--as-dur-1", "--as-dur-2", "--as-dur-3", "--as-dur-4"]) {
      expect(reduced).toMatch(new RegExp(`${token}: 0ms`));
    }
    expect(reduced).toMatch(/\.as-shimmer \{[\s\S]*animation: none/);
    expect(reduced).toMatch(/\.as-status\[data-status="working"\]::after \{[\s\S]*animation: none/);
    // Every keyframe animation in the file runs on a duration token, or is switched off above.
    for (const match of css.matchAll(/animation: ([^;]+);/g)) {
      const value = match[1];
      if (value === "none") continue;
      expect(/var\(--as-dur-\d\)/.test(value) || /as-shimmer|as-breathe/.test(value), value).toBe(true);
    }
  });

  it("keeps hover-only affordances visible without a hover pointer", () => {
    const css = readFileSync(join(SOCIETY, "agentSection.css"), "utf8");
    expect(css).toMatch(/@media \(hover: none\) \{[\s\S]*--as-reveal: 1/);
  });
});
