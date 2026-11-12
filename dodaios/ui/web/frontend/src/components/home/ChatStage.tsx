import { useTranscriptView } from "../society/chat/useTranscriptView";
import { PairConversationBoundary } from "@/components/agentchat/PairConversation";
import { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { useEventStore } from "@/store/events";
import { useHomeStore } from "@/store/home";
import { useAgentChat } from "@/components/agentchat/AgentChatStoreContext";
import { ScrollArea } from "@/components/ui/scroll-area";
import { ScrollToEndButton } from "@/components/ui/scroll-to-end-button";
import { scrollViewportOf, useStickToBottom } from "@/hooks/useStickToBottom";
import { AgentComposer } from "@/components/agentchat/AgentComposer";
import { AgentTimeline } from "@/components/agentchat/AgentTimeline";
import { withoutBackgroundNotices } from "@/components/agentchat/backgroundNotices";
import { STEER_PREFIX, type TimelineItem } from "@/components/agentchat/reduce";
import { rosterFaces } from "@/components/agentchat/InternalMessageRun";
import { useCachedRosterAgents } from "@/components/society/data";
import { societyDisplayName } from "@/lib/societyDisplayName";
import { BinaryCursorField } from "@/components/home/BinaryCursorField";
import { Greeting } from "@/components/home/Greeting";
import { VoiceThreadStage } from "@/components/home/VoiceThreadStage";
import type { ApprovalDecision, ApprovalRuleChoice } from "@/lib/agentChatApi";
import { fill, useT } from "@/i18n";
import { folderLeaf } from "@/lib/folderPath";
import { useHistoryPolling } from "@/hooks/useHistoryPolling";
import { FolderCode } from "lucide-react";

// The one-time introduction after setup (components/onboarding/conversation):
// it shows only while the backend says it is due, else the greeting.
const FirstConversation = lazy(() => import("@/components/onboarding/conversation/FirstConversation"));

// The call window is only needed once a call runs.
const CallWindow = lazy(() =>
  import("@/components/home/CallWindow").then((module) => ({ default: module.CallWindow })),
);

/**
 * The running call's window (components/home/CallWindow), hung on the top
 * edge of whatever wraps it: the composer, so the window stands on it. It
 * shows for every call, however it was started, the wake word and the call
 * hotkey included. Over a composer the window leaves the microphone switch
 * and the hang-up to the composer's own row.
 */
function CallSlot({ composerControls = false }: { composerControls?: boolean }) {
  const callLive = useEventStore((s) => Boolean(s.voiceState) && s.voiceState !== "idle" && s.voiceState !== "error");
  // Asked for at the click, or ended on a problem that still has to be read.
  const waiting = useHomeStore((s) => s.callPending || s.callProblem !== null);
  // Starting a call can keep the window busy for seconds; the code is fetched
  // beforehand so the call window is there the moment it is needed.
  useEffect(() => {
    const timer = window.setTimeout(() => void import("@/components/home/CallWindow"), 1500);
    return () => window.clearTimeout(timer);
  }, []);
  // Once a call has shown, the window decides for itself when to leave: it
  // stays a moment after the call ends, so a reason that arrives right after
  // the hang-up lands in the same window instead of a second one.
  const [shown, setShown] = useState(false);
  useEffect(() => {
    if (callLive || waiting) setShown(true);
  }, [callLive, waiting]);
  return shown || callLive || waiting ? <Suspense fallback={null}><CallWindow composerControls={composerControls} /></Suspense> : null;
}

/**
 * The newest message the person sent, and where it sits: a message of its own,
 * or one sent into the running turn (a `steer-` block of that turn). A result
 * that comes back by itself later (`background`) is not something they sent.
 */
function newestSent(items: TimelineItem[]): { id: string; index: number } | null {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const item = items[index];
    if (item.type === "user" && item.origin !== "background") return { id: item.id, index };
    if (item.type !== "turn") continue;
    for (let at = item.blocks.length - 1; at >= 0; at -= 1) {
      const block = item.blocks[at];
      if (block.kind === "text" && block.id.startsWith(STEER_PREFIX)) return { id: `${item.id}:${block.id}`, index };
    }
  }
  return null;
}

/**
 * The chat stage — the typed half of the front page: Jarvis with a keyboard.
 *
 * What is typed here goes to the same assistant the microphone reaches —
 * the same memory, the same tools, the same voice in the answers — carried
 * by an agent-chat session on the `jarvis` surface (dodaios/agent_chat). The
 * composer's picks — provider, model, reasoning effort, permission mode —
 * decide what Jarvis runs on for THIS chat; they never reach the voice
 * path (AP-9: nothing here touches it). The Agentic IDE lists its coding
 * sessions on its own surface (`agent`), so none of them appear here.
 *
 * One centred column, like a document: the greeting and the composer sit
 * in the middle of an empty page; once there are messages the column
 * scrolls and the composer docks to the bottom. The history is the
 * "Earlier chats" dialog's (components/home/AllChatsDialog).
 *
 * One conversation is on stage at a time. The sidebar's history mixes agent
 * chats with VOICE sessions, and a voice session opened from here is read in
 * components/home/VoiceThreadStage — the same column, no composer. Which of
 * the two shows is decided by the event store's active thread: opening either
 * kind clears the other (components/home/chatRows), so the two can never both
 * claim the stage and leave a click looking like it did nothing.
 *
 * Scrolling is a chat's: the conversation goes on at the bottom and what
 * was said before stays in view above it. A sent message lands under the
 * last one and the view goes to the end with it, wherever the person was
 * reading; the answer grows below. Until 2026-11-12 a sent message was
 * brought to the TOP of the scroll area instead, over a spacer, which hid
 * the whole conversation behind every send (maintainer: "to see the chat I
 * have to scroll up"). The view goes to the end at once, without a glide:
 * a glide started here was cut short by the very next update of the turn,
 * and in the desktop app's engine that could leave the view where it stood
 * (maintainer, the same evening: "the chat does not move down by itself, I
 * have to scroll"). While an answer grows, the rule every conversation
 * surface here shares applies (hooks/useStickToBottom): new output pulls
 * the view along ONLY while the view is already at the end. Scrolled up to
 * read something, you keep your place while the answer goes on below, and a
 * button over the composer takes you back. Nothing yanks the page out from
 * under someone mid-sentence.
 */
export function ChatStage() {
  const assistantName = useEventStore((s) => s.assistantName);
  const surface = useAgentChat((s) => s.surface);
  const sessionId = useAgentChat((s) => s.activeSessionId);
  return surface === "jarvis" ? <PairConversationBoundary key={sessionId} recipient={{ id: "jarvis", name: assistantName }}><ChatStageContent /></PairConversationBoundary> : <ChatStageContent />;
}

function ChatStageContent() {
  const t = useT();
  const assistantName = useEventStore((s) => s.assistantName);
  // Agent messages show each agent's own pet, which only the roster knows.
  const roster = useCachedRosterAgents();
  const faces = useMemo(
    () => (roster ? rosterFaces(roster, (agent) => societyDisplayName(agent, assistantName ?? "")) : undefined),
    [roster, assistantName],
  );
  const surface = useAgentChat((s) => s.surface);
  const allItems = useAgentChat((s) => s.timeline.items);
  const cwd = useAgentChat((s) => s.draft.cwd);
  const activeSessionId = useAgentChat((s) => s.activeSessionId);
  const view = useTranscriptView(surface === "jarvis" ? activeSessionId : null, allItems);
  // Background records (a learned memory, a watchdog finding, a routine run
  // that failed) stay in the log; the conversation shows what was said.
  const items = useMemo(() => withoutBackgroundNotices(view.items), [view.items]);
  const catalog = useAgentChat((s) => s.catalog);
  const catalogStale = useAgentChat((s) => s.catalogStale);
  const sending = useAgentChat((s) => s.busy);
  const sessionRunning = useAgentChat((s) => s.activeSession?.running === true);
  const decide = useAgentChat((s) => s.decide);
  const loadCatalog = useAgentChat((s) => s.loadCatalog);
  const loadSessions = useAgentChat((s) => s.loadSessions);
  const voiceThreadId = useEventStore((s) => (s.activeKind === "voice" ? s.activeThreadId : null));
  const hasContent = items.length > 0;

  // A copy from before paints the picks at once; the fresh read still runs.
  useEffect(() => {
    if (!catalog || catalogStale) void loadCatalog();
  }, [catalog, catalogStale, loadCatalog]);
  useHistoryPolling(loadSessions);

  const providerLabel = useCallback(
    (id: string) => catalog?.providers.find((p) => p.id === id)?.label ?? id,
    [catalog],
  );
  const onDecide = useCallback(
    (approvalId: string, decision: ApprovalDecision, rule?: ApprovalRuleChoice, feedback?: string, edits?: Record<string, string>) =>
      (rule || feedback || edits ? decide(approvalId, decision, rule, feedback, edits) : decide(approvalId, decision)),
    [decide],
  );

  const rootRef = useRef<HTMLDivElement | null>(null);
  const columnRef = useRef<HTMLDivElement | null>(null);
  // Whether the view is at the end — and so whether growth pulls it along —
  // is the hook's to answer; it listens on the same viewport this stage
  // scrolls.
  const { rootRef: stickRootRef, atEnd, jumpToEnd, snapToEnd, follow } = useStickToBottom();
  const setRoot = useCallback(
    (node: HTMLDivElement | null) => {
      rootRef.current = node;
      stickRootRef(node);
    },
    [stickRootRef],
  );
  const lastItemIdRef = useRef<string | null>(null);
  const sentIdRef = useRef<string | null>(null);
  const sessionRef = useRef<string | null>(activeSessionId);

  const lastItem = items[items.length - 1];
  const lastItemId = lastItem?.id ?? null;
  const sent = useMemo(() => newestSent(items), [items]);
  // The person's own message is the last thing in the chat and its turn is
  // on the way (the send is in flight, or the session already works on it):
  // the assistant shows as typing until the turn itself takes over. A turn
  // still running above a message sent into it shows its own dots.
  const awaitingTurn = surface === "jarvis" && lastItem?.type === "user" && lastItem.origin !== "control"
    && lastItem.origin !== "background" && (sending || sessionRunning)
    && !items.some((item) => item.type === "turn" && item.status === "running");

  useLayoutEffect(() => {
    if (sessionRef.current !== activeSessionId) {
      sessionRef.current = activeSessionId;
      lastItemIdRef.current = null;
      sentIdRef.current = null;
    }
    const previousId = lastItemIdRef.current;
    const previousSentId = sentIdRef.current;
    lastItemIdRef.current = lastItemId;
    sentIdRef.current = sent?.id ?? null;
    if (!scrollViewportOf(rootRef.current) || !lastItemId) return;
    // The person sent a message into a conversation that is on screen: it
    // lands under the last one and the view goes there, also for a reader
    // who had scrolled up. Sending is being back at the end, at once.
    //
    // Asked of the newest sent message, not of the last item: the message
    // and the start of its turn arrive a millisecond apart and can reach
    // one render together, and the last item is then the turn. A reader who
    // had scrolled up stayed where they were (seen 2026-11-12). The message
    // has to be new at the end of what was on screen, so a conversation that
    // opens, or one read again after a reconnect, moves nobody.
    const previousAt = previousId === null ? -1 : items.findIndex((item) => item.id === previousId);
    if (sent && sent.id !== previousSentId && previousAt >= 0 && sent.index >= previousAt) {
      snapToEnd();
      return;
    }
    // Everything else — the answer's next words, a tool call, an opened
    // conversation landing at its end — follows only if the view was
    // already there. Growth in place (same item, more words) used to wait
    // for ResizeObserver and lose the reader for that frame. A reader who
    // scrolled up is left where they are (`follow` no-ops).
    follow();
  }, [lastItemId, sent, activeSessionId, items, follow, snapToEnd]);

  // The live blocks grow without a new item — a streamed answer, the dots
  // of a turn at work — so no render-driven effect fires for it; the
  // column's own size is the honest signal. The viewport is watched too: a
  // window that shrinks under a view at the end keeps it at the end.
  useEffect(() => {
    const column = columnRef.current;
    const viewport = scrollViewportOf(rootRef.current);
    if (!column || !viewport || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => follow());
    ro.observe(column);
    ro.observe(viewport);
    return () => ro.disconnect();
  }, [hasContent, follow]);

  // The two surfaces open with different words because they are different
  // things to be doing: here Jarvis reads with your memory and tools, there a
  // coding agent reads the folder. Same layout, so nothing moves.
  const isJarvis = surface === "jarvis";
  const subtitle = useMemo(
    () => t(isJarvis ? "agent_chat.empty_subtitle" : "agent_chat.empty_subtitle_agent"),
    [t, isJarvis],
  );

  // A spoken thread was opened from the history: read it here, in the column
  // the composer would otherwise own. An agent chat opening clears this.
  // Only the front page shares its column with the voice archive; the IDE's
  // chat is coding sessions and never shows a spoken thread.
  if (surface === "jarvis" && voiceThreadId && !activeSessionId) {
    return (
      <div className="relative flex min-h-0 flex-1 flex-col">
        <VoiceThreadStage />
        {/* No composer here: the call window stands on the stage's foot. */}
        <div className="relative mx-auto mb-4 w-full max-w-[720px]"><CallSlot /></div>
      </div>
    );
  }

  // The front page opens with the greeting alone in
  // the middle of the page, the composer already where it will stay — at the
  // bottom — so the first send moves nothing.
  if (!hasContent && isJarvis) {
    return (
      <div className="relative flex min-h-0 flex-1 flex-col items-center" data-testid="chat-stage" data-empty="true">
        <BinaryCursorField />
        <div className="relative flex w-full flex-1 flex-col items-center justify-center px-6 pb-8">
          <Suspense fallback={<Greeting />}><FirstConversation fallback={<Greeting suggestions />} /></Suspense>
        </div>
        <div className="relative w-full max-w-[720px] px-6 pb-5 pt-2">
          <CallSlot composerControls />
          {/* The digits make way while the pointer is on the composer. */}
          <div data-binary-field-off>
            <AgentComposer autoFocus />
          </div>
        </div>
      </div>
    );
  }

  if (!hasContent) {
    return (
      <div className="flex min-h-0 flex-1 flex-col items-center" data-testid="chat-stage" data-empty="true">
        <div className="flex w-full max-w-[720px] flex-1 flex-col justify-center gap-8 px-6 pb-20">
          <FolderHeadline folder={cwd} subtitle={subtitle} />
          <AgentComposer autoFocus />
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col items-center" data-testid="chat-stage" data-empty="false">
      <ScrollArea ref={setRoot} className="min-h-0 w-full flex-1">
        {/* "Select all" outside a text field selects this conversation (lib/selectAllScope). */}
        <div
          ref={columnRef}
          data-select-all
          className="relative mx-auto flex w-full max-w-[720px] flex-col gap-6 px-6 pb-6 pt-8"
        >
          <AgentTimeline
            items={items}
            assistantName={isJarvis ? assistantName : t("agent_chat.surface_agent")}
            providerLabel={providerLabel}
            onDecide={onDecide}
            bubbles={isJarvis}
            // The Agentic IDE mirrors Claude Code and Codex, whose own traces
            // the maintainer kept; every other surface draws the rail.
            traceLook={isJarvis ? "rail" : "classic"}
            traceCompanion={isJarvis}
            awaiting={awaitingTurn}
            agentsById={faces}
            // The Dodaios chat lists its pictures as files, a name and a
            // download link; it never draws them (the person's request, 2026-11-12).
            pictures={isJarvis ? "files" : "shown"}
          />
          {isJarvis && <Suspense fallback={null}><FirstConversation /></Suspense>}
        </div>
      </ScrollArea>
      <div className="relative w-full max-w-[720px] px-6 pb-5 pt-2">
        {!atEnd && <ScrollToEndButton onClick={jumpToEnd} testId="chat-scroll-end" />}
        {isJarvis && <CallSlot composerControls />}
        <AgentComposer />
      </div>
    </div>
  );
}

/**
 * The IDE chat's opening line: which folder the coding agent works in.
 *
 * Not a greeting — nobody is being greeted by a coding agent, and the front
 * page's "Good afternoon" would say the wrong thing about who is answering.
 * Same typography and the same place on the page, so the two surfaces stay
 * one design.
 */
function FolderHeadline({ folder, subtitle }: { folder: string; subtitle: string }) {
  const t = useT();
  return (
    <div className="flex flex-col items-center text-center" data-testid="chat-folder-headline">
      <h1 className="flex items-center gap-3 text-2xl font-semibold text-foreground-strong [text-wrap:balance]">
        <FolderCode className="h-[30px] w-[30px] shrink-0 text-muted-foreground" aria-hidden />
        <span>{fill(t("agent_chat.empty_title_agent"), { folder: folderLeaf(folder) })}</span>
      </h1>
      <p className="mt-2 max-w-md text-base text-muted-foreground">{subtitle}</p>
    </div>
  );
}
