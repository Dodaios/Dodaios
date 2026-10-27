import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { retryOf } from "@/components/society/chat/AgentChatPanel";
import { MessengerTurn } from "./MessengerTurn";
import { EMPTY_TIMELINE, reduceEvents } from "./reduce";
import type { TextBlock, TimelineItem, TurnItem } from "./reduce";

afterEach(cleanup);

const REASON = "The ChatGPT subscription could not answer this turn.";

function turn(status: TurnItem["status"], error: string | null, blocks: TurnItem["blocks"] = []): TurnItem {
  return {
    type: "turn", id: "t1", provider: "p", model: "", effort: "", runner: "api", status, blocks,
    startedMs: 1, durationMs: 10, usage: null, liveUsage: null, costUsd: null, error,
  };
}

const user = (text: string, id = "u1"): TimelineItem => ({ type: "user", id, text, tsMs: 1 }) as TimelineItem;
const answer: TextBlock = { kind: "text", id: "a", text: "Here it is." };

function draw(item: TurnItem, onRetry?: () => void) {
  return render(<MessengerTurn turn={item} avatar={<span />} color="#7ab6ef" onDecide={() => undefined} onRetry={onRetry} />);
}

describe("a failed turn", () => {
  it("says why in an error box with a Retry that sends the message again", () => {
    let retried = 0;
    draw(turn("error", REASON), () => { retried += 1; });
    expect(screen.getByTestId("turn-failure-reason").textContent).toBe(REASON);
    expect(screen.queryByText("Finished without an answer")).toBeNull();
    fireEvent.click(screen.getByTestId("turn-retry"));
    expect(retried).toBe(1);
  });

  it("is a failure when a runtime ended silent with an error on record", () => {
    draw(turn("done", REASON));
    expect(screen.getByTestId("turn-failure-reason").textContent).toBe(REASON);
    expect(screen.queryByTestId("turn-retry")).toBeNull();
  });

  it("says the runtime gave no reason rather than nothing", () => {
    draw(turn("error", null));
    expect(screen.getByTestId("turn-failure").textContent).toContain("The agent's runtime reported no reason.");
  });

  it("keeps a quiet line for a turn that simply did not answer", () => {
    draw(turn("done", null));
    expect(screen.queryByTestId("turn-failure")).toBeNull();
  });

  it("keeps the reason of an error event when the end of the turn names none", () => {
    const state = reduceEvents(EMPTY_TIMELINE, [
      { seq: 1, ts_ms: 1, kind: "turn_started", payload: { turn_id: "t1", provider: "p", model: "" } },
      { seq: 2, ts_ms: 2, kind: "error", payload: { turn_id: "t1", message: REASON } },
      { seq: 3, ts_ms: 3, kind: "turn_finished", payload: { turn_id: "t1", status: "done", duration_ms: 2 } },
    ] as never);
    const finished = state.items.find((item) => item.type === "turn") as TurnItem;
    expect(finished.error).toBe(REASON);
  });
});

describe("retryOf", () => {
  it("offers the latest failed turn the message that started it", () => {
    const sent: string[] = [];
    const retry = retryOf([user("Write qa_note.txt"), turn("error", REASON)], (text) => sent.push(text));
    expect(retry?.turnId).toBe("t1");
    retry?.run();
    expect(sent).toEqual(["Write qa_note.txt"]);
  });

  it("offers nothing once the latest turn answered or a new message is in", () => {
    const send = () => undefined;
    expect(retryOf([user("hi"), turn("done", null, [answer])], send)).toBeNull();
    expect(retryOf([user("hi"), turn("error", REASON), user("again", "u2")], send)).toBeNull();
  });
});
