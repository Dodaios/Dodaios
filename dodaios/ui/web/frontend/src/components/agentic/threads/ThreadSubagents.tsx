import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, Bot, Check, ChevronDown, ChevronRight, ChevronUp, CircleSlash, Loader2, MessageSquare, ShieldAlert, X } from "lucide-react";
import { ChatMarkdown } from "@/components/agentchat/ChatMarkdown";
import type { SubagentStatus, ToolBlock, TurnItem } from "@/components/agentchat/reduce";
import { traceDuration } from "@/components/agentchat/traceEntries";
import { cn } from "@/lib/utils";
import { fill, translate, useT } from "@/i18n";
import { shortCount, subagentCounts, subagentEntry, type SubagentEntry } from "./subagents";

/**
 * A thread's sub-agents on screen: a card where the main agent spawned one,
 * a compact group where it spawned several, a dock above the composer that
 * keeps the working ones in reach, and the header of an opened sub-agent's
 * own conversation.
 */

/**
 * Opens a sub-agent's conversation by the id of the call that spawned it.
 * Null where no conversation can be opened (an agent chat): the card then
 * only reports the sub-agent.
 */
export const OpenSubagent = createContext<((id: string) => void) | null>(null);

/** Locale keys of each state's word, translated where rendered. */
const STATUS_WORD: Record<SubagentStatus, string> = {
  running: "ide_threads.sub_status_running",
  done: "ide_threads.sub_status_done",
  failed: "ide_threads.sub_status_failed",
  stopped: "ide_threads.sub_status_stopped",
};

/** A sub-agent's state at a glance: working, waiting for the person, or how it ended. */
export function SubagentMark({ status, waiting = false, className }: { status: SubagentStatus; waiting?: boolean; className?: string }) {
  const box = cn("h-3.5 w-3.5 shrink-0", className);
  if (waiting && status === "running") return <ShieldAlert aria-hidden className={cn(box, "text-warning")} />;
  if (status === "running") return <Loader2 aria-hidden className={cn(box, "animate-spin text-muted-foreground")} />;
  if (status === "done") return <Check aria-hidden className={cn(box, "text-success")} />;
  if (status === "failed") return <X aria-hidden className={cn(box, "text-destructive")} />;
  return <CircleSlash aria-hidden className={cn(box, "text-muted-foreground")} />;
}

/** A clock that writes its own text once a second, so nothing around it re-renders to tick. */
function LiveClock({ since }: { since: number }) {
  const ref = useRef<HTMLSpanElement | null>(null);
  useEffect(() => {
    const tick = () => { if (ref.current) ref.current.textContent = traceDuration(Math.max(0, Date.now() - since)); };
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [since]);
  return <span ref={ref} className="tabular-nums">{traceDuration(Math.max(0, Date.now() - since))}</span>;
}

function firstLine(text: string): string {
  return text.split(/\r?\n/).map((line) => line.replace(/^[#>*\-\s]+/, "").trim()).find(Boolean) ?? "";
}

/** "4 tools · 23.4k tokens · 12s" — what the sub-agent spent so far. */
function SubagentMeta({ entry }: { entry: SubagentEntry }) {
  const t = useT();
  const parts: string[] = [];
  if (entry.toolUses) parts.push(fill(t(entry.toolUses === 1 ? "ide_threads.tools_one" : "ide_threads.tools_other"), { count: entry.toolUses }));
  if (entry.tokens) parts.push(fill(t("ide_threads.tokens"), { count: shortCount(entry.tokens) }));
  const running = entry.status === "running";
  const duration = !running && entry.durationMs ? traceDuration(entry.durationMs) : "";
  if (duration) parts.push(duration);
  if (!parts.length && !running) return null;
  return <span className="shrink-0 tabular-nums">
    {parts.join(" · ")}
    {running && <>{parts.length ? " · " : ""}<LiveClock since={entry.startedMs} /></>}
  </span>;
}

/** The line under a card's title: what it does now, else how it ended. */
function statusLine(entry: SubagentEntry): string {
  if (entry.status === "running") {
    if (entry.waiting) return translate("ide_threads.waiting_approval");
    return entry.activity || (entry.block.subagent?.lastTool
      ? fill(translate("ide_threads.using_tool"), { tool: entry.block.subagent.lastTool })
      : translate(STATUS_WORD.running));
  }
  if (entry.status === "failed") return firstLine(entry.summary) || translate(STATUS_WORD.failed);
  if (entry.status === "stopped") return translate("ide_threads.stopped_before_answer");
  return firstLine(entry.summary) || translate("ide_threads.finished");
}

/**
 * Where the main agent spawned a sub-agent: one card with its task, what it
 * is doing or how it ended, and what it spent. Where its conversation can be
 * opened, a click opens it.
 */
export function SubagentCard({ block, turn }: { block: ToolBlock; turn: TurnItem }) {
  const t = useT();
  const open = useContext(OpenSubagent);
  const entry = useMemo(() => subagentEntry(block, turn), [block, turn]);
  const running = entry.status === "running";
  const card = "group/agent flex w-full min-w-0 items-center gap-3 rounded-xl border border-border bg-card px-3 py-2.5 text-left";
  const body = <SubagentCardBody entry={entry} running={running} />;
  if (!open) return <div data-testid="thread-subagent-card" data-status={entry.status} className={card}>{body}</div>;
  return <button type="button" onClick={() => open(entry.id)} data-testid="thread-subagent-card" data-status={entry.status}
    aria-label={fill(t("ide_threads.open_subagent"), { title: entry.title, status: t(STATUS_WORD[entry.status]).toLowerCase() })}
    className={cn(card, "transition-colors hover:border-border-strong hover:bg-secondary/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring")}>
    {body}
    <span className="flex shrink-0 items-center gap-1 text-xs text-muted-foreground transition-colors group-hover/agent:text-foreground">
      <MessageSquare aria-hidden className="h-3.5 w-3.5" />
      <span className="hidden sm:inline">{t("ide_git.open")}</span>
      <ChevronRight aria-hidden className="h-3.5 w-3.5" />
    </span>
  </button>;
}

function SubagentCardBody({ entry, running }: { entry: SubagentEntry; running: boolean }) {
  return <>
    <span aria-hidden className="relative flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-secondary text-foreground-secondary">
      <Bot className="h-4 w-4" strokeWidth={1.75} />
      <span className="absolute -bottom-1 -right-1 flex h-4 w-4 items-center justify-center rounded-full border border-border bg-card">
        <SubagentMark status={entry.status} waiting={entry.waiting} className="h-2.5 w-2.5" />
      </span>
    </span>
    <span className="min-w-0 flex-1">
      <span className="flex min-w-0 items-center gap-2">
        <span className="truncate text-sm font-medium text-foreground-strong">{entry.title}</span>
        {entry.agentType && <span className="shrink-0 rounded-md border border-border px-1.5 text-[11px] leading-4 text-muted-foreground">{entry.agentType}</span>}
      </span>
      <span className="mt-0.5 flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
        <span className={cn("min-w-0 truncate", running && !entry.waiting && "live-tool-shine", entry.waiting && "text-warning", entry.status === "failed" && "text-destructive")}>{statusLine(entry)}</span>
        <span aria-hidden className="text-muted-foreground/50">·</span>
        <SubagentMeta entry={entry} />
      </span>
    </span>
  </>;
}

/** "3 sub-agents · 2 working · 1 waiting" — the count a group and the dock show. */
export function subagentSummary(entries: readonly SubagentEntry[]): string {
  const counts = subagentCounts(entries);
  const parts = [fill(translate(counts.total === 1 ? "ide_threads.subagents_one" : "ide_threads.subagents_other"), { count: counts.total })];
  if (counts.running) parts.push(fill(translate("ide_threads.count_working"), { count: counts.running }));
  if (counts.waiting) parts.push(fill(translate("ide_threads.count_waiting"), { count: counts.waiting }));
  if (counts.failed) parts.push(fill(translate("ide_threads.count_failed"), { count: counts.failed }));
  const done = entries.filter((entry) => entry.status === "done").length;
  if (done && done < counts.total) parts.push(fill(translate("ide_threads.count_done"), { count: done }));
  return parts.join(" · ");
}

/** How many rows a long list shows before "Show all"; working and waiting ones always show. */
const FOLDED_ROWS = 5;

function active(entry: SubagentEntry): boolean {
  return entry.status === "running" || entry.waiting;
}

/** The first rows of a long list, plus every one still working, waiting, failed or open. */
export function foldedEntries<T extends SubagentEntry>(entries: readonly T[], openId: string | null, all: boolean): T[] {
  if (all || entries.length <= FOLDED_ROWS + 1) return [...entries];
  return entries.filter((entry, index) => index < FOLDED_ROWS || active(entry) || entry.status === "failed" || entry.id === openId);
}

/**
 * The batch the dock is about: the sub-agents of every turn that still has
 * one working or waiting, else those of the turn whose sub-agent is open.
 * Agents of earlier turns stay in their groups and the sidebar.
 */
export function dockEntries(entries: readonly SubagentEntry[], openId: string | null): SubagentEntry[] {
  const turns = new Set(entries.filter(active).map((entry) => entry.turnId));
  if (!turns.size && openId !== null) {
    const open = entries.find((entry) => entry.id === openId);
    if (open) turns.add(open.turnId);
  }
  return entries.filter((entry) => turns.has(entry.turnId));
}

/**
 * How the sub-agents stand as one thin bar: done, failed, waiting and
 * working each take their share, so a glance tells how far the batch is.
 */
export function SubagentProgress({ entries, className }: { entries: readonly SubagentEntry[]; className?: string }) {
  if (entries.length === 0) return null;
  const parts = [
    { key: "done", count: entries.filter((e) => e.status === "done").length, tone: "bg-success" },
    { key: "failed", count: entries.filter((e) => e.status === "failed").length, tone: "bg-destructive" },
    { key: "waiting", count: entries.filter((e) => e.status === "running" && e.waiting).length, tone: "bg-warning" },
    { key: "running", count: entries.filter((e) => e.status === "running" && !e.waiting).length, tone: "bg-foreground/35 animate-pulse" },
    { key: "stopped", count: entries.filter((e) => e.status === "stopped").length, tone: "bg-muted-foreground/30" },
  ].filter((part) => part.count > 0);
  return <span aria-hidden data-testid="thread-subagent-progress" className={cn("flex h-1 overflow-hidden rounded-full bg-secondary", className)}>
    {parts.map((part) => <span key={part.key} data-part={part.key} className={part.tone} style={{ width: `${(part.count / entries.length) * 100}%` }} />)}
  </span>;
}

/**
 * One sub-agent on one line: its state, its name, what it does now or how
 * it ended, and what it spent. A click opens its conversation where one can
 * be opened. Many of them read as a list, not as a wall of cards.
 */
export function SubagentLine({ entry, onOpen, current = false, indent = 0 }: {
  entry: SubagentEntry;
  onOpen: ((id: string) => void) | null;
  current?: boolean;
  /** Levels of nesting below the list's own sub-agents. */
  indent?: number;
}) {
  const t = useT();
  const running = entry.status === "running";
  const body = <>
    <SubagentMark status={entry.status} waiting={entry.waiting} />
    <span className={cn("min-w-0 max-w-[45%] shrink-0 truncate font-medium", current ? "text-foreground-strong" : "text-foreground")}>{entry.title}</span>
    {entry.agentType && <span className="hidden shrink-0 rounded border border-border px-1 text-[10.5px] leading-4 text-muted-foreground sm:inline">{entry.agentType}</span>}
    <span className={cn("min-w-0 flex-1 truncate text-muted-foreground", running && !entry.waiting && "live-tool-shine", entry.waiting && "text-warning", entry.status === "failed" && "text-destructive")}>{statusLine(entry)}</span>
    <span className="hidden shrink-0 text-[11px] text-muted-foreground md:inline"><SubagentMeta entry={entry} /></span>
  </>;
  const row = "group/line flex min-h-8 w-full min-w-0 items-center gap-2 rounded-md px-2 py-1 text-left text-[13px]";
  const style = indent ? { paddingLeft: 8 + indent * 14 } : undefined;
  if (!onOpen) return <div className={row} style={style} data-testid="thread-subagent-row" data-status={entry.status}>{body}</div>;
  return <button type="button" onClick={() => onOpen(entry.id)} style={style} aria-current={current || undefined}
    title={entry.prompt || entry.title} data-testid="thread-subagent-row" data-status={entry.status}
    aria-label={fill(t("ide_threads.open_subagent"), { title: entry.title, status: t(STATUS_WORD[entry.status]).toLowerCase() })}
    className={cn(row, "transition-colors hover:bg-secondary/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", current && "bg-secondary")}>
    {body}
    <ChevronRight aria-hidden className="h-3.5 w-3.5 shrink-0 text-muted-foreground/50 transition-colors group-hover/line:text-foreground" />
  </button>;
}

function ShowAll({ all, count, onToggle }: { all: boolean; count: number; onToggle: () => void }) {
  const t = useT();
  return <button type="button" onClick={onToggle} data-testid="thread-subagent-show-all"
    className="flex min-h-7 w-full items-center rounded-md px-2 text-left text-xs text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
    {all ? t("ide_threads.show_less") : fill(t("ide_threads.show_all_agents"), { count })}
  </button>;
}

/**
 * Several sub-agents spawned together, read as one block: a header that
 * counts them and shows how far they are, then one line each. It stays open
 * while any of them works or waits and folds to its header once all have
 * ended, unless the person opened or closed it themselves.
 */
export function SubagentGroup({ blocks, turn }: { blocks: readonly ToolBlock[]; turn: TurnItem }) {
  const t = useT();
  const open = useContext(OpenSubagent);
  const entries = useMemo(() => blocks.map((block) => subagentEntry(block, turn)), [blocks, turn]);
  const busy = entries.some(active);
  const [chosen, setChosen] = useState<boolean | null>(null);
  const [all, setAll] = useState(false);
  const expanded = chosen ?? busy;
  const shown = foldedEntries(entries, null, all);
  const hidden = entries.length - shown.length;
  return <section data-testid="thread-subagent-group" aria-label={t("ide_threads.subagents_aria")}
    className="overflow-hidden rounded-xl border border-border bg-card">
    <button type="button" aria-expanded={expanded} onClick={() => setChosen(!expanded)} data-testid="thread-subagent-group-toggle"
      className="flex w-full min-w-0 items-center gap-2.5 px-3 py-2 text-left transition-colors hover:bg-secondary/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring">
      <span aria-hidden className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-secondary text-foreground-secondary">
        <Bot className="h-3.5 w-3.5" strokeWidth={1.75} />
      </span>
      <span className="min-w-0 flex-1">
        <span className={cn("block truncate text-sm text-foreground-strong", busy && "live-tool-shine")} data-testid="thread-subagent-group-count">{subagentSummary(entries)}</span>
        <SubagentProgress entries={entries} className="mt-1.5 max-w-[14rem]" />
      </span>
      <ChevronDown aria-hidden className={cn("h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-150", !expanded && "-rotate-90")} />
    </button>
    {expanded && <div className="border-t border-border/70 px-1 py-1" data-testid="thread-subagent-group-rows">
      {shown.map((entry) => <SubagentLine key={entry.id} entry={entry} onOpen={open} />)}
      {(hidden > 0 || all) && <ShowAll all={all} count={entries.length} onToggle={() => setAll(!all)} />}
    </div>}
  </section>;
}

/**
 * The thread's sub-agents above the composer, the way a coding app keeps its
 * running agents in reach: one quiet bar that counts them and shows how far
 * they are, and a list that opens any of them. It shows while one still
 * works or waits, or while a sub-agent's conversation is open (it is the way
 * back to the main thread); once all have ended, the groups in the
 * conversation and the sidebar keep them.
 */
export function SubagentDock({ entries: thread, openId, onOpen }: {
  entries: readonly SubagentEntry[];
  openId: string | null;
  onOpen: (id: string | null) => void;
}) {
  const t = useT();
  const [expanded, setExpanded] = useState(false);
  const [all, setAll] = useState(false);
  const entries = useMemo(() => dockEntries(thread, openId), [thread, openId]);
  const busy = entries.some(active);
  if (entries.length === 0 || (!busy && openId === null)) return null;
  const shown = foldedEntries(entries, openId, all);
  const hidden = entries.length - shown.length;
  return <div data-testid="thread-subagent-dock" className="mx-auto mb-2 w-full max-w-3xl overflow-hidden rounded-xl border border-border bg-popover shadow-float">
    {expanded && <nav aria-label={t("ide_threads.subagents_aria")} data-testid="thread-subagent-dock-list"
      className="max-h-[40vh] overflow-y-auto border-b border-border/70 px-1 py-1 scrollbar-jarvis">
      {openId !== null && <button type="button" onClick={() => onOpen(null)} data-testid="thread-subagent-main"
        className="flex min-h-8 w-full items-center gap-2 rounded-md px-2 py-1 text-left text-[13px] text-foreground transition-colors hover:bg-secondary/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <MessageSquare aria-hidden className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        <span className="truncate font-medium">{t("ide_threads.main_thread")}</span>
      </button>}
      {shown.map((entry) => <SubagentLine key={entry.id} entry={entry} onOpen={onOpen} current={entry.id === openId} indent={entry.depth} />)}
      {(hidden > 0 || all) && <ShowAll all={all} count={entries.length} onToggle={() => setAll(!all)} />}
    </nav>}
    <button type="button" aria-expanded={expanded} onClick={() => setExpanded(!expanded)} data-testid="thread-subagent-dock-toggle"
      title={t(expanded ? "ide_threads.dock_collapse" : "ide_threads.dock_expand")}
      className="flex w-full min-w-0 items-center gap-2.5 px-3 py-2 text-left transition-colors hover:bg-secondary/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring">
      <Bot aria-hidden className="h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={1.75} />
      <span className="min-w-0 flex-1 truncate text-xs text-foreground-secondary" data-testid="thread-subagent-count">{subagentSummary(entries)}</span>
      <SubagentProgress entries={entries} className="w-24 shrink-0" />
      <ChevronUp aria-hidden className={cn("h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-150", expanded && "rotate-180")} />
    </button>
  </div>;
}

/**
 * The top of an opened sub-agent's conversation: the way back, who it is,
 * where it sits (a sub-agent's own sub-agents name their parents), how it
 * stands, and the task the main agent gave it.
 */
export function SubagentHeader({ entry, path, onOpen }: {
  entry: SubagentEntry;
  path: readonly SubagentEntry[];
  onOpen: (id: string | null) => void;
}) {
  const t = useT();
  const [taskOpen, setTaskOpen] = useState(false);
  const long = entry.prompt.length > 280 || entry.prompt.split("\n").length > 5;
  const parent = path.length > 1 ? path[path.length - 2] : null;
  return <div className="space-y-3" data-testid="thread-subagent-header">
    <div className="flex min-w-0 items-center gap-2 text-sm">
      <button type="button" onClick={() => onOpen(parent ? parent.id : null)} data-testid="thread-subagent-back"
        className="flex h-7 shrink-0 items-center gap-1.5 rounded-md px-1.5 text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <ArrowLeft aria-hidden className="h-4 w-4" />
        <span>{parent ? parent.title : t("ide_threads.main_thread")}</span>
      </button>
    </div>
    <div className="flex min-w-0 items-start gap-3">
      <span aria-hidden className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-secondary text-foreground-secondary">
        <Bot className="h-5 w-5" strokeWidth={1.75} />
      </span>
      <div className="min-w-0 flex-1">
        <h2 className="flex min-w-0 items-center gap-2 text-base font-semibold text-foreground-strong">
          <span className="truncate">{entry.title}</span>
          {entry.agentType && <span className="shrink-0 rounded-md border border-border px-1.5 text-[11px] font-normal leading-4 text-muted-foreground">{entry.agentType}</span>}
        </h2>
        <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
          <span className="flex items-center gap-1">
            <SubagentMark status={entry.status} waiting={entry.waiting} />
            {entry.waiting && entry.status === "running" ? t("ide_threads.waiting_approval") : t(STATUS_WORD[entry.status])}
          </span>
          {entry.background && <><span aria-hidden>·</span><span>{t("ide_threads.in_background")}</span></>}
          <span aria-hidden>·</span>
          <SubagentMeta entry={entry} />
        </div>
      </div>
    </div>
    {entry.prompt && <section aria-label={t("ide_threads.task")} className="rounded-xl border border-border bg-card px-3 py-2.5">
      <div className="mb-1 text-xs font-medium text-muted-foreground">{fill(t("ide_threads.task_from"), { parent: parent ? parent.title : t("ide_threads.the_main_agent") })}</div>
      <div className={cn("relative text-sm leading-6 text-foreground-secondary [overflow-wrap:anywhere]", long && !taskOpen && "max-h-32 overflow-hidden")}>
        <div className="prose prose-neutral max-w-none text-sm dark:prose-invert prose-p:my-1 prose-p:text-foreground-secondary prose-li:text-foreground-secondary"><ChatMarkdown text={entry.prompt} /></div>
        {long && !taskOpen && <div aria-hidden className="pointer-events-none absolute inset-x-0 bottom-0 h-10 bg-gradient-to-t from-card to-transparent" />}
      </div>
      {long && <button type="button" aria-expanded={taskOpen} onClick={() => setTaskOpen(!taskOpen)}
        className="mt-1 text-xs text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        {taskOpen ? t("ide_threads.show_less") : t("ide_threads.show_whole_task")}
      </button>}
    </section>}
    {!entry.streamed && <p className="text-xs text-muted-foreground" data-testid="thread-subagent-unstreamed">
      {entry.status === "running"
        ? t("ide_threads.unstreamed_running")
        : t("ide_threads.unstreamed_done")}
    </p>}
  </div>;
}
