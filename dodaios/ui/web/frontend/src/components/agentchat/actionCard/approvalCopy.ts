import { fill } from "@/i18n";
import type { ToolBlock } from "../reduce";
import type { ApprovalCardInfo, ApprovalSourceKind, RuleBreadth, RuleKind, SavedApprovalRule } from "./approvalInfo";
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
  if (known) return { ...known, detail: maskText(known.detail) };
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
  const where = (kind === "terminal" || kind === "files") && typeof input.cwd === "string" ? input.cwd : "";
  const why = typeof input.description === "string" ? maskText(input.description) : "";
  return {
    source: { kind, app, verb: typeof input.action === "string" && /^[a-z][a-z0-9_.-]{0,39}$/.test(input.action) ? input.action : "" },
    where,
    why,
    caution: null,
    detail: kind === "plan" ? "" : maskedRequest(block.input),
    // An older card cannot say what its "always" saves; it does what it always did.
    rule: kind === "plan" ? null : { scopes: [], chat: "", app: "", verb: "", pattern: "", broad: "" },
  };
}

/** The source chip's label: what is asking. */
export function sourceLabel(info: ApprovalCardInfo, t: T): string {
  const { kind, app } = info.source;
  if ((kind === "connector" || kind === "tool") && app) return app;
  return t(`action_card.source.${kind}`);
}

/** The card's question-form title. */
export function approvalTitle(info: ApprovalCardInfo, t: T): string {
  const { kind, app, verb } = info.source;
  if (kind === "connector") {
    if (verb && app) return fill(t("action_card.title.connector_verb"), { app, verb });
    return app ? fill(t("action_card.title.connector"), { app }) : t("action_card.title.tool_plain");
  }
  if (kind === "tool") return app ? fill(t("action_card.title.tool"), { tool: app }) : t("action_card.title.tool_plain");
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
  return ruleSentence(rule.kind, rule.app, rule.verb, t);
}

/** The verb a rule of this breadth is about. */
export function breadthVerb(verb: string, breadth: RuleBreadth): string {
  return breadth === "app" ? "" : verb;
}
