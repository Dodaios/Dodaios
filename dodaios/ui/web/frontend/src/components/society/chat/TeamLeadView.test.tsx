import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { SocietyChatGroup, SocietyTeam, SocietyTeamGoal } from "@/lib/societyChatGroups";
import type { SocietyAgent } from "../data";
import { TeamLeadView } from "./TeamLeadView";

const api = vi.hoisted(() => ({
  team: null as unknown,
  setLead: vi.fn(),
  createLead: vi.fn(),
  setMission: vi.fn(),
  setCheckin: vi.fn(),
  resume: vi.fn(),
  cancel: vi.fn(),
}));

/** The lead's chat store: what the action row reads and where it sends. */
const chat = vi.hoisted(() => {
  const state = {
    busy: false,
    running: false,
    activeSessionId: "society:boss" as string | null,
    send: vi.fn(async () => "sent" as const),
    disconnect: vi.fn(),
  };
  const hook = Object.assign((selector: (value: typeof state) => unknown) => selector(state), { getState: () => state });
  return { state, hook, namespaces: [] as string[] };
});

vi.mock("@/i18n", () => ({ useT: () => (key: string) => key }));
vi.mock("@/components/agentchat/reduce", () => ({ runningTurn: () => (chat.state.running ? { id: "t1" } : null) }));
vi.mock("../AgentSwatch", () => ({ AgentSwatch: () => <i data-testid="swatch" /> }));
vi.mock("@/store/agentChat", () => ({
  createAgentChatStore: (_surface: string, namespace: string) => {
    chat.namespaces.push(namespace);
    return chat.hook;
  },
}));
vi.mock("./AgentChatPanel", () => ({
  CHAT_MEASURE: "measure",
  Prose: ({ text }: { text: string }) => <p>{text}</p>,
  AgentChatPanel: ({ agent, composerExtras }: { agent: SocietyAgent; composerExtras?: ReactNode }) => (
    <div data-testid={`chat-${agent.agentId}`}>{composerExtras}</div>
  ),
}));
vi.mock("@/components/ui/select", () => ({
  BrandedSelect: ({ options, onValueChange, testId, value }: {
    options: { value: string; label: string }[]; onValueChange: (value: string) => void; testId: string; value: string;
  }) => <div data-testid={testId} data-value={value}>
    {options.map((option) => <button key={option.value} type="button" onClick={() => onValueChange(option.value)}>{option.label}</button>)}
  </div>,
}));
vi.mock("@/lib/societyChatGroups", () => ({
  TEAM_GOAL_OPEN: ["queued", "running", "needs_input", "paused"],
  useSocietyTeam: () => ({ data: api.team, isLoading: false, isError: false, error: null }),
  setSocietyTeamLead: api.setLead,
  createSocietyTeamLead: api.createLead,
  setSocietyTeamMission: api.setMission,
  setSocietyTeamCheckin: api.setCheckin,
  resumeSocietyTeamGoal: api.resume,
  cancelSocietyTeamGoal: api.cancel,
}));

const agent = (agentId: string, name: string, tier = "specialist") => ({
  agentId, name, tier, title: `${name} title`, lifecycle: "active", state: "idle", chatSessionId: `society:${agentId}`,
}) as unknown as SocietyAgent;
const roster = [agent("jarvis", "Jarvis", "lead"), agent("boss", "Boss", "orchestrator"), agent("scout", "Scout"), agent("writer", "Writer")];
const group: SocietyChatGroup = {
  group_id: "team", name: "Launch", members: ["jarvis", "boss", "scout", "writer"], created_ms: 1, updated_ms: 1, lead_agent_id: "boss",
};

function team(over: Partial<SocietyTeam> = {}): SocietyTeam {
  return {
    group_id: "team", lead_agent_id: "boss", lead_available: true, mission: "", checkin_minutes: 0, initiative: false,
    goals: [], working: false, max_lead_turns: 24, ...over,
  };
}

function goal(over: Partial<SocietyTeamGoal> = {}): SocietyTeamGoal {
  return {
    goal_id: "g1", group_id: "team", lead_agent_id: "boss", title: "Launch the page", text: "Launch the page",
    state: "running", report: "", note: "", lead_turns: 1, source: "chat", created_ms: 1, updated_ms: 1, done_ms: null,
    tasks: [], ...over,
  };
}

function mount(onOpenAgent = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><TeamLeadView group={group} roster={roster} onOpenAgent={onOpenAgent} /></QueryClientProvider>);
  return onOpenAgent;
}

beforeEach(() => {
  for (const fn of [api.setLead, api.createLead, api.setMission, api.setCheckin, api.resume, api.cancel]) {
    fn.mockReset();
    fn.mockImplementation(async () => api.team);
  }
  chat.state.busy = false;
  chat.state.running = false;
  chat.state.activeSessionId = "society:boss";
  chat.state.send.mockClear();
  chat.state.disconnect.mockClear();
  chat.namespaces.length = 0;
  window.localStorage.clear();
  window.localStorage.setItem("society.lead.panel", "open");
});
afterEach(cleanup);

it("offers to create a lead or promote a member, never the assistant", async () => {
  api.team = team({ lead_agent_id: null, lead_available: false });
  mount();
  expect(screen.getByText("society.lead.none_title")).toBeTruthy();
  expect(screen.queryByTestId("chat-boss")).toBeNull();
  const picker = screen.getByTestId("team-lead-pick");
  expect(within(picker).queryByText("Jarvis")).toBeNull();
  fireEvent.click(within(picker).getByText("Scout"));
  fireEvent.click(screen.getByRole("button", { name: "society.lead.make" }));
  await waitFor(() => expect(api.setLead).toHaveBeenCalledWith("team", "scout"));
  fireEvent.click(screen.getByTestId("team-lead-create"));
  await waitFor(() => expect(api.createLead).toHaveBeenCalledWith("team"));
});

it("is the lead's own chat, marked as the lead's, with the team beside it", () => {
  api.team = team();
  mount();
  expect(screen.getByTestId("chat-boss")).toBeTruthy();
  expect(chat.namespaces).toEqual(["group:team:lead"]);
  expect(screen.getByText("Boss")).toBeTruthy();
  expect(screen.getByText("society.lead.role")).toBeTruthy();
  expect(screen.getByTestId("team-lead-status").textContent).toBe("society.lead.status_idle");
  expect(screen.getByTestId("team-lead-panel")).toBeTruthy();
  // The chat is the one place to write: the view adds no goal form of its own.
  expect(screen.queryByRole("textbox", { name: /goal/i })).toBeNull();
});

it("sends a lead action as the person's own message", () => {
  api.team = team();
  mount();
  const actions = within(screen.getByTestId("team-lead-actions"));
  expect(actions.getAllByRole("button").map((button) => button.textContent)).toEqual([
    "society.lead.action_status", "society.lead.action_next", "society.lead.action_check", "society.lead.action_drive",
  ]);
  fireEvent.click(screen.getByTestId("team-lead-action-drive"));
  expect(chat.state.send).toHaveBeenCalledWith("society.lead.action_drive_prompt");
});

it("holds the lead actions back while a message is on its way, the lead is in a turn, or its chat is not open yet", () => {
  api.team = team();
  chat.state.busy = true;
  mount();
  expect((screen.getByTestId("team-lead-action-status") as HTMLButtonElement).disabled).toBe(true);
  cleanup();
  chat.state.busy = false;
  chat.state.running = true;
  mount();
  expect((screen.getByTestId("team-lead-action-status") as HTMLButtonElement).disabled).toBe(true);
  cleanup();
  chat.state.running = false;
  chat.state.activeSessionId = "society:someone-else";
  mount();
  expect((screen.getByTestId("team-lead-action-status") as HTMLButtonElement).disabled).toBe(true);
});

it("says in one line what the team is doing and what waits for the person", () => {
  api.team = team({ goals: [goal()] });
  mount();
  expect(screen.getByTestId("team-lead-status").textContent).toBe("society.lead.status_running");
  cleanup();
  api.team = team({ goals: [goal()], working: true });
  mount();
  expect(screen.getByTestId("team-lead-status").textContent).toBe("society.lead.working");
  cleanup();
  api.team = team({ goals: [goal({ state: "needs_input", report: "Which market?" })] });
  mount();
  expect(screen.getByTestId("team-lead-status").textContent).toBe("society.lead.status_needs_input");
  cleanup();
  api.team = team({ goals: [goal({ state: "paused", note: "turn_budget" })] });
  mount();
  expect(screen.getByTestId("team-lead-status").textContent).toBe("society.lead.status_paused");
  cleanup();
  api.team = team({ lead_available: false });
  mount();
  expect(screen.getByTestId("team-lead-status").textContent).toBe("society.lead.unavailable");
});

it("folds the team panel away and remembers it; the closed panel still counts open work", () => {
  api.team = team({ goals: [goal(), goal({ goal_id: "g2", state: "queued" })] });
  mount();
  const toggle = screen.getByTestId("team-lead-panel-toggle");
  expect(toggle.getAttribute("aria-pressed")).toBe("true");
  fireEvent.click(toggle);
  expect(screen.queryByTestId("team-lead-panel")).toBeNull();
  expect(window.localStorage.getItem("society.lead.panel")).toBe("closed");
  expect(toggle.textContent).toContain("2");
  expect(screen.getByTestId("chat-boss")).toBeTruthy();
  cleanup();
  mount();
  expect(screen.queryByTestId("team-lead-panel")).toBeNull();
});

it("shows how the lead works at a glance and opens the setup from there", () => {
  api.team = team({ checkin_minutes: 60, initiative: true });
  window.localStorage.setItem("society.lead.panel", "closed");
  mount();
  const chip = screen.getByTestId("team-lead-initiative");
  expect(chip.getAttribute("data-mode")).toBe("drive");
  expect(chip.textContent).toBe("society.lead.initiative_drive");
  fireEvent.click(chip);
  const setup = screen.getByTestId("team-lead-setup");
  expect(within(setup).getByTestId("team-initiative-drive").getAttribute("aria-checked")).toBe("true");
});

it("shows a refused action as written", async () => {
  api.team = team({ goals: [goal({ state: "paused" })] });
  api.resume.mockRejectedValueOnce(new Error("The society is paused."));
  mount();
  fireEvent.click(screen.getByRole("button", { name: "society.lead.resume" }));
  expect((await screen.findByRole("alert")).textContent).toBe("The society is paused.");
});
