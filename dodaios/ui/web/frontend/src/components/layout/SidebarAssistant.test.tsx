import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useEventStore } from "@/store/events";
import { useSettingsJump } from "@/store/settingsJump";

const chats = vi.hoisted(() => ({
  rows: [] as { kind: "voice" | "agent"; id: string; title: string; preview: string; updatedMs: number; messageCount: number; provider: string; raw: null }[],
  active: "",
  open: vi.fn(),
}));
vi.mock("@/components/home/chatRows", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/home/chatRows")>()),
  useChatRows: () => ({ rows: chats.rows, isActive: (row: { id: string }) => row.id === chats.active, open: chats.open, remove: vi.fn() }),
}));
vi.mock("@/components/layout/SidebarRoutineDialog", () => ({
  default: ({ routineId, onClose }: { routineId: string; onClose: () => void }) => (
    <div data-testid="routine-dialog">{routineId}<button onClick={onClose}>Close routine</button></div>
  ),
}));
vi.mock("@/components/layout/SidebarFileDialog", () => ({
  default: ({ fileId }: { fileId: string }) => <div data-testid="file-dialog">{fileId}</div>,
}));
vi.mock("@/components/pets/PetMark", () => ({ PetMark: () => <span data-testid="pet-mark" /> }));
vi.mock("@/hooks/useVoiceEngineDisplay", () => ({
  useVoiceEngineDisplay: () => ({ tier: "realtime", providerId: "test", providerLabel: "Test Voice", model: "m1" }),
}));
vi.mock("@/views/assistant/api", () => ({
  useSoulProfile: () => ({ isLoading: false, data: { name: "Nova", wake_phrase: "Hey Nova", learning: true, files: [
    { id: "soul", filename: "SOUL.md" }, { id: "instructions", filename: "Nova.md" },
    { id: "memory", filename: "MEMORY.md" }, { id: "user", filename: "USER.md" },
  ] } }),
}));
const skills = vi.hoisted(() => ({ list: [] as { name: string; state: string }[], set: vi.fn() }));
vi.mock("@/hooks/useSkills", () => ({
  useSkillsList: () => ({ isLoading: false, data: { skills: skills.list } }),
  useSetSkillEnabled: () => ({ isPending: false, mutate: skills.set }),
}));
const tasks = vi.hoisted(() => ({ setTaskEnabled: vi.fn(async () => undefined) }));
vi.mock("@/lib/tasksApi", () => ({ setTaskEnabled: tasks.setTaskEnabled }));

import SidebarAssistant from "./SidebarAssistant";

function chat(id: string, title: string, updatedMs: number) {
  return { kind: "agent" as const, id, title, preview: "", updatedMs, messageCount: 2, provider: "", raw: null };
}

function mount(routines: unknown[]) {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => new Response(
    JSON.stringify(String(url) === "/api/agent-chat/lead" ? { session_id: "lead" } : { routines }), { status: 200 },
  )));
  const onConversation = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><SidebarAssistant onConversation={onConversation} /></QueryClientProvider>);
  return onConversation;
}

beforeEach(() => {
  localStorage.clear();
  chats.rows = [];
  chats.active = "";
  chats.open.mockReset();
  skills.list = [];
  skills.set.mockReset();
  tasks.setTaskEnabled.mockClear();
  useEventStore.setState({ activeSection: "chats" });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("SidebarAssistant", () => {
  it("shows the assistant's face and name, and they lead back to the conversation", () => {
    const onConversation = mount([]);
    const face = screen.getByTestId("sidebar-assistant-conversation");
    expect(face.textContent).toContain("Dodaios");
    expect(face.querySelector('[data-testid="pet-mark"]')).toBeTruthy();
    fireEvent.click(face);
    expect(onConversation).toHaveBeenCalledTimes(1);
  });

  it("lists the routines with a switch each, without the scheduler's name tag", async () => {
    mount([
      { id: "r1", title: "[agent:Dodaios] Morning mail", state: "scheduled" },
      { id: "r2", title: "Weekly review", state: "paused" },
    ]);
    const first = await screen.findByTestId("sidebar-automation-r1");
    expect(first.textContent).toContain("Morning mail");
    expect(first.textContent).not.toContain("[agent:");
    expect(vi.mocked(fetch)).toHaveBeenCalledWith("/api/society/agents/jarvis/routines");
    expect(screen.getByTestId("sidebar-automation-switch-r1").getAttribute("aria-checked")).toBe("true");
    const paused = screen.getByTestId("sidebar-automation-switch-r2");
    expect(paused.getAttribute("aria-checked")).toBe("false");
    fireEvent.click(paused);
    await waitFor(() => expect(tasks.setTaskEnabled).toHaveBeenCalledWith("r2", true));
  });

  it("opens a routine's own page from its row", async () => {
    mount([{ id: "r1", title: "Morning mail", state: "scheduled" }]);
    fireEvent.click(await screen.findByTestId("sidebar-automation-r1"));
    expect((await screen.findByTestId("routine-dialog")).textContent).toContain("r1");
    fireEvent.click(screen.getByText("Close routine"));
    expect(screen.queryByTestId("routine-dialog")).toBeNull();
  });

  it("says so when there is no routine yet", async () => {
    mount([]);
    await waitFor(() => expect(screen.getByTestId("sidebar-automations-empty").textContent).toMatch(/None yet/));
  });

  it("names the voice model and the wake word, and each leads to its settings", () => {
    mount([]);
    expect(screen.getByTestId("sidebar-voice-model").textContent).toContain("Test Voice");
    const wake = screen.getByTestId("sidebar-voice-wake");
    expect(wake.textContent).toContain("Hey Nova");
    fireEvent.click(wake);
    expect(useSettingsJump.getState().take()).toBe("wake-word");
    expect(useEventStore.getState().activeSection).toBe("settings");
  });

  it("lists the newest earlier chats without the conversation itself", async () => {
    chats.rows = [chat("lead", "The one conversation", 9), ...Array.from({ length: 6 }, (_, index) => chat(`c${index}`, `Chat ${index}`, 8 - index))];
    mount([]);
    await waitFor(() => expect(screen.queryByTestId("sidebar-recent-lead")).toBeNull());
    expect(screen.getAllByTestId(/^sidebar-recent-c\d$/)).toHaveLength(4);
    fireEvent.click(screen.getByTestId("sidebar-recent-c2"));
    expect(chats.open).toHaveBeenCalledWith(chats.rows[3]);
    expect(screen.getByTestId("earlier-chats")).toBeTruthy();
  });

  it("keeps the files and the skills in the library, and remembers the tab", async () => {
    skills.list = [{ name: "zeta", state: "disabled" }, { name: "alpha", state: "active" }, { name: "draft-one", state: "draft" }];
    mount([]);
    expect(screen.queryByTestId("sidebar-file-user")).toBeNull();
    fireEvent.click(screen.getByTestId("sidebar-assistant-tab-library"));
    expect(localStorage.getItem("jarvis.sidebar.assistantTab.v1")).toBe("library");
    expect(["soul", "instructions", "memory", "user"].map((id) => screen.getByTestId(`sidebar-file-${id}`).textContent))
      .toEqual(["SOUL.md", "Nova.md", "MEMORY.md", "USER.md"]);
    fireEvent.click(screen.getByTestId("sidebar-file-user"));
    expect((await screen.findByTestId("file-dialog")).textContent).toBe("user");
    // Active skills lead; a draft has no switch to flip.
    const switches = screen.getAllByTestId(/^sidebar-skill-switch-/).map((node) => node.getAttribute("data-testid"));
    expect(switches).toEqual(["sidebar-skill-switch-alpha", "sidebar-skill-switch-zeta"]);
    fireEvent.click(screen.getByTestId("sidebar-skill-switch-zeta"));
    expect(skills.set).toHaveBeenCalledWith({ name: "zeta", enabled: true });
    fireEvent.click(screen.getByTestId("sidebar-skills-all"));
    expect(useEventStore.getState().activeSection).toBe("skills");
  });
});
