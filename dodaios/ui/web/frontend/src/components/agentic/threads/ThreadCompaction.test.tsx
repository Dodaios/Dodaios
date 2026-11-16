import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { EMPTY_TIMELINE, reduceEvents, type TurnItem } from "@/components/agentchat/reduce";
import type { AgentChatEvent } from "@/lib/agentChatApi";
import { ThreadTurn } from "./ThreadTimeline";

let seq = 0;
const ev = (kind: string, payload: Record<string, unknown>): AgentChatEvent =>
  ({ seq: ++seq, ts_ms: Date.now(), kind, payload } as AgentChatEvent);
const turnOf = (events: AgentChatEvent[]) =>
  reduceEvents(EMPTY_TIMELINE, events).items.find((item) => item.type === "turn") as TurnItem;

/** A Claude Code turn that ran a command, then compacted its conversation. */
const compacting = () => [
  ev("turn_started", { turn_id: "t1", provider: "claude-cli" }),
  ev("tool_call", { turn_id: "t1", call_id: "c1", name: "Bash", input: { command: "pytest -q" } }),
  ev("tool_result", { turn_id: "t1", call_id: "c1", output: "ok", is_error: false }),
  ev("compaction", { turn_id: "t1", call_id: "compact-t1-1", phase: "started" }),
];

const compacted = () => [
  ...compacting(),
  ev("compaction", {
    turn_id: "t1", call_id: "compact-t1-1", phase: "done", trigger: "auto",
    tokens_before: 182_000, tokens_after: 31_000, duration_ms: 14_000,
  }),
];

afterEach(cleanup);

describe("a thread turn whose agent compacts its conversation", () => {
  it("shows a live line while the agent compacts", () => {
    render(<ThreadTurn turn={turnOf(compacting())} />);
    const line = screen.getByTestId("thread-compaction");
    expect(line.dataset.live).toBe("true");
    expect(line.getAttribute("role")).toBe("status");
    expect(line.textContent).toMatch(/^Compacting the conversation·/);
  });

  it("leaves a quiet divider with how far the context shrank", () => {
    render(<ThreadTurn turn={turnOf([...compacted(), ev("assistant_text", { turn_id: "t1", message_id: "m1", text: "Carrying on." })])} />);
    const line = screen.getByTestId("thread-compaction");
    expect(line.dataset.live).toBe("false");
    expect(line.textContent).toContain("Conversation compacted · 182k → 31k tokens");
    expect(line.textContent).toContain("14s");
    expect(line.getAttribute("title")).toMatch(/context window was full/);
  });

  it("is one line per compaction, never a step of the command run before it", () => {
    const turn = turnOf(compacted());
    expect(turn.blocks.filter((block) => block.kind === "tool").map((block) => block.kind === "tool" && block.name))
      .toEqual(["Bash", "context_compaction"]);
    render(<ThreadTurn turn={turn} />);
    expect(screen.getAllByTestId("thread-compaction")).toHaveLength(1);
  });

  it("says so when the compaction failed", () => {
    const turn = turnOf([
      ...compacting(),
      ev("compaction", { turn_id: "t1", call_id: "compact-t1-1", phase: "failed", error: "Too big" }),
    ]);
    render(<ThreadTurn turn={turn} />);
    const line = screen.getByTestId("thread-compaction");
    expect(line.dataset.failed).toBe("true");
    expect(line.textContent).toContain("Could not compact the conversation");
    expect(line.getAttribute("title")).toBe("Too big");
  });

  it("stays in view on a turn that only compacted (/compact), with no missing-answer note", () => {
    const turn = turnOf([
      ev("turn_started", { turn_id: "t9", provider: "claude-cli" }),
      ev("compaction", { turn_id: "t9", call_id: "k9", phase: "started" }),
      ev("compaction", { turn_id: "t9", call_id: "k9", phase: "done", trigger: "manual", tokens_before: 63_600, tokens_after: 17_900 }),
      ev("turn_finished", { turn_id: "t9", status: "done", duration_ms: 15_000 }),
    ]);
    render(<ThreadTurn turn={turn} />);
    expect(screen.getByTestId("thread-compaction").textContent).toContain("63.6k → 17.9k tokens");
    expect(screen.queryByTestId("thread-worked-for")).toBeNull();
    expect(screen.getByTestId("thread-turn-closing").textContent).not.toMatch(/without an answer/i);
  });

  it("folds with the work once the turn is finished", () => {
    const turn = turnOf([
      ...compacted(),
      ev("assistant_text", { turn_id: "t1", message_id: "m1", text: "All tests pass." }),
      ev("turn_finished", { turn_id: "t1", status: "done", duration_ms: 60_000 }),
    ]);
    render(<ThreadTurn turn={turn} />);
    expect(screen.queryByTestId("thread-compaction")).toBeNull();
    expect(screen.getByText("All tests pass.")).toBeTruthy();
  });
});
