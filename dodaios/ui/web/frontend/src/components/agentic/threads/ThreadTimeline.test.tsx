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
  it("folds a finished turn's work behind one line and opens it to one counted line per stretch", () => {
    show(turn([thought("r1", "**Checking the build**"), tool("c1", "npm run build"), tool("c2", "npm test"), { kind: "text", id: "n1", text: "All green." }]));
    // A finished turn folds its work behind one "Worked for" line; the answer stays.
    expect(screen.getByText("All green.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^Ran 2 commands/ })).toBeNull();
    fireEvent.click(screen.getByTestId("thread-worked-for"));
    // The thought and its calls are ONE closed line that counts what ran.
    const header = screen.getByRole("button", { name: /^Ran 2 commands/ });
    expect(screen.queryByTestId("thread-thought")).toBeNull();
    expect(screen.queryByText("npm test")).toBeNull();
    fireEvent.click(header);
    expect(screen.getByTestId("thread-thought").textContent).toContain("Checking the build");
    expect(screen.getByText("npm run build")).toBeTruthy();
    expect(screen.getByText("npm test")).toBeTruthy();
    expect(screen.getByText("All green.")).toBeTruthy();
  });

  it("keeps the running stretch closed and opens it to a card of every step", () => {
    show(turn([tool("c1", "npm run build"), tool("c2", "npm test", { output: null, durationMs: null })], "running"));
    // Never open by itself.
    const line = screen.getByRole("button", { name: /steps so far/ });
    expect(line.getAttribute("aria-expanded")).toBe("false");
    expect(line.textContent).toContain("Ran 2 commands");
    expect(screen.queryByTestId("thread-steps")).toBeNull();
    expect(screen.queryByText("npm run build")).toBeNull();
    fireEvent.click(line);
    // One row per step; a command says what it was, then the line itself.
    const card = screen.getByTestId("thread-steps");
    expect(card.children).toHaveLength(2);
    expect(card.textContent).toContain("Ran a command");
    expect(screen.getByText("npm run build")).toBeTruthy();
    expect(screen.getByText("npm test")).toBeTruthy();
    expect(screen.getByTestId("thread-working").textContent).toMatch(/^Working for /);
  });

  it("keeps thoughts out of the thread, except the one the running turn is having", () => {
    show(turn([
      thought("r1", "Checking the workflow."),
      tool("c1", "gh run list"),
      thought("r2", "The gate never ran."),
      thought("r2b", "The gate never ran."),
      { kind: "text", id: "n1", text: "The failure hits several pull requests." },
      tool("c2", "gh pr list"),
      thought("r3", "Nobody is on it.\n\nI will look at main.", true),
    ], "running"));
    // A stretch the agent has spoken after: one closed line, no thought in the thread.
    const first = screen.getAllByRole("button", { name: /^Ran a command/ })[0];
    expect(first.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText("Checking the workflow.")).toBeNull();
    expect(screen.queryByText("The gate never ran.")).toBeNull();
    // The stretch the turn is in: closed, with the newest thought under its line.
    expect(screen.getByRole("button", { name: /steps so far/ }).getAttribute("aria-expanded")).toBe("false");
    expect(screen.getByTestId("thread-thought-live").textContent).toBe("Nobody is on it. I will look at main.");
    // Opened, the first stretch tells each thought once, as a row.
    fireEvent.click(first);
    const rows = screen.getAllByTestId("thread-thought").map((row) => row.textContent);
    expect(rows.filter((text) => text?.includes("The gate never ran."))).toHaveLength(1);
    expect(rows.some((text) => text?.includes("Checking the workflow."))).toBe(true);
  });

  it("opens a thought of its own to its whole text with one click", () => {
    show(turn([
      { kind: "text", id: "pre", text: "Looking into it." },
      thought("r1", "Reading the config. It has three sections.\n\nNow the router."),
      { kind: "text", id: "a", text: "Done." },
      tool("c9", "ls"),
    ], "running"));
    const line = screen.getByRole("button", { name: /^Thought/ });
    expect(screen.queryByText("Now the router.")).toBeNull();
    fireEvent.click(line);
    expect(screen.getByText("Now the router.")).toBeTruthy();
  });

  it("names a command by the agent's own words for it", () => {
    const said = (id: string, command: string, description: string) => tool(id, command, { input: { command, description } });
    show(turn([
      said("c1", "grep -n ']\(\./' README.md", "Show the lines with relative links"),
      { kind: "text", id: "n1", text: "Seven links are relative." },
      said("c2", "sed -i 's/a/b/' README.md", "Make links absolute"),
      tool("c3", "git push"),
    ], "running"));
    // A lone command's line is its purpose; the command is behind its row.
    const lone = screen.getByRole("button", { name: /^Show the lines with relative links/ });
    expect(screen.queryByText(/grep -n/)).toBeNull();
    fireEvent.click(lone);
    fireEvent.click(screen.getByTestId("thread-steps").querySelector("button")!);
    expect(screen.getByText(/grep -n/)).toBeTruthy();
    // In a card, a described command reads by its purpose, an undescribed one by its line.
    fireEvent.click(screen.getByRole("button", { name: /steps so far/ }));
    const card = screen.getAllByTestId("thread-steps")[1];
    expect(card.textContent).toContain("Make links absolute");
    expect(card.textContent).not.toContain("sed -i");
    expect(card.textContent).toContain("git push");
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
    fireEvent.click(screen.getByRole("button", { name: /^Ran a command/ }));
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
