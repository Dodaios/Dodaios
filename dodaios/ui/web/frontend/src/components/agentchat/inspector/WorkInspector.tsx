import { memo, useCallback, useEffect, useId, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import {
  Bot, Brain, ChevronRight, ChevronsDownUp, ChevronsUpDown, CircleX, KeyRound, ListTree,
  Loader2, MessageCircleQuestion, MessageSquareText, ShieldQuestion, User, X,
} from "lucide-react";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { useStickToBottom } from "@/hooks/useStickToBottom";
import { listSubagents, subagentTurn, type SubagentEntry } from "@/components/agentic/threads/subagents";
import { ChatMarkdown } from "../ChatMarkdown";
import type { SubagentStatus, ToolBlock, TurnItem } from "../reduce";
import { toolDiff } from "../toolDiff";
import { CallMark } from "../TraceTimeline";
import { plural, readableOutput, traceDuration } from "../traceEntries";
import { formatTokens, outputTokens } from "../toolView";
import { inspectorRows, rowCounts, type InspectorRow } from "./inspectorRows";
import { clampWidth, INSPECTOR_MAX, INSPECTOR_MIN } from "./inspectorWidth";
import "./inspector.css";

/**
 * The work inspector: the full account of one turn, one click from the
 * conversation and out of its way. A side pane with the turn's whole trace
 * as rows (the request, thoughts, replies, calls, cards, helpers), each
 * opening to what it ran and what came back. Every helper the agent started
 * gets a tab of its own with its own trace and a status dot.
 *
 * Reasoning lives here, never in the conversation. The rows come from the
 * event log, so they are the same for every runtime; a runtime that sends
 * only finished blocks shows those, and one that sends nothing live shows an
 * empty state until its turn lands.
 */
export interface WorkInspectorProps {
  turn: TurnItem;
  /** The person's message that started the turn. */
  prompt?: string;
  agentName: string;
  /** The agent's colour, the pane's one accent. */
  color: string;
  avatar?: ReactNode;
  width: number;
  onWidth: (width: number) => void;
  /** The pane floats over the conversation (a narrow window) instead of sitting beside it. */
  floating: boolean;
  onClose: () => void;
  /** Open on a helper's tab (the spawning call's id). */
  initialTab?: string;
}

const MAIN = "main";

const STATUS_DOT: Record<SubagentStatus, string> = { running: "running", done: "done", failed: "failed", stopped: "stopped" };

function turnDot(status: TurnItem["status"]): string {
  return status === "running" ? "running" : status === "error" ? "failed" : status === "cancelled" ? "stopped" : "done";
}

export const WorkInspector = memo(function WorkInspector({
  turn, prompt, agentName, color, avatar, width, onWidth, floating, onClose, initialTab,
}: WorkInspectorProps) {
  const t = useT();
  const titleId = useId();
  const helpers = useMemo(() => listSubagents([turn]), [turn]);
  const [tab, setTab] = useState(initialTab ?? MAIN);
  const active: SubagentEntry | null = tab === MAIN ? null : helpers.find((entry) => entry.id === tab) ?? null;
  // A helper that vanished (another turn opened) falls back to the main tab.
  useEffect(() => {
    if (tab !== MAIN && !helpers.some((entry) => entry.id === tab)) setTab(MAIN);
  }, [helpers, tab]);
  useEffect(() => {
    if (initialTab) setTab(initialTab);
  }, [initialTab]);

  const pane = useRef<HTMLElement | null>(null);
  // Esc closes the pane, unless someone is typing or another layer owns Esc.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      const target = event.target as HTMLElement | null;
      if (target && target.closest("input, textarea, select, [contenteditable='true'], [role='dialog']")) return;
      event.preventDefault();
      onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  // Declared first, so it sees the opener before the pane takes focus.
  // Closing hands focus back to what opened the pane (the "show work" line),
  // when focus was still in the pane and would otherwise drop to the page.
  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const node = pane.current;
    return () => {
      const focus = document.activeElement;
      const lost = !focus || focus === document.body || Boolean(node && node.contains(focus));
      if (lost && opener && opener.isConnected) opener.focus({ preventScroll: true });
    };
  }, []);
  // Opening moves focus into the pane, so the keyboard can read it at once.
  // Following a new turn never takes focus from someone typing elsewhere.
  useEffect(() => {
    const focus = document.activeElement as HTMLElement | null;
    const node = pane.current;
    const typing = Boolean(focus && !node?.contains(focus) && focus.closest("input, textarea, select, [contenteditable='true']"));
    if (!typing) node?.focus({ preventScroll: true });
  }, [turn.id]);

  const tokens = outputTokens(turn.usage ?? turn.liveUsage);
  const meta: string[] = [agentName];
  if (turn.status === "running") meta.push(t("run_view.work.working"));
  else if (turn.durationMs) meta.push(fill(t("run_view.work.worked_for"), { duration: traceDuration(turn.durationMs) }));
  if (tokens && tokens > 0) meta.push(fill(t("run_view.inspector.tokens"), { count: formatTokens(tokens) }));
  if (turn.costUsd !== null && turn.costUsd > 0) meta.push(`$${turn.costUsd.toFixed(4)}`);
  if (turn.model) meta.push(turn.model);

  return <aside ref={pane} tabIndex={-1} aria-labelledby={titleId}
    className={cn("work-inspector", floating && "is-floating")}
    style={{ width, "--agent": color } as CSSProperties}
    data-testid="work-inspector" data-turn={turn.id}>
    <ResizeEdge width={width} onWidth={onWidth} />
    <header className="wi-head">
      <span className="wi-head-mark" aria-hidden>{avatar ?? <ListTree className="h-4 w-4" />}</span>
      <div className="min-w-0 flex-1">
        <h2 id={titleId} className="wi-title">{t("run_view.inspector.title")}</h2>
        <p className="wi-meta">{meta.join(" · ")}</p>
      </div>
      <button type="button" className="wi-icon-btn" onClick={onClose} aria-label={t("run_view.inspector.close")} title={t("run_view.inspector.close")}
        data-testid="work-inspector-close">
        <X aria-hidden className="h-4 w-4" />
      </button>
    </header>
    {helpers.length > 0 ? <InspectorTabs agentName={agentName} turn={turn} helpers={helpers} tab={tab} onTab={setTab} /> : null}
    <TracePanel key={tab} turn={turn} entry={active} prompt={active ? undefined : prompt} onOpenHelper={setTab}
      label={active ? active.title : agentName} />
  </aside>;
});

/** The pane's left edge: drag it, or focus it and use the arrow keys. */
function ResizeEdge({ width, onWidth }: { width: number; onWidth: (width: number) => void }) {
  const t = useT();
  const start = useRef<{ x: number; width: number } | null>(null);
  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    start.current = { x: event.clientX, width };
    event.currentTarget.setPointerCapture?.(event.pointerId);
    event.preventDefault();
  };
  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!start.current) return;
    onWidth(clampWidth(start.current.width + (start.current.x - event.clientX)));
  };
  const onPointerUp = () => {
    start.current = null;
  };
  const onKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const step = event.shiftKey ? 64 : 16;
    if (event.key === "ArrowLeft") onWidth(clampWidth(width + step));
    else if (event.key === "ArrowRight") onWidth(clampWidth(width - step));
    else if (event.key === "Home") onWidth(INSPECTOR_MAX);
    else if (event.key === "End") onWidth(INSPECTOR_MIN);
    else return;
    event.preventDefault();
  };
  return <div className="wi-edge" role="separator" aria-orientation="vertical" tabIndex={0}
    aria-label={t("run_view.inspector.resize")} aria-valuemin={INSPECTOR_MIN} aria-valuemax={INSPECTOR_MAX} aria-valuenow={width}
    onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp}
    onKeyDown={onKeyDown} data-testid="work-inspector-edge" />;
}

function InspectorTabs({ agentName, turn, helpers, tab, onTab }: {
  agentName: string; turn: TurnItem; helpers: SubagentEntry[]; tab: string; onTab: (id: string) => void;
}) {
  const t = useT();
  const ids = [MAIN, ...helpers.map((entry) => entry.id)];
  const refs = useRef(new Map<string, HTMLButtonElement>());
  const move = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const at = ids.indexOf(tab);
    let next = -1;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") next = (at + 1) % ids.length;
    else if (event.key === "ArrowLeft" || event.key === "ArrowUp") next = (at - 1 + ids.length) % ids.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = ids.length - 1;
    if (next < 0) return;
    event.preventDefault();
    onTab(ids[next]);
    refs.current.get(ids[next])?.focus();
  };
  const tabButton = (id: string, label: string, dot: string, depth = 0, kind = "") => <button key={id} type="button" role="tab"
    ref={(node) => { if (node) refs.current.set(id, node); else refs.current.delete(id); }}
    aria-selected={tab === id} tabIndex={tab === id ? 0 : -1} onClick={() => onTab(id)}
    className="wi-tab" data-depth={depth || undefined} title={label} data-testid="work-inspector-tab">
    <span className="wi-dot" data-state={dot} aria-hidden />
    {kind ? <span className="wi-tab-kind">{kind}</span> : null}
    <span className="min-w-0 truncate">{label}</span>
    <span className="sr-only">{t(`run_view.status.${dot}`)}</span>
  </button>;
  return <div role="tablist" aria-label={t("run_view.inspector.tabs")} className="wi-tabs" onKeyDown={move}>
    {tabButton(MAIN, agentName, turnDot(turn.status))}
    {helpers.map((entry) => tabButton(entry.id, entry.title, entry.waiting ? "waiting" : STATUS_DOT[entry.status], entry.depth, entry.agentType))}
  </div>;
}

function TracePanel({ turn, entry, prompt, onOpenHelper, label }: {
  turn: TurnItem; entry: SubagentEntry | null; prompt?: string; onOpenHelper: (id: string) => void;
  /** Whose trace this is, for the panel's accessible name. */
  label: string;
}) {
  const t = useT();
  const lang = t("trace_report.locale");
  const trace = useMemo(() => entry ? helperTrace(entry) : turn, [entry, turn]);
  // A helper's trace opens with the task it was given, the main one with the person's message.
  const rows = useMemo(() => inspectorRows(trace.blocks, { t, lang, status: trace.status, prompt: entry ? entry.prompt : prompt, promptLabel: entry ? "run_view.row.task" : undefined }),
    [trace, t, lang, entry, prompt]);
  const counts = rowCounts(rows);
  const [open, setOpen] = useState<Set<string>>(() => new Set());
  const allOpen = rows.length > 0 && rows.every((row) => open.has(row.id));
  const toggle = useCallback((id: string) => setOpen((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  }), []);
  const { rootRef, contentRef, follow } = useStickToBottom();
  useEffect(follow, [follow, rows.length]);
  const lead = [
    counts.steps ? fill(t(`run_view.work.steps_${plural(lang, counts.steps)}`), { count: counts.steps }) : "",
    counts.thoughts ? fill(t(`run_view.inspector.thoughts_${plural(lang, counts.thoughts)}`), { count: counts.thoughts }) : "",
    counts.failed ? fill(t("run_view.inspector.failed"), { count: counts.failed }) : "",
  ].filter(Boolean).join(" · ");
  return <div className="wi-body" role="tabpanel" aria-label={label}>
    <div className="wi-toolbar">
      <span className="min-w-0 truncate">{lead}</span>
      {rows.length > 0 ? <button type="button" className="wi-text-btn" onClick={() => setOpen(allOpen ? new Set() : new Set(rows.map((row) => row.id)))}>
        {allOpen ? <ChevronsDownUp aria-hidden className="h-3.5 w-3.5" /> : <ChevronsUpDown aria-hidden className="h-3.5 w-3.5" />}
        {t(allOpen ? "run_view.inspector.collapse_all" : "run_view.inspector.expand_all")}
      </button> : null}
    </div>
    <div ref={rootRef} className="wi-scroll chat-scroller" data-testid="work-inspector-rows">
      <div ref={contentRef}>
        {rows.length === 0
          ? <p className="wi-empty">{t(trace.status === "running" ? "run_view.inspector.empty_live" : "run_view.inspector.empty")}</p>
          : <ol className="wi-rows">
            {rows.map((row) => <li key={row.id}>
              <TraceRow row={row} open={open.has(row.id)} onToggle={toggle} onOpenHelper={onOpenHelper} />
            </li>)}
          </ol>}
      </div>
    </div>
  </div>;
}

/**
 * A helper's own trace. A helper that streamed its steps but whose answer
 * arrived only in its final report still ends with that answer.
 */
function helperTrace(entry: SubagentEntry): TurnItem {
  const trace = subagentTurn(entry);
  const summary = entry.summary.trim();
  const last = [...trace.blocks].reverse().find((block) => block.kind === "text");
  if (!summary || (last && last.kind === "text" && last.text.trim() === summary)) return trace;
  return { ...trace, blocks: [...trace.blocks, { kind: "text", id: `summary:${entry.id}`, text: summary }] };
}

const KIND_ICON = {
  prompt: User,
  thought: Brain,
  reply: MessageSquareText,
  question: MessageCircleQuestion,
  approval: ShieldQuestion,
  credential: KeyRound,
  helper: Bot,
} as const;

function RowMark({ row }: { row: InspectorRow }) {
  if (row.status === "running") return <Loader2 aria-hidden className="wi-mark motion-safe:animate-spin" />;
  if (row.status === "failed") return <CircleX aria-hidden className="wi-mark" />;
  if (row.kind === "call" && row.call) return <span className="wi-mark-box"><CallMark call={row.call} /></span>;
  const Icon = row.kind === "call" ? ListTree : KIND_ICON[row.kind];
  return <Icon aria-hidden className="wi-mark" strokeWidth={1.75} />;
}

const TraceRow = memo(function TraceRow({ row, open, onToggle, onOpenHelper }: {
  row: InspectorRow; open: boolean; onToggle: (id: string) => void; onOpenHelper: (id: string) => void;
}) {
  const t = useT();
  const detailId = useId();
  return <div className="wi-row" data-kind={row.kind} data-status={row.status} data-testid="work-inspector-row">
    <button type="button" className="wi-row-btn" aria-expanded={open} aria-controls={detailId} onClick={() => onToggle(row.id)}>
      <RowMark row={row} />
      <span className={cn("wi-label", row.status === "running" && "wi-live")}>{row.label}</span>
      {row.preview ? <span className="wi-preview" title={row.preview}>{row.preview}</span> : <span className="flex-1" />}
      {row.added || row.removed ? <span className="wi-diffstat">
        {row.added ? <span className="run-diff-add">+{row.added}</span> : null}{row.added && row.removed ? " " : null}
        {row.removed ? <span className="run-diff-del">−{row.removed}</span> : null}
      </span> : null}
      {row.status === "waiting" || row.status === "declined" || row.status === "stopped"
        ? <span className="wi-state" data-state={row.status}>{t(`run_view.status.${row.status}`)}</span> : null}
      {row.durationMs && row.status !== "running" ? <span className="wi-time">{traceDuration(row.durationMs)}</span> : null}
      <ChevronRight aria-hidden className={cn("wi-chev", open && "is-open")} />
    </button>
    {open ? <div id={detailId} className="wi-detail"><RowDetail row={row} onOpenHelper={onOpenHelper} /></div> : null}
  </div>;
});

/** Very long values stay readable; the pane is not a log viewer. */
const DETAIL_CAP = 20_000;

function capped(text: string): string {
  return text.length > DETAIL_CAP ? `${text.slice(0, DETAIL_CAP)}\n…` : text;
}

function pretty(value: unknown): string {
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2) ?? "";
  } catch {
    return String(value);
  }
}

function Section({ label, children }: { label: string; children: ReactNode }) {
  return <section className="wi-section">
    <h3 className="wi-section-label">{label}</h3>
    {children}
  </section>;
}

function Pre({ text }: { text: string }) {
  return <pre tabIndex={0} className="wi-pre">{capped(text)}</pre>;
}

function Prose({ text }: { text: string }) {
  return <div className="wi-prose prose prose-sm max-w-none dark:prose-invert [overflow-wrap:anywhere]"><ChatMarkdown text={text} /></div>;
}

function RowDetail({ row, onOpenHelper }: { row: InspectorRow; onOpenHelper: (id: string) => void }) {
  const t = useT();
  if (row.kind === "prompt" || row.kind === "reply") return <Prose text={row.text ?? ""} />;
  if (row.kind === "thought") return row.text ? <Prose text={row.text} /> : <p className="wi-note">{t("run_view.inspector.thought_private")}</p>;
  const block = row.block;
  if (!block) return <p className="wi-note">{t("run_view.inspector.no_details")}</p>;
  if (row.kind === "question") return <QuestionDetail block={block} />;
  if (row.kind === "credential") {
    const c = block.credential!;
    return <div className="wi-sections">
      <Section label={t("run_view.section.asked_for")}><p className="wi-text">{c.label || c.env}</p></Section>
      {c.description ? <p className="wi-note">{c.description}</p> : null}
    </div>;
  }
  if (row.kind === "approval") {
    return <div className="wi-sections">
      <Section label={t("run_view.section.request")}><p className="wi-text">{block.approval?.summary || block.name}</p></Section>
      <ToolSections block={block} />
    </div>;
  }
  if (row.kind === "helper") {
    const sub = block.subagent;
    const input = block.input && typeof block.input === "object" ? block.input as Record<string, unknown> : {};
    const task = sub?.prompt || (typeof input.prompt === "string" ? input.prompt : "");
    return <div className="wi-sections">
      {task ? <Section label={t("run_view.section.task")}><Prose text={task} /></Section> : null}
      {sub?.summary ? <Section label={t("run_view.section.answer")}><Prose text={sub.summary} /></Section> : null}
      <button type="button" className="wi-text-btn self-start" onClick={() => onOpenHelper(block.callId)}>
        <Bot aria-hidden className="h-3.5 w-3.5" />{t("run_view.inspector.open_helper")}
      </button>
    </div>;
  }
  return <div className="wi-sections"><ToolSections block={block} command={row.call?.kind === "command" ? row.call.text : undefined} /></div>;
}

function QuestionDetail({ block }: { block: ToolBlock }) {
  const t = useT();
  const q = block.question!;
  return <ol className="wi-qa">
    {q.questions.map((item, i) => {
      const answer = q.answers[i];
      return <li key={i}>
        <p className="wi-text">{item.question}</p>
        <p className="wi-answer">{answer ? answer.text || t("run_view.inspector.no_answer") : t("run_view.status.waiting")}</p>
      </li>;
    })}
  </ol>;
}

/** What a call ran, what it changed and what came back. */
function ToolSections({ block, command }: { block: ToolBlock; command?: string }) {
  const t = useT();
  const diff = useMemo(() => toolDiff(block.name, block.input, block.output), [block.name, block.input, block.output]);
  const output = block.output === null ? null : readableOutput(block);
  const input = block.input && typeof block.input === "object" ? block.input as Record<string, unknown> : null;
  const fullCommand = command !== undefined
    ? (typeof input?.command === "string" ? input.command : typeof input?.cmd === "string" ? input.cmd : command)
    : null;
  return <>
    <p className="wi-tool-name">{block.name}</p>
    {fullCommand !== null
      ? <Section label={t("run_view.section.command")}><Pre text={`$ ${fullCommand}`} /></Section>
      : block.input !== undefined && block.input !== null && pretty(block.input).trim() && pretty(block.input) !== "{}"
        ? <Section label={t("run_view.section.input")}><Pre text={pretty(block.input)} /></Section> : null}
    {diff ? <Section label={t("run_view.section.changes")}>
      <div className="wi-diff" tabIndex={0}>
        {diff.map((file, i) => <div key={i} className="wi-diff-file">
          <p className="wi-diff-path">
            <span className="min-w-0 truncate">{file.path}</span>
            <span className="wi-diffstat"><span className="run-diff-add">+{file.added}</span> <span className="run-diff-del">−{file.removed}</span></span>
          </p>
          {file.lines.map((line, n) => <div key={n} data-kind={line.kind}
            className={cn("wi-diff-line", line.kind === "add" && "diff-line-add", line.kind === "del" && "diff-line-del")}>
            {line.kind === "add" ? "+ " : line.kind === "del" ? "− " : line.kind === "gap" ? "  ⋯ " : "  "}{line.text}
          </div>)}
          {file.truncated > 0 ? <p className="wi-note">{fill(t("run_view.inspector.truncated"), { count: file.truncated })}</p> : null}
        </div>)}
      </div>
    </Section> : null}
    {output !== null
      ? <Section label={t(block.isError ? "run_view.section.error" : "run_view.section.output")}>
        {output.trim() ? <Pre text={output} /> : <p className="wi-note">{t("run_view.inspector.empty_output")}</p>}
      </Section>
      : null}
    {block.durationMs ? <p className="wi-note">{fill(t("run_view.inspector.took"), { duration: traceDuration(block.durationMs) })}</p> : null}
  </>;
}
