import { describe, expect, it } from "vitest";
import { translate } from "@/i18n";
import type { NoticeItem } from "./reduce";
import { isModelFallback, limitResetLabel, modelFallbackText } from "./modelFallback";

// 2026-11-16T23:00:00Z = 17 Nov, 00:00 in Berlin (the reset of the Fable limit on 2026-11-15).
const RESET = 1794870000;

function notice(kind: string, data: Record<string, unknown>, text = "backend sentence"): NoticeItem {
  return { type: "notice", id: "n1", kind, text, agentName: "", agentId: "", status: "", tsMs: 0, data, resolved: "" };
}

const t = (key: string) => translate(key);

describe("model fallback notice", () => {
  it("names what ran out, until when, and the model the thread continued on", () => {
    const item = notice("model_fallback", {
      limit: "usage", limit_label: "Fable", from_label: "Fable 5.2", to_label: "Opus 5.5", resets_at: RESET,
    });
    const when = limitResetLabel(RESET, "en-GB");
    // The reader's own time zone: 17 Nov, 00:00 in Berlin, 16 Nov, 23:00 in UTC.
    expect(when).toBe(new Intl.DateTimeFormat("en-GB", {
      day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
    }).format(RESET * 1000));
    expect(modelFallbackText(item, t, "en-GB")).toBe(`Fable limit reached until ${when} – continued on Opus 5.5`);
    expect(isModelFallback(item)).toBe(true);
  });

  it("says a rate limit and a limit without a reset time plainly", () => {
    expect(modelFallbackText(notice("model_fallback", { limit: "rate", limit_label: "Opus 5.5", to_label: "Sonnet 5.5" }), t, "en-GB"))
      .toBe("Opus 5.5 is rate limited – continued on Sonnet 5.5");
    expect(modelFallbackText(notice("model_fallback", { limit: "usage", limit_label: "Fable", to_label: "Opus 5.5" }), t, "en-GB"))
      .toBe("Fable limit reached – continued on Opus 5.5");
  });

  it("lists every limited model with its reset when the chain ran out", () => {
    const item = notice("model_fallback_exhausted", {
      models: [
        { model: "claude-fable-5-2", label: "Fable", resets_at: RESET },
        { model: "claude-opus-5-5", label: "Opus 5.5", resets_at: null },
      ],
      resets_at: RESET,
    });
    const when = limitResetLabel(RESET, "en-GB");
    const text = modelFallbackText(item, t, "en-GB");
    expect(text).toContain(`Fable until ${when}; Opus 5.5`);
    expect(text).toContain(`the first one is free again ${when}`);
  });

  it("falls back to the backend's sentence for a notice without fields", () => {
    expect(modelFallbackText(notice("model_fallback", {}), t, "en-GB")).toBe("backend sentence");
    expect(limitResetLabel(null, "en-GB")).toBe("");
  });
});
