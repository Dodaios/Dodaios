/**
 * The agent pane beside the chat: tabs that persist, an Overview with the
 * six-part anatomy, in-pane drill-down with Back, the review queue with
 * "Review in chat", Retire behind ⋯ (still two-press), and a switch of agent
 * that swaps everything.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { readComposerDraft, writeComposerDraft } from "@/components/agentchat/composerDrafts";
import { useSocietyChatStore } from "@/components/society/chat/AgentChatPanel";
import { OptionsRail } from "@/components/society/card/OptionsRail";
import { AgentChatLayout } from "./AgentChatLayout";
import type { SocietyAgent } from "@/components/society/data";

function agent(over: Partial<SocietyAgent> = {}): SocietyAgent {
  return {
    agentId: "gamil-agent",
    name: "Gamil agent",
    title: "Specialist",
    description: "Look after the mail.",
    tier: "specialist",
    provider: "",
    providerLabel: "",
    model: "",
    effort: "",
    figure: null,
    palette: { primary: "#2f6f4f", secondary: "#8a5a3b", accent: "#ffd166" },
    grantMode: "all",
    toolGrants: [],
    focus: [],
    denies: [],
    approvalRules: { requireApproval: [], alwaysAllow: [] },
    permissionCeiling: "safe",
    dailyBudgetUsd: 0,
    checkpoint: "idle",
    state: "idle",
    lifecycle: "active",
    createdMs: 0,
    chatSessionId: "society:gamil-agent",
    routines: [],
    stats: { runs: 0, totalCostUsd: 0, spentTodayUsd: 0, lastActiveMs: null },
    ...over,
  } as SocietyAgent;
}

function mount(row: SocietyAgent, onRetired = vi.fn()) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity, refetchInterval: false } },
  });
  return {
    onRetired,
    client,
    ...render(
      <QueryClientProvider client={client}>
        <AgentChatLayout options={<OptionsRail agent={row} onRetired={onRetired} />}>
          <section aria-label="Chat"><textarea aria-label="Chat draft" /></section>
        </AgentChatLayout>
      </QueryClientProvider>,
    ),
  };
}

function json(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

const QUEUE = {
  items: [
    {
      id: "proposal:p1",
      kind: "proposal",
      proposal_kind: "rule",
      summary: "Add a standing rule: Reply within a day.",
      reason: "You asked twice.",
      preview: ["+ Reply within a day."],
      created_ms: 1_788_000_000_000,
    },
    {
      id: "memory:7",
      kind: "memory",
      proposal_kind: "",
      summary: "The user prefers short replies.",
      reason: "",
      preview: ["+ The user prefers short replies."],
      book: "USER.md",
      created_ms: 1_787_000_000_000,
    },
  ],
  total: 2,
  counts: { proposal: 1, memory_share: 0, memory: 1 },
};

let fetchMock: ReturnType<typeof vi.fn>;

describe("OptionsRail (agent pane)", () => {
  beforeEach(() => {
    window.localStorage.clear();
    fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      const path = String(url);
      if (path === "/api/tasks/gm1") {
        return json({ id: "gm1", title: "Inbox sweep", state: "scheduled", steps: [],
          spec: { action: { kind: "agent", prompt: "Read the inbox." } } });
      }
      if (path.includes("/review/") && init?.method === "POST") {
        return json({ id: "proposal:p1", outcome: "applied", detail: "" });
      }
      if (path.includes("/gamil-agent/review-queue")) return json(QUEUE);
      if (path.includes("/notes-agent/review-queue")) {
        return json({ items: [QUEUE.items[1]], total: 1, counts: { proposal: 0, memory_share: 0, memory: 1 } });
      }
      if (path.includes("/review-queue")) return json({ items: [], total: 0, counts: { proposal: 0, memory_share: 0, memory: 0 } });
      if (path.includes("/knowledge")) {
        return json({ files: [{ path: "memory/USER.md", name: "USER.md", kind: "memory", updated_ms: 1, size: 10 }],
          learned_instructions: ["Sign off with the user's first name."], reviews: { pending: 0, done: 1 }, last_review: null });
      }
      if (path.includes("/skills")) return json({ skills: [{ slug: "triage", name: "Inbox triage", when_to_use: "A full inbox." }] });
      if (path.includes("/capabilities")) {
        return json({ capabilities: [{ id: "plugin:gmail", kind: "plugin", label: "gmail", one_liner: "Mail", risk_tier: "monitor", connected: true, tool_name: "gmail" }] });
      }
      if (path.includes("/providers")) return json({ providers: [] });
      if (path.includes("/browser/status")) {
        return json({ installed: false, phase: "idle", percent: 0, running: false });
      }
      if (path.includes("/gamil-agent/browser") || path.includes("/scout/browser")) {
        return json({ installed: false, mode: "own", logged_in_profile: false, running: false });
      }
      if (path.includes("/gamil-agent/routines")) {
        return json({
          routines: [
            { id: "gm1", title: "[agent:Gamil] Inbox sweep", state: "scheduled", trigger: { kind: "every", interval_seconds: 18_000 } },
          ],
        });
      }
      if (path.includes("/scout/routines")) {
        return json({
          routines: [
            { id: "sc1", title: "[agent:Scout] Dawn brief", state: "scheduled", trigger: { kind: "every", interval_seconds: 86_400 } },
          ],
        });
      }
      if (path.includes("/api/society/agents")) return json({ agents: [] });
      return json({});
    });
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  test("opens on the Overview with the six-part anatomy and a calm header", async () => {
    mount(agent());
    const anatomy = await screen.findByTestId("agent-pane-anatomy");
    for (const row of ["instructions", "memory", "skills", "routines", "tools", "files"]) {
      expect(screen.getByTestId(`agent-pane-row-${row}`)).toBeTruthy();
    }
    await waitFor(() => expect(screen.getByTestId("agent-pane-row-routines").textContent).toContain("1"));
    await waitFor(() => expect(screen.getByTestId("agent-pane-row-memory").textContent).toContain("2 waiting"));
    expect(anatomy).toBeTruthy();
    expect(screen.getByTestId("edit-agent-appearance")).toBeTruthy();
    expect(screen.getByTestId("share-agent")).toBeTruthy();
    expect(screen.queryByTestId("agent-card-retire")).toBeNull();
  });

  test("Retire lives behind ⋯ and still only arms on the first press", async () => {
    const { onRetired } = mount(agent());
    fireEvent.click(screen.getByTestId("agent-card-options-more"));
    const retire = await screen.findByTestId("agent-card-retire");
    fireEvent.click(retire);
    expect(retire.dataset.armed).toBe("true");
    expect(onRetired).not.toHaveBeenCalled();
    expect(fetchMock.mock.calls.filter((c) => (c[1] as RequestInit | undefined)?.method === "DELETE")).toHaveLength(0);
  });

  test("the chosen tab survives a reload", async () => {
    const first = mount(agent());
    fireEvent.mouseDown(screen.getByTestId("agent-pane-tab-tasks"), { button: 0 });
    fireEvent.click(screen.getByTestId("agent-pane-tab-tasks"));
    await waitFor(() => expect(screen.getByTestId("agent-routines").textContent).toContain("Inbox sweep"));
    first.unmount();
    mount(agent());
    await waitFor(() => expect(screen.getByTestId("agent-routines").textContent).toContain("Inbox sweep"));
    expect(screen.getByTestId("agent-pane-tab-tasks").getAttribute("data-state")).toBe("active");
  });

  test("folding the pane keeps routine and chat drafts", async () => {
    window.localStorage.setItem("society.agentPane.tab", "tasks");
    mount(agent());
    await screen.findByText("Inbox sweep");
    const toggle = await screen.findByRole("button", { name: "Collapse Options" });
    const panel = document.getElementById(toggle.getAttribute("aria-controls")!)!;
    fireEvent.click(screen.getByTestId("agent-routines-add"));
    const title = screen.getByRole("textbox", { name: "Title" }) as HTMLInputElement;
    fireEvent.change(title, { target: { value: "Unsaved routine" } });
    const chat = screen.getByRole("textbox", { name: "Chat draft" }) as HTMLTextAreaElement;
    fireEvent.change(chat, { target: { value: "Unsent message" } });

    fireEvent.click(toggle);
    expect(panel.hidden).toBe(true);
    expect(chat.value).toBe("Unsent message");
    fireEvent.click(screen.getByRole("button", { name: "Expand Options" }));
    expect(panel.hidden).toBe(false);
    expect(screen.getByRole("textbox", { name: "Title" })).toBe(title);
    expect(title.value).toBe("Unsaved routine");
    expect(fetchMock.mock.calls.some(([, init]) => ((init as RequestInit | undefined)?.method ?? "GET") !== "GET")).toBe(false);
  });

  test("a routine draft survives a trip to another tab", async () => {
    window.localStorage.setItem("society.agentPane.tab", "tasks");
    mount(agent());
    await screen.findByText("Inbox sweep");
    fireEvent.click(screen.getByTestId("agent-routines-add"));
    fireEvent.change(screen.getByRole("textbox", { name: "Title" }), { target: { value: "Keep me" } });
    fireEvent.mouseDown(screen.getByTestId("agent-pane-tab-overview"), { button: 0 });
    await screen.findByTestId("agent-pane-anatomy");
    fireEvent.mouseDown(screen.getByTestId("agent-pane-tab-tasks"), { button: 0 });
    expect((screen.getByRole("textbox", { name: "Title" }) as HTMLInputElement).value).toBe("Keep me");
  });

  test("the browser tab shows the agent's screen", async () => {
    window.localStorage.setItem("society.agentPane.tab", "browser");
    mount(agent());
    await waitFor(() => expect(screen.getByTestId("agent-browser-preview")).toBeTruthy());
  });

  test("an anatomy row drills down in place and Back returns", async () => {
    mount(agent());
    fireEvent.click(await screen.findByTestId("agent-pane-row-instructions"));
    const input = (await screen.findByTestId("agent-pane-instructions-input")) as HTMLTextAreaElement;
    expect(input.value).toBe("Look after the mail.");
    expect(screen.getByTestId("agent-pane-subpage").textContent).toContain("Instructions");
    fireEvent.click(screen.getByTestId("agent-pane-back"));
    await screen.findByTestId("agent-pane-anatomy");
    expect(screen.queryByTestId("agent-pane-subpage")).toBeNull();
  });

  test("the review queue decides real items and seeds the chat on request", async () => {
    window.localStorage.setItem("society.agentPane.tab", "memory");
    writeComposerDraft(useSocietyChatStore, "society:gamil-agent", { text: "", choices: [] });
    mount(agent());
    await screen.findByTestId("agent-pane-review-proposal:p1");
    expect(screen.getByTestId("agent-pane-review-memory:7").textContent).toContain("The user prefers short replies.");

    fireEvent.click(screen.getByTestId("agent-pane-review-approve-proposal:p1"));
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url, init]) => String(url).includes("/review/") && (init as RequestInit)?.method === "POST");
      expect(call?.[0]).toBe("/api/society/agents/gamil-agent/review/proposal%3Ap1/approve");
    });

    fireEvent.click(screen.getByTestId("agent-pane-review-in-chat"));
    expect(readComposerDraft(useSocietyChatStore, "society:gamil-agent").text).toContain("walk me through");
    // Seeding never sends: no chat message request went out.
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/api/agent-chat/"))).toBe(false);
  });

  test("unblocking a tool asks before it is saved", async () => {
    window.localStorage.setItem("society.agentPane.tab", "tools");
    mount(agent({ denies: ["plugin:gmail"] }));
    const row = await screen.findByTestId("agent-pane-tool-plugin:gmail");
    expect(row.getAttribute("data-state")).toBe("blocked");
    fireEvent.click(row.querySelector('[data-value="on"]')!);
    fireEvent.click(await screen.findByTestId("agent-pane-save"));
    const confirm = await screen.findByTestId("agent-pane-widen");
    await waitFor(() => expect(confirm.textContent).toContain("Gmail"));
    expect(fetchMock.mock.calls.some(([, init]) => (init as RequestInit | undefined)?.method === "PATCH")).toBe(false);
  });

  test("switching agent swaps the header and the routines", async () => {
    window.localStorage.setItem("society.agentPane.tab", "tasks");
    const { rerender, client } = mount(agent());
    await waitFor(() => expect(screen.getByTestId("agent-routines").textContent).toContain("Inbox sweep"));

    rerender(
      <QueryClientProvider client={client}>
        <OptionsRail agent={agent({ agentId: "scout", name: "Scout", chatSessionId: "society:scout" })} onRetired={() => undefined} />
      </QueryClientProvider>,
    );

    await waitFor(() => expect(screen.getByTestId("agent-routines").textContent).toContain("Dawn brief"));
    expect(screen.getByTestId("agent-card-options").textContent).toContain("Scout");
    expect(screen.getByTestId("agent-routines").textContent).not.toContain("Inbox sweep");
  });

  test("only real decisions mark the Memory tab, and the review nudge can be dismissed", async () => {
    const first = mount(agent());
    await waitFor(() => expect(screen.getByTestId("agent-pane-row-memory").textContent).toContain("2 waiting"));
    expect(screen.getByTestId("agent-pane-tab-memory").querySelector(".ap-tab-badge")).toBeTruthy();
    first.unmount();

    mount(agent({ agentId: "notes-agent", chatSessionId: "society:notes-agent" }));
    await waitFor(() => expect(screen.getByTestId("agent-pane-row-memory").textContent).toContain("1 waiting"));
    // A notebook write is listed, but it does not raise a mark on the tab.
    expect(screen.getByTestId("agent-pane-tab-memory").querySelector(".ap-tab-badge")).toBeNull();
    const nudge = await screen.findByTestId("agent-pane-suggestion-review");
    fireEvent.click(within(nudge).getByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(screen.queryByTestId("agent-pane-suggestion-review")).toBeNull());
  });

  test("the lead gets a History tab and no Share", async () => {
    mount(agent({ agentId: "jarvis", name: "Jarvis", tier: "lead", chatSessionId: null }));
    expect(await screen.findByTestId("agent-pane-tab-history")).toBeTruthy();
    expect(screen.queryByTestId("share-agent")).toBeNull();
  });
});
