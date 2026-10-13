import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { createPortal } from "react-dom";
import {
  CalendarCheck,
  CalendarDays,
  Check,
  Loader2,
  Pencil,
  Plus,
  RotateCcw,
  Trash2,
  X,
} from "lucide-react";

import { ViewHeader } from "@/views/ChatsView";
import { Button } from "@/components/ui/button";
import { useTodayTaskActions, useTodayTasks } from "@/hooks/useTodayTasks";
import { fill, useT, useUiLanguage } from "@/i18n";
import {
  groupRuns,
  localDayString,
  parseDay,
  splitTasks,
  taskGroup,
  type TaskGroup,
} from "@/lib/todayTasks";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";
import {
  TASK_NOTES_MAX_CHARS,
  TASK_PRIORITIES,
  TASK_TITLE_MAX_CHARS,
  type PersonalTask,
  type TaskPriority,
} from "@/types/today";

/**
 * "Today" section — the person's own task list (`/api/today/tasks`, backed by
 * `jarvis/today`). The Today tab shows what is overdue, due today or high
 * priority; "Open" lists every open task and "Done" the completed ones. Tasks
 * are added, edited, completed, reopened and deleted here, and the list
 * refreshes on its own, so a task added by voice or chat appears without a
 * reload. Nothing on this page calls a model.
 */
type Tab = "today" | "open" | "done";

const inputClass =
  "w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary";

const PRIORITY_STYLE: Record<TaskPriority, string> = {
  high: "border-destructive/40 bg-destructive/10 text-destructive",
  normal: "border-border bg-muted/60 text-muted-foreground",
  low: "border-border/60 bg-transparent text-muted-foreground",
};

const GROUP_LABEL: Record<TaskGroup, string> = {
  overdue: "today.group_overdue",
  due_today: "today.group_due_today",
  high: "today.group_high",
  other: "today.group_other",
};

export function TodayView() {
  const t = useT();
  const lang = useUiLanguage();
  const pushToast = useEventStore((s) => s.pushToast);
  const { data, isLoading, error } = useTodayTasks();
  const actions = useTodayTaskActions();
  const [tab, setTab] = useState<Tab>("today");
  const [editing, setEditing] = useState<PersonalTask | null>(null);

  const today = data?.today ?? localDayString();
  const split = useMemo(() => splitTasks(data?.tasks ?? [], today), [data, today]);
  const shown = split[tab];

  const longDate = useMemo(
    () =>
      new Intl.DateTimeFormat(lang, { weekday: "long", day: "numeric", month: "long" }).format(
        parseDay(today),
      ),
    [lang, today],
  );

  const fail = (e: unknown) => pushToast("error", (e as Error).message);

  async function toggle(task: PersonalTask) {
    try {
      if (task.status === "open") {
        await actions.complete.mutateAsync(task.id);
        pushToast("success", fill(t("today.completed"), { title: task.title }));
      } else {
        await actions.reopen.mutateAsync(task.id);
        pushToast("success", fill(t("today.reopened"), { title: task.title }));
      }
    } catch (e) {
      fail(e);
    }
  }

  async function remove(task: PersonalTask) {
    try {
      await actions.remove.mutateAsync(task.id);
      pushToast("success", fill(t("today.deleted"), { title: task.title }));
    } catch (e) {
      fail(e);
    }
  }

  const tabs: { id: Tab; label: string; count: number }[] = [
    { id: "today", label: t("today.tab_today"), count: split.today.length },
    { id: "open", label: t("today.tab_open"), count: split.open.length },
    { id: "done", label: t("today.tab_done"), count: split.done.length },
  ];

  return (
    <div className="flex h-full flex-col" data-testid="today-view">
      <ViewHeader
        icon={<CalendarCheck className="h-4 w-4 text-primary" />}
        title={t("today.title")}
        subtitle={fill(t("today.subtitle"), { date: longDate })}
      />
      <div className="flex-1 overflow-y-auto scrollbar-jarvis p-6">
        <div className="mx-auto max-w-3xl space-y-4">
          <QuickAdd today={today} onError={fail} />

          <div
            role="tablist"
            aria-label={t("today.title")}
            className="flex gap-1 rounded-lg border border-border bg-muted/40 p-1"
          >
            {tabs.map((item) => (
              <button
                key={item.id}
                type="button"
                role="tab"
                aria-selected={tab === item.id}
                data-testid={`today-tab-${item.id}`}
                onClick={() => setTab(item.id)}
                className={cn(
                  "flex flex-1 items-center justify-center gap-2 rounded-md px-3 py-1.5 text-sm transition-colors",
                  tab === item.id
                    ? "bg-background font-medium text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {item.label}
                <span className="rounded-full bg-muted px-1.5 text-micro tabular-nums text-muted-foreground">
                  {item.count}
                </span>
              </button>
            ))}
          </div>

          {error && (
            <p className="text-xs text-destructive" data-testid="today-error">
              {t("today.error_load")} ({(error as Error).message})
            </p>
          )}

          <div className="rounded-lg border border-border bg-card/60 px-4 py-2">
            {isLoading ? (
              <div className="flex items-center gap-2 py-3 text-xs text-muted-foreground">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                {t("today.loading")}
              </div>
            ) : shown.length === 0 ? (
              <p className="py-6 text-center text-sm text-muted-foreground" data-testid="today-empty">
                {t(`today.empty_${tab}`)}
              </p>
            ) : tab === "done" ? (
              <TaskList
                tasks={shown}
                today={today}
                onToggle={toggle}
                onEdit={setEditing}
                onDelete={remove}
              />
            ) : (
              groupRuns(shown, today).map((run) => (
                <section key={run.group} data-testid={`today-group-${run.group}`}>
                  <h3
                    className={cn(
                      "pt-3 text-micro font-semibold uppercase tracking-wide",
                      run.group === "overdue" ? "text-destructive" : "text-muted-foreground",
                    )}
                  >
                    {t(GROUP_LABEL[run.group])}
                  </h3>
                  <TaskList
                    tasks={run.tasks}
                    today={today}
                    onToggle={toggle}
                    onEdit={setEditing}
                    onDelete={remove}
                  />
                </section>
              ))
            )}
          </div>

          <p className="text-xs text-muted-foreground">{t("today.voice_hint")}</p>
        </div>
      </div>

      {editing && (
        <TaskDialog
          task={editing}
          onClose={() => setEditing(null)}
          onSave={async (changes) => {
            await actions.update.mutateAsync({ id: editing.id, changes });
            pushToast("success", t("today.saved"));
            setEditing(null);
          }}
        />
      )}
    </div>
  );
}

/** One line to add a task: title, priority, optional date. Enter adds. */
function QuickAdd({ today, onError }: { today: string; onError: (e: unknown) => void }) {
  const t = useT();
  const pushToast = useEventStore((s) => s.pushToast);
  const { add } = useTodayTaskActions();
  const [title, setTitle] = useState("");
  const [priority, setPriority] = useState<TaskPriority>("normal");
  const [due, setDue] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    const clean = title.trim();
    if (!clean || add.isPending) return;
    try {
      await add.mutateAsync({ title: clean, priority, due_date: due || null });
      pushToast("success", fill(t("today.added"), { title: clean }));
      setTitle("");
      setPriority("normal");
      setDue("");
    } catch (e) {
      onError(e);
    }
  }

  return (
    <form
      onSubmit={(e) => void submit(e)}
      className="space-y-2 rounded-lg border border-border bg-card/60 p-3"
      data-testid="today-add"
    >
      <div className="flex items-center gap-2">
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          maxLength={TASK_TITLE_MAX_CHARS}
          placeholder={t("today.add_placeholder")}
          aria-label={t("today.title_label")}
          data-testid="today-add-title"
          className={inputClass}
        />
        <Button
          type="submit"
          size="sm"
          className="shrink-0 gap-1.5"
          disabled={!title.trim() || add.isPending}
          data-testid="today-add-submit"
        >
          {add.isPending ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Plus className="h-3.5 w-3.5" />
          )}
          {t("today.add")}
        </Button>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <PriorityPicker value={priority} onChange={setPriority} testId="today-add-priority" />
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          <CalendarDays className="h-3.5 w-3.5" />
          <span>{t("today.due_label")}</span>
          <input
            type="date"
            value={due}
            onChange={(e) => setDue(e.target.value)}
            data-testid="today-add-due"
            className="rounded-md border border-input bg-background px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </label>
        {due !== today && (
          <button
            type="button"
            onClick={() => setDue(today)}
            title={t("today.due_set_today_hint")}
            aria-label={t("today.due_set_today_hint")}
            className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-medium text-primary underline decoration-dotted underline-offset-2 transition-colors hover:bg-muted hover:decoration-solid focus:outline-none focus-visible:ring-1 focus-visible:ring-primary"
            data-testid="today-add-due-today"
          >
            <CalendarCheck aria-hidden className="h-3.5 w-3.5" />
            {t("today.due_set_today")}
          </button>
        )}
      </div>
    </form>
  );
}

/** Three priority chips; a radio group for keyboard and screen-reader users. */
function PriorityPicker({
  value,
  onChange,
  testId,
}: {
  value: TaskPriority;
  onChange: (value: TaskPriority) => void;
  testId: string;
}) {
  const t = useT();
  return (
    <div
      role="radiogroup"
      aria-label={t("today.priority_label")}
      className="flex items-center gap-1"
      data-testid={testId}
    >
      {TASK_PRIORITIES.map((priority) => (
        <button
          key={priority}
          type="button"
          role="radio"
          aria-checked={value === priority}
          data-testid={`${testId}-${priority}`}
          onClick={() => onChange(priority)}
          className={cn(
            "rounded-full border px-2.5 py-0.5 text-xs transition-colors",
            value === priority
              ? PRIORITY_STYLE[priority]
              : "border-transparent text-muted-foreground hover:text-foreground",
            value === priority && priority === "normal" && "text-foreground",
          )}
        >
          {t(`today.priority_${priority}`)}
        </button>
      ))}
    </div>
  );
}

function TaskList({
  tasks,
  today,
  onToggle,
  onEdit,
  onDelete,
}: {
  tasks: PersonalTask[];
  today: string;
  onToggle: (task: PersonalTask) => Promise<void>;
  onEdit: (task: PersonalTask) => void;
  onDelete: (task: PersonalTask) => Promise<void>;
}) {
  return (
    <ul className="divide-y divide-border/60" data-testid="today-list">
      {tasks.map((task) => (
        <TaskRow
          key={task.id}
          task={task}
          today={today}
          onToggle={onToggle}
          onEdit={onEdit}
          onDelete={onDelete}
        />
      ))}
    </ul>
  );
}

function TaskRow({
  task,
  today,
  onToggle,
  onEdit,
  onDelete,
}: {
  task: PersonalTask;
  today: string;
  onToggle: (task: PersonalTask) => Promise<void>;
  onEdit: (task: PersonalTask) => void;
  onDelete: (task: PersonalTask) => Promise<void>;
}) {
  const t = useT();
  const lang = useUiLanguage();
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const confirmTimer = useRef<ReturnType<typeof setTimeout>>();
  const done = task.status === "done";

  useEffect(() => () => clearTimeout(confirmTimer.current), []);

  const shortDate = (value: string) =>
    new Intl.DateTimeFormat(lang, { day: "numeric", month: "short" }).format(parseDay(value));

  let dueText: string | null = null;
  let dueClass = "text-muted-foreground";
  if (task.due_date && !done) {
    const group = taskGroup(task, today);
    if (group === "overdue") {
      dueText = fill(t("today.due_overdue"), { date: shortDate(task.due_date) });
      dueClass = "text-destructive";
    } else if (group === "due_today") {
      dueText = t("today.due_today");
      dueClass = "text-primary";
    } else {
      dueText = fill(t("today.due_on"), { date: shortDate(task.due_date) });
    }
  }
  if (done && task.completed_at) {
    dueText = fill(t("today.done_on"), {
      date: new Intl.DateTimeFormat(lang, { day: "numeric", month: "short" }).format(
        new Date(task.completed_at),
      ),
    });
  }

  async function run(action: () => Promise<void>) {
    setBusy(true);
    try {
      await action();
    } finally {
      setBusy(false);
    }
  }

  function askDelete() {
    if (confirming) {
      clearTimeout(confirmTimer.current);
      setConfirming(false);
      void run(() => onDelete(task));
      return;
    }
    setConfirming(true);
    confirmTimer.current = setTimeout(() => setConfirming(false), 4000);
  }

  return (
    <li className="group flex items-start gap-3 py-2.5" data-testid={`today-task-${task.id}`}>
      <button
        type="button"
        role="checkbox"
        aria-checked={done}
        aria-label={done ? t("today.reopen") : t("today.complete")}
        title={done ? t("today.reopen") : t("today.complete")}
        disabled={busy}
        onClick={() => void run(() => onToggle(task))}
        data-testid={`today-toggle-${task.id}`}
        className={cn(
          "mt-0.5 flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full border transition-colors disabled:opacity-50",
          done
            ? "border-primary bg-primary text-primary-foreground"
            : "border-muted-foreground/50 hover:border-primary",
        )}
      >
        {busy ? (
          <Loader2 className="h-3 w-3 animate-spin" />
        ) : done ? (
          <Check className="h-3 w-3" />
        ) : null}
      </button>
      <div className="min-w-0 flex-1">
        <p
          className={cn(
            "break-words text-sm",
            done ? "text-muted-foreground line-through" : "text-foreground",
          )}
        >
          {task.title}
        </p>
        {task.notes && (
          <p className="mt-0.5 line-clamp-2 break-words text-xs text-muted-foreground">
            {task.notes}
          </p>
        )}
        <div className="mt-1 flex flex-wrap items-center gap-2">
          {task.priority !== "normal" && !done && (
            <span
              className={cn(
                "rounded-full border px-2 py-px text-micro font-medium",
                PRIORITY_STYLE[task.priority],
              )}
              data-testid={`today-priority-${task.id}`}
            >
              {t(`today.priority_${task.priority}`)}
            </span>
          )}
          {dueText && <span className={cn("text-micro", dueClass)}>{dueText}</span>}
        </div>
      </div>
      {done ? (
        <button
          type="button"
          aria-label={t("today.reopen")}
          title={t("today.reopen")}
          disabled={busy}
          onClick={() => void run(() => onToggle(task))}
          className="text-muted-foreground opacity-0 transition-opacity hover:text-foreground focus:opacity-100 group-hover:opacity-100"
        >
          <RotateCcw className="h-3.5 w-3.5" />
        </button>
      ) : (
        <button
          type="button"
          aria-label={t("today.edit")}
          title={t("today.edit")}
          onClick={() => onEdit(task)}
          data-testid={`today-edit-${task.id}`}
          className="text-muted-foreground opacity-0 transition-opacity hover:text-foreground focus:opacity-100 group-hover:opacity-100"
        >
          <Pencil className="h-3.5 w-3.5" />
        </button>
      )}
      <button
        type="button"
        aria-label={confirming ? t("today.delete_confirm") : t("today.delete")}
        title={confirming ? t("today.delete_confirm") : t("today.delete")}
        disabled={busy}
        onClick={askDelete}
        data-testid={`today-delete-${task.id}`}
        className={cn(
          "flex items-center gap-1 transition-opacity focus:opacity-100 disabled:opacity-50",
          confirming
            ? "rounded-md bg-destructive/10 px-1.5 text-xs text-destructive opacity-100"
            : "text-muted-foreground opacity-0 hover:text-destructive group-hover:opacity-100",
        )}
      >
        <Trash2 className="h-3.5 w-3.5" />
        {confirming && t("today.delete_confirm")}
      </button>
    </li>
  );
}

/** Edit a task: title, notes, priority, due date (which can be removed). */
function TaskDialog({
  task,
  onClose,
  onSave,
}: {
  task: PersonalTask;
  onClose: () => void;
  onSave: (changes: {
    title: string;
    notes: string | null;
    priority: TaskPriority;
    due_date: string | null;
  }) => Promise<void>;
}) {
  const t = useT();
  const [title, setTitle] = useState(task.title);
  const [notes, setNotes] = useState(task.notes ?? "");
  const [priority, setPriority] = useState<TaskPriority>(task.priority);
  const [due, setDue] = useState(task.due_date ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const valid = title.trim().length > 0;

  async function submit() {
    if (!valid || saving) return;
    setSaving(true);
    setError(null);
    try {
      await onSave({
        title: title.trim(),
        notes: notes.trim() || null,
        priority,
        due_date: due || null,
      });
    } catch (e) {
      setError((e as Error).message);
      setSaving(false);
    }
  }

  // Rendered at document level, like the dictionary dialog: a fixed modal
  // inside the section's scroll pane repaints the whole pane in the WebView.
  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-scrim/50"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="w-full max-w-md rounded-lg bg-popover p-6 shadow-float"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="today-dialog-title"
        data-testid="today-dialog"
      >
        <header className="mb-4 flex items-center gap-3">
          <h3 id="today-dialog-title" className="flex-1 font-display text-base font-semibold">
            {t("today.dialog_edit_title")}
          </h3>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("today.cancel")}
            className="text-muted-foreground hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="space-y-4">
          <label className="block space-y-1">
            <span className="text-xs text-muted-foreground">{t("today.title_label")}</span>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              maxLength={TASK_TITLE_MAX_CHARS}
              className={inputClass}
              data-testid="today-dialog-title-input"
              autoFocus
              onKeyDown={(e) => e.key === "Enter" && void submit()}
            />
          </label>
          <label className="block space-y-1">
            <span className="text-xs text-muted-foreground">{t("today.notes_label")}</span>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              maxLength={TASK_NOTES_MAX_CHARS}
              rows={3}
              placeholder={t("today.notes_placeholder")}
              className={cn(inputClass, "resize-y")}
              data-testid="today-dialog-notes"
            />
          </label>
          <div className="space-y-1">
            <span className="text-xs text-muted-foreground">{t("today.priority_label")}</span>
            <PriorityPicker value={priority} onChange={setPriority} testId="today-dialog-priority" />
          </div>
          <div className="space-y-1">
            <span className="text-xs text-muted-foreground">{t("today.due_label")}</span>
            <div className="flex items-center gap-2">
              <input
                type="date"
                value={due}
                onChange={(e) => setDue(e.target.value)}
                className="rounded-md border border-input bg-background px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                data-testid="today-dialog-due"
              />
              {due && (
                <button
                  type="button"
                  onClick={() => setDue("")}
                  className="text-xs text-muted-foreground hover:text-foreground"
                  data-testid="today-dialog-clear-due"
                >
                  {t("today.clear_date")}
                </button>
              )}
            </div>
          </div>
          {error && <p className="text-xs text-destructive">{error}</p>}
        </div>

        <div className="mt-6 flex justify-end gap-3">
          <Button size="sm" variant="outline" onClick={onClose} disabled={saving}>
            {t("today.cancel")}
          </Button>
          <Button
            size="sm"
            onClick={() => void submit()}
            disabled={!valid || saving}
            className="gap-1.5"
            data-testid="today-dialog-save"
          >
            {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            {t("today.save")}
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
