import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { AgentTimeline } from "./AgentTimeline";
import { LeadReply, replyBlocks, splitReply } from "./LeadReply";
import { EMPTY_TIMELINE, reduceEvents } from "./reduce";
import type { AgentChatEvent } from "@/lib/agentChatApi";

afterEach(cleanup);

describe("a reply as the messages it is sent in", () => {
  it("sends each paragraph of a short answer as its own message", () => {
    expect(splitReply("The agent is set up.\n\nOne problem: X is signed out.\n\nTell me when it is back.")).toEqual([
      { text: "The agent is set up.", note: false },
      { text: "One problem: X is signed out.", note: false },
      { text: "Tell me when it is back.", note: false },
    ]);
  });

  it("keeps a list, a quote and a code block with the paragraph that introduces them", () => {
    const parts = splitReply("Three things:\n\n- access to X\n- a browser\n\n```bash\nrun it\n\nnow\n```\n\nShall I go on?");
    expect(parts.map((part) => part.text)).toEqual([
      "Three things:\n\n- access to X\n- a browser\n\n```bash\nrun it\n\nnow\n```",
      "Shall I go on?",
    ]);
    expect(parts.every((part) => !part.note)).toBe(true);
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

  it("draws the messages as bubbles, and eases them in only while the reply is being written", () => {
    const { rerender } = render(<LeadReply text={"Hello.\n\nHow can I **help**?"} live />);
    const reply = screen.getByTestId("agent-text");
    expect(reply.hasAttribute("data-live")).toBe(true);
    const bubbles = within(reply).getAllByTestId("lead-bubble");
    expect(bubbles.map((bubble) => bubble.textContent)).toEqual(["Hello.", "How can I help?"]);
    expect(bubbles[1].querySelector("strong")?.textContent).toBe("help");
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
    expect(within(turn).getAllByTestId("lead-bubble").map((bubble) => bubble.textContent)).toEqual([
      "The agent is ready.",
      "X is signed out, please reconnect it.",
    ]);
    expect(container.querySelector(".text-destructive")).toBeNull();
    expect(turn.textContent).not.toContain("HTTP 401");
    expect(screen.queryByTestId("tool-failure-warning")).toBeNull();
    expect(within(turn).getByTestId("trace-failed-count").textContent).toBe("1 step did not work");
    // Time and usage are there for whoever looks, not as the turn's last line.
    const status = within(turn).getByRole("status");
    expect(status.className).toContain("trace-meta");
    expect(status.textContent).toContain("1m 33s");
    expect(status.textContent).toContain("5k");
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
    expect(screen.getByRole("group", { name: "Approval required" })).toBeTruthy();
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
