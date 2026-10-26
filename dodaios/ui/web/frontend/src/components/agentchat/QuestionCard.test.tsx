import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AgentChatApiError, type AgentChatEvent } from "@/lib/agentChatApi";
import { createAgentChatStore } from "@/store/agentChat";
import { AgentChatStoreProvider } from "./AgentChatStoreContext";
import { QuestionCard } from "./QuestionCard";
import { EMPTY_TIMELINE, reduceEvents, type QuestionState, type ToolBlock, type TurnItem } from "./reduce";
import { useQuestionDrafts } from "./questions/questionDraftStore";
import { resetQuestionKeyboard } from "./questions/useQuestionKeyboard";

let seq = 0;
function ev(kind: string, payload: Record<string, unknown>, tsMs = 1000): AgentChatEvent {
  return { seq: ++seq, ts_ms: tsMs, kind, payload } as AgentChatEvent;
}

const DB = {
  question: "Which database should the project use?",
  options: [
    { label: "SQLite", description: "Zero setup" },
    { label: "Postgres", description: "Scales further" },
  ],
  recommended: 0,
  recommendation_reason: "No server to run.",
};
const HOST = {
  question: "Where should it run?",
  options: [{ label: "Laptop" }, { label: "VPS" }, { label: "Both" }],
  recommended: 0,
  recommendation_reason: "Nothing to pay for.",
};
const FEATURES = {
  question: "Which features ship first?",
  kind: "multi",
  options: [{ label: "Search" }, { label: "Export" }, { label: "Sharing" }],
  recommended: 0,
  recommended_count: 2,
  recommendation_reason: "Most asked for.",
};
const NAME = { question: "What should it be called?", kind: "text", options: [] };

function asking(extra: AgentChatEvent[] = [], questions: unknown[] = [DB, HOST], payload: Record<string, unknown> = {}): AgentChatEvent[] {
  return [
    ev("turn_started", { turn_id: "t1" }),
    ev("tool_call", { turn_id: "t1", call_id: "c1", name: "mcp__jarvis__society_ask_user", input: {} }),
    ev("question_required", {
      turn_id: "t1",
      question_id: "q1",
      asker: "Ada",
      questions,
      expires_ms: Date.now() + 5 * 60_000,
      ...payload,
    }),
    ...extra,
  ];
}

function questionOf(events: AgentChatEvent[]): QuestionState {
  const turn = reduceEvents(EMPTY_TIMELINE, events).items.find((i) => i.type === "turn") as TurnItem;
  return (turn.blocks.find((b) => b.kind === "tool" && (b as ToolBlock).question) as ToolBlock).question!;
}

afterEach(() => {
  cleanup();
  seq = 0;
  vi.restoreAllMocks();
  vi.useRealTimers();
  useQuestionDrafts.setState({ drafts: {} });
  resetQuestionKeyboard();
});

describe("question events", () => {
  it("attach the series to the ask call and record each answer", () => {
    const tl = reduceEvents(EMPTY_TIMELINE, asking([
      ev("question_progress", {
        turn_id: "t1",
        question_id: "q1",
        answers: [{ answer: "Postgres", option_index: 1, source: "person" }, null],
      }),
      ev("question_resolved", {
        turn_id: "t1",
        question_id: "q1",
        answers: [
          { answer: "Postgres", option_index: 1, source: "person" },
          { answer: "Laptop", option_index: 0, source: "timeout" },
        ],
      }),
    ]));
    const turn = tl.items[0] as TurnItem;
    expect(turn.blocks).toHaveLength(1);
    const block = turn.blocks[0] as ToolBlock;
    expect(block.callId).toBe("c1");
    expect(block.question?.questions.map((q) => q.question)).toEqual([DB.question, HOST.question]);
    expect(block.question?.answers.map((a) => a?.source)).toEqual(["person", "timeout"]);
    expect(block.question?.closed).toBe(true);
  });

  it("read an older single-question event as a single-select question", () => {
    const tl = reduceEvents(EMPTY_TIMELINE, [
      ev("turn_started", { turn_id: "t1" }),
      ev("question_required", { turn_id: "t1", question_id: "q0", ...DB }),
      ev("question_resolved", { turn_id: "t1", question_id: "q0", answer: "SQLite", option_index: 0, source: "timeout" }),
    ]);
    const block = (tl.items[0] as TurnItem).blocks[0] as ToolBlock;
    expect(block.question?.questions[0]).toMatchObject({ kind: "single", allowCustom: true, recommendedCount: 1 });
    expect(block.question?.answers[0]).toEqual({ text: "SQLite", optionIndex: 0, source: "timeout" });
  });

  it("read multi-select and text-only questions with their picks", () => {
    const q = questionOf(asking([
      ev("question_resolved", {
        turn_id: "t1",
        question_id: "q1",
        answers: [
          { answer: "Search\nSharing", option_index: null, option_indices: [0, 2], source: "person" },
          { answer: "", option_index: null, source: "declined" },
        ],
      }),
    ], [FEATURES, NAME]));
    expect(q.questions.map((i) => i.kind)).toEqual(["multi", "text"]);
    expect(q.questions[0].recommendedCount).toBe(2);
    expect(q.questions[1].options).toEqual([]);
    expect(q.answers[0]?.optionIndices).toEqual([0, 2]);
  });

  it("close an unanswered card when the turn ends", () => {
    const q = questionOf(asking([ev("turn_finished", { turn_id: "t1", status: "cancelled" })]));
    expect(q.closed).toBe(true);
    expect(q.answers.map((a) => a?.source)).toEqual(["closed", "closed"]);
  });
});

function draw(questions: QuestionState | QuestionState[], overrides: Record<string, unknown> = {}) {
  const store = createAgentChatStore("society");
  const submit = vi.fn(async () => undefined);
  const skip = vi.fn(async () => undefined);
  const touch = vi.fn(async () => undefined);
  store.setState({ activeSessionId: "s1", submitQuestion: submit, skipQuestion: skip, touchQuestion: touch, ...overrides });
  const list = Array.isArray(questions) ? questions : [questions];
  const view = render(
    <AgentChatStoreProvider store={store}>
      {list.map((q) => <QuestionCard key={q.questionId} question={q} />)}
    </AgentChatStoreProvider>,
  );
  return { store, submit, skip, touch, view };
}

function rowsOf(card: HTMLElement): HTMLButtonElement[] {
  return Array.from(card.querySelectorAll<HTMLButtonElement>(".qc-step[data-active] button[data-recommended]"));
}

describe("QuestionCard", () => {
  it("titles the card with the asker and the question, lettered rows and the recommendation", () => {
    draw(questionOf(asking([], [DB])));
    const card = screen.getByTestId("question-card");
    expect(card.getAttribute("data-state")).toBe("open");
    expect(card.textContent).toContain("Ada");
    expect(within(card).getByRole("heading").textContent).toBe(DB.question);
    const rows = rowsOf(card);
    expect(rows.map((r) => r.getAttribute("aria-keyshortcuts"))).toEqual(["A", "B"]);
    expect(rows[0].getAttribute("data-recommended")).toBe("true");
    expect(rows[0].textContent).toContain("Recommended");
    // The reason sits behind a disclosure, not in the way.
    const why = within(card).getByRole("button", { name: /why this recommendation/i });
    expect(why.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(why);
    expect(why.getAttribute("aria-expanded")).toBe("true");
    expect(card.textContent).toContain("No server to run.");
  });

  it("settles at once on a pick and sends the whole card", async () => {
    const { submit } = draw(questionOf(asking([], [DB])));
    fireEvent.click(rowsOf(screen.getByTestId("question-card"))[1]);
    // Optimistic: settled in the same frame, before the request returns.
    const card = screen.getByTestId("question-card");
    expect(card.hasAttribute("data-settled")).toBe(true);
    expect(card.textContent).toContain("Postgres");
    await waitFor(() => expect(submit).toHaveBeenCalledWith("q1", [{ option_index: 1 }]));
  });

  it("rolls back a failed answer and replays it with Try again", async () => {
    const submit = vi.fn()
      .mockRejectedValueOnce(new AgentChatApiError("network down", 500))
      .mockResolvedValueOnce(undefined);
    draw(questionOf(asking([], [DB])), { submitQuestion: submit });
    fireEvent.click(rowsOf(screen.getByTestId("question-card"))[1]);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/did not go through/i);
    expect(screen.getByTestId("question-card").getAttribute("data-state")).toBe("open");
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    await waitFor(() => expect(submit).toHaveBeenCalledTimes(2));
    expect(submit.mock.calls[1]).toEqual(["q1", [{ option_index: 1 }]]);
    await waitFor(() => expect(screen.getByTestId("question-card").hasAttribute("data-settled")).toBe(true));
  });

  it("gives way quietly when the server already closed the card", async () => {
    const submit = vi.fn().mockRejectedValue(new AgentChatApiError("no such open question", 404));
    draw(questionOf(asking([], [DB])), { submitQuestion: submit });
    fireEvent.click(rowsOf(screen.getByTestId("question-card"))[0]);
    await waitFor(() => expect(submit).toHaveBeenCalled());
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("answers the newest open card by letter key, never while typing", async () => {
    const older = questionOf(asking([], [DB]));
    const newer = { ...questionOf(asking([], [HOST])), questionId: "q2" };
    const { submit } = draw([older, newer]);
    const input = document.createElement("input");
    document.body.appendChild(input);
    fireEvent.keyDown(input, { key: "b" });
    expect(submit).not.toHaveBeenCalled();
    fireEvent.keyDown(window, { key: "b", ctrlKey: true });
    expect(submit).not.toHaveBeenCalled();
    fireEvent.keyDown(window, { key: "b" });
    await waitFor(() => expect(submit).toHaveBeenCalledWith("q2", [{ option_index: 1 }]));
    expect(submit).toHaveBeenCalledTimes(1);
    input.remove();
  });

  it("walks a series with auto-advance, review, change and one send", async () => {
    const { submit } = draw(questionOf(asking()));
    const card = screen.getByTestId("question-card");
    expect(screen.getByTestId("question-step").textContent).toBe("1 of 2");
    fireEvent.keyDown(window, { key: "a" });
    await waitFor(() => expect(screen.getByTestId("question-step").textContent).toBe("2 of 2"));
    fireEvent.click(rowsOf(card)[2]);
    const review = await screen.findByTestId("question-review");
    await waitFor(() => expect(review.closest(".qc-step")?.hasAttribute("data-active")).toBe(true));
    expect(review.textContent).toContain("SQLite");
    expect(review.textContent).toContain("Both");
    expect(submit).not.toHaveBeenCalled();
    // Change the first answer, then come back to the review.
    fireEvent.click(within(review).getAllByRole("button")[0]);
    expect(screen.getByTestId("question-step").textContent).toBe("1 of 2");
    expect(rowsOf(card)[0].querySelector("[data-on]")).not.toBeNull();
    fireEvent.click(rowsOf(card)[1]);
    await waitFor(() => expect(screen.getByTestId("question-step").textContent).toBe("2 of 2"));
    fireEvent.click(within(card).getByRole("button", { name: /^review$/i }));
    fireEvent.click(screen.getByTestId("question-send"));
    await waitFor(() => expect(submit).toHaveBeenCalledWith("q1", [{ option_index: 1 }, { option_index: 2 }]));
  });

  it("goes back and skips steps in a series", async () => {
    const { submit } = draw(questionOf(asking()));
    const card = screen.getByTestId("question-card");
    fireEvent.click(within(card).getByRole("button", { name: /^skip$/i }));
    expect(screen.getByTestId("question-step").textContent).toBe("2 of 2");
    fireEvent.click(within(card).getByRole("button", { name: /^back$/i }));
    expect(screen.getByTestId("question-step").textContent).toBe("1 of 2");
    fireEvent.click(within(card).getByRole("button", { name: /^skip$/i }));
    fireEvent.click(within(card).getByRole("button", { name: /^skip$/i }));
    fireEvent.click(screen.getByTestId("question-send"));
    await waitFor(() => expect(submit).toHaveBeenCalledWith("q1", [{ skip: true }, { skip: true }]));
  });

  it("toggles a multi-select question and sends it with Done", async () => {
    const { submit } = draw(questionOf(asking([], [FEATURES])));
    const card = screen.getByTestId("question-card");
    expect(card.textContent).toMatch(/pick all that apply/i);
    const rows = rowsOf(card);
    expect(rows.filter((r) => r.getAttribute("data-recommended") === "true")).toHaveLength(2);
    fireEvent.click(rows[0]);
    fireEvent.keyDown(window, { key: "c" });
    expect(rows[0].getAttribute("aria-pressed")).toBe("true");
    expect(rows[2].getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(rows[0]);
    expect(rows[0].getAttribute("aria-pressed")).toBe("false");
    fireEvent.change(within(card).getByRole("textbox"), { target: { value: "Dark mode" } });
    fireEvent.click(screen.getByTestId("question-done"));
    await waitFor(() => expect(submit).toHaveBeenCalledWith("q1", [{ option_indices: [2], text: "Dark mode" }]));
  });

  it("skips a multi-select question sent with nothing picked", async () => {
    const { submit } = draw(questionOf(asking([], [FEATURES])));
    fireEvent.click(screen.getByTestId("question-done"));
    await waitFor(() => expect(submit).toHaveBeenCalledWith("q1", [{ skip: true }]));
    expect(screen.getByTestId("question-card").textContent).toContain("Skipped");
  });

  it("sends a text-only answer with Enter", async () => {
    const { submit } = draw(questionOf(asking([], [NAME])));
    const field = within(screen.getByTestId("question-card")).getByRole("textbox");
    fireEvent.change(field, { target: { value: "Atlas" } });
    fireEvent.keyDown(field, { key: "Enter" });
    await waitFor(() => expect(submit).toHaveBeenCalledWith("q1", [{ text: "Atlas" }]));
  });

  it("offers a Send button once own words are typed on a lone single question", async () => {
    const { submit } = draw(questionOf(asking([], [DB])));
    expect(screen.queryByTestId("question-done")).toBeNull();
    fireEvent.change(within(screen.getByTestId("question-card")).getByRole("textbox"), { target: { value: "MySQL" } });
    fireEvent.click(screen.getByTestId("question-done"));
    await waitFor(() => expect(submit).toHaveBeenCalledWith("q1", [{ text: "MySQL" }]));
  });

  it("keeps every multi pick when a store answers one question at a time", async () => {
    const answerQuestion = vi.fn(async () => undefined);
    draw(questionOf(asking([], [FEATURES])), { submitQuestion: undefined, answerQuestion });
    const rows = rowsOf(screen.getByTestId("question-card"));
    fireEvent.click(rows[0]);
    fireEvent.click(rows[2]);
    fireEvent.click(screen.getByTestId("question-done"));
    await waitFor(() =>
      expect(answerQuestion).toHaveBeenCalledWith("q1", 0, { optionIndices: [0, 2], text: undefined }),
    );
  });

  it("offers two named ways out instead of a silent close", async () => {
    const { skip, submit } = draw(questionOf(asking([], [DB])));
    fireEvent.click(screen.getByRole("button", { name: /question options/i }));
    const menu = screen.getByRole("menu");
    expect(within(menu).getAllByRole("menuitem").map((m) => m.textContent)).toEqual([
      expect.stringMatching(/skip this question/i),
      expect.stringMatching(/let ada decide all/i),
    ]);
    fireEvent.click(within(menu).getByRole("menuitem", { name: /let ada decide all/i }));
    await waitFor(() => expect(skip).toHaveBeenCalledWith("q1"));
    expect(submit).not.toHaveBeenCalled();
    // Settled optimistically with the recommendation.
    expect(screen.getByTestId("question-card").textContent).toContain("SQLite");
  });

  it("shows the countdown ring only in the last minute of a live card", () => {
    const { view } = draw(questionOf(asking([], [DB])));
    expect(screen.queryByTestId("question-countdown")).toBeNull();
    view.unmount();
    draw(questionOf(asking([], [DB], { expires_ms: Date.now() + 42_000 })));
    expect(screen.getByTestId("question-countdown").getAttribute("aria-label")).toMatch(/0:4\d/);
    cleanup();
    draw(questionOf(asking([], [DB], { deferred: true, expires_ms: Date.now() + 42_000 })));
    expect(screen.queryByTestId("question-countdown")).toBeNull();
  });

  it("restarts a live card's quiet window while the person works on it", () => {
    const { touch } = draw(questionOf(asking()));
    fireEvent.click(rowsOf(screen.getByTestId("question-card"))[0]);
    fireEvent.click(rowsOf(screen.getByTestId("question-card"))[0]);
    expect(touch).toHaveBeenCalledTimes(1);
    expect(touch).toHaveBeenCalledWith("q1");
  });

  it("keeps picks and the step when the card remounts", async () => {
    const q = questionOf(asking());
    const first = draw(q);
    fireEvent.click(rowsOf(screen.getByTestId("question-card"))[1]);
    await waitFor(() => expect(screen.getByTestId("question-step").textContent).toBe("2 of 2"));
    first.view.unmount();
    draw(q);
    expect(screen.getByTestId("question-step").textContent).toBe("2 of 2");
    fireEvent.click(screen.getByRole("button", { name: /^back$/i }));
    expect(rowsOf(screen.getByTestId("question-card"))[1].querySelector("[data-on]")).not.toBeNull();
  });

  it("collapses a finished series to its answers and pages through them", () => {
    draw(questionOf(asking([
      ev("question_resolved", {
        turn_id: "t1",
        question_id: "q1",
        answers: [
          { answer: "Postgres", option_index: 1, source: "person" },
          { answer: "Laptop", option_index: 0, source: "timeout" },
        ],
      }),
    ])));
    const card = screen.getByTestId("question-card");
    expect(card.getAttribute("data-state")).toBe("person timeout");
    expect(card.textContent).toContain("Postgres");
    expect(card.textContent).toContain("Laptop");
    const summary = within(card).getByRole("button", { name: /show the answers/i });
    fireEvent.click(summary);
    expect(summary.getAttribute("aria-expanded")).toBe("true");
    expect(card.querySelector(".qc-step[data-active] .qc-title")?.textContent).toBe(DB.question);
    fireEvent.click(within(card).getByRole("button", { name: /^next$/i }));
    expect(card.querySelector(".qc-step[data-active] .qc-title")?.textContent).toBe(HOST.question);
    expect(card.textContent).toMatch(/no answer came/i);
  });

  it("reads a dismissed card as muted", () => {
    draw(questionOf(asking([
      ev("question_resolved", { turn_id: "t1", question_id: "q1", answers: [{ answer: "", option_index: null, source: "declined" }] }),
    ], [DB])));
    const card = screen.getByTestId("question-card");
    expect(card.hasAttribute("data-dismissed")).toBe(true);
    expect(card.textContent).toContain("Skipped");
  });

  it("turns a card answered in the chat into the question and the reply", () => {
    draw(questionOf(asking([
      ev("question_resolved", {
        turn_id: "t1",
        question_id: "q1",
        answers: [
          { answer: "Neither, use files", option_index: null, source: "message" },
          { answer: "Laptop", option_index: 0, source: "moved_on" },
        ],
      }),
    ])));
    const card = screen.getByTestId("question-card");
    expect(card.getAttribute("data-state")).toBe("message");
    expect(card.textContent).toContain(DB.question);
    expect(card.querySelector(".qc-reply-bubble")?.textContent).toBe("Neither, use files");
  });
});

describe("answering from the composer", () => {
  function storeWith(events: AgentChatEvent[]) {
    const store = createAgentChatStore("society");
    store.setState({ activeSessionId: "s1", timeline: reduceEvents(EMPTY_TIMELINE, events) });
    return store;
  }

  it("routes a message to the open card and reports whether the turn took it", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ ok: true, consumed: true, question_id: "q1" }), { status: 200 }),
    );
    const store = storeWith(asking([], [DB]));
    await expect(store.getState().answerByMessage!("Postgres please")).resolves.toBe(true);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("/api/agent-chat/sessions/s1/reply-to-question");
    expect(JSON.parse(String((init as RequestInit).body))).toEqual({ text: "Postgres please" });
  });

  it("sends nothing special without an open card, and falls back on a failed route", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const closed = storeWith(asking([ev("turn_finished", { turn_id: "t1", status: "done" })], [DB]));
    await expect(closed.getState().answerByMessage!("hello")).resolves.toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
    fetchMock.mockResolvedValue(new Response("{}", { status: 500 }));
    await expect(storeWith(asking([], [DB])).getState().answerByMessage!("hello")).resolves.toBe(false);
  });

  it("a newer message from the person means no card is open any more", async () => {
    const { openQuestionOf } = await import("./questions/questionModel");
    const open = reduceEvents(EMPTY_TIMELINE, asking([], [DB], { deferred: true }));
    expect(openQuestionOf(open)?.question.questionId).toBe("q1");
    const after = reduceEvents(EMPTY_TIMELINE, [
      ...asking([], [DB], { deferred: true }),
      ev("user_message", { turn_id: "t2", text: "never mind" }),
    ]);
    expect(openQuestionOf(after)).toBeNull();
  });
});

describe("the reviewed submit", () => {
  it("posts the answers and treats a closed card as done", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "no such open question" }), { status: 404 }),
    );
    const store = createAgentChatStore("society");
    store.setState({ activeSessionId: "s1" });
    await act(async () => {
      await store.getState().submitQuestion!("q1", [{ option_index: 1 }, { skip: true }]);
    });
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("/api/agent-chat/sessions/s1/questions/q1/submit");
    expect(JSON.parse(String((init as RequestInit).body))).toEqual({ answers: [{ option_index: 1 }, { skip: true }] });
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ detail: "boom" }), { status: 500 }));
    await expect(store.getState().submitQuestion!("q1", [])).rejects.toThrow("boom");
  });
});
