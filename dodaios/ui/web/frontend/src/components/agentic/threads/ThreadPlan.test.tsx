import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { TimelineItem, ToolBlock, TurnBlock, TurnItem, TurnStatus } from "@/components/agentchat/reduce";
import { PLAN_SHOWN } from "./ThreadPlan";
import { ThreadTimeline } from "./ThreadTimeline";

const tool = (id: string, name: string, input: unknown, output: string | null = "ok", over: Partial<ToolBlock> = {}): ToolBlock => ({
  kind: "tool", callId: id, name, input, output, isError: false, durationMs: 300, approval: null, startedMs: 1, ...over,
});
const bash = (id: string, command: string, output: string | null = "ok") => tool(id, "Bash", { command }, output);
const text = (id: string, words: string): TurnBlock => ({ kind: "text", id, text: words });
const thought = (id: string, words: string): TurnBlock => ({ kind: "reasoning", id, text: words, durationMs: 900, live: false, startedMs: 1 });

function turn(blocks: TurnBlock[], status: TurnStatus = "done", id = "t1"): TurnItem {
  return {
    type: "turn", id, provider: "claude-api", model: "", effort: "", runner: "", status, blocks,
    startedMs: Date.now(), durationMs: status === "running" ? null : 5000, usage: null, liveUsage: null, costUsd: null, error: null,
  };
}

const show = (...items: TimelineItem[]) => render(<ThreadTimeline items={items} sessionId="s1" bottomInset={0} />);

const todos = (...rows: [string, string][]) => ({ todos: rows.map(([content, status]) => ({ content, status, activeForm: `Doing ${content}` })) });
const rowsOf = (list: HTMLElement) => [...list.querySelectorAll("li[data-status]")].map((row) => `${row.getAttribute("data-status")}:${row.lastElementChild?.textContent}`);

afterEach(cleanup);

describe("the agent's to-do list in a thread", () => {
  it("draws the list as one card where the agent last touched it, the entry in work turning", () => {
    show(turn([
      tool("p1", "TodoWrite", todos(["Read the repo", "in_progress"], ["Write the drafts", "pending"], ["Open the pull request", "pending"])),
      bash("c1", "git log"),
      bash("c2", "ls"),
      tool("p2", "TodoWrite", todos(["Read the repo", "completed"], ["Write the drafts", "in_progress"], ["Open the pull request", "pending"])),
      bash("c3", "npm test", null),
    ], "running"));
    // One card, with the newest state.
    const card = screen.getByTestId("thread-plan");
    expect(screen.getAllByTestId("thread-plan")).toHaveLength(1);
    expect(rowsOf(card)).toEqual(["completed:Read the repo", "in_progress:Write the drafts", "pending:Open the pull request"]);
    expect(card.querySelector("li[data-status=in_progress] svg")?.getAttribute("class")).toContain("animate-spin");
    expect(within(card).getByRole("list").getAttribute("aria-label")).toBe("To-do list, 1 of 3 done");
    // The work before the card and the work after it are lines of their own; the list is no work.
    const before = screen.getByRole("button", { name: /^Ran 2 commands/ });
    const after = screen.getByRole("button", { name: /steps so far/ });
    expect(before.textContent).not.toMatch(/to-do/i);
    expect(before.compareDocumentPosition(card) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(card.compareDocumentPosition(after) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // The earlier list call is a step of the line before the card: what it did, and the list as it stood.
    fireEvent.click(before);
    const step = screen.getByTestId("thread-plan-step");
    expect(step.textContent).toContain("Made a to-do list with 3 items");
    fireEvent.click(within(step).getByRole("button"));
    expect(rowsOf(step)).toEqual(["in_progress:Read the repo", "pending:Write the drafts", "pending:Open the pull request"]);
    // A list of the past does not turn.
    expect(step.querySelector(".animate-spin")).toBeNull();
  });

  it("names a line by the list change when the agent did nothing else between two things it said", () => {
    show(turn([
      tool("p1", "TodoWrite", todos(["Read the repo", "in_progress"], ["Write the drafts", "pending"])),
      thought("r1", "The repo is small."),
      tool("p2", "TodoWrite", todos(["Read the repo", "completed"], ["Write the drafts", "in_progress"])),
      thought("r2", "Now the drafts."),
      tool("p3", "TodoWrite", todos(["Read the repo", "completed"], ["Write the drafts", "completed"])),
      bash("c1", "git status", null),
    ], "running"));
    expect(screen.getByRole("button", { name: /^Made a to-do list with 2 items/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /^Completed Read the repo, started Write the drafts/ })).toBeTruthy();
    expect(rowsOf(screen.getByTestId("thread-plan"))).toEqual(["completed:Read the repo", "completed:Write the drafts"]);
  });

  it("folds the card into a finished turn's work and stops the ring", () => {
    show(turn([
      tool("p1", "TodoWrite", todos(["Read the repo", "completed"], ["Write the drafts", "in_progress"])),
      bash("c1", "git log"),
      text("n1", "The drafts are half done."),
    ], "cancelled"));
    expect(screen.queryByTestId("thread-plan")).toBeNull();
    expect(screen.getByText("The drafts are half done.")).toBeTruthy();
    fireEvent.click(screen.getByTestId("thread-worked-for"));
    const card = screen.getByTestId("thread-plan");
    expect(rowsOf(card)).toEqual(["completed:Read the repo", "in_progress:Write the drafts"]);
    expect(card.querySelector(".animate-spin")).toBeNull();
  });

  it("keeps the answer in view when the agent ticks its last entry after writing it", () => {
    show(turn([
      tool("p1", "TodoWrite", todos(["Write the report", "in_progress"])),
      bash("c1", "git log"),
      text("n1", "Here is the full report."),
      tool("p2", "TodoWrite", todos(["Write the report", "completed"])),
      text("n2", "Everything on the list is done."),
    ]));
    expect(screen.getByText("Here is the full report.")).toBeTruthy();
    expect(screen.getByText("Everything on the list is done.")).toBeTruthy();
    expect(screen.queryByTestId("thread-plan")).toBeNull();
  });

  it("builds the list from Claude Code's task tools, also across turns", () => {
    show(
      turn([
        tool("k1", "TaskCreate", { subject: "Collect facts", activeForm: "Collecting facts" }, "Task #1 created successfully: Collect facts"),
        tool("k2", "TaskCreate", { subject: "Write draft" }, "Task #2 created successfully: Write draft"),
        tool("u1", "TaskUpdate", { taskId: "1", status: "in_progress" }, "Updated task #1 status"),
        bash("c1", "git log"),
        text("n1", "Facts first."),
      ], "done", "t1"),
      turn([
        tool("u2", "TaskUpdate", { taskId: "1", status: "completed" }, "Updated task #1 status"),
        tool("u3", "TaskUpdate", { taskId: "2", status: "in_progress" }, "Updated task #2 status"),
        tool("l1", "TaskList", {}, "#1 [completed] Collect facts\n#2 [in_progress] Write draft"),
        bash("c2", "npm test", null),
      ], "running", "t2"),
    );
    // The running turn's card knows the tasks the turn before made.
    expect(rowsOf(screen.getByTestId("thread-plan"))).toEqual(["completed:Collect facts", "in_progress:Write draft"]);
    // Reading the list back is no step.
    fireEvent.click(screen.getByRole("button", { name: /steps so far/ }));
    expect(screen.getByTestId("thread-steps").children).toHaveLength(1);
    expect(screen.queryByText(/Task list/i)).toBeNull();
  });

  it("tells a list call that failed like any failed step", () => {
    show(turn([
      tool("p1", "TodoWrite", { todos: "nope" }, "InputValidationError: todos must be an array", { isError: true }),
      bash("c1", "ls", null),
    ], "running"));
    expect(screen.queryByTestId("thread-plan")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /steps so far/ }));
    expect(screen.getByTestId("thread-steps").textContent).toContain("Updated the to-do list");
  });

  it("folds the finished entries of a long list and opens them on a click", () => {
    const many: [string, string][] = Array.from({ length: PLAN_SHOWN + 6 }, (_, index) =>
      [`Entry ${index + 1}`, index < 6 ? "completed" : index === 6 ? "in_progress" : "pending"]);
    show(turn([tool("p1", "TodoWrite", todos(...many)), bash("c1", "ls", null)], "running"));
    const card = screen.getByTestId("thread-plan");
    // Five finished entries fold; the last finished one stays above the entry in work.
    expect(within(card).getByRole("button", { name: "5 done" })).toBeTruthy();
    expect(rowsOf(card)[0]).toBe("completed:Entry 6");
    expect(rowsOf(card)).toHaveLength(PLAN_SHOWN + 1);
    fireEvent.click(within(card).getByRole("button", { name: "5 done" }));
    expect(rowsOf(card)).toHaveLength(PLAN_SHOWN + 6);
    expect(within(card).queryByTestId("thread-plan-more")).toBeNull();
  });
});
