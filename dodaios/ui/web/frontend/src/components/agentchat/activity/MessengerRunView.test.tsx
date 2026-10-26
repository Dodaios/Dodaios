import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MessengerTurn } from "../MessengerTurn";
import type { ReasoningBlock, TextBlock, ToolBlock, TurnBlock, TurnItem } from "../reduce";
import { TIMER_AFTER_MS } from "./ActivityLine";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

function turn(blocks: TurnBlock[], status: TurnItem["status"] = "running", startedMs = Date.now()): TurnItem {
  return {
    type: "turn", id: "t1", provider: "p", model: "", effort: "", runner: "api", status, blocks,
    startedMs, durationMs: status === "running" ? null : 125_000, usage: null, liveUsage: null, costUsd: null, error: null,
  };
}
const text = (value: string, id = "x1"): TextBlock => ({ kind: "text", id, text: value });
const thought = (value: string): ReasoningBlock => ({ kind: "reasoning", id: "r1", text: value, durationMs: 800, live: false, startedMs: 1 });
function call(name: string, input: unknown, output: string | null = null, extra: Partial<ToolBlock> = {}): ToolBlock {
  return { kind: "tool", callId: `c-${name}`, name, input, output, isError: false, durationMs: null, approval: null, startedMs: 1, ...extra };
}

function draw(item: TurnItem, extra: Partial<Parameters<typeof MessengerTurn>[0]> = {}) {
  return render(<MessengerTurn turn={item} avatar={<span data-testid="face" />} color="#7ab6ef" onDecide={() => undefined} {...extra} />);
}

describe("activity line in the chat", () => {
  it("says what the running step is, in words", () => {
    draw(turn([call("Edit", { file_path: "src/app.ts", old_string: "a", new_string: "b" })]));
    expect(screen.getByTestId("activity-phrase").textContent).toBe("Editing app.ts");
    expect(screen.getByTestId("messenger-presence").dataset.presence).toBe("writing");
    // The stage does not announce each step; the transcript's announcer does.
    expect(screen.getByTestId("messenger-presence").getAttribute("role")).toBeNull();
  });

  it("names the teammate an agent writes to, with its face", () => {
    draw(turn([call("society_message_agent", { target: "a7", text: "hi" })]), {
      nameOf: (id) => (id === "a7" ? "Scout" : id),
      peerFace: () => <span data-testid="peer-face" />,
    });
    expect(screen.getByTestId("activity-phrase").textContent).toBe("Writing to Scout");
    expect(screen.getByTestId("peer-face")).toBeTruthy();
  });

  it("shows the time only after a minute", () => {
    vi.useFakeTimers();
    vi.setSystemTime(1_000_000);
    draw(turn([], "running", 1_000_000));
    const timer = screen.getByTestId("activity-timer");
    expect(timer.hidden).toBe(true);
    act(() => { vi.advanceTimersByTime(TIMER_AFTER_MS + 5_000); });
    expect(timer.hidden).toBe(false);
    expect(timer.textContent).toBe("· 1 min");
  });

  it("keeps reasoning and tool rows out of the conversation", () => {
    draw(turn([thought("secret plan"), call("Bash", { command: "ls" }, "a.txt"), text("Here you go.")], "done"));
    expect(screen.queryByText("secret plan")).toBeNull();
    expect(screen.queryByText("a.txt")).toBeNull();
    expect(screen.queryByText(/ls/)).toBeNull();
    expect(screen.getAllByTestId("agent-message-bubble")).toHaveLength(1);
  });
});

describe("show work", () => {
  it("sums the turn up in one line that opens the inspector", () => {
    const open = vi.fn();
    draw(turn([
      thought("x"),
      call("Edit", { file_path: "a.ts", old_string: "a", new_string: "b" }, "ok"),
      call("Read", { file_path: "b.ts" }, "ok"),
      text("Done."),
    ], "done"), { onShowWork: open });
    const line = screen.getByTestId("work-disclosure");
    expect(line.textContent).toContain("Worked for 2m 05s");
    expect(line.textContent).toContain("2 steps");
    expect(line.textContent).toContain("1 file");
    expect(line.textContent).toContain("+1");
    expect(line.textContent).toContain("−1");
    fireEvent.click(line);
    expect(open).toHaveBeenCalledTimes(1);
  });

  it("a plain reply has no work line", () => {
    draw(turn([text("Hello.")], "done"), { onShowWork: () => undefined });
    expect(screen.queryByTestId("work-disclosure")).toBeNull();
  });

  it("sits beside the activity line while the turn runs", () => {
    draw(turn([call("Read", { file_path: "b.ts" })]), { onShowWork: () => undefined });
    expect(screen.getByTestId("work-disclosure").textContent).toContain("Working");
    expect(screen.getByTestId("activity-line")).toBeTruthy();
  });
});
