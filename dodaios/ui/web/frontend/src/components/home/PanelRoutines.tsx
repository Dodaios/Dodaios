import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, Clock, LoaderCircle } from "lucide-react";

import { FOCUS, PANEL_ICON, PANEL_ROW, PanelEmpty, PanelSection, ShowMore } from "@/components/home/panelParts";
import { useRunLocale } from "@/components/runs/format";
import { humanSchedule, triggerFamily } from "@/components/society/card/routines/humanSchedule";
import { Switch } from "@/components/ui/switch";
import { useLocaleChunk, useT } from "@/i18n";
import { setTaskEnabled } from "@/lib/tasksApi";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";

/** The assistant's own id in the roster; its routines are the ones the panel lists. */
export const ASSISTANT_ID = "jarvis";
export const ASSISTANT_ROUTINES_KEY = ["sidebar", "automations"] as const;
/** How many routines show before the rest folds away. */
export const ROUTINES_SHOWN = 2;

const AGENT_TITLE_PREFIX = /^\[agent:[^\]]+\]\s*/i;

export interface AssistantRoutine {
  id: string;
  title: string;
  state: string;
  trigger: unknown;
}

/** The assistant's routines as the task store holds them, in the store's order. */
export function useAssistantRoutines() {
  return useQuery({
    queryKey: ASSISTANT_ROUTINES_KEY,
    staleTime: 30_000,
    refetchInterval: import.meta.env.MODE === "test" ? false : 60_000,
    retry: false,
    queryFn: async (): Promise<AssistantRoutine[]> => {
      const response = await fetch(`/api/society/agents/${ASSISTANT_ID}/routines`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const body = (await response.json()) as { routines?: { id?: string; title?: string; state?: string; trigger?: unknown }[] };
      return (body.routines ?? []).flatMap((row) =>
        row.id
          ? [{ id: row.id, title: (row.title ?? "").replace(AGENT_TITLE_PREFIX, "").trim(), state: row.state ?? "", trigger: row.trigger ?? null }]
          : [],
      );
    },
  });
}

const STATE_RANK: Record<string, number> = { running: 0, scheduled: 1, pending: 1, paused: 2 };
/** States after which a routine never runs again: the task store refuses to pause or resume it. */
const FINISHED = new Set(["completed", "failed", "cancelled", "interrupted"]);

/**
 * Every routine of the assistant in the order worth a look: what runs
 * first, then what waits for its time, then what is paused, and last what
 * already ran for good (a one-time job). The store's order breaks ties.
 */
export function panelRoutines(routines: readonly AssistantRoutine[]): AssistantRoutine[] {
  return routines
    .map((routine, index) => ({ routine, index }))
    .sort((a, b) => (STATE_RANK[a.routine.state] ?? 3) - (STATE_RANK[b.routine.state] ?? 3) || a.index - b.index)
    .map(({ routine }) => routine);
}

/** What a routine's second line says: its schedule, or how a one-time job that already ran ended. */
function routineLine(routine: AssistantRoutine, t: ReturnType<typeof useT>, locale: string): string {
  if (FINISHED.has(routine.state) && triggerFamily(routine.trigger) === "once") {
    if (routine.state === "completed") return t("sidebar.routine_done");
    if (routine.state === "cancelled") return t("sidebar.routine_cancelled");
    return t("sidebar.routine_failed");
  }
  return humanSchedule(routine.trigger, { t, locale });
}

/**
 * The assistant's routines in its Activity tab: the first two, the rest
 * one click away. Each row says its schedule in plain words and has a
 * switch that pauses or resumes it; the row itself opens the routine (its
 * runs, pause and run now) in a dialog over the conversation.
 */
export function PanelRoutines({ onOpen }: { onOpen: (routineId: string) => void }) {
  const t = useT();
  useLocaleChunk("society");
  const locale = useRunLocale();
  const client = useQueryClient();
  const routines = useAssistantRoutines();
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const rows = panelRoutines(routines.data ?? []);
  const shown = open ? rows : rows.slice(0, ROUTINES_SHOWN);

  const toggle = async (routine: AssistantRoutine, enabled: boolean) => {
    setPending(routine.id);
    try {
      await setTaskEnabled(routine.id, enabled);
    } catch (error) {
      useEventStore.getState().pushToast("error", error instanceof Error ? error.message : String(error));
    } finally {
      await client.invalidateQueries({ queryKey: ASSISTANT_ROUTINES_KEY });
      setPending(null);
    }
  };

  return (
    <PanelSection id="routines" title={t("sidebar.routines")}>
      {shown.map((routine) => {
        const sentence = routineLine(routine, t, locale);
        const finished = FINISHED.has(routine.state);
        const active = routine.state !== "paused" && !finished;
        return (
          <div key={routine.id} className={PANEL_ROW}>
            <button type="button" data-testid={`assistant-routine-${routine.id}`} data-state={routine.state}
              onClick={() => onOpen(routine.id)} title={sentence ? `${routine.title} · ${sentence}` : routine.title}
              className={cn("flex min-w-0 flex-1 items-center gap-2.5 rounded-md text-left", FOCUS)}>
              <Clock aria-hidden strokeWidth={1.75} className={PANEL_ICON} />
              <span className="min-w-0 flex-1">
                <span className={cn("block truncate text-sm", active ? "text-foreground" : "text-muted-foreground")}>{routine.title}</span>
                {sentence && <span className="block truncate text-sm text-muted-foreground">{sentence}</span>}
              </span>
              {routine.state === "running" && (
                <LoaderCircle aria-hidden strokeWidth={1.75} className="h-3.5 w-3.5 shrink-0 text-success motion-safe:animate-spin" />
              )}
              {routine.state === "failed" && <CircleAlert aria-hidden strokeWidth={1.75} className="h-3.5 w-3.5 shrink-0 text-destructive" />}
            </button>
            {/* A running routine finishes its run first; a finished one-time job has nothing left to switch. */}
            <Switch aria-label={routine.title} data-testid={`assistant-routine-switch-${routine.id}`}
              checked={active} disabled={finished || routine.state === "running" || pending === routine.id}
              onCheckedChange={(enabled) => void toggle(routine, enabled)} />
          </div>
        );
      })}
      {rows.length === 0 && (
        <PanelEmpty testId="assistant-routines-empty">
          {routines.isLoading ? t("common.loading") : t("sidebar.automations_empty")}
        </PanelEmpty>
      )}
      {rows.length > ROUTINES_SHOWN && (
        <ShowMore testId="assistant-routines-more" open={open} onToggle={() => setOpen((value) => !value)} />
      )}
    </PanelSection>
  );
}
