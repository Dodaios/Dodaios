import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { useT } from "@/i18n";
import { createAgentChatStore, type AgentChatStoreHook } from "@/store/agentChat";
import { AgentChatStoreProvider } from "./AgentChatStoreContext";
import { withoutAnsweredResults } from "./agentResults";
import { cn } from "@/lib/utils";
import { LeadReply, OWN_BUBBLE } from "./LeadReply";
import { MessageReceipt } from "./messageReceipt";
import { TypingBubble } from "./TypingBubble";
import type { Decide } from "./WorkTrace";
import { codingThreadRef, type CodingThreadRef, type NoticeItem, type TimelineItem } from "./reduce";
import { AnswerCodingAgents } from "./AnswerCodingAgents";
import { PAGE_NOTICE_KIND, PageCard, pageCardData, pageModesForTurn } from "./PageCard";
import type { SidePart } from "./chronology";

/**
 * How a side thread's own conversation is drawn: the timeline it stands in
 * draws it. `typing` false keeps its turn from showing the three dots.
 */
export type RenderSideTimeline = (items: TimelineItem[], onDecide: Decide, typing: boolean) => ReactNode;

const ENDED: Record<string, string> = {
  stopped: "society.chat.side_thread_stopped",
  failed: "society.chat.side_thread_failed",
  interrupted: "society.chat.side_thread_interrupted",
};

/**
 * A message the person sent while the conversation was still working on an
 * earlier one, and its answer.
 *
 * It reads like any other exchange of the chat and says nothing about how it
 * is answered: their bubble, then the reply. The reply is written beside the
 * running request, in a side thread (a chat session of its own), so nothing
 * waited; that happens in the background and has no label or control here
 * (the composer's Stop ends it with everything else). While it runs, its
 * messages come from that session; afterwards its messages stand on the
 * notice itself, so a reopened chat needs no second connection. Only one that was
 * not answered says so.
 *
 * `typing`: this is where the conversation shows the assistant typing. The
 * timeline gives that to one place at a time, so two answers being written
 * never show two sets of dots.
 *
 * This is the two halves as one block, for a timeline without the
 * conversation look; that look places each half by its own time.
 */
export function SideThread({ item, renderTimeline, typing = true, receipt = false }: {
  item: NoticeItem; renderTimeline: RenderSideTimeline; typing?: boolean;
  /** The conversation look: the bubble says when the message was read. */
  receipt?: boolean;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-2" data-testid="side-thread">
      <SideThreadMessage item={item} receipt={receipt} />
      <SideThreadAnswer item={item} renderTimeline={renderTimeline} typing={typing} />
    </div>
  );
}

/** The person's message, in their own bubble like every message of theirs. */
export function SideThreadMessage({ item, receipt = false }: { item: NoticeItem; receipt?: boolean }) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <div className="flex justify-end" data-testid="agent-message-user" data-message-id={item.id} data-side-thread="message">
        <div className={cn("text-[15px] leading-[23px] [overflow-wrap:anywhere]", OWN_BUBBLE)}>
          {item.text}
        </div>
      </div>
      {/* A side thread starts the moment the message arrives: it was read then. */}
      {receipt && <MessageReceipt receipt={{ read: true, atMs: item.tsMs }} />}
    </div>
  );
}

/**
 * What answered it. The conversation look places this half by its own time
 * (`chronology.ts`): at the bottom while it is being written, and where the
 * answer arrived afterwards, so it can stand below messages that came in
 * between.
 */
export function SideThreadAnswer({ item, renderTimeline, typing = true, part, store, rowId }: {
  item: NoticeItem; renderTimeline: RenderSideTimeline; typing?: boolean;
  /** The row's own id, where the answer is drawn in parts. */
  rowId?: string;
  /**
   * The conversation look: the part of the answer this row draws, each
   * message placed by its time (`chronology.ts`). Absent: the whole answer,
   * read here.
   */
  part?: SidePart;
  /** The side thread's session a live part's cards answer to (`useSideThreadsLive`). */
  store?: AgentChatStoreHook;
}) {
  if (part) {
    return <SideThreadAnswerPart item={item} part={part} store={store} renderTimeline={renderTimeline} typing={typing}
      rowId={rowId ?? `${item.id}~answer`} />;
  }
  return <WholeSideThreadAnswer item={item} renderTimeline={renderTimeline} typing={typing} />;
}

/** One part of the answer, as the conversation look placed it. */
function SideThreadAnswerPart({ item, part, store, renderTimeline, typing, rowId }: {
  item: NoticeItem; part: SidePart; store?: AgentChatStoreHook; renderTimeline: RenderSideTimeline; typing: boolean; rowId: string;
}) {
  const t = useT();
  const running = item.resolved === "";
  const ended: string | undefined = part.closing ? ENDED[item.resolved] : undefined;
  let body: ReactNode;
  if ("live" in part && part.closing && store) {
    const decide = store.getState().decide;
    body = (
      <AgentChatStoreProvider store={store}>
        <div className="flex min-w-0 flex-col gap-3" data-testid="side-thread-live">
          {renderTimeline(part.live, (id, decision) => decide(id, decision), typing)}
        </div>
      </AgentChatStoreProvider>
    );
  } else {
    const messages = "live" in part ? part.texts.map((block) => block.text) : part.messages;
    // What it made or started stands under its last message.
    const cards = part.closing && !("live" in part) ? sideThreadCards(item) : NO_CARDS;
    // Sent and not yet answering: the dots stand in until its first message.
    body = messages.length || hasCards(cards)
      ? <StaticReply messages={messages} cards={cards} said={sideThreadMessages(item.data)} />
      : part.closing && running && typing ? <Typing /> : null;
  }
  return (
    <div className="flex min-w-0 flex-col gap-2 empty:hidden" data-testid="side-thread-reply"
      data-message-id={rowId} data-status={running ? "running" : item.resolved}
      data-part={part.closing ? "closing" : "earlier"}>
      {body}
      {ended && (
        <p data-testid="side-thread-state" className="ps-[2.625rem] text-xs text-muted-foreground">{t(ended)}</p>
      )}
    </div>
  );
}

/** The whole answer in one block, for a timeline without the conversation look. */
function WholeSideThreadAnswer({ item, renderTimeline, typing }: {
  item: NoticeItem; renderTimeline: RenderSideTimeline; typing: boolean;
}) {
  const t = useT();
  const sideId = String(item.data.side_id ?? "");
  const running = item.resolved === "";
  // A side thread seen while it ran keeps its messages on screen after it
  // ends: the answer does not jump from a live turn to a plain reply.
  const [watched] = useState(running && sideId !== "");
  const messages = useMemo(() => sideThreadMessages(item.data), [item.data]);
  const cards = useMemo(() => sideThreadCards(item), [item]);
  // How one that was not answered ended; undefined while it runs and when it was.
  const ended: string | undefined = ENDED[item.resolved];
  // Sent and not yet answering: the dots stand in until its first message.
  const waiting = running && typing ? <Typing /> : null;
  const reply = messages.length || hasCards(cards) ? <StaticReply messages={messages} cards={cards} said={messages} /> : null;
  const body = watched ? (
    <SideThreadLive sideId={sideId} running={running} typing={typing} renderTimeline={renderTimeline}
      fallback={reply ?? waiting} />
  ) : reply ?? waiting;
  return (
    <div className="flex min-w-0 flex-col gap-2 empty:hidden" data-testid="side-thread-reply"
      data-message-id={`${item.id}~answer`} data-status={running ? "running" : item.resolved}>
      {body}
      {ended && (
        <p data-testid="side-thread-state" className="ps-[2.625rem] text-xs text-muted-foreground">{t(ended)}</p>
      )}
    </div>
  );
}

/** The assistant typing, in the lane every reply of the conversation is written in. */
function Typing() {
  const t = useT();
  return (
    <div className="lead-turn" data-testid="side-thread-typing" data-look="lead">
      <div className="lead-face-lane" aria-hidden />
      <div className="lead-turn-body">
        <TypingBubble />
        <span role="status" className="sr-only">{t("work_trace.working")}</span>
      </div>
    </div>
  );
}

/**
 * What a finished side thread said, one entry per message it wrote. "I'll
 * hand that to an agent" and, minutes later, the result are two messages; the
 * notice keeps them apart (`messages`), so they stay two after the side
 * thread has ended. A notice without them carries the answer as one text.
 */
export function sideThreadMessages(data: Record<string, unknown>): string[] {
  const listed = Array.isArray(data.messages)
    ? data.messages.filter((text): text is string => typeof text === "string" && text.trim() !== "")
    : [];
  if (listed.length) return listed;
  const answer = String(data.answer ?? "");
  return answer.trim() ? [answer] : [];
}

/** What a side thread made or started, as its closing notice carries it (`cards`). */
export interface SideThreadCards {
  /** Pages and nodes it made, as the notices the chat draws as `PageCard`. */
  pages: NoticeItem[];
  /** Coding agents it started. */
  threads: CodingThreadRef[];
}

const NO_CARDS: SideThreadCards = { pages: [], threads: [] };

function hasCards(cards: SideThreadCards): boolean {
  return cards.pages.length > 0 || cards.threads.length > 0;
}

/**
 * The cards a finished side thread posted in its own session: a page or node
 * it made, a coding agent it started. They are part of its answer, so the
 * conversation shows them under it once the side thread has ended.
 */
export function sideThreadCards(item: NoticeItem): SideThreadCards {
  const raw = Array.isArray(item.data.cards) ? item.data.cards : [];
  const pages: NoticeItem[] = [];
  const threads: CodingThreadRef[] = [];
  raw.forEach((entry, index) => {
    if (!entry || typeof entry !== "object") return;
    const card = entry as Record<string, unknown>;
    if (card.kind === "coding_thread") {
      const ref = codingThreadRef(card);
      if (ref && !threads.some((known) => known.threadId === ref.threadId)) threads.push(ref);
      return;
    }
    if (card.kind !== PAGE_NOTICE_KIND) return;
    const page: NoticeItem = {
      type: "notice", id: `${item.id}~card${index}`, kind: PAGE_NOTICE_KIND, text: String(card.text ?? ""),
      agentName: "", agentId: "", status: "", tsMs: Number(card.ts_ms) || item.tsMs, data: card, resolved: "",
    };
    if (pageCardData(page)) pages.push(page);
  });
  return pages.length || threads.length ? { pages, threads } : NO_CARDS;
}

/**
 * The finished side thread's messages, in the lane every reply of the
 * conversation is written in: one bubble per message, as they stood while
 * it ran, and under them what it made or started. `said` is everything the
 * side thread wrote: a coding agent one of its messages links to is not
 * linked twice.
 */
function StaticReply({ messages, cards = NO_CARDS, said = messages }: { messages: string[]; cards?: SideThreadCards; said?: string[] }) {
  // The side thread's pages are one turn: a page it made and revised is one card.
  const pageModes = useMemo(() => pageModesForTurn(cards.pages), [cards.pages]);
  return (
    <div className="lead-turn" data-testid="side-thread-answer" data-look="lead">
      <div className="lead-face-lane" aria-hidden />
      <div className="lead-turn-body">
        <div className="min-w-0">
          {messages.map((text, index) => (
            <div key={index} className="min-w-0" data-trace-reply><LeadReply text={text} live={false} /></div>
          ))}
        </div>
        {cards.pages.length > 0 && (
          <div className="my-2 flex min-w-0 flex-col gap-2" data-testid="side-thread-pages">
            {cards.pages.map((page) => <PageCard key={page.id} item={page} mode={pageModes.get(page.id)} />)}
          </div>
        )}
        <AnswerCodingAgents threads={cards.threads} texts={said} />
      </div>
    </div>
  );
}

/**
 * The side thread's own session, read live: its messages, its cards
 * (an approval, a question) and its answer as it is written. The cards answer
 * to this session, so the store is the side thread's own.
 */
function SideThreadLive({ sideId, running, typing, renderTimeline, fallback }: {
  sideId: string; running: boolean; typing: boolean; renderTimeline: RenderSideTimeline; fallback: ReactNode;
}) {
  const store = useMemo<AgentChatStoreHook>(
    // Never the chat on stage: a voice call must not continue in a side thread.
    () => createAgentChatStore("jarvis", `side:${sideId}`, { voice: false }),
    [sideId],
  );
  const wasRunning = useRef(running);
  useEffect(() => {
    store.getState().openSession(sideId);
    return () => store.getState().disconnect();
  }, [store, sideId]);
  useEffect(() => {
    // Its answer is complete and stays in the store; the socket is not needed any more.
    if (wasRunning.current && !running) store.getState().disconnect();
    wasRunning.current = running;
  }, [running, store]);
  const items = store((s) => s.timeline.items);
  const decide = store((s) => s.decide);
  // The person's message is the bubble above; here is only what answered it.
  // An agent's result this answer takes up itself is not drawn, as in the
  // conversation the side thread stands in.
  const answering = useMemo(
    () => withoutAnsweredResults(items).filter((entry) => entry.type !== "user"),
    [items],
  );
  if (answering.length === 0) return <>{fallback}</>;
  return (
    <AgentChatStoreProvider store={store}>
      <div className="flex min-w-0 flex-col gap-3" data-testid="side-thread-live">
        {renderTimeline(answering, (id, decision) => decide(id, decision), typing)}
      </div>
    </AgentChatStoreProvider>
  );
}
