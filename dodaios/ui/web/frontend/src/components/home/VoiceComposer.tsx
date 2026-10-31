import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Keyboard, Loader2, Mic, Paperclip, Sparkles } from "lucide-react";
import { ChatAttachmentStrip } from "@/components/agentchat/ChatAttachmentStrip";
import { releaseHeldFiles, useChatAttachments } from "@/components/agentchat/useChatAttachments";
import { useEventStore } from "@/store/events";
import { useHomeStore } from "@/store/home";
import { useVoiceCall } from "@/components/agentic/useVoiceCall";
import { useVoiceReadiness } from "@/hooks/useVoiceReadiness";
import { useVoiceEngineDisplay } from "@/hooks/useVoiceEngineDisplay";
import { usePromptMode } from "@/hooks/usePromptMode";
import { fetchVoiceComposerSession, submitVoiceComposer } from "@/lib/voiceApi";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { attachFilePasteBridge } from "@/lib/editActions";

/** One voice bar; typing and files enter the existing call. */
export function VoiceComposer({ hint, onExit }: { hint: string; onExit?: () => void }) {
  const t = useT();
  const assistantName = useEventStore((s) => s.assistantName);
  const setActiveSection = useEventStore((s) => s.setActiveSection);
  const pushToast = useEventStore((s) => s.pushToast);
  const { connected } = useVoiceReadiness();
  const engine = useVoiceEngineDisplay();
  const promptMode = usePromptMode();
  const { active, busy, connecting, toggleCall } = useVoiceCall();
  const [composerSession, setComposerSession] = useState<string | null>(null);
  const [value, setValue] = useState("");
  const [sending, setSending] = useState(false);
  const requestRef = useRef<{ signature: string; id: string } | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!active) { setComposerSession(null); return; }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const refresh = async () => {
      try {
        const id = await fetchVoiceComposerSession();
        if (!cancelled) setComposerSession(id);
      } catch {
        // A transient status error must not erase a draft or end the call.
      } finally {
        if (!cancelled) timer = setTimeout(refresh, 2000);
      }
    };
    void refresh();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [active]);

  const onAttachProblem = useCallback(
    (message: string, severity: "warning" | "error") => pushToast(severity, message),
    [pushToast],
  );
  const files = useChatAttachments(
    { sessionId: null, voiceSessionId: composerSession ?? undefined,
      cwd: "", provider: "", surface: "jarvis" },
    onAttachProblem,
    { owner: useHomeStore, key: composerSession ?? "pending-voice" },
  );

  useEffect(() => {
    const input = inputRef.current;
    if (!input || !composerSession) return;
    return attachFilePasteBridge(input, { pastePaths: files.attachPaths });
  }, [composerSession, files.attachPaths]);

  const onCall = useCallback(() => {
    if (busy || connecting) return;
    void toggleCall();
  }, [busy, connecting, toggleCall]);

  const onPromptMode = useCallback(() => {
    promptMode.toggle().catch((err: unknown) => {
      const detail = err instanceof Error && err.message ? err.message : "";
      pushToast("error", detail || t("home.prompt_mode_failed"));
    });
  }, [promptMode, pushToast, t]);

  async function onSend() {
    if (!active || sending || files.analyzing > 0) return;
    const content = value.trim();
    if (!content && files.attachments.length === 0) return;
    setSending(true);
    let held: ReturnType<typeof files.take> | null = null;
    try {
      const sessionId = composerSession ?? await fetchVoiceComposerSession();
      if (!sessionId) throw new Error("The active voice call is not ready for text input.");
      setComposerSession(sessionId);
      const signature = JSON.stringify([
        sessionId, content, files.attachments.map((item) => item.reference),
      ]);
      if (requestRef.current?.signature !== signature)
        requestRef.current = { signature, id: crypto.randomUUID() };
      const requestId = requestRef.current.id;
      held = files.take();
      await submitVoiceComposer(sessionId, content, held.attachments, requestId);
      requestRef.current = null;
      setValue((current) => current.trim() === content ? "" : current);
      releaseHeldFiles(held);
    } catch (error) {
      if (held) files.restore(held);
      pushToast("error", (error as Error).message);
    } finally {
      setSending(false);
    }
  }

  const onInputKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== "Enter" || event.nativeEvent.isComposing) return;
    event.preventDefault();
    void onSend();
  };

  const promptModeTitle =
    promptMode.enabled === true ? t("home.prompt_mode_on") : t("home.prompt_mode_off");
  const live = active || connecting;

  return (
    <div className="flex flex-col gap-1.5" data-testid="voice-composer" data-active={active || undefined}>
      <div data-tour="voice-bar"
        className={cn("rounded-[22px] border border-border bg-card px-2.5 py-2.5 shadow-rim",
          files.dragging && "border-primary")}>
        <div className="flex items-center gap-1">
          {onExit && (
            <button type="button" onClick={() => active ? inputRef.current?.focus() : onExit()}
              data-testid="voice-mode-exit"
              aria-label={active ? t("agent_chat.input_placeholder") : t("assistant_chat.voice_exit")}
              title={active ? t("agent_chat.input_placeholder") : fill(t("assistant_chat.voice_exit_hint"), { name: assistantName })}
              className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              <Keyboard className="h-4 w-4" aria-hidden />
            </button>
          )}
          <input ref={inputRef} type="text" value={value}
            {...(composerSession ? files.dragHandlers : {})}
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={onInputKeyDown}
            onPaste={(event) => { if (composerSession) files.onPaste(event); }}
            placeholder={hint} aria-label={t("agent_chat.input_placeholder")}
            data-testid="voice-input"
            className="h-8 min-w-0 flex-1 bg-transparent px-1.5 text-reading text-foreground placeholder:text-muted-foreground focus:outline-none" />
          <input ref={fileInputRef} type="file" multiple className="sr-only" tabIndex={-1}
            onChange={(event) => {
              const picked = Array.from(event.currentTarget.files ?? []);
              event.currentTarget.value = "";
              files.attachFiles(picked);
            }} />
          <button type="button" onClick={() => fileInputRef.current?.click()}
            disabled={!composerSession || sending} aria-label={t("agent_chat.attach")}
            title={t("agent_chat.attach_hint")} data-testid="voice-attach"
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground disabled:opacity-50">
            <Paperclip className="h-4 w-4" aria-hidden />
          </button>
          {promptMode.enabled !== null && (
            <button type="button" onClick={onPromptMode} disabled={promptMode.busy}
              aria-pressed={promptMode.enabled} aria-label={promptModeTitle}
              title={promptModeTitle} data-testid="voice-prompt-mode"
              data-on={promptMode.enabled || undefined}
              className={cn("inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full text-xs font-medium transition-colors disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                promptMode.enabled ? "bg-accent-soft px-3 text-accent" : "w-8 justify-center text-muted-foreground hover:bg-secondary hover:text-foreground")}>
              {promptMode.busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Sparkles className="h-4 w-4" aria-hidden />}
              {promptMode.enabled && t("home.prompt_mode_pill")}
            </button>
          )}
          {live ? (
            <button type="button" onClick={onCall} disabled={busy || connecting}
              aria-label={t("home.bar_stop")} title={t("home.bar_stop")} data-testid="voice-call-stop"
              className="ml-0.5 inline-flex h-8 shrink-0 items-center gap-2 rounded-full bg-accent-soft px-3 text-sm font-medium text-accent transition-colors hover:bg-accent/20 disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              <BreathingDots />{t("assistant_chat.voice_stop")}
            </button>
          ) : (
            <button type="button" onClick={onCall} disabled={busy || !connected}
              aria-label={t("home.bar_start")} title={t("home.bar_start")} data-testid="voice-call-start"
              className="ml-0.5 inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full bg-foreground px-3 text-sm font-medium text-background transition-colors hover:bg-foreground/85 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Mic className="h-4 w-4" aria-hidden />}
              {t("assistant_chat.voice_start")}
            </button>
          )}
        </div>
        {(files.attachments.length > 0 || files.analyzing > 0) && (
          <div className="mt-2 border-t border-border pt-2"
            onClick={(event) => {
              // Passive previews return typing to this composer; controls keep their own focus.
              if (event.target instanceof Element &&
                  !event.target.closest('button, a, input, textarea, select, [role="button"], [tabindex], [contenteditable="true"]')) {
                inputRef.current?.focus({ preventScroll: true });
              }
            }}>
            <ChatAttachmentStrip attachments={files.attachments} previews={files.previews}
              analyzing={files.analyzing} onRemove={files.remove} look="thumbnail" />
          </div>
        )}
      </div>
      <div className="flex justify-end px-3">
        <button
          type="button"
          onClick={() => setActiveSection("apikeys")}
          title={t("home.model_hint")}
          data-testid="voice-engine"
          className="inline-flex max-w-[320px] items-center gap-1.5 rounded-full px-2 text-xs font-normal text-muted-foreground/80 transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <span className="truncate">{engine.providerLabel}</span>
          {engine.model && <span className="truncate">{engine.model}</span>}
        </button>
      </div>
    </div>
  );
}

function BreathingDots() {
  return <span className="inline-flex items-center gap-[3px]" aria-hidden>
    {[0, 200, 400].map((delay) => (
      <span key={delay} className="h-1.5 w-1.5 rounded-full bg-current animate-pulse motion-reduce:animate-none"
        style={{ animationDelay: String(delay) + "ms" }} />
    ))}
  </span>;
}
