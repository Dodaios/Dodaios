/**
 * The assistant's suggestion of a standing task in the conversation: what it
 * says, its two buttons, and how it reads once it is settled, here or
 * anywhere else. And the quiet line for a task that paused itself.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { standingBackend, standingTask } from "@/lib/standingTasksApi.testkit";
import { useEventStore } from "@/store/events";
import { useStandingFocus } from "@/store/standingFocus";

import { AgentTimeline } from "./AgentTimeline";
import type { NoticeItem } from "./reduce";
import { StandingPausedNotice, StandingProposalCard, proposalStanding } from "./StandingProposalCard";

const notice = (kind: string, data: Record<string, unknown>, text = ""): NoticeItem => ({
  type: "notice", id: `n-${String(data.standing_id ?? kind)}`, kind, text, agentName: "", agentId: "", status: "", tsMs: 1, data, resolved: "",
});

const proposal = (more: Record<string, unknown> = {}) =>
  notice("standing_proposal", {
    kind: "standing_proposal", standing_id: "s-idea", title: "Domain renewals",
    goal: "Tell me two weeks before a domain runs out.", autonomy: "watch", limits: "", interval_min: 1440,
    reason: "You missed a renewal last month.", text: 'I could look after "Domain renewals" for you.', ...more,
  });

const suggested = (more = {}) => standingTask("s-idea", { title: "Domain renewals", state: "proposed", origin: "suggested", ...more });

function mount(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

const standing = () => screen.getByTestId("standing-proposal").getAttribute("data-standing");

beforeEach(() => {
  useEventStore.setState({ activeSection: "chats" });
  useStandingFocus.setState({ target: null });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("proposalStanding", () => {
  it("reads how a suggestion stands off the task", () => {
    expect(proposalStanding(undefined)).toBe("unknown");
    expect(proposalStanding({ state: "proposed", runs: 0, last_run_ms: null })).toBe("open");
    expect(proposalStanding({ state: "active", runs: 0, last_run_ms: null })).toBe("accepted");
    expect(proposalStanding({ state: "paused", runs: 4, last_run_ms: 5 })).toBe("accepted");
    // Ended without ever looking: it was turned down. Ended after looking: it ran and was ended.
    expect(proposalStanding({ state: "ended", runs: 0, last_run_ms: null })).toBe("declined");
    expect(proposalStanding({ state: "ended", runs: 3, last_run_ms: 5 })).toBe("ended");
  });
});

describe("StandingProposalCard", () => {
  it("says what is suggested, at which level and pace, and why", async () => {
    standingBackend([suggested()]);
    mount(<StandingProposalCard item={proposal()} />);

    await waitFor(() => expect(standing()).toBe("open"));
    expect(screen.getByText("Suggested standing task")).toBeTruthy();
    expect(screen.getByText("Domain renewals")).toBeTruthy();
    expect(screen.getByText("Tell me two weeks before a domain runs out.")).toBeTruthy();
    expect(screen.getByText("Only watches · looks daily")).toBeTruthy();
    expect(screen.getByTestId("standing-proposal-reason").textContent).toBe("Why: You missed a renewal last month.");
    expect(screen.queryByTestId("standing-proposal-limits")).toBeNull();
    expect(screen.getByTestId("standing-accept").textContent).toBe("Accept");
    expect(screen.getByTestId("standing-decline").textContent).toBe("Not now");
  });

  it("shows the limits it would act inside when it asks to act", async () => {
    standingBackend([suggested({ autonomy: "act" })]);
    mount(<StandingProposalCard item={proposal({ autonomy: "act", limits: "Renew within 7 days of expiry. Never buy a new one.", reason: "" })} />);

    await waitFor(() => expect(standing()).toBe("open"));
    expect(screen.getByText("Acts within your limits · looks daily")).toBeTruthy();
    expect(screen.getByTestId("standing-proposal-limits").textContent).toBe("Limits: Renew within 7 days of expiry. Never buy a new one.");
    expect(screen.queryByTestId("standing-proposal-reason")).toBeNull();
  });

  it("accepts through the task's route and then reads as accepted", async () => {
    const backend = standingBackend([suggested()]);
    mount(<StandingProposalCard item={proposal()} />);

    fireEvent.click(await screen.findByTestId("standing-accept"));
    await waitFor(() => expect(backend.writes()).toEqual(["POST /s-idea/accept"]));
    await waitFor(() => expect(screen.getByTestId("standing-settled").textContent).toBe("Accepted"));
    expect(screen.queryByTestId("standing-accept")).toBeNull();
    expect(screen.queryByTestId("standing-decline")).toBeNull();

    // The settled card leads to the task.
    fireEvent.click(screen.getByTestId("standing-open"));
    expect(useEventStore.getState().activeSection).toBe("agent-instructions");
    expect(useStandingFocus.getState().target).toEqual({ taskId: "s-idea" });
  });

  it("declines through the task's route and then reads as declined", async () => {
    const backend = standingBackend([suggested()]);
    mount(<StandingProposalCard item={proposal()} />);

    fireEvent.click(await screen.findByTestId("standing-decline"));
    await waitFor(() => expect(backend.writes()).toEqual(["POST /s-idea/decline"]));
    await waitFor(() => expect(screen.getByTestId("standing-settled").textContent).toBe("Declined"));
    expect(screen.queryByTestId("standing-accept")).toBeNull();
    expect(screen.queryByTestId("standing-open")).toBeNull();
  });

  it("keeps the buttons and names the reason when the answer is refused", async () => {
    standingBackend([suggested()], { refuse: { "POST /s-idea/accept": { status: 503, detail: "The scheduler is not running." } } });
    mount(<StandingProposalCard item={proposal()} />);

    fireEvent.click(await screen.findByTestId("standing-accept"));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toBe("The scheduler is not running."));
    await waitFor(() => expect(standing()).toBe("open"));
    expect(screen.getByTestId("standing-accept")).toBeTruthy();
  });

  it("renders settled when the task was accepted somewhere else", async () => {
    standingBackend([suggested({ state: "active" })]);
    mount(<StandingProposalCard item={proposal()} />);

    await waitFor(() => expect(standing()).toBe("accepted"));
    expect(screen.getByTestId("standing-settled").textContent).toBe("Accepted");
    expect(screen.queryByTestId("standing-accept")).toBeNull();
  });

  it("asks the task itself when the list no longer carries it", async () => {
    // Ended tasks are not in the list: one that never looked was declined.
    const backend = standingBackend([suggested({ state: "ended" })]);
    mount(<StandingProposalCard item={proposal()} />);

    await waitFor(() => expect(standing()).toBe("declined"));
    expect(backend.calls.map((call) => `${call.method} ${call.path}`)).toEqual(["GET ", "GET /s-idea"]);
    expect(screen.getByTestId("standing-settled").textContent).toBe("Declined");
    expect(screen.queryByTestId("standing-accept")).toBeNull();
  });

  it("reads as ended for a task that ran and was ended, or is gone", async () => {
    standingBackend([suggested({ state: "ended", runs: 5, last_run_ms: 10 })]);
    mount(<StandingProposalCard item={proposal()} />);
    await waitFor(() => expect(standing()).toBe("ended"));
    expect(screen.getByTestId("standing-settled").textContent).toBe("Ended");
    cleanup();

    standingBackend([]);
    mount(<StandingProposalCard item={proposal()} />);
    await waitFor(() => expect(standing()).toBe("ended"));
    expect(screen.queryByTestId("standing-accept")).toBeNull();
  });

  it("offers no buttons before it knows how the suggestion stands", () => {
    standingBackend([suggested()]);
    mount(<StandingProposalCard item={proposal()} />);
    // First paint, the list has not answered yet.
    expect(standing()).toBe("unknown");
    expect(screen.queryByTestId("standing-accept")).toBeNull();
    expect(screen.getByText("Domain renewals")).toBeTruthy();
  });

  it("renders nothing without a task to answer for", () => {
    standingBackend([]);
    const { container } = mount(<StandingProposalCard item={proposal({ standing_id: "" })} />);
    expect(container.textContent).toBe("");
  });
});

describe("StandingPausedNotice", () => {
  it("is one plain line with a way to the task", () => {
    render(<StandingPausedNotice item={notice("standing_paused", { standing_id: "s-shop", title: "Shop uptime" }, "server words")} />);
    const line = screen.getByTestId("standing-paused");
    expect(line.textContent).toMatch(/paused “Shop uptime” after several failed looks\.\s*Open$/);
    fireEvent.click(screen.getByTestId("standing-paused-open"));
    expect(useStandingFocus.getState().target).toEqual({ taskId: "s-shop" });
    expect(useEventStore.getState().activeSection).toBe("agent-instructions");
  });

  it("falls back to the server's sentence without a title", () => {
    render(<StandingPausedNotice item={notice("standing_paused", {}, "A standing task paused itself.")} />);
    expect(screen.getByTestId("standing-paused").textContent).toBe("A standing task paused itself.");
    expect(screen.queryByTestId("standing-paused-open")).toBeNull();
  });
});

describe("in the conversation", () => {
  const timeline = (items: NoticeItem[]) => (
    <AgentTimeline items={items} assistantName="Nova" providerLabel={(id) => id} onDecide={vi.fn()} bubbles />
  );

  it("draws the suggestion as a card and the pause as a line", async () => {
    standingBackend([suggested()]);
    mount(timeline([proposal(), notice("standing_paused", { standing_id: "s-shop", title: "Shop uptime" })]));

    expect(await screen.findByTestId("standing-accept")).toBeTruthy();
    expect(screen.getByTestId("standing-paused")).toBeTruthy();
  });

  it("labels a look's result with its standing task", () => {
    const result: NoticeItem = {
      ...notice("society_result", { source: "routine", standing_id: "s-meta", standing_title: "Meta ads campaign" }, "CPA rose to 18.40 EUR."),
      status: "done", agentName: "Nova",
    };
    render(timeline([result]));
    expect(screen.getByText("Standing task: Meta ads campaign")).toBeTruthy();
    expect(screen.getByText("CPA rose to 18.40 EUR.")).toBeTruthy();
    expect(screen.queryByText("Nova is done")).toBeNull();
  });
});
