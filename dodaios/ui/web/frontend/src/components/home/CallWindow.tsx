import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Mic, MicOff, PhoneOff, Settings2 } from "lucide-react";

import { useVoiceCall } from "@/components/agentic/useVoiceCall";
import { TranscriptLine } from "@/components/home/VoiceStage";
import { VoiceGlow } from "@/components/home/VoiceGlow";
import { PetMark } from "@/components/pets/PetMark";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useStickToBottom } from "@/hooks/useStickToBottom";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { useEventStore, type VoiceState } from "@/store/events";
import { useHomeStore } from "@/store/home";
import "./callWindow.css";

const STATUS_KEY: Record<VoiceState, string> = {
  idle: "agentic_grid.voice_bubble.ready",
  connecting: "voice_state.connecting",
  listening: "agentic_grid.voice_bubble.listening",
  thinking: "agentic_grid.voice_bubble.thinking",
  speaking: "agentic_grid.voice_bubble.speaking",
  paused: "agentic_grid.voice_bubble.paused",
  error: "agentic_grid.voice_bubble.error",
};

const WINDOW = "call-window pointer-events-auto absolute bottom-full z-20 mb-3 flex flex-col overflow-hidden rounded-[20px] bg-background shadow-float";

/** How long the window stays after a call ends, for a reason that arrives a moment later. */
const END_LINGER_MS = 900;
/** How long a failed call's note stays when nobody closes it. */
const PROBLEM_TTL_MS = 2 * 60_000;

/**
 * The call, as a window over the foot of the conversation.
 *
 * A call does not leave the conversation: what is said lands in it as
 * ordinary messages (agent_chat/voice_mirror.py). The window is the call
 * itself, in the look the voice page had: the voice light rising from its
 * lower edge, this call's words as they are said, the assistant's pet, and
 * the microphone and hang-up controls.
 *
 * It opens the moment a call is asked for from this window (before the host
 * answers), and for every call that runs, however it was started. When a
 * call ends on its own (the provider refused it, the connection broke) the
 * window stays and says why, until it is closed, the next call starts, or
 * two minutes have passed: a call that fails must never look like nothing
 * happened. Every call leaves with a short "Call ended", so the reason of a
 * failed one arrives in the same window.
 *
 * Its parent positions it: the window stands on the top edge of the nearest
 * positioned ancestor (`bottom: 100%`), so it is mounted inside the
 * composer's own wrapper.
 */
export function CallWindow() {
  const t = useT();
  const assistantName = useEventStore((s) => s.assistantName);
  const voiceState = (useEventStore((s) => s.voiceState) ?? "idle") as VoiceState;
  const setActiveSection = useEventStore((s) => s.setActiveSection);
  const pushToast = useEventStore((s) => s.pushToast);
  const transcription = useEventStore((s) => s.transcription);
  const transcriptionFinal = useEventStore((s) => s.transcriptionFinal);
  const transcript = useHomeStore((s) => s.transcript);
  const liveReply = useHomeStore((s) => s.liveReply);
  const pending = useHomeStore((s) => s.callPending);
  const problem = useHomeStore((s) => s.callProblem);
  const setCallProblem = useHomeStore((s) => s.setCallProblem);
  const { active, busy, connecting, toggleCall } = useVoiceCall();
  const [muted, setMuted] = useState(false);
  // A flip answers with the new state; an older read must not undo it.
  const flipped = useRef(false);
  const live = active || connecting;

  // The moment the call stopped, noted while rendering so the window is
  // still there on the very render that sees the call gone.
  const wasLive = useRef(false);
  const endedAt = useRef(0);
  if (wasLive.current && !live) endedAt.current = Date.now();
  wasLive.current = live;
  const ending = !live && endedAt.current > 0 && Date.now() - endedAt.current < END_LINGER_MS;
  const [, redraw] = useState(0);
  useEffect(() => {
    if (live || !endedAt.current) return;
    const timer = window.setTimeout(() => redraw((n) => n + 1), END_LINGER_MS + 30);
    return () => window.clearTimeout(timer);
  }, [live]);

  // A note nobody closed goes by itself.
  const problemAt = problem?.at ?? 0;
  useEffect(() => {
    if (!problemAt || live) return;
    const timer = window.setTimeout(() => setCallProblem(null), Math.max(0, problemAt + PROBLEM_TTL_MS - Date.now()));
    return () => window.clearTimeout(timer);
  }, [live, problemAt, setCallProblem]);

  useEffect(() => {
    if (!live) return;
    let alive = true;
    flipped.current = false;
    void fetch("/api/voice/mic-mute")
      .then((r) => (r.ok ? r.json() : null))
      .then((body: { muted?: boolean } | null) => {
        if (alive && !flipped.current && typeof body?.muted === "boolean") setMuted(body.muted);
      },
        () => undefined);
    return () => { alive = false; };
  }, [live]);

  const toggleMute = useCallback(() => {
    flipped.current = true;
    void fetch("/api/voice/mic-mute", { method: "POST" })
      .then(async (r) => {
        if (!r.ok) throw new Error(String(r.status));
        const body = (await r.json()) as { muted?: boolean };
        setMuted(Boolean(body.muted));
      })
      .catch(() => pushToast("error", t("home.call.mute_failed")));
  }, [pushToast, t]);

  // This call's words only: the work behind an answer is in the conversation.
  const lines = useMemo(
    () => transcript.filter((line) => line.who !== "steps" && line.text.trim()),
    [transcript],
  );
  const liveLine = transcription && !transcriptionFinal ? transcription : "";
  const lastLine = lines[lines.length - 1];
  // The answer as it is produced, until its spoken line replaces it.
  const liveAnswer = liveReply && !(lastLine?.who === "assistant" && lastLine.text.startsWith(liveReply)) ? liveReply : "";
  const lastIsAnswer = !liveAnswer && lastLine?.who === "assistant";
  const hasWords = lines.length > 0 || Boolean(liveLine) || Boolean(liveAnswer);

  const { rootRef, contentRef, follow } = useStickToBottom();
  useLayoutEffect(follow, [follow, lines, liveLine, liveAnswer]);

  const name = assistantName || t("agentic_grid.voice_bubble.assistant_fallback");
  const label = fill(t("home.call.label"), { name });
  const openSettings = () => setActiveSection("voice-api-keys");

  if (!live && !pending && !problem && !ending) return null;
  if (!live && !pending && problem) {
    // The note has taken over from "Call ended": closing it closes the window.
    endedAt.current = 0;
    // The call is over and did not end by choice: say so, and say what helps.
    return (
      <section data-testid="call-window" data-state="failed" role="region" aria-label={label} className={WINDOW}>
        <VoiceGlow active={false} className="h-[68%]" />
        <div className="relative flex min-h-0 flex-1 flex-col items-center justify-center gap-3 px-8 text-center" role="alert">
          <PetMark size={64} state="error" />
          <p className="text-[15px] font-semibold text-foreground-strong">{t("home.call.failed")}</p>
          <p className="max-w-[26rem] text-sm text-foreground-secondary [overflow-wrap:anywhere]" data-testid="call-problem">
            {problem.message || t("home.call.failed_unknown")}
          </p>
        </div>
        <footer className="relative flex items-center justify-center gap-3 pb-5 pt-2">
          <button type="button" onClick={openSettings} data-testid="call-settings"
            className="inline-flex h-9 items-center gap-2 rounded-full bg-foreground px-4 text-sm font-medium text-background transition-colors hover:bg-foreground/85 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            <Settings2 className="h-4 w-4" aria-hidden />{t("home.call.settings")}
          </button>
          <button type="button" onClick={() => setCallProblem(null)} data-testid="call-close"
            className="inline-flex h-9 items-center rounded-full bg-secondary px-4 text-sm font-medium text-foreground transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            {t("common.close")}
          </button>
        </footer>
      </section>
    );
  }

  // Asked for and not answered yet reads as connecting, whatever the state says.
  const shown: VoiceState = live ? voiceState : pending ? "connecting" : "idle";
  const ended = !live && !pending;
  const status = ended ? t("home.call.ended") : muted && live ? t("home.call.muted") : t(STATUS_KEY[shown] ?? STATUS_KEY.idle);
  return (
    <section data-testid="call-window" data-state={ended ? "ended" : shown} role="region" aria-label={label} className={WINDOW}>
      {/* The voice light fills the lower part of the window, behind everything. */}
      <VoiceGlow active={active} thinking={shown === "thinking" || shown === "connecting"} className="h-[68%]" />

      <header className="relative flex items-center gap-2.5 px-4 pt-3.5">
        {hasWords && <PetMark size={32} reactive />}
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-foreground-strong">{name}</p>
          <p className="truncate text-xs text-muted-foreground" data-testid="call-status" aria-live="polite">{status}</p>
        </div>
        <button type="button" onClick={openSettings} data-testid="call-settings"
          aria-label={t("home.call.settings")} title={t("home.call.settings")}
          className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          <Settings2 className="h-4 w-4" aria-hidden />
        </button>
      </header>

      {hasWords ? (
        <ScrollArea ref={rootRef} className="relative min-h-0 flex-1" data-testid="call-transcript">
          <div ref={contentRef} className="flex flex-col gap-4 px-5 pb-3 pt-4" aria-live="polite">
            {lines.map((line, i) => (
              <TranscriptLine
                key={line.id}
                who={line.who === "user" ? t("home.transcript_you") : name}
                text={line.text}
                lineId={line.id}
                user={line.who === "user"}
                playbackEligible={active && lastIsAnswer && i === lines.length - 1}
              />
            ))}
            {liveLine && <TranscriptLine who={t("home.transcript_you")} text={liveLine} user live />}
            {liveAnswer && <TranscriptLine who={name} text={liveAnswer} user={false} live playbackEligible={active} />}
          </div>
        </ScrollArea>
      ) : (
        // Nothing said yet: the pet alone, doing what the call is doing.
        <div className="relative flex min-h-0 flex-1 items-center justify-center pb-4" data-testid="call-waiting">
          <PetMark size={72} state={live ? undefined : pending ? "thinking" : "idle"} reactive={live} />
        </div>
      )}

      <footer className="relative flex items-center justify-center gap-4 pb-4 pt-2">
        <button type="button" onClick={toggleMute} disabled={!live} aria-pressed={muted} data-testid="call-mute"
          aria-label={muted ? t("home.call.unmute") : t("home.call.mute")} title={muted ? t("home.call.unmute") : t("home.call.mute")}
          className={cn(
            "inline-flex h-11 w-11 items-center justify-center rounded-full transition-colors disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            muted ? "bg-foreground text-background" : "bg-secondary text-foreground hover:bg-muted",
          )}>
          {muted ? <MicOff className="h-[18px] w-[18px]" aria-hidden /> : <Mic className="h-[18px] w-[18px]" aria-hidden />}
        </button>
        <button type="button" onClick={() => void toggleCall()} disabled={busy || !active} data-testid="call-hang-up"
          aria-label={t("agentic_grid.voice_bubble.hang_up_title")} title={t("agentic_grid.voice_bubble.hang_up_title")}
          className="inline-flex h-11 w-16 items-center justify-center rounded-full bg-destructive text-destructive-foreground transition-colors hover:bg-destructive/85 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          <PhoneOff className="h-[18px] w-[18px]" aria-hidden />
        </button>
      </footer>
    </section>
  );
}
