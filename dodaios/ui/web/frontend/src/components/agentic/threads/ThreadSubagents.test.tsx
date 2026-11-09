import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SubagentState, ToolBlock, TurnBlock, TurnItem, TurnStatus } from "@/components/agentchat/reduce";
import { ThreadTimeline } from "./ThreadTimeline";
import { OpenSubagent, SubagentDock, SubagentHeader } from "./ThreadSubagents";
import { listSubagents } from "./subagents";

const sub = (over: Partial<SubagentState> = {}): SubagentState => ({
  description: "Explore the auth code", agentType: "Explore", prompt: "Find where tokens are checked.", background: true,
  threadId: "", status: "running", summary: "", activity: "Reading auth.py", lastTool: "Read", tokens: 12400,
  toolUses: 3, durationMs: null, startedMs: Date.now(), finishedMs: null, blocks: [], ...over,
});

const spawn = (id: string, over: Partial<SubagentState> = {}): ToolBlock => ({
  kind: "tool", callId: id, name: "Agent", input: { description: "x" }, output: "Async agent launched successfully.",
  isError: false, durationMs: 10, approval: null, startedMs: 1, subagent: sub(over),
});

function turn(blocks: TurnBlock[], status: TurnStatus = "running"): TurnItem {
  return {
    type: "turn", id: "t1", provider: "claude-cli", model: "", effort: "", runner: "", status, blocks,
    startedMs: Date.now(), durationMs: status === "running" ? null : 5000, usage: null, liveUsage: null, costUsd: null, error: null,
  };
}

afterEach(cleanup);

describe("thread sub-agents", () => {
  it("shows a spawned sub-agent as a card that opens its conversation", () => {
    const open = vi.fn();
    render(<OpenSubagent.Provider value={open}>
      <ThreadTimeline items={[turn([spawn("a1")])]} sessionId="s1" bottomInset={0} />
    </OpenSubagent.Provider>);
    const card = screen.getByTestId("thread-subagent-card");
    expect(card.textContent).toContain("Explore the auth code");
    expect(card.textContent).toContain("Reading auth.py");
    expect(card.textContent).toContain("3 tools");
    expect(card.textContent).toContain("12.4k tokens");
    expect(screen.getByTestId("thread-working").textContent).toContain("1 sub-agent working");
    fireEvent.click(card);
    expect(open).toHaveBeenCalledWith("a1");
  });

  it("keeps a finished turn's sub-agents in view under its folded work", () => {
    render(<ThreadTimeline items={[turn([
      { kind: "tool", callId: "c0", name: "Bash", input: { command: "ls" }, output: "ok", isError: false, durationMs: 5, approval: null, startedMs: 1 },
      spawn("a1", { status: "done", summary: "Tokens are checked in auth.py." }),
      { kind: "text", id: "m1", text: "Done." },
    ], "done")]} sessionId="s1" bottomInset={0} />);
    expect(screen.getByTestId("thread-worked-for")).toBeTruthy();
    const card = screen.getByTestId("thread-subagent-card");
    expect(card.getAttribute("data-status")).toBe("done");
    expect(card.textContent).toContain("Tokens are checked in auth.py.");
  });

  it("draws several sub-agents spawned together as one group with a line each", () => {
    const open = vi.fn();
    render(<OpenSubagent.Provider value={open}>
      <ThreadTimeline items={[turn([spawn("a1"), spawn("a2", { description: "Write tests", status: "done", summary: "Added 4 tests." }), spawn("a3", { description: "Check docs" })])]} sessionId="s1" bottomInset={0} />
    </OpenSubagent.Provider>);
    expect(screen.queryByTestId("thread-subagent-card")).toBeNull();
    expect(screen.getAllByTestId("thread-subagent-group")).toHaveLength(1);
    expect(screen.getByTestId("thread-subagent-group-count").textContent).toBe("3 sub-agents · 2 working · 1 done");
    const rows = screen.getAllByTestId("thread-subagent-row");
    expect(rows).toHaveLength(3);
    expect(rows[1].textContent).toContain("Added 4 tests.");
    fireEvent.click(rows[1]);
    expect(open).toHaveBeenCalledWith("a2");
  });

  it("folds a finished group to its header and shows the first lines of a long one", () => {
    const blocks = Array.from({ length: 9 }, (_, i) => spawn(`a${i}`, { description: `Agent ${i}`, status: "done", summary: "ok" }));
    render(<ThreadTimeline items={[turn([...blocks, { kind: "text", id: "m1", text: "Done." }], "done")]} sessionId="s1" bottomInset={0} />);
    expect(screen.queryByTestId("thread-subagent-group-rows")).toBeNull();
    fireEvent.click(screen.getByTestId("thread-subagent-group-toggle"));
    expect(screen.getAllByTestId("thread-subagent-row")).toHaveLength(5);
    fireEvent.click(screen.getByTestId("thread-subagent-show-all"));
    expect(screen.getAllByTestId("thread-subagent-row")).toHaveLength(9);
  });

  it("keeps working sub-agents in a dock above the composer and leads back to the main thread", () => {
    const entries = listSubagents([turn([spawn("a1"), spawn("a2", { description: "Write tests", status: "done" })])]);
    const onOpen = vi.fn();
    const { rerender } = render(<SubagentDock entries={entries} openId={null} onOpen={onOpen} />);
    expect(screen.getByTestId("thread-subagent-count").textContent).toBe("2 sub-agents · 1 working · 1 done");
    expect(screen.queryByTestId("thread-subagent-dock-list")).toBeNull();
    fireEvent.click(screen.getByTestId("thread-subagent-dock-toggle"));
    const rows = screen.getAllByTestId("thread-subagent-row");
    fireEvent.click(rows[0]);
    expect(onOpen).toHaveBeenCalledWith("a1");
    rerender(<SubagentDock entries={entries} openId="a2" onOpen={onOpen} />);
    expect(screen.getAllByTestId("thread-subagent-row")[1].getAttribute("aria-current")).toBe("true");
    fireEvent.click(screen.getByTestId("thread-subagent-main"));
    expect(onOpen).toHaveBeenCalledWith(null);
  });

  it("counts only the batch still working in the dock, not earlier turns' agents", () => {
    const earlier = { ...turn([spawn("old", { status: "done" })], "done"), id: "t0" };
    const entries = listSubagents([earlier, turn([spawn("a1"), spawn("a2")])]);
    render(<SubagentDock entries={entries} openId={null} onOpen={vi.fn()} />);
    expect(screen.getByTestId("thread-subagent-count").textContent).toBe("2 sub-agents · 2 working");
  });

  it("hides the dock once every sub-agent has ended and none is open", () => {
    const entries = listSubagents([turn([spawn("a1", { status: "done" })], "done")]);
    render(<SubagentDock entries={entries} openId={null} onOpen={vi.fn()} />);
    expect(screen.queryByTestId("thread-subagent-dock")).toBeNull();
  });

  it("opens with the task it was given and a way back", () => {
    const [entry] = listSubagents([turn([spawn("a1")])]);
    const onOpen = vi.fn();
    render(<SubagentHeader entry={entry} path={[entry]} onOpen={onOpen} />);
    expect(screen.getByRole("region", { name: "Task" }).textContent).toContain("Find where tokens are checked.");
    fireEvent.click(screen.getByTestId("thread-subagent-back"));
    expect(onOpen).toHaveBeenCalledWith(null);
  });

  it("says so when the CLI reports only the task and the answer", () => {
    const block: ToolBlock = { kind: "tool", callId: "c1", name: "task", input: { description: "Review", prompt: "Review it" }, output: "Fine.", isError: false, durationMs: 5, approval: null, startedMs: 1 };
    const [entry] = listSubagents([turn([block], "done")]);
    render(<SubagentHeader entry={entry} path={[entry]} onOpen={() => {}} />);
    expect(screen.getByTestId("thread-subagent-unstreamed")).toBeTruthy();
  });
});
