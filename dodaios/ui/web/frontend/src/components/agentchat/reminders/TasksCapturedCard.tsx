import { useState } from "react";
import { CalendarClock, ListChecks } from "lucide-react";

import { useT, useUiLanguage } from "@/i18n";
import { forgetMemory } from "@/lib/personalMemoryApi";
import { cn } from "@/lib/utils";
import { dueLabel } from "@/components/layout/SidebarDue";
import type { NoticeItem } from "../reduce";

type Captured = { id: string; text: string; due_at: string | null; reminder: boolean };

function rowsOf(item: NoticeItem): Captured[] {
  const raw = Array.isArray(item.data.items) ? item.data.items : [];
  return raw
    .map((row) => row as Partial<Captured>)
    .filter((row) => typeof row.text === "string" && row.text)
    .map((row) => ({
      id: String(row.id ?? ""),
      text: String(row.text),
      due_at: typeof row.due_at === "string" ? row.due_at : null,
      reminder: row.reminder === true,
    }));
}

/**
 * What a brain dump became: one compact list, a reminder (with its time) or a
 * task per line, and an undo per item that forgets it again
 * (`dodaios/notify/reminders.py`, notice `tasks_captured`). Written only.
 */
export function TasksCapturedCard({ item }: { item: NoticeItem }) {
  const t = useT();
  const locale = useUiLanguage();
  const [undone, setUndone] = useState<Record<string, boolean>>({});
  const [failed, setFailed] = useState<Record<string, boolean>>({});
  const rows = rowsOf(item);
  if (rows.length === 0) return null;
  const now = new Date();
  const undo = (id: string) => {
    void forgetMemory(id).then(
      () => setUndone((s) => ({ ...s, [id]: true })),
      () => setFailed((s) => ({ ...s, [id]: true })),
    );
  };
  const title = rows.length === 1
    ? t("reminders.captured_one")
    : t("reminders.captured_title").replace("{count}", String(rows.length));
  return (
    <div data-message-id={item.id} data-testid="tasks-captured"
      className="mx-auto w-full max-w-[85%] rounded-xl border border-border bg-card px-4 py-3">
      <p className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
        <ListChecks aria-hidden className="h-4 w-4" />
        {title}
      </p>
      <ul className="mt-2 space-y-1">
        {rows.map((row) => {
          const gone = undone[row.id];
          const when = row.due_at ? dueLabel(row.due_at, now, t, locale) : "";
          return (
            <li key={row.id || row.text} data-testid="tasks-captured-row"
              className="flex items-baseline gap-2 text-sm">
              <span className={cn("min-w-0 flex-1", gone && "line-through text-muted-foreground")}>
                <span className="text-foreground">{row.text}</span>
                <span className="ml-2 inline-flex items-center gap-1 text-xs text-foreground-faint">
                  {row.reminder ? <CalendarClock aria-hidden className="h-3 w-3" /> : null}
                  {row.reminder ? when : t("reminders.task")}
                </span>
              </span>
              {row.id ? (
                gone ? (
                  <span className="shrink-0 text-xs text-muted-foreground">{t("reminders.undone")}</span>
                ) : (
                  <button type="button" onClick={() => undo(row.id)} data-testid="tasks-captured-undo"
                    className="shrink-0 rounded px-1 text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                    {failed[row.id] ? t("reminders.failed") : t("reminders.undo")}
                  </button>
                )
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
