import { ChevronRight, CircleAlert, Eye, Hand, Lightbulb } from "lucide-react";

import { FOCUS, PANEL_ICON, PANEL_ROW, PANEL_ROW_BUTTON, PanelEmpty, PanelSection } from "@/components/home/panelParts";
import { useT, useUiLanguage } from "@/i18n";
import { sortStanding, useStandingAction, useStandingTasks, type StandingTask } from "@/lib/standingTasksApi";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";
import { openStandingTasks } from "@/store/standingFocus";
import { lastFinding, nextLookLine, outcomeTone } from "@/views/assistant/standingWords";

/** How many running tasks show; the rest are one click away on the assistant's page. */
export const STANDING_SHOWN = 3;

const SMALL_BUTTON = cn("rounded-md px-2 py-0.5 text-xs font-medium transition-colors disabled:opacity-60", FOCUS);

/** A look that brought something says so; a quiet one says when the next comes. */
function noteOf(task: StandingTask, t: (key: string) => string, lang: ReturnType<typeof useUiLanguage>): string {
  const quiet = task.last_outcome === "" || task.last_outcome === "quiet" || task.last_outcome === "skipped";
  if (!quiet) return lastFinding(task, t);
  return nextLookLine(task, t, lang) ?? lastFinding(task, t);
}

/**
 * What the assistant looks after over time: the standing tasks that run,
 * each with what its last look found or when the next one comes, and the
 * ones the assistant suggested, to accept or turn down right here. Every row
 * opens the task on the assistant's page; the last line opens the whole list.
 *
 * Draws nothing while the list is unknown (not loaded, not offered by this
 * backend, scheduler not running), so the panel never shows a dead block.
 */
export function PanelStanding() {
  const t = useT();
  const lang = useUiLanguage();
  const list = useStandingTasks();
  const action = useStandingAction();
  if (!list.data?.available) return null;

  const tasks = sortStanding(list.data.tasks);
  const proposed = tasks.filter((task) => task.state === "proposed");
  const active = tasks.filter((task) => task.state === "active").slice(0, STANDING_SHOWN);
  const busyId = action.isPending ? action.variables?.id : undefined;
  const decide = (task: StandingTask, verb: "accept" | "decline") =>
    action.mutate(
      { id: task.id, action: verb },
      { onError: (error) => useEventStore.getState().pushToast("error", error.message) },
    );

  return (
    <PanelSection id="standing" title={t("standing.panel_title")}>
      {proposed.map((task) => (
        <div key={task.id} data-testid={`assistant-standing-proposal-${task.id}`} className={cn(PANEL_ROW, "items-start")}>
          <Lightbulb aria-hidden strokeWidth={1.75} className={cn(PANEL_ICON, "mt-0.5 text-info")} />
          <div className="min-w-0 flex-1">
            <button type="button" onClick={() => openStandingTasks(task.id)} title={task.goal || task.title}
              className={cn("block w-full truncate rounded-sm text-left text-sm text-foreground hover:underline", FOCUS)}>
              {task.title}
            </button>
            <span className="block truncate text-sm text-muted-foreground">{t("standing.state_proposed")}</span>
            <div className="mt-1 flex items-center gap-1.5 pb-0.5">
              <button type="button" data-testid={`assistant-standing-proposal-accept-${task.id}`} disabled={busyId === task.id}
                onClick={() => decide(task, "accept")}
                className={cn(SMALL_BUTTON, "bg-primary text-primary-foreground hover:bg-primary/90")}>
                {t("standing.accept")}
              </button>
              <button type="button" data-testid={`assistant-standing-proposal-decline-${task.id}`} disabled={busyId === task.id}
                onClick={() => decide(task, "decline")}
                className={cn(SMALL_BUTTON, "text-muted-foreground hover:bg-secondary hover:text-foreground")}>
                {t("standing.decline")}
              </button>
            </div>
          </div>
        </div>
      ))}
      {active.map((task) => {
        const tone = outcomeTone(task.last_outcome);
        const note = noteOf(task, t, lang);
        const Icon = tone === "attention" ? Hand : tone === "fault" ? CircleAlert : Eye;
        return (
          <button key={task.id} type="button" data-testid={`assistant-standing-task-${task.id}`} data-outcome={task.last_outcome}
            onClick={() => openStandingTasks(task.id)} title={note ? `${task.title} · ${note}` : task.title}
            className={PANEL_ROW_BUTTON}>
            <Icon aria-hidden strokeWidth={1.75}
              className={cn(PANEL_ICON, tone === "attention" && "text-warning", tone === "fault" && "text-destructive")} />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm text-foreground">{task.title}</span>
              {note && <span className="block truncate text-sm text-muted-foreground">{note}</span>}
            </span>
          </button>
        );
      })}
      {proposed.length + active.length === 0 && (
        <PanelEmpty testId="assistant-standing-panel-empty">{t("standing.panel_empty")}</PanelEmpty>
      )}
      <button type="button" data-testid="assistant-standing-all" onClick={() => openStandingTasks()} className={PANEL_ROW_BUTTON}>
        <span className="min-w-0 flex-1 truncate text-sm text-muted-foreground">{t("standing.panel_all")}</span>
        <ChevronRight aria-hidden className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      </button>
    </PanelSection>
  );
}
