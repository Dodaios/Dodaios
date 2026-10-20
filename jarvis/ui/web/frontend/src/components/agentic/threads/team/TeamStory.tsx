import { useLayoutEffect, useMemo, useState } from "react";
import { ChevronRight, ShieldAlert } from "lucide-react";
import { AgentMark } from "@/components/agentic/AgentMark";
import { ChatMarkdown } from "@/components/agentchat/ChatMarkdown";
import { ScrollToEndButton } from "@/components/ui/scroll-to-end-button";
import { useStickToBottom } from "@/hooks/useStickToBottom";
import { fill, useT } from "@/i18n";
import type { TeamEntry, TeamFinding, TeamMember, TeamThread } from "@/lib/teamThreadsApi";
import { cn } from "@/lib/utils";
import { buildBoard, gist, type StepBand } from "./board";
import { clock, useMemberStatus } from "./memberLive";
import { PROSE_COMPACT } from "./roomStyle";
import type { TeamGraph } from "./teamGraph";

/**
 * The team's shared story: who contributed what, step by step, as one quiet
 * list. A step opens with a small heading; each contribution is one line with
 * its author, what it is, its verdict and to whom it went, plus a two-line
 * gist; a click unfolds the whole text in place. The person's words, notices
 * and the outcome sit where they happened. What the members caught in each
 * other's work closes the list.
 */

export interface RoomNames {
  name: (id: string) => string;
  agent: (member: TeamMember) => string;
  member: (id: string) => TeamMember | undefined;
}

/** The heading of a step in the story: "Master plan · round 2", "Step 3 · Add the setting". */
function stepHeading(band: StepBand, t: (key: string) => string): string {
  if (band.step === "step") return [fill(t("team_threads.plan.step"), { number: band.number ?? 0 }), band.title].filter(Boolean).join(" · ");
  const name = t(`team_threads.phase.${band.step}`);
  return band.round > 1 && band.step !== "planning" ? `${name} · ${fill(t("team_threads.round"), { round: band.round })}` : name;
}

export function verdictOf(entry: TeamEntry, t: (key: string) => string): { text: string; tone: "positive" | "negative" } | null {
  const payload = entry.payload;
  if (entry.kind === "vote" || entry.kind === "plan_review") {
    return { text: t(payload.agree ? "team_threads.vote.agree" : "team_threads.vote.object"), tone: payload.agree ? "positive" : "negative" };
  }
  if (entry.kind === "review" || entry.kind === "step_review") {
    return { text: t(payload.approve ? "team_threads.review.approve" : "team_threads.review.changes"), tone: payload.approve ? "positive" : "negative" };
  }
  if (entry.kind === "plan_version" && payload.valid === false) return { text: t("team_threads.plan.unreadable"), tone: "negative" };
  if (entry.kind === "step_build") {
    const blocked = payload.status === "blocked";
    return { text: t(blocked ? "team_threads.plan.blocked" : "team_threads.plan.done"), tone: blocked ? "negative" : "positive" };
  }
  return null;
}

/** What a contribution is called: "Own plan", "Plan v2", "Step 3". */
export function kindLabel(entry: TeamEntry, t: (key: string) => string): string {
  if (entry.kind === "plan_version" && entry.payload.valid !== false) return fill(t("team_threads.plan.title"), { version: entry.payload.version ?? 1 });
  if ((entry.kind === "step_build" || entry.kind === "step_review") && entry.payload.number) {
    return `${t(`team_threads.kind.${entry.kind}`)} ${entry.payload.number}`;
  }
  return t(`team_threads.kind.${entry.kind}`);
}

/** The first thing worth reading of a contribution, in one or two lines. */
export function leadOf(entry: TeamEntry, t: (key: string) => string): string {
  const payload = entry.payload;
  const objection = (payload.objections ?? [])[0];
  const finding = (payload.findings ?? []).find((item) => item.severity === "blocking") ?? (payload.findings ?? [])[0];
  if (objection) return objection;
  if (finding) return [finding.where, finding.issue].filter(Boolean).join(": ");
  if (entry.kind === "plan_version" && payload.valid === false) return payload.error ?? "";
  if (entry.kind === "step_build" && payload.status === "blocked" && payload.note) return payload.note;
  return gist(payload.text ?? "", 220) || t("team_threads.no_report");
}

/** The whole of one contribution: its text, plan steps, objections, findings, files. */
export function EntryBody({ entry }: { entry: TeamEntry }) {
  const t = useT();
  const payload = entry.payload;
  const points = entry.kind === "vote" || entry.kind === "plan_review" ? payload.objections ?? [] : [];
  return <div className="min-w-0" data-testid="team-entry-body">
    {payload.text ? <div className={PROSE_COMPACT}><ChatMarkdown text={payload.text} /></div>
      : <p className="text-sm text-muted-foreground">{t("team_threads.no_report")}</p>}
    {points.length > 0 && <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-foreground">
      {points.map((point, index) => <li key={index} className="[overflow-wrap:anywhere]">{point}</li>)}
    </ul>}
    {entry.kind === "plan_version" && payload.valid === false && payload.error && <p className="mt-2 text-sm text-warning">{payload.error}</p>}
    {(payload.steps ?? []).length > 0 && <ol className="mt-3 flex flex-col divide-y divide-border border-y border-border" data-testid="team-entry-plan">
      {(payload.steps ?? []).map((step, index) => <li key={index} className="flex gap-3 py-2 text-sm">
        <span className="w-4 shrink-0 text-right font-mono text-xs leading-5 text-muted-foreground">{index + 1}</span>
        <span className="min-w-0">
          <span className="block font-medium text-foreground">{step.title}</span>
          {step.goal && <span className="block text-foreground/80 [overflow-wrap:anywhere]">{step.goal}</span>}
          <span className="block text-xs text-muted-foreground [overflow-wrap:anywhere]">{t("team_threads.plan.done_when")}: {step.done_when}</span>
        </span>
      </li>)}
    </ol>}
    {entry.kind === "step_build" && (payload.note || payload.plan_change) && <p className="mt-3 text-sm text-foreground [overflow-wrap:anywhere]">
      {[payload.note, payload.plan_change && fill(t("team_threads.plan.plan_change"), { text: payload.plan_change })].filter(Boolean).join(" · ")}
    </p>}
    {(payload.findings ?? []).length > 0 && <ul className="mt-3 flex flex-col gap-1">
      {(payload.findings ?? []).map((finding, index) => <FindingRow key={index} finding={finding} />)}
    </ul>}
    {(payload.files ?? []).length > 0 && <p className="mt-3 font-mono text-xs leading-5 text-muted-foreground [overflow-wrap:anywhere]" title={payload.stat}>
      {(payload.files ?? []).join("  ·  ")}
    </p>}
  </div>;
}

export function FindingRow({ finding, by, resolved }: { finding: TeamFinding; by?: string; resolved?: boolean }) {
  const t = useT();
  const blocking = finding.severity === "blocking";
  return <li className={cn("border-l-[3px] py-1 pl-3 text-sm", blocking ? "border-destructive" : "border-border-strong")}
    data-severity={finding.severity}>
    <div className="flex flex-wrap items-baseline gap-x-2 text-xs">
      <span className={cn("font-medium", blocking ? "text-destructive" : "text-muted-foreground")}>{t(`team_threads.severity.${finding.severity}`)}</span>
      {by && <span className="text-foreground">{by}</span>}
      {finding.where && <code className="font-mono text-muted-foreground [overflow-wrap:anywhere]">{finding.where}</code>}
      {resolved !== undefined && <span className={cn("ml-auto", resolved ? "text-success" : "text-warning")}>
        {t(resolved ? "team_threads.issues.resolved" : "team_threads.issues.open")}
      </span>}
    </div>
    <p className="mt-0.5 text-foreground [overflow-wrap:anywhere]">{finding.issue}</p>
    {finding.fix && <p className="text-xs text-muted-foreground [overflow-wrap:anywhere]">{finding.fix}</p>}
  </li>;
}

function Mark({ member, names }: { member: TeamMember | undefined; names: RoomNames }) {
  const agent = member ? names.agent(member) : "";
  return <span className="grid h-5 w-5 shrink-0 place-items-center rounded bg-secondary">
    {agent && member ? <AgentMark agent={agent} label={member.name} variant="plain" size="sm" /> : null}
  </span>;
}

/** One contribution as a line; a click unfolds it in place. */
function StoryEntry({ entry, names, to, open, onToggle }: {
  entry: TeamEntry; names: RoomNames; to: string[]; open: boolean; onToggle: () => void;
}) {
  const t = useT();
  const verdict = verdictOf(entry, t);
  const member = names.member(entry.author);
  return <li className="min-w-0" data-testid={`team-story-${entry.kind}`} data-seq={entry.seq}>
    <button type="button" onClick={onToggle} aria-expanded={open}
      className="group flex w-full min-w-0 gap-2.5 rounded-md px-2 py-1.5 text-left hover:bg-secondary/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      <Mark member={member} names={names} />
      <span className="min-w-0 flex-1">
        <span className="flex min-w-0 flex-wrap items-baseline gap-x-1.5 text-sm">
          <span className="font-medium text-foreground">{names.name(entry.author)}</span>
          <span className="text-muted-foreground">{kindLabel(entry, t)}</span>
          {verdict && <span className={cn("text-xs font-medium", verdict.tone === "positive" ? "text-success" : "text-warning")}>{verdict.text}</span>}
          {to.length > 0 && <span className="min-w-0 truncate text-xs text-muted-foreground">→ {to.join(", ")}</span>}
          <span className="ml-auto shrink-0 pl-2 text-xs tabular-nums text-muted-foreground">{time(entry.ts_ms)}</span>
        </span>
        {!open && <span className="mt-0.5 line-clamp-2 text-[13px] leading-5 text-muted-foreground [overflow-wrap:anywhere]">{leadOf(entry, t)}</span>}
      </span>
      <ChevronRight aria-hidden className={cn("mt-1 h-3.5 w-3.5 shrink-0 text-muted-foreground opacity-0 transition group-hover:opacity-70", open && "rotate-90 opacity-70")} />
    </button>
    {open && <div className="pb-2 pl-[38px] pr-2 pt-1"><EntryBody entry={entry} /></div>}
  </li>;
}

const time = (ms: number) => {
  if (!ms || ms < 1e11) return "";
  const date = new Date(ms);
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
};

function Notice({ entry, names }: { entry: TeamEntry; names: RoomNames }) {
  const t = useT();
  const payload = entry.payload;
  const code = payload.code ?? "";
  return <li className="flex items-center gap-3 px-2 py-1 text-xs text-muted-foreground" data-testid={`team-notice-${code}`}>
    <span aria-hidden className="h-px w-3 shrink-0 bg-border" />
    <span className="min-w-0 [overflow-wrap:anywhere]">
      {fill(t(`team_threads.notice.${code}`), {
        member: names.name(payload.member_id ?? payload.by ?? ""),
        error: payload.error ?? "", note: payload.note ?? "", rounds: payload.rounds ?? 0,
        step: payload.step ? t(`team_threads.kind.${payload.step}`) : "",
        files: (payload.files ?? []).join(", "), model: payload.model ?? "",
        number: payload.number ?? 0, version: payload.version ?? 0, count: payload.count ?? 0, title: payload.title ?? "",
        role: payload.role ? t(`team_threads.member_role.${payload.role}`) : "",
      })}
    </span>
  </li>;
}

export function Summary({ entry, names }: { entry: TeamEntry; names: RoomNames }) {
  const t = useT();
  const payload = entry.payload;
  const outcome = payload.outcome ?? "done";
  const finished = outcome === "done" || outcome === "accepted_by_user";
  return <li data-testid={`team-summary-${outcome}`}
    className={cn("my-2 border-l-[3px] py-1.5 pl-3 pr-2 text-sm", finished ? "border-success" : "border-warning")}>
    <p className="font-medium text-foreground">
      {finished && payload.mode === "planner_builder"
        ? fill(t(outcome === "done" ? "team_threads.summary.planned_done" : "team_threads.summary.planned_accepted"), {
          count: payload.step_count ?? 0, version: payload.version ?? 1, rounds: payload.step_rounds ?? 0,
          findings: payload.finding_count ?? 0, blocking: payload.blocking ?? 0,
        })
        : finished
          ? fill(t(`team_threads.summary.${outcome}`), {
            plan: payload.plan_rounds ?? 1, review: payload.review_rounds ?? 1,
            count: payload.finding_count ?? 0, blocking: payload.blocking ?? 0,
            builder: names.name(payload.builder ?? ""),
          })
          : fill(t(`team_threads.reason.${outcome}`), { rounds: payload.rounds ?? 0, note: "", number: payload.number ?? 0 })}
    </p>
    {finished && (payload.files ?? []).length > 0 && <p className="mt-1 text-xs text-muted-foreground" title={payload.stat}>
      {fill(t("team_threads.files_changed"), { count: (payload.files ?? []).length })}
    </p>}
    {(payload.open ?? []).length > 0 && <div className="mt-2 flex flex-col gap-2">
      <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">{t("team_threads.summary.open_points")}</p>
      {(payload.open ?? []).map((point) => <div key={point.member_id}>
        <p className="text-xs font-medium text-foreground">{point.name}</p>
        <ul className="list-disc space-y-0.5 pl-5 text-foreground">
          {point.items.map((item, index) => <li key={index} className="[overflow-wrap:anywhere]">{item}</li>)}
        </ul>
      </div>)}
    </div>}
  </li>;
}

/** A member at work, as a line under the step it works on. */
function WorkingLine({ member, names, over }: { member: TeamMember; names: RoomNames; over: boolean }) {
  const t = useT();
  const status = useMemberStatus(member, over);
  return <li className="flex min-w-0 items-center gap-2.5 px-2 py-1.5 text-sm" data-testid={`team-story-live-${member.member_id}`} role="status">
    <Mark member={member} names={names} />
    <span className="shrink-0 font-medium text-foreground">{member.name}</span>
    {status.tone === "waiting"
      ? <span className="flex min-w-0 items-center gap-1 text-warning"><ShieldAlert aria-hidden className="h-3.5 w-3.5 shrink-0" />{status.text}</span>
      : <span className="flex min-w-0 items-center gap-1.5 text-muted-foreground">
        <span aria-hidden className="team-pulse h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
        <span className={cn("truncate", status.call && "font-mono text-xs")}>{status.text}</span>
      </span>}
    {status.seconds > 0 && <span className="ml-auto shrink-0 text-xs tabular-nums text-muted-foreground">{clock(status.seconds)}</span>}
    <span className="sr-only">{t("team_threads.member.working")}</span>
  </li>;
}

type Row =
  | { type: "heading"; key: string; text: string; current: boolean }
  | { type: "entry"; key: string; entry: TeamEntry }
  | { type: "user"; key: string; entry: TeamEntry }
  | { type: "notice"; key: string; entry: TeamEntry }
  | { type: "summary"; key: string; entry: TeamEntry }
  | { type: "live"; key: string };

/** The story in reading order, with a heading wherever the step changes. */
export function storyRows(thread: TeamThread, t: (key: string) => string): Row[] {
  const bands = buildBoard(thread).filter((band): band is StepBand => band.type === "step");
  const bandOf = new Map<number, StepBand>();
  for (const band of bands) for (const cell of band.cells) for (const entry of cell.entries) bandOf.set(entry.seq, band);
  const rows: Row[] = [];
  let last: string | null = null;
  for (const entry of thread.entries) {
    const band = bandOf.get(entry.seq);
    if (band) {
      if (band.key !== last) {
        rows.push({ type: "heading", key: `h:${band.key}:${entry.seq}`, text: stepHeading(band, t), current: band.current });
        last = band.key;
      }
      rows.push({ type: "entry", key: `e:${entry.seq}`, entry });
    } else if (entry.kind === "user") rows.push({ type: "user", key: `u:${entry.seq}`, entry });
    else if (entry.kind === "summary") rows.push({ type: "summary", key: `s:${entry.seq}`, entry });
    else rows.push({ type: "notice", key: `n:${entry.seq}`, entry });
  }
  // The step being worked on shows from its first second, before anything is filed in it.
  const current = bands.find((band) => band.current);
  if (current && current.key !== last && thread.state === "running") {
    rows.push({ type: "heading", key: `h:${current.key}:now`, text: stepHeading(current, t), current: true });
  }
  if (thread.state === "running") rows.push({ type: "live", key: "live" });
  return rows;
}

export function TeamStory({ thread, graph, names }: { thread: TeamThread; graph: TeamGraph; names: RoomNames }) {
  const t = useT();
  const [open, setOpen] = useState<Set<number>>(() => new Set());
  const { rootRef, contentRef, atEnd, jumpToEnd, follow, release } = useStickToBottom();
  useLayoutEffect(follow, [follow, thread.entries.length, thread.state]);
  const rows = useMemo(() => storyRows(thread, t), [thread, t]);
  const recipients = useMemo(() => {
    const ids = new Map<number, { from: string; to: string[] }>();
    for (const line of graph.edges) {
      if (line.from === "you") continue;
      for (const exchange of line.exchanges) {
        const found = ids.get(exchange.seq) ?? { from: line.from, to: [] };
        found.to.push(line.to);
        ids.set(exchange.seq, found);
      }
    }
    // What went to every other member reads "everyone", not a list of names.
    const others = (from: string) => thread.members.filter((member) => member.member_id !== from && member.state === "active").length;
    return new Map([...ids].map(([seq, { from, to }]) => [seq,
      to.length > 1 && to.length >= others(from) ? [t("team_threads.room.to_all")] : to.map((id) => names.name(id))]));
  }, [graph.edges, names, thread.members, t]);
  const over = thread.state === "done" || thread.state === "stopped" || thread.state === "failed";
  const working = thread.members.filter((member) => member.state === "active" && (member.working || member.waiting));
  const unresolved = thread.issues.filter((issue) => !issue.resolved).length;
  const toggle = (seq: number) => {
    // The person reads here: the story stops following its newest line.
    release();
    setOpen((current) => {
      const next = new Set(current);
      if (next.has(seq)) next.delete(seq);
      else next.add(seq);
      return next;
    });
  };

  return <div className="relative flex min-h-0 flex-1 flex-col" data-testid="team-story">
    <div ref={rootRef} className="min-h-0 flex-1 overflow-y-auto scrollbar-jarvis" role="log" aria-label={t("team_threads.room.story")}>
      <ol ref={contentRef} className="flex flex-col px-3 pb-6 pt-2">
        {rows.map((row) => {
          if (row.type === "heading") {
            return <li key={row.key} className="flex items-center gap-2 px-2 pb-1 pt-4 first:pt-1">
              <span className={cn("font-mono text-[10px] uppercase tracking-[0.14em]", row.current ? "text-accent" : "text-muted-foreground")}>{row.text}</span>
              <span aria-hidden className="h-px flex-1 bg-border" />
            </li>;
          }
          if (row.type === "entry") {
            return <StoryEntry key={row.key} entry={row.entry} names={names} to={recipients.get(row.entry.seq) ?? []}
              open={open.has(row.entry.seq)} onToggle={() => toggle(row.entry.seq)} />;
          }
          if (row.type === "user") {
            return <li key={row.key} className="flex justify-end px-2 py-1.5">
              <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl bg-secondary px-3.5 py-2 text-sm text-foreground [overflow-wrap:anywhere]"
                data-testid="team-entry-user">{row.entry.payload.text}</div>
            </li>;
          }
          if (row.type === "summary") return <Summary key={row.key} entry={row.entry} names={names} />;
          if (row.type === "notice") return <Notice key={row.key} entry={row.entry} names={names} />;
          return working.map((member) => <WorkingLine key={`live:${member.member_id}`} member={member} names={names} over={over} />);
        })}
        {thread.issues.length > 0 && <li className="mt-4" data-testid="team-thread-issues">
          <p className="flex items-center gap-2 px-2 pb-1.5">
            <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
              {fill(t("team_threads.issues.title"), { count: thread.issues.length, open: unresolved })}
            </span>
            <span aria-hidden className="h-px flex-1 bg-border" />
          </p>
          <ul className="flex flex-col gap-1.5 px-2">
            {thread.issues.map((issue, index) => <FindingRow key={`${issue.seq}-${index}`} finding={issue} resolved={issue.resolved}
              by={`${names.name(issue.by)} · ${fill(t(`team_threads.issues.${issue.stage}`), { number: issue.number ?? 0 })}`} />)}
          </ul>
        </li>}
      </ol>
    </div>
    {!atEnd && <ScrollToEndButton onClick={jumpToEnd} testId="team-story-scroll-end" className="top-auto bottom-3" />}
  </div>;
}
