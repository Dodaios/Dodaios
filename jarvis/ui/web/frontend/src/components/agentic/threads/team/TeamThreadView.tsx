import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  Brain, Check, ChevronDown, ChevronRight, FileText, FolderOpen, Globe, Hammer, Loader2, MessageSquareText, Pause,
  Pencil, Play, Search, Send, ShieldAlert, Square, Terminal, Trash2, Users, Wrench, X,
} from "lucide-react";
import { AgentMark } from "@/components/agentic/AgentMark";
import { ChatMarkdown } from "@/components/agentchat/ChatMarkdown";
import { ScrollToEndButton } from "@/components/ui/scroll-to-end-button";
import { useStickToBottom } from "@/hooks/useStickToBottom";
import { fill, useT } from "@/i18n";
import type { IdeProject } from "@/lib/agenticIdeApi";
import {
  TEAM_THREAD_PHASES,
  TEAM_THREADS_KEY,
  commandTeamThread,
  deleteTeamThread,
  messageTeamThread,
  teamThreadKey,
  useTeamSeats,
  useTeamThread,
  type TeamCommand,
  type TeamEntry,
  type TeamFinding,
  type TeamMember,
  type TeamThread,
} from "@/lib/teamThreadsApi";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";
import { TEAM_DRAFT, useIdeThreadsStore } from "@/store/ideThreads";
import { buildBoard, gist, stepsDone, type BandCell, type StepBand } from "./board";
import { liveLines, liveTokens, useMemberTurn, type LiveLine } from "./memberLive";
import { TeamThreadDraft } from "./TeamThreadDraft";

/** The board's width: wide enough for four lanes, never wider than reads well. */
const MEASURE = "mx-auto w-full max-w-6xl";
/** A lane never gets narrower than this; a team too wide for the window scrolls sideways. */
const LANE_MIN = 208;

const lanes = (count: number) => ({ gridTemplateColumns: `repeat(${Math.max(1, count)}, minmax(${LANE_MIN}px, 1fr))` });

/**
 * One team thread as a board: a lane per member, a band per step.
 *
 * Everything is on one page. A member whose turn runs shows its newest tool
 * calls and words as they happen; a finished contribution is a card with its
 * gist, and a click opens the whole text under its band. The models never
 * read this page: a coordinator on the server passes contributions between
 * them, and this view shows what it filed.
 */
export function TeamThreadView({ team, project, onScreen }: { team: string; project: IdeProject; onScreen: boolean }) {
  if (team === TEAM_DRAFT) return <TeamThreadDraft project={project} />;
  return <OpenTeamThread teamId={team} project={project} onScreen={onScreen} />;
}

function OpenTeamThread({ teamId, project, onScreen }: { teamId: string; project: IdeProject; onScreen: boolean }) {
  const t = useT();
  const client = useQueryClient();
  const pushToast = useEventStore((state) => state.pushToast);
  const query = useTeamThread(teamId, onScreen);
  const seats = useTeamSeats(onScreen).data;
  const thread = query.data;
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const { rootRef, contentRef, atEnd, jumpToEnd, follow, release } = useStickToBottom();
  useLayoutEffect(follow, [follow, thread?.entries.length, thread?.state]);

  const names = useMemo(
    () => new Map((thread?.members ?? []).map((member) => [member.member_id, member.name])),
    [thread?.members],
  );
  const agentOf = useMemo(
    () => new Map((seats?.seats ?? []).map((seat) => [seat.provider, seat.agent])),
    [seats],
  );
  const bands = useMemo(() => (thread ? buildBoard(thread) : []), [thread]);

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
    if (await run(() => deleteTeamThread(teamId))) useIdeThreadsStore.getState().newThread(project.id);
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
    && (thread.reason === "plan_disagreement" || thread.reason === "review_disagreement");
  const count = thread.members.length;

  return <div className="flex h-full min-h-0 flex-col" data-testid="team-thread-view">
    <header className="shrink-0 border-b border-border px-5 pb-3 pt-3">
      <div className={cn(MEASURE, "flex flex-col gap-3")}>
        <div className="flex items-center gap-2">
          <Users aria-hidden className="h-4 w-4 shrink-0 text-muted-foreground" />
          <h1 className="min-w-0 flex-1 truncate text-sm font-medium text-foreground" title={thread.title}>{thread.title}</h1>
          <StateBadge state={thread.state} />
          {thread.state === "running" && <>
            <IconButton label={t("team_threads.pause")} onClick={() => command("pause")} disabled={busy}><Pause className="h-3.5 w-3.5" /></IconButton>
            <IconButton label={t("team_threads.stop")} onClick={() => command("stop")} disabled={busy}><Square className="h-3.5 w-3.5" /></IconButton>
          </>}
          {over && (confirmDelete
            ? <>
              <span className="text-xs text-muted-foreground">{t("team_threads.delete_confirm")}</span>
              <IconButton label={t("team_threads.delete")} onClick={() => void remove()} disabled={busy}><Check className="h-3.5 w-3.5" /></IconButton>
              <IconButton label={t("ide_threads.cancel_renaming")} onClick={() => setConfirmDelete(false)}><X className="h-3.5 w-3.5" /></IconButton>
            </>
            : <IconButton label={t("team_threads.delete")} onClick={() => setConfirmDelete(true)}><Trash2 className="h-3.5 w-3.5" /></IconButton>)}
        </div>
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
          <StepRail thread={thread} />
          <Meters thread={thread} />
        </div>
      </div>
    </header>

    <div className="relative flex min-h-0 flex-1 flex-col">
      <div ref={rootRef} className="chat-scroller min-h-0 flex-1 overflow-auto px-5 pb-5" role="log" aria-label={thread.title}>
        <div ref={contentRef} className={cn(MEASURE, "flex flex-col gap-4")} style={{ minWidth: count * LANE_MIN + (count - 1) * 12 }}>
          {/* Who sits in which lane stays in view while the work scrolls under it. */}
          <ul className="sticky top-0 z-10 grid gap-3 bg-background pb-2 pt-4" style={lanes(count)} aria-label={t("team_threads.members")}>
            {thread.members.map((member) => <LaneHead key={member.member_id} member={member}
              agent={agentOf.get(member.provider) ?? ""} builder={thread.builder === member.member_id} over={over}
              onOpen={() => useIdeThreadsStore.getState().openThread(member.session_id, project.id)} />)}
          </ul>
          {bands.map((band) => band.type === "note"
            ? <Note key={band.key} entry={band.entry} names={names} />
            : <Band key={band.key} band={band} names={names} onOpen={release} />)}
          {thread.issues.length > 0 && <Issues thread={thread} names={names} />}
        </div>
      </div>
      {!atEnd && <ScrollToEndButton onClick={jumpToEnd} testId="team-thread-scroll-end" className="top-auto bottom-3" />}
    </div>

    <footer className="shrink-0 px-5 pb-4 pt-2">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-2">
        {waiting && <div role="status" data-testid="team-thread-waiting"
          className="flex flex-wrap items-center gap-2 rounded-xl border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-foreground">
          <ShieldAlert aria-hidden className="h-4 w-4 shrink-0 text-warning" />
          <span className="min-w-0 flex-1">
            {fill(t(`team_threads.reason.${thread.reason || "user"}`), {
              note: thread.note, rounds: thread.reason === "plan_disagreement" ? thread.rounds.plan : thread.rounds.review,
            })}
          </span>
          {disagreement && <TextButton onClick={() => command("accept")} disabled={busy}>
            {t(thread.reason === "plan_disagreement" ? "team_threads.accept_plan" : "team_threads.accept_work")}
          </TextButton>}
          <TextButton onClick={() => command("resume")} disabled={busy} primary>
            <Play aria-hidden className="h-3.5 w-3.5" />
            {t(disagreement ? "team_threads.another_round" : "team_threads.resume")}
          </TextButton>
          <TextButton onClick={() => command("stop")} disabled={busy}>{t("team_threads.stop")}</TextButton>
        </div>}
        {thread.state === "failed" && <p role="alert" className="rounded-xl border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-foreground">
          {fill(t(`team_threads.reason.${thread.reason || "error"}`), { note: thread.note, rounds: 0 })}
        </p>}
        {!over && <form onSubmit={(event) => { event.preventDefault(); void send(); }}
          className="flex items-end gap-1 rounded-[24px] border border-border bg-secondary px-2 py-1.5 focus-within:border-border-strong">
          <textarea value={text} rows={1} onChange={(event) => setText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                void send();
              }
            }}
            aria-label={t("team_threads.message")} placeholder={t(disagreement ? "team_threads.message_decide" : "team_threads.message")}
            data-testid="team-thread-message"
            className="max-h-[180px] min-h-8 flex-1 resize-none bg-transparent px-2 py-1.5 text-sm text-foreground outline-none placeholder:text-muted-foreground" />
          <button type="submit" disabled={busy || !text.trim()} aria-label={t("team_threads.send")} title={t("team_threads.send")}
            className="flex h-8 w-8 items-center justify-center rounded-full bg-primary text-primary-foreground disabled:opacity-40">
            <Send className="h-3.5 w-3.5" aria-hidden />
          </button>
        </form>}
      </div>
    </footer>
  </div>;
}

/* ------------------------------------------------------------------ header */

function StateBadge({ state }: { state: TeamThread["state"] }) {
  const t = useT();
  return <span data-testid="team-thread-state" className={cn(
    "flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-xs",
    state === "done" ? "border-success/40 text-success"
      : state === "needs_input" || state === "paused" ? "border-warning/40 text-warning"
        : state === "failed" ? "border-destructive/40 text-destructive"
          : state === "running" ? "border-accent/40 text-accent" : "border-border text-muted-foreground",
  )}>
    {state === "running" && <Loader2 aria-hidden className="h-3 w-3 animate-spin" />}
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

/** The five steps as one line: done, now, still to come. */
function StepRail({ thread }: { thread: TeamThread }) {
  const t = useT();
  const done = stepsDone(thread);
  const active = thread.state === "running";
  return <ol className="flex min-w-0 flex-1 items-center" aria-label={t("team_threads.steps")}>
    {TEAM_THREAD_PHASES.slice(0, 5).map((phase, index) => {
      const isDone = index < done;
      const now = index === done;
      return <li key={phase} aria-current={now ? "step" : undefined} className="flex min-w-0 flex-1 items-center last:flex-none">
        <span className={cn(
          "flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-[10px] font-medium tabular-nums",
          isDone ? "border-success bg-success text-background"
            : now ? "border-accent text-accent" : "border-border text-muted-foreground",
          now && active && "team-step-now",
        )}>
          {isDone ? <Check aria-hidden className="h-3 w-3" strokeWidth={3} /> : index + 1}
        </span>
        <span className={cn("ml-1.5 truncate text-xs", isDone || now ? "text-foreground" : "text-muted-foreground", now && "font-medium")}>
          {t(`team_threads.phase.${phase}`)}
        </span>
        {index < 4 && <span aria-hidden className={cn("mx-2 h-px min-w-3 flex-1", isDone ? "bg-success" : "bg-border")} />}
      </li>;
    })}
  </ol>;
}

/** Time and turns against their bounds, as two thin bars with their numbers. */
function Meters({ thread }: { thread: TeamThread }) {
  const t = useT();
  const minutes = Math.floor(thread.usage.elapsed_ms / 60_000);
  const meter = (value: number, max: number, label: string) => {
    const share = max > 0 ? Math.min(1, value / max) : 0;
    return <span className="flex items-center gap-1.5">
      <span aria-hidden className="h-1 w-14 overflow-hidden rounded-full bg-secondary">
        <span className={cn("block h-full rounded-full", share >= 0.9 ? "bg-warning" : "bg-foreground/50")} style={{ width: `${Math.max(share * 100, value > 0 ? 6 : 0)}%` }} />
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

/* ------------------------------------------------------------------- lanes */

function LaneHead({ member, agent, builder, over, onOpen }: { member: TeamMember; agent: string; builder: boolean; over: boolean; onOpen: () => void }) {
  const t = useT();
  const left = member.state === "left";
  const status = left ? t("team_threads.member.left")
    : member.waiting ? t("team_threads.member.waiting")
      : member.working ? t("team_threads.member.working")
        : over ? "" : t("team_threads.member.idle");
  return <li className="min-w-0">
    <button type="button" onClick={onOpen} data-testid={`team-member-${member.member_id}`}
      aria-label={fill(t("team_threads.open_member"), { member: member.name })}
      title={left ? member.left_reason : fill(t("team_threads.open_member"), { member: member.name })}
      className={cn(
        "group flex w-full min-w-0 items-center gap-2.5 rounded-xl border px-3 py-2 text-left transition-colors hover:bg-secondary/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        member.working && !left ? "border-accent/50 bg-accent/5" : "border-border bg-card",
        left && "opacity-55",
      )}>
      <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-secondary">
        {agent ? <AgentMark agent={agent} label={member.name} variant="plain" size="sm" /> : <Users aria-hidden className="h-4 w-4 text-muted-foreground" />}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-1.5">
          <span className={cn("truncate text-sm font-medium text-foreground", left && "line-through")}>{member.name}</span>
          {builder && !left && <Hammer aria-label={t("team_threads.member.builder")} className="h-3 w-3 shrink-0 text-muted-foreground" />}
        </span>
        <span className={cn("flex items-center gap-1.5 truncate text-xs",
          member.waiting ? "text-warning" : member.working && !left ? "text-accent" : "text-muted-foreground")}>
          {member.waiting ? <ShieldAlert aria-hidden className="h-3 w-3 shrink-0" />
            : member.working && !left ? <span aria-hidden className="team-pulse h-1.5 w-1.5 shrink-0 rounded-full bg-accent" /> : null}
          <span className="truncate">{[status, member.model].filter(Boolean).join(" · ")}</span>
        </span>
      </span>
    </button>
  </li>;
}

/* ------------------------------------------------------------------- bands */

function Band({ band, names, onOpen }: { band: StepBand; names: Map<string, string>; onOpen: () => void }) {
  const t = useT();
  // The contribution whose whole text is open under this band.
  const [reading, setReading] = useState<number | null>(null);
  const entries = band.cells.flatMap((cell) => cell.entries);
  const open = entries.find((entry) => entry.seq === reading) ?? null;
  const filed = band.cells.filter((cell) => cell.entries.length > 0).length;
  const part = band.cells.filter((cell) => cell.role !== "none" || cell.entries.length > 0).length;
  return <section className="flex flex-col gap-2" data-testid={`team-band-${band.key}`} aria-label={t(`team_threads.phase.${band.step}`)}>
    <header className="flex items-center gap-2 text-xs">
      <span className={cn("font-medium uppercase tracking-wide", band.current ? "text-foreground" : "text-muted-foreground")}>
        {t(`team_threads.phase.${band.step}`)}
      </span>
      {band.round > 1 && <span className="rounded-full border border-border px-1.5 py-px text-muted-foreground">{fill(t("team_threads.round"), { round: band.round })}</span>}
      <span aria-hidden className="h-px flex-1 bg-border" />
      <span className="tabular-nums text-muted-foreground">{fill(t("team_threads.band_count"), { done: filed, total: part })}</span>
    </header>
    <div className="grid items-start gap-3" style={lanes(band.cells.length)}>
      {band.cells.map((cell) => <Cell key={cell.member.member_id} cell={cell} band={band} reading={reading}
        onRead={(seq) => {
          // The person wants to read here: the board stops following its newest entry.
          if (reading !== seq) onOpen();
          setReading(reading === seq ? null : seq);
        }} />)}
    </div>
    {open && <Reader entry={open} name={names.get(open.author) ?? open.author} onClose={() => setReading(null)} />}
  </section>;
}

function Cell({ cell, band, reading, onRead }: { cell: BandCell; band: StepBand; reading: number | null; onRead: (seq: number) => void }) {
  const t = useT();
  const empty = cell.entries.length === 0 && !cell.live;
  return <div className="flex min-w-0 flex-col gap-2" data-testid={`team-cell-${band.key}-${cell.member.member_id}`}>
    {cell.entries.map((entry) => <EntryCard key={entry.seq} entry={entry} open={reading === entry.seq} onRead={() => onRead(entry.seq)} />)}
    {cell.live && <LiveCard member={cell.member} />}
    {empty && band.current && cell.role !== "none" && <p className="rounded-xl border border-dashed border-border px-3 py-2.5 text-xs text-muted-foreground">
      {t(`team_threads.role.${cell.role}`)}
    </p>}
  </div>;
}

/** A filed contribution at a glance: what it is, how it ended, its first lines. */
function EntryCard({ entry, open, onRead }: { entry: TeamEntry; open: boolean; onRead: () => void }) {
  const t = useT();
  const payload = entry.payload;
  const verdict = entry.kind === "vote"
    ? t(payload.agree ? "team_threads.vote.agree" : "team_threads.vote.object")
    : entry.kind === "review" ? t(payload.approve ? "team_threads.review.approve" : "team_threads.review.changes") : "";
  const positive = entry.kind === "vote" ? payload.agree : entry.kind === "review" ? payload.approve : undefined;
  const points = entry.kind === "vote" ? payload.objections ?? [] : [];
  const findings = payload.findings ?? [];
  const files = payload.files ?? [];
  const lead = points[0] ?? findings.find((finding) => finding.severity === "blocking")?.issue ?? findings[0]?.issue ?? "";
  return <button type="button" onClick={onRead} aria-expanded={open} data-testid={`team-entry-${entry.kind}`}
    className={cn(
      "flex w-full min-w-0 flex-col gap-1.5 rounded-xl border bg-card px-3 py-2.5 text-left transition-colors hover:border-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
      open ? "border-border-strong" : "border-border",
    )}>
    <span className="flex items-center gap-1.5 text-xs">
      <span className="font-medium text-foreground">{t(`team_threads.kind.${entry.kind}`)}</span>
      {verdict && <span className={cn("rounded-full border px-1.5 py-px",
        positive ? "border-success/40 text-success" : "border-warning/40 text-warning")}>{verdict}</span>}
      <span className="ml-auto text-muted-foreground">
        {open ? <ChevronDown aria-hidden className="h-3.5 w-3.5" /> : <ChevronRight aria-hidden className="h-3.5 w-3.5" />}
      </span>
    </span>
    {lead
      ? <span className="line-clamp-3 text-xs text-foreground [overflow-wrap:anywhere]">{lead}</span>
      : <span className="line-clamp-4 text-xs leading-relaxed text-muted-foreground [overflow-wrap:anywhere]">{gist(payload.text ?? "") || t("team_threads.no_report")}</span>}
    {(files.length > 0 || findings.length > 1 || points.length > 1) && <span className="flex flex-wrap gap-x-3 text-[11px] text-muted-foreground">
      {files.length > 0 && <span title={payload.stat}>{fill(t("team_threads.files_changed"), { count: files.length })}</span>}
      {findings.length > 1 && <span>{fill(t("team_threads.findings_count"), { count: findings.length })}</span>}
      {points.length > 1 && <span>{fill(t("team_threads.objections_count"), { count: points.length })}</span>}
    </span>}
  </button>;
}

/** The whole contribution, opened under its band: nothing to navigate to. */
function Reader({ entry, name, onClose }: { entry: TeamEntry; name: string; onClose: () => void }) {
  const t = useT();
  const payload = entry.payload;
  const points = entry.kind === "vote" ? payload.objections ?? [] : [];
  const box = useRef<HTMLElement | null>(null);
  // Reading starts at the top: the board follows its newest entry, and a long
  // text opened at the end of the page would otherwise show its last lines.
  useEffect(() => {
    box.current?.scrollIntoView?.({ block: "start" });
  }, [entry.seq]);
  return <article ref={box} className="scroll-mt-20 rounded-xl border border-border-strong bg-card" data-testid="team-reader">
    <header className="flex items-center gap-2 border-b border-border px-4 py-2 text-xs">
      <span className="font-medium text-foreground">{name}</span>
      <span className="text-muted-foreground">{t(`team_threads.kind.${entry.kind}`)}</span>
      <button type="button" onClick={onClose} aria-label={t("team_threads.close_reader")} title={t("team_threads.close_reader")}
        className="ml-auto rounded-md p-1 text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <X className="h-3.5 w-3.5" />
      </button>
    </header>
    <div className="mx-auto max-w-3xl px-4 py-3">
      {payload.text ? <ChatMarkdown text={payload.text} /> : <p className="text-sm text-muted-foreground">{t("team_threads.no_report")}</p>}
      {points.length > 0 && <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-foreground">
        {points.map((point, index) => <li key={index}>{point}</li>)}
      </ul>}
      {(payload.findings ?? []).length > 0 && <ul className="mt-3 flex flex-col gap-1.5">
        {(payload.findings ?? []).map((finding, index) => <FindingRow key={index} finding={finding} />)}
      </ul>}
      {(payload.files ?? []).length > 0 && <p className="mt-3 font-mono text-xs text-muted-foreground [overflow-wrap:anywhere]">
        {(payload.files ?? []).join("  ·  ")}
      </p>}
    </div>
  </article>;
}

/* -------------------------------------------------------------------- live */

const CALL_GLYPH: Record<string, typeof Terminal> = {
  command: Terminal, read: FileText, list: FolderOpen, search: Search, edit: Pencil, write: Pencil, web: Globe,
};

function useSeconds(sinceMs: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return sinceMs > 0 ? Math.max(0, Math.floor((now - sinceMs) / 1000)) : 0;
}

const clock = (seconds: number) => `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;

/** A member at work: its newest steps as they happen, in a few lines. */
function LiveCard({ member }: { member: TeamMember }) {
  const t = useT();
  const turn = useMemberTurn(member.session_id, true);
  const seconds = useSeconds(member.since_ms);
  const lang = t("trace_report.locale");
  const lines = useMemo(() => liveLines(turn, { t, lang, max: 6 }), [turn, t, lang]);
  const tokens = liveTokens(turn);
  return <div role="status" data-testid={`team-live-${member.member_id}`}
    className={cn("team-live flex min-w-0 flex-col gap-1.5 overflow-hidden rounded-xl border bg-card px-3 py-2.5",
      member.waiting ? "border-warning/50" : "border-accent/50")}>
    <div className="flex items-center gap-1.5 text-xs">
      {member.waiting
        ? <><ShieldAlert aria-hidden className="h-3.5 w-3.5 text-warning" /><span className="font-medium text-warning">{t("team_threads.member.waiting")}</span></>
        : <><span aria-hidden className="team-pulse h-1.5 w-1.5 rounded-full bg-accent" /><span className="font-medium text-accent">{t("team_threads.member.working")}</span></>}
      <span className="ml-auto tabular-nums text-muted-foreground">
        {tokens > 0 ? `${fill(t("team_threads.live_tokens"), { count: tokens.toLocaleString() })} · ` : ""}{clock(seconds)}
      </span>
    </div>
    {lines.length === 0
      ? <p className="text-xs text-muted-foreground">{t("team_threads.live_starting")}</p>
      : <ol className="flex flex-col gap-1">
        {lines.map((line, index) => <LiveRow key={line.id} line={line} newest={index === lines.length - 1} />)}
      </ol>}
  </div>;
}

function LiveRow({ line, newest }: { line: LiveLine; newest: boolean }) {
  const t = useT();
  const Glyph = line.kind === "call" ? CALL_GLYPH[line.call ?? ""] ?? Wrench : line.kind === "thought" ? Brain : MessageSquareText;
  return <li className={cn("team-live-line flex min-w-0 items-start gap-1.5 text-xs", newest ? "text-foreground" : "text-muted-foreground")}>
    {line.running && line.kind === "call"
      ? <Loader2 aria-hidden className="mt-0.5 h-3 w-3 shrink-0 animate-spin" />
      : <Glyph aria-hidden className={cn("mt-0.5 h-3 w-3 shrink-0", line.failed && "text-destructive")} />}
    <span className={cn("min-w-0 [overflow-wrap:anywhere]", line.kind === "call" ? "truncate font-mono text-[11px]" : "line-clamp-2")}>
      {line.text || t("team_threads.live_thinking")}
    </span>
  </li>;
}

/* ------------------------------------------------------------------- notes */

/** What belongs to nobody's lane: the person's words, a notice, the outcome. */
function Note({ entry, names }: { entry: TeamEntry; names: Map<string, string> }) {
  const t = useT();
  const payload = entry.payload;
  if (entry.kind === "user") {
    return <div className="jarvis-chat-tinted jarvis-chat-out max-w-[min(85%,46rem)] self-end whitespace-pre-wrap rounded-[20px] px-4 py-2.5 text-sm [overflow-wrap:anywhere]"
      data-testid="team-entry-user">{payload.text}</div>;
  }
  if (entry.kind === "summary") return <Summary entry={entry} names={names} />;
  const code = payload.code ?? "";
  return <p className="self-center px-2 text-center text-xs text-muted-foreground" data-testid={`team-notice-${code}`}>
    {fill(t(`team_threads.notice.${code}`), {
      member: names.get(payload.member_id ?? payload.by ?? "") ?? "",
      error: payload.error ?? "", note: payload.note ?? "", rounds: payload.rounds ?? 0,
      step: payload.step ? t(`team_threads.kind.${payload.step}`) : "",
      files: (payload.files ?? []).join(", "), model: payload.model ?? "",
    })}
  </p>;
}

function FindingRow({ finding, by, resolved }: { finding: TeamFinding; by?: string; resolved?: boolean }) {
  const t = useT();
  return <li className="rounded-lg border border-border px-3 py-2 text-sm">
    <div className="flex flex-wrap items-center gap-1.5 text-xs">
      <span className={cn("rounded-full border px-1.5 py-px",
        finding.severity === "blocking" ? "border-destructive/40 text-destructive" : "border-border text-muted-foreground")}>
        {t(`team_threads.severity.${finding.severity}`)}
      </span>
      {by && <span className="font-medium text-foreground">{by}</span>}
      {finding.where && <code className="font-mono text-muted-foreground [overflow-wrap:anywhere]">{finding.where}</code>}
      {resolved !== undefined && <span className={cn("ml-auto", resolved ? "text-success" : "text-warning")}>
        {t(resolved ? "team_threads.issues.resolved" : "team_threads.issues.open")}
      </span>}
    </div>
    <p className="mt-1 text-foreground [overflow-wrap:anywhere]">{finding.issue}</p>
    {finding.fix && <p className="mt-0.5 text-xs text-muted-foreground [overflow-wrap:anywhere]">{finding.fix}</p>}
  </li>;
}

function Summary({ entry, names }: { entry: TeamEntry; names: Map<string, string> }) {
  const t = useT();
  const payload = entry.payload;
  const outcome = payload.outcome ?? "done";
  const finished = outcome === "done" || outcome === "accepted_by_user";
  return <section data-testid={`team-summary-${outcome}`}
    className={cn("rounded-xl border px-4 py-3 text-sm", finished ? "border-success/40 bg-success/10" : "border-warning/40 bg-warning/10")}>
    <p className="font-medium text-foreground">
      {finished
        ? fill(t(`team_threads.summary.${outcome}`), {
          plan: payload.plan_rounds ?? 1, review: payload.review_rounds ?? 1,
          count: payload.finding_count ?? 0, blocking: payload.blocking ?? 0,
          builder: names.get(payload.builder ?? "") ?? "",
        })
        : fill(t(`team_threads.reason.${outcome}`), { rounds: payload.rounds ?? 0, note: "" })}
    </p>
    {finished && (payload.files ?? []).length > 0 && <p className="mt-1 text-xs text-muted-foreground" title={payload.stat}>
      {fill(t("team_threads.files_changed"), { count: (payload.files ?? []).length })}
    </p>}
    {(payload.open ?? []).length > 0 && <div className="mt-2 flex flex-col gap-2">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{t("team_threads.summary.open_points")}</p>
      {(payload.open ?? []).map((point) => <div key={point.member_id}>
        <p className="text-xs font-medium text-foreground">{point.name}</p>
        <ul className="list-disc space-y-0.5 pl-5 text-foreground">
          {point.items.map((item, index) => <li key={index} className="[overflow-wrap:anywhere]">{item}</li>)}
        </ul>
      </div>)}
    </div>}
  </section>;
}

/** The record of what the members caught in each other's plan and work. */
function Issues({ thread, names }: { thread: TeamThread; names: Map<string, string> }) {
  const t = useT();
  const [open, setOpen] = useState(true);
  const unresolved = thread.issues.filter((issue) => !issue.resolved).length;
  return <section className="mt-1 flex flex-col gap-2" data-testid="team-thread-issues">
    <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}
      className="flex items-center gap-1.5 self-start rounded-md px-1 text-xs font-medium text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      {open ? <ChevronDown aria-hidden className="h-3.5 w-3.5 text-muted-foreground" /> : <ChevronRight aria-hidden className="h-3.5 w-3.5 text-muted-foreground" />}
      {fill(t("team_threads.issues.title"), { count: thread.issues.length, open: unresolved })}
    </button>
    {open && <ul className="grid gap-1.5 md:grid-cols-2">
      {thread.issues.map((issue, index) => <FindingRow key={`${issue.seq}-${index}`} finding={issue} resolved={issue.resolved}
        by={`${names.get(issue.by) ?? issue.by} · ${t(`team_threads.issues.${issue.stage}`)}`} />)}
    </ul>}
  </section>;
}
