import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useEventStore } from "@/store/events";
import { useAgentNavigation } from "@/views/society/agentNavigation";

import { AttentionBell } from "./AttentionBell";
import { AttentionInbox } from "./AttentionInbox";
import { quickActionsFor, type AttentionItem } from "./attentionApi";
import { resetAttentionStore, useAttentionStore } from "./attentionStore";
import { resetNotificationPrefs, useNotificationPrefs } from "./notificationPrefs";

const api = vi.hoisted(() => ({
  answer: vi.fn(async () => undefined),
  approve: vi.fn(async () => undefined),
}));
vi.mock("@/lib/agentChatApi", () => ({
  answerAgentChatQuestion: api.answer,
  resolveAgentChatApproval: api.approve,
}));
vi.mock("@/components/society/data", () => ({
  useSocietyRoster: () => ({
    data: {
      sample: false,
      agents: [
        { agentId: "scout", name: "Scout", tier: "specialist", state: "waiting", palette: {}, figure: null },
        { agentId: "brain", name: "Brain", tier: "specialist", state: "idle", palette: {}, figure: null },
      ],
    },
  }),
}));
vi.mock("@/components/society/AgentSwatch", () => ({ AgentSwatch: () => <span data-testid="swatch" /> }));

const NOW = Date.now();

const ROWS = [
  {
    kind: "question", agent_id: "scout", session_id: "society:scout", ref_id: "q1",
    summary: "Which database should the project use?", since_ms: NOW - 5 * 60_000, expires_ms: NOW + 120_000,
    source: "chat",
    detail: { question: "Which database should the project use?", options: ["SQLite", "Postgres"], step: 0, count: 2, single: true },
  },
  {
    kind: "approval", agent_id: "brain", session_id: "society:brain", ref_id: "a1",
    summary: "Run the migration", since_ms: NOW - 10 * 60_000, expires_ms: null, source: "chat", detail: { tool: "shell" },
  },
  {
    kind: "credential", agent_id: "scout", session_id: "society:scout", ref_id: "c1",
    summary: "GitHub token", since_ms: NOW - 60_000, expires_ms: null, source: "chat", detail: { label: "GitHub token" },
  },
];

function stubList(rows: unknown[] = ROWS) {
  const fetchMock = vi.fn(async (url: string) => {
    if (String(url).startsWith("/api/agent-chat/attention")) {
      return new Response(JSON.stringify({ items: rows, count: rows.length }));
    }
    return new Response("{}", { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

beforeEach(() => {
  resetAttentionStore();
  resetNotificationPrefs();
  useAgentNavigation.setState({ request: null, onScreen: null });
  useEventStore.setState({ activeSection: "agents" });
  api.answer.mockClear();
  api.approve.mockClear();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("AttentionInbox", () => {
  it("groups the waiting items by agent, longest wait first", async () => {
    stubList();
    render(<AttentionInbox />);
    const groups = await screen.findAllByTestId("attention-group");
    expect(groups.map((g) => g.dataset.agentId)).toEqual(["brain", "scout"]);
    const scoutItems = within(groups[1]).getAllByTestId("attention-item");
    expect(scoutItems.map((i) => i.dataset.kind)).toEqual(["question", "credential"]);
    expect(within(groups[1]).getByText("1 of 2", { exact: false })).toBeTruthy();
    expect(screen.getByTestId("attention-inbox-count").textContent).toBe("3");
  });

  it("answers a one-pick question in place and lets the row go", async () => {
    stubList();
    render(<AttentionInbox />);
    const options = await screen.findAllByTestId("attention-option");
    expect(options.map((o) => o.textContent)).toEqual(["ASQLite", "BPostgres"]);
    fireEvent.click(options[1]);
    await waitFor(() => expect(api.answer).toHaveBeenCalledWith("society:scout", "q1", 0, { optionIndex: 1 }));
    await waitFor(() => expect(useAttentionStore.getState().list?.items.some((i) => i.refId === "q1")).toBe(false), {
      timeout: 2000,
    });
    expect(useAttentionStore.getState().count).toBe(2);
  });

  it("allows an approval once, never always", async () => {
    stubList();
    render(<AttentionInbox />);
    const allow = await screen.findByTestId("attention-allow");
    expect(screen.getByTestId("attention-deny")).toBeTruthy();
    fireEvent.click(allow);
    await waitFor(() => expect(api.approve).toHaveBeenCalledWith("society:brain", "a1", "allow"));
  });

  it("shows a failed answer instead of dropping the row", async () => {
    stubList();
    api.approve.mockRejectedValueOnce(new Error("boom"));
    render(<AttentionInbox />);
    fireEvent.click(await screen.findByTestId("attention-deny"));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(useAttentionStore.getState().list?.items).toHaveLength(3);
  });

  it("opens the agent at its card and closes", async () => {
    stubList();
    const onClose = vi.fn();
    render(<AttentionInbox onClose={onClose} />);
    const credential = (await screen.findAllByTestId("attention-item")).find((i) => i.dataset.kind === "credential")!;
    fireEvent.click(within(credential).getByText("GitHub token"));
    expect(useAgentNavigation.getState().request).toMatchObject({
      agentId: "scout", sessionId: "society:scout", cardRef: "c1", kind: "credential",
    });
    expect(onClose).toHaveBeenCalled();
  });

  it("mutes one agent from its group", async () => {
    stubList();
    render(<AttentionInbox />);
    const groups = await screen.findAllByTestId("attention-group");
    const mute = within(groups[0]).getByRole("button", { pressed: false });
    fireEvent.click(mute);
    expect(useNotificationPrefs.getState().muted).toEqual(["brain"]);
  });

  it("says plainly when nothing is waiting", async () => {
    stubList([]);
    render(<AttentionInbox />);
    expect(await screen.findByTestId("attention-inbox-empty")).toBeTruthy();
  });
});

describe("quickActionsFor", () => {
  const base: AttentionItem = {
    kind: "proposal", agentId: "a", sessionId: "s", refId: "r", summary: "", sinceMs: 0,
    expiresMs: null, deferred: false, source: "queue", detail: {},
  };
  it("offers only what can be settled safely in one tap", () => {
    expect(quickActionsFor(base).map((a) => a.type)).toEqual(["deny", "allow"]);
    expect(quickActionsFor({ ...base, detail: { proposal_kind: "team" } })).toEqual([]);
    expect(quickActionsFor({ ...base, kind: "credential" })).toEqual([]);
    expect(quickActionsFor({ ...base, kind: "question", detail: { options: ["x", "y"], single: false } })).toEqual([]);
  });
});

describe("AttentionBell", () => {
  it("shows the count and opens the inbox under it", async () => {
    stubList();
    render(<AttentionBell />);
    const bell = screen.getByTestId("attention-bell");
    await waitFor(() => expect(screen.getByTestId("attention-bell-count").textContent).toBe("3"));
    expect(document.title.startsWith("(3) ")).toBe(true);
    fireEvent.click(bell);
    expect(await screen.findByTestId("attention-inbox")).toBeTruthy();
    expect(bell.getAttribute("aria-expanded")).toBe("true");
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByTestId("attention-inbox")).toBeNull());
  });

  it("hides the count at zero", async () => {
    stubList([]);
    render(<AttentionBell />);
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.queryByTestId("attention-bell-count")).toBeNull();
  });
});
