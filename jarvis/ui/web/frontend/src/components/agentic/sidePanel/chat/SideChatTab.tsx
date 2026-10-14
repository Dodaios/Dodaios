import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { ArrowUp, History, Square, SquarePen, Trash2 } from "lucide-react";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { joinProviderOptions } from "@/store/agentChat";
import { AgentModelPicker, EffortPicker } from "@/components/agentic/threads/ThreadPickers";
import { ThreadMenuItem, ThreadMenuSeparator, ThreadPopover } from "@/components/agentic/threads/ThreadPopover";
import { ThreadTimeline } from "@/components/agentic/threads/ThreadTimeline";
import { shortAge } from "@/components/agentic/threads/threadModel";
import { useSideChatStore } from "./sideChatStore";

const DRAFT_KEY = "jarvis.agenticIde.sideChat.message.v1";
/** How many earlier chats the history list shows. */
const HISTORY_ROWS = 30;

function storedMessage(): string {
  try {
    return localStorage.getItem(DRAFT_KEY) ?? "";
  } catch {
    return "";
  }
}

function persistMessage(value: string): void {
  try {
    if (value) localStorage.setItem(DRAFT_KEY, value);
    else localStorage.removeItem(DRAFT_KEY);
  } catch {
    /* a convenience only: the box keeps the text for this session */
  }
}

const ICON_BTN =
  "inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors " +
  "hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring " +
  "disabled:cursor-default disabled:opacity-40 disabled:hover:bg-transparent";

/**
 * The side panel's Chat surface: a plain AI chat with the model you pick.
 *
 * Ask anything, read the answer. It is not a coding agent and knows nothing
 * about the workspace: no seat on its surface has tools, and the model is told
 * only how to answer. Answers stream, and a model's thinking folds behind one
 * line once it is done.
 */
export function SideChatTab() {
  const t = useT();
  const catalog = useSideChatStore((state) => state.catalog);
  const connections = useSideChatStore((state) => state.connections);
  const liveModels = useSideChatStore((state) => state.liveModels);
  const draft = useSideChatStore((state) => state.draft);
  const timeline = useSideChatStore((state) => state.timeline);
  const sessions = useSideChatStore((state) => state.sessions);
  const activeSessionId = useSideChatStore((state) => state.activeSessionId);
  const activeSession = useSideChatStore((state) => state.activeSession);
  const busy = useSideChatStore((state) => state.busy);
  const lastError = useSideChatStore((state) => state.lastError);
  const catalogError = useSideChatStore((state) => state.catalogError);

  const [message, setMessageState] = useState(storedMessage);
  const [historyOpen, setHistoryOpen] = useState(false);
  const historyAnchor = useRef<HTMLButtonElement | null>(null);
  const input = useRef<HTMLTextAreaElement | null>(null);

  const setMessage = useCallback((value: string) => {
    setMessageState(value);
    persistMessage(value);
  }, []);

  useEffect(() => {
    const store = useSideChatStore.getState();
    if (!store.catalog || store.catalogStale) void store.loadCatalog();
    void store.loadSessions();
  }, []);

  // The box grows with what is typed, up to a share of the panel.
  useLayoutEffect(() => {
    const box = input.current;
    if (!box) return;
    box.style.height = "auto";
    box.style.height = `${box.scrollHeight}px`;
  }, [message]);

  const providers = useMemo(
    () => (catalog ? joinProviderOptions(catalog.providers, connections) : [])
      .slice()
      .sort((a, b) => Number(b.connected) - Number(a.connected)),
    [catalog, connections],
  );
  const provider = providers.find((option) => option.id === draft.provider) ?? null;
  const running = busy || timeline.items.some((item) => item.type === "turn" && item.status === "running");
  const canSend = message.trim().length > 0 && !running && Boolean(provider?.connected);
  const started = timeline.items.length > 0;

  const send = useCallback(async () => {
    const text = message.trim();
    if (!text || running) return;
    setMessage("");
    const outcome = await useSideChatStore.getState().send(text);
    // A message that never left comes back into the box.
    if (outcome === "failed") setMessage(text);
  }, [message, running, setMessage]);

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    void send();
  };

  const newChat = () => {
    useSideChatStore.getState().newChat();
    input.current?.focus();
  };

  const earlier = useMemo(
    () => [...sessions].sort((a, b) => b.updated_ms - a.updated_ms).slice(0, HISTORY_ROWS),
    [sessions],
  );
  // A backend from before this chat existed refuses its surface outright:
  // the app was updated and not yet restarted. Say that, not the refusal.
  const error = lastError || (catalogError && !catalog ? t("ide_side_panel.chat.needs_restart") : catalogError);
  // The list is refreshed after every send; the session held from creation has no title yet.
  const listed = sessions.find((session) => session.session_id === activeSessionId);
  const title = listed?.title?.trim() || activeSession?.title?.trim() || t("ide_side_panel.chat.new_chat");

  return (
    <div data-testid="side-chat-tab" className="flex h-full min-h-0 flex-col">
      <header className="flex h-10 shrink-0 items-center gap-1 border-b border-border/60 px-2">
        <span className="min-w-0 flex-1 truncate px-1 text-sm text-foreground" data-testid="side-chat-title">{title}</span>
        <button ref={historyAnchor} type="button" onClick={() => setHistoryOpen((value) => !value)} aria-haspopup="menu" aria-expanded={historyOpen}
          aria-label={t("ide_side_panel.chat.history")} title={t("ide_side_panel.chat.history")} data-testid="side-chat-history" className={ICON_BTN}>
          <History className="h-3.5 w-3.5" aria-hidden />
        </button>
        <button type="button" onClick={newChat} disabled={!started && !activeSessionId}
          aria-label={t("ide_side_panel.chat.new_chat")} title={t("ide_side_panel.chat.new_chat")} data-testid="side-chat-new" className={ICON_BTN}>
          <SquarePen className="h-3.5 w-3.5" aria-hidden />
        </button>
        <ThreadPopover anchor={historyAnchor} open={historyOpen} onClose={() => setHistoryOpen(false)} align="end" width={300} label={t("ide_side_panel.chat.history")}>
          {earlier.length === 0 && <p className="px-2 py-2 text-sm text-muted-foreground">{t("ide_side_panel.chat.history_empty")}</p>}
          {earlier.map((session) => <ThreadMenuItem key={session.session_id}
            label={session.title?.trim() || t("ide_side_panel.chat.new_chat")}
            hint={shortAge(session.updated_ms)}
            selected={session.session_id === activeSessionId}
            onSelect={() => { setHistoryOpen(false); useSideChatStore.getState().openSession(session.session_id); }} />)}
          {activeSessionId && <>
            <ThreadMenuSeparator />
            <ThreadMenuItem danger icon={<Trash2 className="h-3.5 w-3.5" />} label={t("ide_side_panel.chat.delete_chat")}
              onSelect={() => { setHistoryOpen(false); void useSideChatStore.getState().removeSession(activeSessionId); }} />
          </>}
        </ThreadPopover>
      </header>

      {started
        ? <ThreadTimeline items={timeline.items} sessionId={activeSessionId} bottomInset={0} tone="chat" />
        : <div className="flex min-h-0 flex-1 flex-col items-center justify-center px-6 text-center" data-testid="side-chat-empty">
          <h2 className="text-xl font-medium text-foreground-strong">{t("ide_side_panel.chat.empty_title")}</h2>
          <p className="mt-2 max-w-xs text-sm leading-6 text-muted-foreground">{t("ide_side_panel.chat.empty_hint")}</p>
        </div>}

      <div className="shrink-0 px-3 pb-3 pt-1">
        {error && <p role="alert" data-testid="side-chat-error" className="mb-2 px-1 text-xs text-destructive">{error}</p>}
        <div className="overflow-hidden rounded-3xl border border-border bg-card shadow-[0_8px_24px_-12px_rgb(var(--scrim-rgb)/0.5)] transition-colors focus-within:border-border-strong">
          <textarea ref={input} value={message} rows={2}
            onChange={(event) => setMessage(event.target.value)} onKeyDown={onKeyDown}
            aria-label={t("ide_side_panel.chat.input_aria")} placeholder={t("ide_side_panel.chat.placeholder")}
            data-testid="side-chat-input"
            className="block max-h-[36vh] min-h-[64px] w-full resize-none bg-transparent px-4 pb-1 pt-3.5 text-base leading-6 text-foreground outline-none placeholder:text-faint-foreground scrollbar-jarvis" />
          <div className="flex min-w-0 items-center justify-between gap-2 px-2.5 pb-2.5">
            <div className="-ms-0.5 flex min-w-0 flex-1 items-center gap-1 overflow-x-auto [scrollbar-width:none]">
              <AgentModelPicker providers={providers} liveModels={liveModels} draft={draft}
                lockedProvider={started && activeSessionId ? draft.provider : null}
                onPick={(nextProvider, model) => void useSideChatStore.getState().setDraft(nextProvider !== draft.provider ? { provider: nextProvider, model } : { model })} />
              <EffortPicker provider={provider} draft={draft} liveModels={liveModels} separated
                onPick={(effort) => void useSideChatStore.getState().setDraft({ effort })} />
            </div>
            {running
              ? <button type="button" aria-label={t("ide_side_panel.chat.stop")} title={t("ide_side_panel.chat.stop")} data-testid="side-chat-stop"
                onClick={() => void useSideChatStore.getState().cancel("side-chat-stop-button")}
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-foreground text-background transition-transform duration-150 hover:scale-105 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                <Square className="h-3 w-3 fill-current" />
              </button>
              : <button type="button" aria-label={t("ide_side_panel.chat.send")} title={t("ide_side_panel.chat.send")} data-testid="side-chat-send"
                disabled={!canSend} onClick={() => void send()}
                className={cn(
                  "flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent text-accent-foreground shadow-[0_1px_2px_rgb(var(--accent-rgb)/0.3)]",
                  "transition-[opacity,transform] duration-150 hover:scale-105 hover:opacity-95 disabled:opacity-40 disabled:hover:scale-100",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                )}>
                <ArrowUp className="h-4 w-4" />
              </button>}
          </div>
        </div>
      </div>
    </div>
  );
}
