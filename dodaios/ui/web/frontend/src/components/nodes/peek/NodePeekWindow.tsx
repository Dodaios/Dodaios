/**
 * The node window: a node, open over the conversation it was made in.
 *
 * A click on a page card in a chat opens the node here instead of leaving
 * for the Nodes section (the maintainer's request, 2026-11-16). It is a
 * window over the app with a margin all round: on the left the node on the
 * very stage the Nodes section has (`views/VisualizationView`'s `Stage`), so
 * it can be edited, commented, shared and read as source right here; on the
 * right the conversation the click came from, with its composer, so a change
 * can be asked for while the node is in view. The assistant's revision shows
 * in the open node within seconds (the stage's own watcher).
 *
 * The seam between the two can be dragged, and the conversation can be put
 * away; both are remembered. In a window too narrow for two columns the
 * conversation slides over the node instead. Another page card clicked in
 * the conversation beside the node swaps the node; previous / next (the
 * overflow menu, or the arrow keys) walk the pages this conversation made.
 *
 * Not a Radix dialog on purpose: a modal one shuts the pointer and the focus
 * out of everything portaled to <body>, which is where the composer's menus,
 * the editors' menus and the tooltips live. The window keeps focus to itself
 * by hand instead (`keepFocusInside`).
 *
 * It is on screen at the click, with no fade and no blur behind it: the
 * first frame is the window and the node. The conversation follows right
 * after that frame, and it is not drawn a second time: the one that is
 * already on the page behind the window is moved into it (`BorrowedChat`,
 * `moveKeepingPlace`), which costs one layout. Only a conversation that is
 * drawn nowhere the window can borrow it from is drawn here
 * (`useAfterFirstPaint`).
 */
import { Suspense, lazy, useCallback, useDeferredValue, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2, Maximize2, PanelRight, PanelRightClose, X } from "lucide-react";

import { AgentChatStoreProvider } from "@/components/agentchat/AgentChatStoreContext";
import { PaneResizer } from "@/components/layout/PaneResizer";
import { draftChangeBeside } from "@/components/nodes/askDodaios";
import { useNodeCommentDraft } from "@/components/nodes/nodeCommentDraft";
import { isTypedNode, type NodeCard } from "@/components/nodes/nodeModel";
import { invalidateNodes, useNodes } from "@/components/nodes/useNodes";
import { ROUND_BUTTON, StageBar, TitlePill } from "@/components/visualization/ArtifactStageBar";
import { useElementSize } from "@/hooks/useElementSize";
import { useOutputsList } from "@/hooks/useOutputs";
import { useResizablePane } from "@/hooks/useResizablePane";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { useAgentChatStore, type AgentChatStoreHook } from "@/store/agentChat";
import { useEventStore } from "@/store/events";
import { useNodePeek, type LentConversation, type NodePeekRequest } from "@/store/nodePeek";
import { EmptyStage, Stage, isTypingTarget, visualOf, type StageChrome } from "@/views/VisualizationView";
import { moveKeepingPlace } from "./moveKeepingPlace";
import { PEEK_FRAME_CLASS, PEEK_SCRIM_CLASS } from "./peekFrame";
import {
  CHAT_DEFAULT_WIDTH,
  CHAT_MIN_WIDTH,
  chatMaxWidth,
  conversationPages,
  isNarrowFrame,
  visualFromRef,
} from "./peekModel";

// The conversation's own code is the front page's; loaded with it or here.
const ChatStage = lazy(() =>
  import("@/components/home/ChatStage").then((module) => ({ default: module.ChatStage })),
);

const CHAT_WIDTH_KEY = "jarvis.nodes.peek.chat_width";
/** Dragged narrower than this, the conversation is put away. */
const CHAT_COLLAPSE_BELOW = 200;
const NO_CARDS: NodeCard[] = [];

export default function NodePeekWindow({ peek }: { peek: NodePeekRequest }) {
  const t = useT();
  const client = useQueryClient();
  const chat: AgentChatStoreHook = peek.chat ?? useAgentChatStore;
  const chatOpen = useNodePeek((s) => s.chatOpen);
  const setChatOpen = useNodePeek((s) => s.setChatOpen);
  const pushToast = useEventStore((s) => s.pushToast);

  /* --- what is open ------------------------------------------------------ */

  const outputs = useOutputsList();
  const nodes = useNodes();
  const allCards = nodes.data?.nodes ?? NO_CARDS;
  /* A node the stage just made (a new whiteboard) is open before the list has it. */
  const [made, setMade] = useState<NodeCard | null>(null);
  const card = useMemo(() => {
    const listed = allCards.find((c) => c.slug === peek.slug && c.path === peek.path);
    if (listed) return listed;
    return made !== null && made.slug === peek.slug && made.path === peek.path ? made : null;
  }, [allCards, made, peek.slug, peek.path]);
  const run = useMemo(
    () => (outputs.data ?? []).find((r) => r.slug === peek.slug) ?? null,
    [outputs.data, peek.slug],
  );
  const visual = useMemo(
    () =>
      (card !== null ? visualOf(card, run ?? undefined) : null) ??
      visualFromRef(peek.slug, peek.path, peek.title, run),
    [card, run, peek.slug, peek.path, peek.title],
  );
  const node = card !== null && isTypedNode(card) ? card : null;
  const title = visual?.title || card?.title || peek.title;

  /* --- closing ----------------------------------------------------------- */

  const unsent = useNodeCommentDraft((s) => s.pending.length);
  const [confirming, setConfirming] = useState(false);
  const [sendingUnsent, setSendingUnsent] = useState(false);
  const closeNow = useCallback(() => {
    // The pins die with the page: comments nobody sent do not come back.
    useNodeCommentDraft.getState().open(null);
    // The cards and covers elsewhere follow what was edited here.
    invalidateNodes(client);
    useNodePeek.getState().close();
  }, [client]);
  const requestClose = useCallback(() => {
    if (useNodeCommentDraft.getState().pending.length > 0) setConfirming(true);
    else closeNow();
  }, [closeNow]);
  useEffect(() => {
    if (unsent === 0) setConfirming(false);
  }, [unsent]);
  const sendThenClose = useCallback(async () => {
    if (node === null) return closeNow();
    setSendingUnsent(true);
    const sent = await useNodeCommentDraft.getState().sendAll(node);
    setSendingUnsent(false);
    if (sent) closeNow();
    else pushToast("error", t("nodes.comment.failed"));
  }, [node, closeNow, pushToast, t]);

  const openInNodes = useCallback(() => {
    useNodeCommentDraft.getState().open(null);
    useNodePeek.getState().close();
    useEventStore.getState().requestVisual(peek.ref);
  }, [peek.ref]);

  /* --- the pages of this conversation ------------------------------------ */

  const items = chat((s) => s.timeline.items);
  const pages = useMemo(() => conversationPages(items), [items]);
  const position = pages.findIndex((page) => page.ref === peek.ref);
  const step = useCallback(
    (delta: number) => {
      const next = position < 0 ? undefined : pages[position + delta];
      if (next) useNodePeek.getState().open(next.ref, { title: next.title });
    },
    [pages, position],
  );

  /* --- layout ------------------------------------------------------------ */

  const frame = useRef<HTMLDivElement>(null);
  const { width: frameWidth } = useElementSize(frame);
  const narrow = isNarrowFrame(frameWidth);
  /* In a narrow window the conversation covers the node, so it starts away. */
  const [overNode, setOverNode] = useState(false);
  const showChat = narrow ? overNode : chatOpen;
  const toggleChat = useCallback(() => {
    if (narrow) setOverNode((value) => !value);
    else setChatOpen(!chatOpen);
  }, [narrow, chatOpen, setChatOpen]);
  const hideChat = useCallback(() => {
    if (narrow) setOverNode(false);
    else setChatOpen(false);
  }, [narrow, setChatOpen]);
  const maxChat = chatMaxWidth(frameWidth);
  const pane = useResizablePane({
    storageKey: CHAT_WIDTH_KEY,
    defaultSize: CHAT_DEFAULT_WIDTH,
    min: CHAT_MIN_WIDTH,
    max: maxChat,
    handle: "start",
    collapseBelow: CHAT_COLLAPSE_BELOW,
    onCollapse: hideChat,
  });

  /* The conversation behind the window is this one: it is moved here as it
   * is. Any other is drawn here. Either way after the node: the window's
   * first frame waits for no conversation, however long it is. */
  const lender = useNodePeek((s) => s.lender);
  const borrowed = lender !== null && lender.chat === chat ? lender : null;
  const painted = useAfterFirstPaint();
  /* Moving is one layout and happens at once. Drawing a conversation here is
   * long work: it waits its turn behind whatever the person does meanwhile. */
  const drawHere = useDeferredValue(painted);

  /* --- keys and focus ---------------------------------------------------- */

  const [editorOpen, setEditorOpen] = useState(false);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return;
      // Only keys pressed in the window (or with nothing focused): a dialog
      // or a menu drawn over it keeps its own.
      const target = event.target;
      const inWindow = target instanceof Node && frame.current?.contains(target) === true;
      if (!inWindow && target !== document.body) return;
      // The node's own content keeps its keys: a whiteboard moves what is
      // selected with the arrows and leaves a tool with Escape.
      if (target instanceof Element && target.closest('[data-testid="visualization-stage"]')) return;
      if (event.key === "Escape") {
        if (confirming) setConfirming(false);
        // A text being typed and an open editor keep their Escape.
        else if (isTypingTarget(event.target) || editorOpen) return;
        else requestClose();
      } else if (isTypingTarget(event.target) || editorOpen) return;
      else if (event.key === "ArrowLeft") step(-1);
      else if (event.key === "ArrowRight") step(1);
      else return;
      event.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [confirming, editorOpen, requestClose, step]);

  // Focus comes into the window when it opens and goes back where it was.
  useEffect(() => {
    const before = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    frame.current?.focus({ preventScroll: true });
    return () => {
      if (before?.isConnected) before.focus({ preventScroll: true });
    };
  }, []);
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => keepFocusInside(host, frame), []);

  /* --- the stage's bar --------------------------------------------------- */

  const askChange = useCallback(
    (asked: NodeCard) => {
      if (narrow) setOverNode(true);
      else setChatOpen(true);
      draftChangeBeside(asked, chat, () => frame.current);
    },
    [narrow, setChatOpen, chat],
  );
  /* One close button, in the window's top right corner: on the conversation's
   * header while that column stands beside the node, on the node's bar else. */
  const chatBeside = showChat && !narrow;
  const chrome: StageChrome = useMemo(
    () => ({
      layout: "window",
      closeButton: !chatBeside,
      onAskChange: askChange,
      trailing: (
        <>
          <button
            type="button"
            onClick={openInNodes}
            aria-label={t("nodes.peek.open_in_nodes")}
            title={t("nodes.peek.open_in_nodes")}
            data-testid="node-peek-expand"
            className={ROUND_BUTTON}
          >
            <Maximize2 aria-hidden />
          </button>
          <button
            type="button"
            onClick={toggleChat}
            aria-pressed={showChat}
            aria-label={t(showChat ? "nodes.peek.hide_chat" : "nodes.peek.show_chat")}
            title={t(showChat ? "nodes.peek.hide_chat" : "nodes.peek.show_chat")}
            data-testid="node-peek-chat-toggle"
            className={cn(ROUND_BUTTON, showChat && "bg-secondary text-foreground")}
          >
            {showChat ? <PanelRightClose aria-hidden /> : <PanelRight aria-hidden />}
          </button>
        </>
      ),
    }),
    [askChange, openInNodes, toggleChat, showChat, chatBeside, t],
  );
  const openMade = useCallback((next: NodeCard) => {
    if (next.path === null) return;
    setMade(next);
    useNodePeek.getState().open(`${next.slug}::${next.path}`, { title: next.title });
  }, []);
  const jumpToRun = useCallback((slug: string) => {
    // A run is the Nodes section's to show: its files, its graph, its state.
    useNodePeek.getState().close();
    useEventStore.getState().requestVisual(`${slug}::`);
  }, []);

  const loading = outputs.isLoading || nodes.isLoading;
  const failed = outputs.isError && nodes.isError;

  return (
    <div ref={host} className="fixed inset-0 z-[60]" data-testid="node-peek">
      <div
        aria-hidden
        onClick={requestClose}
        data-testid="node-peek-scrim"
        className={PEEK_SCRIM_CLASS}
      />
      <div
        ref={frame}
        role="dialog"
        aria-modal="true"
        aria-label={title || t("nodes.peek.window")}
        tabIndex={-1}
        data-testid="node-peek-window"
        data-narrow={narrow ? "true" : "false"}
        className={PEEK_FRAME_CLASS}
      >
        <section className="relative flex min-h-0 min-w-0 flex-1 flex-col" data-testid="node-peek-stage">
          {visual === null && run === null ? (
            <>
              <StageBar
                onClose={requestClose}
                layout="window"
                trailing={chrome.trailing}
                closeButton={chrome.closeButton}
                center={<TitlePill title={title} picture={false} plain />}
              />
              <EmptyStage loading={loading} error={failed} />
            </>
          ) : (
            <Stage
              key={peek.slug}
              run={run}
              visual={visual}
              node={node}
              onEditorOpen={setEditorOpen}
              onOpenNode={openMade}
              onJumpToRun={jumpToRun}
              nav={{ onBack: requestClose, position, total: pages.length, onStep: step }}
              chrome={chrome}
            />
          )}
          {/* A drag over the page's frame would lose the pointer to it. */}
          {pane.isResizing && <div aria-hidden className="absolute inset-0 z-30" />}
          {confirming && (
            <UnsentComments
              count={unsent}
              busy={sendingUnsent}
              canSend={node !== null}
              onKeep={() => setConfirming(false)}
              onDiscard={closeNow}
              onSend={() => void sendThenClose()}
            />
          )}
        </section>
        {showChat && !narrow && (
          <PaneResizer
            orientation="vertical"
            onPointerDown={pane.startResize}
            onDoubleClick={pane.reset}
            // The conversation is right of its seam: left makes it wider.
            onNudge={(delta) => pane.nudge(-delta)}
            valueNow={pane.size}
            valueMin={CHAT_MIN_WIDTH}
            valueMax={maxChat}
            controls="node-peek-chat"
            active={pane.isResizing}
            title={t("nodes.peek.resize")}
            testId="node-peek-resizer"
            className="-mx-[3px]"
          />
        )}
        {showChat && (
          <aside
            id="node-peek-chat"
            data-testid="node-peek-chat"
            style={narrow ? undefined : { width: pane.size }}
            className={cn(
              "flex min-h-0 shrink-0 flex-col bg-background",
              narrow && "absolute inset-y-0 right-0 z-40 w-[min(100%,420px)] border-l border-border shadow-float animate-in slide-in-from-right-6 fade-in-0 duration-200",
            )}
          >
            <PeekChat
              chat={chat}
              borrowed={borrowed}
              ready={borrowed !== null ? painted : drawHere}
              onHide={narrow ? hideChat : null}
              onClose={requestClose}
            />
          </aside>
        )}
      </div>
    </div>
  );
}

/**
 * The conversation beside the node: the very chat the click came from (its
 * store), drawn by the stage every chat here uses, composer included. What
 * is typed here is typed into that conversation; the draft and the files
 * waiting to be sent are the store's, so they are the same on both sides.
 */
function PeekChat({
  chat,
  borrowed,
  ready,
  onHide,
  onClose,
}: {
  chat: AgentChatStoreHook;
  /** The conversation is on the page behind the window and is moved here; null when it is not. */
  borrowed: LentConversation | null;
  /** False for the window's first frame: the column is there, a conversation drawn here follows. */
  ready: boolean;
  /** Over the node (a narrow window): the header puts the column away. Null beside it. */
  onHide: (() => void) | null;
  /** Beside the node, the header carries the window's close button. */
  onClose: () => void;
}) {
  const t = useT();
  const assistantName = useEventStore((s) => s.assistantName);
  const surface = chat((s) => s.surface);
  const sessionTitle = chat((s) => s.activeSession?.title ?? "");
  const name = surface === "jarvis" ? assistantName : sessionTitle.trim() || t("nodes.peek.conversation");
  return (
    <AgentChatStoreProvider store={chat}>
      <header className="flex shrink-0 items-center gap-2 border-b border-border py-2.5 pl-5 pr-3">
        <div className="flex h-10 min-w-0 flex-1 items-center">
          <span className="truncate text-base font-medium text-foreground-strong" data-testid="node-peek-chat-name">
            {name || t("nodes.peek.conversation")}
          </span>
        </div>
        {onHide !== null ? (
          <button
            type="button"
            onClick={onHide}
            aria-label={t("nodes.peek.hide_chat")}
            title={t("nodes.peek.hide_chat")}
            data-testid="node-peek-chat-hide"
            className={ROUND_BUTTON}
          >
            <PanelRightClose aria-hidden />
          </button>
        ) : (
          <button
            type="button"
            onClick={onClose}
            aria-label={t("visualization.close")}
            title={t("visualization.close")}
            data-testid="node-peek-close"
            className={ROUND_BUTTON}
          >
            <X aria-hidden />
          </button>
        )}
      </header>
      {borrowed !== null ? (
        <BorrowedChat lent={borrowed} ready={ready} />
      ) : (
        <div className="flex min-h-0 min-w-0 flex-1 flex-col" data-testid="node-peek-conversation" data-ready={ready ? "true" : "false"}>
          {ready && (
            <Suspense fallback={null}>
              <ChatStage />
            </Suspense>
          )}
        </div>
      )}
    </AgentChatStoreProvider>
  );
}

/**
 * The conversation from the page behind the window, moved here once the
 * window's first frame is on screen, and put back where it came from before
 * this place leaves the page. Putting it back happens in a layout cleanup on
 * purpose: that runs while the conversation is still on the page, so the
 * reader's place in it can be read and kept.
 */
function BorrowedChat({ lent, ready }: { lent: LentConversation; ready: boolean }) {
  const place = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    if (ready && place.current) moveKeepingPlace(lent.element, place.current);
  }, [lent, ready]);
  useLayoutEffect(
    () => () => {
      if (lent.home.isConnected) moveKeepingPlace(lent.element, lent.home);
    },
    [lent],
  );
  return (
    <div
      ref={place}
      className="flex min-h-0 min-w-0 flex-1 flex-col"
      data-testid="node-peek-conversation"
      data-borrowed="true"
      data-ready={ready ? "true" : "false"}
    />
  );
}

/**
 * The longest the conversation waits for the window's first frame. A window
 * that is covered or minimised is given no frames at all, and the desktop
 * shell's engine has been seen to treat a window on screen that way for a
 * while; the conversation must not hang on a frame that does not come.
 */
const FIRST_FRAME_WAIT_MS = 150;

/**
 * False while the component's first frame is drawn, true right after it, or
 * after `FIRST_FRAME_WAIT_MS` when no frame is drawn.
 */
function useAfterFirstPaint(): boolean {
  const [painted, setPainted] = useState(false);
  useEffect(() => {
    let timer: number | undefined;
    const done = () => setPainted(true);
    // The frame callback runs before the paint; the timer it sets, after it.
    const frame = window.requestAnimationFrame(() => {
      timer = window.setTimeout(done, 0);
    });
    const latest = window.setTimeout(done, FIRST_FRAME_WAIT_MS);
    return () => {
      window.cancelAnimationFrame(frame);
      window.clearTimeout(timer);
      window.clearTimeout(latest);
    };
  }, []);
  return painted;
}

/** Asked before the window closes on comments that were left and not sent. */
function UnsentComments({
  count,
  busy,
  canSend,
  onKeep,
  onDiscard,
  onSend,
}: {
  count: number;
  busy: boolean;
  canSend: boolean;
  onKeep: () => void;
  onDiscard: () => void;
  onSend: () => void;
}) {
  const t = useT();
  const quiet =
    "inline-flex h-9 items-center justify-center rounded-full border border-border/70 px-4 text-base text-foreground " +
    "transition-colors hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60";
  return (
    <div
      role="alertdialog"
      aria-label={t("nodes.peek.unsent_title")}
      data-testid="node-peek-unsent"
      className="absolute left-1/2 top-[72px] z-40 w-[min(440px,calc(100%-2rem))] -translate-x-1/2 rounded-xl border border-border-strong bg-popover p-4 text-popover-foreground shadow-float animate-in fade-in-0 zoom-in-95 duration-150"
    >
      <p className="text-base font-medium text-foreground-strong">
        {count === 1 ? t("nodes.peek.unsent_one") : t("nodes.peek.unsent_many").replace("{0}", String(count))}
      </p>
      <p className="mt-1 text-sm text-muted-foreground">{t("nodes.peek.unsent_body")}</p>
      <div className="mt-4 flex flex-wrap justify-end gap-2">
        <button type="button" onClick={onKeep} disabled={busy} data-testid="node-peek-unsent-keep" className={quiet}>
          {t("nodes.peek.unsent_keep")}
        </button>
        <button type="button" onClick={onDiscard} disabled={busy} data-testid="node-peek-unsent-discard" className={quiet}>
          {t("nodes.peek.unsent_discard")}
        </button>
        {canSend && (
          <button
            type="button"
            onClick={onSend}
            disabled={busy}
            autoFocus
            data-testid="node-peek-unsent-send"
            className="inline-flex h-9 items-center justify-center gap-2 rounded-full bg-foreground px-4 text-base text-background transition-colors hover:bg-foreground/85 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
          >
            {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
            {t("nodes.peek.unsent_send")}
          </button>
        )}
      </div>
    </div>
  );
}

/**
 * Focus that lands in the app behind the window (a Tab past the window's
 * last control) comes back into the window. Everything portaled to <body>
 * (menus, dialogs, toasts) is outside the app's root and so left alone, and
 * so is the window caption, whose buttons must keep working.
 */
function keepFocusInside(
  host: { current: HTMLElement | null },
  frame: { current: HTMLElement | null },
): () => void {
  const onFocusIn = (event: FocusEvent) => {
    const target = event.target;
    const shell = host.current?.parentElement;
    if (!(target instanceof Element) || !frame.current || !shell) return;
    if (frame.current.contains(target) || !shell.contains(target)) return;
    if (target.closest('[data-testid="window-caption"]')) return;
    frame.current.focus({ preventScroll: true });
  };
  document.addEventListener("focusin", onFocusIn);
  return () => document.removeEventListener("focusin", onFocusIn);
}
