/**
 * Plain-words reasons for unattended work that did not run.
 *
 * The backend sends a stable reason code (a routine run's `skipped` step and
 * its chat notice, an agent's `last_review` record); the words live in the
 * locale files so every reader gets them in their own language. A record
 * without a known code falls back to the English sentence the server wrote.
 */

type T = (key: string) => string;

/** `{name}` placeholders; a missing provider drops its "({provider})" slot. */
function fillReason(template: string, provider: string): string {
  const text = provider ? template : template.replace(/\s*[(（]\{provider\}[)）]/g, "");
  return text.replace(/\{provider\}/g, provider);
}

/** Why a routine run was skipped (codes from `dodaios/tasks/runner.py::skip_code`). */
export function routineSkipReason(t: T, code: unknown, provider: unknown, fallback = ""): string {
  const name = typeof provider === "string" ? provider : "";
  if (code === "api_key_seat") return fillReason(t("society.chat.skip_api_key_seat"), name);
  if (code === "no_capacity" || !fallback) return t("society.chat.skip_no_capacity");
  return fallback;
}

/** Why the last learning review got no answer (codes from `dodaios/society/review.py`). */
export function reviewWaitReason(t: T, code: unknown, provider: unknown, fallback = ""): string {
  const name = typeof provider === "string" ? provider : "";
  if (code === "api_key_seat" || code === "no_seat" || code === "seat_failed") {
    return fillReason(t(`society.profile_card.review_reason_${code}`), name);
  }
  return fallback;
}

/** The headline of a `society_result` chat notice. */
export function societyResultHeadline(t: T, item: { status: string; agentName: string; data?: Record<string, unknown> }): string {
  const agent = item.agentName || t("society.chat.result_agent");
  if (item.status === "skipped") {
    const routine = typeof item.data?.routine === "string" ? item.data.routine : "";
    return routine
      ? t("society.chat.result_skipped").replace("{0}", agent).replace("{1}", routine)
      : t("society.chat.result_skipped_run").replace("{0}", agent);
  }
  return t(item.status === "done" ? "society.chat.result_done" : "society.chat.result_blocked").replace("{0}", agent);
}

/** The body of a `society_result` notice: a skipped run says why in the reader's words. */
export function societyResultText(t: T, item: { status: string; text: string; data?: Record<string, unknown> }): string {
  if (item.status !== "skipped" || !item.data?.reason_code) return item.text;
  return routineSkipReason(t, item.data.reason_code, item.data.provider, item.text);
}
