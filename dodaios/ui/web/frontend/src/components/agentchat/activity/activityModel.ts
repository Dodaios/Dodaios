/**
 * What an agent is doing right now, as one short line.
 *
 * A running turn is a list of blocks: thoughts, words and tool calls. The
 * activity line under the conversation says what the newest of them means to
 * a person, in a phrase of a few words ("Editing app.ts", "Working in Gmail",
 * "Writing to Scout"), never a raw tool name. This module is the pure part:
 *
 *   blocks → an Activity (a verb family, an optional target, an episode key)
 *   Activity → the phrase, capped at PHRASE_MAX characters
 *   Activity → the face's scene (BotStage presence)
 *
 * Generic families (thinking, working) have several phrasings. One is picked
 * per episode from a hash of the episode key, so the line does not flicker
 * between wordings while the same step lasts, and two steps rarely read the
 * same.
 *
 * Every runtime feeds the same event vocabulary, so this works the same for
 * our own agents, every CLI seat and the ACP runtimes. A runtime that sends
 * no stream simply shows "thinking" until its finished blocks arrive.
 */

import { fill } from "@/i18n";
import { resolveToolBrand } from "@/lib/toolBrand";
import type { Presence } from "../messengerPresence";
import { isCredentialTool, isQuestionTool, waitsOnCard, type ToolBlock, type TurnBlock, type TurnItem } from "../reduce";
import { isSubagentCall } from "@/components/agentic/threads/subagents";
import { commandBinary, ownServerTool, shortPath, withoutCd } from "../traceEntries";
import { traceAction, traceToolIdentity, traceToolName } from "../traceActivity";

/** The verb families the line speaks in. */
export type ActivityFamily =
  | "thinking"
  | "composing"
  | "searching"
  | "reading"
  | "writing"
  | "running"
  | "browsing"
  | "recalling"
  | "noting"
  | "messaging"
  | "delegating"
  | "connecting"
  | "setting_up"
  | "waiting"
  | "working";

export interface Activity {
  family: ActivityFamily;
  /**
   * The phrase key under `run_view.phrase.` without a variant suffix. Most
   * families have one or two shapes ("read_file" with a target, "read_any"
   * without one).
   */
  phrase: string;
  /** What the step is about: a file, a host, a teammate, a service. Untranslated. */
  target: string;
  /**
   * Stable while one step lasts (the call id, the thought id). The phrasing
   * variant is chosen from it, and the pacer treats a new key of the same
   * family and target as the same step.
   */
  episode: string;
  /** A connector's brand row id, for its logo; "" otherwise. */
  brand: string;
  /** The teammate an agent message goes to (roster id or name), for its face. */
  peer: string;
}

/** Lines longer than this end in an ellipsis. */
export const PHRASE_MAX = 60;

/** How many phrasings each generic family has (`thinking_0` … `thinking_3`). */
export const VARIANTS: Partial<Record<string, number>> = {
  thinking: 4,
  working: 3,
};

/** Resolves a roster id or name to the name a person sees. */
export type NameOf = (idOrName: string) => string;

const identity: NameOf = (value) => value;

function record(value: unknown): Record<string, unknown> {
  const out = value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
  // A runtime's permission request nests the tool's own arguments ({ tool, arguments: { path } }).
  const nested = out.arguments;
  return nested && typeof nested === "object" && !Array.isArray(nested) ? { ...(nested as Record<string, unknown>), ...out } : out;
}

function firstString(input: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = input[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
}

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

/** "linear-server" → "Linear", "github_mcp" → "Github": an MCP server id as a name. */
export function serviceName(server: string): string {
  const words = server
    .replace(/^(?:mcp|plugin|cli)[-_]/i, "")
    .replace(/[-_](?:mcp|server|plugin|cli)$/i, "")
    .split(/[-_.\s]+/)
    .filter(Boolean);
  if (!words.length) return server;
  return words.map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(" ");
}

function make(family: ActivityFamily, phrase: string, episode: string, extra: Partial<Activity> = {}): Activity {
  return { family, phrase, target: "", episode, brand: "", peer: "", ...extra };
}

const MEMORY_WRITE = /(wiki_?note|^remember$|memory_?(write|update|save))/;
const MEMORY_READ = /(recall|memory_?(read|search|get)|^memory$|wiki_?(recall|read|list|page))/;
const BROWSER = /(^browser|browser_|^navigate|^click|screenshot|^computer|^society_browser$)/;
const WEB_SEARCH = /(web_?search|search_?web|websearch|^google_search|^brave_search)/;
const WEB_FETCH = /^(web_?fetch|fetch_?url|fetch|read_?url|open_?url)$/;
const SHELL = /^(bash|powershell|shell|run_?shell(_command)?|exec(_command)?|run_?command|terminal|society_shell|society_sandbox)$/;
const SETUP = /(credential|routine|install|connect|plugin|connector|configure|setup|propose_change)/;
const MESSAGE = /^(society_message_agent|send_?message_?to_?agent|message_agent)$/;

/**
 * The family and phrase of one tool call. `nameOf` turns a teammate's id
 * into the name a person knows.
 */
export function toolActivity(block: ToolBlock, nameOf: NameOf = identity): Activity {
  const episode = block.callId;
  const input = record(block.input);
  if (isQuestionTool(block.name) || isCredentialTool(block.name)) return make("waiting", "waiting", episode);
  if (isSubagentCall(block)) {
    const title = block.subagent?.description || firstString(input, ["description", "title", "name"]);
    return title ? make("delegating", "delegate", episode, { target: title }) : make("delegating", "delegate_any", episode);
  }
  const traced = traceToolName(block.name);
  const own = ownServerTool(traced);
  // The app's own MCP server is the road, not the destination.
  const name = (own ?? traced).toLowerCase();
  const bare = name.split("/").pop() ?? name;

  if (MESSAGE.test(bare)) {
    const peer = firstString(input, ["target", "to", "agent", "recipient", "agent_id"]);
    return peer ? make("messaging", "message", episode, { target: nameOf(peer), peer }) : make("messaging", "message_any", episode);
  }
  if (MEMORY_WRITE.test(bare)) return make("noting", "note", episode);
  if (MEMORY_READ.test(bare)) return make("recalling", "recall", episode);
  if (WEB_SEARCH.test(bare)) {
    const query = firstString(input, ["query", "q", "search_query", "pattern"]);
    return query ? make("searching", "search_web_for", episode, { target: query }) : make("searching", "search_web", episode);
  }
  if (WEB_FETCH.test(bare)) {
    const host = hostOf(firstString(input, ["url", "uri", "href"]));
    return host ? make("reading", "read_page", episode, { target: host }) : make("reading", "read_any", episode);
  }
  if (BROWSER.test(bare)) {
    const host = hostOf(firstString(input, ["url", "uri", "href"]));
    return host ? make("browsing", "browse_site", episode, { target: host }) : make("browsing", "browse_any", episode);
  }

  const action = traceAction(own ?? traced);
  if (action === "command" || SHELL.test(bare)) {
    const raw = firstString(input, ["command", "cmd", "CommandLine", "commandLine", "script"]);
    const binary = raw ? commandBinary(withoutCd(raw.split(/\r?\n/).find((line) => line.trim()) ?? "")) : "";
    return binary ? make("running", "run_cmd", episode, { target: binary }) : make("running", "run_any", episode);
  }
  if (action === "edit" || action === "write") {
    const path = firstString(input, ["file_path", "path", "notebook_path", "filename"]);
    const file = path ? fileName(path) : "";
    if (!file) return make("writing", "write_any", episode);
    return make("writing", action === "edit" ? "edit_file" : "write_file", episode, { target: file });
  }
  if (action === "read") {
    const path = firstString(input, ["file_path", "path", "notebook_path", "filename"]);
    if (/\.(png|jpe?g|gif|webp|bmp|svg|heic|avif)$/i.test(path)) return make("reading", "view_image", episode);
    return path ? make("reading", "read_file", episode, { target: fileName(path) }) : make("reading", "read_any", episode);
  }
  if (action === "list") {
    const path = firstString(input, ["path", "directory", "dir"]);
    return path ? make("reading", "list_folder", episode, { target: shortPath(path) }) : make("reading", "read_any", episode);
  }
  if (action === "search") {
    const pattern = firstString(input, ["pattern", "query", "regex", "q"]);
    return pattern ? make("searching", "search_for", episode, { target: pattern }) : make("searching", "search_files", episode);
  }
  if (action === "memory") return make("recalling", "recall", episode);

  // A connector: an MCP server's tool, a plugin of ours, a branded service.
  if (own !== null) {
    const brand = resolveToolBrand(own);
    if (brand.logoUrl) return make("connecting", "connect", episode, { target: brand.label.split(" · ")[0], brand: brand.brandId ?? "" });
  } else {
    const view = traceToolIdentity(block);
    if (view.integration) {
      const label = view.row.brand ? view.service : serviceName(view.service || traced.split("/")[0]);
      return make("connecting", "connect", episode, { target: label, brand: view.row.brand });
    }
  }
  if (SETUP.test(bare)) return make("setting_up", "setup", episode);
  return make("working", "working", episode);
}

function fileName(path: string): string {
  return path.replace(/\\/g, "/").split("/").filter(Boolean).pop() ?? path;
}

/** The call waits on the person: an open question, a credential field, an approval. */
function waitsForPerson(block: TurnBlock): block is ToolBlock {
  return block.kind === "tool" && (waitsOnCard(block) || Boolean(block.approval && block.approval.decision === null && !block.approval.answering));
}

/** Question and credential polls draw nothing: the card speaks for them. */
function isPoll(block: TurnBlock): boolean {
  return block.kind === "tool" && block.output !== null && (
    (isQuestionTool(block.name) && !block.question) || (isCredentialTool(block.name) && !block.credential)
  );
}

/**
 * What a running turn is doing now, or null once it is over. A card that
 * waits for the person wins over everything else: nothing moves until they
 * answer.
 */
export function activityOf(turn: TurnItem, nameOf: NameOf = identity): Activity | null {
  if (turn.status !== "running") return null;
  const blocks = turn.blocks;
  const waiting = blocks.find(waitsForPerson);
  if (waiting) {
    const approval = Boolean(waiting.approval && waiting.approval.decision === null) && !waiting.question && !waiting.credential;
    return make("waiting", approval ? "waiting_approval" : "waiting", `wait:${waiting.callId}`);
  }
  for (let i = blocks.length - 1; i >= 0; i--) {
    const block = blocks[i];
    if (isPoll(block)) continue;
    if (block.kind === "tool") {
      if (block.output === null) return toolActivity(block, nameOf);
      // A helper the agent started keeps working after its spawn call returned.
      const helpers = runningHelpers(blocks);
      if (helpers) return helpers;
      return make("thinking", "thinking", `after:${block.callId}`);
    }
    if (block.kind === "text") {
      return block.text.trim() ? make("composing", "composing", block.id) : make("thinking", "thinking", block.id);
    }
    return make("thinking", "thinking", block.id);
  }
  return make("thinking", "thinking", `start:${turn.id}`);
}

function runningHelpers(blocks: TurnBlock[]): Activity | null {
  const running = blocks.filter((block): block is ToolBlock => block.kind === "tool" && block.subagent?.status === "running");
  if (!running.length) return null;
  if (running.length === 1) {
    const title = running[0].subagent?.description ?? "";
    return title ? make("delegating", "delegate", running[0].callId, { target: title }) : make("delegating", "delegate_any", running[0].callId);
  }
  return make("delegating", "delegate_many", `helpers:${running.length}`, { target: String(running.length) });
}

/** Same family and same target: the same step, whatever its episode. */
export function sameStep(a: Activity | null, b: Activity | null): boolean {
  if (a === b) return true;
  if (!a || !b) return false;
  return a.family === b.family && a.phrase === b.phrase && a.target === b.target;
}

export function stepKey(activity: Activity | null): string {
  return activity ? `${activity.family}|${activity.phrase}|${activity.target}` : "";
}

function hash(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 16777619) >>> 0;
  return h;
}

/** The full i18n key of the phrase, with the episode's stable variant. */
export function phraseKey(activity: Activity): string {
  const count = VARIANTS[activity.phrase] ?? 0;
  const suffix = count > 1 ? `_${hash(activity.episode) % count}` : "";
  return `run_view.phrase.${activity.phrase}${suffix}`;
}

/** Collapse whitespace and cap at `max` characters with an ellipsis. */
export function capPhrase(text: string, max = PHRASE_MAX): string {
  const clean = text.replace(/\s+/g, " ").trim();
  return clean.length > max ? `${clean.slice(0, max - 1).trimEnd()}…` : clean;
}

/**
 * The line itself. The target is shortened first, so the verb always reads
 * whole ("Editing …/very/long/name.ts" rather than "Editi…").
 */
export function activityPhrase(activity: Activity, t: (key: string) => string): string {
  const template = t(phraseKey(activity));
  if (!activity.target || !template.includes("{target}")) return capPhrase(template);
  const room = Math.max(8, PHRASE_MAX - (template.replace("{target}", "").length));
  const target = capPhrase(activity.target, room);
  return capPhrase(fill(template, { target }));
}

/** The face's scene for each family (BotStage keeps its own pacing and crossfades). */
const PRESENCE: Record<ActivityFamily, Presence> = {
  thinking: "thinking",
  composing: "typing",
  searching: "searching",
  reading: "searching",
  writing: "writing",
  running: "command",
  browsing: "browsing",
  recalling: "recall",
  noting: "writing",
  messaging: "working",
  delegating: "working",
  connecting: "setting_up",
  setting_up: "setting_up",
  waiting: "reading",
  working: "working",
};

export function presenceForFamily(family: ActivityFamily): Presence {
  return PRESENCE[family];
}
