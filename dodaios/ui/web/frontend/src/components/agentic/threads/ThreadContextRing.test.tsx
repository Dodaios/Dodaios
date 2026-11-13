import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ThreadContextRing } from "./ThreadContextRing";

const breakdown = {
  model: "claude-opus-5-5", used: 139_400, window: 1_000_000,
  categories: [
    { key: "system_prompt", label: "System prompt", tokens: 2_800 },
    { key: "deferred_tools", label: "System tools (deferred)", tokens: 14_700 },
    { key: "messages", label: "Messages", tokens: 122_700 },
    { key: "free", label: "Free space", tokens: 827_600 },
    { key: "autocompact", label: "Autocompact buffer", tokens: 33_000 },
    { key: "other", label: "Plugins", tokens: 1_000 },
  ],
};

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockImplementation(async (url: string) => ({
    ok: true,
    json: async () => url.includes("detail=true")
      ? { supported: true, reading: null, breakdown }
      : { supported: true, reading: { used: 120_000, window: 1_000_000, model: "claude-opus-5-5" }, breakdown: null },
  }));
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); fetchMock.mockReset(); });

describe("ThreadContextRing", () => {
  it("draws nothing for a draft or while the window size is unknown", () => {
    const { container } = render(<ThreadContextRing sessionId="" live={undefined} running={false} className="" />);
    expect(container.innerHTML).toBe("");
    render(<ThreadContextRing sessionId="s1" live={{ used: 10, window: null, model: "m" }} running className="" />);
    expect(screen.queryByTestId("thread-context-ring")).toBeNull();
  });

  it("fills with the live reading, without asking the backend", () => {
    render(<ThreadContextRing sessionId="s1" live={{ used: 250_000, window: 1_000_000, model: "m" }} running={false} className="" />);
    const ring = screen.getByTestId("thread-context-ring");
    expect(ring.getAttribute("data-percent")).toBe("25");
    expect(ring.getAttribute("aria-label")).toContain("25 %");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("reads an older thread's last answer from the backend", async () => {
    render(<ThreadContextRing sessionId="s1" live={undefined} running={false} className="" />);
    await waitFor(() => expect(screen.getByTestId("thread-context-ring").getAttribute("data-percent")).toBe("12"));
    expect(fetchMock.mock.calls[0][0]).toBe("/api/agent-chat/sessions/s1/context");
  });

  it("shows what fills the window when pointed at, leaving out tools that are not loaded", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(<ThreadContextRing sessionId="s1" live={{ used: 139_400, window: 1_000_000, model: "claude-opus-5-5" }} running={false} className="" />);
    fireEvent.pointerEnter(screen.getByTestId("thread-context-ring"));
    await act(async () => { vi.advanceTimersByTime(200); });
    const parts = await screen.findByTestId("thread-context-parts");
    expect(fetchMock.mock.calls.at(-1)?.[0]).toBe("/api/agent-chat/sessions/s1/context?detail=true");
    const rows = Array.from(parts.querySelectorAll("li")).map((row) => row.textContent ?? "");
    expect(rows.map((row) => row.split(/\d/)[0])).toEqual(["System prompt", "Plugins", "Conversation", "Reserve for summarizing", "Free"]);
    expect(rows.join(" ")).not.toContain("deferred");
    expect(screen.getByTestId("thread-context-details").textContent).toContain("At about 97 %");
  });

  it("stays open after a click and closes on a second one", async () => {
    render(<ThreadContextRing sessionId="s1" live={{ used: 139_400, window: 1_000_000, model: "claude-opus-5-5" }} running className="" />);
    const ring = screen.getByTestId("thread-context-ring");
    fireEvent.click(ring);
    expect(await screen.findByTestId("thread-context-details")).toBeTruthy();
    // While the agent works, the breakdown waits for the turn's end.
    expect(fetchMock).not.toHaveBeenCalled();
    fireEvent.pointerLeave(ring);
    expect(screen.getByTestId("thread-context-details")).toBeTruthy();
    fireEvent.click(ring);
    await waitFor(() => expect(screen.queryByTestId("thread-context-details")).toBeNull());
  });
});
