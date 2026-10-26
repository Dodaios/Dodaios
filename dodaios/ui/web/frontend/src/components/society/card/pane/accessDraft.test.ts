import { describe, expect, test } from "vitest";

import { agentConfigBody, type SocietyAgent } from "../../data";
import {
  draftFromAgent,
  normalizeDomain,
  patchFromDraft,
  setGrantMode,
  setToolState,
  toolState,
  widenings,
} from "./accessDraft";

const BASE = {
  agentId: "mail",
  name: "Mail",
  tier: "specialist",
  grantMode: "all",
  toolGrants: [],
  focus: ["plugin:gmail"],
  denies: ["cli:gh"],
  approvalRules: { requireApproval: ["plugin:gmail:send"], alwaysAllow: [] },
  permissionCeiling: "monitor",
  approvalMode: "ask",
  dailyBudgetUsd: 2,
  maxConcurrentRuns: 1,
  browserMode: "own",
  browserAllowedDomains: ["mail.google.com"],
} as unknown as SocietyAgent;

describe("access draft", () => {
  test("an untouched draft sends nothing", () => {
    expect(patchFromDraft(BASE, draftFromAgent(BASE))).toEqual({});
    expect(widenings(BASE, draftFromAgent(BASE))).toEqual([]);
  });

  test("tool states move between denies, focus and grants", () => {
    let draft = draftFromAgent(BASE);
    expect(toolState(draft, "plugin:gmail")).toBe("first");
    expect(toolState(draft, "cli:gh")).toBe("blocked");
    expect(toolState(draft, "plugin:notion")).toBe("on");
    draft = setToolState(draft, "plugin:notion", "first");
    expect(draft.focus).toEqual(["plugin:gmail", "plugin:notion"]);
    draft = setToolState(draft, "plugin:gmail", "blocked");
    expect(draft.focus).toEqual(["plugin:notion"]);
    expect(draft.denies).toContain("plugin:gmail");
    expect(patchFromDraft(BASE, draft)).toEqual({ focus: ["plugin:notion"], denies: ["cli:gh", "plugin:gmail"] });
  });

  test("moving to an allow-list keeps the focus tools as its hands", () => {
    const draft = setGrantMode(draftFromAgent(BASE), "allowlist");
    expect(draft.grants).toEqual(["plugin:gmail"]);
    expect(toolState(draft, "plugin:notion")).toBe("off");
    expect(widenings(BASE, draft)).toEqual([]);
  });

  test("every widening is named; a narrowing is not", () => {
    let draft = draftFromAgent(BASE);
    draft = setToolState(draft, "cli:gh", "on");
    draft = { ...draft, approvalMode: "bypass", permissionCeiling: "ask", alwaysAllow: ["plugin:gmail:send"], requireApproval: [] };
    draft = { ...draft, browserMode: "attach", domains: [] };
    expect(widenings(BASE, draft).map((w) => w.key)).toEqual([
      "unblocked", "approval_mode", "ceiling", "always_allow", "require_removed", "browser_attach", "domains_opened",
    ]);
    const stricter = { ...draftFromAgent(BASE), approvalMode: "always_ask" as const, permissionCeiling: "safe" as const };
    expect(widenings(BASE, stricter)).toEqual([]);
  });

  test("the patch maps onto the route's field names", () => {
    const draft = { ...draftFromAgent(BASE), budgetOn: false, jobs: "3", domains: ["example.com"] };
    expect(agentConfigBody(patchFromDraft(BASE, draft))).toEqual({
      daily_budget_usd: 0,
      max_concurrent_runs: 3,
      browser_allowed_domains: ["example.com"],
    });
  });

  test("pasted sites become bare host names", () => {
    expect(normalizeDomain("https://Mail.Google.com/u/0/#inbox")).toBe("mail.google.com");
    expect(normalizeDomain("example.com:8080")).toBe("example.com");
    expect(normalizeDomain("not a site")).toBe("");
  });
});
