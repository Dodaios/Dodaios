import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { LAST_AGENT_STORAGE_KEY } from "./lastAgent";
import { SocietyView } from "./SocietyView";

const app = vi.hoisted(() => ({ instance: { name: "default", isDev: false } }));
const groupsState = vi.hoisted(() => ({ groups: [] as Array<{ group_id: string; name: string; members: string[] }> }));
const quick = vi.hoisted(() => ({ create: vi.fn(async (): Promise<{ agentId: string }> => ({ agentId: "specialist" })) }));
vi.mock("@/hooks/useAppInstance", () => ({ useAppInstance: () => app.instance }));
beforeEach(() => {
  app.instance = { name: "default", isDev: false }; groupsState.groups = [];
  quick.create.mockReset(); quick.create.mockResolvedValue({ agentId: "specialist" });
});

vi.mock("@/lib/mapFullscreen", () => ({ setMapFullscreen: vi.fn(async () => undefined) }));
vi.mock("@tanstack/react-query", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@tanstack/react-query")>()),
  useQueryClient: () => ({ invalidateQueries: async () => undefined }),
}));
vi.mock("@/i18n", () => ({ useT: () => (key: string) => key, useLocaleChunk: () => true }));
vi.mock("@/components/society/chat/useModelMenuData", () => ({ useModelMenuData: () => undefined }));
vi.mock("@/lib/societyChatGroups", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/societyChatGroups")>()), useSocietyChatGroups: () => ({ data: groupsState.groups, isSuccess: true, isError: false, failureCount: 0 }) }));
vi.mock("@/components/society/chat/ChatGroupPanel", () => ({ ChatGroupPanel: ({ group, onOpenAgent }: any) => <div data-testid="group-workspace">{group.name}<button onClick={() => onOpenAgent("specialist")}>Open member</button></div> }));
vi.mock("@/components/society/data", () => ({ useQuickCreateAgent: () => quick.create, useSocietyRoster: () => ({ data: { sample: false, agents: [
  { agentId: "lead", name: "Lead", tier: "lead", state: "idle" },
  { agentId: "specialist", name: "Specialist", tier: "specialist", state: "idle" },
] }, isLoading: false }) }));
vi.mock("@/views/DodaiosAgentsView", () => ({ DodaiosAgentsView: ({ active, onSelectAgent, onOpenAgents, onMarsSelectionChange }: any) => (
  <div data-testid="map" data-active={active}><button onClick={() => onSelectAgent("specialist")}>Map specialist</button><button onClick={onOpenAgents}>Map fallback</button><div data-mars-ui><input aria-label="Mars draft" /></div><div data-mars-mode="player"><button>Player viewport</button></div><div data-mars-mode="follow"><button>Follow viewport</button></div><button onClick={() => onMarsSelectionChange(false)}>Previous world</button><button onClick={() => onMarsSelectionChange(true)}>Mars world</button></div>
) }));
vi.mock("@/components/society/mars/MarsStationPanel", () => ({ MarsStationPanel: ({ onClose }: any) => <aside aria-label="Mars station"><button onClick={onClose}>Close station</button></aside> }));
vi.mock("@/components/society/card/AgentCardOverlay", () => ({ AgentCardOverlay: ({ agent, embedded, onSelectAgent, onSelectGroup, onCreate, railHeader }: any) => (
  <div data-testid="workspace" data-embedded={String(embedded)}>
    {railHeader}
    <span>{agent.name}</span><input aria-label="Draft" />
    <button onClick={() => onSelectAgent("specialist")}>Select specialist</button>
    <button onClick={() => onSelectGroup?.("team")}>Open group</button>
    <button onClick={onCreate}>Create agent</button>
  </div>
) }));
vi.mock("@/components/society/roster/RosterRail", () => ({ RosterRail: () => <div data-testid="roster" /> }));
vi.mock("@/components/society/card/BuildingCardOverlay", () => ({ BuildingCardOverlay: () => null }));

const initialUrl = window.location.href;
afterEach(() => { cleanup(); window.history.replaceState(null, "", initialUrl); localStorage.removeItem(LAST_AGENT_STORAGE_KEY); });

it("defaults to the embedded Agents workspace even with a saved legacy ledger preference", () => {
  localStorage.setItem("jarvis.agents.mode.v2", "ledger");
  render(<SocietyView />);
  expect(screen.getByTestId("workspace").getAttribute("data-embedded")).toBe("true");
  expect(screen.getByText("Lead")).toBeTruthy();
  expect(screen.queryByTestId("map")).toBeNull();
  localStorage.removeItem("jarvis.agents.mode.v2");
});

it("opens a group from the agent rail and returns to an individual member chat", () => {
  groupsState.groups = [{ group_id: "team", name: "Launch team", members: ["specialist"] }];
  render(<SocietyView />);
  fireEvent.click(screen.getByText("Open group"));
  expect(screen.getByTestId("group-workspace").textContent).toContain("Launch team");
  fireEvent.click(screen.getByText("Open member"));
  expect(screen.getByTestId("workspace").textContent).toContain("Specialist");
});

it("restores the most recently selected agent after the view is remounted", () => {
  const firstVisit = render(<SocietyView />);
  fireEvent.click(screen.getByText("Select specialist"));
  expect(localStorage.getItem(LAST_AGENT_STORAGE_KEY)).toBe("specialist");

  firstVisit.unmount();
  render(<SocietyView />);

  expect(screen.getByText("Specialist")).toBeTruthy();
});

it("one click creates an agent and opens its chat", async () => {
  render(<SocietyView />);
  expect(screen.getByText("Lead")).toBeTruthy();
  fireEvent.click(screen.getByText("Create agent"));
  expect(await screen.findByText("Specialist")).toBeTruthy();
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("shows a failed one-click creation instead of inventing a row", async () => {
  quick.create.mockRejectedValueOnce(new Error("no seat connected"));
  render(<SocietyView />);
  fireEvent.click(screen.getByText("Create agent"));
  expect((await screen.findByRole("alert")).textContent).toBe("no seat connected");
  expect(screen.getByText("Lead")).toBeTruthy();
});


it("navigates back through the window caption instead of a sections toggle", () => {
  render(<SocietyView />);
  expect(screen.queryByRole("button", { name: "society.world.toggle_sections" })).toBeNull();
  expect(screen.queryByRole("button", { name: "settings_hub.back_to_app" })).toBeNull();
  // The caption back button leaves this fullscreen section. The sidebar toggle is gone,
  // and nothing of this page rides in the caption.
  expect(screen.queryByTestId("mode-switch")).toBeNull();
  expect(screen.queryByRole("tab", { name: "society.shell.mode_verse" })).toBeNull();
});

it("shows no station shortcut in Agents mode", () => {
  window.history.replaceState(null, "", "?view=agents");
  render(<SocietyView />);
  expect(screen.queryByRole("button", { name: "society.mars.station_title" })).toBeNull();
});
