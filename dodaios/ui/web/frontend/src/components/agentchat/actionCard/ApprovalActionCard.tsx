import { memo, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Bot, Check, FilePenLine, Globe, ListChecks, Monitor, Plug, SquareTerminal, Wrench } from "lucide-react";
import { fill, useT } from "@/i18n";
import type { ApprovalDecision, ApprovalRuleChoice, ApprovalRuleRequest } from "@/lib/agentChatApi";
import { ChatMarkdown } from "../ChatMarkdown";
import { useAgentChat } from "../AgentChatStoreContext";
import type { ApprovalState, ToolBlock } from "../reduce";
import { ToolChoiceIcon } from "../ToolChoiceChips";
import type { ToolChoice } from "../toolChoices";
import { ActionCard, type ActionSpec, type SettledSpec } from "./ActionCard";
import { approvalTitle, cardInfoOf, disclosureText, narrowSentence, outcomeLabel, outcomeTone, ruleSentence, savedRuleSentence, shownSummary, sourceLabel } from "./approvalCopy";
import type { ApprovalCardInfo, ApprovalRuleOffer, RuleBreadth, RuleNarrow, RuleScope } from "./approvalInfo";
import { claimKeyboardTarget, TARGET_PRIORITY } from "./keyboardTarget";

/** How a surface answers an approval: by its id, the decision, and where an "always" lives. */
export type ApprovalDecide = (approvalId: string, decision: ApprovalDecision, rule?: ApprovalRuleChoice) => void | Promise<void>;

type T = (key: string) => string;

/**
 * A tool approval on the action card. Open, it asks in plain words with
 * "Allow once" first (it answers at once); "Always allow" never saves on its
 * own: it opens a small rule editor (the rule as a sentence; this agent or
 * this chat; this action or the whole app, this folder or this command) and
 * only its Save answers. Answered, it stays in the chat as one line that says what
 * happened, rebuilt from the event log after a reload.
 */
export const ApprovalActionCard = memo(function ApprovalActionCard({ block, onDecide }: { block: ToolBlock; onDecide?: ApprovalDecide }) {
  const approval = block.approval;
  const info = useMemo(() => cardInfoOf(block), [block]);
  if (!approval) return null;
  return approval.decision === null
    ? <OpenApproval key={approval.approvalId} block={block} approval={approval} info={info} onDecide={onDecide} />
    : <SettledApproval block={block} approval={approval} info={info} />;
});

const KIND_ICONS = {
  terminal: SquareTerminal,
  files: FilePenLine,
  browser: Globe,
  computer: Monitor,
  plan: ListChecks,
  agent: Bot,
  tool: Wrench,
} as const;

function SourceIcon({ info }: { info: ApprovalCardInfo }) {
  const { kind, app } = info.source;
  if (kind === "connector") {
    if (!app) return <Plug strokeWidth={1.75} />;
    const slug = app.toLowerCase().replace(/\s+/g, "_");
    const row: ToolChoice = {
      id: `plugin:${slug}`, label: app, description: "", category: "plugins", group: "", brand: slug,
      available: true, tool_names: [], skill: "",
    };
    return <ToolChoiceIcon row={row} size={14} />;
  }
  const Icon = KIND_ICONS[kind];
  return <Icon strokeWidth={1.75} />;
}

function subtitleLines(info: ApprovalCardInfo, approval: ApprovalState, title: string, t: T): ReactNode[] {
  const lines: ReactNode[] = [];
  const { kind } = info.source;
  if (info.where) {
    const line = fill(t(kind === "browser" ? "action_card.field.on" : "action_card.field.in"), { where: info.where });
    lines.push(info.whereFull && info.whereFull !== info.where ? <span title={info.whereFull}>{line}</span> : line);
  }
  // A command is read in its own block below; a summary that only repeats it says nothing new.
  const what = shownSummary(info, approval.summary);
  const repeatsCommand = kind === "terminal" && Boolean(info.detail) && info.detail.startsWith(approval.summary.trim());
  if (what && !repeatsCommand && kind !== "plan" && what !== title) lines.push(<span className="text-foreground-secondary">{what}</span>);
  if (info.why) lines.push(fill(t("action_card.field.why"), { why: info.why }));
  return lines;
}

function errorText(err: unknown, t: T): string {
  return err instanceof Error && err.message ? err.message : t("action_card.failed");
}

function planText(block: ToolBlock): string {
  const input = block.input && typeof block.input === "object" ? (block.input as Record<string, unknown>) : {};
  return typeof input.plan === "string" ? input.plan : "";
}

function OpenApproval({ block, approval, info, onDecide }: {
  block: ToolBlock; approval: ApprovalState; info: ApprovalCardInfo; onDecide?: ApprovalDecide;
}) {
  const t = useT();
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [choosing, setChoosing] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const mounted = useRef(true);
  useEffect(() => () => { mounted.current = false; }, []);
  const kind = info.source.kind;
  const isPlan = kind === "plan";
  const offer = isPlan ? null : info.rule;
  const title = approvalTitle(info, t);

  const decide = async (decision: ApprovalDecision, rule?: ApprovalRuleChoice) => {
    if (!onDecide || pending) return;
    setPending(decision);
    setError(null);
    try {
      if (rule) await onDecide(approval.approvalId, decision, rule);
      else await onDecide(approval.approvalId, decision);
    } catch (err) {
      if (mounted.current) setError(errorText(err, t));
    } finally {
      if (mounted.current) setPending(null);
    }
  };
  // Esc answers the newest open approval: back out of the chooser, else deny once.
  const escape = useRef<() => void>(() => {});
  escape.current = () => (choosing ? setChoosing(false) : void decide("deny"));
  useEffect(() => {
    if (!onDecide) return;
    return claimKeyboardTarget({ priority: TARGET_PRIORITY.approval, element: () => rootRef.current, onEscape: () => escape.current() });
  }, [onDecide]);

  const elsewhere = onDecide ? undefined : t("action_card.elsewhere");
  const chatHint = offer?.chat === "tool" && offer.app
    ? fill(t("action_card.rule.chat_tool"), { app: offer.app })
    : offer?.chat === "all" ? t("action_card.rule.chat_all") : undefined;
  const actions: ActionSpec[] = isPlan
    ? [
      { id: "allow", label: t("action_card.plan_build"), tone: "primary", onSelect: () => void decide("allow"), disabled: !onDecide, reason: elsewhere, testId: "action-card-allow" },
      { id: "deny", label: t("action_card.plan_keep"), tone: "tertiary", onSelect: () => void decide("deny"), disabled: !onDecide, reason: elsewhere, hint: t("action_card.deny_esc"), keyShortcut: "Escape", testId: "action-card-deny" },
    ]
    : [
      { id: "allow", label: t("action_card.allow_once"), tone: "primary", onSelect: () => void decide("allow"), disabled: !onDecide, reason: elsewhere, testId: "action-card-allow" },
      ...(offer ? [{
        id: "allow_always", label: t("action_card.always_allow_more"), tone: "secondary" as const,
        onSelect: () => setChoosing(true),
        disabled: !onDecide, reason: elsewhere, hint: chatHint, testId: "action-card-always",
      }] : []),
      { id: "deny", label: t("action_card.deny"), tone: "tertiary", onSelect: () => void decide("deny"), disabled: !onDecide, reason: elsewhere, hint: t("action_card.deny_esc"), keyShortcut: "Escape", testId: "action-card-deny" },
    ];
  const plan = isPlan ? planText(block) : "";
  const disclosure = disclosureText(info, t);
  return <ActionCard
    id={approval.approvalId}
    testId="thread-approval"
    rootRef={rootRef}
    source={{ icon: <SourceIcon info={info} />, label: sourceLabel(info, t) }}
    title={title}
    ariaLabel={`${t("action_card.needs_approval")}: ${title}`}
    lines={subtitleLines(info, approval, title, t)}
    disclosure={disclosure ? {
      text: disclosure,
      showLabel: t(kind === "terminal" ? "action_card.show_command" : "action_card.show_details"),
      hideLabel: t(kind === "terminal" ? "action_card.hide_command" : "action_card.hide_details"),
      defaultOpen: kind === "terminal" && info.detail.length <= 400,
    } : undefined}
    failure={error}
    actions={choosing ? [] : actions}
    pending={pending}
    caution={info.caution ? t(`action_card.caution.${info.caution}`) : null}
  >
    {plan ? <div className="max-h-72 overflow-auto rounded-lg bg-secondary px-3 py-2 text-sm scrollbar-jarvis"><ChatMarkdown text={plan} /></div> : null}
    {choosing && offer ? <RuleChooser offer={offer} pending={pending === "allow_always"}
      onSave={(choice) => void decide("allow_always", choice)} onBack={() => setChoosing(false)} /> : null}
  </ActionCard>;
}

/** How far a chat rule reaches: one narrow option, or the whole tool / chat. */
type Reach = RuleNarrow | "tool";

/** The rule as one sentence, for the scope and reach picked in the editor. */
export function editorSentence(offer: ApprovalRuleOffer, scope: RuleScope, breadth: RuleBreadth, reach: Reach, t: T): string {
  if (scope === "agent") return ruleSentence("always_allow", offer.app, breadth === "action" ? offer.verb : "", t);
  const narrow = reach === "tool" ? null : offer.narrow.find((option) => option.kind === reach);
  if (narrow) return narrowSentence(narrow.kind, narrow.label, t);
  if (offer.chat === "all") return t("action_card.rule.always_everything");
  return ruleSentence("always_allow", offer.app, "", t);
}

function whereLine(offer: ApprovalRuleOffer, scope: RuleScope, reach: Reach, t: T): string {
  if (scope === "agent") return t("action_card.rule.where_agent");
  if (reach === "tool" && offer.chat === "all") return t("action_card.rule.chat_all");
  return t("action_card.rule.where_chat");
}

/**
 * "Always allow" as a small rule editor: the rule read back as a sentence,
 * where it lives (this agent / this chat) and how far it reaches (one
 * action or the whole app on the agent; only this folder or this command,
 * or the whole tool, in the chat). Nothing is saved until Save; Cancel goes
 * back to the card's three answers. The narrowest reach is picked first.
 */
export function RuleChooser({ offer, pending, onSave, onBack }: {
  offer: ApprovalRuleOffer; pending: boolean; onSave: (choice: ApprovalRuleChoice) => void; onBack: () => void;
}) {
  const t = useT();
  // "This chat" is always possible: a runtime that remembers its own "always"
  // remembers it for this chat, and a surface without its own memory stops
  // asking in this chat (the sentence says which).
  const scopes: RuleScope[] = offer.scopes.includes("agent") ? ["agent", "chat"] : ["chat"];
  const [scope, setScope] = useState<RuleScope>(scopes[0]);
  const [breadth, setBreadth] = useState<RuleBreadth>("action");
  const [reach, setReach] = useState<Reach>(offer.narrow[0]?.kind ?? "tool");
  const sentence = editorSentence(offer, scope, breadth, reach, t);
  const wideLabel = offer.chat === "all"
    ? t("action_card.rule.reach_everything")
    : offer.app ? fill(t("action_card.rule.breadth_app"), { app: offer.app }) : t("action_card.rule.reach_tool_plain");
  const save = () => {
    if (scope === "agent") onSave({ scope, breadth });
    else onSave(reach === "tool" ? { scope, breadth: "action" } : { scope, breadth: "action", narrow: reach });
  };
  return <div className="action-card-rule" data-testid="action-card-rule">
    <p className="m-0 text-[13px] font-medium text-foreground">{t("action_card.rule.heading")}</p>
    <div className="mt-2 flex flex-wrap items-center gap-2">
      <Segments label={t("action_card.rule.scope_label")} value={scope} onChange={setScope}
        options={scopes.map((s) => ({ value: s, label: t(`action_card.rule.scope_${s}`) }))} />
      {scope === "agent" && offer.verb ? <Segments label={t("action_card.rule.breadth_label")} value={breadth} onChange={setBreadth}
        options={[
          { value: "action", label: fill(t("action_card.rule.breadth_action"), { verb: offer.verb }) },
          { value: "app", label: fill(t("action_card.rule.breadth_app"), { app: offer.app }) },
        ]} /> : null}
      {scope === "chat" && offer.narrow.length ? <Segments label={t("action_card.rule.breadth_label")} value={reach} onChange={setReach}
        options={[
          ...offer.narrow.map((option) => ({ value: option.kind as Reach, label: t(`action_card.rule.reach_${option.kind}`) })),
          { value: "tool" as Reach, label: wideLabel },
        ]} /> : null}
    </div>
    <p className="mt-2.5 break-words text-sm font-medium text-foreground-strong" data-testid="action-card-rule-text">{sentence}</p>
    <p className="m-0 mt-0.5 text-[13px] leading-5 text-muted-foreground" data-testid="action-card-rule-where">
      {whereLine(offer, scope, reach, t)}
    </p>
    <div className="mt-3 flex flex-wrap items-center gap-2">
      <button type="button" className="action-card-button" data-tone="primary" disabled={pending} data-testid="action-card-rule-save"
        onClick={save}>
        {t("action_card.rule.save_allow")}
      </button>
      <button type="button" className="action-card-button" data-tone="tertiary" disabled={pending} onClick={onBack}
        data-testid="action-card-rule-cancel">
        {t("action_card.rule.cancel")}
      </button>
    </div>
  </div>;
}

function Segments<V extends string>({ label, value, options, onChange }: {
  label: string; value: V; options: { value: V; label: string }[]; onChange: (value: V) => void;
}) {
  if (options.length < 2) return null;
  return <div role="radiogroup" aria-label={label} className="action-card-segments">
    {options.map((option) => <button key={option.value} type="button" role="radio" aria-checked={option.value === value}
      className="action-card-segment" onClick={() => onChange(option.value)}>
      {option.label}
    </button>)}
  </div>;
}

function SettledApproval({ block, approval, info }: { block: ToolBlock; approval: ApprovalState; info: ApprovalCardInfo }) {
  const t = useT();
  const saveRule = useAgentChat((s) => s.saveApprovalRule);
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const decision = approval.decision ?? "cancel";
  const title = approvalTitle(info, t);
  const offer = info.source.kind === "plan" ? null : info.rule;
  const saved = approval.rule;

  const save = async (id: string, rule: ApprovalRuleRequest) => {
    if (saving) return;
    setSaving(id);
    setError(null);
    try {
      await saveRule(approval.approvalId, rule);
    } catch {
      setError(t("action_card.rule.save_failed"));
    } finally {
      setSaving(null);
    }
  };
  const actions: ActionSpec[] = [];
  const unanswered = decision === "expired" || decision === "cancel";
  // A chat-wide "always" that would silence the whole chat is never offered after the fact.
  const canRemember = Boolean(offer && (offer.scopes.includes("agent") || (offer.scopes.includes("chat") && offer.chat === "tool")));
  if (unanswered && offer && canRemember && !saved) {
    const scope: RuleScope = offer.scopes.includes("agent") ? "agent" : "chat";
    actions.push({
      id: "always_next", label: t("action_card.rule.always_next_time"), tone: "secondary",
      hint: ruleSentence("always_allow", offer.app, scope === "agent" ? offer.verb : "", t),
      onSelect: () => void save("always_next", { kind: "always_allow", scope }), disabled: saving !== null, testId: "action-card-always-next",
    });
  }
  const alwaysOnAgent = decision === "allow_always" && (approval.scope === "agent" || saved?.scope === "agent");
  if (alwaysOnAgent && offer?.scopes.includes("agent") && saved?.kind !== "require_approval") {
    const breadth: RuleBreadth = saved && offer.broad && saved.pattern === offer.broad ? "app" : "action";
    actions.push({
      id: "ask_next", label: t("action_card.rule.ask_next_time"), tone: "tertiary",
      hint: ruleSentence("require_approval", offer.app, breadth === "action" ? offer.verb : "", t),
      onSelect: () => void save("ask_next", { kind: "require_approval", scope: "agent", breadth }), disabled: saving !== null, testId: "action-card-ask-next",
    });
  }
  const savedText = saved
    ? saved.scope === "chat"
      ? fill(t("action_card.rule.saved_chat"), { app: saved.narrow && saved.target ? savedRuleSentence(saved, t) : saved.app || title })
      : fill(t("action_card.rule.saved"), { rule: savedRuleSentence(saved, t) })
    : "";
  const note = decision === "expired" || decision === "cancel" || decision === "deny" ? t(`action_card.outcome_note.${decision}`) : "";
  const settled: SettledSpec = {
    tone: outcomeTone(decision),
    label: outcomeLabel(decision, t),
    detail: shownSummary(info, approval.summary) || title,
    actions,
    receipt: saved ? <span className="action-card-receipt" title={savedText} data-testid="action-card-rule-saved">
      <Check aria-hidden />{t("action_card.rule.saved_short")}
    </span> : error ? <span role="alert" className="text-[13px] text-destructive">{error}</span> : null,
    body: <>
      {note ? <p className="m-0 text-[13px] leading-5 text-muted-foreground">{note}</p> : null}
      {savedText ? <p className="m-0 text-[13px] leading-5 text-foreground-secondary">{savedText}</p> : null}
      {saved?.stillAsks ? <p className="m-0 text-[13px] leading-5 text-warning">{t("action_card.rule.still_asks")}</p> : null}
    </>,
  };
  return <ActionCard
    id={approval.approvalId}
    testId="approval-outcome"
    state={decision}
    source={{ icon: <SourceIcon info={info} />, label: sourceLabel(info, t) }}
    title={title}
    ariaLabel={`${settled.label}: ${title}`}
    lines={subtitleLines(info, approval, title, t)}
    disclosure={disclosureText(info, t) ? {
      text: disclosureText(info, t),
      showLabel: t(info.source.kind === "terminal" ? "action_card.show_command" : "action_card.show_details"),
      hideLabel: t(info.source.kind === "terminal" ? "action_card.hide_command" : "action_card.hide_details"),
    } : undefined}
    settled={settled}
  >
    {info.source.kind === "plan" && planText(block) ? <div className="max-h-56 overflow-auto rounded-lg bg-secondary px-3 py-2 text-sm scrollbar-jarvis"><ChatMarkdown text={planText(block)} /></div> : null}
  </ActionCard>;
}
