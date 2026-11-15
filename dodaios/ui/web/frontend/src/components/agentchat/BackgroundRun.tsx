import { Fragment, useId, useState } from "react";
import { Clock3, Feather } from "lucide-react";

import { AgentSwatch } from "@/components/society/AgentSwatch";
import { MemoryNoticeViewer, memoryNoticePath, memoryNoticeTitle } from "@/components/society/chat/MemoryUpdateNotice";
import type { RoutineChatTarget } from "@/components/society/chat/routineExecution";
import { useRoutineNavigation } from "@/components/society/chat/routineNavigation";
import { useT } from "@/i18n";
import { societyResultText } from "@/lib/skipReasons";
import { cn } from "@/lib/utils";

import { ChatMarkdown } from "./ChatMarkdown";
import type { RunFace } from "./InternalMessageRun";
import type { BackgroundRunItem } from "./backgroundLine";
import type { NoticeItem } from "./reduce";

type T = ReturnType<typeof useT>;
type Faces = Record<string, RunFace> | undefined;

/** The lead's roster id: its notices are the assistant's own. */
const LEAD_ID = "jarvis";
/** Notice kinds that carry another agent's report, whoever sent them. */
const REPORT_KINDS: ReadonlySet<string> = new Set(["society_result", "delegation_report", "society_message"]);
/** A one-line notice longer than this unfolds to show it whole (the line cuts it short). */
const LONG_SUBJECT = 80;
const NEUTRAL = { primary: "#888", secondary: "#555", accent: "#aaa" };

interface Sender {
  id: string;
  name: string;
}

/** How one background notice reads: what it is, who it is from, what about, and its full text. */
interface NoticeLine {
  item: NoticeItem;
  look: "routine" | "memory" | "report" | "update";
  sender: Sender;
  subject: string;
  /** What the notice says in full, under its row when the run is open; "" when the row says it all. */
  body: string;
  failed: boolean;
}

function str(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/** The first non-empty line, without the Markdown marks that would show as raw characters in a line. */
function firstLine(text: string): string {
  const line = text.split(/\r?\n/).find((entry) => entry.trim()) ?? "";
  return line.replace(/^\s*(?:#{1,6}\s+|[-*]\s+)/, "").replace(/\*\*/g, "").trim();
}

/**
 * Who a notice is from: a society agent, or the assistant itself. A notice
 * that names no agent, or names the lead (by id, or by its old built-in name
 * without an id), is the assistant's own.
 */
function noticeSender(item: NoticeItem, assistantName: string): Sender {
  const id = item.agentId || str(item.data.agent_id);
  const name = item.agentName.trim();
  const lead = id === LEAD_ID || (!id && (!name || name === assistantName || name.toLowerCase() === LEAD_ID));
  return lead ? { id: LEAD_ID, name: assistantName } : { id, name: name || id };
}

function lineOf(item: NoticeItem, t: T, assistantName: string): NoticeLine {
  const sender = noticeSender(item, assistantName);
  const failed = item.status === "failed" || item.status === "blocked" || item.resolved === "failed";
  const base = { item, sender, failed };
  if (item.kind === "routine_run") {
    // The routine's own name; an older notice carries only its first line.
    return { ...base, look: "routine", subject: str(item.data.title).trim() || firstLine(item.text), body: "" };
  }
  if (item.kind === "memory_updated") {
    return { ...base, look: "memory", subject: str(item.data.path).split("/").at(-1) ?? "", body: "" };
  }
  if (REPORT_KINDS.has(item.kind) || sender.id !== LEAD_ID) {
    const text = item.kind === "society_result" ? societyResultText(t, item) : item.text;
    const subject = (str(item.data.standing_title) || str(item.data.title)).trim();
    return { ...base, look: "report", subject, body: text.trim() };
  }
  const text = item.text.trim();
  const subject = firstLine(text);
  return { ...base, look: "update", subject, body: text.includes("\n") || subject.length > LONG_SUBJECT ? text : "" };
}

/** The run a routine's start notice opens, or null when the notice does not say which. */
function routineTarget(line: NoticeLine): RoutineChatTarget | null {
  const sessionId = str(line.item.data.session_id);
  const agentId = line.item.agentId || str(line.item.data.agent_id);
  if (!sessionId || !agentId) return null;
  return { agentId, sessionId, title: line.subject, timestamp: line.item.tsMs };
}

/**
 * The notice a memory row opens. A receipt in the assistant's own chat names
 * no agent; it is the assistant's, so its file is read from the lead's folder.
 */
function memoryItem(line: NoticeLine): NoticeItem {
  return line.item.agentId ? line.item : { ...line.item, agentId: line.sender.id };
}

/** Senders of the run, each once, in order of appearance. */
function runSenders(lines: NoticeLine[]): Sender[] {
  const seen = new Map<string, Sender>();
  for (const { sender } of lines) {
    const key = sender.id || sender.name;
    if (key && !seen.has(key)) seen.set(key, sender);
  }
  return [...seen.values()];
}

/** An agent's face and name, as in the agent-to-agent line; a neutral face without a roster entry. */
function Person({ who, agentsById }: { who: Sender; agentsById: Faces }) {
  const face = agentsById?.[who.id] ?? { name: who.name, agentId: who.id || undefined, figure: null, palette: NEUTRAL };
  return (
    <span data-testid="background-run-person" className="inline-flex items-center gap-1 text-foreground-secondary group-hover:text-foreground">
      <AgentSwatch agent={face} size={18} />
      <span className="max-w-[12rem] truncate">{agentsById?.[who.id]?.name || who.name}</span>
    </span>
  );
}

/**
 * "Routine started · Daily issue check", "Noted · USER.md",
 * "Report from [face] Scout", "Update from [face] Nova · The first line".
 * The sender stands where the translation puts `{0}`.
 */
function NoticeLabel({ line, agentsById }: { line: NoticeLine; agentsById: Faces }) {
  const t = useT();
  const Icon = line.look === "routine" ? Clock3 : line.look === "memory" ? Feather : null;
  const [before, after = ""] = (
    line.look === "report" ? t("agent_chat.bg_report_from") : t("agent_chat.bg_update_from")
  ).split("{0}");
  return (
    <>
      {Icon ? (
        <>
          <Icon aria-hidden className="h-3.5 w-3.5 shrink-0" />
          <span>{t(line.look === "routine" ? "agent_chat.bg_routine_started" : "agent_chat.bg_noted")}</span>
        </>
      ) : (
        <>
          {before.trim() ? <span>{before.trim()}</span> : null}
          <Person who={line.sender} agentsById={agentsById} />
          {after.trim() ? <span>{after.trim()}</span> : null}
        </>
      )}
      {line.subject ? <span className="max-w-[18rem] truncate" title={line.subject}>· {line.subject}</span> : null}
    </>
  );
}

const ROW = "mx-auto flex max-w-full flex-wrap items-center justify-center gap-x-1.5 gap-y-1 rounded px-0.5 text-center text-xs";
const PRESSABLE = "group hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/** One notice of an open run: a button when it opens something (the routine's run, the memory file). */
function NoticeRow({ line, onOpen, title, agentsById }: {
  line: NoticeLine; onOpen: (() => void) | null; title?: string; agentsById: Faces;
}) {
  const className = cn(ROW, line.failed ? "text-destructive" : "text-muted-foreground");
  const label = <NoticeLabel line={line} agentsById={agentsById} />;
  if (!onOpen) return <p data-testid="background-run-row" className={className}>{label}</p>;
  return (
    <button type="button" onClick={onOpen} title={title} data-testid="background-run-row" className={cn(className, PRESSABLE)}>
      {label}
    </button>
  );
}

/**
 * One quiet, centred line for a run of background notices, drawn like the
 * agent-to-agent line (`InternalMessageRun`): "Routine started · Daily issue
 * check", "Report from Scout", or "3 updates from Nova and Scout". No box:
 * it is not a message. The line unfolds the notices in place, each a row of
 * its own with its full text under it. A lone notice with nothing to unfold
 * does what its row would do: a routine's start opens the run, a memory
 * receipt opens the file.
 */
export function BackgroundRun({ run, agentsById, assistantName }: {
  run: BackgroundRunItem;
  /** Faces by agent id from the society roster, under the names a person knows. */
  agentsById?: Record<string, RunFace>;
  /** The assistant's name, for a notice that names no agent (the assistant's own). */
  assistantName: string;
}) {
  const t = useT();
  const labelId = useId();
  const [open, setOpen] = useState(false);
  const [viewing, setViewing] = useState<NoticeItem | null>(null);
  const { items } = run;
  const lines = items.map((item) => lineOf(item, t, assistantName));
  const failed = lines.filter((line) => line.failed).length;
  const single = lines.length === 1 ? lines[0] : null;

  const actionOf = (line: NoticeLine): (() => void) | null => {
    if (line.look === "routine") {
      const target = routineTarget(line);
      return target ? () => useRoutineNavigation.getState().open(target) : null;
    }
    if (line.look === "memory" && memoryNoticePath(memoryItem(line))) return () => setViewing(memoryItem(line));
    return null;
  };
  const titleOf = (line: NoticeLine): string | undefined => {
    const path = line.look === "memory" ? memoryNoticePath(memoryItem(line)) : null;
    return path ? memoryNoticeTitle(t, path) : undefined;
  };
  // Several notices, or one with more to say than its line, unfold.
  const foldable = !single || Boolean(single.body);
  const direct = single && !foldable ? actionOf(single) : null;

  const senders = runSenders(lines);
  const summary = (
    <span id={labelId} className="inline-flex max-w-full flex-wrap items-center justify-center gap-x-1.5 gap-y-1">
      {single ? <NoticeLabel line={single} agentsById={agentsById} /> : (
        <>
          <span>{t("agent_chat.bg_count").replace("{0}", String(lines.length))}</span>
          {senders.map((who, index) => (
            <Fragment key={who.id || who.name}>
              {index > 0 ? <span>{index === senders.length - 1 ? t("agent_chat.run_and") : ","}</span> : null}
              <Person who={who} agentsById={agentsById} />
            </Fragment>
          ))}
        </>
      )}
      {failed > 0 ? (
        <span className="text-destructive">· {t("agent_chat.run_failed").replace("{0}", String(failed))}</span>
      ) : null}
    </span>
  );

  return (
    <div data-testid="background-run" data-message-id={items[0].id} data-count={items.length} className="flex flex-col gap-2">
      {/* A desktop notification of a later notice in the run lands here too. */}
      {items.slice(1).map((item) => <span key={item.id} data-message-id={item.id} hidden />)}
      <div className="flex justify-center py-1 text-center text-xs text-muted-foreground">
        {foldable ? (
          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            aria-expanded={open}
            aria-label={open ? t("agent_chat.bg_collapse") : t("agent_chat.bg_expand")}
            aria-describedby={labelId}
            data-testid="background-run-toggle"
            className={cn("max-w-full rounded px-0.5", PRESSABLE)}
          >
            {summary}
          </button>
        ) : direct ? (
          <button
            type="button"
            onClick={direct}
            title={single ? titleOf(single) : undefined}
            data-testid="background-run-open"
            className={cn("max-w-full rounded px-0.5", PRESSABLE)}
          >
            {summary}
          </button>
        ) : (
          <p className="max-w-full px-0.5">{summary}</p>
        )}
      </div>
      {open && foldable ? (
        <div data-testid="background-run-items" className="flex flex-col gap-1 text-xs text-muted-foreground">
          {lines.map((line) => (
            <Fragment key={line.item.id}>
              {/* A lone notice's line is the header already. */}
              {single ? null : <NoticeRow line={line} onOpen={actionOf(line)} title={titleOf(line)} agentsById={agentsById} />}
              {line.body ? (
                <div data-testid="background-run-body"
                  className="mx-auto mt-1 w-full max-w-xl rounded-xl bg-secondary px-4 py-3 text-sm leading-relaxed [overflow-wrap:anywhere]">
                  <ChatMarkdown text={line.body} />
                </div>
              ) : null}
            </Fragment>
          ))}
        </div>
      ) : null}
      {viewing ? <MemoryNoticeViewer item={viewing} onClose={() => setViewing(null)} /> : null}
    </div>
  );
}
