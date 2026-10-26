/**
 * The Tools & access tab as plain data: a draft of everything the tab edits,
 * the one-tool state machine, the PATCH that carries only what changed, and
 * the list of changes that WIDEN what the agent may do (those ask first).
 *
 * Kept free of React so every rule here is unit-tested on its own.
 */
import type { AgentApprovalMode, BrowserMode } from "@/lib/societyApi";

import type { AgentConfigPatch, GrantMode, PermissionCeiling, SocietyAgent } from "../../data";

export interface AccessDraft {
  grantMode: GrantMode;
  grants: string[];
  focus: string[];
  denies: string[];
  approvalMode: AgentApprovalMode | null;
  permissionCeiling: PermissionCeiling;
  requireApproval: string[];
  alwaysAllow: string[];
  budgetOn: boolean;
  /** Kept as typed text so a half-typed number is not reformatted under the cursor. */
  budget: string;
  jobs: string;
  browserMode: BrowserMode;
  domains: string[];
}

/** How one capability stands for this agent. `off` exists only on an allow-list. */
export type ToolState = "blocked" | "off" | "on" | "first";

export function draftFromAgent(agent: SocietyAgent): AccessDraft {
  return {
    grantMode: agent.grantMode,
    grants: [...agent.toolGrants],
    focus: [...agent.focus],
    denies: [...agent.denies],
    approvalMode: agent.approvalMode ?? null,
    permissionCeiling: agent.permissionCeiling,
    requireApproval: [...agent.approvalRules.requireApproval],
    alwaysAllow: [...agent.approvalRules.alwaysAllow],
    budgetOn: agent.dailyBudgetUsd > 0,
    budget: String(agent.dailyBudgetUsd > 0 ? agent.dailyBudgetUsd : 2),
    jobs: String(agent.maxConcurrentRuns),
    browserMode: agent.browserMode ?? "own",
    domains: [...(agent.browserAllowedDomains ?? [])],
  };
}

export function toolState(draft: AccessDraft, id: string): ToolState {
  if (draft.denies.includes(id)) return "blocked";
  if (draft.focus.includes(id)) return "first";
  if (draft.grantMode === "allowlist") return draft.grants.includes(id) ? "on" : "off";
  return "on";
}

const without = (list: string[], id: string) => list.filter((x) => x !== id);
const withId = (list: string[], id: string) => (list.includes(id) ? list : [...list, id]);

export function setToolState(draft: AccessDraft, id: string, state: ToolState): AccessDraft {
  const allowlist = draft.grantMode === "allowlist";
  switch (state) {
    case "blocked":
      return { ...draft, denies: withId(draft.denies, id), focus: without(draft.focus, id), grants: without(draft.grants, id) };
    case "off":
      return { ...draft, denies: without(draft.denies, id), focus: without(draft.focus, id), grants: without(draft.grants, id) };
    case "on":
      return {
        ...draft,
        denies: without(draft.denies, id),
        focus: without(draft.focus, id),
        grants: allowlist ? withId(draft.grants, id) : draft.grants,
      };
    case "first":
      return {
        ...draft,
        denies: without(draft.denies, id),
        focus: withId(draft.focus, id),
        grants: allowlist ? withId(draft.grants, id) : draft.grants,
      };
  }
}

/**
 * Switch between "everything connected" and "only what I pick". Moving to an
 * allow-list starts from the tools the agent reaches for first, so it is never
 * left with no hands by one click.
 */
export function setGrantMode(draft: AccessDraft, mode: GrantMode): AccessDraft {
  if (mode === draft.grantMode) return draft;
  if (mode === "allowlist" && draft.grants.length === 0) {
    return { ...draft, grantMode: mode, grants: [...draft.focus] };
  }
  return { ...draft, grantMode: mode };
}

const sameList = (a: string[], b: string[]) => a.length === b.length && a.every((x, i) => x === b[i]);
const sameSet = (a: string[], b: string[]) => a.length === b.length && a.every((x) => b.includes(x));

export function budgetValue(draft: AccessDraft): number {
  return draft.budgetOn ? Math.max(0, Number.parseFloat(draft.budget) || 0) : 0;
}

export function jobsValue(draft: AccessDraft): number {
  return Math.min(10, Math.max(1, Number.parseInt(draft.jobs, 10) || 1));
}

/** Only the fields that differ from the agent: a budget edit never carries prose or tools along. */
export function patchFromDraft(agent: SocietyAgent, draft: AccessDraft): AgentConfigPatch {
  const patch: AgentConfigPatch = {};
  if (draft.grantMode !== agent.grantMode) patch.grantMode = draft.grantMode;
  if (!sameSet(draft.grants, agent.toolGrants)) patch.toolGrants = draft.grants;
  if (!sameList(draft.focus, agent.focus)) patch.focus = draft.focus;
  if (!sameSet(draft.denies, agent.denies)) patch.denies = draft.denies;
  if (draft.approvalMode && draft.approvalMode !== (agent.approvalMode ?? null)) patch.approvalMode = draft.approvalMode;
  if (draft.permissionCeiling !== agent.permissionCeiling) patch.permissionCeiling = draft.permissionCeiling;
  if (
    !sameSet(draft.requireApproval, agent.approvalRules.requireApproval) ||
    !sameSet(draft.alwaysAllow, agent.approvalRules.alwaysAllow)
  ) {
    patch.approvalRules = { requireApproval: draft.requireApproval, alwaysAllow: draft.alwaysAllow };
  }
  if (budgetValue(draft) !== agent.dailyBudgetUsd) patch.dailyBudgetUsd = budgetValue(draft);
  if (jobsValue(draft) !== agent.maxConcurrentRuns) patch.maxConcurrentRuns = jobsValue(draft);
  if (draft.browserMode !== (agent.browserMode ?? "own")) patch.browserMode = draft.browserMode;
  if (!sameSet(draft.domains, agent.browserAllowedDomains ?? [])) patch.browserAllowedDomains = draft.domains;
  return patch;
}

export function isDirty(agent: SocietyAgent, draft: AccessDraft): boolean {
  return Object.keys(patchFromDraft(agent, draft)).length > 0;
}

/** One change that lets the agent do more than before. `items` names what, when that helps. */
export interface Widening {
  key:
    | "reach_all"
    | "tools_added"
    | "unblocked"
    | "approval_mode"
    | "ceiling"
    | "always_allow"
    | "require_removed"
    | "browser_attach"
    | "domains_opened";
  items: string[];
}

const MODE_RANK: Record<AgentApprovalMode, number> = { always_ask: 0, ask: 1, bypass: 2 };
const CEILING_RANK: Record<PermissionCeiling, number> = { safe: 0, monitor: 1, ask: 2 };

export function widenings(agent: SocietyAgent, draft: AccessDraft): Widening[] {
  const out: Widening[] = [];
  if (agent.grantMode === "allowlist" && draft.grantMode === "all") out.push({ key: "reach_all", items: [] });
  if (draft.grantMode === "allowlist") {
    const added = draft.grants.filter((id) => agent.grantMode === "allowlist" && !agent.toolGrants.includes(id));
    if (added.length) out.push({ key: "tools_added", items: added });
  }
  const unblocked = agent.denies.filter((id) => !draft.denies.includes(id));
  if (unblocked.length) out.push({ key: "unblocked", items: unblocked });
  if (draft.approvalMode && agent.approvalMode && MODE_RANK[draft.approvalMode] > MODE_RANK[agent.approvalMode]) {
    out.push({ key: "approval_mode", items: [draft.approvalMode] });
  }
  if (CEILING_RANK[draft.permissionCeiling] > CEILING_RANK[agent.permissionCeiling]) {
    out.push({ key: "ceiling", items: [draft.permissionCeiling] });
  }
  const allowed = draft.alwaysAllow.filter((p) => !agent.approvalRules.alwaysAllow.includes(p));
  if (allowed.length) out.push({ key: "always_allow", items: allowed });
  const unasked = agent.approvalRules.requireApproval.filter((p) => !draft.requireApproval.includes(p));
  if (unasked.length) out.push({ key: "require_removed", items: unasked });
  if ((agent.browserMode ?? "own") === "own" && draft.browserMode === "attach") out.push({ key: "browser_attach", items: [] });
  const before = agent.browserAllowedDomains ?? [];
  if (before.length > 0) {
    const opened = draft.domains.length === 0 ? ["*"] : draft.domains.filter((d) => !before.includes(d));
    if (opened.length) out.push({ key: "domains_opened", items: opened });
  }
  return out;
}

/** "example.com" from what a person pastes: a URL, a host with a path, mixed case. */
export function normalizeDomain(raw: string): string {
  const text = raw.trim().toLowerCase();
  if (!text) return "";
  const host = text.replace(/^[a-z]+:\/\//, "").split(/[/?#]/)[0].replace(/:\d+$/, "");
  return /^[a-z0-9*][a-z0-9.*-]*\.[a-z0-9-]+$/.test(host) ? host : "";
}
