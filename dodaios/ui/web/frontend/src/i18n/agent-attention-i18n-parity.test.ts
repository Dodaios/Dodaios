import { describe, expect, it } from "vitest";
import en from "./locales/en.json";
import de from "./locales/de.json";
import es from "./locales/es.json";
import pt from "./locales/pt.json";
import zh from "./locales/zh.json";

type Locale = Record<string, unknown>;

const block = (locale: Locale) => (locale.agent_attention ?? {}) as Record<string, string>;
const placeholders = (text: string) => (text.match(/\{\w+\}/g) ?? []).sort();

describe("agent attention i18n parity", () => {
  it("en defines the attention block", () => {
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

  it("never uses the assistant-name token, which the translator would fill", () => {
    for (const text of Object.values(block(en as Locale))) expect(text).not.toContain("{name}");
  });
});
