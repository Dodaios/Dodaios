import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { create } from "zustand";

import type { SocietyAgent } from "../data";
import { modeSupported, runnerFor } from "./approvalModes";
import { AgentHeader } from "./AgentHeader";

vi.mock("@/i18n", () => ({ useT: () => (key: string) => key, useUiLanguage: () => "en" }));
vi.mock("../chat/AgentModelPicker", () => ({
  AgentModelPicker: ({ agent }: { agent: SocietyAgent }) => <button type="button">model:{agent.model || "default"}</button>,
}));
const chatStore = vi.hoisted(() => ({ hook: null as unknown }));
vi.mock("../chat/AgentChatPanel", () => {
  chatStore.hook = create(() => ({ busy: false, activeSessionId: null }));
  return { useSocietyChatStore: chatStore.hook };
});

function agent(over: Partial<SocietyAgent> = {}): SocietyAgent {
  return {
    agentId: "scout",
    name: "Scout",
    title: "Research scout",
    description: "",
    tier: "specialist",
    provider: "codex",
    providerLabel: "Codex",
    model: "gpt-x",
    effort: "",
    figure: null,
    palette: { primary: "#000", secondary: "#111", accent: "#222" },
    grantMode: "all",
    toolGrants: [],
    focus: [],
    denies: [],
    approvalRules: { requireApproval: [], alwaysAllow: [] },
    permissionCeiling: "ask",
    approvalMode: "ask",
    dailyBudgetUsd: 0,
    checkpoint: "idle",
    state: "idle",
    lifecycle: "active",
    createdMs: 0,
    maxConcurrentRuns: 1,
    workspaceDir: "",
    wikiNamespace: "",
    chatSessionId: "society:scout",
    routines: [],
    stats: { runs: 0, totalCostUsd: 0, spentTodayUsd: 0, lastActiveMs: null },
    ...over,
  };
}

const providers = [
  { id: "codex", runner: "codex-cli" },
  { id: "claude-api", runner: "claude-cli" },
  { id: "opencode", runner: "opencode-cli" },
];

function json(body: unknown, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
}

function mount(row: SocietyAgent, fetcher = vi.fn(async (url: string) => (String(url).endsWith("/providers") ? json({ providers }) : json({})))) {
  vi.stubGlobal("fetch", fetcher);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><AgentHeader agent={row} detailsToggle={<button type="button">details</button>} /></QueryClientProvider>);
  return { fetcher, client };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("approval mode support", () => {
  it("mirrors the server's runner rules", () => {
    expect(runnerFor({ provider: "", runtime: "jarvis" }, providers)).toBe("brain");
    expect(runnerFor({ provider: "codex", runtime: "hermes" }, providers)).toBe("hermes-cli");
    expect(runnerFor({ provider: "codex", runtime: "openclaw" }, providers)).toBe("openclaw-cli");
    expect(runnerFor({ provider: "codex" }, providers)).toBe("codex-cli");
    expect(runnerFor({ provider: "codex" }, undefined)).toBeNull();

    expect(modeSupported("brain", "always_ask")).toBe(true);
    expect(modeSupported("codex-cli", "always_ask")).toBe(true);
    expect(modeSupported("claude-cli", "always_ask")).toBe(false);
    expect(modeSupported("claude-cli", "ask")).toBe(true);
    expect(modeSupported("hermes-cli", "ask")).toBe(true);
    expect(modeSupported("openclaw-cli", "ask")).toBe(true);
    expect(modeSupported("opencode-cli", "ask")).toBe(false);
    expect(modeSupported(null, "ask")).toBe(false);
    expect(modeSupported(null, "bypass")).toBe(true);
  });
});

describe("AgentHeader", () => {
  it("shows identity, the live phrase, the brain picker and the details toggle", () => {
    mount(agent({ state: "working" }));
    expect(screen.getByTestId("agent-header-name").textContent).toBe("Scout");
    expect(screen.getByTestId("agent-header-status").textContent).toBe("society.shell.preview_working");
    expect(screen.getByRole("button", { name: "model:gpt-x" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "details" })).toBeTruthy();
  });

  it("says why the agent waits when the backend names a reason", () => {
    mount({ ...agent({ state: "waiting" }), waiting_reason: { kind: "approval", summary: "Send the invoice?" } } as SocietyAgent);
    expect(screen.getByTestId("agent-header-status").textContent).toBe("society.shell.preview_needs_you · Send the invoice?");
  });

  it("shows no brain or approval picker for the lead, whose chat follows the app's own choice", () => {
    mount(agent({ tier: "lead", agentId: "jarvis", name: "Jarvis" }));
    expect(screen.queryByTestId("agent-header-model")).toBeNull();
    expect(screen.queryByTestId("agent-header-approval")).toBeNull();
  });

  it("offers only the modes the runner can honour", async () => {
    mount(agent({ provider: "claude-api", approvalMode: "ask" }));
    fireEvent.click(screen.getByTestId("agent-header-approval"));
    await waitFor(() => expect((screen.getByTestId("approval-mode-ask") as HTMLButtonElement).disabled).toBe(false));
    expect((screen.getByTestId("approval-mode-always_ask") as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByTestId("approval-mode-bypass") as HTMLButtonElement).disabled).toBe(false);
  });

  it("lets a Hermes agent ask but not always ask", async () => {
    mount(agent({ provider: "codex", runtime: "hermes", approvalMode: "bypass" }));
    fireEvent.click(screen.getByTestId("agent-header-approval"));
    await waitFor(() => expect((screen.getByTestId("approval-mode-ask") as HTMLButtonElement).disabled).toBe(false));
    expect((screen.getByTestId("approval-mode-always_ask") as HTMLButtonElement).disabled).toBe(true);
  });

  it("tightens at once but asks once more before loosening", async () => {
    const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
      if (String(url).endsWith("/providers")) return json({ providers });
      if (init?.method === "PATCH") return json({});
      return json({});
    });
    mount(agent({ approvalMode: "ask" }), fetcher);
    const patches = () => fetcher.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === "PATCH");

    fireEvent.click(screen.getByTestId("agent-header-approval"));
    await waitFor(() => expect((screen.getByTestId("approval-mode-always_ask") as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByTestId("approval-mode-always_ask"));
    await waitFor(() => expect(patches()).toHaveLength(1));
    expect(JSON.parse(String((patches()[0][1] as RequestInit).body))).toEqual({ approval_mode: "always_ask" });

    fireEvent.click(screen.getByTestId("agent-header-approval"));
    fireEvent.click(await screen.findByTestId("approval-mode-bypass"));
    expect(patches()).toHaveLength(1);
    expect(screen.getByTestId("approval-mode-bypass").textContent).toContain("society.shell.approval_confirm");
    fireEvent.click(screen.getByTestId("approval-mode-bypass"));
    await waitFor(() => expect(patches()).toHaveLength(2));
    expect(JSON.parse(String((patches()[1][1] as RequestInit).body))).toEqual({ approval_mode: "bypass" });
  });

  it("keeps the menu open with the server's reason when a save is refused", async () => {
    const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
      if (String(url).endsWith("/providers")) return json({ providers });
      if (init?.method === "PATCH") return json({ detail: "This runner cannot provide an actionable approval for that mode." }, 422);
      return json({});
    });
    mount(agent({ approvalMode: "bypass" }), fetcher);
    fireEvent.click(screen.getByTestId("agent-header-approval"));
    await waitFor(() => expect((screen.getByTestId("approval-mode-ask") as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByTestId("approval-mode-ask"));
    expect((await screen.findByRole("alert")).textContent).toContain("cannot provide");
    expect(screen.getByRole("menu")).toBeTruthy();
  });
});
