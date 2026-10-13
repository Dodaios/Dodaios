import { useLayoutEffect, useMemo, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Check, ChevronDown, ChevronRight, Hammer, Loader2, Pause, Play, Send, ShieldAlert, Square, Trash2, Users, X } from "lucide-react";
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
import { TeamThreadDraft } from "./TeamThreadDraft";

/** The reading width of the shared thread, the same as a single thread's. */
const MEASURE = "mx-auto w-full max-w-3xl";

/** Contributions that open folded: long, and superseded by the master plan. */
const FOLDED_KINDS = new Set(["draft", "critique"]);

/**
 * One team thread: the task, every member's contributions in the order of
 * work, where they disagreed and how it ended, and the controls to step in.
 *
 * The models never read this page. A coordinator on the server passes
 * contributions between them; this view only shows what it filed.
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
  const { rootRef, contentRef, atEnd, jumpToEnd, follow } = useStickToBottom();
  useLayoutEffect(follow, [follow, thread?.entries.length, thread?.state]);

  const names = useMemo(
    () => new Map((thread?.members ?? []).map((member) => [member.member_id, member.name])),
    [thread?.members],
  );
  const agentOf = useMemo(
    () => new Map((seats?.seats ?? []).map((seat) => [seat.provider, seat.agent])),
    [seats],
  );

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
  const phaseIndex = TEAM_THREAD_PHASES.indexOf(thread.phase);
  const minutes = Math.floor(thread.usage.elapsed_ms / 60_000);

  return <div className="flex h-full min-h-0 flex-col" data-testid="team-thread-view">
    <header className="shrink-0 border-b border-border px-5 py-3">
      <div className={cn(MEASURE, "flex flex-col gap-2")}>
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
        <ol className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs" aria-label={t("team_threads.steps")}>
          {TEAM_THREAD_PHASES.slice(0, 5).map((phase, index) => {
            const done = index < phaseIndex;
            const now = index === phaseIndex && !over;
            return <li key={phase} aria-current={now ? "step" : undefined}
              className={cn("flex items-center gap-1 rounded-full border px-2 py-0.5",
                now ? "border-border-strong bg-secondary text-foreground"
                  : done ? "border-transparent text-foreground" : "border-transparent text-muted-foreground")}>
              {done && <Check aria-hidden className="h-3 w-3 text-success" />}
              {t(`team_threads.phase.${phase}`)}
            </li>;
          })}
          <li className="ml-auto tabular-nums text-muted-foreground" data-testid="team-thread-usage"
            title={thread.usage.cost_usd > 0
              ? `${t("team_threads.cost_hint")}${thread.usage.cost_partial ? ` ${t("team_threads.cost_partial")}` : ""}`
              : undefined}>
            {fill(t("team_threads.usage"), {
              minutes, max_minutes: thread.limits.max_minutes,
              turns: thread.usage.turns, max_turns: thread.limits.max_turns,
            })}
            {thread.usage.cost_usd > 0 && ` · ≈ $${thread.usage.cost_usd.toFixed(2)}`}
          </li>
        </ol>
        <ul className="flex flex-wrap gap-1.5" aria-label={t("team_threads.members")}>
          {thread.members.map((member) => <MemberChip key={member.member_id} member={member}
            agent={agentOf.get(member.provider) ?? ""} builder={thread.builder === member.member_id}
            onOpen={() => useIdeThreadsStore.getState().openThread(member.session_id, project.id)} />)}
        </ul>
      </div>
    </header>

    <div className="relative flex min-h-0 flex-1 flex-col">
      <div ref={rootRef} className="chat-scroller min-h-0 flex-1 overflow-y-auto px-5 py-5" role="log" aria-label={thread.title}>
        <div ref={contentRef} className={cn(MEASURE, "flex flex-col gap-3")}>
          {thread.entries.map((entry) => {
            const latestPlan = entry.kind === "plan" && !thread.entries.some((other) => other.kind === "plan" && other.seq > entry.seq);
            // Keyed by it too: a plan that a newer one replaced folds by itself.
            return <Entry key={`${entry.seq}:${latestPlan}`} entry={entry} names={names} latestPlan={latestPlan} />;
          })}
          {thread.issues.length > 0 && <Issues thread={thread} names={names} />}
        </div>
      </div>
      {!atEnd && <ScrollToEndButton onClick={jumpToEnd} testId="team-thread-scroll-end" className="top-auto bottom-3" />}
    </div>

    <footer className="shrink-0 px-5 pb-4 pt-2">
      <div className={cn(MEASURE, "flex flex-col gap-2")}>
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

function StateBadge({ state }: { state: TeamThread["state"] }) {
  const t = useT();
  return <span data-testid="team-thread-state" className={cn(
    "flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-xs",
    state === "done" ? "border-success/40 text-success"
      : state === "needs_input" || state === "paused" ? "border-warning/40 text-warning"
        : state === "failed" ? "border-destructive/40 text-destructive" : "border-border text-muted-foreground",
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

function MemberChip({ member, agent, builder, onOpen }: { member: TeamMember; agent: string; builder: boolean; onOpen: () => void }) {
  const t = useT();
  const left = member.state === "left";
  const status = left ? t("team_threads.member.left")
    : member.waiting ? t("team_threads.member.waiting")
      : member.working ? t("team_threads.member.working") : "";
  return <li>
    <button type="button" onClick={onOpen} data-testid={`team-member-${member.member_id}`}
      aria-label={fill(t("team_threads.open_member"), { member: member.name })}
      title={left ? member.left_reason : fill(t("team_threads.open_member"), { member: member.name })}
      className={cn(
        "flex items-center gap-1.5 rounded-full border border-border px-2 py-0.5 text-xs hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        left ? "text-muted-foreground line-through" : "text-foreground",
      )}>
      {agent ? <AgentMark agent={agent} label={member.name} variant="plain" size="sm" /> : null}
      <span className="max-w-[16ch] truncate">{member.name}</span>
      {builder && !left && <Hammer aria-label={t("team_threads.member.builder")} className="h-3 w-3 text-muted-foreground" />}
      {member.waiting ? <ShieldAlert aria-hidden className="h-3 w-3 text-warning" />
        : member.working ? <Loader2 aria-hidden className="h-3 w-3 animate-spin text-muted-foreground" /> : null}
      {status && <span className="text-muted-foreground no-underline">{status}</span>}
    </button>
  </li>;
}

function Entry({ entry, names, latestPlan }: { entry: TeamEntry; names: Map<string, string>; latestPlan: boolean }) {
  const t = useT();
  const name = names.get(entry.author) ?? entry.author;
  const payload = entry.payload;
  const [open, setOpen] = useState(!FOLDED_KINDS.has(entry.kind) && (entry.kind !== "plan" || latestPlan));

  if (entry.kind === "user") {
    return <div className="jarvis-chat-tinted jarvis-chat-out max-w-[min(85%,42rem)] self-end whitespace-pre-wrap rounded-[20px] px-4 py-2.5 text-sm [overflow-wrap:anywhere]"
      data-testid="team-entry-user">{payload.text}</div>;
  }
  if (entry.kind === "notice") {
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
  if (entry.kind === "summary") return <Summary entry={entry} names={names} />;

  const verdict = entry.kind === "vote"
    ? t(payload.agree ? "team_threads.vote.agree" : "team_threads.vote.object")
    : entry.kind === "review" ? t(payload.approve ? "team_threads.review.approve" : "team_threads.review.changes") : "";
  const positive = entry.kind === "vote" ? payload.agree : entry.kind === "review" ? payload.approve : undefined;
  const round = entry.round > 1 ? ` · ${fill(t("team_threads.round"), { round: entry.round })}` : "";
  const points = entry.kind === "vote" ? payload.objections ?? [] : [];
  return <article className="flex min-w-0 flex-col gap-1.5 self-stretch" data-testid={`team-entry-${entry.kind}`}>
    <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}
      className="flex items-center gap-1.5 self-start rounded-md px-1 text-left text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      {open ? <ChevronDown aria-hidden className="h-3.5 w-3.5 text-muted-foreground" /> : <ChevronRight aria-hidden className="h-3.5 w-3.5 text-muted-foreground" />}
      <span className="font-medium text-foreground">{name}</span>
      <span className="text-muted-foreground">{t(`team_threads.kind.${entry.kind}`)}{round}</span>
      {verdict && <span className={cn("rounded-full border px-1.5 py-px",
        positive ? "border-success/40 text-success" : "border-warning/40 text-warning")}>{verdict}</span>}
    </button>
    {open && <div className="jarvis-chat-in min-w-0 rounded-[20px] px-4 py-2.5">
      {payload.text ? <ChatMarkdown text={payload.text} /> : null}
      {points.length > 0 && <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-foreground">
        {points.map((point, index) => <li key={index}>{point}</li>)}
      </ul>}
      {(payload.findings ?? []).length > 0 && <ul className="mt-2 flex flex-col gap-1.5">
        {(payload.findings ?? []).map((finding, index) => <FindingRow key={index} finding={finding} />)}
      </ul>}
      {(payload.files ?? []).length > 0 && <p className="mt-2 text-xs text-muted-foreground" title={payload.stat}>
        {fill(t("team_threads.files_changed"), { count: (payload.files ?? []).length })}
      </p>}
    </div>}
  </article>;
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
  return <section className="mt-2 flex flex-col gap-2" data-testid="team-thread-issues">
    <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}
      className="flex items-center gap-1.5 self-start rounded-md px-1 text-xs font-medium text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      {open ? <ChevronDown aria-hidden className="h-3.5 w-3.5 text-muted-foreground" /> : <ChevronRight aria-hidden className="h-3.5 w-3.5 text-muted-foreground" />}
      {fill(t("team_threads.issues.title"), { count: thread.issues.length, open: unresolved })}
    </button>
    {open && <ul className="flex flex-col gap-1.5">
      {thread.issues.map((issue, index) => <FindingRow key={`${issue.seq}-${index}`} finding={issue} resolved={issue.resolved}
        by={`${names.get(issue.by) ?? issue.by} · ${t(`team_threads.issues.${issue.stage}`)}`} />)}
    </ul>}
  </section>;
}
