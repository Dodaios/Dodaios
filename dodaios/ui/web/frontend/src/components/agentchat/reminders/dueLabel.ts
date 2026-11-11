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
