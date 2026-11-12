import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Check, Lightbulb } from "lucide-react";

import { fill, useT, useUiLanguage } from "@/i18n";
import {
  STANDING_LIST_KEY,
  StandingApiError,
  useStandingAction,
  useStandingTask,
  useStandingTasks,
  type StandingTask,
} from "@/lib/standingTasksApi";
import { cn } from "@/lib/utils";
import { openStandingTasks } from "@/store/standingFocus";
import { mannerLine } from "@/views/assistant/standingWords";
import type { NoticeItem } from "./reduce";

const LINK =
  "shrink-0 rounded px-1 underline-offset-2 hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/** How a suggestion stands: still open, taken on, turned down, or ended since. */
export type ProposalStanding = "open" | "accepted" | "declined" | "ended" | "unknown";

/**
 * Where a suggestion stands, read off the task itself. A task that never
 * looked and is ended was turned down; one that ran and is ended was taken
 * on and ended later.
 */
export function proposalStanding(task: Pick<StandingTask, "state" | "runs" | "last_run_ms"> | undefined): ProposalStanding {
  if (!task) return "unknown";
  if (task.state === "proposed") return "open";
  if (task.state === "active" || task.state === "paused") return "accepted";
  return task.runs > 0 || task.last_run_ms !== null ? "ended" : "declined";
}

const text = (value: unknown): string => (typeof value === "string" ? value.trim() : "");

/**
 * The assistant suggests looking after something over time (notice
 * `standing_proposal`): the title, the goal, how far it would go and how
 * often it would look, why it suggests it, and the limits it would act
 * inside when it asks to act on its own. Accept and Not now call the task's
 * routes; after that the card says how it was settled, and so does a card
 * whose task is no longer a suggestion (accepted on the assistant's page,
 * say). Written only, never spoken.
 */
export function StandingProposalCard({ item }: { item: NoticeItem }) {
  const t = useT();
  const lang = useUiLanguage();
  const client = useQueryClient();
  const id = text(item.data.standing_id);
  const list = useStandingTasks();
  const action = useStandingAction();
  const [decided, setDecided] = useState<"accepted" | "declined" | null>(null);
  const [failed, setFailed] = useState("");

  const listed = list.data?.tasks.find((task) => task.id === id);
  // A task the list does not carry is either ended (the list leaves those
  // out) or newer than the list: its own record says which.
  const lookUp = Boolean(id) && decided === null && !action.isPending && list.isSuccess && !listed;
  const own = useStandingTask(id, { enabled: lookUp });
  const task = listed ?? (lookUp ? own.data?.task : undefined);
  const gone = lookUp && own.error instanceof StandingApiError && own.error.status === 404;
  const standing: ProposalStanding = decided ?? (gone ? "ended" : proposalStanding(task));

  // The list is behind: a suggestion it does not know yet belongs in it.
  const stale = !listed && task !== undefined && task.state !== "ended";
  useEffect(() => {
    if (stale) void client.invalidateQueries({ queryKey: STANDING_LIST_KEY });
  }, [stale, client]);

  const title = text(item.data.title) || task?.title || "";
  const goal = text(item.data.goal) || task?.goal || "";
  if (!id || !(title || goal || item.text)) return null;

  const autonomy = text(item.data.autonomy) || task?.autonomy || "";
  const interval = Number(item.data.interval_min) || task?.interval_min || 0;
  const limits = text(item.data.limits);
  const reason = text(item.data.reason);
  const manner = autonomy ? mannerLine({ autonomy, interval_min: interval }, t, lang) : "";

  const decide = (verb: "accept" | "decline") => {
    setFailed("");
    action.mutate(
      { id, action: verb },
      {
        onSuccess: () => setDecided(verb === "accept" ? "accepted" : "declined"),
        onError: (error) => setFailed(error.message),
      },
    );
  };

  // While the task's state is still being read the card offers nothing; when
  // it cannot be read at all, the buttons stay and the server has the last word.
  const unreadable = list.isError || (lookUp && own.isError);
  const canDecide = standing === "open" || (standing === "unknown" && unreadable && !action.isPending);
  const settled = standing === "accepted" || standing === "declined" || standing === "ended";

  return (
    <div data-message-id={item.id} data-testid="standing-proposal" data-standing={standing}
      className="mx-auto w-full max-w-[85%] rounded-xl border border-border bg-card px-4 py-3">
      <div className="flex items-start gap-3">
        <Lightbulb aria-hidden className={cn("mt-0.5 h-4 w-4 shrink-0", canDecide ? "text-info" : "text-muted-foreground")} />
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium text-muted-foreground">{t("standing.card_title")}</p>
          <p className="text-sm font-medium text-foreground">{title || item.text}</p>
          {goal && <p className="line-clamp-2 text-sm text-foreground">{goal}</p>}
          {manner && <p className="mt-1 text-xs text-muted-foreground">{manner}</p>}
          {limits && (
            <p className="mt-1 line-clamp-2 text-xs text-muted-foreground" data-testid="standing-proposal-limits">
              <span className="font-medium text-foreground">{t("standing.limits_label")}:</span> {limits}
            </p>
          )}
          {reason && (
            <p className="mt-1 line-clamp-2 text-xs text-muted-foreground" data-testid="standing-proposal-reason">
              {fill(t("standing.reason"), { reason })}
            </p>
          )}
        </div>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-1.5 pl-7 text-xs">
        {canDecide ? (
          <>
            <button type="button" onClick={() => decide("accept")} disabled={action.isPending} data-testid="standing-accept"
              className="inline-flex items-center gap-1 rounded-md bg-primary px-2.5 py-1 font-medium text-primary-foreground hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60">
              <Check aria-hidden className="h-3 w-3" />
              {t("standing.accept")}
            </button>
            <button type="button" onClick={() => decide("decline")} disabled={action.isPending} data-testid="standing-decline"
              className="rounded-md border border-border px-2 py-1 text-foreground hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60">
              {t("standing.decline")}
            </button>
          </>
        ) : null}
        {settled ? (
          <span className="text-muted-foreground" data-testid="standing-settled">{t(`standing.settled_${standing}`)}</span>
        ) : null}
        {standing === "accepted" ? (
          <button type="button" onClick={() => openStandingTasks(id)} data-testid="standing-open"
            className={cn(LINK, "text-muted-foreground")}>
            {t("standing.open")}
          </button>
        ) : null}
        {failed ? <span role="alert" className="text-destructive">{failed}</span> : null}
      </div>
    </div>
  );
}

/**
 * A standing task that paused itself after repeated failures (notice
 * `standing_paused`): one quiet line, and a way to the task where it can be
 * looked at and resumed.
 */
export function StandingPausedNotice({ item }: { item: NoticeItem }) {
  const t = useT();
  const id = text(item.data.standing_id);
  const title = text(item.data.title);
  const line = title ? fill(t("standing.paused_line"), { title }) : item.text;
  if (!line) return null;
  return (
    <p data-message-id={item.id} data-testid="standing-paused"
      className="mx-auto max-w-[85%] py-1 text-center text-xs text-muted-foreground">
      {line}
      {id ? (
        <>
          {" "}
          <button type="button" onClick={() => openStandingTasks(id)} data-testid="standing-paused-open" className={LINK}>
            {t("standing.open")}
          </button>
        </>
      ) : null}
    </p>
  );
}
