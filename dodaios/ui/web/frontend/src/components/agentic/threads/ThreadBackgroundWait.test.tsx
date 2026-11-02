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

/** A Claude Code turn whose agent wrote its answer, then waited for two background shells. */
const waiting = () => [
  ev("turn_started", { turn_id: "t1", provider: "claude-cli" }),
  ev("assistant_text", { turn_id: "t1", message_id: "m1", text: "Tests and push run in the background." }),
  ev("background_wait", { turn_id: "t1", tasks: ["Run the full test suite", "git push"] }),
];

afterEach(cleanup);

describe("a thread turn that waits for its background tasks", () => {
  it("says it waits, and on what, instead of plain Working", () => {
    render(<ThreadTurn turn={turnOf(waiting())} />);
    const line = screen.getByTestId("thread-working").textContent ?? "";
    expect(line).toMatch(/^Waiting for 2 background tasks · /);
    expect(line).toContain("Run the full test suite, git push");
    expect(line).not.toContain("Working for");
  });

  it("goes back to Working once the agent picks up again", () => {
    const turn = turnOf([...waiting(), ev("background_wait", { turn_id: "t1", tasks: [] })]);
    render(<ThreadTurn turn={turn} />);
    expect(screen.queryByTestId("thread-waiting-background")).toBeNull();
    expect(screen.getByTestId("thread-working").textContent).toMatch(/^Working for /);
  });

  it("shows no wait on a finished turn", () => {
    const turn = turnOf([...waiting(), ev("turn_finished", { turn_id: "t1", status: "done", duration_ms: 9000 })]);
    render(<ThreadTurn turn={turn} />);
    expect(screen.queryByTestId("thread-working")).toBeNull();
    expect(screen.queryByTestId("thread-waiting-background")).toBeNull();
  });
});
