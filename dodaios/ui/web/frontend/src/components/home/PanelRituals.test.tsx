/**
 * The rituals in the assistant's panel: each row with the phrase that starts
 * it and where it stands today, the switch that turns it on or off, the
 * fold, the way to a new one, and what the part says while there is none.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PanelRituals, ritualState } from "@/components/home/PanelRituals";
import { ritual, ritualDay, ritualsBackend, todayAt } from "@/lib/ritualsApi.testkit";
import { useEventStore } from "@/store/events";

function mount() {
  const onOpen = vi.fn();
  const onNew = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(<QueryClientProvider client={client}><PanelRituals onOpen={onOpen} onNew={onNew} /></QueryClientProvider>);
  return { onOpen, onNew };
}

const row = (id: string) => screen.getByTestId(`assistant-ritual-${id}`);
const toggle = (id: string) => screen.getByTestId(`assistant-ritual-switch-${id}`);
const toasts = () => useEventStore.getState().toasts.map((toast) => toast.message);

beforeEach(() => {
  useEventStore.setState({ toasts: [] });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("PanelRituals", () => {
  it("names each ritual with the phrase that starts it and where it stands today", async () => {
    ritualsBackend([
      ritual("gathering", { name: "Good morning", phrases: ["Good morning", "Morning"], today: ritualDay({ prep_state: "running" }) }),
      ritual("failed", { phrases: ["Start the day"], today: ritualDay({ prep_state: "failed", prep_error: "No model answered." }) }),
      ritual("ran", { phrases: ["Wrap up"], today: ritualDay({ prep_state: "ready", prepared_ms: todayAt(7, 50), fired_ms: todayAt(8, 5) }) }),
      ritual("ready", { phrases: ["Lunch"], today: ritualDay({ prep_state: "ready", prepared_ms: todayAt(11, 30) }) }),
      ritual("again", { phrases: ["News"], today: ritualDay({ prep_state: "ready", prepared_ms: todayAt(12, 0), fired_ms: todayAt(8, 5) }) }),
      ritual("window", { phrases: ["Good night"], window_from: "21:00", window_to: "23:30" }),
      ritual("plain", { phrases: ["Focus"] }),
    ]);
    mount();

    const part = screen.getByTestId("assistant-panel-rituals");
    expect(part.querySelector("h2")?.textContent).toBe("Rituals");
    await screen.findByTestId("assistant-ritual-gathering");
    const shown = () => Array.from(part.querySelectorAll("[data-testid^='assistant-ritual-']"))
      .map((node) => node.getAttribute("data-testid")).filter((id) => !id?.includes("switch") && !id?.endsWith("-new"));

    // The first four show; the rest is one click away.
    expect(shown()).toEqual(["gathering", "failed", "ran", "ready"].map((id) => `assistant-ritual-${id}`));
    fireEvent.click(screen.getByTestId("assistant-rituals-more"));
    expect(shown()).toHaveLength(7);

    // The first phrase only, in quotes, then today's state.
    expect(row("gathering").textContent).toBe("Good morning“Good morning” · Gathering");
    expect(row("gathering").getAttribute("title")).toBe("Good morning · “Good morning” · Gathering");
    expect(row("failed").textContent).toBe("failed“Start the day” · Failed");
    // It ran, and what it wanted ready was handed over with that start.
    expect(row("ran").textContent).toBe("ran“Wrap up” · Ran at 08:05");
    expect(row("ready").textContent).toBe("ready“Lunch” · Ready");
    // Gathered again after it ran: ready once more.
    expect(row("again").textContent).toBe("again“News” · Ready");
    // Nothing about today: the time window stands in, and without one nothing does.
    expect(row("window").textContent).toBe("window“Good night” · 21:00–23:30");
    expect(row("plain").textContent).toBe("plain“Focus”");
    expect(["gathering", "failed", "ran", "ready", "again", "window", "plain"].map((id) => row(id).getAttribute("data-state")))
      .toEqual(["gathering", "failed", "ran", "ready", "ready", "window", ""]);

    // A gathering that runs turns, one that failed is marked; nothing else is.
    expect(row("gathering").querySelector(".lucide-loader-circle")).toBeTruthy();
    expect(row("failed").querySelector(".lucide-circle-alert")).toBeTruthy();
    expect(row("ready").querySelector(".lucide-loader-circle, .lucide-circle-alert")).toBeNull();

    fireEvent.click(screen.getByTestId("assistant-rituals-more"));
    expect(shown()).toHaveLength(4);
  });

  it("reads a start as the day's news until something newer was gathered", () => {
    const at = (today: Parameters<typeof ritualDay>[0]) => ritualState(ritual("r", { today: ritualDay(today) }));
    // A gathering under way or failed comes before everything else.
    expect(at({ prep_state: "running", fired_ms: 5 })).toBe("gathering");
    expect(at({ prep_state: "failed", fired_ms: 5 })).toBe("failed");
    // It ran without anything gathered ahead.
    expect(at({ fired_ms: 5 })).toBe("ran");
    // What is there was gathered before the start, so the start took it.
    expect(at({ prep_state: "ready", prepared_ms: 5, fired_ms: 5 })).toBe("ran");
    expect(at({ prep_state: "ready", prepared_ms: 6, fired_ms: 5 })).toBe("ready");
    // Half a window is no window.
    expect(ritualState(ritual("r", { window_from: "08:00" }))).toBe("");
  });

  it("turns a ritual off and on with its switch", async () => {
    const backend = ritualsBackend([ritual("rit_1", { name: "Good morning" }), ritual("rit_2", { enabled: false })]);
    mount();

    await screen.findByTestId("assistant-ritual-rit_1");
    expect(toggle("rit_1").getAttribute("aria-checked")).toBe("true");
    expect(toggle("rit_1").getAttribute("aria-label")).toBe("Good morning");
    // A ritual that is off stays in the list, its name in the quiet ink.
    expect(toggle("rit_2").getAttribute("aria-checked")).toBe("false");
    expect(row("rit_2").querySelector("span > span")?.className).toContain("text-muted-foreground");
    expect(row("rit_1").querySelector("span > span")?.className).toContain("text-foreground");

    fireEvent.click(toggle("rit_1"));
    await waitFor(() => expect(backend.writes()).toEqual(["PATCH /rit_1"]));
    expect(backend.bodyOf("PATCH /rit_1")).toEqual({ enabled: false });
    await waitFor(() => expect(toggle("rit_1").getAttribute("aria-checked")).toBe("false"));

    fireEvent.click(toggle("rit_2"));
    await waitFor(() => expect(backend.writes()).toEqual(["PATCH /rit_1", "PATCH /rit_2"]));
    expect(backend.bodyOf("PATCH /rit_2")).toEqual({ enabled: true });
    await waitFor(() => expect(toggle("rit_2").getAttribute("aria-checked")).toBe("true"));
  });

  it("says the server's sentence when the switch is refused, and stays as it was", async () => {
    ritualsBackend([ritual("rit_1")], { refuse: { "PATCH /rit_1": { status: 409, detail: "The ritual is starting right now." } } });
    mount();

    fireEvent.click(await screen.findByTestId("assistant-ritual-switch-rit_1"));
    await waitFor(() => expect(toasts()).toContain("The ritual is starting right now."));
    expect(toggle("rit_1").getAttribute("aria-checked")).toBe("true");
    expect(toggle("rit_1").hasAttribute("disabled")).toBe(false);
  });

  it("says a refusal even when another switch was flipped right after", async () => {
    const backend = ritualsBackend([ritual("rit_1"), ritual("rit_2")], {
      refuse: { "PATCH /rit_1": { status: 409, detail: "The ritual is starting right now." } },
    });
    mount();

    await screen.findByTestId("assistant-ritual-rit_1");
    fireEvent.click(toggle("rit_1"));
    fireEvent.click(toggle("rit_2"));
    await waitFor(() => expect(toasts()).toContain("The ritual is starting right now."));
    await waitFor(() => expect(toggle("rit_2").getAttribute("aria-checked")).toBe("false"));
    expect(toggle("rit_1").getAttribute("aria-checked")).toBe("true");
    expect(backend.writes()).toEqual(["PATCH /rit_1", "PATCH /rit_2"]);
  });

  it("opens a ritual from its row, and a new one from the last row", async () => {
    ritualsBackend([ritual("rit_1")]);
    const { onOpen, onNew } = mount();

    fireEvent.click(await screen.findByTestId("assistant-ritual-rit_1"));
    expect(onOpen).toHaveBeenCalledWith("rit_1");
    expect(onNew).not.toHaveBeenCalled();

    const add = screen.getByTestId("assistant-ritual-new");
    expect(add.textContent).toBe("New ritual");
    expect(screen.getByTestId("assistant-panel-rituals").lastElementChild).toBe(add);
    fireEvent.click(add);
    expect(onNew).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("assistant-rituals-more")).toBeNull();
  });

  it("offers no new ritual once there are as many as there may be", async () => {
    ritualsBackend([ritual("a"), ritual("b")], { limits: { max_rituals: 2 } });
    mount();

    await screen.findByTestId("assistant-ritual-a");
    expect(screen.queryByTestId("assistant-ritual-new")).toBeNull();
  });

  it("says what a ritual is for while there is none", async () => {
    ritualsBackend([]);
    mount();

    // Until the list is there, the part only says that it loads.
    expect(screen.getByTestId("assistant-rituals-empty").textContent).toBe("Loading…");
    expect(screen.queryByTestId("assistant-ritual-new")).toBeNull();

    await waitFor(() => expect(screen.getByTestId("assistant-rituals-empty").textContent)
      .toBe("Say a short phrase, and what you set up happens."));
    expect(screen.getByTestId("assistant-ritual-new")).toBeTruthy();
  });
});
