import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { ToolBlock, TurnBlock, TurnItem, TurnStatus } from "@/components/agentchat/reduce";
import { projectPath, ThreadTimeline } from "./ThreadTimeline";

const tool = (id: string, command: string, over: Partial<ToolBlock> = {}): ToolBlock => ({
  kind: "tool", callId: id, name: "Bash", input: { command }, output: "ok", isError: false,
  durationMs: 300, approval: null, startedMs: 1, ...over,
});
const thought = (id: string, text: string, live = false): TurnBlock => ({ kind: "reasoning", id, text, durationMs: live ? null : 4200, live, startedMs: 1 });

function turn(blocks: TurnBlock[], status: TurnStatus = "done"): TurnItem {
  return {
    type: "turn", id: "t1", provider: "claude-api", model: "", effort: "", runner: "", status, blocks,
    startedMs: Date.now(), durationMs: status === "running" ? null : 5000, usage: null, liveUsage: null, costUsd: null, error: null,
  };
}

const show = (item: TurnItem) => render(<ThreadTimeline items={[item]} sessionId="s1" bottomInset={0} />);

afterEach(cleanup);

describe("thread work log", () => {
  it("folds a finished stretch to one named line that opens to its steps", () => {
    show(turn([thought("r1", "**Checking the build**"), tool("c1", "npm run build"), tool("c2", "npm test"), { kind: "text", id: "n1", text: "All green." }]));
    // A finished turn folds its work behind one "Worked for" line; the answer stays.
    expect(screen.getByText("All green.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^Ran commands/ })).toBeNull();
    fireEvent.click(screen.getByTestId("thread-worked-for"));
    // The thought and its calls are ONE line, named by the thought's heading.
    const header = screen.getByRole("button", { name: /^Checking the build/ });
    expect(screen.queryByTestId("thread-thought")).toBeNull();
    expect(screen.queryByText("npm test")).toBeNull();
    fireEvent.click(header);
    expect(screen.getByTestId("thread-thought").textContent).toContain("Checking the build");
    expect(screen.getByText("npm run build")).toBeTruthy();
    expect(screen.getByText("npm test")).toBeTruthy();
    expect(screen.getByText("All green.")).toBeTruthy();
  });

  it("keeps the running stretch closed on the step it is on, and opens to a card of every step", () => {
    show(turn([tool("c1", "npm run build"), tool("c2", "npm test", { output: null, durationMs: null })], "running"));
    // Never open by itself: the closed line reads the step the agent is on.
    const line = screen.getByRole("button", { name: /steps so far/ });
    expect(line.getAttribute("aria-expanded")).toBe("false");
    expect(line.textContent).toContain("npm test");
    expect(screen.queryByTestId("thread-steps")).toBeNull();
    expect(screen.queryByText("npm run build")).toBeNull();
    fireEvent.click(line);
    // One row per step; a command says what it was, then the line itself.
    const card = screen.getByTestId("thread-steps");
    expect(card.children).toHaveLength(2);
    expect(card.textContent).toContain("Ran a command");
    expect(screen.getByText("npm run build")).toBeTruthy();
    expect(screen.getByTestId("thread-working").textContent).toMatch(/^Working for /);
  });

  it("shows a thought as one short line that opens to its full text", () => {
    show(turn([thought("r1", "Reading the config. It has three sections.\n\nNow the router.", true)], "running"));
    const line = screen.getByRole("button", { name: "Reading the config." });
    expect(screen.queryByText("Now the router.")).toBeNull();
    fireEvent.click(line);
    expect(screen.getByText("Now the router.")).toBeTruthy();
  });

  it("reads the thoughts and calls between two things the agent said as one line", () => {
    show(turn([
      thought("r1", "Checking the workflow."),
      tool("c1", "gh run list"),
      thought("r2", "The gate never ran."),
      { kind: "text", id: "n1", text: "The failure hits several pull requests." },
      tool("c2", "gh pr list"),
      tool("c3", "gh pr view 7", { output: null, durationMs: null }),
    ], "running"));
    // The finished stretch is one closed line; its thoughts stay out of the thread.
    const first = screen.getByRole("button", { name: /^gh run list/ });
    expect(first.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText("The gate never ran.")).toBeNull();
    // The stretch the turn is still in stays closed too.
    expect(screen.getByRole("button", { name: /steps so far/ }).getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText("gh pr list")).toBeNull();
    fireEvent.click(first);
    expect(screen.getByText("The gate never ran.")).toBeTruthy();
    expect(screen.getByText("Checking the workflow.")).toBeTruthy();
  });

  it("keeps the answer in view when a thought lands after it", () => {
    show(turn([
      tool("c1", "gh pr view 1191"),
      { kind: "text", id: "pre", text: "Fetching the description." },
      { kind: "text", id: "a", text: "The pull request adds two pets." },
      thought("r1", "Summarizing the pull request.\n\nIt adds two pets."),
    ]));
    expect(screen.getByText("Fetching the description.")).toBeTruthy();
    expect(screen.getByText("The pull request adds two pets.")).toBeTruthy();
    expect(screen.queryByTestId("thread-thought")).toBeNull();
    fireEvent.click(screen.getByTestId("thread-worked-for"));
    fireEvent.click(screen.getByRole("button", { name: /^gh pr view 1191/ }));
    expect(screen.getByTestId("thread-thought").textContent).toContain("Summarizing the pull request.");
  });

  it("folds a preamble that an earlier step separates from the answer", () => {
    show(turn([
      { kind: "text", id: "pre", text: "Fetching the description." },
      tool("c1", "gh pr view 1191"),
      { kind: "text", id: "a", text: "The pull request adds two pets." },
      thought("r1", "Done thinking."),
    ]));
    expect(screen.getByText("The pull request adds two pets.")).toBeTruthy();
    expect(screen.queryByText("Fetching the description.")).toBeNull();
    fireEvent.click(screen.getByTestId("thread-worked-for"));
    expect(screen.getByText("Fetching the description.")).toBeTruthy();
  });

  it("shows wordless live thinking as one Thinking step", () => {
    show(turn([thought("r1", "", true)], "running"));
    expect(screen.getByText("Thinking")).toBeTruthy();
  });
});

describe("changed files card", () => {
  const edit = (id: string, path: string): ToolBlock =>
    tool(id, "", { name: "Edit", input: { file_path: path, old_string: "a", new_string: "b\nc" } });

  it("lists three files and folds the rest behind a count", () => {
    const paths = ["src/a.ts", "src/b.ts", "docs/c.md", "lib/d.py", "e.json"];
    show(turn(paths.map((path, i) => edit(`e${i}`, path))));
    const card = screen.getByTestId("thread-changed-files");
    expect(card.textContent).toContain("5 files changed");
    expect(screen.getByText("a.ts")).toBeTruthy();
    expect(screen.getAllByText("src/").length).toBe(2);
    expect(screen.queryByText("d.py")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Show 2 more files/ }));
    expect(screen.getByText("d.py")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Collapse files/ }));
    expect(screen.queryByText("e.json")).toBeNull();
  });

  it("shows no fold line for three files or fewer", () => {
    show(turn([edit("e1", "a.ts"), edit("e2", "b.ts")]));
    expect(screen.queryByRole("button", { name: /more file/ })).toBeNull();
  });

  it("opens every diff at once from the header", () => {
    show(turn(["a.ts", "b.ts", "c.ts", "d.ts"].map((path, i) => edit(`e${i}`, path))));
    fireEvent.click(screen.getByRole("button", { name: "Show changes" }));
    expect(screen.getByText("d.ts")).toBeTruthy();
    expect(screen.getAllByRole("button", { expanded: true }).length).toBeGreaterThanOrEqual(4);
  });
});

describe("projectPath", () => {
  it("reads a file relative to the thread folder on every OS", () => {
    expect(projectPath("C:\\Repo\\src\\a.ts", "c:\\repo")).toBe("src/a.ts");
    expect(projectPath("/home/me/repo/src/a.ts", "/home/me/repo/")).toBe("src/a.ts");
    expect(projectPath("src/a.ts", "/home/me/repo")).toBe("src/a.ts");
    expect(projectPath("/etc/x/y/z/a.conf", "/home/me/repo")).toBe("…/y/z/a.conf");
  });
});
