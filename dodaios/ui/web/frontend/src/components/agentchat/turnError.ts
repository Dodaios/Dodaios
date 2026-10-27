import { fill } from "@/i18n";

/** Backend turn-failure codes the chat shows as a sentence, not a raw identifier. */
const TURN_ERROR_CODES = new Set([
  "mandated_tool_unfulfilled",
  "unbacked_action_claim",
  "guarded_response",
  "delegation_continuation_limit",
]);

/**
 * A plan's allowance is used up (a subscription's usage limit, a daily
 * quota). Not a short rate limit: waiting a few seconds never helps. The
 * last pattern is the wording turns stored before the gateway told the
 * subscription's usage limit apart from a rate limit.
 */
const USAGE_LIMIT = [
  /usage limit/i,
  /usage_limit/i,
  /allowance (?:is )?used up/i,
  /allowance resets/i,
  /^openai-codex returned HTTP 429\b/i,
];

/** The conversation is longer than the model's context window, in any runtime's words. */
const CONTEXT_FULL = [
  /context window exceeded/i,
  /no longer fits this model's context window/i,
  /context[ _]length[ _]exceeded/i,
  /context overflow/i,
  /prompt is too long/i,
  /exceeds the model's context/i,
];

/** The UTC reset time the gateway names ("resets at 2026-10-27T15:04:00Z"). */
const RESET_AT = /resets at (\d{4}-\d\d-\d\dT\d\d:\d\d(?::\d\d)?Z)/;

/** A reset time in the person's own clock; the day too when it is not today. */
export function resetTimeLabel(iso: string, now: Date = new Date()): string | null {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return null;
  const sameDay = at.toDateString() === now.toDateString();
  return at.toLocaleString(undefined, sameDay
    ? { hour: "2-digit", minute: "2-digit" }
    : { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

/**
 * The text to show for a failed turn: a known code translated, a spent
 * usage allowance or a full context window as an actionable sentence in the
 * person's language, anything else as sent.
 */
export function turnErrorText(
  error: string | null | undefined,
  t: (key: string) => string,
): string | null {
  if (!error) return null;
  if (TURN_ERROR_CODES.has(error)) return t(`thread_turn.errors.${error}`);
  if (USAGE_LIMIT.some((pattern) => pattern.test(error))) {
    const reset = RESET_AT.exec(error);
    const time = reset ? resetTimeLabel(reset[1]) : null;
    return time
      ? fill(t("thread_turn.errors.usage_limit_until"), { time })
      : t("thread_turn.errors.usage_limit");
  }
  if (CONTEXT_FULL.some((pattern) => pattern.test(error))) return t("thread_turn.errors.context_window");
  return error;
}
