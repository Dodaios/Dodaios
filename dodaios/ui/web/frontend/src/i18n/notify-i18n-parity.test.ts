import { describe, expect, it } from "vitest";
import en from "./locales/en.json";
import de from "./locales/de.json";
import es from "./locales/es.json";
import pt from "./locales/pt.json";
import zh from "./locales/zh.json";

type Locale = Record<string, unknown>;

const block = (locale: Locale, name: string) => (locale[name] ?? {}) as Record<string, string>;
const placeholders = (text: string) => (text.match(/\{\w+\}/g) ?? []).sort();

describe.each(["notify", "reminders"])("%s i18n parity", (namespace) => {
  it("en defines the block", () => {
    expect(Object.keys(block(en as Locale, namespace)).length).toBeGreaterThan(0);
  });

  for (const [language, locale] of Object.entries({ de, es, pt, zh })) {
    it(`${language} has the same keys and placeholders as en`, () => {
      const source = block(en as Locale, namespace);
      const target = block(locale as Locale, namespace);
      expect(Object.keys(target).sort()).toEqual(Object.keys(source).sort());
      for (const [key, text] of Object.entries(source)) {
        expect(placeholders(target[key] ?? ""), `${language}.${key}`).toEqual(placeholders(text));
        expect((target[key] ?? "").trim().length, `${language}.${key}`).toBeGreaterThan(0);
      }
    });
  }

  it("never names the assistant with the translator's token", () => {
    for (const text of Object.values(block(en as Locale, namespace))) expect(text).not.toContain("{name}");
  });
});

it("every locale labels the Notifications settings page", () => {
  for (const locale of [en, de, es, pt, zh]) {
    const nav = (locale as Locale).nav as Record<string, string>;
    expect(nav.notifications?.trim().length).toBeGreaterThan(0);
  }
});
