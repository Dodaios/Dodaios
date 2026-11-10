import { createContext, memo, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ArrowDown, Bot, Check, ChevronDown, ChevronRight, Copy, Diff, FileText, MessageCircleQuestion, ShieldAlert, X } from "lucide-react";
import { ChatMarkdown } from "@/components/agentchat/ChatMarkdown";
import { CredentialCard } from "@/components/agentchat/CredentialCard";
import { QuestionCard } from "@/components/agentchat/QuestionCard";
import { STEER_PREFIX, waitsOnCard, type TextBlock, type TimelineItem, type ToolBlock, type TurnBlock, type TurnItem, type UserItem } from "@/components/agentchat/reduce";
import { toolDiff, type DiffFile } from "@/components/agentchat/toolDiff";
import { capitalize, plural, readableOutput, tr, traceDuration, type Call } from "@/components/agentchat/traceEntries";
import { fill, useI18nStore, useT } from "@/i18n";
import { localeForUiLanguage } from "@/components/runs/format";
import { ApprovalActionCard, type ApprovalDecide } from "@/components/agentchat/actionCard/ApprovalActionCard";
import { robustCopy } from "@/lib/clipboard";
import { cn } from "@/lib/utils";
import { ChatThought } from "./ChatThought";
import { buildThreadRows, isFailed, joinStretches, type Stretch, type StretchItem, type ThreadRow } from "./threadWork";
import { flattenMarks } from "@/lib/plainMarks";
import { SubagentRun } from "./ThreadSubagents";
import { listSubagents } from "./subagents";
import { turnErrorText } from "@/components/agentchat/turnError";

/**
 * A thread's conversation: the person's messages on the right, the agent's
 * answer as plain reading text on the left, and the work in between as a
 * quiet log. A thought the agent put into words reads as prose, a step
 * quieter than the answer, so a turn says what it is doing from its first
 * step on; a long thought shows its first lines and opens to the rest. The
 * calls between two pieces of prose are ONE grey line with a chevron that
 * says what they did ("Ran commands, edited a file"). The line never opens by
 * itself: while the turn works it carries the live shine. A click opens a
 * card with one row per step, a hairline between them; a row opens to what
 * the call ran, the diff it made or what came back. A running turn ends in "Working for 12s";
 * a finished one says how long it worked and which files it changed.
 *
 * The work-log geometry and the live shine are adapted from pingdotgg/t3code
 * @ e22c880 (apps/web/src/components/chat/WorkLog.tsx, MessagesTimeline.tsx),
 * MIT License, Copyright (c) 2026 T3 Tools Inc. — third_party/t3code/LICENSE.
 */

export const PROSE = cn(
  "py-1 prose prose-neutral max-w-none text-base leading-6 text-foreground dark:prose-invert dark:text-foreground [overflow-wrap:anywhere]",
  "[&>div>:first-child]:mt-0 [&>div>:last-child]:mb-0",
  "prose-p:my-2 prose-p:text-foreground prose-li:text-foreground prose-strong:text-foreground-strong",
  "prose-headings:mb-1.5 prose-headings:mt-4 prose-headings:font-semibold prose-headings:tracking-normal prose-headings:text-foreground-strong",
  "prose-h1:text-lg prose-h2:text-base prose-h3:text-base prose-h4:text-base",
  "prose-a:text-foreground-strong prose-a:underline prose-a:decoration-border-strong prose-a:underline-offset-2",
  "prose-code:rounded prose-code:bg-secondary prose-code:px-1 prose-code:py-0.5 prose-code:font-mono prose-code:font-normal prose-code:before:hidden prose-code:after:hidden",
  "prose-pre:my-2 prose-pre:rounded-lg prose-pre:border prose-pre:border-border prose-pre:bg-card prose-pre:text-sm",
  "prose-li:my-0.5 prose-ul:my-2 prose-ol:my-2 prose-ul:pl-5 prose-ol:pl-5",
  "prose-table:my-3 prose-table:text-sm prose-th:text-foreground-strong prose-td:text-foreground",
);

/**
 * One row of the work log, set like a line of the answer: body size, a 16 px
 * mark flush with the text's left edge, the words in the quiet tone, then a
 * trailing note. A row on its own gets the air of a paragraph; rows inside an
 * opened group sit tight. The words of a live row carry the shine. The
 * chevron of a row that opens shows only on hover, focus or while open, so a
 * finished log reads as plain grey lines between the agent's words.
 */
function WorkRow({
  icon,
  label,
  trailing,
  expanded,
  onToggle,
  grouped = false,
  live = false,
  stamp,
  ariaLabel,
  children,
}: {
  /** A step inside an opened list wears its mark; a line of the thread itself has none. */
  icon?: ReactNode;
  label: ReactNode;
  trailing?: ReactNode;
  expanded?: boolean;
  onToggle?: () => void;
  grouped?: boolean;
  live?: boolean;
  /** When the step began; shown while the row is hovered. */
  stamp?: number;
  ariaLabel?: string;
  children?: ReactNode;
}) {
  const line = <span className={cn("flex min-h-6 min-w-0 items-center gap-2.5 leading-6", grouped ? "text-sm" : "text-base")}>
    {icon && <span aria-hidden className="flex h-6 w-4 shrink-0 items-center justify-center text-muted-foreground [&_svg]:h-4 [&_svg]:w-4">{icon}</span>}
    <span className={cn(
      "min-w-0 truncate transition-colors",
      "text-muted-foreground",
      onToggle && !live && "group-hover/row:text-foreground",
      live && "live-tool-shine",
    )}>{label}</span>
    {trailing}
    {onToggle && <span aria-hidden className={cn("flex h-4 w-4 shrink-0 items-center justify-center", !icon && "-ml-1.5")}>
      <ChevronRight className={cn(
        "h-3.5 w-3.5 text-muted-foreground transition duration-200 group-hover/row:opacity-100 group-focus-visible/row:opacity-100",
        // A line of the thread always shows that it opens; a step in a list only when pointed at.
        icon ? "opacity-0 group-hover/row:opacity-70" : "opacity-60",
        expanded && "rotate-90 opacity-70",
      )} />
    </span>}
    {stamp ? <span className="ml-auto shrink-0 pl-2 text-xs tabular-nums text-muted-foreground opacity-0 transition-opacity group-hover/row:opacity-100 group-focus-visible/row:opacity-100">{clock(stamp)}</span> : null}
  </span>;
  const row = cn("group/row relative block w-full min-w-0 rounded-md text-left", grouped ? "py-0" : "py-1.5");
  return <div className="min-w-0">
    {onToggle
      ? <button type="button" aria-expanded={expanded} aria-label={ariaLabel} onClick={onToggle}
        className={cn(row, "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring")}>{line}</button>
      : <div className={row}>{line}</div>}
    {expanded && children}
  </div>;
}

function DiffStat({ added, removed }: { added: number; removed: number }) {
  if (!added && !removed) return null;
  return <span className="shrink-0 font-mono text-xs tabular-nums">
    {added > 0 && <span className="text-success">+{added}</span>}
    {added > 0 && removed > 0 && " "}
    {removed > 0 && <span className="text-destructive">−{removed}</span>}
  </span>;
}

function DiffView({ files }: { files: DiffFile[] }) {
  return <div className="space-y-2">
    {files.map((file, index) => <div key={`${file.path}:${index}`} className="overflow-hidden rounded-lg border border-border bg-card">
      {file.path && <div className="flex items-center gap-2 border-b border-border px-3 py-1.5 font-mono text-xs text-muted-foreground">
        <span className="min-w-0 flex-1 truncate">{file.path}</span><DiffStat added={file.added} removed={file.removed} />
      </div>}
      <pre className="m-0 max-h-80 overflow-auto py-1 font-mono text-xs leading-5 scrollbar-jarvis">
        {file.lines.map((line, i) => line.kind === "gap"
          ? <div key={i} className="px-3 text-muted-foreground">⋯</div>
          : <div key={i} className={cn("whitespace-pre px-3", line.kind === "add" && "diff-line-add", line.kind === "del" && "diff-line-del")}>
            <span aria-hidden className="mr-2 select-none opacity-60">{line.kind === "add" ? "+" : line.kind === "del" ? "-" : " "}</span>{line.text}
          </div>)}
        {file.truncated > 0 && <div className="px-3 text-muted-foreground">… {file.truncated} more lines</div>}
      </pre>
    </div>)}
  </div>;
}

function inputText(input: unknown): string {
  if (input == null) return "";
  if (typeof input === "string") return input;
  try { return JSON.stringify(input, null, 2); } catch { return String(input); }
}

/** Pictures a tool call brought back, by call id, and the text blocks that carried them. */
interface CallPictures {
  byCall: ReadonlyMap<string, string[]>;
  moved: ReadonlySet<string>;
}

const CallMedia = createContext<ReadonlyMap<string, string[]>>(new Map());

/**
 * The server posts each picture a tool returned (an image the agent viewed)
 * as its own `media-…` text right after that call. In a thread the picture
 * belongs to the call: it shows once the call's line is opened, never in the
 * answer. A picture after the agent's own prose stays where it is.
 */
export function callPictures(blocks: TurnBlock[]): CallPictures {
  const byCall = new Map<string, string[]>();
  const moved = new Set<string>();
  let call: string | null = null;
  for (const block of blocks) {
    if (block.kind === "tool") call = block.callId;
    else if (block.kind === "text" && block.id.startsWith("media-") && call) {
      byCall.set(call, [...(byCall.get(call) ?? []), block.text]);
      moved.add(block.id);
    } else if (block.kind === "text") call = null;
  }
  return { byCall, moved };
}

/** What a call opened to: its pictures, the diff it made, else what ran and what came back. */
function CallDetails({ call, className = "mb-1.5 mt-0.5" }: { call: Call; className?: string }) {
  const t = useT();
  const block = call.block;
  const pictures = useContext(CallMedia).get(block.callId);
  const diff = useMemo(() => toolDiff(block.name, block.input, block.output), [block.name, block.input, block.output]);
  const output = readableOutput(block).trim();
  if (pictures?.length) {
    return <div className={cn(className, PROSE, THREAD_MEDIA)}>
      {pictures.map((text, index) => <ChatMarkdown key={index} text={text} />)}
    </div>;
  }
  if (diff && diff.length > 0 && !block.isError) return <div className={className}><DiffView files={diff} /></div>;
  const input = call.kind === "command" ? "" : inputText(block.input);
  return <div className={cn(className, "space-y-1.5 select-text")}>
    {call.kind === "command" && <pre className="m-0 max-h-24 overflow-y-auto whitespace-pre-wrap rounded-lg bg-secondary px-3 py-2 font-mono text-xs leading-5 text-foreground [overflow-wrap:anywhere] scrollbar-jarvis">$ {inputText((block.input as Record<string, unknown> | null)?.command ?? call.text)}</pre>}
    {input && input !== "{}" && <pre className="m-0 max-h-48 overflow-auto rounded-lg bg-secondary px-3 py-2 font-mono text-xs leading-5 text-muted-foreground scrollbar-jarvis">{input}</pre>}
    {output
      ? <pre className={cn("m-0 max-h-40 overflow-auto whitespace-pre-wrap rounded-lg border border-border px-3 py-2 font-mono text-xs leading-5 [overflow-wrap:anywhere] scrollbar-jarvis", block.isError ? "text-destructive" : "text-foreground-secondary")}>{output}</pre>
      : block.output === null ? null : <p className="text-xs text-muted-foreground">{t("thread_turn.no_output")}</p>}
  </div>;
}

/** What a call's line says after its words: why it failed, or that it was cut off. */
function callTail(call: Call, t: (key: string) => string): string {
  return isFailed(call) && call.reason ? call.reason : call.status === "interrupted" ? t("thread_turn.interrupted") : "";
}

/** The kinds of call a line of the thread names by what they were ("Ran a command", "Read a file"). */
const PLAIN_KINDS: ReadonlySet<string> = new Set(["command", "read", "list", "search", "edit", "write", "image"]);

/** A lone call as its line says it: what it was. What it acted on is one click away, in its row. */
function callWords(call: Call, t: (key: string) => string): string {
  return PLAIN_KINDS.has(call.kind) ? capitalize(tr(t, `act.${call.kind}_one`)) : call.text;
}

const THOUGHT_PROSE = cn(PROSE, "text-foreground-secondary dark:text-foreground-secondary prose-p:text-foreground-secondary prose-li:text-foreground-secondary");

/** A thought longer than this shows its first lines and opens to the rest. */
export const THOUGHT_PREVIEW = 320;

/**
 * A thought the agent put into words, read as prose between its work: what
 * it is looking at and why, a step quieter than the answer. A short thought
 * stands whole; a long one shows its first three lines and opens to the rest.
 */
function ThoughtView({ text }: { text: string }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const plain = useMemo(() => flattenMarks(text), [text]);
  const long = plain.length > THOUGHT_PREVIEW;
  return <div className="min-w-0" data-testid="thread-thought">
    {long && !open
      ? <p className="m-0 line-clamp-3 py-1 text-base leading-6 text-foreground-secondary [overflow-wrap:anywhere]">{plain}</p>
      : <div className={cn(THOUGHT_PROSE, "select-text")}><ChatMarkdown text={text} /></div>}
    {long && <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}
      className="rounded-sm text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      {t(open ? "trace_report.show_less" : "trace_report.show_more")}
    </button>}
  </div>;
}

/**
 * A picture in the agent's words — an image it viewed or made — reads as a
 * small preview in the thread; a click opens it full size.
 */
export const THREAD_MEDIA = "[&_[data-kind=image]_img]:max-h-48 [&_[data-kind=image]_img]:max-w-sm [&_[data-kind=image]_img]:border [&_[data-kind=image]_img]:border-border";

const CARD_ROW = "group/step flex w-full min-w-0 items-center gap-1.5 px-3.5 py-2 text-left text-sm leading-6 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring";

/**
 * One row of an opened stretch's card: what the step was in the quiet tone,
 * what it acted on a step brighter, then the chevron right after the words.
 * A row with something behind it opens in place.
 */
function CardRow({ label, openLabel, detail, mono = false, trailing, live = false, ariaLabel, testId, startOpen = false, children }: {
  label: ReactNode;
  /** What the row reads while open, when what it opens to already says the label. */
  openLabel?: ReactNode;
  detail?: ReactNode; mono?: boolean; trailing?: ReactNode; live?: boolean;
  ariaLabel?: string; testId?: string;
  /** The row is the only one of its card and what it opens to is the point (a picture). */
  startOpen?: boolean;
  children?: ReactNode;
}) {
  const [open, setOpen] = useState(startOpen);
  const words = <>
    <span className={cn("truncate text-muted-foreground transition-colors", detail ? "shrink-0" : "min-w-0",
      children && !live && "group-hover/step:text-foreground", live && "live-tool-shine")}>{open && openLabel ? openLabel : label}</span>
    {detail && <span className={cn("min-w-0 truncate text-foreground-secondary", mono && "font-mono text-[13px]")}>{detail}</span>}
    {trailing}
    {children && <ChevronRight aria-hidden className={cn("h-3.5 w-3.5 shrink-0 text-muted-foreground opacity-60 transition duration-200 group-hover/step:opacity-100", open && "rotate-90")} />}
  </>;
  return <div className="min-w-0" data-testid={testId}>
    {children
      ? <button type="button" aria-expanded={open} aria-label={ariaLabel} onClick={() => setOpen(!open)} className={CARD_ROW}>{words}</button>
      : <div className={CARD_ROW}>{words}</div>}
    {open && children}
  </div>;
}

function CardStep({ item, running, lone = false }: { item: StretchItem; running: boolean; lone?: boolean }) {
  const t = useT();
  if (item.kind === "thought") return running ? <CardRow label={t("thread_turn.thinking")} live /> : null;
  const call = item.call;
  const failed = isFailed(call);
  const command = call.kind === "command";
  const tail = callTail(call, t);
  return <CardRow
    // A command reads as what it was, then the line itself in the terminal's type.
    label={command ? capitalize(tr(t, "act.command_one")) : call.text}
    detail={command ? call.text : call.detail || call.result}
    mono={command}
    live={call.status === "running"}
    startOpen={lone && call.kind === "image"}
    ariaLabel={failed ? fill(t("thread_turn.call_failed"), { call: call.text }) : undefined}
    trailing={<>
      {tail && <span className="min-w-0 truncate text-muted-foreground/70">— {tail}</span>}
      <DiffStat added={call.added} removed={call.removed} />
      {failed && <X aria-hidden className="h-3 w-3 shrink-0 text-destructive/70" />}
    </>}>
    <CallDetails call={call} className="px-3.5 pb-3" />
  </CardRow>;
}

/**
 * The calls between two pieces of the agent's prose, as one line: what they
 * did, with a chevron. The line stays closed until the reader opens it; while
 * the turn works in it, it carries the live shine. Opened, it shows a card
 * with one row per step — a lone call too, so every line opens the same way
 * and a command's output never lands in the thread unasked.
 */
function StretchView({ stretch, running }: { stretch: Stretch; running: boolean }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const calls = stretch.items.flatMap((item) => item.kind === "call" ? [item.call] : []);
  // Only the wordless thought of a running turn: one live line, nothing to open.
  if (calls.length === 0) return running ? <WorkRow label={t("thread_turn.thinking")} live /> : null;
  const label = calls.length === 1 ? callWords(calls[0], t) : stretch.label;
  const failed = calls.length === 1 && isFailed(calls[0]);
  return <WorkRow
    label={label}
    ariaLabel={stretch.live ? fill(t("thread_turn.steps_so_far"), { summary: label, count: stretch.items.length })
      : failed ? fill(t("thread_turn.call_failed"), { call: calls[0].text }) : undefined}
    trailing={<>
      <DiffStat added={stretch.added} removed={stretch.removed} />
      {failed && <X aria-hidden className="h-3 w-3 shrink-0 text-destructive/70" />}
    </>}
    stamp={stretch.startedMs}
    live={stretch.live}
    expanded={open}
    onToggle={() => setOpen(!open)}>
    <div role="region" aria-label={t("thread_turn.steps")} data-testid="thread-steps"
      className="mb-2 mt-0.5 divide-y divide-border overflow-hidden rounded-xl border border-border">
      {stretch.items.map((item) => <CardStep key={item.id} item={item} running={running} lone={stretch.items.length === 1} />)}
    </div>
  </WorkRow>;
}

/**
 * The running turn's clock. It writes its own text once a second, so the
 * timeline never re-renders to tick.
 */
function Elapsed({ since }: { since: number }) {
  const ref = useRef<HTMLSpanElement | null>(null);
  useEffect(() => {
    const tick = () => { if (ref.current) ref.current.textContent = traceDuration(Math.max(0, Date.now() - since)); };
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [since]);
  return <span ref={ref} className="tabular-nums">{traceDuration(Math.max(0, Date.now() - since))}</span>;
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [done, setDone] = useState(false);
  return <button type="button" aria-label={label} title={label}
    onClick={() => { void robustCopy(text).then(() => { setDone(true); window.setTimeout(() => setDone(false), 1200); }); }}
    className="rounded p-1 text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
    {done ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
  </button>;
}

function clock(ms: number): string {
  return new Date(ms).toLocaleTimeString(localeForUiLanguage(useI18nStore.getState().ui), { hour: "2-digit", minute: "2-digit" });
}

function UserBubble({ item }: { item: UserItem }) {
  const t = useT();
  return <div className="group flex flex-col items-end gap-1" data-testid="thread-user-message">
    {item.author && <div className="flex items-center gap-1.5 pr-1 text-xs text-muted-foreground" data-testid="thread-message-author">
      <Bot aria-hidden className="h-3.5 w-3.5 shrink-0" />
      <span className="truncate">{t("society.chat.coding_thread_author").replace("{0}", item.author.name)}</span>
    </div>}
    <div className="max-w-[80%] rounded-2xl bg-secondary px-4 py-2.5 text-foreground">
      {item.attachments.length > 0 && <div className="mb-2 flex flex-wrap justify-end gap-2">
        {item.attachments.map((file) => file.url && file.kind === "image"
          ? <img key={file.name} src={file.url} alt={file.name} className="h-24 max-w-[200px] rounded-lg border border-border object-cover" />
          : <span key={file.name} className="inline-flex max-w-[240px] items-center gap-1.5 rounded-md border border-border bg-background/60 px-2 py-1 text-xs text-muted-foreground">
            <FileText aria-hidden className="h-3.5 w-3.5 shrink-0" /><span className="truncate">{file.name}</span>
          </span>)}
      </div>}
      {item.text && <div className="whitespace-pre-wrap text-base leading-6 [overflow-wrap:anywhere]">{item.text}</div>}
    </div>
    <div className="flex items-center gap-1 pr-1 text-xs text-muted-foreground opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100 [@media(hover:none)]:opacity-100">
      <span className="tabular-nums">{clock(item.tsMs)}</span>
      {item.text && <CopyButton text={item.text} label={t("ide_threads.copy_message")} />}
    </div>
  </div>;
}

/** Every file the turn's edits touched, with the size of the change. */
function changedFiles(turn: TurnItem): { path: string; added: number; removed: number; files: DiffFile[] }[] {
  const byPath = new Map<string, { path: string; added: number; removed: number; files: DiffFile[] }>();
  for (const block of turn.blocks) {
    if (block.kind !== "tool" || block.isError || block.output === null) continue;
    for (const file of toolDiff(block.name, block.input, block.output) ?? []) {
      if (!file.path) continue;
      const row = byPath.get(file.path) ?? { path: file.path, added: 0, removed: 0, files: [] };
      row.added += file.added;
      row.removed += file.removed;
      row.files.push(file);
      byPath.set(file.path, row);
    }
  }
  return [...byPath.values()];
}

/** The thread's project folder, so changed files read relative to it. */
export const ThreadFolder = createContext("");

function slashes(path: string): string {
  return path.replace(/\\/g, "/");
}

/**
 * A changed file as the project sees it: relative to the thread's folder,
 * else (an absolute path elsewhere) its last three parts.
 */
export function projectPath(path: string, root: string): string {
  const clean = slashes(path);
  const base = slashes(root).replace(/\/+$/, "");
  if (base && clean.toLowerCase().startsWith(`${base.toLowerCase()}/`)) return clean.slice(base.length + 1);
  const absolute = clean.startsWith("/") || /^[A-Za-z]:\//.test(clean);
  const parts = clean.split("/").filter(Boolean);
  return absolute && parts.length > 3 ? `…/${parts.slice(-3).join("/")}` : clean;
}

/** A path split into its folder (read quieter) and its file name. */
function splitPath(path: string): { folder: string; name: string } {
  const clean = slashes(path);
  const cut = clean.lastIndexOf("/");
  return cut < 0 ? { folder: "", name: clean } : { folder: clean.slice(0, cut + 1), name: clean.slice(cut + 1) };
}

/** How many files a finished turn lists before the rest fold behind "Show N more files". */
export const CHANGED_FILES_FOLDED = 3;

/** Both counts, even a zero — the card's columns line up on them. */
function ChangeCount({ added, removed, className }: { added: number; removed: number; className?: string }) {
  return <span className={cn("shrink-0 tabular-nums", className)}>
    <span className="text-success">+{added}</span> <span className="text-destructive">-{removed}</span>
  </span>;
}

/**
 * The card under a finished turn: how many files it edited and by how much,
 * then one row per file — folder quiet, name bright, counts on the right.
 * Only the first few rows show; the rest fold behind "Show N more files" so
 * a big turn never fills the screen. A row opens to its own diff, and
 * "Show changes" opens every diff at once.
 */
export function ChangedFiles({ turn }: { turn: TurnItem }) {
  const t = useT();
  const lang = t("trace_report.locale");
  const root = useContext(ThreadFolder);
  const rows = useMemo(() => changedFiles(turn), [turn]);
  const [openPaths, setOpenPaths] = useState<ReadonlySet<string>>(() => new Set());
  const [expanded, setExpanded] = useState(false);
  if (rows.length === 0) return null;
  const added = rows.reduce((sum, row) => sum + row.added, 0);
  const removed = rows.reduce((sum, row) => sum + row.removed, 0);
  const hidden = Math.max(0, rows.length - CHANGED_FILES_FOLDED);
  const shown = expanded ? rows : rows.slice(0, CHANGED_FILES_FOLDED);
  const allOpen = rows.every((row) => openPaths.has(row.path));
  const togglePath = (path: string) => setOpenPaths((prev) => {
    const next = new Set(prev);
    if (next.has(path)) next.delete(path); else next.add(path);
    return next;
  });
  const toggleAll = () => {
    if (allOpen) { setOpenPaths(new Set()); return; }
    setOpenPaths(new Set(rows.map((row) => row.path)));
    setExpanded(true);
  };
  const title = fill(t(`thread_turn.files_changed_${plural(lang, rows.length)}`), { count: rows.length });
  return <section aria-label={t("thread_turn.changed_files")} data-testid="thread-changed-files" className="mt-3 overflow-hidden rounded-xl border border-border bg-card">
    <div className="flex items-center gap-3 border-b border-border px-3 py-3">
      <span aria-hidden className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-secondary text-foreground-secondary">
        <span className="flex h-5 w-5 items-center justify-center rounded-[5px] border-[1.5px] border-current"><Diff className="h-3 w-3" strokeWidth={2.25} /></span>
      </span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-semibold text-foreground-strong">{title}</div>
        <ChangeCount added={added} removed={removed} className="text-sm" />
      </div>
      <button type="button" aria-pressed={allOpen} onClick={toggleAll}
        className="shrink-0 rounded-lg border border-border bg-background px-3 py-1.5 text-sm text-foreground hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        {t(allOpen ? "thread_turn.hide_changes" : "thread_turn.show_changes")}
      </button>
    </div>
    <ul>
      {shown.map((row) => {
        const { folder, name } = splitPath(projectPath(row.path, root));
        const open = openPaths.has(row.path);
        return <li key={row.path}>
          <button type="button" aria-expanded={open} onClick={() => togglePath(row.path)} title={row.path}
            className="flex w-full items-center gap-3 px-3 py-1.5 text-left text-sm hover:bg-secondary/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring">
            {/* The folder gives way first, cut from its left, so the name stays readable. */}
            <span className="flex min-w-0 flex-1">
              {folder && <span dir="rtl" className="min-w-0 shrink-[999] truncate text-left text-muted-foreground">
                <bdi dir="ltr">{folder}</bdi>
              </span>}
              <span className="min-w-0 max-w-full shrink-0 truncate text-foreground">{name}</span>
            </span>
            <ChangeCount added={row.added} removed={row.removed} />
          </button>
          {open && <div className="px-3 pb-2 pt-0.5"><DiffView files={row.files.map((file) => ({ ...file, path: "" }))} /></div>}
        </li>;
      })}
    </ul>
    {hidden > 0 && <button type="button" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}
      className="flex w-full items-center gap-1.5 px-3 py-2 text-left text-sm text-foreground-secondary hover:bg-secondary/60 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring">
      {expanded ? t("thread_turn.collapse_files") : fill(t(`thread_turn.more_files_${plural(lang, hidden)}`), { count: hidden })}
      <ChevronDown aria-hidden className={cn("h-4 w-4 transition-transform duration-200", expanded && "rotate-180")} />
    </button>}
  </section>;
}

function answerText(turn: TurnItem): string {
  return turn.blocks.filter((block): block is TextBlock => block.kind === "text" && !block.id.startsWith(STEER_PREFIX)).map((block) => block.text.trim()).filter(Boolean).join("\n\n");
}

/** How a surface answers an approval: by its id, the person's decision and where an "always" lives. */
export type Decide = ApprovalDecide;

/** A call still waiting for the person: an open question or an undecided approval. */
function waitsForPerson(block: ToolBlock): boolean {
  return waitsOnCard(block) || Boolean(block.approval && block.approval.decision === null);
}

function pendingLabel(block: ToolBlock, t: (key: string) => string): { icon: ReactNode; text: string } | null {
  if (block.question && !block.question.closed) return { icon: <MessageCircleQuestion className="h-3.5 w-3.5" />, text: t("thread_turn.waiting_answer") };
  if (block.approval && block.approval.decision === null) {
    return { icon: <ShieldAlert className="h-3.5 w-3.5" />, text: fill(t("thread_turn.waiting_approval"), { summary: block.approval.summary || block.name }) };
  }
  return null;
}

/**
 * An approval answered in the turn itself, on the shared action card: what
 * the agent asks for in plain words, with "Allow once" first.
 */
export function ApprovalPrompt({ block, onDecide }: { block: ToolBlock; onDecide?: Decide }) {
  return <ApprovalActionCard block={block} onDecide={onDecide} />;
}

/**
 * A finished turn read the short way: its steps and thoughts fold behind one
 * "Worked for …" line, and the answer stays in view.
 *
 * The answer is the last run of prose. A thought or a step that arrives after
 * those words (a thinking snapshot landing once the text is already on screen)
 * must not pull the answer into the fold. Prose written before an earlier
 * step stays with the work. A turn with no step at all has nothing to fold.
 * A card the turn ended on is no step: it stays with the answer it belongs to.
 */
/**
 * Rows with each run of sub-agents spawned one after another drawn as one
 * line of the thread ("Ran 3 sub-agents"), a lone sub-agent too, so a batch
 * of agents reads like any other step instead of burying the conversation.
 */
export function joinAgentRuns(rows: readonly ThreadRow[]): (ThreadRow | { kind: "agents"; id: string; blocks: ToolBlock[] })[] {
  const out: (ThreadRow | { kind: "agents"; id: string; blocks: ToolBlock[] })[] = [];
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i];
    if (row.kind !== "agent") { out.push(row); continue; }
    let j = i;
    while (j + 1 < rows.length && rows[j + 1].kind === "agent") j++;
    const run = rows.slice(i, j + 1) as Extract<ThreadRow, { kind: "agent" }>[];
    out.push({ kind: "agents", id: `agents:${row.id}`, blocks: run.map((entry) => entry.block) });
    i = j;
  }
  return out;
}

/** The person's own message sent into the running turn, drawn between the agent's steps. */
function isSteerRow(row: ThreadRow): boolean {
  return row.kind === "text" && row.block.id.startsWith(STEER_PREFIX);
}

export function foldFinished(rows: ThreadRow[]): { work: ThreadRow[]; answer: ThreadRow[] } {
  let lastStep = -1;
  let lastText = -1;
  rows.forEach((row, index) => {
    if (row.kind === "work" || row.kind === "thought") lastStep = index;
    if (row.kind === "text" && !isSteerRow(row)) lastText = index;
  });
  // No prose yet, or the prose already follows every step.
  if (lastText < 0 || lastText > lastStep) {
    return { work: rows.slice(0, lastStep + 1), answer: rows.slice(lastStep + 1) };
  }
  let start = lastText;
  while (start > 0 && rows[start - 1].kind === "text" && !isSteerRow(rows[start - 1])) start -= 1;
  return {
    work: rows.filter((_, index) => index < start || index > lastText),
    answer: rows.slice(start, lastText + 1),
  };
}

/** "Working for 12s" with the ticking clock in place of the duration. */
function WorkingFor({ since }: { since: number }) {
  const t = useT();
  const [before, after = ""] = t("thread_turn.working_for").split("{duration}");
  return <>{before}<Elapsed since={since} />{after}</>;
}

/**
 * The live line of a turn whose agent ended its message and waits for its own
 * background tasks: a quiet heading with the clock, then one line per task
 * under a thin rail, so a long task name never runs into the next one.
 */
function BackgroundWait({ tasks, since }: { tasks: readonly string[]; since: number }) {
  const t = useT();
  const lang = t("trace_report.locale");
  return <div className="min-w-0 text-sm text-muted-foreground" data-testid="thread-working">
    <div className="flex h-6 min-w-0 items-center gap-2" data-testid="thread-waiting-background">
      <span aria-hidden className="relative flex h-1.5 w-1.5 shrink-0">
        <span className="absolute inline-flex h-full w-full rounded-full bg-primary/60 motion-safe:animate-ping" />
        <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-primary/80" />
      </span>
      <span className="live-tool-shine truncate">{fill(t(`thread_turn.waiting_background_${plural(lang, tasks.length)}`), { count: tasks.length })}</span>
      <span aria-hidden className="text-muted-foreground/50">·</span>
      <span className="shrink-0 text-muted-foreground/80"><Elapsed since={since} /></span>
    </div>
    <ul className="ml-[2.5px] mt-0.5 space-y-0.5 border-l border-border/70 pl-3.5" data-testid="thread-waiting-tasks">
      {tasks.map((task, index) => <li key={`${index}:${task}`} className="truncate text-[13px] leading-5 text-muted-foreground/90" title={task}>{task}</li>)}
    </ul>
  </div>;
}

export interface ThreadTurnProps {
  turn: TurnItem;
  /**
   * Where the person answers a waiting call. A thread answers in its
   * composer, so the turn only says it waits; an agent chat ("inline") draws
   * the question card and the approval buttons in the turn itself.
   */
  prompts?: "composer" | "inline";
  onDecide?: Decide;
  /**
   * Steps that belong to this turn's work without being blocks of it (a
   * memory receipt posted after the turn). They sit with the work, above the
   * answer, and fold with it.
   */
  extras?: { key: string; node: ReactNode }[];
  /** A quiet note on a finished turn's closing line: tokens, cost. */
  receipt?: ReactNode;
  /**
   * How the turn reads. A coding thread counts its work ("Working for 12s",
   * "Worked for 40s"). A plain chat has a thought and an answer: the thought
   * streams under a shimmering "Thinking" and folds into "Thought for 3s"
   * once the answer begins (`ChatThought`), and no duration sits under the
   * answer.
   */
  tone?: "work" | "chat";
}

/**
 * One turn of a conversation the way a thread reads it. The Agentic IDE's
 * threads and every agent chat draw their turns with it, so a turn looks and
 * behaves the same wherever it is read — streaming, finished or reloaded.
 */
export const ThreadTurn = memo(function ThreadTurn({ turn, prompts = "composer", onDecide, extras, receipt, tone = "work" }: ThreadTurnProps) {
  const t = useT();
  const lang = t("trace_report.locale");
  const running = turn.status === "running";
  const inline = prompts === "inline";
  const pictures = useMemo(() => callPictures(turn.blocks), [turn.blocks]);
  // Keep credential fields mounted while the surrounding work folds at turn end.
  // The pasted value lives only in the field, so a remount would discard it.
  const credentials = turn.blocks.filter((block): block is ToolBlock => block.kind === "tool" && Boolean(block.credential));
  const rows = useMemo(
    () => buildThreadRows(turn.blocks, { t, lang, status: turn.status }).filter((row) =>
      !(row.kind === "text" && pictures.moved.has(row.block.id)) && !(row.kind === "pending" && row.block.credential)),
    [turn.blocks, t, lang, turn.status, pictures],
  );
  const answer = answerText(turn);
  const [workOpen, setWorkOpen] = useState(false);
  // Finished: every step and thought folds behind one "Worked for …" line; the answer stays.
  const { work, answer: tail } = useMemo(() => (running ? { work: rows, answer: [] } : foldFinished(rows)), [rows, running]);
  // The sub-agents it spawned stay in view under the fold: each opens its own conversation.
  const agents = useMemo(() => work.filter((row) => row.kind === "agent"), [work]);
  // What the person told it mid-turn stays in view under the fold too.
  const steers = useMemo(() => work.filter(isSteerRow), [work]);
  // A call that still waits for the person never folds away.
  const waiting = useMemo(() => work.filter((row) => row.kind === "pending" && waitsForPerson(row.block)), [work]);
  const agentsWorking = useMemo(() => running ? listSubagents([turn]).filter((entry) => entry.status === "running").length : 0, [turn, running]);
  // The agent ended its message and waits for its background tasks: the answer
  // above reads finished, so the live line says what it still waits for.
  const waitingOn = running ? turn.waitingOn ?? [] : [];
  const extraRows = extras ?? [];
  const folded = !running && (work.length > 0 || extraRows.length > 0);
  const duration = turn.durationMs != null ? traceDuration(turn.durationMs) : "";
  const timed = (key: string) => duration ? fill(t(`thread_turn.${key}_after`), { duration }) : t(`thread_turn.${key}`);
  const workedFor = duration ? fill(t("thread_turn.worked_for"), { duration }) : "";
  const foldLabel = turn.status === "cancelled" ? timed("stopped")
    : turn.status === "error" ? timed("failed")
      : workedFor || t("thread_turn.worked");
  const closing = turn.status === "cancelled" ? timed("stopped")
    : turn.status === "error" ? timed("failed")
      : answer ? workedFor : timed("no_answer");
  const renderRows = (list: readonly ThreadRow[]) => joinStretches(joinAgentRuns(list), { running }).map((row) =>
    row.kind === "stretch" ? <StretchView key={row.id} stretch={row} running={running} />
      : row.kind === "agents" ? <SubagentRun key={row.id} blocks={row.blocks} turn={turn} /> : renderRow(row));
  const renderRow = (row: ThreadRow) => {
    // Work is drawn as stretches (renderRows), never as a row of its own.
    if (row.kind === "work") return null;
    if (row.kind === "thought") return <ThoughtView key={row.id} text={row.text} />;
    if (isSteerRow(row)) return <div key={row.id} className="flex justify-end" data-testid="thread-steer-message">
      <div className="max-w-[80%] whitespace-pre-wrap rounded-2xl bg-secondary px-4 py-2.5 text-base leading-6 text-foreground [overflow-wrap:anywhere]">{(row as { text: string }).text}</div>
    </div>;
    if (row.kind === "text") return <div key={row.id} className={cn(PROSE, THREAD_MEDIA)}><ChatMarkdown text={row.text} /></div>;
    if (row.kind === "agent") return <SubagentRun key={row.id} blocks={[row.block]} turn={turn} />;
    // A secret is pasted where it is asked for, never into a composer.
    if (row.block.credential) return <CredentialCard key={row.id} credential={row.block.credential} />;
    if (inline) {
      if (row.block.question) return <QuestionCard key={row.id} question={row.block.question} />;
      if (row.block.approval && row.block.approval.decision === null) return <ApprovalPrompt key={row.id} block={row.block} onDecide={onDecide} />;
      return null;
    }
    const pending = pendingLabel(row.block, t);
    return pending ? <WorkRow key={row.id} icon={pending.icon} label={pending.text} live /> : null;
  };
  if (tone === "chat") {
    // A plain chat: its thought, its answer, and a quiet closing line.
    const textRows = rows.filter((row) => row.kind === "text");
    const ending = turn.status === "cancelled" ? timed("stopped")
      : turn.status === "error" ? timed("failed")
        : !answer ? timed("no_answer") : "";
    return <CallMedia.Provider value={pictures.byCall}><div className="min-w-0 space-y-1.5" data-testid="thread-turn" data-status={turn.status}>
      <ChatThought turn={turn} answering={textRows.length > 0} />
      {textRows.map(renderRow)}
      {!running && <>
        {turn.status === "error" && turn.error && <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">{turnErrorText(turn.error, t)}</p>}
        <div className="flex items-center gap-1.5 pt-1 text-xs text-muted-foreground" data-testid="thread-turn-closing">
          {ending && <span>{ending}</span>}
          {answer && <CopyButton text={answer} label={t("thread_turn.copy_answer")} />}
        </div>
      </>}
    </div></CallMedia.Provider>;
  }
  const extraNodes = extraRows.map((extra) => <div key={`extra:${extra.key}`} className="min-w-0">{extra.node}</div>);
  // A running turn's streaming answer is its tail; extra steps go above it.
  const shown = folded ? tail : rows;
  let extraAt = shown.length;
  if (!folded) while (extraAt > 0 && shown[extraAt - 1].kind === "text") extraAt--;
  return <CallMedia.Provider value={pictures.byCall}><div className="min-w-0 space-y-1.5" data-testid="thread-turn" data-status={turn.status}>
    {folded && <div>
      <button type="button" aria-expanded={workOpen} onClick={() => setWorkOpen((value) => !value)} data-testid="thread-worked-for"
        className="flex h-7 items-center gap-1 rounded-md px-1 text-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <span className="tabular-nums">{foldLabel}</span>
        <ChevronRight aria-hidden className={cn("h-3.5 w-3.5 transition-transform duration-150", workOpen && "rotate-90")} />
      </button>
      {workOpen && <div className="space-y-1.5 pb-2 pt-1" data-testid="thread-worked-steps">
        {renderRows(work.filter((row) => row.kind !== "agent" && !isSteerRow(row) && !waiting.includes(row)))}
        {extraNodes}
      </div>}
      <div aria-hidden className="mt-1 border-b border-border/70" />
    </div>}
    {folded && agents.length > 0 && <div className="space-y-1.5 pt-1" data-testid="thread-turn-subagents">{renderRows(agents)}</div>}
    {folded && steers.map(renderRow)}
    {folded && waiting.map(renderRow)}
    {credentials.map((block) => <CredentialCard key={block.credential!.requestId} credential={block.credential!} />)}
    {renderRows(shown.slice(0, extraAt))}
    {!folded && extraNodes}
    {renderRows(shown.slice(extraAt))}
    {running
      ? waitingOn.length > 0
        ? <BackgroundWait tasks={waitingOn} since={turn.startedMs} />
        : <div className="flex h-6 min-w-0 items-center text-sm leading-relaxed text-muted-foreground" data-testid="thread-working">
          <span className="whitespace-nowrap"><WorkingFor since={turn.startedMs} />
            {agentsWorking > 0 && <> · {fill(t(`thread_turn.subagents_working_${plural(lang, agentsWorking)}`), { count: agentsWorking })}</>}</span>
        </div>
      : <>
        {turn.status === "error" && turn.error && <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">{turnErrorText(turn.error, t)}</p>}
        <ChangedFiles turn={turn} />
        <div className="flex items-center gap-1.5 pt-1 text-xs text-muted-foreground" data-testid="thread-turn-closing">
          {!folded && closing && <span>{closing}</span>}
          {folded && !answer && <span>{t("thread_turn.no_answer")}</span>}
          {receipt && <span className="inline-flex items-center gap-1.5 tabular-nums">
            {((!folded && closing) || (folded && !answer)) && <span aria-hidden className="text-muted-foreground/50">·</span>}
            {receipt}
          </span>}
          {answer && <CopyButton text={answer} label={t("thread_turn.copy_answer")} />}
        </div>
      </>}
  </div></CallMedia.Provider>;
});

function ErrorLine({ text }: { text: string }) {
  return <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">{text}</p>;
}

/** One item of the conversation, drawn by its kind. */
function ItemView({ item, tone }: { item: TimelineItem } & Pick<ThreadTurnProps, "tone">) {
  if (item.type === "user") return <UserBubble item={item} />;
  if (item.type === "turn") return <ThreadTurn turn={item} tone={tone} />;
  if (item.type === "error") return <ErrorLine text={item.text} />;
  if (item.type === "notice") {
    return <p className="text-center text-xs text-muted-foreground">{item.agentName ? `${item.agentName}: ` : ""}{item.text}</p>;
  }
  return <div className="rounded-xl border border-border px-3 py-2 text-sm">
    <p className="mb-1 text-xs text-muted-foreground">Message from {item.message.sender_name}</p>
    <div className={PROSE}><ChatMarkdown text={item.message.text} /></div>
  </div>;
}

/**
 * The scrolling column. It follows the newest line while the reader is at
 * the bottom and stays put once they scroll up to read; a button brings them
 * back down.
 */
export function ThreadTimeline({ items, sessionId, bottomInset, folder = "", lead, tone }: {
  items: TimelineItem[]; sessionId: string | null; bottomInset: number;
  /** How every turn's status lines read (see `ThreadTurnProps.tone`). */
  tone?: ThreadTurnProps["tone"];
  /** The thread's project folder; changed files list relative to it. */
  folder?: string;
  /** What reads above the conversation — an opened sub-agent's header and task. */
  lead?: ReactNode;
}) {
  const t = useT();
  const scroller = useRef<HTMLDivElement | null>(null);
  const pinned = useRef(true);
  const [away, setAway] = useState(false);

  // A newly opened thread starts at its newest message.
  useLayoutEffect(() => {
    pinned.current = true;
    setAway(false);
    const box = scroller.current;
    if (box) box.scrollTop = box.scrollHeight;
  }, [sessionId]);

  useLayoutEffect(() => {
    const box = scroller.current;
    if (box && pinned.current) box.scrollTop = box.scrollHeight;
  });

  useEffect(() => {
    const box = scroller.current;
    if (!box || typeof ResizeObserver === "undefined") return;
    // Content that grows without a re-render (an image loading) keeps the pin too.
    const observer = new ResizeObserver(() => { if (pinned.current) box.scrollTop = box.scrollHeight; });
    const content = box.firstElementChild;
    if (content) observer.observe(content);
    return () => observer.disconnect();
  }, []);

  return <ThreadFolder.Provider value={folder}><div className="relative min-h-0 flex-1">
    <div ref={scroller} data-testid="thread-timeline"
      onScroll={(event) => {
        const box = event.currentTarget;
        const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 48;
        pinned.current = atBottom;
        setAway(!atBottom);
      }}
      className="h-full overflow-y-auto scrollbar-jarvis">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-5 px-5 pt-6" style={{ paddingBottom: bottomInset + 24 }}>
        {lead}
        {items.map((item) => <ItemView key={item.id} item={item} tone={tone} />)}
      </div>
    </div>
    {away && <button type="button" aria-label={t("ide_threads.scroll_newest")}
      onClick={() => { const box = scroller.current; if (box) box.scrollTo({ top: box.scrollHeight, behavior: "smooth" }); }}
      style={{ bottom: bottomInset + 12 }}
      className="absolute left-1/2 z-10 flex h-8 w-8 -translate-x-1/2 items-center justify-center rounded-full border border-border bg-popover text-muted-foreground shadow-float hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      <ArrowDown className="h-4 w-4" />
    </button>}
  </div></ThreadFolder.Provider>;
}
