import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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

import SidebarAssistant, { nextRunLabel } from "./SidebarAssistant";

function chat(id: string, title: string, updatedMs: number) {
  return { kind: "agent" as const, id, title, preview: "", updatedMs, messageCount: 2, provider: "", raw: null };
}

function mount(routines: unknown[]) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ routines }), { status: 200 })));
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
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("nextRunLabel", () => {
  it("gives the time for today and adds the weekday for another day", () => {
    const now = new Date(2026, 10, 11, 9, 0);
    const today = nextRunLabel(new Date(2026, 10, 11, 15, 40).getTime(), now, "en-GB");
    const later = nextRunLabel(new Date(2026, 10, 13, 8, 0).getTime(), now, "en-GB");
    expect(today).toBe("15:40");
    expect(later).toBe("Fri 08:00");
  });
});

describe("SidebarAssistant", () => {
  it("leads back to the conversation and marks it while no earlier chat is open", () => {
    const onConversation = mount([]);
    const row = screen.getByTestId("sidebar-assistant-conversation");
    expect(row.getAttribute("aria-current")).toBe("page");
    fireEvent.click(row);
    expect(onConversation).toHaveBeenCalledTimes(1);
  });

  it("lists the assistant's routines without the scheduler's name tag and opens one", async () => {
    mount([
      { id: "r1", title: "[agent:Dodaios] Morning mail", state: "scheduled", due_at_ns: 0 },
      { id: "r2", title: "Weekly review", state: "paused", due_at_ns: 0 },
    ]);
    const first = await screen.findByTestId("sidebar-automation-r1");
    expect(first.textContent).toBe("Morning mail");
    expect(screen.getByTestId("sidebar-automation-r2").textContent).toContain("Paused");
    expect(vi.mocked(fetch)).toHaveBeenCalledWith("/api/society/agents/jarvis/routines");
    fireEvent.click(first);
    expect((await screen.findByTestId("routine-dialog")).textContent).toContain("r1");
    fireEvent.click(screen.getByText("Close routine"));
    expect(screen.queryByTestId("routine-dialog")).toBeNull();
  });

  it("says so when there is no routine yet", async () => {
    mount([]);
    await waitFor(() => expect(screen.getByTestId("sidebar-automations-empty").textContent).toMatch(/None yet/));
  });

  it("lists the newest chats, opens one, and hands the mark to it", () => {
    chats.rows = Array.from({ length: 8 }, (_, index) => chat(`c${index}`, `Chat ${index}`, 100 - index));
    chats.active = "c1";
    mount([]);
    expect(screen.getAllByTestId(/^sidebar-recent-c\d$/)).toHaveLength(6);
    expect(screen.getByTestId("sidebar-recent-c1").getAttribute("aria-current")).toBe("page");
    expect(screen.getByTestId("sidebar-assistant-conversation").getAttribute("aria-current")).toBeNull();
    fireEvent.click(screen.getByTestId("sidebar-recent-c3"));
    expect(chats.open).toHaveBeenCalledWith(chats.rows[3]);
    expect(screen.getByTestId("earlier-chats")).toBeTruthy();
  });

  it("folds a section and remembers it", () => {
    chats.rows = [chat("c0", "Chat 0", 1)];
    mount([]);
    fireEvent.click(screen.getByTestId("sidebar-assistant-recents-toggle"));
    expect(screen.queryByTestId("sidebar-recent-c0")).toBeNull();
    expect(JSON.parse(localStorage.getItem("jarvis.sidebar.assistantSections.v1") ?? "{}")).toEqual({ recents: false });
  });
});
