import { useState } from "react";
import { BellRing, Check } from "lucide-react";

import { useT, useUiLanguage } from "@/i18n";
import { markReminderDone, snoozeReminder } from "@/lib/remindersApi";
import { cn } from "@/lib/utils";
import type { NoticeItem } from "../reduce";

/** The snooze presets the card offers; "tomorrow" is resolved by the backend. */
const SNOOZES: readonly { key: string; minutes?: number; until?: string }[] = [
  { key: "reminders.snooze_15", minutes: 15 },
  { key: "reminders.snooze_1h", minutes: 60 },
  { key: "reminders.snooze_3h", minutes: 180 },
  { key: "reminders.snooze_tomorrow", until: "tomorrow" },
];

type State = { kind: "open" } | { kind: "done" } | { kind: "snoozed"; until: string } | { kind: "failed" };

/**
 * A reminder that has come due, as a quiet card in the conversation
 * (`dodaios/notify/reminders.py`, notice `reminder_due`): the text, Done, and
 * four snooze choices. Written only, never spoken. A desktop notification
 * carried the same text while the app was in the background; clicking it
 * lands here.
 */
export function ReminderDueNotice({ item }: { item: NoticeItem }) {
  const t = useT();
  const locale = useUiLanguage();
  const [state, setState] = useState<State>({ kind: "open" });
  const memoryId = String(item.data.memory_id ?? "");
  const text = String(item.data.text ?? item.text ?? "");
  if (!text) return null;

  const done = () => {
    void markReminderDone(memoryId).then(
      () => setState({ kind: "done" }),
      () => setState({ kind: "failed" }),
    );
  };
  const snooze = (choice: (typeof SNOOZES)[number]) => {
    void snoozeReminder(memoryId, choice.until ? { until: choice.until } : { minutes: choice.minutes }).then(
      (row) => setState({ kind: "snoozed", until: formatWhen(row.due_at, locale) }),
      () => setState({ kind: "failed" }),
    );
  };

  return (
    <div data-message-id={item.id} data-testid="reminder-due"
      className="mx-auto w-full max-w-[85%] rounded-xl border border-border bg-card px-4 py-3">
      <div className="flex items-start gap-3">
        <BellRing aria-hidden className={cn("mt-0.5 h-4 w-4 shrink-0", state.kind === "open" ? "text-primary" : "text-muted-foreground")} />
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium text-muted-foreground">{t("reminders.due_title")}</p>
          <p className={cn("text-sm text-foreground", state.kind === "done" && "line-through text-muted-foreground")}>{text}</p>
        </div>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-1.5 pl-7 text-xs">
        {state.kind === "open" && memoryId ? (
          <>
            <button type="button" onClick={done} data-testid="reminder-done"
              className="inline-flex items-center gap-1 rounded-md bg-primary px-2.5 py-1 font-medium text-primary-foreground hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              <Check aria-hidden className="h-3 w-3" />
              {t("reminders.done")}
            </button>
            <span className="ml-1 text-muted-foreground">{t("reminders.snooze")}:</span>
            {SNOOZES.map((choice) => (
              <button key={choice.key} type="button" onClick={() => snooze(choice)} data-testid="reminder-snooze"
                className="rounded-md border border-border px-2 py-1 text-foreground hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                {t(choice.key)}
              </button>
            ))}
          </>
        ) : null}
        {state.kind === "done" ? <span className="text-muted-foreground">{t("reminders.marked_done")}</span> : null}
        {state.kind === "snoozed" ? (
          <span className="text-muted-foreground">{t("reminders.snoozed_until").replace("{when}", state.until)}</span>
        ) : null}
        {state.kind === "failed" ? <span role="alert" className="text-destructive">{t("reminders.failed")}</span> : null}
      </div>
    </div>
  );
}

function formatWhen(dueAt: string | null, locale: string): string {
  if (!dueAt) return "";
  const date = new Date(dueAt);
  if (Number.isNaN(date.getTime())) return dueAt;
  const sameDay = date.toDateString() === new Date().toDateString();
  const time = date.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
  if (sameDay) return time;
  return `${date.toLocaleDateString(locale, { weekday: "short", day: "numeric", month: "short" })} ${time}`;
}
