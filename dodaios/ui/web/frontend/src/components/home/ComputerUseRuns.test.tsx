import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ComputerUseRuns } from "./ComputerUseRuns";

type Run = {
  mission_id: string;
  goal: string;
  source: string;
  status: "queued" | "running" | "finished" | "error" | "cancelled" | "timeout";
  started_at: number;
  result_text: string;
};

function run(overrides: Partial<Run> = {}): Run {
  return {
    mission_id: "mission-1",
    goal: "Open the calculator",
    source: "voice",
    status: "running",
    started_at: 1,
    result_text: "",
    ...overrides,
  };
}

describe("ComputerUseRuns", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("shows recent runs and keeps polling from creating a render loop", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({
      runs: [
        run(),
        run({ mission_id: "mission-done", goal: "Saved the document", status: "finished", result_text: "Saved successfully." }),
      ],
      active: 1,
      total: 2,
    })));
    vi.stubGlobal("fetch", fetchMock);

    render(<ComputerUseRuns />);

    expect(await screen.findByText("Open the calculator")).toBeTruthy();
    expect(screen.getByText("1")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Stop this run" })).toBeTruthy();
    expect(screen.getByText("Saved successfully.")).toBeTruthy();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  });

  it("cancels only the selected active run and refreshes its status", async () => {
    let current = run();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/computer-use/goals?limit=8") {
        return new Response(JSON.stringify({ runs: [current], active: current.status === "running" ? 1 : 0, total: 1 }));
      }
      if (url === "/api/computer-use/goals/mission-1/cancel" && init?.method === "POST") {
        current = { ...current, status: "cancelled" };
        return new Response(JSON.stringify({ mission_id: current.mission_id, cancel_requested: true }));
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ComputerUseRuns />);
    fireEvent.click(await screen.findByRole("button", { name: "Stop this run" }));

    await screen.findByText("Cancelled");
    expect(screen.queryByRole("button", { name: "Stop this run" })).toBeNull();
    expect(fetchMock).toHaveBeenCalledWith("/api/computer-use/goals/mission-1/cancel", { method: "POST" });
  });
});
