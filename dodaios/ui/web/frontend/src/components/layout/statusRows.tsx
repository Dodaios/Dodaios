import {
  CircleHelp, Clock, Cog, Globe, KeyRound, Lightbulb, Loader2, Rocket, ShieldCheck, SquareTerminal, Users,
  type LucideIcon,
} from "lucide-react";

import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { useAgentChatStore } from "@/store/agentChat";
import { useEventStore, type SectionId } from "@/store/events";
import { openAgent, revealCard, type CardKind } from "@/views/society/agentNavigation";

import type { StatusRow } from "./statusLightStore";

/** The assistant's own id in the roster: its cards live in the conversation. */
const ASSISTANT_ID = "jarvis";
const CARD_KINDS: readonly string[] = ["question", "approval", "credential", "proposal"];

const KIND_ICON: Record<string, LucideIcon> = {
  question: CircleHelp,
  approval: ShieldCheck,
  credential: KeyRound,
  proposal: Lightbulb,
  browser: Globe,
  browser_takeover: Globe,
  pane: SquareTerminal,
  team: Users,
  mission: Rocket,
  task: Clock,
  job: Cog,
};

/**
 * Go to the place a status row stands for.
 *
 * A card of the assistant itself (a question, an approval) lives in its one
 * conversation, so the row opens the conversation and marks the card there.
 * Any other agent's card opens that agent; every other row names a section.
 */
export function goToStatusRow(row: StatusRow): void {
  const { link } = row;
  const kind = CARD_KINDS.includes(row.kind) ? (row.kind as CardKind) : undefined;
  if (link.agent_id === ASSISTANT_ID) {
    useEventStore.getState().setActiveSection("chats");
    // A `society:` id names the conversation itself, which is already the one on stage.
    if (link.session_id && !link.session_id.startsWith("society:")) {
      const chat = useAgentChatStore.getState();
      if (chat.activeSessionId !== link.session_id) chat.openSession(link.session_id);
    }
    void revealCard({ cardRef: link.ref_id || undefined, kind });
  } else if (link.agent_id) {
    openAgent(link.agent_id, { sessionId: link.session_id || undefined, cardRef: link.ref_id || undefined, kind });
  } else if (link.section) {
    useEventStore.getState().setActiveSection(link.section as SectionId);
  }
}

/**
 * One status row: what it is (a mark and a word) and its title, as a button
 * that leads to its place. `running` turns the mark into a quiet spinner.
 */
export function StatusRowButton({ row, running = false, onGo }: {
  row: StatusRow; running?: boolean; onGo: (row: StatusRow) => void;
}) {
  const t = useT();
  const Icon = running ? Loader2 : KIND_ICON[row.kind] ?? CircleHelp;
  return (
    <button type="button" onClick={() => onGo(row)} title={row.title} data-testid="status-light-row" data-kind={row.kind}
      className="flex w-full min-w-0 items-center gap-2.5 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      <span aria-hidden className={cn("flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-secondary", running ? "text-muted-foreground" : "text-foreground")}>
        <Icon strokeWidth={1.75} className={cn("h-4 w-4", running && "motion-safe:animate-spin")} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm text-foreground">{row.title}</span>
        <span className="block truncate text-sm text-muted-foreground">{t(`status_light.kind_${row.kind}`)}</span>
      </span>
    </button>
  );
}

/** A group of status rows under a heading that carries their count. */
export function StatusGroup({ title, rows, running = false, onGo, testId, max }: {
  title: string; rows: StatusRow[]; running?: boolean; onGo: (row: StatusRow) => void; testId: string;
  /** Show at most this many rows; the rest is told as a number. */
  max?: number;
}) {
  if (rows.length === 0) return null;
  const shown = max ? rows.slice(0, max) : rows;
  const more = rows.length - shown.length;
  return (
    <section data-testid={testId} className="pt-3 first:pt-0">
      <h3 className="m-0 flex items-center gap-2 px-2 pb-1 text-sm text-muted-foreground">
        <span className="truncate">{title}</span>
        <span className={cn("rounded-full px-1.5 text-xs font-medium tabular-nums", running ? "bg-secondary text-muted-foreground" : "bg-primary/15 text-primary")}>
          {rows.length}
        </span>
      </h3>
      <ul className="m-0 flex list-none flex-col gap-px p-0">
        {shown.map((row) => (
          <li key={`${row.kind}:${row.id}:${row.title}`}><StatusRowButton row={row} running={running} onGo={onGo} /></li>
        ))}
      </ul>
      {more > 0 && <p data-testid={`${testId}-more`} className="m-0 px-2 pt-1 text-sm text-muted-foreground">+{more}</p>}
    </section>
  );
}
