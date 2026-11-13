import { describe, expect, it } from "vitest";
import en from "./locales/en.json";
import de from "./locales/de.json";
import es from "./locales/es.json";
import pt from "./locales/pt.json";
import zh from "./locales/zh.json";

type Locale = Record<string, unknown>;

const block = (locale: Locale) => (locale.rail_notice ?? {}) as Record<string, string>;
const placeholders = (text: string) => (text.match(/\{\w+\}/g) ?? []).sort();

describe("rail notice i18n parity", () => {
  it("en defines the block", () => {
    expect(Object.keys(block(en as Locale)).length).toBeGreaterThan(0);
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
  }

  it("no sentence uses {name}: the translator fills that with the assistant's own name", () => {
    for (const locale of [en, de, es, pt, zh]) {
      for (const text of Object.values(block(locale as Locale))) expect(text).not.toContain("{name}");
    }
  });

  it("German uses real umlauts", () => {
    expect(block(de as Locale).takeover_action).toBe("Browser öffnen");
    expect(block(de as Locale).provider_action).toBe("API-Schlüssel öffnen");
  });
});
