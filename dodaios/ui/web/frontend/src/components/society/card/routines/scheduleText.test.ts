import { describe, expect, it } from "vitest";
import { parseScheduleText } from "./scheduleText";

const ZONE = "Europe/Berlin";
const parse = (text: string) => parseScheduleText(text, ZONE);

describe("a schedule typed in plain words", () => {
  it("reads weekdays, single days and every day at a clock time", () => {
    expect(parse("every weekday at 7")).toEqual({ type: "calendar", local_time: "07:00", timezone: ZONE, weekdays: [0, 1, 2, 3, 4] });
    expect(parse("Every Monday at 9am")).toEqual({ type: "calendar", local_time: "09:00", timezone: ZONE, weekdays: [0] });
    expect(parse("tuesdays and thursdays 18:30")).toEqual({ type: "calendar", local_time: "18:30", timezone: ZONE, weekdays: [1, 3] });
    expect(parse("daily at 8:15")).toEqual({ type: "calendar", local_time: "08:15", timezone: ZONE });
    expect(parse("at 7 in the evening")).toEqual({ type: "calendar", local_time: "19:00", timezone: ZONE });
    expect(parse("weekends at noon")).toEqual({ type: "calendar", local_time: "12:00", timezone: ZONE, weekdays: [5, 6] });
  });

  it("reads intervals", () => {
    expect(parse("every 2 hours")).toEqual({ type: "every", interval_seconds: 7_200 });
    expect(parse("every 30 minutes")).toEqual({ type: "every", interval_seconds: 1_800 });
    expect(parse("hourly")).toEqual({ type: "every", interval_seconds: 3_600 });
  });

  it("reads the other UI languages' common shapes", () => {
    expect(parse("jeden Werktag um 7")).toEqual({ type: "calendar", local_time: "07:00", timezone: ZONE, weekdays: [0, 1, 2, 3, 4] }); // i18n-allow: input vocabulary
    expect(parse("alle 3 Stunden")).toEqual({ type: "every", interval_seconds: 10_800 }); // i18n-allow: input vocabulary
    expect(parse("cada lunes a las 9")).toEqual({ type: "calendar", local_time: "09:00", timezone: ZONE, weekdays: [0] }); // i18n-allow: input vocabulary
    expect(parse("am Montag um 7 abends")).toEqual({ type: "calendar", local_time: "19:00", timezone: ZONE, weekdays: [0] }); // i18n-allow: input vocabulary
  });

  it("does not guess when the words name no clear time", () => {
    expect(parse("")).toBeNull();
    expect(parse("every Monday")).toBeNull();
    expect(parse("when the inbox is full")).toBeNull();
    expect(parse("at 25:00")).toBeNull();
    // Past what the scheduler takes (one year).
    expect(parse("every 400 days")).toBeNull();
  });
});
