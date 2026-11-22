import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SocietyView } from "./SocietyView";

const quick = vi.hoisted(() => ({ create: vi.fn(async () => ({ agentId: "lead" })) }));
vi.mock("@/i18n", () => ({ useT: () => (key: string) => key, useLocaleChunk: () => true }));
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
afterEach(cleanup);

it("creates agents without a dialog and keeps the open draft", async () => {
  const client = new QueryClient();
  render(<QueryClientProvider client={client}><SocietyView /></QueryClientProvider>);
  const draft = screen.getByLabelText("Existing chat draft");
  fireEvent.change(draft, { target: { value: "Keep this draft" } });

  fireEvent.click(screen.getByRole("button", { name: "Create agent" }));
  await waitFor(() => expect(quick.create).toHaveBeenCalledTimes(1));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(screen.getByLabelText("Existing chat draft")).toBe(draft);
  expect((draft as HTMLInputElement).value).toBe("Keep this draft");

  // The Verse has no entry on this page any more.
  expect(screen.queryByTestId("society-world-surface")).toBeNull();
  client.clear();
});
