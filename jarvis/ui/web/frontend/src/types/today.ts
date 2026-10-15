/**
 * The person's own task list — mirror of `jarvis/today/store.py` and the REST
 * models in `jarvis/ui/web/today_routes.py`. The three vocabularies below are
 * parity-tested against the Python side (tests/unit/today/test_frontend_parity.py).
 */

export const TASK_PRIORITIES = ["high", "normal", "low"] as const;
export const TASK_STATUSES = ["open", "done"] as const;
export const TASK_VIEWS = ["today", "open", "done", "all"] as const;

export type TaskPriority = (typeof TASK_PRIORITIES)[number];
export type TaskStatus = (typeof TASK_STATUSES)[number];
export type TaskView = (typeof TASK_VIEWS)[number];

/** Same limits as the store; the inputs stop there instead of failing on save. */
export const TASK_TITLE_MAX_CHARS = 200;
export const TASK_NOTES_MAX_CHARS = 2000;

export interface PersonalTask {
  id: string;
  title: string;
  notes: string | null;
  priority: TaskPriority;
  /** A calendar date, `YYYY-MM-DD`, or null. */
  due_date: string | null;
  status: TaskStatus;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface PersonalTaskList {
  view: TaskView;
  /** The server's local date, `YYYY-MM-DD` — what "overdue" is measured against. */
  today: string;
  tasks: PersonalTask[];
}

export interface NewPersonalTask {
  title: string;
  notes?: string | null;
  priority?: TaskPriority;
  due_date?: string | null;
}

export type PersonalTaskChanges = Partial<
  Pick<PersonalTask, "title" | "notes" | "priority" | "due_date">
>;
