import { useEffect, useMemo, useState } from "react";
import { Check } from "lucide-react";

import { fill, useT, useUiLanguage } from "@/i18n";
import { openExternalUrl } from "@/lib/openExternal";
import { markReminderDone, snoozeReminder, type ReminderRow } from "@/lib/remindersApi";
import { useEventStore } from "@/store/events";

import { REPLY_PROSE } from "../LeadReply";
import type { NoticeItem, TimelineItem } from "../reduce";
import { dropDueReminder, formatDue, refreshDueReminders, useDueRemindersStore, watchDueReminders } from "./dueReminders";
import { itemPlace, itemTitle, itemWhen, OWN_SOURCE, reminderItems, sourceName, type ReminderItem } from "./reminderItems";
import { ChatMarkdown } from "../ChatMarkdown";

/**
 * A reminder or calendar appointment that came due, said by the assistant in
 * its chat as a message of its own: "Your break runs until 10:45, then you
 * have half an hour for mail." The words come with the notice (`voice`,
 * written by `dodaios/agent_chat/proactive_voice.py` in the person's
 * language); under them, small, what fits each item while it is still open.
 * An appointment opens in its calendar or is dismissed; a reminder is ticked
 * off, or snoozed once "Later" shows the choices.
 *
 * The scheduler (`dodaios/notify/reminders.py`) posts one `reminder_due`
 * notice per item; several told in one go are one message (the first notice
 * carries the words, the rest `voice_covered`). The lead reads the same
 * notice in its history, so the person can simply answer it ("move it to
 * tomorrow"). A notice from before the words were written reads as one
 * plain sentence per item.
 *
 * The actions show only while the item is still open (`dueReminders`): the
 * message stays as what was said, and an item ticked off, snoozed or over
 * keeps its words without the actions.
 */

export const REMINDER_DUE_KIND = "reminder_due";

/** The snooze choices a reminder offers; "tomorrow" is resolved by the backend. */
const SNOOZES: readonly { key: string; minutes?: number; until?: string }[] = [
  { key: "reminders.snooze_15", minutes: 15 },
  { key: "reminders.snooze_1h", minutes: 60 },
  { key: "reminders.snooze_3h", minutes: 180 },
  { key: "reminders.snooze_tomorrow", until: "tomorrow" },
];

/** A word that does something. */
const ACTION =
  "-mx-1 rounded px-1 py-0.5 font-medium text-accent hover:underline disabled:opacity-60 " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
/** The quieter second word beside it. */
const QUIET_ACTION =
  "-mx-1 rounded px-1 py-0.5 text-muted-foreground hover:text-foreground disabled:opacity-60 " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/** The notices of one message: the first carries the rest that were told right after it. */
const GROUP = "reminder_group";

function isReminderNotice(item: TimelineItem | undefined): item is NoticeItem {
  return item?.type === "notice" && item.kind === REMINDER_DUE_KIND;
}

/**
 * Whether `item` belongs to the message of `last`. A notice the assistant
 * worded together with the one before it says so (`voice_covered`); a notice
 * with words of its own is a message of its own (a break told at 13:00 is not
 * part of what was said at 12:26). Notices from before the words were written
 * fold when they follow each other, as they always did.
 */
function joins(last: NoticeItem, item: NoticeItem): boolean {
  if (item.data.voice_covered === true) return true;
  return !item.data.voice && !last.data.voice;
}

/**
 * Reminders told together are one message: the first notice of a run carries
 * the others (`data.reminder_group`). The same array when there is nothing to
 * fold.
 */
export function foldReminderNotices(items: TimelineItem[]): TimelineItem[] {
  if (!items.some((item, index) => isReminderNotice(item) && isReminderNotice(items[index + 1]))) return items;
  const out: TimelineItem[] = [];
  for (const item of items) {
    const last = out[out.length - 1];
    if (isReminderNotice(item) && isReminderNotice(last) && joins(last, item)) {
      const group = (last.data[GROUP] as NoticeItem[] | undefined) ?? [last];
      out[out.length - 1] = { ...last, data: { ...last.data, [GROUP]: [...group, item] } };
      continue;
    }
    out.push(item);
  }
  return out;
}

const text = (value: unknown): string => (typeof value === "string" ? value : "");

/** How the calendar sync words an appointment memory ("Appointment: Dentist on 2026-11-12 09:00."). */
const CALENDAR_TEXT = /^Appointment:\s/;

/**
 * The item as the API lists it, from what its notice carries; an older notice
 * has only its text. Only an entry from a calendar is an appointment: any
 * other dated memory that came due (a task, a plan with a date) is the
 * person's own, ticked off or snoozed like a reminder, never "from your
 * Google Calendar".
 */
export function noticeRow(item: NoticeItem): ReminderRow {
  const d = item.data;
  const body = text(d.text) || item.text;
  const source = text(d.source);
  const calendar = source ? source !== OWN_SOURCE : CALENDAR_TEXT.test(body);
  return {
    id: text(d.memory_id),
    text: body,
    due_at: text(d.due_at) || null,
    kind: "",
    reminder: d.reminder === true || !calendar,
    overdue: true,
    delivered: true,
    source: source || (calendar ? undefined : OWN_SOURCE),
    title: typeof d.title === "string" ? d.title : undefined,
    busy_only: d.busy_only === true,
    start: text(d.start) || null,
    end: text(d.end) || null,
    all_day: d.all_day === true,
    calendar: text(d.calendar),
    location: text(d.location),
    url: text(d.url),
  };
}

type Settled = { kind: "done" } | { kind: "dismissed" } | { kind: "snoozed"; when: string };

/** What fits one item, while it is still open; what became of it once answered here. */
function ItemActions({ item, service, open, label }: {
  item: ReminderItem; service: string; open: boolean;
  /** The item's name before its actions, when the message tells several. */
  label?: string;
}) {
  const t = useT();
  const locale = useUiLanguage();
  const [busy, setBusy] = useState(false);
  const [later, setLater] = useState(false);
  const [settled, setSettled] = useState<Settled | null>(null);
  const { row, ids, appointment } = item;

  if (settled) {
    const words = settled.kind === "snoozed" ? fill(t("reminders.snoozed_until"), { when: settled.when })
      : t(settled.kind === "done" ? "reminders.settled_done" : "reminders.settled_dismissed");
    return (
      <span className="flex items-center gap-1 text-xs text-muted-foreground" data-testid="reminder-settled">
        {label ? <span className="mr-1 min-w-0 truncate">{label}</span> : null}
        <Check aria-hidden className="h-3 w-3 shrink-0" />{words}
      </span>
    );
  }
  if (!open) return null;

  const settle = (work: Promise<Settled>) => {
    setBusy(true);
    void work.then(
      (outcome) => {
        for (const id of ids) dropDueReminder(id);
        setSettled(outcome);
        void refreshDueReminders();
      },
      () => {
        setBusy(false);
        useEventStore.getState().pushToast("error", t("reminders.failed"));
      },
    );
  };
  const done = () => settle(Promise.all(ids.map((id) => markReminderDone(id)))
    .then((): Settled => ({ kind: appointment ? "dismissed" : "done" })));
  const snooze = (choice: (typeof SNOOZES)[number]) => settle(
    Promise.all([
      snoozeReminder(row.id, choice.until ? { until: choice.until } : { minutes: choice.minutes }),
      ...ids.filter((id) => id !== row.id).map((id) => markReminderDone(id)),
    ]).then(([moved]): Settled => ({ kind: "snoozed", when: formatDue(moved.due_at, locale) })),
  );

  return (
    <>
      <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs" data-testid="reminder-actions">
        {label ? <span className="min-w-0 max-w-[16rem] truncate text-muted-foreground" data-testid="reminder-label">{label}</span> : null}
        {appointment ? (
          <>
            {row.url && (
              <button type="button" onClick={() => void openExternalUrl(row.url ?? "")} data-testid="reminder-open" className={ACTION}>
                {fill(t("reminders.open_in"), { service })}
              </button>
            )}
            <button type="button" onClick={done} disabled={busy} data-testid="reminder-dismiss" className={row.url ? QUIET_ACTION : ACTION}>
              {t("reminders.dismiss")}
            </button>
          </>
        ) : (
          <>
            <button type="button" onClick={done} disabled={busy} data-testid="reminder-done" className={ACTION}>
              {t("reminders.done")}
            </button>
            <button type="button" onClick={() => setLater((value) => !value)} disabled={busy} aria-expanded={later}
              data-testid="reminder-later" className={QUIET_ACTION}>
              {t("reminders.snooze")}
            </button>
          </>
        )}
      </span>
      {later && (
        <span role="group" aria-label={t("reminders.snooze_label")} className="mt-1.5 flex flex-wrap items-center gap-1 text-xs">
          <span className="mr-1 text-muted-foreground">{t("reminders.snooze_label")}</span>
          {SNOOZES.map((choice) => (
            <button key={choice.key} type="button" onClick={() => snooze(choice)} disabled={busy} data-testid="reminder-snooze"
              className="rounded-md px-1.5 py-0.5 text-foreground ring-1 ring-inset ring-border hover:bg-secondary disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              {t(choice.key)}
            </button>
          ))}
        </span>
      )}
    </>
  );
}

/**
 * What a notice from before the assistant wrote its own words says: one
 * plain sentence per item, its title and when it runs.
 */
function plainWords(items: ReminderItem[], locale: string, t: (key: string) => string): string {
  return items.map((entry) => {
    const when = itemWhen(entry.row, locale, t);
    const place = itemPlace(entry.row);
    const title = itemTitle(entry.row, t);
    return fill(t(when ? "reminders.say_item" : "reminders.say_title"), {
      title, when: [when, place].filter(Boolean).join(" · "),
    });
  }).join(" ");
}

/** The message's items: one per thing told, the same item seen twice folded into one. */
function messageItems(item: NoticeItem, notices: NoticeItem[]): ReminderItem[] {
  const items = reminderItems(notices.map(noticeRow));
  if (items.length) return items;
  // A notice too old to carry an id or a title still says its sentence.
  const sentence = text(item.data.text) || item.text;
  if (!sentence) return [];
  return [{ key: item.id, row: { ...noticeRow(item), title: sentence }, ids: [], source: "dodaios", appointment: false }];
}

export function ReminderDueMessage({ item }: { item: NoticeItem }) {
  const t = useT();
  const locale = useUiLanguage();
  const notices = useMemo(() => (item.data[GROUP] as NoticeItem[] | undefined) ?? [item], [item]);
  const items = useMemo(() => messageItems(item, notices), [item, notices]);
  const openRows = useDueRemindersStore((s) => s.items);
  const loaded = useDueRemindersStore((s) => s.loaded);
  useEffect(() => watchDueReminders(), []);
  if (!items.length) return null;
  const open = (entry: ReminderItem) => loaded && entry.ids.some((id) => openRows.some((row) => row.id === id));
  const serviceOf = (entry: ReminderItem) => sourceName(entry.source, t);
  const words = notices.map((notice) => text(notice.data.voice)).find(Boolean) || plainWords(items, locale, t);
  const several = items.length > 1;
  return (
    <div className="lead-turn" data-testid="reminder-message" data-look="lead" data-message-id={item.id}>
      {/* A desktop notification of a later item in the message lands here too. */}
      {notices.slice(1).map((notice) => <span key={notice.id} data-message-id={notice.id} hidden />)}
      <div className="lead-face-lane" aria-hidden />
      <div className="lead-turn-body">
        <div className="lead-bubbles">
          <div className="lead-bubble jarvis-chat-in">
            <div className={REPLY_PROSE} data-testid="reminder-words"><ChatMarkdown text={words} /></div>
            <div className="mt-1.5 flex flex-col gap-1 empty:hidden">
              {items.map((entry) => (
                <ItemActions key={entry.key} item={entry} service={serviceOf(entry)} open={open(entry)}
                  label={several ? itemTitle(entry.row, t) : undefined} />
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
