/**
 * "Looks after" in the assistant's panel: the running standing tasks with
 * what their last look found or when the next one comes, the suggestions
 * with their two answers, and the way to the whole list.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { standingBackend, standingTask } from "@/lib/standingTasksApi.testkit";
import { useEventStore } from "@/store/events";
import { useStandingFocus } from "@/store/standingFocus";

import { PanelStanding, STANDING_SHOWN } from "./PanelStanding";

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(<QueryClientProvider client={client}><PanelStanding /></QueryClientProvider>);
}

const HOUR = 3_600_000;

beforeEach(() => {
  useEventStore.setState({ activeSection: "chats", toasts: [] });
  useStandingFocus.setState({ target: null });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("PanelStanding", () => {
  it("shows running tasks with their last finding or their next look", async () => {
    standingBackend([
      standingTask("s-meta", { title: "Meta ads campaign", last_run_ms: Date.now() - HOUR, next_run_ms: Date.now() + HOUR,
        last_outcome: "reported", last_summary: "CPA rose to 18.40 EUR." }),
      standingTask("s-inbox", { title: "Supplier invoices", last_run_ms: Date.now() - HOUR, last_outcome: "asked", last_summary: "Which order?" }),
      standingTask("s-water", { title: "Water reports", last_run_ms: Date.now() - HOUR, next_run_ms: Date.now() + 2 * HOUR, last_outcome: "quiet" }),
      standingTask("s-paused", { title: "Shop uptime", state: "paused" }),
    ]);
    mount();

    const block = await screen.findByTestId("assistant-panel-standing");
    expect(within(block).getByRole("heading").textContent).toBe("Looks after");
    expect(within(block).getByTestId("assistant-standing-task-s-meta").textContent).toBe("Meta ads campaignTold you: CPA rose to 18.40 EUR.");
    // A look that waits for the person is marked as one.
    const asked = within(block).getByTestId("assistant-standing-task-s-inbox");
    expect(asked.textContent).toBe("Supplier invoicesNeeds you: Which order?");
    expect(asked.querySelector("svg")?.getAttribute("class")).toContain("text-warning");
    // A quiet one says when it looks again.
    expect(within(block).getByTestId("assistant-standing-task-s-water").textContent).toMatch(/^Water reportsNext look: /);
    // A paused task is not work in progress.
    expect(within(block).queryByText("Shop uptime")).toBeNull();
    expect(within(block).getByTestId("assistant-standing-all").textContent).toBe("All standing tasks");
  });

  it("keeps the block short", async () => {
    standingBackend(Array.from({ length: STANDING_SHOWN + 2 }, (_, i) => standingTask(`s-${i}`)));
    mount();

    await screen.findByTestId("assistant-panel-standing");
    expect(screen.getAllByTestId(/^assistant-standing-task-/)).toHaveLength(STANDING_SHOWN);
  });

  it("accepts a suggestion right in the panel", async () => {
    const backend = standingBackend([
      standingTask("s-idea", { title: "Domain renewals", state: "proposed", origin: "suggested" }),
    ]);
    mount();

    const row = await screen.findByTestId("assistant-standing-proposal-s-idea");
    expect(within(row).getByText("Suggested")).toBeTruthy();
    fireEvent.click(within(row).getByTestId("assistant-standing-proposal-accept-s-idea"));
    await waitFor(() => expect(backend.writes()).toEqual(["POST /s-idea/accept"]));
    // It is a running task now, with no answer left to give.
    expect(await screen.findByTestId("assistant-standing-task-s-idea")).toBeTruthy();
    expect(screen.queryByTestId("assistant-standing-proposal-s-idea")).toBeNull();
  });

  it("turns a suggestion down, and says why when that is refused", async () => {
    const backend = standingBackend([
      standingTask("s-idea", { title: "Domain renewals", state: "proposed", origin: "suggested" }),
      standingTask("s-other", { title: "Other idea", state: "proposed", origin: "suggested" }),
    ], { refuse: { "POST /s-other/decline": { status: 409, detail: "It is not a proposal any more." } } });
    mount();

    fireEvent.click(await screen.findByTestId("assistant-standing-proposal-decline-s-idea"));
    await waitFor(() => expect(backend.writes()).toEqual(["POST /s-idea/decline"]));
    await waitFor(() => expect(screen.queryByTestId("assistant-standing-proposal-s-idea")).toBeNull());

    await waitFor(() => expect((screen.getByTestId("assistant-standing-proposal-decline-s-other") as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByTestId("assistant-standing-proposal-decline-s-other"));
    await waitFor(() => expect(useEventStore.getState().toasts.map((toast) => toast.message)).toContain("It is not a proposal any more."));
    expect(await screen.findByTestId("assistant-standing-proposal-s-other")).toBeTruthy();
  });

  it("opens a task, or the whole list, on the assistant's page", async () => {
    standingBackend([standingTask("s-meta", { title: "Meta ads campaign" })]);
    mount();

    fireEvent.click(await screen.findByTestId("assistant-standing-task-s-meta"));
    expect(useEventStore.getState().activeSection).toBe("agent-instructions");
    expect(useStandingFocus.getState().target).toEqual({ taskId: "s-meta" });

    fireEvent.click(screen.getByTestId("assistant-standing-all"));
    expect(useStandingFocus.getState().target).toEqual({ taskId: "" });
  });

  it("says how to start one while there is none", async () => {
    standingBackend([]);
    mount();

    expect((await screen.findByTestId("assistant-standing-panel-empty")).textContent).toBe("Nothing yet. Say “Look after …” in the chat.");
    expect(screen.getByTestId("assistant-standing-all")).toBeTruthy();
  });

  it("draws nothing when standing tasks are not offered or cannot be read", async () => {
    standingBackend([standingTask("s-meta")], { overview: { available: false } });
    const first = mount();
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(first.container.textContent).toBe("");
    cleanup();

    const backend = standingBackend([], { listStatus: 404 });
    const second = mount();
    await waitFor(() => expect(backend.calls.length).toBeGreaterThan(0));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(second.container.textContent).toBe("");
  });
});
