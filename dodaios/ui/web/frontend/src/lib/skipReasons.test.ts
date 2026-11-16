import { describe, expect, it } from "vitest";
import en from "@/i18n/locales/en.json";
import societyEn from "@/i18n/locales/society/en.json";
import de from "@/i18n/locales/de.json";
import { isRitualResult, reviewWaitReason, routineSkipReason, societyResultHeadline, societyResultText } from "./skipReasons";

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

  it("labels a standing task's look with the task, not with who ran it", () => {
    const look = (status: string) => ({ status, agentName: "Scout", data: { source: "routine", standing_id: "s1", standing_title: "Meta ads campaign" } });
    expect(societyResultHeadline(t, look("done"))).toBe("Standing task: Meta ads campaign");
    expect(societyResultHeadline(t, look("blocked"))).toBe("Standing task did not work: Meta ads campaign");
    expect(societyResultHeadline(t, look("skipped"))).toBe("Standing task skipped: Meta ads campaign");
    expect(societyResultHeadline(translator(de), look("done"))).toBe("Daueraufgabe: Meta ads campaign"); // i18n-allow: German locale check
    // An empty title is no label: the result reads like any other.
    expect(societyResultHeadline(t, { status: "done", agentName: "Scout", data: { standing_title: " " } })).toBe("Scout is done");
  });

  it("labels a ritual's card with the ritual: that it started, what was gathered later, or that nothing could be", () => {
    const card = (more: Record<string, unknown> = {}, status = "done") =>
      ({ status, agentName: "Nova", text: "", data: { source: "ritual", ritual_id: "rit_1", ritual_title: "Good morning", via: "voice", ...more } });
    expect(societyResultHeadline(t, card())).toBe("“Good morning” started");
    expect(societyResultHeadline(t, card({ pending: true }))).toBe("“Good morning” started");
    expect(societyResultHeadline(t, card({ late: true }))).toBe("“Good morning”: what was gathered");
    expect(societyResultHeadline(t, card({ late: true }, "failed"))).toBe("“Good morning”: gathering failed");
    // Steps for the moment that never got the conversation are named as such, not as a failed gathering.
    expect(societyResultHeadline(t, card({ late: true, steps_not_run: true }, "failed"))).toBe("“Good morning”: these steps did not run");
    expect(societyResultHeadline(translator(de), card())).toBe("„Good morning“ gestartet"); // i18n-allow: German locale check
    // The title stands as the person wrote it, whatever signs it has.
    expect(societyResultHeadline(t, card({ ritual_title: "Costs $& more" }))).toBe("“Costs $& more” started");
    // An empty title is no label: the result reads like any other.
    expect(societyResultHeadline(t, card({ ritual_title: " " }))).toBe("Nova is done");
    expect(isRitualResult(card())).toBe(true);
    expect(isRitualResult(card({ ritual_title: " " }))).toBe(false);
    expect(isRitualResult({ data: { standing_title: "Meta ads campaign" } })).toBe(false);
  });

  it("ends a ritual's card on the line that the rest follows while it is still gathered", () => {
    const card = (text: string, more: Record<string, unknown> = {}, status = "done") =>
      ({ status, text, data: { source: "ritual", ritual_title: "Good morning", ...more } });
    const follows = "The rest is being gathered and follows shortly.";
    expect(societyResultText(t, card("- Open my calendar"))).toBe("- Open my calendar");
    expect(societyResultText(t, card("- Open my calendar", { pending: false }))).toBe("- Open my calendar");
    // A paragraph of its own, so it does not read as one more step of the list above it.
    expect(societyResultText(t, card("- Open my calendar", { pending: true }))).toBe(`- Open my calendar\n\n${follows}`);
    // A ritual that only gathers has no text at its start: the line stands alone.
    expect(societyResultText(t, card("", { pending: true }))).toBe(follows);
    expect(societyResultText(t, card(""))).toBe("");
    // The second card brings what was gathered, or the reason nothing could be.
    expect(societyResultText(t, card("## News", { late: true }))).toBe("## News");
    expect(societyResultText(t, card("No model answered.", { late: true }, "failed"))).toBe("No model answered.");
    // Only a ritual's card reads `pending`.
    expect(societyResultText(t, { status: "done", text: "Kept.", data: { pending: true } })).toBe("Kept.");
  });
});
