/**
 * What one roster row says about its agent, as pure functions.
 *
 * A row has one status (the corner mark on the avatar) and one preview line.
 * Both follow a single vocabulary shared by the row, the hover card and the
 * chat header:
 *
 *   status:  needs-you > working > unread > paused > idle
 *   preview: waiting reason > unsent draft > last message > role
 *
 * "Needs you" beats everything because it is the only state where the agent
 * cannot move on without the person. A draft beats the last message because
 * it is the person's own unsent words. Live work shows on the corner mark and
 * in the chat header, so the preview keeps saying what was last said.
 */
import { hideAskBlocks } from "@/components/agentchat/askFence";
import { friendlyToolName, isRawToolId } from "@/components/agentchat/traceEntries";
import { stripInlineMarks } from "@/lib/plainMarks";

import { wasAnswered } from "../attention/attentionStore";
import type { SocietyAgent } from "../data";

export type WaitingKind = "question" | "approval" | "credential" | "proposal";

/** Why an agent waits on the person (society agent payload `waiting_reason`). */
export interface WaitingReason {
  kind: WaitingKind;
  summary: string;
  sessionId?: string;
  refId?: string;
}

const WAITING_KINDS: ReadonlySet<string> = new Set(["question", "approval", "credential", "proposal"]);

function coerceReason(value: unknown): WaitingReason | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Record<string, unknown>;
  const kind = typeof raw.kind === "string" && WAITING_KINDS.has(raw.kind) ? (raw.kind as WaitingKind) : null;
  if (!kind) return null;
  const sessionId = raw.sessionId ?? raw.session_id;
  const refId = raw.refId ?? raw.ref_id;
  return {
    kind,
    summary: typeof raw.summary === "string" ? raw.summary : "",
    ...(typeof sessionId === "string" ? { sessionId } : {}),
    ...(typeof refId === "string" ? { refId } : {}),
  };
}

/**
 * The agent's waiting reason when the backend sends one. Older backends do
 * not; the row then falls back to the plain `waiting` state.
 */
export function waitingReasonOf(agent: SocietyAgent): WaitingReason | null {
  const loose = agent as SocietyAgent & { waitingReason?: unknown; waiting_reason?: unknown };
  const reason = coerceReason(loose.waitingReason ?? loose.waiting_reason);
  // Answered here: the card is settled even before the next roster read says so.
  return reason && wasAnswered(reason.refId) ? null : reason;
}

/** The waiting reason the roster still holds although the person already answered it here. */
function answeredReason(agent: SocietyAgent): WaitingReason | null {
  const loose = agent as SocietyAgent & { waitingReason?: unknown; waiting_reason?: unknown };
  const reason = coerceReason(loose.waitingReason ?? loose.waiting_reason);
  return reason && wasAnswered(reason.refId) ? reason : null;
}

function answeredHere(agent: SocietyAgent): boolean {
  return answeredReason(agent) !== null;
}

export function needsYou(agent: SocietyAgent): boolean {
  if (answeredHere(agent)) return false;
  return agent.state === "waiting" || waitingReasonOf(agent) !== null;
}

/** A waiting reason in words: a bare tool id reads as what the tool does. */
export function readableWaiting(text: string, t: (key: string) => string): string {
  return text && isRawToolId(text) ? friendlyToolName(text, t) : text;
}

export type RosterStatus = "needs-you" | "working" | "unread" | "paused" | "idle";

export function rosterStatus(agent: SocietyAgent, unread: boolean): RosterStatus {
  // An answered approval, question or sign-in lets the paused run go on; a
  // decided proposal starts nothing, so the agent reads as it otherwise would.
  const answered = answeredReason(agent);
  if (answered && answered.kind !== "proposal") return "working";
  if (!answered && needsYou(agent)) return "needs-you";
  if (agent.state === "working") return "working";
  if (unread) return "unread";
  if (agent.state === "paused") return "paused";
  return "idle";
}

export type PreviewKind = "waiting" | "draft" | "message" | "role";

export interface RosterPreview {
  kind: PreviewKind;
  text: string;
}

export interface PreviewSources {
  agent: SocietyAgent;
  /** Unsent composer text for this agent's chat, if any. */
  draft?: string;
  /** The last message in the agent's chat (either side), if known. */
  lastMessage?: string;
}

/** The hidden routing lines a society message carries (AgentChatPanel strips the same). */
const MARKER_LINE = /^\s*\[(?:to jarvis\]|agent mentions\]|tools:)[^\n]*$/gm;
const MAX_PREVIEW = 160;

/** One line of plain text from a chat message: no ask block, markers or markdown. */
export function previewText(raw: string | null | undefined): string {
  if (!raw) return "";
  const text = hideAskBlocks(raw)
    .replace(/```[\s\S]*?(```|$)/g, " ")
    .replace(MARKER_LINE, " ")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, " ")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/^\s*(?:[>#]+|[-*+]\s)\s*/gm, " ")
    .replace(/[^\n]+/g, (line) => stripInlineMarks(line))
    .replace(/\|/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return text.length > MAX_PREVIEW ? `${text.slice(0, MAX_PREVIEW - 1)}…` : text;
}

/** The single preview line, by the priority in the file comment. */
export function rosterPreview({ agent, draft, lastMessage }: PreviewSources): RosterPreview {
  const reason = waitingReasonOf(agent);
  if (reason || agent.state === "waiting") {
    return { kind: "waiting", text: previewText(reason?.summary) };
  }
  const unsent = previewText(draft);
  if (unsent) return { kind: "draft", text: unsent };
  const last = previewText(lastMessage);
  if (last) return { kind: "message", text: last };
  return { kind: "role", text: agent.title };
}

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

export type RelativeStamp =
  | { unit: "now" }
  | { unit: "minute" | "hour" | "day"; value: number }
  | { unit: "date"; ms: number };

/** Bucket a timestamp the way a dense list shows it: now, 5m, 3h, 2d, then a date. */
export function relativeStamp(ms: number, now: number): RelativeStamp {
  const delta = Math.max(0, now - ms);
  if (delta < MINUTE) return { unit: "now" };
  if (delta < HOUR) return { unit: "minute", value: Math.floor(delta / MINUTE) };
  if (delta < DAY) return { unit: "hour", value: Math.floor(delta / HOUR) };
  if (delta < 7 * DAY) return { unit: "day", value: Math.floor(delta / DAY) };
  return { unit: "date", ms };
}

/** Localised short form of `relativeStamp`; `nowLabel` comes from the locale file. */
export function formatRelative(ms: number, now: number, locale: string, nowLabel: string): string {
  const stamp = relativeStamp(ms, now);
  if (stamp.unit === "now") return nowLabel;
  try {
    if (stamp.unit === "date") {
      const sameYear = new Date(ms).getFullYear() === new Date(now).getFullYear();
      return new Intl.DateTimeFormat(locale, sameYear ? { month: "short", day: "numeric" } : { year: "2-digit", month: "short" }).format(ms);
    }
    return new Intl.NumberFormat(locale, { style: "unit", unit: stamp.unit, unitDisplay: "narrow" }).format(stamp.value);
  } catch {
    if (stamp.unit === "date") return new Date(ms).toLocaleDateString();
    return `${stamp.value}${stamp.unit[0]}`;
  }
}
