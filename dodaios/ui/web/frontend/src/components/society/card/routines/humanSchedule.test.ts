import { describe, expect, test } from "vitest";
import en from "@/i18n/locales/society/en.json";
import de from "@/i18n/locales/society/de.json";
import { humanSchedule, parseCronField, triggerFamily, zoneOffsetMinutes } from "./humanSchedule";

function translator(bundle: unknown) {
  return (key: string) => {
    const value = key.split(".").reduce<unknown>((node, part) => (node as Record<string, unknown> | undefined)?.[part], bundle);
    return typeof value === "string" ? value : key;
  };
}

const t = translator(en);
// A winter day: Berlin is UTC+1, New York UTC-5, Kolkata UTC+5:30.
const WINTER = new Date(Date.UTC(2026, 0, 14, 12));
const SUMMER = new Date(Date.UTC(2026, 6, 14, 12));
const inBerlin = { t, locale: "en-GB", viewerZone: "Europe/Berlin", now: WINTER };
const say = (trigger: unknown, options: Partial<typeof inBerlin> = {}) => humanSchedule(trigger, { ...inBerlin, ...options });

describe("cron forms", () => {
  test.each([
    ["* * * * *", "Every minute"],
    ["*/15 * * * *", "Every 15 minutes"],
    ["0/10 * * * *", "Every 10 minutes"],
    ["0 * * * *", "Every hour"],
    ["30 * * * *", "Hourly at :30"],
    ["0 */2 * * *", "Every 2 hours"],
    ["15 */6 * * *", "Every 6 hours at :15"],
    ["0 8 * * *", "Daily at 08:00"],
    ["30 7 * * 1-5", "Weekdays at 07:30"],
    ["0 10 * * 6,0", "Weekends at 10:00"],
    ["0 10 * * SAT,SUN", "Weekends at 10:00"],
    ["0 9 * * 1", "Weekly on Monday at 09:00"],
    ["0 9 * * 1,3,5", "Weekly on Monday, Wednesday and Friday at 09:00"],
    ["0 9 * * 7", "Weekly on Sunday at 09:00"],
    ["0 9 * * 5-7", "Weekly on Friday, Saturday and Sunday at 09:00"],
    ["0 9 * * 0-6", "Daily at 09:00"],
    ["*/30 * * * 1-7", "Every 30 minutes"],
    ["0 8,18 * * *", "Daily at 08:00 and 18:00"],
    ["0 9 1 * *", "Monthly on day 1 at 09:00"],
    ["0 9 1,15 * *", "Monthly on day 1 and 15 at 09:00"],
    ["0 9 1 1 *", "Yearly on 1 January at 09:00"],
    ["0 9 * 6-8 *", "Daily at 09:00, only in June, July and August"],
    ["*/30 * * * 1-5", "Every 30 minutes on weekdays"],
    ["@daily", "Daily at 00:00"],
    ["@hourly", "Every hour"],
  ])("%s", (expression, sentence) => {
    expect(say({ type: "cron", expression, timezone: "Europe/Berlin" })).toBe(sentence);
  });

  test("shapes without a sentence are shown raw, never guessed", () => {
    expect(say({ type: "cron", expression: "*/5 9-17 * * 1-5", timezone: "Europe/Berlin" })).toBe("Custom schedule: */5 9-17 * * 1-5");
    expect(say({ type: "cron", expression: "0 9 1 * 1", timezone: "Europe/Berlin" })).toBe("Custom schedule: 0 9 1 * 1");
    expect(say({ type: "cron", expression: "not a cron", timezone: "Europe/Berlin" })).toBe("Custom schedule: not a cron");
    expect(say({ type: "cron", expression: "99 * * * *", timezone: "Europe/Berlin" })).toBe("Custom schedule: 99 * * * *");
  });

  test("field parser expands ranges, lists and steps", () => {
    expect(parseCronField("1-5", 0, 6)).toEqual({ any: false, values: [1, 2, 3, 4, 5] });
    expect(parseCronField("*/20", 0, 59)).toEqual({ any: false, values: [0, 20, 40], step: 20 });
    expect(parseCronField("0-59", 0, 59)).toEqual({ any: true });
    expect(() => parseCronField("5-1", 0, 6)).toThrow();
  });
});

describe("time zones", () => {
  test("a clock time moves into the reader's zone and names the routine's own", () => {
    expect(say({ type: "calendar", local_time: "08:00", timezone: "America/New_York" }))
      .toBe("Daily at 14:00 · 08:00 in New York");
  });

  test("weekdays shift with a time that crosses midnight", () => {
    // Monday 22:00 in New York is Tuesday 04:00 in Berlin.
    expect(say({ type: "cron", expression: "0 22 * * 1", timezone: "America/New_York" }))
      .toBe("Weekly on Tuesday at 04:00 · 22:00 in New York");
  });

  test("daylight saving time is read on the day, not assumed", () => {
    const options = { viewerZone: "UTC" };
    expect(say({ type: "calendar", local_time: "08:00", timezone: "Europe/Berlin" }, { ...options, now: WINTER })).toBe("Daily at 07:00 · 08:00 in Berlin");
    expect(say({ type: "calendar", local_time: "08:00", timezone: "Europe/Berlin" }, { ...options, now: SUMMER })).toBe("Daily at 06:00 · 08:00 in Berlin");
  });

  test("half-hour zones and month days that would change date keep the routine's zone", () => {
    expect(say({ type: "calendar", local_time: "08:00", timezone: "Asia/Kolkata" })).toBe("Daily at 03:30 · 08:00 in Kolkata");
    expect(say({ type: "calendar", local_time: "03:00", timezone: "Asia/Tokyo", month_days: [1] }))
      .toBe("Monthly on day 1 at 03:00 (Tokyo time)");
  });

  test("the same zone reads without any suffix; an unknown zone is named", () => {
    expect(say({ type: "calendar", local_time: "08:00", timezone: "Europe/Berlin", weekdays: [0, 2] })).toBe("Weekly on Monday and Wednesday at 08:00");
    expect(say({ type: "calendar", local_time: "08:00", timezone: "Mars/Olympus" })).toBe("Daily at 08:00 (Olympus time)");
    expect(zoneOffsetMinutes("Mars/Olympus", WINTER)).toBeNull();
    expect(zoneOffsetMinutes("Asia/Kolkata", WINTER)).toBe(330);
  });
});

describe("other triggers", () => {
  test.each([
    [{ type: "every", interval_seconds: 60 }, "Every minute"],
    [{ type: "every", interval_seconds: 3600 }, "Every hour"],
    [{ kind: "every", interval_seconds: 18000 }, "Every 5 hours"],
    [{ type: "every", interval_seconds: 86400 }, "Every day"],
    [{ type: "every", interval_seconds: 172800 }, "Every 2 days"],
    [{ type: "every", interval_seconds: 1800 }, "Every 30 minutes"],
    [{ type: "every", interval_seconds: 45 }, "Every 45 seconds"],
    [{ type: "after_delay", delay_seconds: 7200 }, "Once, in 2 hours"],
    [{ type: "on_event", event_name: "MissionCompleted" }, "When MissionCompleted happens"],
    [{ type: "webhook", provider: "generic" }, "When its webhook is called"],
    [{ type: "webhook", provider: "github" }, "On Github events"],
    [{ type: "event_hook", event_name: "crm.customer.created" }, "On the integration event crm.customer.created"],
    [{ type: "source", source: { kind: "form" } }, "When you start it"],
    [{ type: "source", source: { kind: "file", path: "C:/inbox" } }, "When files change in C:/inbox"],
  ])("%j", (trigger, sentence) => {
    expect(say(trigger)).toBe(sentence);
  });

  test("an anchored daily interval reads its clock time in the reader's zone", () => {
    expect(say({ type: "every", interval_seconds: 86400, start_at: "2026-01-10T07:00:00Z" })).toBe("Daily at 08:00");
  });

  test("a one-time run names its moment", () => {
    expect(say({ type: "at_time", iso_timestamp: "2026-01-20T09:00:00Z" })).toMatch(/^Once, /);
  });

  test("nothing stored reads as nothing; unknown kinds name themselves", () => {
    expect(say(null)).toBe("");
    expect(say({ type: "teleport" })).toBe("Schedule: teleport");
  });

  test("families pick the row icon", () => {
    expect(triggerFamily({ type: "cron" })).toBe("clock");
    expect(triggerFamily({ kind: "every" })).toBe("interval");
    expect(triggerFamily({ type: "webhook" })).toBe("webhook");
    expect(triggerFamily({ type: "source", source: { kind: "form" } })).toBe("manual");
    expect(triggerFamily({ type: "source", source: { kind: "kafka" } })).toBe("source");
    expect(triggerFamily(undefined)).toBe("unknown");
  });
});

test("other languages read naturally, with their own weekday names", () => {
  const options = { ...inBerlin, t: translator(de), locale: "de-DE" };
  expect(humanSchedule({ type: "cron", expression: "30 7 * * 1-5", timezone: "Europe/Berlin" }, options)).toBe("Werktags um 07:30");
  expect(humanSchedule({ type: "cron", expression: "0 9 * * 1,3", timezone: "Europe/Berlin" }, options)).toBe("Wöchentlich am Montag und Mittwoch um 09:00"); // i18n-allow: German locale fixture
  expect(humanSchedule({ type: "every", interval_seconds: 900 }, options)).toBe("Alle 15 Minuten");
});
