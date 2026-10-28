/**
 * The display fields an approval card reads, parsed from the
 * `approval_required` payload (dodaios/agent_chat/approval_card.py). Every
 * field is optional: an event written before the backend sent them parses to
 * `undefined`, and the card falls back to the tool name and the summary.
 */

export type ApprovalSourceKind = "terminal" | "files" | "browser" | "computer" | "plan" | "agent" | "connector" | "tool";
export type ApprovalCaution = "irreversible" | "security" | "data_leaves";
/** Where a rule from the card lives: the agent's own approval rules, or this chat. */
export type RuleScope = "agent" | "chat";
/** `action`: only this action of the app; `app`: every action of it. */
export type RuleBreadth = "action" | "app";
export type RuleKind = "always_allow" | "require_approval";

/** A narrower chat rule the call allows: only this folder, only this command. */
export type RuleNarrow = "folder" | "command";

export interface NarrowOption {
  kind: RuleNarrow;
  /** How the card shows it: a path relative to the workspace, or with `~`. */
  label: string;
}

/** What "Always allow" saves on this card. */
export interface ApprovalRuleOffer {
  scopes: RuleScope[];
  /** What a chat-wide "always" does here: this tool, the whole chat, or the runtime remembers. */
  chat: "tool" | "all" | "runtime" | "";
  app: string;
  verb: string;
  pattern: string;
  broad: string;
  /** Narrower chat rules this call allows; empty when the payload has none. */
  narrow: NarrowOption[];
}

export interface ApprovalCardInfo {
  /** What is asking; `verb` is the one-word action a connector call performs ("send"). */
  source: { kind: ApprovalSourceKind; app: string; verb: string };
  where: string;
  /** `where` in full (the card's details only); "" when it is the same or unknown. */
  whereFull: string;
  why: string;
  caution: ApprovalCaution | null;
  /** The exact command or request, secrets masked by the backend. */
  detail: string;
  /** The summary with short paths (workspace-relative, `~` for home); "" on older events. */
  brief: string;
  /** `null`: the card offers no "Always allow" (a plan). */
  rule: ApprovalRuleOffer | null;
  /** One of the agents' own tools, by what it does ("Create a routine"); absent for any other call. */
  action?: string;
}

/** A standing rule saved from a card (`notice{kind:"approval_rule"}`). */
export interface SavedApprovalRule {
  kind: RuleKind;
  scope: RuleScope;
  pattern: string;
  app: string;
  verb: string;
  /** A broader "ask first" rule keeps asking anyway. */
  stillAsks: boolean;
  /** A narrow chat rule: what it covers, as the card showed it. */
  narrow?: RuleNarrow;
  target?: string;
}

const KINDS = new Set<ApprovalSourceKind>(["terminal", "files", "browser", "computer", "plan", "agent", "connector", "tool"]);
const CAUTIONS = new Set<ApprovalCaution>(["irreversible", "security", "data_leaves"]);
const SCOPES = new Set<RuleScope>(["agent", "chat"]);
const NARROWS = new Set<RuleNarrow>(["folder", "command"]);

const text = (v: unknown): string => (typeof v === "string" ? v : "");
const record = (v: unknown): Record<string, unknown> | null =>
  v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;

export function parseApprovalCard(payload: Record<string, unknown>): ApprovalCardInfo | undefined {
  const source = record(payload.source);
  if (!source) return undefined;
  const kind = text(source.kind) as ApprovalSourceKind;
  const caution = text(payload.caution) as ApprovalCaution;
  return {
    source: { kind: KINDS.has(kind) ? kind : "tool", app: text(source.app), verb: text(source.verb) },
    where: text(payload.where),
    whereFull: text(payload.where_full),
    why: text(payload.why),
    caution: CAUTIONS.has(caution) ? caution : null,
    detail: text(payload.detail),
    brief: text(payload.brief),
    rule: parseRuleOffer(payload.rule),
  };
}

function parseRuleOffer(raw: unknown): ApprovalRuleOffer | null {
  const rule = record(raw);
  if (!rule) return null;
  const scopes = Array.isArray(rule.scopes) ? rule.scopes.filter((s): s is RuleScope => SCOPES.has(s as RuleScope)) : [];
  const chat = text(rule.chat);
  return {
    scopes,
    chat: chat === "tool" || chat === "all" || chat === "runtime" ? chat : "",
    app: text(rule.app),
    verb: text(rule.verb),
    pattern: text(rule.pattern),
    broad: text(rule.broad),
    narrow: Array.isArray(rule.narrow)
      ? rule.narrow.flatMap((raw) => {
        const entry = record(raw);
        const kind = text(entry?.kind) as RuleNarrow;
        const label = text(entry?.label);
        return NARROWS.has(kind) && label ? [{ kind, label }] : [];
      })
      : [],
  };
}

export function parseSavedRule(payload: Record<string, unknown>): SavedApprovalRule | null {
  const kind = text(payload.rule_kind);
  const scope = text(payload.scope) as RuleScope;
  if ((kind !== "always_allow" && kind !== "require_approval") || !SCOPES.has(scope)) return null;
  return {
    kind,
    scope,
    pattern: text(payload.pattern),
    app: text(payload.app),
    verb: text(payload.verb),
    stillAsks: payload.still_asks === true,
    ...(NARROWS.has(text(payload.narrow) as RuleNarrow)
      ? { narrow: text(payload.narrow) as RuleNarrow, target: text(payload.target) }
      : {}),
  };
}
