import { useT } from "@/i18n";
import { useEventStore } from "@/store/events";
import { useVoiceMode } from "@/hooks/useVoiceMode";
import { useVoiceReadiness } from "@/hooks/useVoiceReadiness";

/**
 * The voice status dot, in the three colours a status is allowed to have.
 *
 * It used to run on four shades of grey, which is a ramp nobody can read:
 * "listening" and "idle" differed by an opacity, and the loudest value on the
 * ramp was "paused". Colour carries exactly three meanings in this product, so
 * the dot carries them too: green while the voice path is actually doing
 * something, red when it broke, amber while it is only half up, and neutral
 * ink when it is simply at rest.
 */
const VOICE_STATE_STYLE: Record<string, { dot: string; pulse: boolean }> = {
  // "Ready" IS a life state: the stack is up and waiting for the wake word.
  idle: { dot: "bg-success", pulse: false },
  listening: { dot: "bg-success", pulse: true },
  thinking: { dot: "bg-success", pulse: true },
  speaking: { dot: "bg-success", pulse: true },
  // The user muted or suspended the pipeline: neither working nor broken.
  paused: { dot: "bg-muted-foreground", pulse: false },
  error: { dot: "bg-destructive", pulse: false },
  // The surface's own "a realtime transport is negotiating" phase, which no
  // backend state covers. Half up, so amber.
  connecting: { dot: "bg-warning", pulse: true },
};

export interface VoiceIndicator {
  /** The voice path is still coming up: draw a spinner, not a dot. */
  spinning: boolean;
  /** The dot's colour class and whether it pulses. */
  dot: string;
  pulse: boolean;
  /** The state in words. */
  label: string;
  /** Anything but a connected, warmed-up pipeline at rest. */
  news: boolean;
}

/**
 * The voice path's state, one answer for every place that shows it: the
 * caption's Dodaios switch draws the dot, the sidebar spells out the news.
 *
 * The window connects in ~1 s but voice warms up ~20 s in the background; in
 * that gap the state is "starting", not "ready". Disconnected outranks warmup,
 * and a negotiating realtime transport outranks the pipeline's own state: the
 * subscription route needs 15-45 s before it can hear anything, and showing
 * the stale pre-call state there made a live handshake look frozen.
 */
export function useVoiceIndicator(): VoiceIndicator {
  const t = useT();
  const voiceState = useEventStore((s) => s.voiceState);
  const voiceMode = useVoiceMode();
  const { connected, voiceWarming, bootWarming, warming } = useVoiceReadiness();
  const spinning = warming || voiceMode.connecting;
  const style = voiceMode.connecting
    ? VOICE_STATE_STYLE.connecting
    : VOICE_STATE_STYLE[voiceState] ?? VOICE_STATE_STYLE.idle;
  const label = !connected
    ? bootWarming
      ? t("voice_state.booting")
      : t("voice_state.offline")
    : voiceWarming
      ? t("voice_state.starting")
      : voiceMode.connecting
        ? t("voice_state.connecting")
        : t(`voice_state.${voiceState}`);
  return {
    spinning,
    dot: style.dot,
    pulse: style.pulse,
    label,
    news: !connected || spinning || voiceState !== "idle",
  };
}
