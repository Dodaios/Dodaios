import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { ArrowUp } from "lucide-react";
import { getWSClient } from "@/hooks/useWebSocket";
import { useVoiceEngineDisplay } from "@/hooks/useVoiceEngineDisplay";
import { useAutoGrowTextarea } from "@/hooks/useAutoGrowTextarea";
import { useEventStore } from "@/store/events";
import { cn } from "@/lib/utils";
import { useT } from "@/i18n";
import { DictationButton } from "@/components/agentchat/DictationButton";
import { useComposerDictation } from "@/components/agentchat/useComposerDictation";

// Safety net: if the brain doesn't respond within 60s (no reply, no error event),
// we revert the indicator. A backend hang must not leave the UI stuck in the
// wait state permanently.
const THINKING_TIMEOUT_MS = 60_000;

/**
 * The composer — a card with the text box and, on its bottom row, dictation,
 * the model that will answer (click to change it) and send.
 *
 * One rounded card. Dictation runs through `useComposerDictation`, the same
 * hook every other composer uses: the dictated text is appended when it
 * arrives, and Send during a dictation waits for it.
 */
export function ChatInput() {
  const t = useT();
  const [value, setValue] = useState("");
  const textareaRef = useAutoGrowTextarea(value);
  const connected = useEventStore((s) => s.connected);
  const setActiveSection = useEventStore((s) => s.setActiveSection);
  // What will answer: the classic brain, or the realtime engine when voice
  // mode is realtime — the same resolver the header and the sidebar use.
  const engine = useVoiceEngineDisplay();
  const wsWarming = useEventStore((s) => s.wsWarming);
  // The turn's progress is no longer mirrored in the composer — the chat
  // column renders the live steps (components/home/TurnSteps) as the
  // in-progress assistant turn. The composer only arms the wait state.
  const setChatThinking = useEventStore((s) => s.setChatThinking);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Microphone dictation: the text is appended to the box when it arrives.
  const dictation = useComposerDictation(setValue, () => void send());

  useEffect(() => {
    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, []);

  async function send() {
    // Send during a dictation ends it first; the message goes once the text is here.
    if (dictation.awaitingText) {
      dictation.stopAndSend();
      return;
    }
    const content = value.trim();
    if (!content) return;
    const client = getWSClient();
    // Route the message into the active conversation so the brain (seeded on
    // resume) and the persisted thread line up. ensureActiveThread() lazily
    // creates a text thread for an unsaved "New chat" or a voice continuation.
    let threadId: string | undefined;
    try {
      threadId = await useEventStore.getState().ensureActiveThread();
    } catch {
      threadId = undefined; // fall back to the WS session thread
    }
    client?.send({
      type: "message",
      kind: "text",
      content,
      metadata: threadId ? { thread_id: threadId } : undefined,
    });
    useEventStore.getState().pushEvent({
      id: `local-${Date.now()}`,
      name: "ui.user_message",
      layer: "ui",
      ts: Date.now(),
      payload: { content },
    });
    setChatThinking(true);
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    timeoutRef.current = setTimeout(() => {
      setChatThinking(false);
      timeoutRef.current = null;
    }, THINKING_TIMEOUT_MS);
    setValue("");
  }

  function onKeyDown(ev: KeyboardEvent<HTMLTextAreaElement>) {
    if (ev.key === "Enter" && !ev.shiftKey) {
      ev.preventDefault();
      send();
    }
  }

  // Live during a dictation even with an empty box: Send then waits for the text.
  const canSend = connected && (Boolean(value.trim()) || dictation.awaitingText);

  return (
    <div
      data-testid="chat-composer"
      className={cn(
        // The composer is an object: card fill, the strong rim, one radius.
        // `dark:border-transparent` used to erase that rim in the theme the
        // app opens in, which left the box with no outline and no focus state
        // at all on near-black. The ring is the focus device everywhere else
        // in the system, so it is the focus device here.
        "flex flex-col gap-row rounded-lg border border-border-strong bg-card p-3",
        "transition-[box-shadow] focus-within:ring-2 focus-within:ring-border-strong",
      )}
    >
      <textarea
        // Marks the composer as the app's fallback dictation sink. The
        // delivery path needs to know whether it is on screen at all before
        // it hands a transcript to a component that may be unmounted — see
        // lib/dictationTarget.ts.
        data-jarvis-chat-input=""
        ref={textareaRef}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder={
          dictation.dictating
            ? t("chats_view.dictation_listening")
            : connected
            ? t("chats_view.input_placeholder")
            : wsWarming
              ? t("voice_state.booting")
              : t("voice_state.offline")
        }
        disabled={!connected}
        rows={2}
        // Grows with the text up to half the window (useAutoGrowTextarea);
        // past the cap the box scrolls rather than pushing Send out of reach.
        className="max-h-[50vh] w-full resize-none bg-transparent px-1 py-1 text-reading text-foreground scrollbar-jarvis placeholder:text-faint-foreground focus-visible:outline-none disabled:opacity-50"
      />
      <div className="flex items-center gap-row">
        <DictationButton
          dictating={dictation.dictating}
          transcribing={dictation.finishing}
          sendQueued={dictation.sendQueued}
          onToggle={dictation.toggle}
          disabled={!connected || dictation.micHeld}
          startLabel={t("chats_view.dictation_start")}
          stopLabel={t("chats_view.dictation_stop")}
        />
        <span className="flex-1" />
        <button
          type="button"
          onClick={() => setActiveSection("apikeys")}
          title={t("home.model_hint")}
          data-testid="composer-model"
          className="inline-flex h-8 max-w-[280px] items-center gap-1.5 rounded-md px-2 text-meta text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
        >
          <span className="truncate font-medium text-foreground">{engine.providerLabel}</span>
          {engine.model && (
            <span className="truncate font-mono text-micro text-muted-foreground">{engine.model}</span>
          )}
        </button>
        <button
          type="button"
          onClick={send}
          disabled={!canSend}
          aria-label={t("agent_chat.send")}
          data-testid="composer-send"
          className={cn(
            // --primary is a fill and this is the one place in the composer
            // that earns it. There is no step above it in dark mode, so hover
            // answers with opacity rather than a colour that does not exist.
            "inline-flex h-8 w-8 items-center justify-center rounded-md transition-opacity",
            canSend
              ? "bg-primary text-primary-foreground hover:opacity-90"
              : "bg-secondary text-faint-foreground",
          )}
        >
          <ArrowUp className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
