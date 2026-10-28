/**
 * One routine, as a task the person can understand at a glance and leave
 * running: what triggers it (as a sentence), whether it is on, a test run,
 * "edit in chat", the last failure, every run with its duration and cost,
 * and the full editor (instruction, model seat, schedules, connections).
 * Backed by the existing task scheduler.
 */
import { useEffect, useState } from "react";
import { useQueries, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Loader2 } from "lucide-react";
import { useT } from "@/i18n";
import { useRunLocale } from "@/components/runs/format";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import { cancelAndDeleteTask, cancelTask, fetchTask, runTaskNow, setTaskEnabled } from "@/lib/tasksApi";
import { describeTrigger, displayRoutineTitle, type LiveRoutine } from "../cardData";
import type { TaskDetail } from "@/lib/tasksApi";
import { useSocietyAgent } from "../data";
import { TriggerBuilder } from "./TriggerBuilder";
import { WebhookConnection } from "./WebhookConnection";
import { SourceControls } from "./SourceControls";
import { RoutineSeatPicker, useSeatLabel, type RoutineSeat } from "./RoutineSeatPicker";
import { useRoutineNavigation } from "../chat/routineNavigation";
import { routineSkipReason } from "@/lib/skipReasons";
import type { RoutineTone } from "./routines/TriggerIcon";
import { humanSchedule } from "./routines/humanSchedule";
import { calmMoment, fill, formatDuration, relativeTime } from "./routines/format";
import { markRoutinesSeen, useRoutineRuns } from "./routines/routinesApi";
import { mergeRunDetails, routineRuns, type Run } from "./routines/runs";
import { RunHistory, runReason } from "./routines/RunHistory";
import { seedAgentComposer } from "./routines/editThroughChat";
import { useNow } from "./routines/useNow";

export { routineRuns } from "./routines/runs";

const field = "w-full rounded-lg border border-border bg-background px-3 py-2 text-[12px] text-foreground transition-colors focus:border-border-strong focus:outline-none disabled:opacity-60";
const button = "inline-flex items-center gap-1.5 rounded-full bg-secondary px-3.5 py-1.5 text-[13px] font-medium text-foreground transition-colors duration-150 hover:bg-border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-40";
const primary = "inline-flex items-center gap-1.5 rounded-full bg-foreground px-3.5 py-1.5 text-[13px] font-medium text-background transition-colors duration-150 hover:bg-foreground/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-40";
const heading = "text-xs font-medium text-muted-foreground";
const recurring = ["every", "calendar", "cron", "webhook", "event_hook", "source", "on_event"];
const terminal = ["completed", "failed", "cancelled", "interrupted"];
const timeKinds = ["every", "calendar", "cron"];

async function writeRoutine(url: string, body: unknown, method = "PATCH") {
  const response = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!response.ok) {
    const error = await response.json().catch(() => null) as { detail?: unknown } | null;
    throw new Error(typeof error?.detail === "string" ? error.detail : `HTTP ${response.status}`);
  }
}

export function AgentRoutineDetail({ agentId, routine, onClose, parked = false }: {
  agentId: string; routine: LiveRoutine; onClose: () => void;
  /** Paused by away-parking (the list knows; the banner explains). */
  parked?: boolean;
}) {
  const t = useT();
  const locale = useRunLocale();
  const label = (key: string) => t(`society.routine_detail.${key}`);
  const own = (key: string) => t(`society.agent_routines.detail.${key}`);
  const client = useQueryClient();
  const members = routine.members ?? [routine];
  const queries = useQueries({ queries: members.map((member) => ({
    queryKey: ["tasks", "detail", member.id], queryFn: () => fetchTask(member.id),
    retry: false, refetchInterval: import.meta.env.MODE === "test" ? false : 3000,
  })) });
  const { agent } = useSocietyAgent(agentId);
  const [draft, setDraft] = useState<{ title: string; prompt: string } | null>(null);
  const [editing, setEditing] = useState<LiveRoutine | "new" | null>(null);
  const [schedule, setSchedule] = useState<Record<string, unknown> | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const openChat = useRoutineNavigation((state) => state.open);
  useEffect(() => { markRoutinesSeen(agentId); }, [agentId]);
  const details = queries.map((query) => query.data);
  const first = details[0];
  const rawPrompt = String((first?.spec?.action as { prompt?: string } | undefined)?.prompt ?? "");
  const marker = rawPrompt.indexOf("\nRoutine:\n");
  const saved = { title: displayRoutineTitle(first?.title ?? routine.title), prompt: marker >= 0 ? rawPrompt.slice(marker + 10) : routine.prompt ?? rawPrompt };
  const values = draft ?? saved;
  const seatAction = (first?.spec?.action ?? {}) as { kind?: string; provider?: unknown; model?: unknown; effort?: unknown; account_id?: unknown };
  const savedSeat: RoutineSeat = {
    provider: String(seatAction.provider ?? ""),
    model: String(seatAction.model ?? ""),
    effort: String(seatAction.effort ?? ""),
    account_id: String(seatAction.account_id ?? ""),
  };
  const [seatDraft, setSeatDraft] = useState<RoutineSeat | null>(null);
  const [seatOpen, setSeatOpen] = useState(false);
  const seat = seatDraft ?? savedSeat;
  const seatName = useSeatLabel(seat);
  const seatDirty = seatDraft !== null && (
    seatDraft.provider !== savedSeat.provider || seatDraft.model !== savedSeat.model ||
    seatDraft.effort !== savedSeat.effort || seatDraft.account_id !== savedSeat.account_id
  );
  const ready = details.every(Boolean);
  const running = details.some((detail) => detail?.state === "running");
  const now = useNow(running ? 1000 : 30_000);
  const active = details.some((detail) => detail && detail.state !== "paused" && !terminal.includes(detail.state));
  // Until every timing has loaded, the routine's own state speaks for the switch and its words.
  const shownActive = ready ? active : routine.state !== "paused";
  const editable = ready && !running && details.every((detail, index) => detail && (
    index > 0 && terminal.includes(detail.state) || recurring.includes(detail.trigger_type) && !terminal.includes(detail.state)
  ));
  const seatEditable = ready && !running && seatAction.kind !== "workflow";
  const url = `/api/society/agents/${encodeURIComponent(agentId)}/routines`;
  const refresh = () => Promise.all([
    client.invalidateQueries({ queryKey: ["tasks"] }),
    client.invalidateQueries({ queryKey: ["society", "agent-routines", agentId] }),
    client.invalidateQueries({ queryKey: ["society", "routine-activity", agentId] }),
    client.invalidateQueries({ queryKey: ["society", "routine-runs", agentId] }),
  ]);
  const act = async (fn: () => Promise<void>) => {
    setPending(true); setError(""); setNotice("");
    try { await fn(); }
    catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { await refresh(); setPending(false); }
  };
  const update = (member: LiveRoutine, nextSchedule: unknown) => writeRoutine(`${url}/${encodeURIComponent(member.id)}`, {
    title: values.title.trim(), prompt: values.prompt.trim(), schedule: nextSchedule,
    ...(seatDirty ? { provider: seat.provider, model: seat.model, effort: seat.effort, account_id: seat.account_id } : {}),
  });
  const valid = Boolean(values.title.trim() && values.prompt.trim());
  const history = useRoutineRuns(agentId, members.map((member) => member.id), running);
  const localRuns = details.flatMap((detail) => detail ? routineRuns(detail.id, detail.steps) : []).sort((a, b) => b.timestamp - a.timestamp);
  const runs = mergeRunDetails(localRuns, history.runs);
  const latest = runs[0];
  const lastFailure = runs.find((run) => run.status === "failed");
  const showFailure = lastFailure && (latest?.status === "failed" || latest?.status === "interrupted") ? lastFailure : undefined;
  const renderConnection = (detail: TaskDetail) => {
    if (detail.trigger_type === "webhook") return <WebhookConnection taskId={detail.id} />;
    if (detail.trigger_type === "source") return <SourceControls taskId={detail.id} source={(detail.trigger as { source: { kind: string } }).source} />;
    return null;
  };
  const sentenceOf = (trigger: unknown) => humanSchedule(trigger, { t, locale }) || describeTrigger(trigger, t);
  const headTrigger = first?.trigger ?? routine.trigger;
  const sentence = sentenceOf(headTrigger);
  const due = details.filter((detail) => detail?.state === "scheduled" && detail.due_at_ns).map((detail) => detail!.due_at_ns! / 1e6);
  const nextMs = due.length ? Math.min(...due) : null;
  const tone: RoutineTone = running ? "running" : !active ? (parked ? "parked" : "paused") : latest?.status === "failed" ? "failed" : "active";
  const canTest = !(pending || !ready || running || Boolean(draft) || Boolean(editing) || !first || terminal.includes(first.state) || first.trigger_type === "source");

  const openRun = (run: Run) => {
    const ownChat = run.sessionId?.startsWith(`society:${agentId}:routine:${run.taskId}:`);
    openChat({ agentId, sessionId: ownChat ? run.sessionId! : `society:${agentId}`,
      title: saved.title, timestamp: run.timestamp,
      result: run.status === "skipped" ? routineSkipReason(t, run.skipCode, run.skipProvider, run.text) : run.text,
      ...(!ownChat ? { legacy: { taskId: run.taskId, startedMs: run.startedMs, finishedMs: run.finishedMs } } : {}),
    });
  };
  const editInChat = () => void seedAgentComposer(
    { tier: agent?.tier ?? "specialist", chatSessionId: agent?.chatSessionId ?? `society:${agentId}` },
    fill(own("edit_prompt"), { title: saved.title, schedule: sentence }),
  );
  const runningRun = runs.find((run) => run.status === "running");
  const status = running
    ? `${own("running")}${runningRun?.startedMs ? ` · ${formatDuration(Math.max(0, now - runningRun.startedMs))}` : ""}`
    : !active ? (parked ? own("parked") : t("tasks_view.state.paused"))
    : nextMs ? `${t("society.card.next_run")} ${nextMs <= now ? own("due_now") : relativeTime(nextMs, now, locale)}` : own("active");

  return <section className="min-h-0 flex-1 space-y-4 overflow-y-auto pb-4 text-foreground" data-testid="agent-routine-detail">
    <button type="button" className="-ml-1 flex items-center gap-1 rounded-md px-1 py-0.5 text-[12px] text-muted-foreground transition-colors hover:text-foreground" disabled={pending} onClick={onClose}><ArrowLeft size={14} />{t("society.card.routines")}</button>

    <header className="rounded-2xl bg-card p-4">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-[14px] font-semibold leading-5 text-foreground-strong" title={saved.title}>{saved.title}</h3>
          {sentence && <p className="text-[12px] leading-snug text-foreground-secondary" data-testid="routine-schedule-sentence">{sentence}</p>}
          <p className={cn("mt-0.5 text-xs leading-4", tone === "parked" ? "text-warning" : tone === "running" ? "text-primary" : "text-muted-foreground")}
            title={nextMs ? new Date(nextMs).toLocaleString(locale, { timeZoneName: "short" }) : undefined}>{status}</p>
        </div>
        <label className="flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground"><Switch aria-label={label(shownActive ? "active" : "paused")} checked={shownActive} disabled={pending || !editable} onCheckedChange={(enabled) => void act(async () => {
          for (const detail of details) if (detail && !terminal.includes(detail.state) && (detail.state === "paused") === enabled) await setTaskEnabled(detail.id, enabled);
        })} /><span className="sr-only sm:not-sr-only" aria-hidden data-testid="routine-switch-state">{label(shownActive ? "active" : "paused")}</span></label>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        <button type="button" className={primary} disabled={!canTest} onClick={() => void act(async () => {
          await runTaskNow(routine.id); setNotice(label("test_started"));
        })}>{running ? <Loader2 size={13} className="motion-safe:animate-spin" /> : null}{label("test")}</button>
        <button type="button" className={button} onClick={editInChat}>{own("edit_in_chat")}</button>
      </div>
    </header>

    {queries.some((query) => query.isLoading) && <p role="status" className="text-[12px] text-muted-foreground">{t("tasks_view.loading_details")}</p>}
    {queries.some((query) => query.error) && <p role="alert" className="text-[12px] text-destructive">{t("tasks_view.load_error")}</p>}
    {error && <p role="alert" className="break-words text-[12px] text-destructive">{error}</p>}
    {notice && <p role="status" className="text-[12px] text-success">{notice}</p>}

    {showFailure && <div className="rounded-xl border border-destructive/30 bg-destructive/[0.05] p-3" data-testid="routine-last-failure">
      <div className="flex items-center gap-1.5 text-xs font-medium text-destructive">
        {own("last_failure")}
        <span className="ml-auto font-normal normal-case tracking-normal text-muted-foreground">{relativeTime(showFailure.finishedMs ?? showFailure.timestamp, now, locale)}</span>
      </div>
      <p className="mt-1.5 break-words text-[12px] leading-snug text-foreground-secondary">{runReason(t, showFailure) || own("failed_no_detail")}</p>
      <button type="button" className="mt-2 text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline" onClick={() => openRun(showFailure)}>{own("open_failed_run")}</button>
    </div>}

    <section className="space-y-2">
      <label className="block space-y-1 text-xs text-muted-foreground">{label("name")}<input className={field} aria-label={label("name")} maxLength={200} disabled={pending || !editable || Boolean(editing)} value={values.title} onChange={(event) => setDraft({ ...values, title: event.target.value })} /></label>
      <label className="block space-y-1 text-xs text-muted-foreground">{label("prompt")}<textarea className={cn(field, "resize-y leading-relaxed")} aria-label={label("prompt")} maxLength={16000} rows={6} disabled={pending || !editable || Boolean(editing) || (first?.spec?.action as { kind?: string } | undefined)?.kind !== "agent"} value={values.prompt} onChange={(event) => setDraft({ ...values, prompt: event.target.value })} /></label>
      {draft && <div className="flex gap-2"><button className={primary} disabled={pending || !valid || !editable || Boolean(editing)} onClick={() => void act(async () => {
        for (const [index, member] of members.entries()) if (!terminal.includes(details[index]!.state)) await update(member, details[index]?.trigger);
        setDraft(null); setSeatDraft(null); setSeatOpen(false); setNotice(label("saved"));
      })}>{label("save")}</button><button className={button} disabled={pending} onClick={() => setDraft(null)}>{label("cancel")}</button></div>}
    </section>

    {seatEditable && <div className="space-y-2 rounded-2xl bg-card p-4">
      <div className="flex items-center justify-between gap-2">
        <h4 className={heading}>{label("model")}</h4>
        <button
          type="button"
          className="text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline disabled:opacity-50"
          disabled={pending || !editable || Boolean(editing)}
          onClick={() => setSeatOpen((open) => !open)}
        >
          {seatOpen ? label("cancel") : label("change")}
        </button>
      </div>
      <p className="text-[12px]">
        {!seat.provider ? label("follow_agent") : seatName}
      </p>
      {seatOpen && <RoutineSeatPicker seat={seat} disabled={pending || !editable || Boolean(editing)} onChange={setSeatDraft} />}
    </div>}
    {seatDirty && <div className="flex gap-2"><button className={primary} disabled={pending || !valid || !editable || Boolean(editing) || Boolean(draft)} onClick={() => void act(async () => {
      for (const [index, member] of members.entries()) if (!terminal.includes(details[index]!.state)) await update(member, details[index]?.trigger);
      setSeatDraft(null); setSeatOpen(false); setNotice(label("saved"));
    })}>{label("save")}</button><button className={button} disabled={pending} onClick={() => setSeatDraft(null)}>{label("cancel")}</button></div>}

    <section className="space-y-2">
      <h4 className={heading}>{label("when")}</h4>
      <div className="divide-y divide-border/50 overflow-hidden rounded-2xl bg-card">
        {members.map((member, index) => {
          const detail = details[index];
          if (index > 0 && detail && terminal.includes(detail.state)) return null;
          return <div key={member.id} className="space-y-1 px-3 py-2.5">
            <button className="flex w-full items-start gap-2 rounded text-left text-[12px] transition-colors enabled:hover:text-foreground disabled:opacity-80" disabled={pending || !editable || Boolean(draft) || !detail || !timeKinds.includes(detail.trigger_type)} onClick={() => { setEditing({ ...member, trigger: detail?.trigger }); setSchedule(null); }}>
              <span>{sentenceOf(detail?.trigger ?? member.trigger)}</span>
            </button>
            {detail?.due_at_ns && detail.state === "scheduled" ? <p className="text-xs text-muted-foreground" title={new Date(detail.due_at_ns / 1e6).toLocaleString(locale, { timeZoneName: "short" })}>{t("society.card.next_run")}: {calmMoment(detail.due_at_ns / 1e6, now, locale)}</p> : null}
            {detail && <div>{renderConnection(detail)}</div>}
            {index > 0 && <button className="text-xs text-muted-foreground hover:text-foreground" disabled={pending || !editable || Boolean(draft)} onClick={() => void act(async () => { await cancelTask(member.id); })}>{label("remove_schedule")}</button>}
          </div>;
        })}
        <div className="px-3 py-2">
          <button className="flex items-center gap-1 text-[12px] text-muted-foreground transition-colors enabled:hover:text-foreground disabled:opacity-50" disabled={pending || !editable || Boolean(draft)} onClick={() => { setEditing("new"); setSchedule(null); }}>{label("add_schedule")}</button>
        </div>
      </div>
      {editing && <div className="space-y-2 rounded-2xl bg-card p-4">
        <TriggerBuilder key={editing === "new" ? "new" : editing.id} timeOnly initialValue={editing === "new" ? undefined : editing.trigger as Record<string, unknown>} onChange={setSchedule} />
        <button className={primary} disabled={pending || !schedule || !valid} onClick={() => void act(async () => {
          if (editing === "new") await writeRoutine(url, { title: values.title, prompt: values.prompt, schedule, parent_task_id: routine.id }, "POST");
          else await update(editing, schedule);
          setEditing(null); setNotice(label("saved"));
        })}>{label("save")}</button>{" "}<button className={button} disabled={pending} onClick={() => setEditing(null)}>{label("cancel")}</button>
      </div>}
    </section>

    <RunHistory runs={runs} ready={ready} locale={locale} onOpen={openRun} />

    <footer className="space-y-2 border-t border-border/70 pt-3">
      <button type="button" className="inline-flex items-center rounded-full px-3 py-1.5 text-[13px] text-muted-foreground transition-colors hover:bg-secondary hover:text-destructive disabled:opacity-40" disabled={pending || !ready || running} onClick={() => setConfirmDelete(true)}>{label("delete")}</button>
      {confirmDelete && <div className="space-y-2 rounded-xl border border-destructive/30 bg-destructive/[0.04] p-3" role="alert">
        <p className="text-[12px] text-foreground">{label("delete_confirm")}</p>
        <p className="text-xs text-muted-foreground">{own("delete_note")}</p>
        <div className="flex gap-2">
          <button className="rounded-lg bg-destructive px-2.5 py-1.5 text-[12px] font-medium text-destructive-foreground disabled:opacity-50" disabled={pending} onClick={() => void act(async () => {
            for (const detail of [...details].reverse()) if (detail) await cancelAndDeleteTask(detail.id, !terminal.includes(detail.state));
            onClose();
          })}>{label("delete")}</button>
          <button className={button} disabled={pending} onClick={() => setConfirmDelete(false)}>{label("cancel")}</button>
        </div>
      </div>}
    </footer>
  </section>;
}
