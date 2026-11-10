import { useEffect, useState } from "react";
import { CalendarClock } from "lucide-react";

import { useT, useUiLanguage } from "@/i18n";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";

/** What falls due soon, from the personal memory (plans, deadlines, appointments). */
type Due = { id: string; text: string; due_at: string | null };

const DAYS = 7;
const MAX_ROWS = 4;
const REFRESH_MS = 5 * 60_000;

function dayStart(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

/** "Overdue", "Today", "Tomorrow" or a short weekday and date. */
export function dueLabel(dueAt: string, now: Date, t: (key: string) => string, locale: string): string {
  const due = new Date(dueAt);
  if (Number.isNaN(due.getTime())) return "";
  const days = Math.round((dayStart(due) - dayStart(now)) / 86_400_000);
  const hasTime = dueAt.length > 10;
  const time = hasTime ? " " + due.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" }) : "";
  if (days < 0 || (days === 0 && hasTime && due.getTime() < now.getTime())) return t("sidebar.due.overdue");
  if (days === 0) return t("sidebar.due.today") + time;
  if (days === 1) return t("sidebar.due.tomorrow") + time;
  return due.toLocaleDateString(locale, { weekday: "short", day: "numeric", month: "short" });
}

/**
 * "Coming up": the next few things the assistant knows fall due — a
 * deadline, an appointment, a plan — read from the personal memory
 * (`/api/memory/vault/upcoming`). Absent when nothing is due, so the
 * sidebar stays quiet on an empty week. A row opens the memory page.
 */
export default function SidebarDue() {
  const t = useT();
  const locale = useUiLanguage();
  const setActive = useEventStore((s) => s.setActiveSection);
  const [items, setItems] = useState<Due[]>([]);
  useEffect(() => {
    let live = true;
    const load = () => {
      void fetch(`/api/memory/vault/upcoming?days=${DAYS}`)
        .then((r) => (r.ok ? r.json() : null))
        .then((body: { items?: Due[] } | null) => { if (live && body?.items) setItems(body.items); },
          () => undefined);
    };
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => { live = false; clearInterval(timer); };
  }, []);
  const rows = items.filter((item) => item.due_at && item.text).slice(0, MAX_ROWS);
  if (rows.length === 0) return null;
  const now = new Date();
  return (
    <section className="mt-5 px-2" aria-label={t("sidebar.due.title")} data-testid="sidebar-due">
      <h2 className="px-3 pb-1.5 text-sm text-muted-foreground">{t("sidebar.due.title")}</h2>
      <ul className="space-y-px">
        {rows.map((item) => {
          const label = dueLabel(item.due_at as string, now, t, locale);
          const overdue = label === t("sidebar.due.overdue");
          return (
            <li key={item.id}>
              <button type="button" onClick={() => setActive("memory")} title={item.text}
                data-testid="sidebar-due-row"
                className="flex w-full items-start gap-3 rounded-lg px-3 py-1.5 text-left transition-colors hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                <CalendarClock aria-hidden strokeWidth={1.75} className="mt-0.5 h-[18px] w-[18px] shrink-0 text-muted-foreground" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm text-foreground">{item.text}</span>
                  <span className={cn("block text-xs", overdue ? "text-primary" : "text-foreground-faint")}>{label}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
