/**
 * The phone app's strings: the `mobile.app` namespace of the five locale files,
 * picked by the phone's language, English when a key is missing.
 */
import strings from "virtual:mobile-strings";

export type PhoneLanguage = "en" | "de" | "es" | "pt" | "zh";

const KNOWN: readonly PhoneLanguage[] = ["en", "de", "es", "pt", "zh"];

export function pickLanguage(tags: readonly string[]): PhoneLanguage {
  for (const tag of tags) {
    const code = String(tag || "").toLowerCase().split("-")[0];
    if ((KNOWN as readonly string[]).includes(code)) return code as PhoneLanguage;
  }
  return "en";
}

let current: PhoneLanguage = "en";

export function setLanguage(language: PhoneLanguage): void {
  current = language;
}

export function language(): PhoneLanguage {
  return current;
}

/** The string for `key`, with `{name}`-style fills; English when the language lacks it. */
export function t(key: string, fills: Record<string, string | number> = {}): string {
  const table = strings[current] ?? {};
  const fallback = strings.en ?? {};
  let text = table[key] ?? fallback[key] ?? key;
  for (const [name, value] of Object.entries(fills)) {
    text = text.split(`{${name}}`).join(String(value));
  }
  return text;
}
