/** Backend turn-failure codes the chat shows as a sentence, not a raw identifier. */
const TURN_ERROR_CODES = new Set([
  "mandated_tool_unfulfilled",
  "unbacked_action_claim",
  "guarded_response",
  "delegation_continuation_limit",
]);

/** The text to show for a failed turn: a known code translated, anything else as sent. */
export function turnErrorText(
  error: string | null | undefined,
  t: (key: string) => string,
): string | null {
  if (!error) return null;
  return TURN_ERROR_CODES.has(error) ? t(`thread_turn.errors.${error}`) : error;
}
