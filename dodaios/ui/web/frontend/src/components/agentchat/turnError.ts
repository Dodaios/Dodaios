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
/** A vendor's own wording ("try again at Oct 15th, 2026 3:37 PM"). */
const TRY_AGAIN_AT = /try again at ([A-Z][a-z]{2,8} \d{1,2})(?:st|nd|rd|th)?(, \d{4} \d{1,2}:\d\d(?: ?[AP]M)?)/;

/**
 * Runtime failures the backend maps to short reasons
 * (``dodaios/agent_chat/turn_errors.py``); the patterns also match the raw
 * wording turns stored before that mapping existed.
 */
const RUNTIME_UPDATING = [/schema version[\s\S]*doctor --fix/i, /^The agent runtime is updating its data\b/];
const STILL_STARTING = [/has not completed startup inspection/i, /^The agent is still starting up\b/];
const APP_RESTARTED = /^(?:The app|\w+) restarted while this turn was running\b/;
const STALL_LEGACY = /^([\w.-]+-cli) stopped responding \(nothing for (\d+) minutes?\)/;
const STALL = /^(.+?) got no reply from the (local )?model for (\d+) minutes?, so the turn was stopped/;
const INTERNAL = /^(?:(.+?) hit an internal error and stopped this turn\b|Internal error(?::\s*([\s\S]*))?$)/;
const CRASHED = /^(.+?) stopped with an error\. Try again\.$/;
/** A log line ("2026-10-27 17:05:19 [INFO] ..."), a traceback, or the agent's own prompt. */
const RAW_MARKERS = /Traceback \(most recent call last\)|\[(?:INFO|DEBUG|WARNING|ERROR)\]|<jarvis_identity>|^\s*\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d/m;

/** The name the person knows a runtime by. */
const RUNNER_LABELS: Record<string, string> = {
  "hermes-cli": "Hermes",
  "openclaw-cli": "OpenClaw",
  "claude-cli": "Claude Code",
  "codex-cli": "Codex",
  "agy-cli": "Antigravity",
  "grok-cli": "Grok Build",
  "opencode-cli": "OpenCode",
  "kimi-cli": "Kimi Code",
  "glm-cli": "GLM Coding Plan",
  "dsh-cli": "DeepSeek Harness",
  "cursor-cli": "Cursor CLI",
};

const DETAILS_MAX = 2000;

/**
 * Raw runtime output made safe to show behind "Technical details": no blocks
 * of the agent's own prompt, no URLs (they can carry tokens or name internal
 * endpoints), no keys, and the person's home folder as "~".
 */
export function redactDetails(text: string): string {
  let out = text
    .replace(/msg='[^'\n]*'?/g, "msg=[removed]")
    .replace(/<(jarvis_[a-z_]+|system|system_prompt|instructions)>[\s\S]*?(?:<\/\1>|(?=\n[ \t]*\d{4}-\d\d-\d\d[ T]\d\d:\d\d)|$(?![\s\S]))/g, "[agent instructions removed]")
    .replace(/\b(?:sk|pk|rk|ghp|gho|xox[abp])[-_][A-Za-z0-9_-]{8,}|\bBearer\s+[A-Za-z0-9._~+/=-]{8,}/gi, "[redacted]")
    .replace(/\b[a-z][a-z0-9+.-]*:\/\/[^\s'"<>)]+/gi, "[url]")
    // A profile folder may contain spaces ("C:\Users\First Last\...").
    .replace(/\b[A-Z]:[\\/]+Users[\\/]+[^\\/\r\n'"<>|:*?]+(?=[\\/])/gi, "~")
    .replace(/\b[A-Z]:[\\/]+Users[\\/]+[^\\/\s'"]+/gi, "~")
    .replace(/\/(?:home|Users)\/[^/\r\n'"<>|:*?]+(?=\/)/g, "~")
    .replace(/\/(?:home|Users)\/[^/\s'"]+/g, "~");
  out = out.split(/\r?\n/).map((line) => line.trimEnd()).join("\n").trim();
  return out.length > DETAILS_MAX ? `…${out.slice(-DETAILS_MAX)}` : out;
}

/** A reset time in the person's own clock; the day too when it is not today. */
export function resetTimeLabel(iso: string, now: Date = new Date()): string | null {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return null;
  const sameDay = at.toDateString() === now.toDateString();
  return at.toLocaleString(undefined, sameDay
    ? { hour: "2-digit", minute: "2-digit" }
    : { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

/** When a spent allowance comes back, if the error says. */
function resetDate(error: string): Date | null {
  const iso = RESET_AT.exec(error);
  if (iso) {
    const at = new Date(iso[1]);
    return Number.isNaN(at.getTime()) ? null : at;
  }
  const vendor = TRY_AGAIN_AT.exec(error);
  if (vendor) {
    const at = new Date(`${vendor[1]}${vendor[2]}`.replace(/(\d)([AP]M)$/, "$1 $2"));
    return Number.isNaN(at.getTime()) ? null : at;
  }
  return null;
}

/** What the failed-turn card shows. */
export interface TurnErrorView {
  /** One short sentence in the person's language. */
  reason: string;
  /** Redacted raw output for the collapsed "Technical details", if any. */
  details: string | null;
  /** False when sending the message again cannot work yet (a spent allowance). */
  retryable: boolean;
}

function nameOf(raw: string | undefined, t: (key: string) => string): string {
  if (!raw || raw === "The agent" || raw === "The model") return t("thread_turn.errors.the_agent");
  return RUNNER_LABELS[raw] ?? raw;
}

/**
 * The failed-turn card for an error: a known code translated, a runtime
 * failure as a short readable reason (its raw output only as redacted
 * details), a spent usage allowance or a full context window as an
 * actionable sentence, anything else as sent.
 */
export function turnErrorView(
  error: string | null | undefined,
  rawDetails: string | null | undefined,
  t: (key: string) => string,
  now: Date = new Date(),
): TurnErrorView | null {
  if (!error) return null;
  const details = rawDetails ? redactDetails(rawDetails) || null : null;
  const view = (reason: string, extra: string | null = details, retryable = true): TurnErrorView =>
    ({ reason, details: extra, retryable });
  if (TURN_ERROR_CODES.has(error)) return view(t(`thread_turn.errors.${error}`));
  if (USAGE_LIMIT.some((pattern) => pattern.test(error))) {
    const reset = resetDate(error);
    const time = reset ? resetTimeLabel(reset.toISOString(), now) : null;
    const reason = time
      ? fill(t("thread_turn.errors.usage_limit_until"), { time })
      : t("thread_turn.errors.usage_limit");
    // Retry cannot succeed before the allowance resets.
    return view(reason, details, !(reset && reset.getTime() > now.getTime()));
  }
  if (CONTEXT_FULL.some((pattern) => pattern.test(error))) return view(t("thread_turn.errors.context_window"));
  if (RUNTIME_UPDATING.some((pattern) => pattern.test(error))) {
    return view(t("thread_turn.errors.runtime_updating"), details ?? (error.startsWith("The agent runtime") ? null : redactDetails(error)));
  }
  if (STILL_STARTING.some((pattern) => pattern.test(error))) {
    return view(t("thread_turn.errors.still_starting"), details ?? (error.startsWith("The agent is") ? null : redactDetails(error)));
  }
  if (APP_RESTARTED.test(error)) return view(t("thread_turn.errors.app_restarted"));
  const legacyStall = STALL_LEGACY.exec(error);
  if (legacyStall) {
    return view(fill(t("thread_turn.errors.stall"), { runtime: nameOf(legacyStall[1], t), minutes: legacyStall[2] }));
  }
  const stall = STALL.exec(error);
  if (stall) {
    const key = stall[2] ? "thread_turn.errors.stall_local" : "thread_turn.errors.stall";
    return view(fill(t(key), { runtime: nameOf(stall[1], t), minutes: stall[3] }));
  }
  const internal = INTERNAL.exec(error);
  if (internal) {
    const rest = internal[2]?.trim();
    return view(fill(t("thread_turn.errors.internal"), { runtime: nameOf(internal[1], t) }), details ?? (rest ? redactDetails(rest) : null));
  }
  const crashed = CRASHED.exec(error);
  if (crashed) return view(fill(t("thread_turn.errors.crashed"), { runtime: nameOf(crashed[1], t) }));
  // A dump stored before the backend mapped it: never on the card itself.
  if (RAW_MARKERS.test(error) || error.split(/\r?\n/).filter((line) => line.trim()).length > 3) {
    return view(fill(t("thread_turn.errors.crashed"), { runtime: t("thread_turn.errors.the_agent") }), details ?? redactDetails(error));
  }
  const [head, ...rest] = error.split(" ");
  if (rest.length && RUNNER_LABELS[head]) return view(`${RUNNER_LABELS[head]} ${rest.join(" ")}`);
  return view(error);
}

/** The card's reason alone (the work trace and thread views show only that). */
export function turnErrorText(
  error: string | null | undefined,
  t: (key: string) => string,
): string | null {
  return turnErrorView(error, null, t)?.reason ?? null;
}
