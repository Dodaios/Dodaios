import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { AgentTimeline } from "./AgentTimeline";
import { LeadReply, replyBlocks, splitReply } from "./LeadReply";
import { EMPTY_TIMELINE, reduceEvents } from "./reduce";
import type { AgentChatEvent } from "@/lib/agentChatApi";

afterEach(cleanup);

describe("a reply as the message it is", () => {
  it("keeps a short answer in one message, however many paragraphs it has", () => {
    // The complaint this guards (maintainer, 2026-11-12): every paragraph was
    // a bubble of its own, so one answer read as three or four messages.
    const text = "The agent is set up.\n\nOne problem: X is signed out.\n\nTell me when it is back.";
    expect(splitReply(text)).toEqual([{ text, note: false }]);
  });

  it("keeps a list, a quote and a code block inside the message that holds them", () => {
    const text = "Three things:\n\n- access to X\n- a browser\n\n```bash\nrun it\n\nnow\n```\n\nShall I go on?";
    expect(splitReply(text)).toEqual([{ text, note: false }]);
  });

  it("never splits inside a code fence, even one that is still being written", () => {
    expect(replyBlocks("Look:\n\n```ts\nconst a = 1;\n\nconst b = 2;")).toEqual([
      { kind: "para", text: "Look:" },
      { kind: "code", text: "```ts\nconst a = 1;\n\nconst b = 2;" },
    ]);
  });

  it("keeps a document whole: headings, tables, reference links, many paragraphs, long text", () => {
    const whole = (text: string) => expect(splitReply(text)).toEqual([{ text, note: true }]);
    whole("## Plan\n\nFirst this.\n\nThen that.");
    whole("The week:\n\n| Day | Topic |\n|---|---|\n| Mon | Launch |");
    whole("See [the docs][1].\n\n[1]: https://example.com");
    whole(["one", "two", "three", "four", "five", "six"].join("\n\n"));
    whole(`${"word ".repeat(200).trim()}\n\n${"word ".repeat(120).trim()}`);
  });

  it("draws nothing for an empty reply", () => {
    expect(splitReply("  \n\n ")).toEqual([]);
    const { container } = render(<LeadReply text="   " />);
    expect(container.firstChild).toBeNull();
  });

  it("draws the message as one bubble, and eases it in only while the reply is being written", () => {
    const { rerender } = render(<LeadReply text={"Hello.\n\nHow can I **help**?"} live />);
    const reply = screen.getByTestId("agent-text");
    expect(reply.hasAttribute("data-live")).toBe(true);
    const bubble = within(reply).getByTestId("lead-bubble");
    expect(bubble.querySelectorAll("p")).toHaveLength(2);
    expect(bubble.textContent).toContain("Hello.");
    expect(bubble.querySelector("strong")?.textContent).toBe("help");
    rerender(<LeadReply text={"Hello.\n\nHow can I **help**?"} />);
    expect(screen.getByTestId("agent-text").hasAttribute("data-live")).toBe(false);
    rerender(<LeadReply text={"# Report\n\nAll good."} />);
    expect(screen.getByTestId("lead-bubble").hasAttribute("data-note")).toBe(true);
  });
});

describe("the front page's conversation look", () => {
  let seq = 0;
  const ev = (kind: string, payload: Record<string, unknown>, tsMs = 1000): AgentChatEvent =>
    ({ seq: ++seq, ts_ms: tsMs, kind, payload }) as AgentChatEvent;
  const draw = (events: AgentChatEvent[]) => render(
    <AgentTimeline items={reduceEvents(EMPTY_TIMELINE, events).items} assistantName="Dodaios" providerLabel={(id) => id}
      onDecide={() => undefined} bubbles traceLook="rail" traceCompanion />,
  );
  const answered = (turn: string, text: string) => [
    ev("user_message", { text: `question ${turn}` }),
    ev("turn_started", { turn_id: turn, provider: "openai", model: "", effort: "", runner: "api" }),
    ev("tool_call", { turn_id: turn, call_id: `${turn}-c`, name: "mcp__dodaios__x_read_profile", input: {} }),
    ev("tool_result", { turn_id: turn, call_id: `${turn}-c`, output: "Tool failed: x: HTTP 401; reconnect in Plugins", is_error: true }),
    ev("assistant_text", { turn_id: turn, message_id: `${turn}-m`, text }),
    ev("turn_finished", { turn_id: turn, status: "done", duration_ms: 93_000, usage: { input_tokens: 2, output_tokens: 5000 } }),
  ];

  it("writes the answer as messages, with nothing red and no state line between question and answer", () => {
    // The complaint this guards (maintainer, 2026-11-10): the one
    // conversation read like a log, with red tool output above the answer, a
    // red warning under it and "Done 1m 33s · 5k tokens" as its last line.
    const { container } = draw(answered("t1", "The agent is ready.\n\nX is signed out, please reconnect it."));
    const turn = screen.getByTestId("agent-turn");
    expect(turn.getAttribute("data-look")).toBe("lead");
    // One answer is one message, its two paragraphs inside it.
    const bubble = within(turn).getByTestId("lead-bubble");
    expect(Array.from(bubble.querySelectorAll("p")).map((p) => p.textContent)).toEqual([
      "The agent is ready.",
      "X is signed out, please reconnect it.",
    ]);
    expect(container.querySelector(".text-destructive")).toBeNull();
    expect(turn.textContent).not.toContain("HTTP 401");
    expect(screen.queryByTestId("tool-failure-warning")).toBeNull();
    // Nothing counts the turn under its answer (maintainer, 2026-11-13):
    // no failed step, no number of steps, no time and no usage.
    expect(within(turn).queryByTestId("trace-failed-count")).toBeNull();
    expect(within(turn).getByRole("status").className).toBe("sr-only");
    expect(within(turn).queryByRole("button")).toBeNull();
    expect(turn.textContent).not.toMatch(/did not work|1m 33s|5k|\dsteps?/);
  });

  it("stands the assistant's pet beside the newest turn only, at work while the turn runs", () => {
    draw([
      ...answered("t1", "First answer."),
      ev("user_message", { text: "and now?" }),
      ev("turn_started", { turn_id: "t2", provider: "openai", model: "", effort: "", runner: "api" }),
      ev("tool_call", { turn_id: "t2", call_id: "c2", name: "exec_command", input: { command: "ls" } }),
    ]);
    const [older, newest] = screen.getAllByTestId("agent-turn");
    expect(within(older).queryByTestId("lead-face")).toBeNull();
    expect(within(newest).getByTestId("lead-face").getAttribute("data-pet")).toBe("working");
    // The pet is not also drawn on the trace's state line.
    expect(newest.querySelector("[data-trace-pet]")).toBeNull();
    expect(within(newest).getByRole("status").textContent).toContain("Working");
  });

  it("rests the pet once the turn has answered, and waits with a turn that waits for the person", () => {
    const { unmount } = draw(answered("t1", "Done with it."));
    expect(screen.getByTestId("lead-face").getAttribute("data-pet")).toBe("idle");
    unmount();
    draw([
      ev("user_message", { text: "delete it" }),
      ev("turn_started", { turn_id: "t3", provider: "openai", model: "", effort: "", runner: "api" }),
      ev("approval_required", { turn_id: "t3", approval_id: "a1", call_id: "c3", name: "RunCommand", input: { command: "rm x" }, summary: "rm x" }),
    ]);
    expect(screen.getByTestId("lead-face").getAttribute("data-pet")).toBe("idle");
    expect(screen.getByTestId("thread-approval")).toBeTruthy();
  });

  it("shows no dots while the turn only waits for an agent it sent out, and types again once the agent is back", () => {
    // The complaint this guards (maintainer, 2026-11-12): the assistant had
    // said the agent was running, and the three dots stood under that message
    // for the minutes the agent worked, as if another message were being written.
    const sentOut = [
      ev("user_message", { text: "fix the notebooks" }),
      ev("turn_started", { turn_id: "t1", provider: "openai", model: "", effort: "", runner: "api" }),
      ev("assistant_text", { turn_id: "t1", message_id: "m1", text: "The agent is running. I'll come back once it reports." }),
      ev("reasoning", { turn_id: "t1", text: "Waiting for agents (1): Notebooks stay empty.\n" }),
    ];
    // Until the turn says that it waits, a thought after a message is typing.
    const { unmount } = draw(sentOut);
    expect(screen.getByTestId("typing-indicator")).toBeTruthy();
    unmount();
    const waits = [...sentOut, ev("background_wait", { turn_id: "t1", tasks: ["Notebooks stay empty"] })];
    const waiting = draw(waits);
    expect(screen.getByTestId("agent-turn").getAttribute("data-status")).toBe("running");
    expect(screen.queryByTestId("typing-indicator")).toBeNull();
    expect(screen.getByTestId("lead-bubble").textContent).toContain("The agent is running.");
    // The pet rests beside the last message instead of playing its working row.
    expect(screen.getByTestId("lead-face").getAttribute("data-pet")).toBe("idle");
    waiting.unmount();
    // The agent reported: the assistant works on its answer again.
    draw([
      ...waits,
      ev("background_wait", { turn_id: "t1", tasks: [] }),
      ev("reasoning", { turn_id: "t1", text: "Agent replies received: Notebooks stay empty (completed)" }),
    ]);
    expect(screen.getByTestId("typing-indicator")).toBeTruthy();
    expect(screen.getByTestId("lead-face").getAttribute("data-pet")).toBe("working");
  });

  it("colours the two sides like a messenger: grey for the assistant, the signal hue for the person", () => {
    render(<AgentTimeline items={reduceEvents(EMPTY_TIMELINE, [
      ...answered("t1", "One.\n\nTwo."),
      ...answered("t2", "## Plan\n\nA document."),
    ]).items} assistantName="Dodaios" providerLabel={(id) => id} onDecide={() => undefined} bubbles />);
    const own = screen.getAllByTestId("agent-message-user")[0].firstElementChild!;
    expect(own.className).toContain("jarvis-chat-out");
    expect(own.className).not.toContain("jarvis-user-bubble");
    const [first, note] = screen.getAllByTestId("lead-bubble");
    expect(first.className).toContain("jarvis-chat-in");
    expect(first.className).not.toContain("border");
    // A document-like reply stays a card with an edge.
    expect(note.hasAttribute("data-note")).toBe(true);
    expect(note.className).toContain("bg-card");
    expect(note.className).not.toContain("jarvis-chat-in");
  });

  it("shows the assistant typing under the person's message while its turn is on the way", () => {
    const sent = reduceEvents(EMPTY_TIMELINE, answered("t1", "One.")).items;
    const { rerender } = render(<AgentTimeline items={sent} assistantName="Dodaios" providerLabel={(id) => id}
      onDecide={() => undefined} bubbles traceCompanion awaiting />);
    const waiting = screen.getByTestId("agent-turn-awaiting");
    expect(within(waiting).getByTestId("typing-indicator").className).toContain("jarvis-chat-in");
    // The pet stands beside the dots, not beside the turn before them.
    expect(screen.getAllByTestId("lead-face")).toHaveLength(1);
    expect(within(waiting).getByTestId("lead-face")).toBeTruthy();
    rerender(<AgentTimeline items={sent} assistantName="Dodaios" providerLabel={(id) => id}
      onDecide={() => undefined} bubbles traceCompanion />);
    expect(screen.queryByTestId("agent-turn-awaiting")).toBeNull();
    // The labelled document look never shows it.
    rerender(<AgentTimeline items={sent} assistantName="Dodaios" providerLabel={(id) => id} onDecide={() => undefined} awaiting />);
    expect(screen.queryByTestId("typing-indicator")).toBeNull();
  });

  it("keeps the labelled document look where the conversation look is not asked for", () => {
    render(<AgentTimeline items={reduceEvents(EMPTY_TIMELINE, answered("t1", "One.\n\nTwo.")).items} assistantName="Dodaios"
      providerLabel={(id) => id} onDecide={() => undefined} />);
    const turn = screen.getByTestId("agent-turn");
    expect(turn.hasAttribute("data-look")).toBe(false);
    expect(within(turn).queryByTestId("lead-bubble")).toBeNull();
    expect(within(turn).getByTestId("agent-text").querySelectorAll("p")).toHaveLength(2);
  });
});
