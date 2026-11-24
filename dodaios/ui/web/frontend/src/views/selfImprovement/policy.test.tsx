/**
 * How coding agents are steered, on the Self-improvement page: a policy the
 * steering learner put in place reads as one plain sentence with the
 * measurement that let it in, and can be taken back; a policy on trial says
 * what it has to show; the stored reasons stay in the case file.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { SelfImprovementView } from "@/views/SelfImprovementView";
import { loadLocaleChunk, setUiLanguage } from "@/i18n";
import { policyProof } from "@/views/selfImprovement/policy";
import type { LearnedChange, Measurement, SelfImprovementOverview } from "@/lib/selfImprovementApi";

const NOW = Date.now();
const DAY = 86_400_000;
const CELL = "backend|claude-opus-5-5|claude-cli 2.1";
const FACTORY = { hold: false, p_max: 2, evidence_wait_s: 2700, lines: [] as string[] };
const LINE = "Keep every existing test and its assertions; when one fails, fix the code, or say why the test is wrong.";

const ADMITTED: Measurement = {
  ts_ms: NOW - DAY,
  step: "admit",
  verdict: "accept",
  split: "",
  reason: "branch A: the PassRate rises by 0.10 or more within the cost budget",
  domain: "backend",
  diff: 18 / 65,
  low: 0.131,
  high: null,
  n: 65,
  cost_diff: 0.01,
  metric: "pass",
  n_reference: 65,
  arms: {
    candidate: { n: 65, pass: 60 / 65, one: 0.85, p: 0.2, cost: 0.17, churn: 10 },
    reference: { n: 65, pass: 42 / 65, one: 0.65, p: 0, cost: 0.16, churn: 10 },
  },
};

function hold(overrides: Partial<LearnedChange> = {}): LearnedChange {
  return {
    id: "p1",
    surface: "coding_policy",
    target: `${CELL}#active`,
    state: "trial",
    author: "rsi-selector",
    reason: "accepted by the selector's gate: branch A (65 against 65 requests)",
    measured: true,
    since_ms: NOW - DAY,
    before: FACTORY,
    after: { ...FACTORY, hold: true },
    default: null,
    doc: "",
    admitted: ADMITTED,
    last_check: null,
    policy: {
      cell: CELL,
      slot: "active",
      domain: "backend",
      model: "claude-opus-5-5",
      harness: "claude-cli 2.1",
      kinds: ["hold"],
      lines: [],
      claim: { branch: "A", target: "pass" },
    },
    ...overrides,
  };
}

function lineOnTrial(): LearnedChange {
  const held = { ...FACTORY, hold: true };
  return hold({
    id: "p2",
    target: "testing|(default)|codex-cli 0.9#candidate",
    reason: `one line for the first brief of testing|(default)|codex-cli 0.9: '${LINE}'`,
    before: held,
    after: { ...held, lines: [LINE] },
    admitted: null,
    policy: {
      cell: "testing|(default)|codex-cli 0.9",
      slot: "candidate",
      domain: "testing",
      model: "(default)",
      harness: "codex-cli 0.9",
      kinds: ["brief_line"],
      lines: [LINE],
      claim: { branch: "B", target: "p" },
    },
  });
}

function overview(stack: LearnedChange[], candidates: LearnedChange[] = []): SelfImprovementOverview {
  return {
    status: { app: "5.7.0", paused: false, readonly: false, last_night_ms: NOW - DAY, next_night_ms: NOW + DAY, decides_on: ["made"], own_tasks: true },
    limits: { idle_after_s: 900, every_s: 72_000, budget_share: 0.2, max_model_calls: 8 },
    domains: [
      { domain: "recall", tasks: { practice: 0, select: 0, guard: 0, sealed: 0 }, tasks_total: 0, all_tasks: {}, measured: false, point: null },
    ],
    series: [],
    stack,
    candidates,
    nights: [],
    resting: [],
    now_ms: NOW,
  };
}

function installFetch(start: SelfImprovementOverview) {
  const calls: { url: string; method: string }[] = [];
  let current = start;
  (globalThis as unknown as { fetch: typeof fetch }).fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    calls.push({ url, method });
    if (method === "GET" && url === "/api/self-improvement") {
      const payload = current;
      return { ok: true, status: 200, json: async () => payload } as Response;
    }
    const undo = /^\/api\/self-improvement\/changes\/([^/]+)\/undo$/.exec(url);
    if (method === "POST" && undo) {
      current = { ...current, stack: current.stack.filter((c) => c.id !== undo[1]) };
      return { ok: true, status: 200, json: async () => ({ ok: true, reverted: [undo[1]] }) } as Response;
    }
    return { ok: false, status: 404, json: async () => ({ detail: "nope" }) } as Response;
  }) as unknown as typeof fetch;
  return calls;
}

function renderView() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SelfImprovementView />
    </QueryClientProvider>,
  );
}

describe("coding policies on the Self-improvement page", () => {
  beforeEach(async () => {
    setUiLanguage("en");
    await loadLocaleChunk("self_improvement");
  });
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("lists a policy in one plain sentence with the measurement that let it in, and takes it back", async () => {
    const calls = installFetch(overview([hold()]));
    renderView();
    const [row] = await screen.findAllByTestId("si-change-row");
    expect(row.dataset.surface).toBe("coding_policy");
    expect(within(row).getByTestId("si-policy-sentence").textContent).toBe(
      "Waits for the checks and asks for fixes, for backend work with claude-opus-5-5 in claude-cli 2.1",
    );
    expect(row.textContent).toContain("On trial");
    expect(within(row).getByTestId("si-change-proof").textContent).toBe(
      "Passed 92% of 65 requests, against 65% of 65 without it (at least +13.1 points)",
    );
    expect(row.textContent).not.toContain("→"); // a policy has no value to show
    expect(screen.getByTestId("si-stack-kinds").textContent).toContain("how it steers coding agents");

    fireEvent.click(within(row).getByTestId("si-undo"));
    await waitFor(() => expect(screen.queryAllByTestId("si-change-row")).toHaveLength(0));
    expect(calls.some((c) => c.method === "POST" && c.url === "/api/self-improvement/changes/p1/undo")).toBe(true);
  });

  it("opens a policy into its case file with both halves of its trial and the stored reason", async () => {
    installFetch(overview([hold()]));
    renderView();
    fireEvent.click((await screen.findAllByTestId("si-change-row"))[0]);
    const detail = await screen.findByTestId("si-change-detail");
    expect(detail.textContent).toContain("Waits for the checks and asks for fixes, for backend work");
    expect(within(detail).getByTestId("si-detail-policy-proof").textContent).toBe(
      "Passed 92% of 65 requests, against 65% of 65 without it (at least +13.1 points)",
    );
    expect(detail.textContent).toContain("Measured on 65 of your requests with it and 65 without it");
    expect(within(detail).getByTestId("si-detail-reason-admitted").textContent).toBe(ADMITTED.reason);
    expect(detail.textContent).toContain("the first run under it that weakens a check takes it back by itself");
    expect(detail.textContent).toContain("The steering learner");
    expect(within(detail).queryByTestId("si-detail-values")).toBeNull();
    expect(within(detail).getByTestId("si-detail-undo")).toBeTruthy();
  });

  it("shows a line on trial with its words, what it has to show, and no Take back", async () => {
    installFetch(overview([], [lineOnTrial()]));
    renderView();
    const [row] = await screen.findAllByTestId("si-change-row");
    expect(within(row).getByTestId("si-policy-sentence").textContent).toBe(
      "Adds a line to the first brief, for testing work with the default model in codex-cli 0.9",
    );
    expect(within(row).getByTestId("si-policy-lines").textContent).toBe(`“${LINE}”`);
    expect(row.textContent).toContain("on trial on half of your requests since");
    expect(within(row).getByTestId("si-change-proof").textContent).toBe(
      "kept only if fewer fixes are needed and nothing gets worse",
    );
    expect(within(row).queryByTestId("si-undo")).toBeNull();
    fireEvent.click(row);
    const detail = await screen.findByTestId("si-change-detail");
    expect(within(detail).getByTestId("si-detail-policy-trial").textContent).toContain("on trial on half of your requests");
    expect(within(detail).queryByTestId("si-detail-undo")).toBeNull();
  });

  it("words a cheaper or a fix-sparing policy by its own metric", () => {
    const t = (key: string) =>
      ({
        "self_improvement.policy.proof_cost": "{diff} less, {n}/{m}, at least {low}",
        "self_improvement.policy.proof_p": "{diff} fewer, {n}/{m}, at least {low}",
        "self_improvement.effect.none": "not measured",
      })[key] ?? key;
    const cost = { ...ADMITTED, metric: "cost", diff: 0.12, low: 0.031, n: 70, n_reference: 68 };
    expect(policyProof(t, cost, "en")).toBe("$0.12 less, 70/68, at least $0.031");
    const fixes = { ...ADMITTED, metric: "p", diff: 0.35, low: 0.1, n: 70, n_reference: 68 };
    expect(policyProof(t, fixes, "en")).toBe("0.35 fewer, 70/68, at least 0.1");
    expect(policyProof(t, null, "en")).toBe("not measured");
    expect(policyProof(t, { ...ADMITTED, arms: null }, "en")).toBe("not measured");
  });
});
