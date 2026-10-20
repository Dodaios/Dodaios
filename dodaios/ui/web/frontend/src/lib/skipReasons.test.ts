import { describe, expect, it } from "vitest";
import en from "@/i18n/locales/en.json";
import societyEn from "@/i18n/locales/society/en.json";
import de from "@/i18n/locales/de.json";
import { reviewWaitReason, routineSkipReason, societyResultHeadline, societyResultText } from "./skipReasons";

function translator(...sources: unknown[]) {
  return (key: string) => {
    for (const source of sources) {
      const value = key.split(".").reduce<unknown>((node, part) => (node as Record<string, unknown> | undefined)?.[part], source);
      if (typeof value === "string") return value;
    }
    return key;
  };
}

const t = translator(en, societyEn);

describe("skip and wait reasons", () => {
  it("names the routine's own key seat", () => {
    const text = routineSkipReason(t, "api_key_seat", "gemini");
    expect(text).toContain("API key (gemini) was not charged");
    expect(text).not.toContain("{provider}");
  });

  it("drops the provider slot when the seat is unknown", () => {
    expect(routineSkipReason(t, "api_key_seat", "")).toContain("the routine's API key was not charged");
  });

  it("uses the generic wording for no free capacity and keeps an older server sentence", () => {
    expect(routineSkipReason(t, "no_capacity", "")).toMatch(/^Skipped: no subscription or local model was free/);
    expect(routineSkipReason(t, "", "", "Older server sentence.")).toBe("Older server sentence.");
  });

  it("words a review's wait reason and falls back to the server sentence", () => {
    expect(reviewWaitReason(t, "api_key_seat", "openai")).toContain("API key (openai) is not charged");
    expect(reviewWaitReason(t, "seat_failed", "")).toBe("The agent's model did not give a usable answer.");
    expect(reviewWaitReason(t, undefined, undefined, "server")).toBe("server");
  });

  it("gives a skipped chat notice its own headline and translated body", () => {
    const item = { status: "skipped", agentName: "Scout", text: "English sentence.", data: { reason_code: "api_key_seat", provider: "gemini", routine: "Inbox sweep" } };
    expect(societyResultHeadline(t, item)).toBe("Scout skipped “Inbox sweep”");
    expect(societyResultText(t, item)).toContain("API key (gemini)");
    const german = translator(de);
    expect(societyResultHeadline(german, item)).toBe("Scout hat „Inbox sweep“ übersprungen"); // i18n-allow: German locale check
    expect(societyResultText(german, item)).toContain("API-Schlüssel der Routine (gemini)"); // i18n-allow: German locale check
    expect(societyResultHeadline(t, { status: "done", agentName: "Scout" })).toBe("Scout is done");
    expect(societyResultText(t, { status: "failed", text: "Kept." })).toBe("Kept.");
  });
});
