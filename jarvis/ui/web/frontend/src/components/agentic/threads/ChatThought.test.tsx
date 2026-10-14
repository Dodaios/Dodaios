import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReasoningBlock, TurnBlock, TurnItem, TurnStatus } from "@/components/agentchat/reduce";
import { ThreadTimeline } from "./ThreadTimeline";

function turn(blocks: TurnBlock[], status: TurnStatus = "done"): TurnItem {
  return {
    type: "turn", id: "t1", provider: "fake", model: "", effort: "", runner: "api", status, blocks,
    startedMs: Date.now(), durationMs: status === "running" ? null : 9000, usage: null, liveUsage: null, costUsd: null, error: null,
  };
}

function thought(id: string, text: string, over: Partial<ReasoningBlock> = {}): ReasoningBlock {
  return { kind: "reasoning", id, text, durationMs: 2000, live: false, startedMs: Date.now(), ...over };
}

const answer: TurnBlock = { kind: "text", id: "a1", text: "Rayleigh scattering." };
const show = (item: TurnItem) => render(<ThreadTimeline items={[item]} sessionId="s1" bottomInset={0} tone="chat" />);

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("a chat's thinking", () => {
  it("streams the thought under a live Thinking line until the answer begins", () => {
    show(turn([thought("r1", "Short wavelengths scatter more.", { live: true, durationMs: null })], "running"));

    expect(screen.getByRole("status").textContent).toContain("Thinking");
    expect(screen.getByTestId("chat-thought").getAttribute("data-live")).toBe("true");
    expect(screen.getByTestId("chat-thought-stream").textContent).toContain("Short wavelengths scatter more.");
    // One live indicator, not the coding thread's "Working for" line beside it.
    expect(screen.queryByTestId("thread-working")).toBeNull();
  });

  it("says it is thinking before any thought arrives", () => {
    show(turn([], "running"));
    expect(screen.getByRole("status").textContent).toContain("Thinking");
    expect(screen.queryByTestId("chat-thought-stream")).toBeNull();
  });

  it("counts the time while it thinks", () => {
    vi.useFakeTimers();
    const started = Date.now();
    show(turn([thought("r1", "", { live: true, durationMs: null, startedMs: started })], "running"));
    act(() => { vi.advanceTimersByTime(3000); });
    expect(screen.getByRole("status").textContent).toContain("3.0s");
  });

  it("folds into one line once the answer streams, and opens on a click", () => {
    show(turn([thought("r1", "First idea."), thought("r2", "Second idea.", { durationMs: 1500 }), answer]));

    const toggle = screen.getByTestId("chat-thought-toggle");
    // Two blocks read as one thought, timed by the thinking alone.
    expect(toggle.textContent).toBe("Thought for 3.5s");
    expect(screen.queryByText("First idea.")).toBeNull();
    expect(screen.getByText("Rayleigh scattering.")).toBeTruthy();

    fireEvent.click(toggle);
    const body = screen.getByTestId("chat-thought-body").textContent ?? "";
    expect(body).toContain("First idea.");
    expect(body).toContain("Second idea.");
  });

  it("shows nothing for a finished answer that had no thinking", () => {
    show(turn([answer]));
    expect(screen.queryByTestId("chat-thought")).toBeNull();
    expect(screen.queryByTestId("thread-turn-closing")?.textContent).not.toContain("Worked");
  });

  it("keeps a redacted thought as a plain line that does not open", () => {
    show(turn([thought("r1", ""), answer]));
    const toggle = screen.getByTestId("chat-thought-toggle") as HTMLButtonElement;
    expect(toggle.textContent).toBe("Thought for 2.0s");
    expect(toggle.disabled).toBe(true);
  });
});
