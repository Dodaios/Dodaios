export const CHAT_COMMAND_NAMES = [
  "help", "clear", "history", "plan", "build", "goal", "status", "stop", "continue",
  "recap", "find", "model", "remember", "message", "review", "routines", "project",
] as const;
export type ChatCommandName = typeof CHAT_COMMAND_NAMES[number];
export type GoalStatus = "active" | "paused" | "blocked" | "complete" | "cleared";
export interface GoalState {
  id: string; objective: string; status: GoalStatus; engine: string; native_pending: boolean; reason: string;
  steps: number; stalled_steps: number; evidence: string[]; started_ms: number; updated_ms: number;
}
export interface ChatControlState {
  session_id: string; mode: "build" | "plan"; permission_mode: string; previous_permission: string; output_language: string;
  plan: string; last_request: string; goal: GoalState | null; revision: number;
  last_status: "idle" | "running" | "done" | "interrupted" | "failed";
}
export interface ChatCommand {
  name: ChatCommandName; kind: "local" | "control"; example: string; available: boolean; reason: string;
}
export interface ChatCommandResult {
  request_id: string; command: ChatCommandName; status: "done" | "started" | "failed";
  state: ChatControlState; data: Record<string, unknown>; error: string;
}
export interface ChatSearchHit { seq: number; text: string; item_id: string; session_id: string }

async function read<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(typeof data.detail === "string" ? data.detail : `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function fetchChatCommands(sessionId: string | null, signal?: AbortSignal) {
  const query = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
  return read<{ commands: ChatCommand[]; state: ChatControlState | null }>(await fetch(`/api/agent-chat/commands${query}`, { signal }));
}

export async function runChatCommand(sessionId: string, command: ChatCommandName, args: string, requestId: string, locale = "en", attachments: ChatAttachment[] = []) {
  return read<ChatCommandResult>(await fetch(`/api/agent-chat/sessions/${encodeURIComponent(sessionId)}/commands`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command, arguments: args, request_id: requestId, locale, attachments }),
  }));
}

/** Only a leading, exact command token typed by the user is recognized. */
export function parseChatCommand(text: string): { name: ChatCommandName; args: string } | null {
  const match = /^\/([a-z]+)(?:\s+([\s\S]*))?$/.exec(text.trim());
  if (!match || !CHAT_COMMAND_NAMES.includes(match[1] as ChatCommandName)) return null;
  return { name: match[1] as ChatCommandName, args: (match[2] ?? "").trim() };
}

// A closed list, like the slash commands: only a message that is nothing but
// one of these counts, never a sentence that contains one.
const STOP_WORDS = new Set([
  "stop", "stop it", "stop that", "stop this", "halt", "cancel", "cancel it", "abort",
  "stopp", "stoppen", "stoppe", "anhalten", "abbrechen", "abbruch", "aufhören", "aufhoeren", "hör auf", "hoer auf", // i18n-allow: input vocabulary
  "para", "parar", "pare", "detente", "detener", "alto", "cancelar", "cancela", // i18n-allow: input vocabulary
  "停", "停止", "停下", "取消", // i18n-allow: input vocabulary
]);
const POLITE_LEAD = /^(?:bitte|please|por favor|ok|okay) /;
const POLITE_TAIL = / (?:bitte|please|por favor|jetzt|now|ahora|agora)$/;

/**
 * True when the whole message is a word for "stop" ("stop", "Stop!",
 * "please stop"). The Dodaios chat has no Stop button: this word, sent
 * while the assistant works, ends the turn.
 */
export function isStopWord(text: string): boolean {
  if (text.trimStart().startsWith("/")) return false; // a slash command is its own path
  const plain = text.toLowerCase().replace(/[^\p{L}\p{N}\s]/gu, " ").replace(/\s+/g, " ").trim();
  if (!plain || plain.length > 40) return false;
  const core = plain.replace(POLITE_LEAD, "").replace(POLITE_TAIL, "");
  if (STOP_WORDS.has(core)) return true;
  // "stop stop stop" is still only the word.
  const words = core.split(" ");
  return STOP_WORDS.has(words[0]) && words.every((word) => word === words[0]);
}
import type { ChatAttachment } from "./agentChatApi";
