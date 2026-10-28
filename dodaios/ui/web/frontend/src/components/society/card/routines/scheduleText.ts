/**
 * A schedule typed in plain words ("every weekday at 7", "every 2 hours",
 * "jeden Montag um 9") as the trigger the scheduler stores
 * (`dodaios/tasks/schema.py`): `calendar` with a local time, the reader's
 * zone and optional weekdays (0 = Monday), or `every` with an interval.
 * Returns null when the words do not name a schedule clearly; the form then
 * offers the detailed editor or the chat instead of guessing.
 *
 * The vocabulary covers the UI languages (English, German, Spanish,
 * Portuguese) for the common shapes only; anything else goes to the chat.
 */

export type ScheduleTrigger =
  | { type: "calendar"; local_time: string; timezone: string; weekdays?: number[] }
  | { type: "every"; interval_seconds: number };

const DAY_WORDS: [RegExp, number][] = [
  [/\b(?:mon(?:day)?s?|montags?|lunes|segunda(?:s|-feira)?)\b/, 0], // i18n-allow: input vocabulary
  [/\b(?:tue(?:s(?:day)?)?s?|dienstags?|martes|terças?(?:-feira)?|tercas?)\b/, 1], // i18n-allow: input vocabulary
  [/\b(?:wed(?:nesday)?s?|mittwochs?|miércoles|miercoles|quartas?(?:-feira)?)\b/, 2], // i18n-allow: input vocabulary
  [/\b(?:thu(?:rs(?:day)?)?s?|donnerstags?|jueves|quintas?(?:-feira)?)\b/, 3], // i18n-allow: input vocabulary
  [/\b(?:fri(?:day)?s?|freitags?|viernes|sextas?(?:-feira)?)\b/, 4], // i18n-allow: input vocabulary
  [/\b(?:sat(?:urday)?s?|samstags?|sábados?|sabados?)\b/, 5], // i18n-allow: input vocabulary
  [/\b(?:sun(?:day)?s?|sonntags?|domingos?)\b/, 6], // i18n-allow: input vocabulary
];

const WEEKDAYS = /\b(?:week ?days?|workdays?|werktags?|werktagen|wochentags?|wochentagen|(?:días|dias) (?:laborables|úteis|uteis)|entre semana|mon(?:day)?\s*(?:-|to|through|bis)\s*fri(?:day)?|montag\s*(?:-|bis)\s*freitag)\b/; // i18n-allow: input vocabulary
const WEEKENDS = /\b(?:weekends?|wochenendes?|fin(?:es)? de semana|fim de semana|fins de semana)\b/; // i18n-allow: input vocabulary
const DAILY = /\b(?:every ?day|daily|each day|täglich|taeglich|jeden tag|todos los días|todos los dias|cada día|cada dia|todos os dias|diariamente)\b/; // i18n-allow: input vocabulary
const HOURLY = /\b(?:every hour|hourly|each hour|stündlich|stuendlich|jede stunde|cada hora|de hora a hora)\b/; // i18n-allow: input vocabulary
const INTERVAL = /\b(?:every|each|alle|cada)\s+(\d{1,3})\s*(m|mins?|minutes?|minuten|minutos|h|hrs?|hours?|stunden|horas|d|days?|tage|tagen|días|dias)\b/; // i18n-allow: input vocabulary
const NOON = /\b(?:noon|midday|mittags?|mediodía|mediodia|meio-dia)\b/; // i18n-allow: input vocabulary
const EVENING = /\b(?:evening|night|tonight|pm|abends?|nachts?|tarde|noche|noite)\b/; // i18n-allow: input vocabulary
/** No bare "am": in German it means "on" ("am Montag"); "7am" is read by the clock itself. */
const MORNING = /\b(?:morning|morgens|früh|frueh|mañana|manana|manhã|manha)\b/; // i18n-allow: input vocabulary
/** A clock time: "7", "7:30", "07.30", "7h30", "19 uhr", "7am", "at 7". */
const CLOCK = /(?:^|\s|at\s|um\s|a las\s|às\s|as\s|@)(\d{1,2})(?:[:.h](\d{2}))?\s*(am|pm|a\.m\.|p\.m\.|uhr|h)?(?=$|[\s,.;!?])/; // i18n-allow: input vocabulary

function unitSeconds(unit: string): number {
  if (/^(?:m|mins?|minutes?|minuten|minutos)$/.test(unit)) return 60; // i18n-allow: input vocabulary
  if (/^(?:h|hrs?|hours?|stunden|horas)$/.test(unit)) return 3_600; // i18n-allow: input vocabulary
  return 86_400;
}

function clockOf(text: string): string | null {
  if (NOON.test(text)) return "12:00";
  const match = CLOCK.exec(text);
  if (!match) return null;
  let hours = Number(match[1]);
  const minutes = match[2] ? Number(match[2]) : 0;
  const suffix = (match[3] ?? "").replace(/\./g, "");
  if (hours > 23 || minutes > 59) return null;
  if (suffix === "pm" && hours < 12) hours += 12;
  else if (suffix === "am" && hours === 12) hours = 0;
  else if (!suffix && hours < 12 && EVENING.test(text) && !MORNING.test(text)) hours += 12;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
}

function viewerZone(): string {
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"; } catch { return "UTC"; }
}

/** The trigger for `text`, or null when it does not name a schedule clearly. */
export function parseScheduleText(text: string, timezone: string = viewerZone()): ScheduleTrigger | null {
  const clean = ` ${text.toLowerCase().replace(/\s+/g, " ").trim()} `;
  if (!clean.trim()) return null;
  const interval = INTERVAL.exec(clean);
  if (interval) {
    const seconds = Number(interval[1]) * unitSeconds(interval[2]);
    // The scheduler takes a gap of one minute up to a year.
    return seconds >= 60 && seconds <= 366 * 86_400 ? { type: "every", interval_seconds: seconds } : null;
  }
  if (HOURLY.test(clean)) return { type: "every", interval_seconds: 3_600 };
  // Words that name days are taken out before the clock is read, so "Monday 9" is 9 o'clock.
  let days: number[] = [];
  if (WEEKDAYS.test(clean)) days = [0, 1, 2, 3, 4];
  else if (WEEKENDS.test(clean)) days = [5, 6];
  else {
    for (const [pattern, day] of DAY_WORDS) if (pattern.test(clean)) days.push(day);
  }
  const time = clockOf(clean.replace(INTERVAL, " "));
  if (!time) return null;
  const daily = DAILY.test(clean) || days.length === 0 || days.length === 7;
  return daily
    ? { type: "calendar", local_time: time, timezone }
    : { type: "calendar", local_time: time, timezone, weekdays: [...new Set(days)].sort((a, b) => a - b) };
}
