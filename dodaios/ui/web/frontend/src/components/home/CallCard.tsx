import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Captions, Mic, MicOff, PhoneOff, Settings2 } from "lucide-react";

import { useVoiceCall } from "@/components/agentic/useVoiceCall";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { readVoiceInputLevel } from "@/lib/voiceInputLevel";
import { voiceOutputLevelRef } from "@/lib/voiceOutputLevel";
import { useEventStore, type VoiceState } from "@/store/events";
import { useHomeStore } from "@/store/home";

const BARS = 36;
const TRANSCRIPT_KEY = "dodaios.home.call.transcript.v1";

const STATUS_KEY: Record<VoiceState, string> = {
  idle: "agentic_grid.voice_bubble.ready",
  connecting: "voice_state.connecting",
  listening: "agentic_grid.voice_bubble.listening",
  thinking: "agentic_grid.voice_bubble.thinking",
  speaking: "agentic_grid.voice_bubble.speaking",
  paused: "agentic_grid.voice_bubble.paused",
  error: "agentic_grid.voice_bubble.error",
};

function readStoredTranscript(): boolean {
  try {
    return localStorage.getItem(TRANSCRIPT_KEY) === "on";
  } catch {
    return false;
  }
}

/** Bars that follow the voice: the person's while listening, the assistant's while speaking. */
function CallWave({ state }: { state: VoiceState }) {
  const ref = useRef<HTMLCanvasElement | null>(null);
  const stateRef = useRef(state);
  stateRef.current = state;
  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext?.("2d");
    if (!canvas || !ctx) return;
    const still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    const levels = new Array<number>(BARS).fill(0);
    let frame = 0;
    let last = 0;
    const draw = (now: number) => {
      frame = requestAnimationFrame(draw);
      if (now - last < 50) return;
      last = now;
      const current = stateRef.current;
      const level = current === "speaking"
        ? (voiceOutputLevelRef.current ?? 0.35 + 0.25 * Math.sin(now / 140))
        : current === "listening" ? readVoiceInputLevel(now) : 0;
      levels.shift();
      levels.push(still ? 0.15 : Math.max(0, Math.min(1, level)));
      const dpr = window.devicePixelRatio || 1;
      const width = canvas.clientWidth;
      const height = canvas.clientHeight;
      if (canvas.width !== width * dpr) { canvas.width = width * dpr; canvas.height = height * dpr; }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = getComputedStyle(canvas).color;
      const step = width / BARS;
      levels.forEach((value, i) => {
        const h = Math.max(2, value * height);
        ctx.globalAlpha = 0.35 + 0.65 * (i / BARS);
        ctx.fillRect(i * step + step * 0.3, (height - h) / 2, Math.max(1.5, step * 0.4), h);
      });
    };
    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, []);
  return <canvas ref={ref} aria-hidden className="h-6 w-full text-foreground" />;
}

function RoundButton({ label, onClick, pressed, danger, disabled, testId, children }: {
  label: string; onClick: () => void; pressed?: boolean; danger?: boolean; disabled?: boolean;
  testId: string; children: React.ReactNode;
}) {
  return (
    <button type="button" onClick={onClick} disabled={disabled} aria-label={label} title={label}
      aria-pressed={pressed} data-testid={testId}
      className={cn(
        "inline-flex h-9 w-9 items-center justify-center rounded-full transition-colors disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        danger ? "bg-destructive text-destructive-foreground hover:bg-destructive/85"
          : pressed ? "bg-foreground text-background"
            : "bg-secondary text-foreground hover:bg-secondary/70",
      )}>
      {children}
    </button>
  );
}

/**
 * The running call, as a small card over the conversation.
 *
 * A call does not leave the conversation: what is said lands in it as
 * ordinary messages (agent_chat/voice_mirror.py), and this card only shows
 * that a call runs and holds its controls — voice settings, the live
 * transcript, the microphone, hang up. It disappears with the call.
 */
export function CallCard() {
  const t = useT();
  const assistantName = useEventStore((s) => s.assistantName);
  const voiceState = (useEventStore((s) => s.voiceState) ?? "idle") as VoiceState;
  const setActiveSection = useEventStore((s) => s.setActiveSection);
  const pushToast = useEventStore((s) => s.pushToast);
  const transcription = useEventStore((s) => s.transcription);
  const transcriptionFinal = useEventStore((s) => s.transcriptionFinal);
  const transcript = useHomeStore((s) => s.transcript);
  const liveReply = useHomeStore((s) => s.liveReply);
  const { active, busy, connecting, toggleCall } = useVoiceCall();
  const [muted, setMuted] = useState(false);
  const [showTranscript, setShowTranscript] = useState(readStoredTranscript);
  // A flip answers with the new state; an older read must not undo it.
  const flipped = useRef(false);
  const live = active || connecting;

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

  const toggleTranscript = useCallback(() => {
    setShowTranscript((on) => {
      try { localStorage.setItem(TRANSCRIPT_KEY, on ? "off" : "on"); } catch { /* keep it for this visit */ }
      return !on;
    });
  }, []);

  const lines = useMemo(
    () => transcript.filter((line) => line.who !== "steps" && line.text.trim()).slice(-4),
    [transcript],
  );
  const caption = transcription && !transcriptionFinal ? transcription : "";
  const lastText = lines[lines.length - 1]?.text ?? "";
  const answer = liveReply && liveReply !== lastText ? liveReply : "";

  if (!live) return null;
  const name = assistantName || t("agentic_grid.voice_bubble.assistant_fallback");
  return (
    <div data-testid="call-card" data-state={voiceState} role="region" aria-label={fill(t("home.call.label"), { name })}
      className="pointer-events-auto absolute right-3 top-3 z-20 w-[244px] rounded-2xl border border-border bg-card p-3 shadow-lg">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-sm font-medium text-foreground-strong">{name}</span>
        <span className="shrink-0 text-xs text-muted-foreground">
          {muted ? t("home.call.muted") : t(STATUS_KEY[voiceState] ?? STATUS_KEY.idle)}
        </span>
      </div>
      <div className="mt-2"><CallWave state={muted && voiceState === "listening" ? "idle" : voiceState} /></div>
      {showTranscript && (lines.length > 0 || caption || answer) && (
        <div data-testid="call-transcript" aria-live="polite"
          className="mt-2 max-h-40 space-y-1 overflow-y-auto border-t border-border pt-2 text-xs leading-snug">
          {lines.map((line) => (
            <p key={line.id} className={line.who === "user" ? "text-muted-foreground" : "text-foreground"}>{line.text}</p>
          ))}
          {answer && <p className="text-foreground">{answer}</p>}
          {caption && <p className="italic text-muted-foreground">{caption}</p>}
        </div>
      )}
      <div className="mt-3 flex items-center justify-between">
        <RoundButton label={t("home.call.settings")} onClick={() => setActiveSection("voice-api-keys")} testId="call-settings">
          <Settings2 className="h-4 w-4" aria-hidden />
        </RoundButton>
        <RoundButton label={showTranscript ? t("home.call.hide_transcript") : t("home.call.show_transcript")}
          onClick={toggleTranscript} pressed={showTranscript} testId="call-transcript-toggle">
          <Captions className="h-4 w-4" aria-hidden />
        </RoundButton>
        <RoundButton label={muted ? t("home.call.unmute") : t("home.call.mute")} onClick={toggleMute}
          pressed={muted} testId="call-mute">
          {muted ? <MicOff className="h-4 w-4" aria-hidden /> : <Mic className="h-4 w-4" aria-hidden />}
        </RoundButton>
        <RoundButton label={t("agentic_grid.voice_bubble.hang_up_title")} onClick={() => void toggleCall()}
          danger disabled={busy || !active} testId="call-hang-up">
          <PhoneOff className="h-4 w-4" aria-hidden />
        </RoundButton>
      </div>
    </div>
  );
}
