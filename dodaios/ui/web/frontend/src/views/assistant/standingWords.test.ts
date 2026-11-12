/**
 * A standing task's words: the pace per language, the level, what a look
 * came to, and when the next one is due. Checked against the real English
 * and German dictionaries, so a reworded locale string fails here.
 */
import { describe, expect, it } from "vitest";

import de from "@/i18n/locales/de.json";
import en from "@/i18n/locales/en.json";
import { whenAhead } from "@/views/assistant/format";
import {
  PACE_CHOICES,
  autonomyDoes,
  autonomyName,
  lastFinding,
  lastLookLine,
  looksWords,
  mannerLine,
  nextLookLine,
  nextLookWords,
  outcomeTone,
  outcomeWords,
  paceOptions,
  paceWords,
} from "@/views/assistant/standingWords";

function translator(source: unknown) {
  return (key: string) => {
    const value = key.split(".").reduce<unknown>((node, part) => (node as Record<string, unknown> | undefined)?.[part], source);
    return typeof value === "string" ? value : key;
  };
}

const t = translator(en);
const german = translator(de);
const LIMITS = { min_interval_min: 15, max_interval_min: 10080, default_interval_min: 180, max_open: 12 };

describe("paceWords", () => {
  it("says an interval the way a person would", () => {
    expect(paceWords(15, t, "en")).toBe("every 15 minutes");
    expect(paceWords(60, t, "en")).toBe("hourly");
    expect(paceWords(180, t, "en")).toBe("every 3 hours");
    expect(paceWords(1440, t, "en")).toBe("daily");
    expect(paceWords(4320, t, "en")).toBe("every 3 days");
    expect(paceWords(10080, t, "en")).toBe("weekly");
  });

  it("keeps a pace the assistant chose in between readable", () => {
    expect(paceWords(90, t, "en")).toBe("every 90 minutes");
    expect(paceWords(150, t, "en")).toBe("every 2.5 hours");
    expect(paceWords(150, german, "de")).toBe("alle 2,5 Stunden"); // i18n-allow: German locale check
  });

  it("speaks German", () => {
    expect(paceWords(15, german, "de")).toBe("alle 15 Minuten"); // i18n-allow: German locale check
    expect(paceWords(60, german, "de")).toBe("stündlich"); // i18n-allow: German locale check
    expect(paceWords(180, german, "de")).toBe("alle 3 Stunden"); // i18n-allow: German locale check
    expect(paceWords(1440, german, "de")).toBe("täglich"); // i18n-allow: German locale check
    expect(paceWords(10080, german, "de")).toBe("wöchentlich"); // i18n-allow: German locale check
    expect(looksWords(180, german, "de")).toBe("sieht alle 3 Stunden nach"); // i18n-allow: German locale check
  });
});

describe("paceOptions", () => {
  it("offers the presets inside the server's limits, capitalised", () => {
    const options = paceOptions(LIMITS, 180, t, "en");
    expect(options.map((option) => Number(option.value))).toEqual([...PACE_CHOICES]);
    expect(options.find((option) => option.value === "180")?.label).toBe("Every 3 hours");
    expect(options[0].label).toBe("Every 15 minutes");
  });

  it("trims both ends and keeps the task's own odd pace", () => {
    const options = paceOptions({ ...LIMITS, min_interval_min: 60, max_interval_min: 1440 }, 240, t, "en");
    expect(options.map((option) => Number(option.value))).toEqual([60, 180, 240, 360, 720, 1440]);
    expect(options.find((option) => option.value === "240")?.label).toBe("Every 4 hours");
  });
});

describe("level and outcome words", () => {
  it("names the level and says what the assistant does at it", () => {
    expect(autonomyName("prepare", t)).toBe("Prepare");
    expect(autonomyDoes("watch", t)).toBe("Only watches");
    expect(mannerLine({ autonomy: "prepare", interval_min: 180 }, t, "en")).toBe("Prepares the next step · looks every 3 hours");
    // A level this build does not know is shown as the server wrote it.
    expect(autonomyName("supervise", t)).toBe("supervise");
  });

  it("puts every outcome in words", () => {
    expect(
      ["quiet", "reported", "prepared", "acted", "asked", "failed", "skipped"].map((outcome) => outcomeWords(outcome, t)),
    ).toEqual(["Nothing new", "Told you", "Prepared something", "Took care of it", "Needs you", "Did not work", "Skipped"]);
    expect(outcomeWords("", t)).toBe("");
    expect(outcomeWords("asked", german)).toBe("Braucht dich"); // i18n-allow: German locale check
    expect(outcomeWords("quiet", german)).toBe("Nichts Neues"); // i18n-allow: German locale check
  });

  it("gives only a look that needs the person or failed a status tone", () => {
    expect(outcomeTone("asked")).toBe("attention");
    expect(outcomeTone("failed")).toBe("fault");
    expect(outcomeTone("reported")).toBe("plain");
  });

  it("joins the outcome and its summary", () => {
    expect(lastFinding({ last_outcome: "reported", last_summary: "CPA rose to 18.40 EUR" }, t)).toBe("Told you: CPA rose to 18.40 EUR");
    expect(lastFinding({ last_outcome: "quiet", last_summary: "" }, t)).toBe("Nothing new");
    expect(lastFinding({ last_outcome: "", last_summary: "" }, t)).toBe("");
  });
});

describe("when it looked and when it looks again", () => {
  const now = new Date(2026, 10, 12, 10, 0).getTime();
  const at = (day: number, hour: number) => new Date(2026, 10, day, hour, 0).getTime();

  it("says later today as a time, the coming days in words, and nothing for a due moment", () => {
    expect(whenAhead(at(12, 17), "de", now)).toBe("17:00");
    expect(whenAhead(at(13, 9), "de", now)).toBe("morgen, 09:00");
    expect(whenAhead(at(13, 9), "en", now)).toMatch(/^tomorrow, 09:00/);
    expect(whenAhead(at(12, 9), "en", now)).toBeNull();
    expect(whenAhead(null, "en", now)).toBeNull();
  });

  it("words the next look of a running task only", () => {
    expect(nextLookLine({ state: "active", next_run_ms: at(12, 17) }, german, "de", now)).toBe("Nächstes Mal: 17:00"); // i18n-allow: German locale check
    expect(nextLookWords({ state: "active", next_run_ms: at(12, 9) }, t, "en", now)).toBe("any moment");
    expect(nextLookLine({ state: "paused", next_run_ms: at(12, 17) }, t, "en", now)).toBeNull();
    expect(nextLookLine({ state: "active", next_run_ms: null }, t, "en", now)).toBeNull();
  });

  it("words the last look, or nothing before the first one", () => {
    expect(lastLookLine({ last_run_ms: at(11, 8) }, t, "en", now)).toBe("Last look: yesterday");
    expect(lastLookLine({ last_run_ms: null }, t, "en", now)).toBeNull();
  });
});
