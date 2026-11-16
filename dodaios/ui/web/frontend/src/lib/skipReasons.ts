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

/** The ritual a `society_result` notice is the card of; "" for every other notice. */
function ritualTitle(data: Record<string, unknown> | undefined): string {
  return typeof data?.ritual_title === "string" ? data.ritual_title.trim() : "";
}

/** Whether a `society_result` notice is the card of a ritual that started. */
export function isRitualResult(item: { data?: Record<string, unknown> }): boolean {
  return ritualTitle(item.data) !== "";
}

/** The headline of a `society_result` chat notice. */
export function societyResultHeadline(t: T, item: { status: string; agentName: string; data?: Record<string, unknown> }): string {
  // A look of a standing task is labelled with the task, not with who ran it.
  const standing = typeof item.data?.standing_title === "string" ? item.data.standing_title.trim() : "";
  if (standing) {
    const outcome = item.status === "skipped" ? "skipped" : item.status === "done" ? "done" : "blocked";
    return t(`standing.result_${outcome}`).replace("{title}", standing);
  }
  // A ritual's card is labelled with the ritual: that it started, or, on the
  // second card, what was gathered for it after the start or that nothing could
  // be, or which of its steps for the moment did not run.
  const ritual = ritualTitle(item.data);
  if (ritual) {
    const key = item.data?.steps_not_run === true ? "rituals.card_steps_not_run"
      : item.status === "failed" ? "rituals.card_failed"
      : item.data?.late === true ? "rituals.card_late" : "rituals.started";
    // A function, so a "$" in the person's title is not read as a pattern.
    return t(key).replace("{title}", () => ritual);
  }
  const agent = item.agentName || t("society.chat.result_agent");
  if (item.status === "skipped") {
    const routine = typeof item.data?.routine === "string" ? item.data.routine : "";
    return routine
      ? t("society.chat.result_skipped").replace("{0}", agent).replace("{1}", routine)
      : t("society.chat.result_skipped_run").replace("{0}", agent);
  }
  return t(item.status === "done" ? "society.chat.result_done" : "society.chat.result_blocked").replace("{0}", agent);
}

/**
 * The body of a `society_result` notice: a skipped run says why in the
 * reader's words, and a ritual that started before what it wants ready was
 * there ends on the line that the rest follows.
 */
export function societyResultText(t: T, item: { status: string; text: string; data?: Record<string, unknown> }): string {
  if (isRitualResult(item)) {
    if (item.data?.pending !== true) return item.text;
    const pending = t("rituals.card_pending");
    // A paragraph of its own: right under a list it would read as part of the last item.
    return item.text ? `${item.text}\n\n${pending}` : pending;
  }
  if (item.status !== "skipped" || !item.data?.reason_code) return item.text;
  return routineSkipReason(t, item.data.reason_code, item.data.provider, item.text);
}
