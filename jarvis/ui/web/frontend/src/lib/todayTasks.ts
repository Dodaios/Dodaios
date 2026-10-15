import type { PersonalTask } from "@/types/today";

/**
 * Where an open task belongs on the Today page. Same rule as the store
 * (`TaskStore.bucket`): overdue, due today, high priority, everything else.
 * The server already returns open tasks in this order, so grouping keeps it.
 */
export type TaskGroup = "overdue" | "due_today" | "high" | "other";

export const TODAY_GROUPS: readonly TaskGroup[] = ["overdue", "due_today", "high"];

export function taskGroup(task: PersonalTask, today: string): TaskGroup {
  if (task.due_date) {
    // ISO dates compare correctly as text.
    if (task.due_date < today) return "overdue";
    if (task.due_date === today) return "due_today";
  }
  return task.priority === "high" ? "high" : "other";
}

export interface SplitTasks {
  /** Overdue, due today and high priority — the Today page. */
  today: PersonalTask[];
  /** Every open task, Today ones first. */
  open: PersonalTask[];
  /** Completed tasks, newest first. */
  done: PersonalTask[];
}

/** Split the server's `view=all` answer (open first, then done) without reordering. */
export function splitTasks(tasks: readonly PersonalTask[], today: string): SplitTasks {
  const open = tasks.filter((task) => task.status === "open");
  return {
    today: open.filter((task) => TODAY_GROUPS.includes(taskGroup(task, today))),
    open,
    done: tasks.filter((task) => task.status === "done"),
  };
}

/** Consecutive runs of one group, in the order given. */
export function groupRuns(
  tasks: readonly PersonalTask[],
  today: string,
): { group: TaskGroup; tasks: PersonalTask[] }[] {
  const runs: { group: TaskGroup; tasks: PersonalTask[] }[] = [];
  for (const task of tasks) {
    const group = taskGroup(task, today);
    const last = runs[runs.length - 1];
    if (last && last.group === group) last.tasks.push(task);
    else runs.push({ group, tasks: [task] });
  }
  return runs;
}

/** A `YYYY-MM-DD` date as a local calendar day (no timezone shift). */
export function parseDay(value: string): Date {
  const [year, month, day] = value.split("-").map(Number);
  return new Date(year, (month || 1) - 1, day || 1);
}

/** Today's local date as `YYYY-MM-DD`, for a date input before the server answered. */
export function localDayString(now: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}
