/**
 * One routine in the agent's list: what triggers it, the schedule as a
 * sentence, when it runs next, how the last run went and what it cost.
 * Pause/resume and a test run sit on the row and appear on hover or focus.
 */
import { useId, useState } from "react";
import { Pause, Play, Loader2 } from "lucide-react";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { runTaskNow, setTaskEnabled } from "@/lib/tasksApi";
import { BuiltByBadge } from "@/components/selfBuild/BuiltByBadge";
import { displayRoutineTitle, type LiveRoutine } from "../../cardData";
import { TriggerIcon, type RoutineTone } from "./TriggerIcon";
import { RunStatusIcon } from "./RunStatus";
import { humanSchedule, triggerFamily } from "./humanSchedule";
import { formatCost, relativeTime } from "./format";
import type { RoutineRunRow } from "./routinesApi";
import { runStateLabel } from "./RunHistory";

const ACTIVE = ["scheduled", "active", "enabled", ""];
const TERMINAL = ["completed", "failed", "cancelled", "interrupted"];

export function routineTone(routine: LiveRoutine, lastRun: RoutineRunRow | null | undefined, parked: boolean): RoutineTone {
  if (routine.state === "running") return "running";
  if (routine.state === "paused") return parked ? "parked" : "paused";
  if (lastRun?.status === "failed") return "failed";
  return ACTIVE.includes(routine.state) ? "active" : "paused";
}

export function RoutineRow({ routine, lastRun, parked, locale, now, onOpen, onChanged }: {
  routine: LiveRoutine; lastRun?: RoutineRunRow | null; parked: boolean; locale: string; now: number;
  onOpen: () => void; onChanged: () => void;
}) {
  const t = useT();
  const own = (key: string) => t(`society.agent_routines.list.${key}`);
  const describedBy = useId();
  const [busy, setBusy] = useState<"run" | "toggle" | null>(null);
  const [problem, setProblem] = useState("");
  const title = displayRoutineTitle(routine.title);
  const tone = routineTone(routine, lastRun, parked);
  const active = ACTIVE.includes(routine.state);
  const sentence = humanSchedule(routine.trigger, { t, locale }) || routine.schedule;
  const members = routine.members ?? [routine];
  const family = triggerFamily(routine.trigger);
  const canRun = routine.state !== "running" && !TERMINAL.includes(routine.state) && family !== "source" && family !== "manual";
  const canToggle = routine.state === "paused" || (active && routine.state !== "running");
  const act = async (kind: "run" | "toggle") => {
    setBusy(kind); setProblem("");
    try {
      if (kind === "run") await runTaskNow(routine.id);
      else for (const member of members) {
        if (TERMINAL.includes(member.state)) continue;
        if ((member.state === "paused") === (routine.state === "paused")) await setTaskEnabled(member.id, routine.state === "paused");
      }
    } catch (err) { setProblem(err instanceof Error ? err.message : String(err)); }
    finally { setBusy(null); onChanged(); }
  };
  const cost = formatCost(lastRun?.cost_usd, locale);
  const lastAt = lastRun?.finished_ms ?? lastRun?.started_ms ?? null;
  const tool = "rounded-md p-1.5 text-muted-foreground transition-colors duration-150 hover:bg-background hover:text-foreground focus-visible:outline focus-visible:outline-1 focus-visible:outline-ring disabled:opacity-40";
  return <li className="group relative">
    <div className="flex items-start gap-1 rounded-xl transition-colors duration-150 hover:bg-secondary/55 focus-within:bg-secondary/55">
      <button type="button" aria-label={title} aria-describedby={describedBy} onClick={onOpen}
        className="flex min-w-0 flex-1 cursor-pointer select-none items-start gap-2.5 rounded-xl px-2 py-2 text-left focus-visible:outline focus-visible:outline-1 focus-visible:outline-ring">
        <TriggerIcon trigger={routine.trigger} tone={tone} />
        <span className="min-w-0 flex-1">
          <span className={cn("block truncate text-[13px] font-medium leading-5", tone === "paused" || tone === "parked" ? "text-muted-foreground" : "text-foreground")}>{title}</span>
          <span id={describedBy} className="contents">
          <span className="block break-words text-[11.5px] leading-snug text-foreground-secondary">{sentence}</span>
          <span className="mt-0.5 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[11px] leading-4 text-muted-foreground">
            {routine.state === "running" && <span className="font-medium text-primary">{own("running")}</span>}
            {routine.state === "paused" && <span className={cn("font-medium", parked ? "text-warning" : "")}>{parked ? own("parked") : t("tasks_view.state.paused")}</span>}
            {routine.dueMs && active ? <span title={new Date(routine.dueMs).toLocaleString(locale, { timeZoneName: "short" })}>{t("society.card.next_run")}: {routine.dueMs <= now ? own("due_now") : relativeTime(routine.dueMs, now, locale)}</span> : null}
            {lastRun && lastRun.status !== "running" && lastAt ? <span className="inline-flex items-center gap-1" title={lastRun.error || lastRun.summary || undefined}>
              <span aria-hidden className="text-faint-foreground">·</span>
              <RunStatusIcon status={lastRun.status} label={runStateLabel(t, lastRun.status)} size={12} />
              <span className={lastRun.status === "failed" ? "text-destructive/90" : ""}>{relativeTime(lastAt, now, locale)}</span>
              {cost && <span className="tabular-nums">· {cost}</span>}
            </span> : null}
          </span>
          {lastRun?.status === "failed" && lastRun.error && <span className="mt-0.5 block truncate text-[11px] text-destructive/80" title={lastRun.error}>{lastRun.error}</span>}
          </span>
        </span>
      </button>
      <div className="flex shrink-0 items-center gap-0.5 self-center pr-1 opacity-0 transition-opacity duration-150 group-hover:opacity-100 group-focus-within:opacity-100 [@media(hover:none)]:opacity-100">
        {canRun && <button type="button" className={tool} disabled={busy !== null} onClick={() => void act("run")} aria-label={own("test_run")} title={own("test_run")}>
          {busy === "run" ? <Loader2 size={14} className="motion-safe:animate-spin" /> : <Play size={14} />}
        </button>}
        {canToggle && <button type="button" className={tool} disabled={busy !== null} onClick={() => void act("toggle")}
          aria-label={routine.state === "paused" ? own("resume") : own("pause")} title={routine.state === "paused" ? own("resume") : own("pause")}>
          {busy === "toggle" ? <Loader2 size={14} className="motion-safe:animate-spin" /> : routine.state === "paused" ? <Play size={14} className="text-success" /> : <Pause size={14} />}
        </button>}
      </div>
      {/* Outside the row button: the badge is a link of its own. */}
      <BuiltByBadge compact type="routine" id={routine.id} className="mt-2.5" />
    </div>
    {problem && <p role="alert" className="px-2 pb-1 text-[11px] text-destructive">{problem}</p>}
  </li>;
}
