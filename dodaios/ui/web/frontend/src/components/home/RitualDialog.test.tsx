/**
 * The dialog that writes or changes one ritual: what a save sends, what an
 * existing ritual says about today, its three ways out besides Save (run it
 * now, gather for it now, delete it), and what it says and sends for a step
 * that comes down to one tool call.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import RitualDialog from "@/components/home/RitualDialog";
import { RITUAL_LIMITS, RITUALS_URL, ritual, ritualDay, ritualsBackend, todayAt } from "@/lib/ritualsApi.testkit";
import { useEventStore } from "@/store/events";

function mount(ritualId: string | null) {
  const onClose = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(<QueryClientProvider client={client}><RitualDialog ritualId={ritualId} onClose={onClose} /></QueryClientProvider>);
  return onClose;
}

const field = (id: string) => screen.getByTestId(id) as HTMLInputElement;
const button = (id: string) => screen.getByTestId(id) as HTMLButtonElement;
const type = (id: string, value: string) => fireEvent.change(field(id), { target: { value } });
const phrases = () => screen.queryAllByTestId("ritual-phrase").map((chip) => chip.textContent);
const toasts = () => useEventStore.getState().toasts.map((toast) => toast.message);

/** The least a ritual needs: a name, a phrase and a step. */
function writeTheLeast() {
  type("ritual-name", "Good morning");
  type("ritual-phrase-input", "Good morning");
  fireEvent.keyDown(field("ritual-phrase-input"), { key: "Enter" });
  type("ritual-now-0", "Open my calendar");
}

/** A saved ritual with one step for the moment and one that is gathered ahead. */
const saved = (more: Parameters<typeof ritual>[1] = {}) =>
  ritual("rit_1", {
    name: "Good morning",
    phrases: ["Good morning"],
    steps: [
      { id: "s_now", when: "now", text: "Open my calendar" },
      { id: "s_ahead", when: "ahead", text: "The AI news" },
    ],
    ...more,
  });

/** Waits until the saved ritual stands in the fields. */
async function opened() {
  await waitFor(() => expect(field("ritual-name").value).toBe("Good morning"));
}

beforeEach(() => {
  useEventStore.setState({ toasts: [], assistantName: "Nova" });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("RitualDialog, a new ritual", () => {
  it("sends what was written, without the lines left empty", async () => {
    const backend = ritualsBackend([]);
    const onClose = mount(null);

    expect(screen.getByTestId("ritual-dialog")).toBeTruthy();
    expect(field("ritual-name").getAttribute("placeholder")).toBe("Good morning");
    // Nothing about today, and nothing to run or delete, before it exists.
    expect(screen.queryByTestId("ritual-status")).toBeNull();
    expect(screen.queryByTestId("ritual-run")).toBeNull();
    expect(screen.queryByTestId("ritual-delete")).toBeNull();
    expect(screen.queryByTestId("ritual-gathered")).toBeNull();
    // The hint names the assistant the way the person named it.
    expect(screen.getByTestId("ritual-now").textContent)
      .toContain("Happens the moment you say it. Anything Nova can do, in your own words.");

    type("ritual-name", "  Good morning ");
    type("ritual-phrase-input", "Good morning");
    fireEvent.keyDown(field("ritual-phrase-input"), { key: "Enter" });
    type("ritual-now-0", "Open my calendar");
    // A second line that stays empty, and one topic to gather ahead.
    fireEvent.click(button("ritual-now-add"));
    expect(document.activeElement).toBe(field("ritual-now-1"));
    fireEvent.click(button("ritual-ahead-add"));
    expect(document.activeElement).toBe(field("ritual-ahead-0"));
    type("ritual-ahead-0", "The AI news of the last day");

    fireEvent.click(button("ritual-save"));
    await waitFor(() => expect(backend.writes()).toEqual(["POST "]));
    expect(backend.bodyOf("POST ")).toEqual({
      name: "Good morning",
      phrases: ["Good morning"],
      steps: [
        { when: "now", text: "Open my calendar" },
        { when: "ahead", text: "The AI news of the last day" },
      ],
      enabled: true,
      window_from: "",
      window_to: "",
      weekdays: [],
      once_per_day: true,
      prepare_from: "",
    });
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });

  it("keeps Save off until there is a name, a phrase and a step", () => {
    ritualsBackend([]);
    mount(null);

    expect(button("ritual-save").disabled).toBe(true);
    type("ritual-name", "Good morning");
    expect(button("ritual-save").disabled).toBe(true);
    // A phrase still in its field counts: nobody has to press Enter first.
    type("ritual-phrase-input", "Good morning");
    expect(button("ritual-save").disabled).toBe(true);
    type("ritual-now-0", "   ");
    expect(button("ritual-save").disabled).toBe(true);
    type("ritual-now-0", "Open my calendar");
    expect(button("ritual-save").disabled).toBe(false);
    type("ritual-name", "  ");
    expect(button("ritual-save").disabled).toBe(true);
  });

  it("sends a phrase that was typed but never entered", async () => {
    const backend = ritualsBackend([]);
    mount(null);

    type("ritual-name", "Good morning");
    type("ritual-phrase-input", "Good morning");
    type("ritual-now-0", "Open my calendar");
    fireEvent.click(button("ritual-save"));
    await waitFor(() => expect(backend.bodyOf("POST ")).toMatchObject({ phrases: ["Good morning"] }));
  });

  it("sends the time window, the days and the gather time that were chosen", async () => {
    const backend = ritualsBackend([]);
    mount(null);
    writeTheLeast();

    // Any time of day until the person says otherwise.
    expect(button("ritual-when-always").getAttribute("aria-pressed")).toBe("true");
    expect(button("ritual-when-timed").getAttribute("aria-pressed")).toBe("false");
    expect(screen.queryByTestId("ritual-from")).toBeNull();

    fireEvent.click(button("ritual-when-timed"));
    expect(button("ritual-when-timed").getAttribute("aria-pressed")).toBe("true");
    type("ritual-from", "08:00");
    type("ritual-to", "10:00");
    // Monday first, named the way the language shortens it.
    expect(Array.from({ length: 7 }, (_, day) => button(`ritual-day-${day}`).textContent))
      .toEqual(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]);
    fireEvent.click(button("ritual-day-2"));
    fireEvent.click(button("ritual-day-0"));
    fireEvent.click(button("ritual-day-5"));
    fireEvent.click(button("ritual-day-5"));
    expect(Array.from({ length: 7 }, (_, day) => button(`ritual-day-${day}`).getAttribute("aria-pressed")))
      .toEqual(["true", "false", "true", "false", "false", "false", "false"]);

    expect(button("ritual-once").getAttribute("aria-checked")).toBe("true");
    fireEvent.click(button("ritual-once"));

    // The gather time is only there once something is gathered ahead.
    expect(screen.queryByTestId("ritual-prepare-from")).toBeNull();
    fireEvent.click(button("ritual-ahead-add"));
    type("ritual-ahead-0", "The open pull requests");
    type("ritual-prepare-from", "07:30");

    fireEvent.click(button("ritual-enabled"));
    fireEvent.click(button("ritual-save"));
    await waitFor(() => expect(backend.writes()).toEqual(["POST "]));
    expect(backend.bodyOf("POST ")).toMatchObject({
      enabled: false, window_from: "08:00", window_to: "10:00", weekdays: [0, 2], once_per_day: false, prepare_from: "07:30",
    });
  });

  it("sends no window and no days once \"Always\" is chosen again", async () => {
    const backend = ritualsBackend([]);
    mount(null);
    writeTheLeast();

    fireEvent.click(button("ritual-when-timed"));
    type("ritual-from", "08:00");
    type("ritual-to", "10:00");
    fireEvent.click(button("ritual-day-0"));
    fireEvent.click(button("ritual-when-always"));
    expect(screen.queryByTestId("ritual-from")).toBeNull();
    // The switch below belongs to both choices.
    expect(button("ritual-once").getAttribute("aria-checked")).toBe("true");

    fireEvent.click(button("ritual-save"));
    await waitFor(() => expect(backend.writes()).toEqual(["POST "]));
    expect(backend.bodyOf("POST ")).toMatchObject({ window_from: "", window_to: "", weekdays: [], once_per_day: true });
  });

  it("takes a phrase on Enter, at a comma and on leaving the field, and none twice", () => {
    ritualsBackend([]);
    mount(null);

    type("ritual-phrase-input", "  Good   morning ");
    fireEvent.keyDown(field("ritual-phrase-input"), { key: "Enter" });
    expect(phrases()).toEqual(["Good morning"]);
    expect(field("ritual-phrase-input").value).toBe("");

    // The same phrase in other letters is not a second one; what follows the last comma is still being typed.
    type("ritual-phrase-input", "Morning, good MORNING, Hello");
    expect(phrases()).toEqual(["Good morning", "Morning"]);
    expect(field("ritual-phrase-input").value).toBe("Hello");
    fireEvent.blur(field("ritual-phrase-input"));
    expect(phrases()).toEqual(["Good morning", "Morning", "Hello"]);

    fireEvent.click(screen.getByLabelText("Remove “Morning”"));
    expect(phrases()).toEqual(["Good morning", "Hello"]);
  });

  it("keeps to the limits the server names", async () => {
    ritualsBackend([], { limits: { max_phrases: 2, max_steps: 2 } });
    mount(null);

    // The limits come with the list.
    await waitFor(() => expect(field("ritual-name").maxLength).toBe(60));
    expect(field("ritual-phrase-input").maxLength).toBe(60);
    expect(field("ritual-now-0").maxLength).toBe(500);

    type("ritual-phrase-input", "One, Two, Three");
    expect(phrases()).toEqual(["One", "Two"]);
    expect(screen.queryByTestId("ritual-phrase-input")).toBeNull();

    // Two lines are all it takes, whichever kind they are.
    fireEvent.click(button("ritual-ahead-add"));
    expect(screen.queryByTestId("ritual-now-add")).toBeNull();
    expect(screen.queryByTestId("ritual-ahead-add")).toBeNull();
    fireEvent.click(button("ritual-ahead-remove-0"));
    expect(screen.getByTestId("ritual-now-add")).toBeTruthy();
  });

  it("says the server's sentence when a save is refused, and stays open", async () => {
    ritualsBackend([], { refuse: { "POST ": { status: 409, detail: 'There is already a ritual named "Good morning".' } } });
    const onClose = mount(null);
    writeTheLeast();

    expect(screen.queryByRole("alert")).toBeNull();
    fireEvent.click(button("ritual-save"));
    expect((await screen.findByRole("alert")).textContent).toBe('There is already a ritual named "Good morning".');
    expect(onClose).not.toHaveBeenCalled();
    expect(field("ritual-name").value).toBe("Good morning");
    expect(button("ritual-save").disabled).toBe(false);
  });
});

describe("RitualDialog, an existing ritual", () => {
  it("shows the ritual as it is saved", async () => {
    ritualsBackend([saved({ enabled: false, window_from: "08:00", window_to: "10:00", weekdays: [0, 4], once_per_day: false, prepare_from: "07:30" })]);
    mount("rit_1");

    await opened();
    expect(button("ritual-enabled").getAttribute("aria-checked")).toBe("false");
    expect(phrases()).toEqual(["Good morning"]);
    expect(button("ritual-when-timed").getAttribute("aria-pressed")).toBe("true");
    expect(field("ritual-from").value).toBe("08:00");
    expect(field("ritual-to").value).toBe("10:00");
    expect(button("ritual-day-0").getAttribute("aria-pressed")).toBe("true");
    expect(button("ritual-day-1").getAttribute("aria-pressed")).toBe("false");
    expect(button("ritual-day-4").getAttribute("aria-pressed")).toBe("true");
    expect(button("ritual-once").getAttribute("aria-checked")).toBe("false");
    expect(field("ritual-now-0").value).toBe("Open my calendar");
    expect(field("ritual-ahead-0").value).toBe("The AI news");
    expect(field("ritual-prepare-from").value).toBe("07:30");
  });

  it("changes it with a PATCH, and a reworded step keeps its id", async () => {
    const backend = ritualsBackend([saved()]);
    const onClose = mount("rit_1");
    await opened();

    type("ritual-now-0", "Open my calendar and my mail");
    fireEvent.click(button("ritual-now-add"));
    type("ritual-now-1", "Play some music");
    fireEvent.click(button("ritual-save"));

    await waitFor(() => expect(backend.writes()).toEqual(["PATCH /rit_1"]));
    expect(backend.bodyOf("PATCH /rit_1")).toEqual({
      name: "Good morning",
      phrases: ["Good morning"],
      steps: [
        { id: "s_now", when: "now", text: "Open my calendar and my mail" },
        { when: "now", text: "Play some music" },
        { id: "s_ahead", when: "ahead", text: "The AI news" },
      ],
      enabled: true,
      window_from: "",
      window_to: "",
      weekdays: [],
      once_per_day: true,
      prepare_from: "",
    });
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });

  it("drops a step that was taken away, and the gather time with the last topic", async () => {
    const backend = ritualsBackend([saved({ prepare_from: "07:30" })]);
    mount("rit_1");
    await opened();

    fireEvent.click(button("ritual-ahead-remove-0"));
    expect(screen.queryByTestId("ritual-prepare-from")).toBeNull();
    fireEvent.click(button("ritual-save"));
    await waitFor(() => expect(backend.writes()).toEqual(["PATCH /rit_1"]));
    expect(backend.bodyOf("PATCH /rit_1")).toMatchObject({
      steps: [{ id: "s_now", when: "now", text: "Open my calendar" }],
      prepare_from: "",
    });
  });

  it("says where the ritual stands today, and unfolds what was gathered", async () => {
    ritualsBackend([saved({
      today: ritualDay({ prep_state: "ready", prepared_ms: todayAt(7, 50), fired_ms: todayAt(8, 5), written: "## News\n\n- One thing happened." }),
    })]);
    mount("rit_1");

    await waitFor(() => expect(screen.getByTestId("ritual-status").textContent).toBe("Gathered today at 07:50 · Ran today at 08:05"));
    const fold = await screen.findByTestId("ritual-gathered");
    expect(fold.textContent).toBe("What was gathered today");
    expect(fold.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByTestId("ritual-gathered-text")).toBeNull();

    fireEvent.click(fold);
    expect(fold.getAttribute("aria-expanded")).toBe("true");
    // Drawn like an answer in the chat: the heading is a heading, the line a list item.
    const text = screen.getByTestId("ritual-gathered-text");
    expect(text.querySelector("h2")?.textContent).toBe("News");
    expect(text.querySelector("li")?.textContent).toBe("One thing happened.");
  });

  it("says in the destructive colour why a gathering failed", async () => {
    ritualsBackend([saved({ today: ritualDay({ prep_state: "failed", prep_error: "No model answered." }) })]);
    mount("rit_1");

    await waitFor(() => expect(screen.getByTestId("ritual-status").textContent).toBe("Gathering failed: No model answered."));
    expect(screen.getByTestId("ritual-status").querySelector(".text-destructive")?.textContent)
      .toBe("Gathering failed: No model answered.");
    expect(screen.queryByTestId("ritual-gathered")).toBeNull();
  });

  it("gathers now for a ritual that wants something ready", async () => {
    const backend = ritualsBackend([saved()]);
    mount("rit_1");
    await opened();

    expect(button("ritual-gather").textContent).toBe("Gather now");
    expect(screen.getByTestId("ritual-status").textContent).toBe("");
    fireEvent.click(button("ritual-gather"));
    await waitFor(() => expect(backend.writes()).toEqual(["POST /rit_1/prepare"]));
    await waitFor(() => expect(screen.getByTestId("ritual-status").textContent).toBe("Gathering right now…"));
    // One gathering at a time.
    expect(button("ritual-gather").disabled).toBe(true);
  });

  it("offers no gathering for a ritual that wants nothing ready", async () => {
    ritualsBackend([ritual("rit_2", { name: "Good morning" })]);
    mount("rit_2");
    await opened();

    expect(screen.queryByTestId("ritual-gather")).toBeNull();
    expect(screen.queryByTestId("ritual-status")).toBeNull();
    expect(screen.queryByTestId("ritual-prepare-from")).toBeNull();
  });

  it("runs the ritual as it is saved: \"Run now\" waits for a save", async () => {
    const backend = ritualsBackend([saved()]);
    const onClose = mount("rit_1");
    await opened();

    expect(button("ritual-run").disabled).toBe(false);
    expect(button("ritual-run").getAttribute("title")).toBeNull();
    type("ritual-name", "Good morning!");
    expect(button("ritual-run").disabled).toBe(true);
    expect(button("ritual-run").getAttribute("title")).toBe("Save your changes first");
    expect(button("ritual-gather").disabled).toBe(true);
    // Put back as it was, there is nothing left to save.
    type("ritual-name", "Good morning");
    expect(button("ritual-run").disabled).toBe(false);

    fireEvent.click(button("ritual-run"));
    await waitFor(() => expect(backend.writes()).toEqual(["POST /rit_1/run"]));
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(toasts()).toContain("“Good morning” started");
  });

  it("deletes in two clicks, and the first one falls back by itself", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const backend = ritualsBackend([saved()]);
      const onClose = mount("rit_1");
      await opened();

      expect(button("ritual-delete").textContent).toBe("Delete");
      fireEvent.click(button("ritual-delete"));
      expect(button("ritual-delete").textContent).toBe("Delete for good");
      expect(backend.writes()).toEqual([]);

      // Nobody pressed it a second time: it is "Delete" again.
      act(() => { vi.advanceTimersByTime(5_100); });
      expect(button("ritual-delete").textContent).toBe("Delete");

      fireEvent.click(button("ritual-delete"));
      fireEvent.click(button("ritual-delete"));
      await waitFor(() => expect(backend.writes()).toEqual(["DELETE /rit_1"]));
      await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    } finally {
      vi.useRealTimers();
    }
  });

  describe("opened on the list's copy", () => {
    /** The list answers at once; the ritual's own request waits until it is let go. */
    function slowDetail() {
      const own = saved({
        steps: [
          { id: "s_now", when: "now", text: "Open my calendar and my mail" },
          { id: "s_ahead", when: "ahead", text: "The AI news" },
        ],
        today: ritualDay({ prep_state: "ready", prepared_ms: todayAt(7, 50) }),
      });
      let letGo: () => void = () => undefined;
      const held = new Promise<void>((resolve) => { letGo = resolve; });
      vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
        const reply = (payload: unknown) => new Response(JSON.stringify(payload), { status: 200 });
        if (String(input) === RITUALS_URL) return reply({ available: true, rituals: [saved()], limits: RITUAL_LIMITS });
        await held;
        const { today, ...ritual } = own;
        return reply({ ritual, today });
      }));
      return () => letGo();
    }

    it("takes the ritual's own copy when it arrives", async () => {
      const letGo = slowDetail();
      mount("rit_1");

      // The dialog does not wait for it: the list's copy stands in.
      await waitFor(() => expect(field("ritual-now-0").value).toBe("Open my calendar"));
      letGo();
      await waitFor(() => expect(field("ritual-now-0").value).toBe("Open my calendar and my mail"));
      expect(button("ritual-run").disabled).toBe(false);
    });

    it("keeps what the person wrote meanwhile", async () => {
      const letGo = slowDetail();
      mount("rit_1");

      await opened();
      type("ritual-name", "Good morning, all");
      letGo();
      // Its own copy is there now: it says where the ritual stands today.
      await waitFor(() => expect(screen.getByTestId("ritual-status").textContent).toBe("Gathered today at 07:50"));
      // What was written stays, and it counts as a change to the ritual as it is saved.
      expect(field("ritual-name").value).toBe("Good morning, all");
      expect(field("ritual-now-0").value).toBe("Open my calendar");
      expect(button("ritual-run").disabled).toBe(true);
    });
  });

  it("keeps its buttons, and what the server says to a save, outside the fields that scroll", async () => {
    ritualsBackend([saved()], { refuse: { "PATCH /rit_1": { status: 422, detail: "A time window needs both its start and its end." } } });
    const onClose = mount("rit_1");
    await opened();

    const fields = screen.getByTestId("ritual-fields");
    expect(fields.contains(field("ritual-name"))).toBe(true);
    expect(fields.contains(field("ritual-ahead-0"))).toBe(true);
    for (const id of ["ritual-delete", "ritual-run", "ritual-save"]) expect(fields.contains(button(id))).toBe(false);

    // Half a time window: the server says what is missing, and the sentence stands with the buttons.
    fireEvent.click(button("ritual-when-timed"));
    type("ritual-from", "08:00");
    fireEvent.click(button("ritual-save"));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("A time window needs both its start and its end.");
    expect(fields.contains(alert)).toBe(false);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("says so when the ritual is not there", async () => {
    ritualsBackend([]);
    mount("rit_gone");

    expect(screen.getByRole("status").textContent).toBe("Loading…");
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("No such ritual"));
    expect(screen.queryByTestId("ritual-save")).toBeNull();
  });
});

describe("RitualDialog, a step that comes down to one tool call", () => {
  const LIKED = { tool: "youtube_music_play", args: { playlist: "liked" }, says: "YouTube Music: liked songs" };
  const withCall = () => saved({
    steps: [
      { id: "s_music", when: "now", text: "Play my liked songs", call: LIKED },
      { id: "s_cal", when: "now", text: "Open my calendar" },
      { id: "s_ahead", when: "ahead", text: "The AI news" },
    ],
  });
  const sentSteps = (backend: ReturnType<typeof ritualsBackend>) =>
    (backend.bodyOf("PATCH /rit_1") as { steps: Record<string, unknown>[] }).steps;

  it("says under the step what it comes down to, and nothing under any other", async () => {
    ritualsBackend([withCall()]);
    mount("rit_1");
    await opened();

    const line = screen.getByTestId("ritual-now-call-0");
    expect(line.textContent).toBe("YouTube Music: liked songs");
    expect(line.getAttribute("title")).toBe("Happens at once, without a wait");
    expect(line.querySelector(".lucide-zap")).toBeTruthy();
    // A step that takes an ordinary turn says nothing more, and neither does one that is gathered ahead.
    expect(screen.queryByTestId("ritual-now-call-1")).toBeNull();
    expect(screen.queryByTestId("ritual-ahead-call-0")).toBeNull();
    // Nothing was changed by reading it.
    expect(button("ritual-run").disabled).toBe(false);
  });

  it("names the tool when the call has no words of its own", async () => {
    ritualsBackend([saved({ steps: [{ id: "s_music", when: "now", text: "Play my liked songs", call: { ...LIKED, says: " " } }] })]);
    mount("rit_1");
    await opened();

    expect(screen.getByTestId("ritual-now-call-0").textContent).toBe("youtube_music_play");
  });

  it("sends the call back as it came while the sentence is the same", async () => {
    const backend = ritualsBackend([withCall()]);
    mount("rit_1");
    await opened();

    type("ritual-now-1", "Open my calendar and my mail");
    fireEvent.click(button("ritual-now-add"));
    type("ritual-now-2", "Read me the weather");
    fireEvent.click(button("ritual-save"));

    await waitFor(() => expect(backend.writes()).toEqual(["PATCH /rit_1"]));
    expect(sentSteps(backend)).toEqual([
      { id: "s_music", when: "now", text: "Play my liked songs", call: LIKED },
      { id: "s_cal", when: "now", text: "Open my calendar and my mail" },
      // A step the person just wrote has no call yet.
      { when: "now", text: "Read me the weather" },
      { id: "s_ahead", when: "ahead", text: "The AI news" },
    ]);
  });

  it("drops the call of a reworded step: the sentence no longer says what that call does", async () => {
    const backend = ritualsBackend([withCall()]);
    mount("rit_1");
    await opened();

    type("ritual-now-0", "Play my favourite album");
    expect(screen.queryByTestId("ritual-now-call-0")).toBeNull();
    // Put back as it was, it is again the sentence the call belongs to.
    type("ritual-now-0", "Play my liked songs");
    expect(screen.getByTestId("ritual-now-call-0").textContent).toBe("YouTube Music: liked songs");
    type("ritual-now-0", "Play my favourite album");
    fireEvent.click(button("ritual-save"));

    await waitFor(() => expect(backend.writes()).toEqual(["PATCH /rit_1"]));
    const steps = sentSteps(backend);
    // The step stays the same step, without the call.
    expect(steps[0]).toEqual({ id: "s_music", when: "now", text: "Play my favourite album" });
    expect("call" in steps[0]).toBe(false);
    expect(steps.slice(1)).toEqual([
      { id: "s_cal", when: "now", text: "Open my calendar" },
      { id: "s_ahead", when: "ahead", text: "The AI news" },
    ]);
  });
});
