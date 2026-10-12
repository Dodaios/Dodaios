import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { SocietyChatGroup, SocietyTeam, SocietyTeamGoal } from "@/lib/societyChatGroups";
import type { SocietyAgent } from "../data";
import { TeamLeadBoard } from "./TeamLeadBoard";

const api = vi.hoisted(() => ({
  team: null as unknown,
  setLead: vi.fn(),
  createLead: vi.fn(),
  setMission: vi.fn(),
  setCheckin: vi.fn(),
  startGoal: vi.fn(),
  message: vi.fn(),
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
  useSocietyTeam: () => ({ data: api.team, isLoading: false, isError: false, error: null }),
  setSocietyTeamLead: api.setLead,
  createSocietyTeamLead: api.createLead,
  setSocietyTeamMission: api.setMission,
  setSocietyTeamCheckin: api.setCheckin,
  startSocietyTeamGoal: api.startGoal,
  messageSocietyTeamGoal: api.message,
  resumeSocietyTeamGoal: api.resume,
  cancelSocietyTeamGoal: api.cancel,
}));

const agent = (agentId: string, name: string, tier = "specialist") => ({
  agentId, name, tier, title: `${name} title`, lifecycle: "active", chatSessionId: `society:${agentId}`,
}) as unknown as SocietyAgent;
const roster = [agent("jarvis", "Jarvis", "lead"), agent("boss", "Boss", "orchestrator"), agent("scout", "Scout"), agent("writer", "Writer")];
const group: SocietyChatGroup = {
  group_id: "team", name: "Launch", members: ["jarvis", "boss", "scout", "writer"], created_ms: 1, updated_ms: 1, lead_agent_id: "boss",
};

function team(over: Partial<SocietyTeam> = {}): SocietyTeam {
  return {
    group_id: "team", lead_agent_id: "boss", lead_available: true, mission: "", checkin_minutes: 0,
    goals: [], working: false, max_lead_turns: 24, ...over,
  };
}

function goal(over: Partial<SocietyTeamGoal> = {}): SocietyTeamGoal {
  return {
    goal_id: "g1", group_id: "team", lead_agent_id: "boss", title: "Launch the page", text: "Launch the page",
    state: "running", report: "", note: "", lead_turns: 1, source: "board", created_ms: 1, updated_ms: 1, done_ms: null,
    tasks: [], ...over,
  };
}

function mount(onOpenAgent = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><TeamLeadBoard group={group} roster={roster} onOpenAgent={onOpenAgent} /></QueryClientProvider>);
  return onOpenAgent;
}

beforeEach(() => {
  for (const fn of [api.setLead, api.createLead, api.setMission, api.setCheckin, api.startGoal, api.message, api.resume, api.cancel]) {
    fn.mockReset();
    fn.mockImplementation(async () => api.team);
  }
});
afterEach(cleanup);

it("offers to create a lead or promote a member, never the assistant or nobody", async () => {
  api.team = team({ lead_agent_id: null, lead_available: false });
  mount();
  expect(screen.getByText("society.lead.none_title")).toBeTruthy();
  const pick = screen.getByTestId("team-lead-pick");
  expect(within(pick).getAllByRole("button").map((button) => button.textContent)).toEqual(["Boss", "Scout", "Writer"]);
  expect(screen.getByRole("button", { name: "society.lead.make" }).hasAttribute("disabled")).toBe(true);
  fireEvent.click(within(pick).getByRole("button", { name: "Scout" }));
  fireEvent.click(screen.getByRole("button", { name: "society.lead.make" }));
  await waitFor(() => expect(api.setLead).toHaveBeenCalledWith("team", "scout"));
  fireEvent.click(screen.getByTestId("team-lead-create"));
  await waitFor(() => expect(api.createLead).toHaveBeenCalledWith("team"));
});

it("gives the team a goal and clears the field once the lead has it", async () => {
  api.team = team();
  const onOpenAgent = mount();
  expect(screen.getByRole("heading", { name: "Boss" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "society.lead.open_chat" }));
  expect(onOpenAgent).toHaveBeenCalledWith("boss");

  const send = screen.getByRole("button", { name: "society.lead.goal_send" });
  expect(send.hasAttribute("disabled")).toBe(true);
  const field = screen.getByLabelText("society.lead.goal_label") as HTMLTextAreaElement;
  fireEvent.change(field, { target: { value: "  Launch the page  " } });
  fireEvent.click(send);
  await waitFor(() => expect(api.startGoal).toHaveBeenCalledWith("team", "Launch the page"));
  await waitFor(() => expect(field.value).toBe(""));
});

it("keeps the goal text and shows the reason when the team refuses it", async () => {
  api.team = team();
  api.startGoal.mockImplementation(async () => { throw new Error("The society is paused."); });
  mount();
  const field = screen.getByLabelText("society.lead.goal_label") as HTMLTextAreaElement;
  fireEvent.change(field, { target: { value: "Launch" } });
  fireEvent.click(screen.getByRole("button", { name: "society.lead.goal_send" }));
  expect((await screen.findByRole("alert")).textContent).toBe("The society is paused.");
  expect(field.value).toBe("Launch");
});

it("shows each task with its member, state and result", () => {
  api.team = team({
    working: true,
    goals: [goal({
      tasks: [
        { task_id: "t1", goal_id: "g1", agent_id: "scout", title: "Research", brief: "", state: "done", result: "Three found.", reviewed: true, created_ms: 1, updated_ms: 2, done_ms: 2 },
        { task_id: "t2", goal_id: "g1", agent_id: "writer", title: "Draft", brief: "", state: "running", result: "", reviewed: false, created_ms: 2, updated_ms: 2, done_ms: null },
      ],
    })],
  });
  mount();
  expect(screen.getByRole("status").textContent).toBe("society.lead.working");
  const card = screen.getByTestId("team-goal-g1");
  expect(card.getAttribute("data-state")).toBe("running");
  const research = within(card).getByTestId("team-task-t1");
  expect(research.textContent).toContain("Scout");
  expect(research.textContent).toContain("society.lead.task_state_done");
  expect(within(research).queryByText("Three found.")).toBeNull();
  fireEvent.click(within(research).getByRole("button", { name: "society.lead.show_result" }));
  expect(within(research).getByText("Three found.")).toBeTruthy();
  const draft = within(card).getByTestId("team-task-t2");
  expect(draft.textContent).toContain("society.lead.task_state_running");
  expect(within(draft).queryByRole("button")).toBeNull();
});

it("shows a goal's text once: the full first line as heading, the rest below", () => {
  const long = "Research the three largest cities of the country and then do a good deal more with them";
  api.team = team({
    goals: [
      goal({ title: `${long.slice(0, 40)}…`, text: `${long}
Second line with details.` }),
      goal({ goal_id: "g2", title: "Short goal", text: "Short goal" }),
      goal({ goal_id: "g3", title: "Given title", text: "A different description." }),
    ],
  });
  mount();
  const cut = screen.getByTestId("team-goal-g1");
  expect(within(cut).getByRole("heading", { level: 4 }).textContent).toBe(long);
  expect(within(cut).getByText("Second line with details.")).toBeTruthy();
  expect(cut.textContent?.split(long).length).toBe(2);
  const short = screen.getByTestId("team-goal-g2");
  expect(short.textContent?.split("Short goal").length).toBe(2);
  const given = screen.getByTestId("team-goal-g3");
  expect(within(given).getByRole("heading", { level: 4 }).textContent).toBe("Given title");
  expect(within(given).getByText("A different description.")).toBeTruthy();
});

it("answers the lead's question and stops a goal", async () => {
  api.team = team({ goals: [goal({ state: "needs_input", report: "Which market?", note: "question" })] });
  mount();
  const card = screen.getByTestId("team-goal-g1");
  expect(within(card).getByText("society.lead.question")).toBeTruthy();
  expect(within(card).getByText("Which market?")).toBeTruthy();
  fireEvent.change(within(card).getByLabelText("society.lead.answer_placeholder"), { target: { value: "Germany" } });
  fireEvent.click(within(card).getByRole("button", { name: "society.lead.send" }));
  await waitFor(() => expect(api.message).toHaveBeenCalledWith("team", "g1", "Germany"));
  fireEvent.click(within(card).getByRole("button", { name: "society.lead.stop" }));
  await waitFor(() => expect(api.cancel).toHaveBeenCalledWith("team", "g1"));
});

it("explains why a goal is paused and continues it", async () => {
  api.team = team({
    goals: [
      goal({ state: "paused", note: "turn_budget" }),
      goal({ goal_id: "g2", state: "paused", note: "error:provider unavailable" }),
      goal({ goal_id: "g3", state: "queued" }),
      goal({ goal_id: "g4", state: "done", report: "All shipped." }),
    ],
  });
  mount();
  expect(within(screen.getByTestId("team-goal-g1")).getByText("society.lead.note_turn_budget")).toBeTruthy();
  expect(within(screen.getByTestId("team-goal-g2")).getByText("society.lead.note_error")).toBeTruthy();
  fireEvent.click(within(screen.getByTestId("team-goal-g1")).getByRole("button", { name: "society.lead.resume" }));
  await waitFor(() => expect(api.resume).toHaveBeenCalledWith("team", "g1"));
  const queued = screen.getByTestId("team-goal-g3");
  expect(within(queued).getByRole("button", { name: "society.lead.start_now" })).toBeTruthy();
  expect(within(queued).getByRole("button", { name: "society.lead.remove_goal" })).toBeTruthy();
  // A finished goal keeps its report and offers nothing to do.
  const done = screen.getByTestId("team-goal-g4");
  expect(within(done).getByText("All shipped.")).toBeTruthy();
  expect(within(done).queryByRole("button")).toBeNull();
  expect(screen.getByText("society.lead.finished")).toBeTruthy();
});

it("saves the mission, switches check-ins and changes the lead", async () => {
  api.team = team({ mission: "Ship the launch." });
  mount();
  const mission = screen.getByLabelText("society.lead.mission") as HTMLTextAreaElement;
  await waitFor(() => expect(mission.value).toBe("Ship the launch."));
  expect(screen.queryByRole("button", { name: "society.lead.mission_save" })).toBeNull();
  fireEvent.change(mission, { target: { value: "Ship it by Friday." } });
  fireEvent.click(screen.getByRole("button", { name: "society.lead.mission_save" }));
  await waitFor(() => expect(api.setMission).toHaveBeenCalledWith("team", "Ship it by Friday."));

  fireEvent.click(within(screen.getByTestId("team-lead-checkin")).getByRole("button", { name: "society.lead.checkin_60" }));
  await waitFor(() => expect(api.setCheckin).toHaveBeenCalledWith("team", 60));

  fireEvent.click(screen.getByRole("button", { name: "society.lead.change" }));
  // The current lead is not offered as its own replacement.
  expect(within(screen.getByTestId("team-lead-pick")).getAllByRole("button").map((button) => button.textContent)).toEqual(["Scout", "Writer"]);
  fireEvent.click(screen.getByRole("button", { name: "society.lead.remove" }));
  await waitFor(() => expect(api.setLead).toHaveBeenCalledWith("team", null));
});
