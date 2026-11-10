import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { chat } = vi.hoisted(() => ({ chat: { items: [] as unknown[] } }));

vi.mock("@/i18n", () => ({ useT: () => (key: string) => key }));
vi.mock("@/store/home", () => ({
  useHomeStore: (selector: (s: { agentChatId: string | null }) => unknown) => selector({ agentChatId: null }),
}));
vi.mock("@/store/agentChat", () => ({
  useAgentChatStore: (selector: (s: { timeline: { items: unknown[] } }) => unknown) => selector({ timeline: { items: chat.items } }),
}));
vi.mock("@/components/home/AssistantChat", () => ({ AssistantChat: () => <div data-testid="assistant-chat" /> }));
vi.mock("@/components/home/LeadActivityPanel", () => ({
  LeadActivityPanel: ({ onClose }: { onClose: () => void }) => (
    <aside data-testid="lead-activity"><button type="button" onClick={onClose}>close</button></aside>
  ),
}));

import { HomeView } from "@/views/HomeView";

const running = { type: "turn", id: "t", status: "running", blocks: [] };

beforeEach(() => {
  localStorage.clear();
  chat.items = [];
});
afterEach(cleanup);

describe("HomeView activity panel", () => {
  it("is closed on a quiet page with nothing to show", () => {
    render(<HomeView />);
    expect(screen.queryByTestId("lead-activity")).toBeNull();
    expect(screen.getByTestId("lead-activity-open")).toBeTruthy();
    expect(screen.queryByTestId("lead-activity-live")).toBeNull();
  });

  it("opens by itself while work runs", async () => {
    chat.items = [running];
    render(<HomeView />);
    expect(await screen.findByTestId("lead-activity")).toBeTruthy();
    expect(screen.queryByTestId("lead-activity-open")).toBeNull();
  });

  it("stays closed when the person closed it, with a live dot instead", async () => {
    chat.items = [running];
    render(<HomeView />);
    fireEvent.click(await screen.findByText("close"));
    expect(localStorage.getItem("dodaios.home.activity.v1")).toBe("closed");
    await waitFor(() => expect(screen.queryByTestId("lead-activity")).toBeNull());
    expect(screen.getByTestId("lead-activity-live")).toBeTruthy();
  });

  it("stays open on a quiet page when the person opened it", async () => {
    render(<HomeView />);
    fireEvent.click(screen.getByTestId("lead-activity-open"));
    expect(localStorage.getItem("dodaios.home.activity.v1")).toBe("open");
    expect(await screen.findByTestId("lead-activity")).toBeTruthy();
  });

  it("honours a choice remembered from an earlier visit", () => {
    localStorage.setItem("dodaios.home.activity.v1", "closed");
    chat.items = [running];
    render(<HomeView />);
    expect(screen.queryByTestId("lead-activity")).toBeNull();
  });

  it("fades in after mounting and leaves on the shorter exit", async () => {
    localStorage.setItem("dodaios.home.activity.v1", "open");
    render(<HomeView />);
    const close = await screen.findByText("close");
    vi.useFakeTimers();
    try {
      const frame = screen.getByTestId("lead-activity-frame");
      expect(frame.getAttribute("data-state")).toBe("open");
      expect(frame.className).toContain("duration-slow");
      fireEvent.click(close);
      expect(frame.getAttribute("data-state")).toBe("closed");
      expect(frame.className).toContain("duration-exit");
      // Still on the page while it leaves, gone after the exit.
      expect(screen.getByTestId("lead-activity-frame")).toBe(frame);
      act(() => { vi.advanceTimersByTime(200); });
      expect(screen.queryByTestId("lead-activity-frame")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});
