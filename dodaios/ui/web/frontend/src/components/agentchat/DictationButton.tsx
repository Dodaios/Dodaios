/**
 * The composer's microphone: one control that shows where a dictation stands.
 *
 * Idle it is a plain mic icon. Pressed, it grows in place into a pill that
 * shows everything a live dictation owes the person: a waveform driven by the
 * real microphone level, the elapsed time, and the Stop right where the
 * finger already is. After Stop it stays a pill, now with a spinner and a
 * short line, for as long as the recording is being transcribed, so the wait
 * for the text is never a blank moment.
 *
 * Everything it shows is real. `dictating` and `transcribing` come from the
 * dictation state the event bus drives; the clock counts from the moment
 * `dictating` went true; the bars read `readVoiceInputLevel()`, the level the
 * backend streams from the very microphone the dictation records
 * (`audio.level` frames). With no fresh sample (a muted device) the bars
 * rest flat instead of inventing motion.
 *
 * Recording is green, not red: a live microphone is a state, not a fault, and
 * the palette keeps `--destructive` for faults (see
 * components/VoiceIndicator.tsx). Transcribing is neutral: the microphone is
 * closed and nothing is being heard any more.
 */
import { useEffect, useRef, useState } from "react";
import { Loader2, Mic, Square } from "lucide-react";

import { useT } from "@/i18n";
import { readVoiceInputLevel } from "@/lib/voiceInputLevel";
import { cn } from "@/lib/utils";

/** Bars in the waveform; the newest sample enters on the right. */
const BAR_COUNT = 18;
/** How often the waveform scrolls one bar, in ms. */
const STEP_MS = 60;
/** Resting height of a silent bar, as a fraction of the full height. */
const REST = 0.14;

/** "0:07", "1:42" — mm:ss with no leading hour nobody dictates for. */
export function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

/**
 * The live waveform. Written straight to the DOM from one animation frame
 * loop: the level arrives ~30 times a second, and routing that through React
 * state would re-render the whole composer on every sample.
 */
function Waveform() {
  const barsRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const host = barsRef.current;
    if (!host) return;
    const bars = Array.from(host.children) as HTMLElement[];
    const history = new Array<number>(bars.length).fill(0);
    let frame = 0;
    let last = 0;
    let peak = 0;
    const tick = (now: number) => {
      // Hold the loudest sample of each step so a short syllable between two
      // steps still shows up as a bar instead of being skipped.
      peak = Math.max(peak, readVoiceInputLevel(now));
      if (now - last >= STEP_MS) {
        last = now;
        history.shift();
        history.push(peak);
        peak = 0;
        for (let i = 0; i < bars.length; i += 1) {
          const bar = bars[i];
          if (bar) bar.style.transform = `scaleY(${REST + (1 - REST) * (history[i] ?? 0)})`;
        }
      }
      frame = window.requestAnimationFrame(tick);
    };
    frame = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(frame);
  }, []);

  return (
    <span
      ref={barsRef}
      aria-hidden
      data-testid="dictation-waveform"
      className="flex h-4 items-center gap-[2px]"
    >
      {Array.from({ length: BAR_COUNT }, (_, i) => (
        <span
          key={i}
          className="h-full w-[2px] origin-center rounded-full bg-success transition-transform duration-75 ease-out"
          style={{ transform: `scaleY(${REST})` }}
        />
      ))}
    </span>
  );
}

export interface DictationButtonProps {
  dictating: boolean;
  /** The microphone is closed and the recording is being transcribed. */
  transcribing?: boolean;
  /** Send was pressed meanwhile: the message goes out when the text is here. */
  sendQueued?: boolean;
  onToggle: () => void;
  disabled?: boolean;
  /** Label of the idle button (differs per surface: "Dictate" / "Record"). */
  startLabel: string;
  stopLabel: string;
  /** Corner shape of the idle button, to match its neighbours. */
  shape?: "round" | "square";
  className?: string;
  /**
   * Classes for the idle button only: a size that fits the microphone glyph
   * would crush the wider pills (dot, wave, timer and stop; spinner and line).
   */
  idleClassName?: string;
}

export function DictationButton({
  dictating,
  transcribing = false,
  sendQueued = false,
  onToggle,
  disabled,
  startLabel,
  stopLabel,
  shape = "square",
  className,
  idleClassName,
}: DictationButtonProps) {
  const t = useT();
  const startedRef = useRef(0);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!dictating) {
      startedRef.current = 0;
      setElapsed(0);
      return;
    }
    startedRef.current = Date.now();
    setElapsed(0);
    const id = window.setInterval(() => setElapsed(Date.now() - startedRef.current), 500);
    return () => window.clearInterval(id);
  }, [dictating]);

  if (!dictating && transcribing) {
    // No Stop here: the recording is over and its text cannot be called back.
    return (
      <div
        role="status"
        aria-live="polite"
        data-testid="dictation-transcribing"
        className={cn(
          "inline-flex h-8 shrink-0 items-center gap-2 whitespace-nowrap rounded-full border border-border bg-secondary px-3 text-xs text-foreground/80",
          "motion-safe:animate-in motion-safe:fade-in-0 motion-safe:duration-150",
          className,
        )}
      >
        <Loader2 className="h-3.5 w-3.5 shrink-0 motion-safe:animate-spin" aria-hidden />
        <span>
          {t(sendQueued ? "chats_view.dictation_send_queued" : "chats_view.dictation_transcribing")}
        </span>
      </div>
    );
  }

  if (!dictating) {
    return (
      <button
        type="button"
        // Focus leaving a text field for THIS button still dictates into
        // that field (lib/dictationTarget.ts).
        data-jarvis-dictation-trigger
        data-testid="dictation-button"
        onClick={onToggle}
        disabled={disabled}
        aria-label={startLabel}
        title={startLabel}
        className={cn(
          "inline-flex h-8 w-8 shrink-0 items-center justify-center text-muted-foreground transition-colors",
          "hover:bg-secondary hover:text-foreground disabled:opacity-50",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-strong",
          shape === "round" ? "rounded-full" : "rounded-lg",
          className,
          idleClassName,
        )}
      >
        <Mic className="h-4 w-4" aria-hidden />
      </button>
    );
  }

  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="dictation-status"
      className={cn(
        "inline-flex h-8 shrink-0 items-center gap-2 rounded-full border border-success/35 bg-success/10 pl-3 pr-1",
        "motion-safe:animate-in motion-safe:fade-in-0 motion-safe:zoom-in-95 motion-safe:duration-150",
        className,
      )}
    >
      <span className="sr-only">{t("chats_view.dictation_listening")}</span>
      <span className="relative flex h-2 w-2 shrink-0" aria-hidden>
        <span className="absolute inline-flex h-full w-full rounded-full bg-success/60 motion-safe:animate-ping" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-success" />
      </span>
      <Waveform />
      <span className="w-8 shrink-0 text-right font-mono text-micro tabular-nums text-muted-foreground">
        {formatElapsed(elapsed)}
      </span>
      <button
        type="button"
        data-jarvis-dictation-trigger
        data-testid="dictation-stop"
        onClick={onToggle}
        aria-label={stopLabel}
        title={stopLabel}
        className={cn(
          "inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-success text-background transition-opacity",
          "hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-success/50",
        )}
      >
        <Square className="h-2.5 w-2.5 fill-current" aria-hidden />
      </button>
    </div>
  );
}
