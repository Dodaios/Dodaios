import { describe, expect, test } from "vitest";

import {
  dayLabel, itemDetail, itemTitle, itemWhen, reminderItems, reminderSource, sourceName,
} from "@/components/layout/reminderItems";
import { translate } from "@/i18n";
import de from "@/i18n/locales/de.json";
import type { ReminderRow } from "@/lib/remindersApi";

const t = (key: string) => translate(key);
/** German words straight from the catalog, without switching the app's language. */
const tDe = (key: string) => String(key.split(".").reduce<unknown>((node, part) => (node as Record<string, unknown>)?.[part], de) ?? key);

/** Local wall times, so the checks hold in any time zone the tests run in. */
const at = (day: number, hour: number, minute = 0) => new Date(2026, 10, day, hour, minute).toISOString();
const NOW = new Date(2026, 10, 14, 12, 0);
/** ICU writes thin and narrow no-break spaces around "AM" and the dash; the words are what is checked. */
const plain = (text: string) => text.replace(/\s/g, " ");

function row(extra: Partial<ReminderRow>): ReminderRow {
  return { id: "m1", text: "", due_at: at(14, 10, 15), kind: "ephemeral", reminder: false, overdue: true, delivered: true, ...extra };
}

describe("itemWhen", () => {
  test("an appointment reads as its day in words and its span on the person's clock", () => {
    const meeting = row({ start: at(14, 10, 15), end: at(14, 15) });
    expect(plain(itemWhen(meeting, "de", tDe, NOW))).toBe("Heute, 10:15–15:00 Uhr");
    expect(plain(itemWhen(meeting, "en", t, NOW))).toBe("Today, 10:15 AM – 3:00 PM");
    // Never "Due since": an appointment says when it runs.
    expect(itemWhen(meeting, "en", t, NOW)).not.toMatch(/due/i);
  });

  test("a whole day says so, one day or several", () => {
    expect(itemWhen(row({ all_day: true, start: "2026-11-15", end: "2026-11-16" }), "en", t, NOW)).toBe("Tomorrow, all day");
    expect(itemWhen(row({ all_day: true, start: "2026-11-15", end: "2026-11-16" }), "de", tDe, NOW)).toBe("Morgen, ganztägig"); // i18n-allow: the German UI's words
    expect(itemWhen(row({ all_day: true, start: "2026-11-16", end: "2026-11-19" }), "en", t, NOW)).toBe("Mon, Nov 16 – Wed, Nov 18");
  });

  test("an appointment into the next day names both days", () => {
    expect(plain(itemWhen(row({ start: at(14, 22), end: at(15, 1, 30) }), "en", t, NOW))).toBe("Today, 10:00 PM – Tomorrow, 1:30 AM");
  });

  test("a reminder says when it was due", () => {
    const own = row({ reminder: true, due_at: at(13, 18), start: at(13, 18), end: null });
    expect(plain(itemWhen(own, "en", t, NOW))).toBe("Yesterday, 6:00 PM");
    expect(itemWhen(own, "de", tDe, NOW)).toBe("Gestern, 18:00");
  });

  test("days further away read as a short date", () => {
    expect(dayLabel(new Date(2026, 10, 18, 9), "en", NOW)).toBe("Wed, Nov 18");
  });
});

describe("itemTitle and itemDetail", () => {
  test("an entry that only says busy says so instead of showing 'Busy' as its name", () => {
    const busy = row({ busy_only: true, title: "", calendar: "Team availability", start: at(14, 10, 15), end: at(14, 15) });
    expect(itemTitle(busy, t)).toBe("Busy (no details shared)");
    expect(itemTitle(busy, tDe)).toBe("Belegt (keine Details freigegeben)"); // i18n-allow: the German UI's words
    expect(plain(itemDetail(busy, "de", tDe, NOW))).toBe("Heute, 10:15–15:00 Uhr · Team availability");
  });

  test("the place wins over the calendar's name on the second line", () => {
    const dentist = row({ title: "Dentist", location: "Main St 1", calendar: "Family", start: at(14, 9), end: at(14, 9, 30) });
    expect(itemTitle(dentist, t)).toBe("Dentist");
    expect(plain(itemDetail(dentist, "de", tDe, NOW))).toBe("Heute, 09:00–09:30 Uhr · Main St 1");
  });

  test("a title-less event, an older backend's sentence, and a reminder's own text", () => {
    expect(itemTitle(row({ title: "" }), t)).toBe("Untitled event");
    expect(itemTitle(row({ text: "Appointment: Dentist on 2026-11-12 09:00 (Main St 1)." }), t)).toBe("Dentist");
    expect(itemTitle(row({ reminder: true, text: "Take the pizza out" }), t)).toBe("Take the pizza out");
  });
});

describe("sources", () => {
  test("an older backend's rows still say whose they are", () => {
    expect(reminderSource(row({ reminder: true }))).toBe("dodaios");
    expect(reminderSource(row({ reminder: false }))).toBe("google_calendar");
    expect(reminderSource(row({ source: "todoist" }))).toBe("todoist");
  });

  test("names: translated for Google's calendar and the own ones, brand names otherwise", () => {
    expect(sourceName("google_calendar", t)).toBe("Google Calendar");
    expect(sourceName("google_calendar", tDe)).toBe("Google Kalender");
    expect(sourceName("dodaios", t)).toBe("Reminder");
    expect(sourceName("microsoft_todo", t)).toBe("Microsoft To Do");
    expect(sourceName("some_new_service", t)).toBe("Some New Service");
  });
});

describe("reminderItems", () => {
  test("one appointment seen on two calendars is one item that answers for both", () => {
    const rows = [
      row({ id: "v1", busy_only: true, title: "", start: "2026-11-18T18:30:00Z", end: "2026-11-18T19:00:00Z" }),
      row({ id: "v2", busy_only: true, title: "", start: "2026-11-18T19:30:00+01:00", end: "2026-11-18T20:00:00+01:00" }),
      row({ id: "o1", busy_only: true, title: "", start: "2026-11-18T21:00:00+01:00", end: "2026-11-18T22:00:00+01:00" }),
    ];
    const items = reminderItems(rows);
    expect(items.map((item) => item.ids)).toEqual([["v1", "v2"], ["o1"]]);
    expect(items[0]).toMatchObject({ source: "google_calendar", appointment: true });
  });

  test("a reminder and an appointment with the same words stay two", () => {
    const items = reminderItems([
      row({ id: "a", title: "Dentist", text: "Appointment: Dentist on 2026-11-14 10:15." }),
      row({ id: "b", reminder: true, title: "Dentist", text: "Dentist" }),
    ]);
    expect(items.map((item) => [item.source, item.appointment])).toEqual([["google_calendar", true], ["dodaios", false]]);
  });
});
