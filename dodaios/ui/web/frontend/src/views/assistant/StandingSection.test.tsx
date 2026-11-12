/**
 * The standing tasks on the assistant's page: the list and its order, a
 * suggestion accepted or turned down, the form's rule that acting needs
 * limits, the empty and the unavailable state, and a task's own page with
 * its controls.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { standingBackend, standingRun, standingTask } from "@/lib/standingTasksApi.testkit";
import { useEventStore } from "@/store/events";
import { StandingSection } from "@/views/assistant/StandingSection";
import { StandingTaskPage } from "@/views/assistant/StandingTaskPage";

function mount(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

const HOUR = 3_600_000;
const tasks = () => [
  standingTask("s-paused", { title: "Shop uptime", state: "paused", autonomy: "watch", interval_min: 15, updated_ms: 9_000 }),
  standingTask("s-meta", {
    title: "Meta ads campaign", goal: "Keep cost per purchase under 20 EUR.", updated_ms: 5_000,
    last_run_ms: Date.now() - 2 * HOUR, next_run_ms: Date.now() + HOUR, last_outcome: "asked",
    last_summary: "Which order does invoice 1187 belong to?", runs: 3,
  }),
  standingTask("s-gone", { title: "Old one", state: "ended" }),
  standingTask("s-idea", {
    title: "Domain renewals", state: "proposed", origin: "suggested", autonomy: "watch", interval_min: 1440,
    reason: "You missed a renewal last month.", updated_ms: 1_000,
  }),
];

const toasts = () => useEventStore.getState().toasts.map((toast) => toast.message);

beforeEach(() => {
  useEventStore.setState({ toasts: [] });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("StandingSection", () => {
  it("lists what was suggested first, then what runs, then what is paused", async () => {
    standingBackend(tasks());
    mount(<StandingSection onOpen={vi.fn()} />);

    const list = await screen.findByTestId("assistant-standing-list");
    const rows = within(list).getAllByRole("listitem");
    expect(rows.map((row) => row.getAttribute("data-state"))).toEqual(["proposed", "active", "paused"]);
    expect(within(list).queryByText("Old one")).toBeNull();

    // A suggestion says why and carries the two answers.
    expect(within(rows[0]).getByText("Why: You missed a renewal last month.")).toBeTruthy();
    expect(within(rows[0]).getByText("Only watches · looks daily")).toBeTruthy();
    expect(within(rows[0]).getByTestId("assistant-standing-accept-s-idea").textContent).toBe("Accept");
    expect(within(rows[0]).getByTestId("assistant-standing-decline-s-idea").textContent).toBe("Not now");

    // A running task says its goal, level and pace, what the last look found and when the next comes.
    expect(within(rows[1]).getByText("Keep cost per purchase under 20 EUR.")).toBeTruthy();
    expect(within(rows[1]).getByText("Prepares the next step · looks every 3 hours")).toBeTruthy();
    const last = within(rows[1]).getByTestId("assistant-standing-last-s-meta");
    expect(last.textContent).toMatch(/^Last look: .+ · Needs you: Which order does invoice 1187 belong to\?$/);
    expect(last.querySelector('[data-outcome="asked"]')?.className).toContain("text-warning");
    expect(within(rows[1]).getByText(/^Next look: /)).toBeTruthy();
    expect(within(rows[1]).queryByText("Accept")).toBeNull();

    // A paused one says so, and that it has not looked yet.
    expect(within(rows[2]).getByText("Paused")).toBeTruthy();
    expect(within(rows[2]).getByText("Has not looked yet")).toBeTruthy();
  });

  it("accepts a suggestion: it becomes a running task", async () => {
    const backend = standingBackend(tasks());
    mount(<StandingSection onOpen={vi.fn()} />);

    fireEvent.click(await screen.findByTestId("assistant-standing-accept-s-idea"));
    await waitFor(() => expect(backend.writes()).toEqual(["POST /s-idea/accept"]));
    await waitFor(() => expect(screen.getByTestId("assistant-standing-s-idea").getAttribute("data-state")).toBe("active"));
    expect(screen.queryByTestId("assistant-standing-accept-s-idea")).toBeNull();
  });

  it("turns a suggestion down: it leaves the list", async () => {
    const backend = standingBackend(tasks());
    mount(<StandingSection onOpen={vi.fn()} />);

    fireEvent.click(await screen.findByTestId("assistant-standing-decline-s-idea"));
    await waitFor(() => expect(backend.writes()).toEqual(["POST /s-idea/decline"]));
    await waitFor(() => expect(screen.queryByTestId("assistant-standing-s-idea")).toBeNull());
    expect(screen.getByTestId("assistant-standing-s-meta")).toBeTruthy();
  });

  it("puts a refused accept back and says why", async () => {
    standingBackend(tasks(), { refuse: { "POST /s-idea/accept": { status: 409, detail: "There are already 12 standing tasks." } } });
    mount(<StandingSection onOpen={vi.fn()} />);

    fireEvent.click(await screen.findByTestId("assistant-standing-accept-s-idea"));
    await waitFor(() => expect(toasts()).toContain("There are already 12 standing tasks."));
    await waitFor(() => expect(screen.getByTestId("assistant-standing-s-idea").getAttribute("data-state")).toBe("proposed"));
  });

  it("opens a task from its row", async () => {
    standingBackend(tasks());
    const onOpen = vi.fn();
    mount(<StandingSection onOpen={onOpen} />);

    fireEvent.click(await screen.findByTestId("assistant-standing-open-s-meta"));
    expect(onOpen).toHaveBeenCalledWith("s-meta");
  });

  it("adds a task by hand, and asks for limits before it may act", async () => {
    const backend = standingBackend([]);
    mount(<StandingSection onOpen={vi.fn()} />);

    fireEvent.click(await screen.findByTestId("assistant-standing-add"));
    const submit = screen.getByTestId("assistant-standing-form-submit") as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    // The level starts at "prepare" and no limits are asked for.
    expect(screen.getByTestId("assistant-standing-form-level-prepare").getAttribute("aria-checked")).toBe("true");
    expect(screen.queryByTestId("assistant-standing-form-limits")).toBeNull();

    fireEvent.change(screen.getByTestId("assistant-standing-form-title"), { target: { value: " Meta ads " } });
    fireEvent.change(screen.getByTestId("assistant-standing-form-goal"), { target: { value: "Keep CPA under 20 EUR." } });
    expect(submit.disabled).toBe(false);

    // Acting needs limits in the person's words.
    fireEvent.click(screen.getByTestId("assistant-standing-form-level-act"));
    expect(submit.disabled).toBe(true);
    expect(screen.getByTestId("assistant-standing-form-limits-hint").textContent).toMatch(/^Acting needs limits/);
    fireEvent.change(screen.getByTestId("assistant-standing-form-limits"), { target: { value: "Pause single ads only." } });
    expect(submit.disabled).toBe(false);

    fireEvent.click(submit);
    await waitFor(() => expect(backend.writes()).toEqual(["POST "]));
    const body = backend.bodyOf("POST ");
    expect(body).toMatchObject({ title: "Meta ads", goal: "Keep CPA under 20 EUR.", autonomy: "act", limits: "Pause single ads only.", interval_min: 180 });
    expect(typeof body?.timezone).toBe("string");
    // The form closes and the new task is in the list.
    await waitFor(() => expect(screen.queryByTestId("assistant-standing-form")).toBeNull());
    expect(await screen.findByTestId("assistant-standing-s-new")).toBeTruthy();
    expect(toasts()).toContain("Standing task added");
  });

  it("keeps the form open and shows the server's reason when adding is refused", async () => {
    standingBackend([], { refuse: { "POST ": { status: 409, detail: "There are already 12 standing tasks. End one before adding another." } } });
    mount(<StandingSection onOpen={vi.fn()} />);

    fireEvent.click(await screen.findByTestId("assistant-standing-add"));
    fireEvent.change(screen.getByTestId("assistant-standing-form-title"), { target: { value: "One more" } });
    fireEvent.change(screen.getByTestId("assistant-standing-form-goal"), { target: { value: "Anything." } });
    fireEvent.click(screen.getByTestId("assistant-standing-form-submit"));

    expect((await screen.findByRole("alert")).textContent).toBe("There are already 12 standing tasks. End one before adding another.");
    expect(screen.getByTestId("assistant-standing-form")).toBeTruthy();
  });

  it("shows an example to start from and the chat hint while there is nothing", async () => {
    standingBackend([]);
    mount(<StandingSection onOpen={vi.fn()} />);

    const empty = await screen.findByTestId("assistant-standing-empty");
    expect(within(empty).getByText(/^Nothing yet\./)).toBeTruthy();
    expect(within(empty).getByText("Or simply say it: “Look after …”")).toBeTruthy();

    fireEvent.click(within(empty).getByTestId("assistant-standing-example"));
    expect((screen.getByTestId("assistant-standing-form-title") as HTMLInputElement).value).toBe("Meta ads campaign");
    expect((screen.getByTestId("assistant-standing-form-goal") as HTMLTextAreaElement).value).toMatch(/^Keep cost per purchase under 20 EUR/);
    expect(screen.queryByTestId("assistant-standing-empty")).toBeNull();
  });

  it("says plainly when standing tasks are not available", async () => {
    standingBackend([], { overview: { available: false } });
    mount(<StandingSection onOpen={vi.fn()} />);

    expect((await screen.findByTestId("assistant-standing-unavailable")).textContent).toMatch(/^Standing tasks are not available right now\./);
    expect(screen.queryByTestId("assistant-standing-add")).toBeNull();
    expect(screen.queryByTestId("assistant-standing-empty")).toBeNull();
  });

  it("says what failed when the list cannot be loaded", async () => {
    standingBackend([], { listStatus: 500 });
    mount(<StandingSection onOpen={vi.fn()} />);

    const error = await screen.findByTestId("assistant-standing-error");
    expect(within(error).getByText("Standing tasks could not be loaded")).toBeTruthy();
    expect(within(error).getByText("The list is not there.")).toBeTruthy();
    expect(screen.queryByTestId("assistant-standing-add")).toBeNull();
  });
});

describe("StandingTaskPage", () => {
  const meta = () =>
    standingTask("s-meta", {
      title: "Meta ads campaign", goal: "Keep cost per purchase under 20 EUR.", how: "Check Ads Manager.",
      notes: "Baseline CPA 14.90 EUR.", last_run_ms: Date.now() - 2 * HOUR, next_run_ms: Date.now() + HOUR,
      last_outcome: "reported", last_summary: "CPA rose to 18.40 EUR.", runs: 2,
    });
  const runs = {
    "s-meta": [
      standingRun("r2", "s-meta", { outcome: "acted", summary: "One ad was too expensive.", actions: ["Paused the ad Carousel B"] }),
      standingRun("r1", "s-meta", { at_ms: Date.now() - 30 * HOUR, outcome: "quiet" }),
    ],
  };

  it("shows the task, the assistant's notes and the log of its looks", async () => {
    standingBackend([meta()], { runs });
    mount(<StandingTaskPage id="s-meta" name="Nova" onBack={vi.fn()} />);

    expect((await screen.findByRole("heading", { level: 2, name: "Meta ads campaign" })).textContent).toBe("Meta ads campaign");
    expect(screen.getByTestId("assistant-standing-summary").textContent).toBe("Active · looks every 3 hours");
    expect(screen.getByTestId("assistant-standing-goal").textContent).toBe("Keep cost per purchase under 20 EUR.");
    expect(screen.getByTestId("assistant-standing-how").textContent).toBe("Check Ads Manager.");
    expect(screen.getByTestId("assistant-standing-limits").textContent).toBe("None written.");
    expect(screen.getByTestId("assistant-standing-notes").textContent).toBe("Baseline CPA 14.90 EUR.");
    expect(screen.getByTestId("assistant-standing-last").textContent).toMatch(/^today, .+ · Told you: CPA rose to 18\.40 EUR\.$/);
    expect(screen.getByTestId("assistant-standing-next")).toBeTruthy();
    expect(screen.getByTestId("assistant-standing-level-prepare").getAttribute("aria-checked")).toBe("true");

    const acted = await screen.findByTestId("assistant-standing-run-r2");
    expect(within(acted).getByText("Took care of it")).toBeTruthy();
    expect(within(acted).getByText("One ad was too expensive.")).toBeTruthy();
    expect(within(acted).getByText("Changed")).toBeTruthy();
    expect(within(acted).getByText("Paused the ad Carousel B")).toBeTruthy();
    expect(within(screen.getByTestId("assistant-standing-run-r1")).getByText("Nothing new")).toBeTruthy();
  });

  it("saves 'act' only together with limits when none are written yet", async () => {
    const backend = standingBackend([meta()], { runs });
    mount(<StandingTaskPage id="s-meta" name="Nova" onBack={vi.fn()} />);

    fireEvent.click(await screen.findByTestId("assistant-standing-level-act"));
    // Nothing is saved yet: the limits field opens and says what is missing.
    const input = await screen.findByTestId("assistant-standing-limits-input");
    expect(screen.getByTestId("assistant-standing-limits-hint").textContent).toMatch(/^Acting needs limits/);
    expect(screen.getByTestId("assistant-standing-level-act").getAttribute("aria-checked")).toBe("true");
    expect((screen.getByTestId("assistant-standing-limits-save") as HTMLButtonElement).disabled).toBe(true);
    expect(backend.writes()).toEqual([]);

    fireEvent.change(input, { target: { value: "Pause single ads only." } });
    fireEvent.click(screen.getByTestId("assistant-standing-limits-save"));
    await waitFor(() => expect(backend.writes()).toEqual(["PATCH /s-meta"]));
    expect(backend.bodyOf("PATCH /s-meta")).toEqual({ autonomy: "act", limits: "Pause single ads only." });
    await waitFor(() => expect(screen.getByTestId("assistant-standing-limits").textContent).toBe("Pause single ads only."));
    expect(screen.getByTestId("assistant-standing-level-act").getAttribute("aria-checked")).toBe("true");
  });

  it("drops the wish to act when the limits are not written", async () => {
    const backend = standingBackend([meta()], { runs });
    mount(<StandingTaskPage id="s-meta" name="Nova" onBack={vi.fn()} />);

    fireEvent.click(await screen.findByTestId("assistant-standing-level-act"));
    fireEvent.click(await screen.findByTestId("assistant-standing-limits-cancel"));
    expect(screen.getByTestId("assistant-standing-level-prepare").getAttribute("aria-checked")).toBe("true");
    expect(backend.writes()).toEqual([]);
  });

  it("changes the level at once when it needs no limits, and when limits are there", async () => {
    const backend = standingBackend([{ ...meta(), limits: "Pause single ads only." }], { runs });
    mount(<StandingTaskPage id="s-meta" name="Nova" onBack={vi.fn()} />);

    fireEvent.click(await screen.findByTestId("assistant-standing-level-act"));
    await waitFor(() => expect(backend.bodyOf("PATCH /s-meta")).toEqual({ autonomy: "act" }));
    await waitFor(() => expect(screen.getByTestId("assistant-standing-level-act").getAttribute("aria-checked")).toBe("true"));
    // While it may act, the limits cannot be emptied.
    fireEvent.click(screen.getByTestId("assistant-standing-limits-edit"));
    fireEvent.change(screen.getByTestId("assistant-standing-limits-input"), { target: { value: "  " } });
    expect((screen.getByTestId("assistant-standing-limits-save") as HTMLButtonElement).disabled).toBe(true);
  });

  it("changes the pace", async () => {
    const backend = standingBackend([meta()], { runs });
    mount(<StandingTaskPage id="s-meta" name="Nova" onBack={vi.fn()} />);

    const trigger = await screen.findByTestId("assistant-standing-pace");
    expect(trigger.textContent).toContain("Every 3 hours");
    fireEvent.click(trigger);
    fireEvent.click(await screen.findByRole("option", { name: "Daily" }));
    await waitFor(() => expect(backend.bodyOf("PATCH /s-meta")).toEqual({ interval_min: 1440 }));
    await waitFor(() => expect(screen.getByTestId("assistant-standing-summary").textContent).toBe("Active · looks daily"));
  });

  it("rewrites the goal in place", async () => {
    const backend = standingBackend([meta()], { runs });
    mount(<StandingTaskPage id="s-meta" name="Nova" onBack={vi.fn()} />);

    fireEvent.click(await screen.findByTestId("assistant-standing-goal-edit"));
    fireEvent.change(screen.getByTestId("assistant-standing-goal-input"), { target: { value: "Keep CPA under 18 EUR." } });
    fireEvent.click(screen.getByTestId("assistant-standing-goal-save"));
    await waitFor(() => expect(backend.bodyOf("PATCH /s-meta")).toEqual({ goal: "Keep CPA under 18 EUR." }));
    await waitFor(() => expect(screen.getByTestId("assistant-standing-goal").textContent).toBe("Keep CPA under 18 EUR."));
  });

  it("looks now, pauses and resumes", async () => {
    const backend = standingBackend([meta()], { runs });
    mount(<StandingTaskPage id="s-meta" name="Nova" onBack={vi.fn()} />);

    fireEvent.click(await screen.findByTestId("assistant-standing-run"));
    await waitFor(() => expect(backend.writes()).toEqual(["POST /s-meta/run"]));
    await waitFor(() => expect(toasts().some((message) => message.endsWith("is taking a look now."))).toBe(true));

    await waitFor(() => expect((screen.getByTestId("assistant-standing-pause") as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByTestId("assistant-standing-pause"));
    const resume = await screen.findByTestId("assistant-standing-resume");
    expect(screen.queryByTestId("assistant-standing-run")).toBeNull();
    expect(screen.getByTestId("assistant-standing-summary").textContent).toBe("Paused · looks every 3 hours");

    await waitFor(() => expect((resume as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(resume);
    expect(await screen.findByTestId("assistant-standing-run")).toBeTruthy();
    expect(backend.writes()).toEqual(["POST /s-meta/run", "POST /s-meta/pause", "POST /s-meta/resume"]);
  });

  it("ends a task only after the question is answered, and goes back", async () => {
    const backend = standingBackend([meta()], { runs });
    const onBack = vi.fn();
    mount(<StandingTaskPage id="s-meta" name="Nova" onBack={onBack} />);

    fireEvent.click(await screen.findByTestId("assistant-standing-end"));
    const confirm = screen.getByTestId("assistant-standing-end-confirm");
    expect(confirm.textContent).toMatch(/^End “Meta ads campaign”\?/);
    expect(backend.writes()).toEqual([]);

    // Cancel takes the question away again.
    fireEvent.click(screen.getByTestId("assistant-standing-end-no"));
    expect(screen.queryByTestId("assistant-standing-end-confirm")).toBeNull();
    expect(backend.writes()).toEqual([]);

    fireEvent.click(screen.getByTestId("assistant-standing-end"));
    fireEvent.click(screen.getByTestId("assistant-standing-end-yes"));
    await waitFor(() => expect(backend.writes()).toEqual(["POST /s-meta/end"]));
    await waitFor(() => expect(onBack).toHaveBeenCalledTimes(1));
    expect(toasts()).toContain("Standing task ended");
  });

  it("offers Accept and Not now on a suggestion's own page", async () => {
    const backend = standingBackend([standingTask("s-idea", { title: "Domain renewals", state: "proposed", origin: "suggested", reason: "You missed one." })]);
    mount(<StandingTaskPage id="s-idea" name="Nova" onBack={vi.fn()} />);

    expect((await screen.findByTestId("assistant-standing-reason")).textContent).toBe("Why: You missed one.");
    expect(screen.queryByTestId("assistant-standing-run")).toBeNull();
    expect(screen.queryByTestId("assistant-standing-end")).toBeNull();
    fireEvent.click(screen.getByTestId("assistant-standing-page-accept"));
    await waitFor(() => expect(backend.writes()).toEqual(["POST /s-idea/accept"]));
    expect(await screen.findByTestId("assistant-standing-run")).toBeTruthy();
  });

  it("says so when the task is gone, with a way back", async () => {
    standingBackend([]);
    const onBack = vi.fn();
    mount(<StandingTaskPage id="s-nope" name="Nova" onBack={onBack} />);

    const error = await screen.findByTestId("assistant-standing-page-error");
    expect(within(error).getByText("No such standing task")).toBeTruthy();
    fireEvent.click(screen.getByTestId("assistant-standing-back"));
    expect(onBack).toHaveBeenCalled();
  });
});
