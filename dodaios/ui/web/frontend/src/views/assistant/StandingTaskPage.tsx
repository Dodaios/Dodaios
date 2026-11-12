/**
 * One standing task, opened in place with a way back, like one of the
 * assistant's files.
 *
 * The head names the task, says whether it runs and how often, and carries
 * the one thing to do next: accept a suggestion, look now, or resume. Under
 * it the task in the page's label-column grammar: the goal, how to go about
 * it and the limits (each the person's to rewrite), how far the assistant may
 * go, how often it looks, what it last found, and the notes it keeps for
 * itself (read only). Then the log of its looks, newest first, and at the
 * foot the two quiet controls: pause and end. Ending asks once, in the line
 * itself.
 *
 * Choosing "Act" needs limits in the person's own words first: without any,
 * the limits field opens and the level is only saved together with them.
 */
import { ArrowLeft } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { fill, useT, useUiLanguage } from "@/i18n";
import {
  usePatchStanding,
  useStandingAction,
  useStandingTask,
  useStandingTasks,
  type StandingAction,
  type StandingAutonomy,
  type StandingPatch,
  type StandingRun,
} from "@/lib/standingTasksApi";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";
import { clockTime, relativeDay } from "@/views/assistant/format";
import { Section, SpecRow, TextAction } from "@/views/assistant/Section";
import { AutonomyChoice, Finding, PaceSelect, StateDot } from "@/views/assistant/standingParts";
import {
  TONE_INK,
  capitalize,
  lastFinding,
  looksWords,
  nextLookWords,
  outcomeTone,
  outcomeWords,
} from "@/views/assistant/standingWords";

/** A text of the task the person may rewrite: shown as prose, edited in place. */
function EditableRow({
  field,
  label,
  value,
  emptyText,
  placeholder,
  hint,
  canEdit,
  mayBeEmpty,
  forceOpen = false,
  onSave,
  onCancel,
}: {
  field: string;
  label: string;
  value: string;
  emptyText: string;
  placeholder?: string;
  /** Said under the open field. */
  hint?: string;
  canEdit: boolean;
  mayBeEmpty: boolean;
  /** Opened from outside: the level needs this text before it can be saved. */
  forceOpen?: boolean;
  /** Resolves true once saved; the field stays open otherwise. */
  onSave: (text: string) => Promise<boolean>;
  onCancel?: () => void;
}) {
  const t = useT();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const [saving, setSaving] = useState(false);
  const open = canEdit && (editing || forceOpen);

  // A save (or a write from elsewhere) brings new text: take it while closed.
  useEffect(() => {
    if (!open) setDraft(value);
  }, [open, value]);

  const text = draft.trim();
  const canSave = !saving && (mayBeEmpty || text.length > 0) && (text !== value.trim() || forceOpen);

  const save = async () => {
    if (!canSave) return;
    setSaving(true);
    const saved = await onSave(text);
    setSaving(false);
    if (saved) setEditing(false);
  };
  const cancel = () => {
    setEditing(false);
    setDraft(value);
    onCancel?.();
  };

  return (
    <SpecRow label={open ? <label htmlFor={`standing-${field}`}>{label}</label> : label}>
      {open ? (
        <>
          <Textarea
            id={`standing-${field}`}
            data-testid={`assistant-standing-${field}-input`}
            value={draft}
            rows={3}
            autoFocus
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if ((e.ctrlKey || e.metaKey) && e.key === "s") {
                e.preventDefault();
                void save();
              }
            }}
            placeholder={placeholder}
          />
          <div className="mt-2 flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
            <p data-testid={`assistant-standing-${field}-hint`} className="min-w-0 flex-1 text-sm text-muted-foreground">{hint}</p>
            <div className="flex items-center gap-5">
              <TextAction disabled={saving} onClick={cancel} data-testid={`assistant-standing-${field}-cancel`}>
                {t("standing.cancel")}
              </TextAction>
              <Button type="button" size="sm" disabled={!canSave} onClick={() => void save()} data-testid={`assistant-standing-${field}-save`}>
                {saving ? t("standing.saving") : t("standing.save")}
              </Button>
            </div>
          </div>
        </>
      ) : (
        <div className="group flex items-start gap-6">
          <p
            data-testid={`assistant-standing-${field}`}
            className={cn("min-w-0 flex-1 whitespace-pre-line", !value.trim() && "text-muted-foreground")}
          >
            {value.trim() || emptyText}
          </p>
          {canEdit && (
            <TextAction
              aria-label={`${t("standing.edit")}: ${label}`}
              data-testid={`assistant-standing-${field}-edit`}
              onClick={() => setEditing(true)}
              className="shrink-0 leading-7"
            >
              {t("standing.edit")}
            </TextAction>
          )}
        </div>
      )}
    </SpecRow>
  );
}

function RunRow({ run }: { run: StandingRun }) {
  const t = useT();
  const lang = useUiLanguage();
  const words = outcomeWords(run.outcome, t);
  const actions = run.actions.filter((line) => line.trim());
  // A look that found nothing is the quiet line of the log.
  const uneventful = run.outcome === "quiet" || run.outcome === "skipped";
  return (
    <SpecRow
      label={
        <span className="tabular-nums">
          <span className="block">{relativeDay(run.at_ms, lang) ?? "–"}</span>
          <span className="block text-sm">{clockTime(run.at_ms, lang)}</span>
        </span>
      }
    >
      <div data-testid={`assistant-standing-run-${run.id}`} data-outcome={run.outcome}>
        {words && (
          <p className={cn("font-medium", TONE_INK[outcomeTone(run.outcome)] || (uneventful ? "text-muted-foreground" : "text-foreground-strong"))}>
            {words}
          </p>
        )}
        {run.summary.trim() && <p className="whitespace-pre-line">{run.summary.trim()}</p>}
        {actions.length > 0 && (
          <div className="mt-2 text-sm text-muted-foreground">
            <p>{t("standing.log_changed")}</p>
            <ul className="mt-1 flex list-disc flex-col gap-1 pl-5">
              {actions.map((line, i) => (
                <li key={i} className="text-foreground">{line}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </SpecRow>
  );
}

function Shell({ name, onBack, children }: { name: string; onBack: () => void; children: ReactNode }) {
  return (
    <div data-testid="assistant-standing-page" className="flex flex-col">
      <TextAction onClick={onBack} data-testid="assistant-standing-back" className="inline-flex items-center gap-1.5 self-start">
        <ArrowLeft aria-hidden className="h-4 w-4" />
        {name}
      </TextAction>
      {children}
    </div>
  );
}

export function StandingTaskPage({ id, name, onBack }: { id: string; name: string; onBack: () => void }) {
  const t = useT();
  const lang = useUiLanguage();
  const pushToast = useEventStore((s) => s.pushToast);
  const list = useStandingTasks();
  const detail = useStandingTask(id);
  const action = useStandingAction();
  const patch = usePatchStanding();
  // "Act" was picked without limits: it waits for them and is saved with them.
  const [wantsAct, setWantsAct] = useState(false);
  const [confirmEnd, setConfirmEnd] = useState(false);

  const task = detail.data?.task;
  const runs = detail.data?.runs ?? [];

  if (!task) {
    return (
      <Shell name={name} onBack={onBack}>
        {detail.error ? (
          <div role="alert" data-testid="assistant-standing-page-error" className="mt-5 border-t border-border pt-7">
            <p className="text-base font-medium text-foreground-strong">{t("standing.task_error")}</p>
            <p className="mt-1 text-base text-muted-foreground">{detail.error.message}</p>
            <TextAction className="mt-3" onClick={() => void detail.refetch()}>
              {t("standing.retry")}
            </TextAction>
          </div>
        ) : (
          <div role="status" aria-busy="true" aria-label={t("common.loading")} className="mt-5 flex flex-col gap-4">
            <div className="h-6 w-72 max-w-full animate-pulse rounded-md bg-secondary" />
            <div className="h-4 w-48 animate-pulse rounded-full bg-secondary" />
            <div className="mt-6 h-4 w-11/12 animate-pulse rounded-full bg-secondary" />
            <div className="h-4 w-2/3 animate-pulse rounded-full bg-secondary" />
          </div>
        )}
      </Shell>
    );
  }

  const ended = task.state === "ended";
  const proposed = task.state === "proposed";
  const acting = action.isPending;
  const acts = wantsAct || task.autonomy === "act";

  const act = (verb: StandingAction, onDone?: () => void) =>
    action.mutate({ id, action: verb }, { onSuccess: onDone, onError: (e) => pushToast("error", e.message) });

  const save = (change: StandingPatch): Promise<boolean> =>
    patch.mutateAsync({ id, patch: change }).then(
      () => true,
      (e: Error) => {
        pushToast("error", e.message);
        return false;
      },
    );

  const chooseLevel = (level: StandingAutonomy) => {
    if (level === "act" && !task.limits.trim()) {
      setWantsAct(true);
      return;
    }
    setWantsAct(false);
    if (level !== task.autonomy) void save({ autonomy: level });
  };

  const finding = lastFinding(task, t);
  const lastDay = relativeDay(task.last_run_ms, lang);
  const next = nextLookWords(task, t, lang);
  const summary = [
    t(`standing.state_${task.state}`),
    ...(ended ? [] : [looksWords(task.interval_min, t, lang)]),
  ].join(" · ");

  return (
    <Shell name={name} onBack={onBack}>
      <div className="mb-2 mt-5 flex flex-wrap items-end justify-between gap-x-6 gap-y-4 border-b border-border pb-5">
        <div className="min-w-0">
          <h2 className="truncate text-xl font-semibold text-foreground-strong">{task.title}</h2>
          <p data-testid="assistant-standing-summary" className="mt-1 flex items-center gap-2 text-base text-muted-foreground">
            <StateDot state={task.state} />
            {summary}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-5">
          {proposed && (
            <>
              <TextAction disabled={acting} onClick={() => act("decline", onBack)} data-testid="assistant-standing-page-decline">
                {t("standing.decline")}
              </TextAction>
              <Button type="button" size="sm" disabled={acting} onClick={() => act("accept")} data-testid="assistant-standing-page-accept">
                {t("standing.accept")}
              </Button>
            </>
          )}
          {task.state === "active" && (
            <Button
              type="button"
              size="sm"
              variant="secondary"
              disabled={acting}
              data-testid="assistant-standing-run"
              onClick={() => act("run", () => pushToast("success", t("standing.run_started")))}
            >
              {t("standing.run")}
            </Button>
          )}
          {task.state === "paused" && (
            <Button type="button" size="sm" disabled={acting} onClick={() => act("resume")} data-testid="assistant-standing-resume">
              {t("standing.resume")}
            </Button>
          )}
        </div>
      </div>

      {proposed && task.reason && (
        <p data-testid="assistant-standing-reason" className="max-w-reading py-3 text-base leading-7 text-muted-foreground">
          {fill(t("standing.reason"), { reason: task.reason })}
        </p>
      )}

      <div className="divide-y divide-border">
        <EditableRow
          field="goal"
          label={t("standing.goal_label")}
          value={task.goal}
          emptyText="–"
          placeholder={t("standing.form_goal_placeholder")}
          canEdit={!ended}
          mayBeEmpty={false}
          onSave={(goal) => save({ goal })}
        />
        <EditableRow
          field="how"
          label={t("standing.how_label")}
          value={task.how}
          emptyText={t("standing.how_empty")}
          placeholder={t("standing.form_how_placeholder")}
          canEdit={!ended}
          mayBeEmpty
          onSave={(how) => save({ how })}
        />
        <SpecRow label={t("standing.autonomy_label")}>
          <AutonomyChoice
            testId="assistant-standing-level"
            value={wantsAct ? "act" : task.autonomy}
            levels={list.data?.autonomy}
            disabled={ended || patch.isPending}
            onChange={chooseLevel}
          />
        </SpecRow>
        <EditableRow
          field="limits"
          label={t("standing.limits_label")}
          value={task.limits}
          emptyText={t("standing.limits_empty")}
          placeholder={t("standing.form_limits_placeholder")}
          hint={acts ? t("standing.act_needs_limits") : undefined}
          canEdit={!ended}
          mayBeEmpty={!acts}
          forceOpen={wantsAct}
          onSave={async (limits) => {
            const saved = await save(wantsAct ? { autonomy: "act", limits } : { limits });
            if (saved) setWantsAct(false);
            return saved;
          }}
          onCancel={() => setWantsAct(false)}
        />
        <SpecRow label={ended ? t("standing.pace_label") : <label htmlFor="standing-pace">{t("standing.pace_label")}</label>}>
          {ended ? (
            capitalize(looksWords(task.interval_min, t, lang), lang)
          ) : (
            <PaceSelect
              id="standing-pace"
              testId="assistant-standing-pace"
              value={task.interval_min}
              limits={list.data?.limits}
              disabled={patch.isPending}
              onChange={(interval_min) => {
                if (interval_min !== task.interval_min) void save({ interval_min });
              }}
            />
          )}
        </SpecRow>
        <SpecRow label={t("standing.last_look")}>
          <p data-testid="assistant-standing-last">
            {task.last_run_ms === null ? (
              <span className="text-muted-foreground">{t("standing.never_looked")}</span>
            ) : (
              <>
                <span className="tabular-nums">{`${lastDay}, ${clockTime(task.last_run_ms, lang)}`}</span>
                {finding && (
                  <>
                    {" · "}
                    <Finding task={task} />
                  </>
                )}
              </>
            )}
          </p>
        </SpecRow>
        {next && (
          <SpecRow label={t("standing.next_look")}>
            <span data-testid="assistant-standing-next" className="tabular-nums">{next}</span>
          </SpecRow>
        )}
        <SpecRow label={t("standing.notes_label")}>
          <p data-testid="assistant-standing-notes" className={cn("whitespace-pre-line", !task.notes.trim() && "text-muted-foreground")}>
            {task.notes.trim() || t("standing.notes_empty")}
          </p>
          <p className="mt-1 text-sm text-muted-foreground">{t("standing.notes_hint")}</p>
        </SpecRow>
      </div>

      <div className="mt-10">
        <Section testId="assistant-standing-log" title={t("standing.log_title")}>
          {runs.length === 0 ? (
            <p className="text-base text-muted-foreground">
              {detail.isPlaceholderData ? t("common.loading") : t("standing.log_empty")}
            </p>
          ) : (
            <div className="divide-y divide-border">
              {runs.map((run) => (
                <RunRow key={run.id} run={run} />
              ))}
            </div>
          )}
        </Section>
      </div>

      {!ended && !proposed && (
        <div className="mt-10 flex flex-wrap items-center gap-x-6 gap-y-3 border-t border-border pt-5">
          {confirmEnd ? (
            <div role="alert" data-testid="assistant-standing-end-confirm" className="flex flex-wrap items-center gap-x-5 gap-y-3">
              <p className="max-w-reading text-base text-foreground">{fill(t("standing.end_confirm"), { title: task.title })}</p>
              <Button
                type="button"
                size="sm"
                variant="destructive"
                disabled={acting}
                data-testid="assistant-standing-end-yes"
                onClick={() =>
                  act("end", () => {
                    pushToast("success", t("standing.end_done"));
                    onBack();
                  })
                }
              >
                {t("standing.end")}
              </Button>
              <TextAction disabled={acting} onClick={() => setConfirmEnd(false)} data-testid="assistant-standing-end-no">
                {t("standing.cancel")}
              </TextAction>
            </div>
          ) : (
            <>
              {task.state === "active" && (
                <TextAction disabled={acting} onClick={() => act("pause")} data-testid="assistant-standing-pause">
                  {t("standing.pause")}
                </TextAction>
              )}
              <TextAction
                disabled={acting}
                onClick={() => setConfirmEnd(true)}
                data-testid="assistant-standing-end"
                className="hover:text-destructive focus-visible:text-destructive"
              >
                {t("standing.end")}
              </TextAction>
            </>
          )}
        </div>
      )}
    </Shell>
  );
}
