import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SubagentRow } from "@/store/threadSubagents";
import { ThreadTreeSubagents, visibleSubagentRows } from "./ThreadTreeSubagents";

const row = (id: string, over: Partial<SubagentRow> = {}): SubagentRow => ({
  id, parentId: null, depth: 0, title: `Agent ${id}`, agentType: "", status: "done", waiting: false, ...over,
});

afterEach(cleanup);

describe("sidebar sub-agent rows", () => {
  it("shows a short list whole", () => {
    const rows = Array.from({ length: 7 }, (_, index) => row(`a${index}`));
    expect(visibleSubagentRows(rows, null, false)).toHaveLength(7);
  });

  it("folds a long list but keeps working, waiting and open sub-agents in view", () => {
    const rows = Array.from({ length: 12 }, (_, index) => row(`a${index}`));
    rows[9] = row("a9", { status: "running" });
    rows[10] = row("a10", { status: "running", waiting: true });
    const shown = visibleSubagentRows(rows, "a11", false).map((entry) => entry.id);
    expect(shown).toEqual(["a0", "a1", "a2", "a3", "a4", "a5", "a9", "a10", "a11"]);
  });

  it("opens a sub-agent on click and unfolds a long list on request", () => {
    const rows = Array.from({ length: 10 }, (_, index) => row(`a${index}`));
    const onOpen = vi.fn();
    render(<ThreadTreeSubagents rows={rows} openId={null} threadTitle="Fix login" onOpen={onOpen} />);
    expect(screen.getAllByTestId("thread-tree-subagent")).toHaveLength(6);
    fireEvent.click(screen.getByRole("button", { name: /4 more/ }));
    expect(screen.getAllByTestId("thread-tree-subagent")).toHaveLength(10);
    fireEvent.click(screen.getByText("Agent a7"));
    expect(onOpen).toHaveBeenCalledWith("a7");
  });
});
