/**
 * Why the host refused to start a voice conversation, and the sentence for it.
 *
 * Mirrors `VOICE_START_REFUSALS` in `jarvis/speech/start_refusal.py` (parity:
 * `tests/unit/speech/test_voice_start_refusal_parity.py`).
 */
export const VOICE_START_REFUSALS = [
  "busy",
  "muted",
  "dictation",
  "microphone_in_use",
  "microphone",
  "unavailable",
] as const;

export type VoiceStartRefusal = (typeof VOICE_START_REFUSALS)[number];

/**
 * The i18n key of the sentence for a refused start. A reason this build does
 * not know (or none, from an older host) gets the plain "could not start"
 * sentence: the control never names a cause it was not given.
 */
export function voiceStartRefusalKey(reason: string | undefined): string {
  return (VOICE_START_REFUSALS as readonly string[]).includes(reason ?? "")
    ? `agentic_grid.voice_bubble.start_refused.${reason}`
    : "agentic_grid.voice_bubble.start_failed";
}
