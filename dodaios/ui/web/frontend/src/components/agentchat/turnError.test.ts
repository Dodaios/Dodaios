import { describe, expect, it } from "vitest";
import de from "@/i18n/locales/de.json";
import en from "@/i18n/locales/en.json";
import es from "@/i18n/locales/es.json";
import pt from "@/i18n/locales/pt.json";
import zh from "@/i18n/locales/zh.json";
import { turnErrorText } from "./turnError";

const CODES = [
  "mandated_tool_unfulfilled",
  "unbacked_action_claim",
  "guarded_response",
  "delegation_continuation_limit",
];

describe("turnErrorText", () => {
  it("translates a known backend code and passes any other text through", () => {
    const t = (key: string) => `T:${key}`;
    expect(turnErrorText("guarded_response", t)).toBe("T:thread_turn.errors.guarded_response");
    expect(turnErrorText("Provider timed out", t)).toBe("Provider timed out");
    expect(turnErrorText(null, t)).toBeNull();
    expect(turnErrorText("", t)).toBeNull();
  });

  it("has a sentence for every code in every UI language", () => {
    for (const locale of [en, de, es, pt, zh]) {
      const errors = (locale as { thread_turn: { errors: Record<string, string> } }).thread_turn.errors;
      for (const code of CODES) expect(errors[code]?.length).toBeGreaterThan(10);
    }
  });
});
