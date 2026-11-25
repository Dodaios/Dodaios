import { describe, expect, it } from "vitest";
import en from "./locales/en.json";
import de from "./locales/de.json";
import es from "./locales/es.json";
import pt from "./locales/pt.json";
import zh from "./locales/zh.json";

type Locale = Record<string, unknown>;

const block = (locale: Locale) =>
  (((locale.settings_view ?? {}) as Record<string, unknown>).background_agents ?? {}) as Record<
    string,
    string
  >;
const placeholders = (text: string) => (text.match(/\{\w+\}/g) ?? []).sort();

describe("background agents i18n parity", () => {
  it("en names the learning the background service keeps", () => {
    const words = block(en as Locale);
    expect(words.learning).toBe("self-improvement learning");
    expect(words.description).toContain("self-improvement learning");
    expect(words.login_description).toContain("self-improvement learning");
  });

  for (const [language, locale] of Object.entries({ de, es, pt, zh })) {
    it(`${language} has the same keys and placeholders as en`, () => {
      const source = block(en as Locale);
      const target = block(locale as Locale);
      expect(Object.keys(target).sort()).toEqual(Object.keys(source).sort());
      for (const [key, text] of Object.entries(source)) {
        expect(placeholders(target[key] ?? ""), `${language}.${key}`).toEqual(placeholders(text));
        expect((target[key] ?? "").trim().length, `${language}.${key}`).toBeGreaterThan(0);
      }
    });

    it(`${language} names the learning in the description and the login row`, () => {
      const target = block(locale as Locale);
      expect(target.description).toContain(target.learning.replace(/^(das|el|a) /, ""));
      expect(target.login_description).toContain(target.learning.replace(/^(das|el|a) /, ""));
    });
  }

  it("German uses real umlauts", () => {
    expect(block(de as Locale).description).toContain("schließt");
    expect(block(de as Locale).description).toContain("Öffnest");
  });
});
