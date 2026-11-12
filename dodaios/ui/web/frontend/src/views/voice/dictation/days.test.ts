import { describe, expect, it } from "vitest";

import { dayKey, dayTitle, groupByDay, matching, timeOfDay } from "./days";
import { testEntry } from "./testEntry";

const WORDS = { today: "Today", yesterday: "Yesterday" };

describe("history days", () => {
  it("puts the newest day first and the newest entry first within a day", () => {
    const days = groupByDay([
      testEntry({ id: "old", created_at: new Date(2026, 4, 1, 9, 0).toISOString() }),
      testEntry({ id: "morning", created_at: new Date(2026, 4, 3, 8, 0).toISOString() }),
      testEntry({ id: "evening", created_at: new Date(2026, 4, 3, 23, 30).toISOString() }),
    ]);

    expect(days.map((day) => day.key)).toEqual(["2026-05-03", "2026-05-01"]);
    expect(days[0].entries.map((entry) => entry.id)).toEqual(["evening", "morning"]);
  });

  it("keeps a late evening on the local day it happened", () => {
    const late = new Date(2026, 4, 3, 23, 59);
    expect(groupByDay([testEntry({ created_at: late.toISOString() })])[0].key).toBe(
      dayKey(late),
    );
  });

  it("gives an unreadable time its own group instead of dropping the entry", () => {
    const days = groupByDay([testEntry({ created_at: "not a date" })]);
    expect(days).toHaveLength(1);
    expect(days[0].entries).toHaveLength(1);
  });

  it("names today and yesterday, and writes out any other date", () => {
    const now = new Date(2026, 4, 3, 12, 0);
    expect(dayTitle("2026-05-03", "en-US", WORDS, now)).toBe("Today");
    expect(dayTitle("2026-05-02", "en-US", WORDS, now)).toBe("Yesterday");
    expect(dayTitle("2026-04-20", "en-US", WORDS, now)).toBe("April 20, 2026");
    expect(dayTitle("2026-04-20", "de-DE", WORDS, now)).toBe("20. April 2026");
  });

  it("gives the time without seconds, and nothing for an unreadable one", () => {
    const stamp = new Date(2026, 4, 3, 16, 12, 45).toISOString();
    expect(timeOfDay(stamp, "de-DE")).toBe("16:12");
    expect(timeOfDay("not a date", "de-DE")).toBe("");
  });

  it("searches the delivered and the heard text, ignoring case", () => {
    const entries = [
      testEntry({ id: "a", text: "Send the report.", raw_text: "um send the report" }),
      testEntry({ id: "b", text: "Call Anna.", raw_text: "call Anna" }),
    ];

    expect(matching(entries, "REPORT").map((entry) => entry.id)).toEqual(["a"]);
    expect(matching(entries, "um ").map((entry) => entry.id)).toEqual(["a"]);
    expect(matching(entries, "  ").map((entry) => entry.id)).toEqual(["a", "b"]);
    expect(matching(entries, "nothing like it")).toEqual([]);
  });
});
