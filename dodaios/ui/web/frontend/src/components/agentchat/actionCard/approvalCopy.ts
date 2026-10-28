import { fill } from "@/i18n";
import type { ToolBlock } from "../reduce";
import { agentToolLabel, capitalize, isRawToolId, readableToolName } from "../traceEntries";
import type { ApprovalCardInfo, ApprovalSourceKind, RuleBreadth, RuleKind, RuleNarrow, SavedApprovalRule } from "./approvalInfo";
import { maskText, maskedRequest } from "./redact";

type T = (key: string) => string;

const OWN_SERVER = /^mcp__(?:dodaios|jarvis)__/;

function humanize(raw: string): string {
  const words = raw.split(/[_\-.]+/).filter(Boolean);
  if (!words.length) return raw;
  return words.map((w) => (w === "github" ? "GitHub" : w.charAt(0).toUpperCase() + w.slice(1))).join(" ");
}

/**
 * The card fields of an approval, from the backend's own fields when the
 * event carries them, else read off the tool name and input (events written
 * before the fields existed).
 */
export function cardInfoOf(block: ToolBlock): ApprovalCardInfo {
  const known = block.approval?.card;
  if (known) return { ...known, where: shortenHome(known.where), detail: maskText(known.detail) };
  const name = block.name || "";
  const input = block.input && typeof block.input === "object" ? (block.input as Record<string, unknown>) : {};
  let kind: ApprovalSourceKind = "tool";
  let app = "";
  if (name === "ExitPlanMode" || name === "exit_plan_mode") kind = "plan";
  else if (/^(bash|runcommand|run_command|shell|exec|exec_command|powershell)$/i.test(name)) kind = "terminal";
  else if (/^(write|edit|multiedit|notebookedit|apply_patch|write_file|edit_file|create_file)$/i.test(name)) kind = "files";
  else if (/browser|webfetch|web_fetch/i.test(name)) kind = "browser";
  else if (name.startsWith("mcp__")) {
    kind = "connector";
    const [, server = "", tool = ""] = name.split("__");
    app = humanize(OWN_SERVER.test(name) ? tool : server);
  } else if (typeof input.command === "string") kind = "terminal";
  else app = name;
  const where = (kind === "terminal" || kind === "files") && typeof input.cwd === "string" ? shortenHome(input.cwd) : "";
  const why = typeof input.description === "string" ? maskText(input.description) : "";
  return {
    source: { kind, app, verb: typeof input.action === "string" && /^[a-z][a-z0-9_.-]{0,39}$/.test(input.action) ? input.action : "" },
    where,
    whereFull: "",
    why,
    caution: null,
    detail: kind === "plan" ? "" : maskedRequest(block.input),
    brief: "",
    // An older card cannot say what its "always" saves; it does what it always did.
    rule: kind === "plan" ? null : { scopes: [], chat: "", app: "", verb: "", pattern: "", broad: "", narrow: [] },
  };
}

/**
 * The card with the agents' own tools named by what they do: "Create a
 * routine?" under a plain "Tool" chip, never "Society Create Routine" or
 * "mcp__dodaios__society-create-routine".
 */
export function withReadableNames(info: ApprovalCardInfo, block: ToolBlock, t: T): ApprovalCardInfo {
  const action = agentToolLabel(block.name || "", t);
  if (!action) return info;
  return {
    ...info,
    action,
    source: { kind: "tool", app: action, verb: info.source.verb },
    rule: info.rule ? { ...info.rule, app: action } : null,
  };
}

/**
 * What the card says it is about: the summary, unless it only repeats the
 * tool's id; then the tool's readable name, or nothing when the title already
 * names the action.
 */
export function approvalSummary(info: ApprovalCardInfo, summary: string, block: ToolBlock): string {
  const shown = shownSummary(info, summary);
  if (!isRawToolId(shown, block.name || "")) return shown;
  return info.action ? "" : readableToolName(block.name || shown);
}

/** Two lines that say the same thing, ignoring quotes, case and the closing stop. */
export function sameWords(a: string, b: string): boolean {
  const norm = (text: string) => text.toLowerCase().replace(/["'“”„«»‘’.!?…\s]+/g, " ").trim();
  return Boolean(norm(a)) && norm(a) === norm(b);
}

export interface DetailRow {
  label: string;
  value: string;
}

const MAX_ROWS = 24;
const MAX_VALUE = 400;

function words(key: string): string {
  return capitalize(key.replace(/([a-z])([A-Z])/g, "$1 $2").replace(/[_-]+/g, " ").trim().toLowerCase());
}

function primitive(value: unknown): value is string | number | boolean {
  return typeof value === "string" || typeof value === "number" || typeof value === "boolean";
}

/**
 * A request as label/value rows ("Title · QA weekly check"), nested objects
 * one level down as "Schedule · Local time"; [] when it is not a JSON object
 * (a command line stays as it is).
 */
export function detailRows(detail: string): DetailRow[] {
  const text = detail.trim();
  if (!text.startsWith("{")) return [];
  let parsed: unknown;
  try { parsed = JSON.parse(text); } catch { return []; }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return [];
  const rows: DetailRow[] = [];
  const walk = (record: Record<string, unknown>, prefix: string, depth: number) => {
    for (const [key, value] of Object.entries(record)) {
      if (rows.length >= MAX_ROWS) return;
      const label = prefix ? `${prefix} · ${words(key)}` : words(key);
      if (value === null || value === undefined || value === "" || (Array.isArray(value) && value.length === 0)) continue;
      let shown: string;
      if (primitive(value)) shown = String(value);
      else if (Array.isArray(value) && value.every(primitive)) shown = value.map(String).join(", ");
      else if (!Array.isArray(value) && depth < 1) {
        walk(value as Record<string, unknown>, label, depth + 1);
        continue;
      } else shown = JSON.stringify(value);
      rows.push({ label, value: shown.length > MAX_VALUE ? `${shown.slice(0, MAX_VALUE - 1)}…` : shown });
    }
  };
  walk(parsed as Record<string, unknown>, "", 0);
  return rows;
}

/** The source chip's label: what is asking. */
export function sourceLabel(info: ApprovalCardInfo, t: T): string {
  if (info.action) return t("action_card.source.tool");
  const { kind, app } = info.source;
  if ((kind === "connector" || kind === "tool") && app) return app;
  return t(`action_card.source.${kind}`);
}

/** The card's question-form title. */
export function approvalTitle(info: ApprovalCardInfo, t: T): string {
  if (info.action) return fill(t("action_card.title.action"), { action: info.action });
  const { kind, app, verb } = info.source;
  if (kind === "connector") {
    if (verb && app) return fill(t("action_card.title.connector_verb"), { app, verb });
    return app ? fill(t("action_card.title.connector"), { app }) : t("action_card.title.tool_plain");
  }
  if (kind === "tool") return app ? fill(t("action_card.title.tool"), { tool: app }) : t("action_card.title.tool_plain");
  if (kind === "files" && info.creates) return t("action_card.title.files_create");
  return t(`action_card.title.${kind}`);
}

/** How a settled approval reads in one line ("Allowed once"). */
export function outcomeLabel(decision: string, t: T): string {
  const known = ["allow", "allow_always", "deny", "expired", "cancel"].includes(decision) ? decision : "cancel";
  return t(`action_card.outcome.${known}`);
}

export type OutcomeTone = "success" | "danger" | "muted";

export function outcomeTone(decision: string): OutcomeTone {
  if (decision === "allow" || decision === "allow_always") return "success";
  if (decision === "deny") return "danger";
  return "muted";
}

/** A rule as the person reads it: "Always allow send with Gmail". */
export function ruleSentence(kind: RuleKind, app: string, verb: string, t: T): string {
  const base = kind === "require_approval" ? "ask" : "always";
  if (!app) return t(`action_card.rule.${base}_generic`);
  return verb
    ? fill(t(`action_card.rule.${base}_verb`), { app, verb })
    : fill(t(`action_card.rule.${base}_app`), { app });
}

export function savedRuleSentence(rule: SavedApprovalRule, t: T): string {
  if (rule.narrow && rule.target) return narrowSentence(rule.narrow, rule.target, t);
  return ruleSentence(rule.kind, rule.app, rule.verb, t);
}

/** A narrow chat rule as the person reads it: "Always allow changes to files in src". */
export function narrowSentence(narrow: RuleNarrow, target: string, t: T): string {
  return narrow === "folder"
    ? fill(t("action_card.rule.always_folder"), { folder: target })
    : fill(t("action_card.rule.always_command"), { command: target });
}

/** A user-profile folder, Windows or POSIX; system profiles are left alone. */
const WIN_HOME = /\b[A-Za-z]:[\\/]Users[\\/](?!(?:Public|Default|All Users)(?:[\\/]|$))[^\\/\s"'`]+(?=[\\/]|$|[\s"'`),;])/gi;
const POSIX_HOME = /(^|[\s"'`(=:])\/(?:Users|home)\/(?!Shared(?:\/|$))[^/\s"'`]+(?=\/|$|[\s"'`),;])/g;

/**
 * `text` with the person's home folder shown as `~`: the card's visible
 * lines never spell out the profile folder (the backend also makes paths
 * relative to the workspace; this covers events written before it did). The
 * full path stays in the details disclosure.
 */
export function shortenHome(text: string): string {
  if (!text) return text;
  return text.replace(WIN_HOME, "~").replace(POSIX_HOME, "$1~");
}

/**
 * What a card's details disclosure says: the folder in full when the line
 * above shows it short, then the exact request. "" when there is nothing.
 */
export function disclosureText(info: ApprovalCardInfo, t: T): string {
  const full = info.whereFull.trim();
  const folder = full && full !== info.where
    ? fill(t(info.source.kind === "browser" ? "action_card.field.on" : "action_card.field.in"), { where: full })
    : "";
  return [folder, info.detail].filter(Boolean).join("\n\n");
}

/** The summary a card shows: the backend's short-path brief, else the summary with `~`. */
export function shownSummary(info: ApprovalCardInfo, summary: string): string {
  return (info.brief || shortenHome(summary)).trim();
}

/** The verb a rule of this breadth is about. */
export function breadthVerb(verb: string, breadth: RuleBreadth): string {
  return breadth === "app" ? "" : verb;
}
