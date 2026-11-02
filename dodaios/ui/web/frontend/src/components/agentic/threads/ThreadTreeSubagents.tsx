import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { fill, useT } from "@/i18n";
import type { SubagentRow } from "@/store/threadSubagents";
import { SubagentMark } from "./ThreadSubagents";

/**
 * The open thread's sub-agents in the sidebar, listed under the thread as
 * threads of their own: each one's state at a glance, nested ones indented
 * under the sub-agent that spawned them, and a click opens its conversation.
 */

/** Rows a long list shows before "Show more"; working and waiting ones always show. */
const FOLDED_ROWS = 6;
/** How far each level of nesting moves in, in pixels. */
const INDENT = 14;
/** Deepest level drawn further in; deeper ones line up with it. */
const MAX_DEPTH = 3;

/** The few rows a long list shows: the first ones, plus every one still working, waiting or open. */
export function visibleSubagentRows(rows: readonly SubagentRow[], openId: string | null, all: boolean): SubagentRow[] {
  if (all || rows.length <= FOLDED_ROWS + 1) return [...rows];
  return rows.filter((row, index) => index < FOLDED_ROWS || row.status === "running" || row.waiting || row.id === openId);
}

/** The twisty at the start of a thread row that has sub-agents: folds them away or back. */
export function SubagentFoldToggle({ open, count, title, onToggle }: { open: boolean; count: number; title: string; onToggle: () => void }) {
  const t = useT();
  const label = fill(t(open ? "ide_threads.hide_subagents" : "ide_threads.show_subagents"), { count, title });
  return <button type="button" aria-expanded={open} aria-label={label} title={label} onClick={onToggle}
    data-testid="thread-subagents-fold"
    className="absolute left-2 top-1/2 z-10 flex h-5 w-5 -translate-y-1/2 items-center justify-center rounded text-muted-foreground/80 transition-colors hover:bg-background/70 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
    {open ? <ChevronDown aria-hidden className="h-3.5 w-3.5" /> : <ChevronRight aria-hidden className="h-3.5 w-3.5" />}
  </button>;
}

export function ThreadTreeSubagents({ rows, openId, threadTitle, onOpen }: {
  rows: readonly SubagentRow[];
  openId: string | null;
  threadTitle: string;
  onOpen: (id: string) => void;
}) {
  const t = useT();
  const [all, setAll] = useState(false);
  if (rows.length === 0) return null;
  const shown = visibleSubagentRows(rows, openId, all);
  const hidden = rows.length - shown.length;
  return <div role="group" aria-label={fill(t("ide_threads.subagents_of"), { title: threadTitle })} data-testid="thread-tree-subagents"
    className="relative mb-0.5 flex flex-col gap-px before:absolute before:bottom-1.5 before:left-[19px] before:top-0.5 before:w-px before:rounded-full before:bg-border">
    {shown.map((row) => {
      const selected = row.id === openId;
      const depth = Math.min(row.depth, MAX_DEPTH);
      const running = row.status === "running";
      return <button key={row.id} type="button" aria-current={selected ? "page" : undefined}
        onClick={() => onOpen(row.id)} title={row.agentType ? `${row.title} · ${row.agentType}` : row.title}
        data-testid="thread-tree-subagent" data-status={row.status}
        style={{ paddingLeft: 32 + depth * INDENT }}
        className={cn(
          "group/sub relative flex min-h-7 min-w-0 items-center gap-2 rounded-md py-0.5 pr-2 text-left text-[13px] transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          selected ? "bg-muted text-foreground-strong" : "text-foreground-secondary",
        )}>
        {depth > 0 && <span aria-hidden style={{ left: 32 + (depth - 1) * INDENT + 6 }}
          className="pointer-events-none absolute top-0 h-1/2 w-2 rounded-bl-md border-b border-l border-border" />}
        <SubagentMark status={row.status} waiting={row.waiting} />
        {/* The sidebar is narrow: the name gets the room, the agent type is in the tooltip. */}
        <span className={cn("min-w-0 flex-1 truncate", running && !row.waiting && !selected && "live-tool-shine")}>{row.title}</span>
      </button>;
    })}
    {hidden > 0 || (all && rows.length > FOLDED_ROWS + 1)
      ?<button type="button" onClick={() => setAll(!all)}
        className="flex min-h-6 items-center rounded-md pl-8 text-left text-[12px] text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        {all ? t("ide_threads.show_less") : fill(t("ide_threads.show_more"), { count: hidden })}
      </button>
      : null}
  </div>;
}
