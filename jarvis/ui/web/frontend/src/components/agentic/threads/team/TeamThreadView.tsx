import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Check, Loader2, Pause, Play, Send, ShieldAlert, Square, Trash2, X } from "lucide-react";
import { fill, useT } from "@/i18n";
import type { IdeProject } from "@/lib/agenticIdeApi";
import {
  PEER_PHASES,
  PLANNED_PHASES,
  TEAM_THREADS_KEY,
  commandTeamThread,
  deleteTeamThread,
  messageTeamThread,
  teamThreadKey,
  useTeamSeats,
  useTeamThread,
  type TeamCommand,
  type TeamMember,
  type TeamThread,
} from "@/lib/teamThreadsApi";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";
import { TEAM_DRAFT, useIdeThreadsStore } from "@/store/ideThreads";
import { stepsDone } from "./board";
import { buildGraph, withShortNames, YOU } from "./teamGraph";
import { TeamSide, tabKey, type RoomTab } from "./TeamSide";
import type { RoomNames } from "./TeamStory";
import { TeamThreadDraft } from "./TeamThreadDraft";

// The canvas brings its graph library along; it loads with the first team room opened.
const TeamCanvas = lazy(() => import("./TeamCanvas"));

/** Side by side from this width of the room; stacked below it. */
const SPLIT_MIN = 980;

/**
 * One team thread as a room: the team on a canvas, their chats beside it.
 *
 * The canvas shows who works with whom right now: every member and the
 * person as a node, every handoff as a line labelled with what went across.
 * The side column shows the chats themselves, one tab per member, plus the
 * shared story and (planner and builder) the plan. Everything opens in place;
 * the one action that leaves the room, a member's full thread, leads back.
 * The models never read this page: a coordinator on the server passes
 * contributions between them, and this view shows what it filed.
 */
export function TeamThreadView({ team, project, onScreen }: { team: string; project: IdeProject; onScreen: boolean }) {
  if (team === TEAM_DRAFT) return <TeamThreadDraft project={project} />;
  return <OpenTeamThread teamId={team} project={project} onScreen={onScreen} />;
}

/** Which tab each team room showed, so a visit to a member's full thread comes back to it. */
const rememberedTabs = new Map<string, { tab: RoomTab; following: boolean }>();

/** The member the room follows: the one already followed while it still works, else the first that works. */
export function followed(thread: TeamThread, current: RoomTab): RoomTab | null {
  const busy = thread.members.filter((member) => member.state === "active" && (member.working || member.waiting));
  if (current.kind === "member" && busy.some((member) => member.member_id === current.id)) return null;
  if (busy.length) return { kind: "member", id: busy[0].member_id };
  const over = thread.state === "done" || thread.state === "stopped" || thread.state === "failed";
  return over && current.kind !== "story" ? { kind: "story" } : null;
}

function OpenTeamThread({ teamId, project, onScreen }: { teamId: string; project: IdeProject; onScreen: boolean }) {
  const t = useT();
  const client = useQueryClient();
  const pushToast = useEventStore((state) => state.pushToast);
  const query = useTeamThread(teamId, onScreen);
  const seats = useTeamSeats(onScreen).data;
  const thread = useMemo(() => (query.data ? withShortNames(query.data) : undefined), [query.data]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const remembered = rememberedTabs.get(teamId);
  const [tab, setTabState] = useState<RoomTab>(remembered?.tab ?? { kind: "story" });
  const [following, setFollowing] = useState(remembered?.following ?? true);
  const [edge, setEdge] = useState<string | null>(null);
  const [wide, setWide] = useState(true);
  const room = useRef<HTMLDivElement | null>(null);

  useEffect(() => { rememberedTabs.set(teamId, { tab, following }); }, [teamId, tab, following]);

  // The room lays itself out by its own width, not the window's.
  useEffect(() => {
    const box = room.current;
    if (!box || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => setWide(box.clientWidth >= SPLIT_MIN));
    observer.observe(box);
    setWide(box.clientWidth === 0 || box.clientWidth >= SPLIT_MIN);
    return () => observer.disconnect();
  }, [thread !== undefined]);

  const graph = useMemo(() => (thread ? buildGraph(thread) : { nodes: [], edges: [] }), [thread]);
  const agentByProvider = useMemo(() => new Map((seats?.seats ?? []).map((seat) => [seat.provider, seat.agent])), [seats]);
  const members = thread?.members;
  const names = useMemo<RoomNames>(() => {
    const byId = new Map((members ?? []).map((member) => [member.member_id, member]));
    return {
      name: (id) => (id === YOU || id === "user" ? t("team_threads.room.you") : byId.get(id)?.name ?? id),
      agent: (member) => agentByProvider.get(member.provider) ?? "",
      member: (id) => byId.get(id),
    };
  }, [members, agentByProvider, t]);
  const agentOf = useCallback((member: TeamMember) => agentByProvider.get(member.provider) ?? "", [agentByProvider]);

  // While following, the side column shows whoever works right now.
  useEffect(() => {
    if (!thread || !following) return;
    const next = followed(thread, tab);
    if (next && tabKey(next) !== tabKey(tab)) setTabState(next);
  }, [thread, following, tab]);

  const pick = useCallback((next: RoomTab) => {
    setEdge(null);
    setFollowing(false);
    setTabState(next);
  }, []);
  const openNode = useCallback((id: string) => pick(id === YOU ? { kind: "story" } : { kind: "member", id }), [pick]);
  const openEdge = useCallback((id: string) => setEdge((current) => (current === id ? null : id)), []);
  const closeEdge = useCallback(() => setEdge(null), []);

  const run = async (work: () => Promise<TeamThread | { deleted: boolean }>) => {
    setBusy(true);
    try {
      const next = await work();
      if ("team_id" in next) client.setQueryData(teamThreadKey(teamId), next);
      void client.invalidateQueries({ queryKey: TEAM_THREADS_KEY });
      return true;
    } catch (error) {
      pushToast("error", error instanceof Error ? error.message : String(error));
      return false;
    } finally {
      setBusy(false);
    }
  };
  const command = (name: TeamCommand) => void run(() => commandTeamThread(teamId, name));
  const send = async () => {
    const message = text.trim();
    if (!message || busy) return;
    if (await run(() => messageTeamThread(teamId, message))) setText("");
  };
  const remove = async () => {
    if (await run(() => deleteTeamThread(teamId))) {
      rememberedTabs.delete(teamId);
      useIdeThreadsStore.getState().newThread(project.id);
    }
  };
  const openFull = (member: TeamMember) => {
    rememberedTabs.set(teamId, { tab: { kind: "member", id: member.member_id }, following: false });
    useIdeThreadsStore.getState().openMemberThread(member.session_id, project.id, teamId);
  };

  if (query.isError && !thread) {
    return <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center" data-testid="team-thread-missing">
      <p className="text-sm text-muted-foreground">{t("team_threads.missing")}</p>
      <button type="button" onClick={() => useIdeThreadsStore.getState().newThread(project.id)}
        className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-secondary">{t("ide_threads.new_thread")}</button>
    </div>;
  }
  if (!thread) {
    return <div className="flex h-full items-center justify-center" role="status" aria-label={t("team_threads.loading")}>
      <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
    </div>;
  }

  const over = thread.state === "done" || thread.state === "stopped" || thread.state === "failed";
  const waiting = thread.state === "needs_input" || thread.state === "paused";
  const disagreement = thread.state === "needs_input"
    && (thread.reason === "plan_disagreement" || thread.reason === "review_disagreement" || thread.reason === "step_disagreement");
  const selectedNode = edge ? null : tab.kind === "member" ? tab.id : null;

  const canvas = <Suspense fallback={<div className="flex h-full items-center justify-center" role="status" aria-label={t("team_threads.loading")}>
    <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
  </div>}>
    <TeamCanvas thread={thread} graph={graph} agentOf={agentOf} selectedNode={selectedNode} selectedEdge={edge}
      onOpenNode={openNode} onOpenEdge={openEdge} />
  </Suspense>;

  return <div className="flex h-full min-h-0 flex-col" data-testid="team-thread-view">
    <header className="shrink-0 border-b border-border px-4 py-2.5">
      <div className="flex min-w-0 items-center gap-3">
        <div className="min-w-0 flex-1">
          <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
            {t(`team_threads.mode.${thread.mode}`)} · {fill(t("team_threads.room.members_count"), { count: thread.members.length })}
          </p>
          <h1 className="truncate text-[15px] font-medium leading-6 text-foreground" title={thread.task}>{thread.title}</h1>
        </div>
        <StateLabel state={thread.state} />
        {thread.state === "running" && <>
          <IconButton label={t("team_threads.pause")} onClick={() => command("pause")} disabled={busy}><Pause className="h-3.5 w-3.5" /></IconButton>
          <IconButton label={t("team_threads.stop")} onClick={() => command("stop")} disabled={busy}><Square className="h-3.5 w-3.5" /></IconButton>
        </>}
        {over && (confirmDelete
          ? <span className="flex items-center gap-1">
            <span className="text-xs text-muted-foreground">{t("team_threads.delete_confirm")}</span>
            <IconButton label={t("team_threads.delete")} onClick={() => void remove()} disabled={busy}><Check className="h-3.5 w-3.5" /></IconButton>
            <IconButton label={t("ide_threads.cancel_renaming")} onClick={() => setConfirmDelete(false)}><X className="h-3.5 w-3.5" /></IconButton>
          </span>
          : <IconButton label={t("team_threads.delete")} onClick={() => setConfirmDelete(true)}><Trash2 className="h-3.5 w-3.5" /></IconButton>)}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-6 gap-y-2">
        <StepRail thread={thread} />
        {thread.plan && thread.plan.steps.length > 0 && <button type="button" onClick={() => pick({ kind: "plan" })} data-testid="team-plan-progress"
          className="shrink-0 rounded-md px-1 text-xs tabular-nums text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          {fill(t("team_threads.plan.title"), { version: thread.plan.version })} · {fill(t("team_threads.plan.progress"), {
            done: thread.plan.steps.filter((step) => step.status === "accepted").length, total: thread.plan.steps.length,
          })}
        </button>}
        <Meters thread={thread} />
      </div>
    </header>

    <div ref={room} className={cn("flex min-h-0 flex-1", wide ? "flex-row" : "flex-col")} data-layout={wide ? "split" : "stacked"}>
      <div className={cn("relative min-w-0 bg-background", wide ? "min-h-0 flex-1" : "h-[min(320px,42%)] shrink-0 border-b border-border")}>
        {canvas}
      </div>
      <div className={cn("flex min-h-0 min-w-0 flex-col", wide ? "w-[clamp(380px,44%,640px)] shrink-0 border-l border-border" : "flex-1")}>
        <TeamSide thread={thread} graph={graph} names={names} folder={thread.cwd || project.path}
          tab={tab} onTab={pick} following={following} edge={edge} onCloseEdge={closeEdge} onOpenFull={openFull}
          onFollow={() => { setEdge(null); setFollowing(!following); }} />
      </div>
    </div>

    <footer className="shrink-0 border-t border-border px-4 pb-3 pt-2.5">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-2">
        {waiting && <div role="status" data-testid="team-thread-waiting"
          className="flex flex-wrap items-center gap-2 border-l-[3px] border-warning py-1 pl-3 text-sm text-foreground">
          <ShieldAlert aria-hidden className="h-4 w-4 shrink-0 text-warning" />
          <span className="min-w-0 flex-1">
            {fill(t(`team_threads.reason.${thread.reason || "user"}`), {
              note: thread.note, rounds: thread.reason === "plan_disagreement" ? thread.rounds.plan : thread.rounds.review,
              number: thread.rounds.step ?? 0,
            })}
          </span>
          {disagreement && <TextButton onClick={() => command("accept")} disabled={busy}>
            {t(thread.reason === "plan_disagreement" ? "team_threads.accept_plan"
              : thread.reason === "step_disagreement" ? "team_threads.accept_step" : "team_threads.accept_work")}
          </TextButton>}
          <TextButton onClick={() => command("resume")} disabled={busy} primary>
            <Play aria-hidden className="h-3.5 w-3.5" />
            {t(disagreement ? "team_threads.another_round" : "team_threads.resume")}
          </TextButton>
          <TextButton onClick={() => command("stop")} disabled={busy}>{t("team_threads.stop")}</TextButton>
        </div>}
        {thread.state === "failed" && <p role="alert" className="border-l-[3px] border-destructive py-1 pl-3 text-sm text-foreground">
          {fill(t(`team_threads.reason.${thread.reason || "error"}`), { note: thread.note, rounds: 0 })}
        </p>}
        {!over && <form onSubmit={(event) => { event.preventDefault(); void send(); }}
          className="flex items-end gap-1 rounded-[20px] border border-border bg-secondary px-2 py-1 focus-within:border-border-strong">
          <textarea value={text} rows={1} onChange={(event) => setText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                void send();
              }
            }}
            aria-label={t("team_threads.message")} placeholder={t(disagreement ? "team_threads.message_decide" : "team_threads.message")}
            data-testid="team-thread-message"
            className="max-h-[160px] min-h-8 flex-1 resize-none bg-transparent px-2 py-1.5 text-sm text-foreground outline-none placeholder:text-muted-foreground" />
          <button type="submit" disabled={busy || !text.trim()} aria-label={t("team_threads.send")} title={t("team_threads.send")}
            className="mb-0.5 flex h-7 w-7 items-center justify-center rounded-full bg-primary text-primary-foreground disabled:opacity-40">
            <Send className="h-3.5 w-3.5" aria-hidden />
          </button>
        </form>}
      </div>
    </footer>
  </div>;
}

/* ------------------------------------------------------------------ header */

function StateLabel({ state }: { state: TeamThread["state"] }) {
  const t = useT();
  return <span data-testid="team-thread-state" className={cn(
    "flex shrink-0 items-center gap-1.5 text-xs font-medium",
    state === "done" ? "text-success"
      : state === "needs_input" || state === "paused" ? "text-warning"
        : state === "failed" ? "text-destructive"
          : state === "running" ? "text-accent" : "text-muted-foreground",
  )}>
    <span aria-hidden className={cn("h-1.5 w-1.5 rounded-full bg-current", state === "running" && "team-pulse")} />
    {t(`team_threads.state.${state}`)}
  </span>;
}

function IconButton({ label, onClick, disabled, children }: { label: string; onClick: () => void; disabled?: boolean; children: ReactNode }) {
  return <button type="button" aria-label={label} title={label} onClick={onClick} disabled={disabled}
    className="rounded-md p-1.5 text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-40">
    {children}
  </button>;
}

function TextButton({ onClick, disabled, primary, children }: { onClick: () => void; disabled?: boolean; primary?: boolean; children: ReactNode }) {
  return <button type="button" onClick={onClick} disabled={disabled}
    className={cn(
      "inline-flex shrink-0 items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-40",
      primary ? "bg-primary text-primary-foreground" : "border border-border text-foreground hover:bg-secondary",
    )}>
    {children}
  </button>;
}

/** The steps as one line: done, now, still to come. */
function StepRail({ thread }: { thread: TeamThread }) {
  const t = useT();
  const done = stepsDone(thread);
  const active = thread.state === "running";
  const phases: readonly string[] = thread.mode === "planner_builder" ? PLANNED_PHASES : PEER_PHASES;
  return <ol className="flex min-w-0 max-w-[720px] flex-1 items-center gap-1" aria-label={t("team_threads.steps")}>
    {phases.map((phase, index) => {
      const isDone = index < done;
      const now = index === done;
      return <li key={phase} aria-current={now ? "step" : undefined} className="flex min-w-0 flex-1 items-center gap-1.5 last:flex-none">
        <span aria-hidden className={cn(
          "flex h-4 w-4 shrink-0 items-center justify-center rounded-full border text-[9px] font-medium tabular-nums",
          isDone ? "border-foreground/40 bg-foreground/10 text-foreground"
            : now ? "border-accent text-accent" : "border-border text-muted-foreground",
          now && active && "team-step-now",
        )}>
          {isDone ? <Check className="h-2.5 w-2.5" strokeWidth={3} /> : index + 1}
        </span>
        <span className={cn("truncate text-xs", now ? "font-medium text-foreground" : isDone ? "text-foreground/80" : "text-muted-foreground")}>
          {t(`team_threads.phase.${phase}`)}
        </span>
        {index < phases.length - 1 && <span aria-hidden className={cn("mx-1 h-px min-w-2 flex-1", isDone ? "bg-foreground/30" : "bg-border")} />}
      </li>;
    })}
  </ol>;
}

/** Time and turns against their bounds. */
function Meters({ thread }: { thread: TeamThread }) {
  const t = useT();
  const minutes = Math.floor(thread.usage.elapsed_ms / 60_000);
  const meter = (value: number, max: number, label: string) => {
    const share = max > 0 ? Math.min(1, value / max) : 0;
    return <span className="flex items-center gap-1.5">
      <span aria-hidden className="h-1 w-10 overflow-hidden rounded-full bg-secondary">
        <span className={cn("block h-full rounded-full", share >= 0.9 ? "bg-warning" : "bg-foreground/40")} style={{ width: `${Math.max(share * 100, value > 0 ? 6 : 0)}%` }} />
      </span>
      <span className="tabular-nums">{label}</span>
    </span>;
  };
  return <div className="flex shrink-0 items-center gap-4 text-xs text-muted-foreground" data-testid="team-thread-usage"
    title={thread.usage.cost_usd > 0
      ? `${t("team_threads.cost_hint")}${thread.usage.cost_partial ? ` ${t("team_threads.cost_partial")}` : ""}`
      : undefined}>
    {meter(minutes, thread.limits.max_minutes, fill(t("team_threads.meter_time"), { minutes, max_minutes: thread.limits.max_minutes }))}
    {meter(thread.usage.turns, thread.limits.max_turns, fill(t("team_threads.meter_turns"), { turns: thread.usage.turns, max_turns: thread.limits.max_turns }))}
    {thread.usage.cost_usd > 0 && <span className="tabular-nums">≈ ${thread.usage.cost_usd.toFixed(2)}</span>}
  </div>;
}
