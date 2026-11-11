import {
  ChevronRight, CircleHelp, Clock, Cog, Globe, KeyRound, Lightbulb, Loader2, Rocket, ShieldCheck, SquareTerminal,
  TriangleAlert, Users, type LucideIcon,
} from "lucide-react";

import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { useAgentChatStore } from "@/store/agentChat";
import { useEventStore, type SectionId } from "@/store/events";
import { openAgent, revealCard, type CardKind } from "@/views/society/agentNavigation";

import type { StatusFinding, StatusRow, StatusTrouble } from "./statusLightStore";

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

/** The mark for a kind of status row; a question mark for a kind not known here. */
export function statusKindIcon(kind: string): LucideIcon {
  return KIND_ICON[kind] ?? CircleHelp;
}

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

/** How a row is tinted: waiting on the person, working quietly, or in trouble. */
export type StatusTone = "needs" | "running" | "trouble";

export const TILE_TONE: Record<StatusTone, string> = {
  needs: "bg-primary/10 text-primary ring-primary/20",
  running: "bg-secondary text-muted-foreground ring-border",
  trouble: "bg-warning/10 text-warning ring-warning/25",
};

const COUNT_TONE: Record<StatusTone, string> = {
  needs: "bg-primary/15 text-primary",
  running: "bg-secondary text-muted-foreground",
  trouble: "bg-warning/15 text-warning",
};

/**
 * One line of the status list: a tinted mark, a title and the word for what it
 * is. With `onGo` it is a button that leads to its place and shows a chevron
 * on hover; without, it is a plain line.
 */
export function StatusItem({ Icon, tone, title, subtitle, spin = false, onGo, hint, testId, kind }: {
  Icon: LucideIcon; tone: StatusTone; title: string; subtitle: string; spin?: boolean;
  onGo?: () => void; hint?: string; testId: string; kind?: string;
}) {
  const body = (
    <>
      <span aria-hidden className={cn("flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ring-1 ring-inset", TILE_TONE[tone])}>
        <Icon strokeWidth={1.75} className={cn("h-4 w-4", spin && "motion-safe:animate-spin")} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium text-foreground">{title}</span>
        <span className="block truncate text-xs text-muted-foreground first-letter:uppercase">{subtitle}</span>
      </span>
      {onGo && (
        <ChevronRight aria-hidden strokeWidth={1.75}
          className="h-4 w-4 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100" />
      )}
    </>
  );
  const shape = "group flex w-full min-w-0 items-center gap-3 rounded-lg px-2 py-1.5 text-left";
  if (!onGo) return <div title={title} data-testid={testId} data-kind={kind} className={shape}>{body}</div>;
  return (
    <button type="button" onClick={onGo} title={hint ? `${title} · ${hint}` : title} data-testid={testId} data-kind={kind}
      className={cn(shape, "transition-colors hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring")}>
      {body}
    </button>
  );
}

/**
 * One status row: what it is (a mark and a word) and its title, as a button
 * that leads to its place. `running` turns the mark into a quiet spinner.
 */
export function StatusRowButton({ row, running = false, onGo }: {
  row: StatusRow; running?: boolean; onGo: (row: StatusRow) => void;
}) {
  const t = useT();
  return (
    <StatusItem Icon={running ? Loader2 : statusKindIcon(row.kind)} tone={running ? "running" : "needs"} spin={running}
      title={row.title} subtitle={t(`status_light.kind_${row.kind}`)} onGo={() => onGo(row)} testId="status-light-row" kind={row.kind} />
  );
}

/** The heading of a status group: its name and how many rows it holds. */
function GroupHeading({ title, count, tone }: { title: string; count: number; tone: StatusTone }) {
  return (
    <h3 className="m-0 flex items-center gap-2 px-2 pb-1 text-xs font-medium text-muted-foreground">
      <span className="truncate">{title}</span>
      <span className={cn("rounded-full px-1.5 text-xs font-medium tabular-nums", COUNT_TONE[tone])}>{count}</span>
    </h3>
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
    <section data-testid={testId} className="pt-4 first:pt-0">
      <GroupHeading title={title} count={rows.length} tone={running ? "running" : "needs"} />
      <ul className="m-0 flex list-none flex-col gap-px p-0">
        {shown.map((row) => (
          <li key={`${row.kind}:${row.id}:${row.title}`}><StatusRowButton row={row} running={running} onGo={onGo} /></li>
        ))}
      </ul>
      {more > 0 && <p data-testid={`${testId}-more`} className="m-0 px-2 pt-1 text-xs text-muted-foreground">+{more}</p>}
    </section>
  );
}

/** A provider failure as a trouble class: a bad key is a login problem, no credit is a limit. */
const STATUS_CLASS: Record<string, string> = { bad_key: "auth", no_credits: "quota", model_unavailable: "model_unavailable" };
const KNOWN_CLASSES = ["quota", "rate_limit", "auth", "model_unavailable"];

/** The words for a provider's trouble class ("usage limit reached"). */
export function troubleLabel(t: (key: string) => string, cls: string): string {
  return t(`status_light.class_${KNOWN_CLASSES.includes(cls) ? cls : "other"}`);
}

/**
 * A provider name such as "OpenAI GPT-Live (ChatGPT subscription)" is too long
 * for one sidebar line: the name stays the title, the part in brackets joins
 * what is wrong in the second line.
 */
function providerLines(name: string, problem: string): { title: string; subtitle: string } {
  const match = /^(.+?)\s*\(([^()]+)\)$/.exec(name);
  return match ? { title: match[1], subtitle: `${problem} · ${match[2]}` } : { title: name, subtitle: problem };
}

/** Open the API keys page, where a provider in trouble is set right. */
export function openKeys(onDone?: () => void): void {
  useEventStore.getState().setActiveSection("apikeys");
  onDone?.();
}

/** One line of "Needs a look", ready to draw as a row or as a tile. */
export interface TroubleItem {
  key: string;
  kind: string;
  testId: "status-light-seat" | "status-light-finding";
  title: string;
  subtitle: string;
  /** A provider is set right on the API keys page; any other finding leads nowhere. */
  opensKeys: boolean;
}

/**
 * Providers in trouble and the watchdog's open findings as plain lines. A
 * provider line names the provider and what is wrong ("model not available");
 * any other finding is told as it is.
 */
export function troubleItems(trouble: StatusTrouble[], findings: StatusFinding[], t: (key: string) => string): TroubleItem[] {
  const seats = trouble.map((seat): TroubleItem => ({
    key: `${seat.provider}/${seat.account}`, kind: seat.class, testId: "status-light-seat",
    title: seat.account ? `${seat.provider} · ${seat.account}` : seat.provider,
    subtitle: troubleLabel(t, seat.class), opensKeys: true,
  }));
  const found = findings.map((finding): TroubleItem => finding.provider
    ? {
      key: finding.id, kind: finding.kind, testId: "status-light-finding", opensKeys: true,
      ...providerLines(finding.provider, troubleLabel(t, STATUS_CLASS[finding.status ?? ""] ?? "other")),
    }
    : {
      key: finding.id, kind: finding.kind, testId: "status-light-finding", opensKeys: false,
      title: finding.title, subtitle: t("status_light.finding_label"),
    });
  return [...seats, ...found];
}

/**
 * "Needs a look": providers in trouble and the watchdog's open findings, each
 * with a warning mark. A provider row opens the API keys page.
 */
export function StatusTroubleGroup({ trouble, findings, testId, onNavigate }: {
  trouble: StatusTrouble[]; findings: StatusFinding[]; testId: string;
  /** Called after a row took the person somewhere (a popover closes itself). */
  onNavigate?: () => void;
}) {
  const t = useT();
  const items = troubleItems(trouble, findings, t);
  if (items.length === 0) return null;
  const hint = t("status_light.open_keys");
  return (
    <section data-testid={testId} className="pt-4 first:pt-0">
      <GroupHeading title={t("status_light.trouble_heading")} count={items.length} tone="trouble" />
      <ul className="m-0 flex list-none flex-col gap-px p-0">
        {items.map((item) => (
          <li key={item.key}>
            <StatusItem Icon={TriangleAlert} tone="trouble" testId={item.testId} kind={item.kind}
              title={item.title} subtitle={item.subtitle}
              {...(item.opensKeys ? { hint, onGo: () => openKeys(onNavigate) } : {})} />
          </li>
        ))}
      </ul>
    </section>
  );
}
