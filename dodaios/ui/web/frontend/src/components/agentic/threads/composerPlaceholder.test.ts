import { describe, expect, it } from "vitest";
import de from "@/i18n/locales/de.json";
import en from "@/i18n/locales/en.json";
import zh from "@/i18n/locales/zh.json";
import { composerPlaceholder } from "./composerPlaceholder";

type Dictionary = Record<string, Record<string, string>>;

// Reads the real dictionaries, so a renamed or missing key shows as the key itself.
const lookup = (dictionary: Dictionary) => (key: string) => {
  const [section, name] = key.split(".");
  return dictionary[section]?.[name] ?? key;
};

describe("composerPlaceholder", () => {
  it("names only the shortcuts the picked agent honours", () => {
    const t = lookup(en as unknown as Dictionary);
    // Claude Code: commands and file mentions.
    expect(composerPlaceholder(["/", "@"], t)).toBe("Ask anything. @ files, / commands");
    // Codex: file mentions and skills.
    expect(composerPlaceholder(["@", "$"], t)).toBe("Ask anything. @ files, $ skills");
    // The other coding agents: file mentions only.
    expect(composerPlaceholder(["@"], t)).toBe("Ask anything. @ files");
  });

  it("keeps the sentence alone for an agent without shortcuts or while the catalog loads", () => {
    const t = lookup(en as unknown as Dictionary);
    expect(composerPlaceholder([], t)).toBe("Ask anything");
    expect(composerPlaceholder(["#"], t)).toBe("Ask anything");
  });

  it("speaks the interface language, with its own list separator", () => {
    expect(composerPlaceholder(["/", "@"], lookup(de as unknown as Dictionary))).toBe("Frag einfach los. @ Dateien, / Befehle");
    expect(composerPlaceholder(["/", "@", "$"], lookup(zh as unknown as Dictionary))).toBe("有什么尽管问。@ 文件、$ 技能、/ 命令");
  });
});
