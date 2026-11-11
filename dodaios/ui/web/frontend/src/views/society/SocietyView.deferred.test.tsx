import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SocietyView } from "./SocietyView";

const loaded = vi.hoisted(() => ({ building: 0, world: 0 }));
const quick = vi.hoisted(() => ({ create: vi.fn(async () => ({ agentId: "lead" })) }));
vi.mock("@/i18n", () => ({ useT: () => (key: string) => key, useLocaleChunk: () => true }));
vi.mock("@/lib/mapFullscreen", () => ({ setMapFullscreen: async () => undefined }));
vi.mock("@/components/society/chat/useModelMenuData", () => ({ useModelMenuData: () => undefined }));
vi.mock("@/lib/societyChatGroups", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/societyChatGroups")>()), useSocietyChatGroups: () => ({ data: [], isSuccess: true, isError: false, failureCount: 0 }) }));
vi.mock("@/components/society/chat/ChatGroupPanel", () => ({ ChatGroupPanel: () => null }));
vi.mock("@/components/society/chat/AgentChatPanel", () => ({ useSocietyChatStore: { getState: () => ({ disconnect: () => undefined }) } }));
vi.mock("@/components/society/data", () => ({ useQuickCreateAgent: () => quick.create,
  useSocietyRoster: () => ({ data: { sample: false,
  agents: [{ agentId: "lead", name: "Lead", tier: "lead", state: "idle" }] }, isLoading: false }) }));
vi.mock("@/components/society/roster/RosterRail", () => ({ RosterRail: () => null }));
vi.mock("@/components/society/roster/useRosterActivity", () => ({ useRosterActivity: () => new Map() }));
vi.mock("@/components/society/card/AgentCardOverlay", () => ({ AgentCardOverlay: ({ onCreate }: { onCreate: () => void }) => (
  <><input aria-label="Existing chat draft" /><button onClick={onCreate}>Create agent</button></>
) }));
vi.mock("@/components/society/card/BuildingCardOverlay", () => {
  // Counts MODULE evaluation, not component mounts. An eager import fails
  // before this test's first render, even when a closed dialog renders null.
  loaded.building += 1;
  return { BuildingCardOverlay: ({ place, onClose }: { place: string; onClose: () => void }) =>
    <section role="dialog" aria-label="Building"><span>{place}</span><button onClick={onClose}>Close building</button></section> };
});
afterEach(cleanup);

it("never evaluates the Verse or dialog modules; creates agents without a dialog", async () => {
  const client = new QueryClient();
  render(<QueryClientProvider client={client}><SocietyView /></QueryClientProvider>);
  expect(loaded).toEqual({ building: 0, world: 0 });
  const draft = screen.getByLabelText("Existing chat draft");
  fireEvent.change(draft, { target: { value: "Keep this draft" } });

  fireEvent.click(screen.getByRole("button", { name: "Create agent" }));
  await waitFor(() => expect(quick.create).toHaveBeenCalledTimes(1));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(screen.getByLabelText("Existing chat draft")).toBe(draft);
  expect((draft as HTMLInputElement).value).toBe("Keep this draft");

  // The Verse has no entry on this page any more: its chunk stays unloaded.
  expect(loaded).toEqual({ building: 0, world: 0 });
  expect(screen.queryByTestId("society-world-surface")).toBeNull();
  client.clear();
});
