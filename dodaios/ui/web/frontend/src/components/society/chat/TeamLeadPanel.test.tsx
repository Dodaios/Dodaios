import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { SocietyChatGroup, SocietyTeam, SocietyTeamGoal, SocietyTeamTask } from "@/lib/societyChatGroups";
import type { SocietyAgent } from "../data";
import { TeamLeadPanel, initiativeMode } from "./TeamLeadPanel";

const api = vi.hoisted(() => ({
  setLead: vi.fn(),
  createLead: vi.fn(),
  setMission: vi.fn(),
  setCheckin: vi.fn(),
  resume: vi.fn(),
  cancel: vi.fn(),
}));

vi.mock("@/i18n", () => ({ useT: () => (key: string) => key }));
vi.mock("../AgentSwatch", () => ({ AgentSwatch: () => <i data-testid="swatch" /> }));
vi.mock("./AgentChatPanel", () => ({ Prose: ({ text }: { text: string }) => <p>{text}</p> }));
vi.mock("@/components/ui/select", () => ({
  BrandedSelect: ({ options, onValueChange, testId, value }: {
    options: { value: string; label: string }[]; onValueChange: (value: string) => void; testId: string; value: string;
  }) => <div data-testid={testId} data-value={value}>
    {options.map((option) => <button key={option.value} type="button" onClick={() => onValueChange(option.value)}>{option.label}</button>)}
  </div>,
}));
vi.mock("@/lib/societyChatGroups", () => ({
  TEAM_GOAL_OPEN: ["queued", "running", "needs_input", "paused"],
  setSocietyTeamLead: api.setLead,
  createSocietyTeamLead: api.createLead,
  setSocietyTeamMission: api.setMission,
  setSocietyTeamCheckin: api.setCheckin,
  resumeSocietyTeamGoal: api.resume,
  cancelSocietyTeamGoal: api.cancel,
}));

const agent = (agentId: string, name: string, tier = "specialist", state = "idle") => ({
  agentId, name, tier, title: `${name} title`, lifecycle: "active", state, chatSessionId: `society:${agentId}`,
}) as unknown as SocietyAgent;
const roster = [
  agent("jarvis", "Jarvis", "lead"), agent("boss", "Boss", "orchestrator"), agent("scout", "Scout"),
  agent("writer", "Writer", "specialist", "paused"),
];
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

function task(over: Partial<SocietyTeamTask> = {}): SocietyTeamTask {
  return {
    task_id: "t1", goal_id: "g1", agent_id: "scout", title: "Research", brief: "Find three", state: "running",
    result: "", reviewed: false, created_ms: 1, updated_ms: 1, done_ms: null, ...over,
  };
}

interface Mounted {
  run: ReturnType<typeof vi.fn>;
  leadChanged: ReturnType<typeof vi.fn>;
  onOpenAgent: ReturnType<typeof vi.fn>;
  onSetupOpen: ReturnType<typeof vi.fn>;
}

function mount(value: SocietyTeam, setupOpen = false): Mounted {
  const run = vi.fn(async (_key: string, action: () => Promise<SocietyTeam>) => { await action(); return true; });
  const leadChanged = vi.fn(async (_key: string, action: () => Promise<SocietyTeam>) => { await action(); return true; });
  const onOpenAgent = vi.fn();
  const onSetupOpen = vi.fn();
  render(<TeamLeadPanel team={value} group={group} roster={roster} busy="" setupOpen={setupOpen} onSetupOpen={onSetupOpen}
    run={run} leadChanged={leadChanged} onOpenAgent={onOpenAgent} />);
  return { run, leadChanged, onOpenAgent, onSetupOpen };
}

beforeEach(() => {
  for (const fn of Object.values(api)) {
    fn.mockReset();
    fn.mockImplementation(async () => team());
  }
});
afterEach(cleanup);

it("reads the three ways a lead works from the check-in and its initiative", () => {
  expect(initiativeMode({ checkin_minutes: 0, initiative: false })).toBe("off");
  expect(initiativeMode({ checkin_minutes: 0, initiative: true })).toBe("off");
  expect(initiativeMode({ checkin_minutes: 60, initiative: false })).toBe("watch");
  expect(initiativeMode({ checkin_minutes: 240, initiative: true })).toBe("drive");
});

it("says there is nothing in progress and points at the chat", () => {
  mount(team());
  expect(screen.getByText("society.lead.now_empty")).toBeTruthy();
  expect(screen.queryByText("society.lead.next")).toBeNull();
  expect(screen.queryByTestId("team-lead-finished")).toBeNull();
});

it("shows the goal in progress with every task, and a result only when asked", () => {
  mount(team({
    goals: [goal({
      text: "Launch the page\nBy Friday, in German.",
      tasks: [task(), task({ task_id: "t2", agent_id: "writer", title: "Copy", state: "done", result: "Draft is ready." })],
    })],
  }));
  const card = within(screen.getByTestId("team-goal-g1"));
  expect(card.getByRole("heading", { name: "Launch the page" })).toBeTruthy();
  expect(card.getByText("By Friday, in German.")).toBeTruthy();
  expect(card.getByText("society.lead.state_running")).toBeTruthy();
  expect(within(screen.getByTestId("team-task-t1")).getByText("society.lead.task_state_running")).toBeTruthy();
  const done = within(screen.getByTestId("team-task-t2"));
  expect(done.queryByText("Draft is ready.")).toBeNull();
  fireEvent.click(done.getByRole("button", { name: "society.lead.show_result" }));
  expect(done.getByText("Draft is ready.")).toBeTruthy();
});

it("shows the lead's question and sends the person to the chat for the answer", () => {
  mount(team({ goals: [goal({ state: "needs_input", report: "Which market?" })] }));
  const card = within(screen.getByTestId("team-goal-g1"));
  expect(card.getByText("society.lead.question")).toBeTruthy();
  expect(card.getByText("Which market?")).toBeTruthy();
  expect(card.getByText("society.lead.answer_in_chat")).toBeTruthy();
  // The answer is a chat message, so the card carries no text field of its own.
  expect(card.queryByRole("textbox")).toBeNull();
});

it("continues a paused goal, with the reason it stopped, and stops one in progress", async () => {
  const { run } = mount(team({ goals: [goal({ state: "paused", note: "turn_budget" })] }));
  expect(screen.getByText("society.lead.note_turn_budget")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "society.lead.resume" }));
  await waitFor(() => expect(api.resume).toHaveBeenCalledWith("team", "g1"));
  expect(run.mock.calls[0][0]).toBe("resume:g1");
  fireEvent.click(screen.getByRole("button", { name: "society.lead.stop" }));
  await waitFor(() => expect(api.cancel).toHaveBeenCalledWith("team", "g1"));
});

it("lists what waits behind the current goal", () => {
  mount(team({ goals: [goal(), goal({ goal_id: "g2", title: "Write the post", text: "Write the post", state: "queued", created_ms: 2 })] }));
  expect(screen.getByText("society.lead.next")).toBeTruthy();
  const queued = within(screen.getByTestId("team-goal-g2"));
  expect(queued.getByRole("button", { name: "society.lead.start_now" })).toBeTruthy();
  expect(queued.getByRole("button", { name: "society.lead.remove_goal" })).toBeTruthy();
});

it("shows each member with what it is on, and opens its chat", () => {
  const { onOpenAgent } = mount(team({ goals: [goal({ tasks: [task()] })] }));
  expect(screen.queryByTestId("team-member-boss")).toBeNull();
  expect(screen.queryByTestId("team-member-jarvis")).toBeNull();
  const scout = within(screen.getByTestId("team-member-scout"));
  expect(scout.getByText("Research")).toBeTruthy();
  expect(scout.getByText("society.lead.member_working")).toBeTruthy();
  const writer = within(screen.getByTestId("team-member-writer"));
  expect(writer.getByText("Writer title")).toBeTruthy();
  expect(writer.getByText("society.lead.member_paused")).toBeTruthy();
  fireEvent.click(screen.getByTestId("team-member-scout"));
  expect(onOpenAgent).toHaveBeenCalledWith("scout");
});

it("keeps finished goals folded, one line each, and opens a report on request", async () => {
  mount(team({
    goals: [
      goal({ goal_id: "d1", title: "Old launch", text: "Old launch", state: "done", report: "Shipped." }),
      goal({ goal_id: "f1", title: "Broken", text: "Broken", state: "failed", note: "error:boom" }),
    ],
  }));
  const fold = screen.getByRole("button", { name: "society.lead.finished" });
  expect(fold.getAttribute("aria-expanded")).toBe("false");
  expect(screen.queryByTestId("team-goal-d1")).toBeNull();
  fireEvent.click(fold);
  expect(screen.queryByText("Shipped.")).toBeNull();
  fireEvent.click(screen.getByTestId("team-goal-d1"));
  expect(screen.getByText("Shipped.")).toBeTruthy();
  fireEvent.click(screen.getByTestId("team-goal-f1"));
  expect(screen.getByText("society.lead.note_error")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "society.lead.retry" }));
  await waitFor(() => expect(api.resume).toHaveBeenCalledWith("team", "f1"));
});

it("folds a long report until the person asks for all of it", () => {
  const long = "A ".repeat(400);
  mount(team({ goals: [goal({ report: long })] }));
  const more = screen.getByRole("button", { name: "society.lead.show_more" });
  expect(more.getAttribute("aria-expanded")).toBe("false");
  fireEvent.click(more);
  expect(screen.getByRole("button", { name: "society.lead.show_less" }).getAttribute("aria-expanded")).toBe("true");
});

it("keeps the setup folded until it is opened", () => {
  const { onSetupOpen } = mount(team());
  expect(screen.queryByLabelText("society.lead.mission")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "society.lead.setup" }));
  expect(onSetupOpen).toHaveBeenCalledWith(true);
});

it("switches how the lead works: only when asked, watching, or taking the initiative", async () => {
  mount(team(), true);
  expect(screen.getByTestId("team-initiative-off").getAttribute("aria-checked")).toBe("true");
  expect(screen.queryByTestId("team-lead-checkin")).toBeNull();
  fireEvent.click(screen.getByTestId("team-initiative-watch"));
  await waitFor(() => expect(api.setCheckin).toHaveBeenCalledWith("team", 240, false));
  fireEvent.click(screen.getByTestId("team-initiative-drive"));
  await waitFor(() => expect(api.setCheckin).toHaveBeenCalledWith("team", 240, true));
});

it("changes the rhythm without changing the way, and asks for a mission to drive from", async () => {
  mount(team({ checkin_minutes: 60, initiative: true }), true);
  expect(screen.getByTestId("team-initiative-drive").getAttribute("aria-checked")).toBe("true");
  expect(screen.getByRole("note").textContent).toBe("society.lead.initiative_needs_mission");
  expect(screen.getByTestId("team-lead-checkin").getAttribute("data-value")).toBe("60");
  fireEvent.click(within(screen.getByTestId("team-lead-checkin")).getByText("society.lead.checkin_1440"));
  await waitFor(() => expect(api.setCheckin).toHaveBeenCalledWith("team", 1440, true));
  fireEvent.click(screen.getByTestId("team-initiative-off"));
  await waitFor(() => expect(api.setCheckin).toHaveBeenCalledWith("team", 0, false));
  // Choosing the way that is already on changes nothing.
  api.setCheckin.mockClear();
  fireEvent.click(screen.getByTestId("team-initiative-drive"));
  expect(api.setCheckin).not.toHaveBeenCalled();
});

it("saves the mission only when it changed", async () => {
  mount(team({ mission: "Ship the launch.", checkin_minutes: 60, initiative: true }), true);
  expect(screen.queryByRole("note")).toBeNull();
  expect(screen.queryByRole("button", { name: "society.lead.mission_save" })).toBeNull();
  fireEvent.change(screen.getByLabelText("society.lead.mission"), { target: { value: "Ship it by Friday." } });
  fireEvent.click(screen.getByRole("button", { name: "society.lead.mission_save" }));
  await waitFor(() => expect(api.setMission).toHaveBeenCalledWith("team", "Ship it by Friday."));
});

it("changes who leads: another member, a new lead, or nobody", async () => {
  const { leadChanged } = mount(team(), true);
  const picker = screen.getByTestId("team-lead-pick");
  expect(within(picker).queryByText("Boss")).toBeNull();
  expect(within(picker).queryByText("Jarvis")).toBeNull();
  fireEvent.click(within(picker).getByText("Writer"));
  fireEvent.click(screen.getByRole("button", { name: "society.lead.make" }));
  await waitFor(() => expect(api.setLead).toHaveBeenCalledWith("team", "writer"));
  fireEvent.click(screen.getByTestId("team-lead-create"));
  await waitFor(() => expect(api.createLead).toHaveBeenCalledWith("team"));
  fireEvent.click(screen.getByRole("button", { name: "society.lead.remove" }));
  await waitFor(() => expect(api.setLead).toHaveBeenCalledWith("team", null));
  expect(leadChanged.mock.calls.map((call) => call[0])).toEqual(["pick", "create", "remove"]);
});
