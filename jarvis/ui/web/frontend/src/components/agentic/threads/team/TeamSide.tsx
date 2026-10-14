import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { ArrowDown, ArrowLeftRight, ArrowRight, ChevronRight, Crosshair, ExternalLink, ListChecks, MessagesSquare, ShieldAlert, X } from "lucide-react";
import { AgentMark } from "@/components/agentic/AgentMark";
import type { TimelineItem, UserItem } from "@/components/agentchat/reduce";
import { plural } from "@/components/agentchat/traceEntries";
import { fill, useT } from "@/i18n";
import type { TeamMember, TeamThread } from "@/lib/teamThreadsApi";
import { cn } from "@/lib/utils";
import { ThreadFolder, ThreadTurn } from "../ThreadTimeline";
import { useMemberTimeline } from "./memberStreams";
import { useMemberStatus } from "./memberLive";
import { PlanPanel } from "./PlanPanel";
import { PROSE_COMPACT } from "./roomStyle";
import { exchangeLabel, YOU, type Exchange, type TeamGraph } from "./teamGraph";
import { EntryBody, kindLabel, leadOf, TeamStory, verdictOf, type RoomNames } from "./TeamStory";

/**
 * The team room's side column: the chats, right beside the canvas.
 *
 * A tab per member shows that member's own conversation as it streams in (its
 * turns, tool calls and words); the team's shared story and, for planner and
 * builder, the living plan are tabs of their own. A line picked on the canvas
 * shows what went across it in place of the tab, until it is closed. Nothing
 * here navigates away: a member's full thread opens only on request, and
 * that thread leads back to the team.
 */

export type RoomTab = { kind: "story" } | { kind: "plan" } | { kind: "member"; id: string };

export const tabKey = (tab: RoomTab) => (tab.kind === "member" ? `member:${tab.id}` : tab.kind);

interface SideProps {
  thread: TeamThread;
  graph: TeamGraph;
  names: RoomNames;
  folder: string;
  tab: RoomTab;
  onTab: (tab: RoomTab) => void;
  following: boolean;
  onFollow: () => void;
  edge: string | null;
  onCloseEdge: () => void;
  onOpenFull: (member: TeamMember) => void;
}

export function TeamSide({ thread, graph, names, folder, tab, onTab, following, onFollow, edge, onCloseEdge, onOpenFull }: SideProps) {
  const t = useT();
  const tabs: RoomTab[] = [
    { kind: "story" },
    ...(thread.mode === "planner_builder" ? [{ kind: "plan" } as RoomTab] : []),
    ...thread.members.map((member): RoomTab => ({ kind: "member", id: member.member_id })),
  ];
  const current = tabKey(tab);
  const refs = useRef(new Map<string, HTMLButtonElement | null>());
  // Arrow keys move along the tabs, as in any tab list.
  const onKey = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft" && event.key !== "Home" && event.key !== "End") return;
    event.preventDefault();
    const at = tabs.findIndex((item) => tabKey(item) === current);
    const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1
      : (at + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
    onTab(tabs[next]);
    refs.current.get(tabKey(tabs[next]))?.focus();
  };
  const member = tab.kind === "member" ? names.member(tab.id) : undefined;

  return <section className="flex h-full min-h-0 flex-col" data-testid="team-side" aria-label={t("team_threads.room.chats")}>
    <div className="flex h-10 shrink-0 items-stretch gap-0.5 border-b border-border pl-2 pr-1">
      <div role="tablist" aria-label={t("team_threads.room.chats")} onKeyDown={onKey}
        className="flex min-w-0 flex-1 items-stretch gap-0.5 overflow-x-auto [scrollbar-width:none]">
        {tabs.map((item) => {
          const key = tabKey(item);
          const selected = key === current && !edge;
          const person = item.kind === "member" ? names.member(item.id) : undefined;
          return <button key={key} ref={(node) => { refs.current.set(key, node); }} type="button" role="tab"
            aria-selected={selected} tabIndex={key === current ? 0 : -1} onClick={() => onTab(item)}
            title={person?.name}
            data-testid={`team-tab-${key}`}
            className={cn(
              "relative flex shrink-0 items-center gap-1.5 px-2.5 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
              selected ? "text-foreground after:absolute after:inset-x-2 after:bottom-0 after:h-0.5 after:bg-accent" : "text-muted-foreground hover:text-foreground",
            )}>
            {item.kind === "story" ? <><MessagesSquare aria-hidden className="h-3.5 w-3.5" />{t("team_threads.room.story")}</>
              : item.kind === "plan" ? <><ListChecks aria-hidden className="h-3.5 w-3.5" />{t("team_threads.phase.planning")}</>
                : person ? <TabMember member={person} names={names} /> : null}
          </button>;
        })}
      </div>
      <button type="button" onClick={onFollow} aria-pressed={following} data-testid="team-follow"
        title={t("team_threads.room.follow_hint")}
        className={cn(
          "my-1.5 flex shrink-0 items-center gap-1 rounded-md px-2 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          following ? "text-accent" : "text-muted-foreground hover:bg-secondary hover:text-foreground",
        )}>
        <Crosshair aria-hidden className="h-3.5 w-3.5" />{t("team_threads.room.follow")}
      </button>
    </div>
    <div className="flex min-h-0 flex-1 flex-col" role="tabpanel" aria-label={current}>
      {edge ? <ExchangeView graph={graph} edge={edge} names={names} onClose={onCloseEdge} />
        : tab.kind === "story" ? <TeamStory thread={thread} graph={graph} names={names} />
          : tab.kind === "plan" ? <div className="min-h-0 flex-1 overflow-y-auto p-3 scrollbar-jarvis"><PlanPanel thread={thread} names={new Map(thread.members.map((item) => [item.member_id, item.name]))} /></div>
            : member ? <MemberChat key={member.member_id} member={member} thread={thread} names={names} folder={folder} onOpenFull={() => onOpenFull(member)} />
              : null}
    </div>
  </section>;
}

function TabMember({ member, names }: { member: TeamMember; names: RoomNames }) {
  const agent = names.agent(member);
  const left = member.state === "left";
  return <>
    {agent ? <AgentMark agent={agent} label={member.name} variant="plain" size="sm" /> : null}
    <span className={cn("max-w-[9rem] truncate", left && "line-through opacity-60")}>{member.name}</span>
    {!left && member.waiting ? <ShieldAlert aria-hidden className="h-3 w-3 text-warning" />
      : !left && member.working ? <span aria-hidden className="team-pulse h-1.5 w-1.5 rounded-full bg-accent" /> : null}
  </>;
}

/* ------------------------------------------------------------- member chat */

/** A brief the coordinator handed the member: folded to its first line, it is long. */
function Brief({ item }: { item: UserItem }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const first = item.text.split(/\r?\n/).map((line) => line.trim()).find(Boolean) ?? "";
  return <div className="min-w-0 rounded-md border border-border" data-testid="team-chat-brief">
    <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
      className="flex w-full min-w-0 items-center gap-2 px-2.5 py-1.5 text-left text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring">
      <ArrowDown aria-hidden className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      <span className="shrink-0 font-medium text-foreground">{t("team_threads.room.brief")}</span>
      {!open && <span className="min-w-0 flex-1 truncate text-muted-foreground">{first.replace(/^#+\s*/, "")}</span>}
      <ChevronRight aria-hidden className={cn("ml-auto h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform", open && "rotate-90")} />
    </button>
    {open && <div className="max-h-[50vh] overflow-y-auto whitespace-pre-wrap border-t border-border px-2.5 py-2 font-mono text-xs leading-5 text-foreground/85 scrollbar-jarvis [overflow-wrap:anywhere]">
      {item.text}
    </div>}
  </div>;
}

function ChatItem({ item }: { item: TimelineItem }) {
  if (item.type === "user") {
    if (item.author) return <Brief item={item} />;
    return <div className="flex justify-end"><div className="max-w-[85%] whitespace-pre-wrap rounded-2xl bg-secondary px-3.5 py-2 text-sm text-foreground [overflow-wrap:anywhere]">{item.text}</div></div>;
  }
  if (item.type === "turn") return <ThreadTurn turn={item} />;
  if (item.type === "error") return <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">{item.text}</p>;
  if (item.type === "notice") return <p className="text-center text-xs text-muted-foreground">{item.text}</p>;
  return <div className={PROSE_COMPACT}>{item.message.text}</div>;
}

/** One member's own conversation, live, read-only: the team speaks to it, the person steps in below. */
function MemberChat({ member, thread, names, folder, onOpenFull }: {
  member: TeamMember; thread: TeamThread; names: RoomNames; folder: string; onOpenFull: () => void;
}) {
  const t = useT();
  const timeline = useMemberTimeline(member.session_id, true);
  const over = thread.state === "done" || thread.state === "stopped" || thread.state === "failed";
  const status = useMemberStatus(member, over);
  const agent = names.agent(member);
  const scroller = useRef<HTMLDivElement | null>(null);
  const pinned = useRef(true);
  const [away, setAway] = useState(false);
  useLayoutEffect(() => {
    const box = scroller.current;
    if (box && pinned.current) box.scrollTop = box.scrollHeight;
  });
  useEffect(() => {
    const box = scroller.current;
    if (!box || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => { if (pinned.current) box.scrollTop = box.scrollHeight; });
    const content = box.firstElementChild;
    if (content) observer.observe(content);
    return () => observer.disconnect();
  }, []);
  const items = timeline.items;
  return <div className="flex min-h-0 flex-1 flex-col" data-testid={`team-chat-${member.member_id}`}>
    <div className="flex min-h-11 shrink-0 items-center gap-2 border-b border-border px-3 py-1.5">
      <span className="grid h-6 w-6 shrink-0 place-items-center rounded-md bg-secondary">
        {agent ? <AgentMark agent={agent} label={member.name} variant="plain" size="sm" /> : null}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-baseline gap-2">
          <span className="truncate text-sm font-medium text-foreground">{member.name}</span>
          {member.role && <span className="shrink-0 font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">{t(`team_threads.member_role.${member.role}`)}</span>}
          {member.model && !member.name.includes(member.model) && <span className="truncate font-mono text-[11px] text-muted-foreground">{member.model}</span>}
        </span>
        <span className={cn("block truncate text-xs", status.tone === "waiting" ? "text-warning" : status.tone === "working" ? "text-foreground" : "text-muted-foreground")}>
          {status.text}
        </span>
      </span>
      <button type="button" onClick={onOpenFull} data-testid="team-chat-open-full"
        className={cn(
          "flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          member.waiting ? "bg-warning/15 font-medium text-foreground hover:bg-warning/25" : "text-muted-foreground hover:bg-secondary hover:text-foreground",
        )}>
        {member.waiting ? t("team_threads.room.answer_in_thread") : t("team_threads.room.open_full")}
        <ExternalLink aria-hidden className="h-3 w-3" />
      </button>
    </div>
    <ThreadFolder.Provider value={folder}>
      <div className="relative min-h-0 flex-1">
        <div ref={scroller} className="h-full overflow-y-auto scrollbar-jarvis" data-testid="team-chat-scroll"
          onScroll={(event) => {
            const box = event.currentTarget;
            const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 48;
            pinned.current = atBottom;
            setAway(!atBottom);
          }}>
          <div className="team-chat flex flex-col gap-4 px-4 pb-6 pt-4">
            {items.length === 0
              ? <p className="py-8 text-center text-sm text-muted-foreground">{fill(t("team_threads.room.chat_empty"), { member: member.name })}</p>
              : items.map((item) => <ChatItem key={item.id} item={item} />)}
          </div>
        </div>
        {away && <button type="button" aria-label={t("ide_threads.scroll_newest")}
          onClick={() => { const box = scroller.current; if (box) box.scrollTo({ top: box.scrollHeight, behavior: "smooth" }); }}
          className="absolute bottom-3 left-1/2 z-10 flex h-8 w-8 -translate-x-1/2 items-center justify-center rounded-full border border-border bg-popover text-muted-foreground shadow-float hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          <ArrowDown className="h-4 w-4" />
        </button>}
      </div>
    </ThreadFolder.Provider>
  </div>;
}

/* ---------------------------------------------------------------- exchange */

function Who({ id, names }: { id: string; names: RoomNames }) {
  const t = useT();
  const member = names.member(id);
  const agent = member ? names.agent(member) : "";
  return <span className="flex min-w-0 items-center gap-1.5">
    {agent && member ? <AgentMark agent={agent} label={member.name} variant="plain" size="sm" /> : null}
    <span className="truncate font-medium text-foreground">{id === YOU ? t("team_threads.room.you") : names.name(id)}</span>
  </span>;
}

/** What went across one line of the canvas, both ways, in order. */
function ExchangeView({ graph, edge, names, onClose }: { graph: TeamGraph; edge: string; names: RoomNames; onClose: () => void }) {
  const t = useT();
  const lang = t("trace_report.locale");
  const line = graph.edges.find((item) => item.id === edge);
  // Escape closes it, unless the person is typing.
  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      if (event.target instanceof Element && event.target.closest("textarea, input, [contenteditable=true]")) return;
      onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  if (!line) return null;
  const both = graph.edges
    .filter((item) => (item.from === line.from && item.to === line.to) || (item.from === line.to && item.to === line.from))
    .flatMap((item) => item.exchanges)
    .sort((left, right) => left.seq - right.seq);
  return <div className="flex min-h-0 flex-1 flex-col" data-testid="team-exchange">
    <div className="flex min-h-11 shrink-0 items-center gap-2 border-b border-border px-3 text-sm">
      <Who id={line.from} names={names} />
      {both.some((item) => item.from === line.to)
        ? <ArrowLeftRight aria-hidden className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        : <ArrowRight aria-hidden className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
      <Who id={line.to} names={names} />
      <span className="ml-1 truncate text-xs text-muted-foreground">{fill(t(`team_threads.room.exchange_count_${plural(lang, both.length)}`), { count: both.length })}</span>
      <button type="button" onClick={onClose} aria-label={t("team_threads.close_reader")} title={t("team_threads.close_reader")}
        data-testid="team-exchange-close"
        className="ml-auto rounded-md p-1 text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
    <ol className="min-h-0 flex-1 overflow-y-auto px-3 pb-6 pt-2 scrollbar-jarvis">
      {both.map((exchange, index) => <ExchangeItem key={`${exchange.seq}:${exchange.from}:${exchange.to}`} exchange={exchange} names={names}
        label={exchangeLabel(exchange, t, lang)} highlight={exchange.from === line.from} first={index === both.length - 1} />)}
    </ol>
  </div>;
}

/** One exchange: a line with who, what and the verdict; the newest opens to its whole text. */
function ExchangeItem({ exchange, names, label, highlight, first }: {
  exchange: Exchange; names: RoomNames; label: string; highlight: boolean; first: boolean;
}): ReactNode {
  const t = useT();
  const entry = exchange.entry;
  const verdict = verdictOf(entry, t);
  const [open, setOpen] = useState(first);
  return <li className={cn("border-l-[3px] py-1.5 pl-3 pr-1", highlight ? "border-accent/60" : "border-border")} data-testid="team-exchange-item">
    <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
      className="group flex w-full min-w-0 flex-col gap-0.5 rounded-md text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
    <span className="flex w-full flex-wrap items-baseline gap-x-1.5 text-xs">
      <span className="font-medium text-foreground">{exchange.from === YOU ? t("team_threads.room.you") : names.name(exchange.from)}</span>
      <span className="text-muted-foreground">→ {exchange.to === YOU ? t("team_threads.room.you") : names.name(exchange.to)}</span>
      <span className="text-muted-foreground">· {entry.kind === "user" ? label : kindLabel(entry, t)}</span>
      {verdict && <span className={cn("font-medium", verdict.tone === "positive" ? "text-success" : "text-warning")}>{verdict.text}</span>}
      <ChevronRight aria-hidden className={cn("ml-auto h-3.5 w-3.5 shrink-0 self-center text-muted-foreground transition-transform", open && "rotate-90")} />
    </span>
    {!open && <span className="line-clamp-2 text-[13px] leading-5 text-muted-foreground [overflow-wrap:anywhere]">{leadOf(entry, t)}</span>}
    </button>
    {open && <div className="pt-1.5">
      {entry.kind === "user"
        ? <p className="whitespace-pre-wrap text-sm text-foreground [overflow-wrap:anywhere]">{entry.payload.text}</p>
        : <EntryBody entry={entry} />}
    </div>}
  </li>;
}
