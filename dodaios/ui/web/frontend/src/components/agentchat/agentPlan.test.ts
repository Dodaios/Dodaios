import { describe, expect, it } from "vitest";
import { isPlanRead, joinPlanViews, planCallKind, planOps, planViews, planViewsOf, samePlanOps, type PlanView } from "./agentPlan";
import type { TimelineItem, ToolBlock, TurnBlock, TurnItem } from "./reduce";

const call = (callId: string, name: string, input: unknown, output: string | null = "ok", over: Partial<ToolBlock> = {}): ToolBlock => ({
  kind: "tool", callId, name, input, output, isError: false, durationMs: 5, approval: null, startedMs: 1, ...over,
});

function turn(id: string, blocks: TurnBlock[]): TurnItem {
  return {
    type: "turn", id, provider: "claude-api", model: "", effort: "", runner: "", status: "done", blocks,
    startedMs: 1, durationMs: 100, usage: null, liveUsage: null, costUsd: null, error: null,
  };
}

const viewsOf = (...blocks: TurnBlock[]) => planViewsOf([turn("t1", blocks)]);
const texts = (view: PlanView | undefined) => view?.items.map((item) => `${item.status}:${item.text}`);

describe("list calls by name", () => {
  it("knows each CLI's list tool and leaves every other tool alone", () => {
    expect(planCallKind("TodoWrite")).toBe("list");
    expect(planCallKind("update_plan")).toBe("list");
    expect(planCallKind("todowrite")).toBe("list");
    expect(planCallKind("write_todos")).toBe("list");
    expect(planCallKind("TaskCreate")).toBe("create");
    expect(planCallKind("TaskUpdate")).toBe("update");
    expect(planCallKind("TaskList")).toBe("read");
    expect(planCallKind("mcp__dodaios__reminders")).toBeNull();
    // Stopping a background task is no list call.
    expect(planCallKind("TaskStop")).toBeNull();
    expect(planCallKind("Task")).toBeNull();
    expect(planCallKind("Bash")).toBeNull();
    expect(isPlanRead("TaskGet")).toBe(true);
    expect(isPlanRead("TodoWrite")).toBe(false);
  });
});

describe("a whole-list tool", () => {
  // The calls Claude Code 2.1.325 made in a real run (TodoWrite).
  const first = { todos: [
    { content: "Step 1: create a.txt", status: "in_progress", activeForm: "Creating a.txt" },
    { content: "Step 2: create b.txt", status: "pending", activeForm: "Creating b.txt" },
    { content: "Step 3: list the folder", status: "pending", activeForm: "Listing the folder" },
  ] };
  const second = { todos: [
    { content: "Step 1: create a.txt", status: "completed", activeForm: "Creating a.txt" },
    { content: "Step 2: create b.txt", status: "in_progress", activeForm: "Creating b.txt" },
    { content: "Step 3: list the folder", status: "pending", activeForm: "Listing the folder" },
  ] };

  it("reads the list after each call and what the call changed", () => {
    const views = viewsOf(call("c1", "TodoWrite", first), call("x", "Write", { file_path: "a.txt" }), call("c2", "TodoWrite", second));
    expect(views.size).toBe(2);
    const made = views.get("c1")!;
    expect(made.fresh).toBe(true);
    expect(made.changes).toEqual([]);
    expect(texts(made)).toEqual(["in_progress:Step 1: create a.txt", "pending:Step 2: create b.txt", "pending:Step 3: list the folder"]);
    expect(made.items[0].active).toBe("Creating a.txt");
    const next = views.get("c2")!;
    expect(next.fresh).toBe(false);
    expect(next.changes).toEqual([
      { kind: "completed", text: "Step 1: create a.txt" },
      { kind: "started", text: "Step 2: create b.txt" },
    ]);
  });

  it("reads Codex's plan and other CLIs' spellings", () => {
    const views = viewsOf(
      call("p1", "update_plan", { explanation: "Start", plan: [{ step: "Read the code", status: "in_progress" }, { step: "Fix it", status: "pending" }] }),
      call("p2", "update_plan", { plan: [{ step: "Read the code", status: "completed" }, { step: "Fix it", status: "in_progress" }, { step: "Test it", status: "pending" }] }),
    );
    expect(texts(views.get("p1"))).toEqual(["in_progress:Read the code", "pending:Fix it"]);
    expect(views.get("p2")!.changes.map((change) => change.kind)).toEqual(["completed", "started", "added"]);
    const cursor = viewsOf(call("u1", "TodoWrite", { todos: [
      { id: "a", content: "One", status: "TODO_STATUS_COMPLETED" },
      { id: "b", content: "Two", status: "TODO_STATUS_IN_PROGRESS" },
      { id: "c", content: "Dropped", status: "cancelled" },
    ] }));
    expect(texts(cursor.get("u1"))).toEqual(["completed:One", "in_progress:Two"]);
    // A list of plain strings and one that ticks entries with a flag.
    const plain = viewsOf(call("s1", "todo_write", { items: ["First", { text: "Second", completed: true }] }));
    expect(texts(plain.get("s1"))).toEqual(["pending:First", "completed:Second"]);
  });

  it("changes only the named entries of a merging call", () => {
    const views = viewsOf(
      call("m1", "TodoWrite", { todos: [{ id: "1", content: "One", status: "in_progress" }, { id: "2", content: "Two", status: "pending" }] }),
      call("m2", "TodoWrite", { merge: true, todos: [{ id: "1", content: "One", status: "completed" }] }),
    );
    expect(texts(views.get("m2"))).toEqual(["completed:One", "pending:Two"]);
    expect(views.get("m2")!.changes).toEqual([{ kind: "completed", text: "One" }]);
  });

  it("starts a new list when none of the entries were on the old one", () => {
    const views = viewsOf(
      call("a", "TodoWrite", { todos: [{ content: "Old", status: "completed" }] }),
      call("b", "TodoWrite", { todos: [{ content: "New one", status: "pending" }, { content: "New two", status: "pending" }] }),
      call("c", "TodoWrite", { todos: [] }),
    );
    expect(views.get("b")!.fresh).toBe(true);
    expect(views.get("c")!.items).toEqual([]);
  });

  it("skips a call that failed or carries no list", () => {
    const views = viewsOf(
      call("f", "TodoWrite", first, "InputValidationError", { isError: true }),
      call("n", "TodoWrite", {}),
    );
    expect(views.size).toBe(0);
  });
});

describe("Claude Code's task tools", () => {
  // Inputs and answers as Claude Code 2.1.325 gave them in a real run.
  const blocks = [
    call("k1", "TaskCreate", { subject: "Collect facts", description: "Gather the facts." }, "Task #1 created successfully: Collect facts"),
    call("k2", "TaskCreate", { subject: "Write draft", description: "Write it.", activeForm: "Writing the draft" }, "Task #2 created successfully: Write draft"),
    call("k3", "TaskCreate", { subject: "Review draft", description: "Review it." }, "Task #3 created successfully: Review draft"),
    call("u1", "TaskUpdate", { taskId: "1", status: "in_progress" }, "Updated task #1 status"),
    call("u2", "TaskUpdate", { taskId: "1", status: "completed" }, "Updated task #1 status"),
    call("u3", "TaskUpdate", { taskId: "2", subject: "Write the launch draft", status: "in_progress" }, "Updated task #2 subject, status"),
    call("u4", "TaskUpdate", { taskId: "3", status: "deleted" }, "Updated task #3 deleted"),
    call("l1", "TaskList", {}, "#1 [completed] Collect facts\n#2 [in_progress] Write the launch draft"),
  ];

  it("builds the list call by call", () => {
    const views = viewsOf(...blocks);
    expect(views.get("k1")!.fresh).toBe(true);
    expect(views.get("k2")!.fresh).toBe(false);
    expect(texts(views.get("k3"))).toEqual(["pending:Collect facts", "pending:Write draft", "pending:Review draft"]);
    expect(views.get("u1")!.changes).toEqual([{ kind: "started", text: "Collect facts" }]);
    expect(views.get("u2")!.changes).toEqual([{ kind: "completed", text: "Collect facts" }]);
    expect(texts(views.get("u3"))).toEqual(["completed:Collect facts", "in_progress:Write the launch draft", "pending:Review draft"]);
    expect(views.get("u3")!.items[1].active).toBe("Writing the draft");
    expect(views.get("u4")!.changes).toEqual([{ kind: "removed", text: "Review draft" }]);
    expect(texts(views.get("u4"))).toEqual(["completed:Collect facts", "in_progress:Write the launch draft"]);
    // Reading the list back is no change of it.
    expect(views.has("l1")).toBe(false);
  });

  it("carries the list over into the next turn", () => {
    const items: TimelineItem[] = [
      turn("t1", blocks.slice(0, 4)),
      turn("t2", [call("z1", "TaskUpdate", { taskId: "1", status: "completed" }, "Updated task #1 status")]),
    ];
    const views = planViewsOf(items);
    expect(texts(views.get("z1"))).toEqual(["completed:Collect facts", "pending:Write draft", "pending:Review draft"]);
    // The second turn on its own does not know the tasks.
    expect(planViewsOf([items[1]]).size).toBe(0);
  });

  it("begins a new list once every task of the old one is done", () => {
    const views = viewsOf(
      call("a", "TaskCreate", { subject: "Only task" }, "Task #1 created successfully: Only task"),
      call("b", "TaskUpdate", { taskId: "1", status: "completed" }, "Updated task #1 status"),
      call("c", "TaskCreate", { subject: "Next job" }, "Task #2 created successfully: Next job"),
    );
    expect(views.get("c")!.fresh).toBe(true);
    expect(texts(views.get("c"))).toEqual(["pending:Next job"]);
  });

  it("numbers a task whose answer has not arrived yet", () => {
    const views = viewsOf(
      call("a", "TaskCreate", { subject: "First" }, "Task #4 created successfully: First"),
      call("b", "TaskCreate", { subject: "Second" }, null),
      call("c", "TaskUpdate", { taskId: "5", status: "in_progress" }, null),
    );
    expect(texts(views.get("c"))).toEqual(["pending:First", "in_progress:Second"]);
  });

  it("takes what a read of the list reports: another agent's change, a task made earlier", () => {
    const views = viewsOf(
      call("a", "TaskCreate", { subject: "Mine" }, "Task #7 created successfully: Mine"),
      call("l", "TaskList", {}, "#6 [pending] Made before [blocked by #7]\n#7 [in_progress] Mine\n#3 [completed] Long done"),
      call("u", "TaskUpdate", { taskId: "6", status: "in_progress" }, "Updated task #6 status"),
    );
    expect(texts(views.get("u"))).toEqual(["in_progress:Mine", "in_progress:Made before"]);
    const emptied = viewsOf(
      call("a", "TaskCreate", { subject: "Mine" }, "Task #1 created successfully: Mine"),
      call("l", "TaskList", {}, "No tasks found"),
      call("b", "TaskCreate", { subject: "Fresh" }, "Task #2 created successfully: Fresh"),
    );
    expect(emptied.get("b")!.fresh).toBe(true);
  });

  it("ignores an update of a task it never saw, until the update names it", () => {
    const views = viewsOf(
      call("a", "TaskUpdate", { taskId: "9", status: "in_progress" }, "Updated task #9 status"),
      call("b", "TaskUpdate", { taskId: "9", subject: "Named now", status: "in_progress" }, "Updated task #9 subject"),
    );
    expect(views.has("a")).toBe(false);
    expect(texts(views.get("b"))).toEqual(["in_progress:Named now"]);
  });
});

describe("a run of list calls", () => {
  it("reads as one step: every change since before the first", () => {
    const views = viewsOf(
      call("k1", "TaskCreate", { subject: "One" }, "Task #1 created successfully: One"),
      call("k2", "TaskCreate", { subject: "Two" }, "Task #2 created successfully: Two"),
      call("u1", "TaskUpdate", { taskId: "1", status: "in_progress" }, "Updated task #1 status"),
      call("u2", "TaskUpdate", { taskId: "1", status: "completed" }, "Updated task #1 status"),
      call("u3", "TaskUpdate", { taskId: "2", status: "in_progress" }, "Updated task #2 status"),
    );
    const made = joinPlanViews([views.get("k1")!, views.get("k2")!, views.get("u1")!]);
    expect(made.fresh).toBe(true);
    expect(made.items).toHaveLength(2);
    const moved = joinPlanViews([views.get("u2")!, views.get("u3")!]);
    expect(moved.fresh).toBe(false);
    expect(moved.changes).toEqual([{ kind: "completed", text: "One" }, { kind: "started", text: "Two" }]);
    // An entry started and finished within the run is finished.
    expect(joinPlanViews([views.get("u1")!, views.get("u2")!]).changes).toEqual([{ kind: "completed", text: "One" }]);
  });
});

describe("the list calls of a conversation", () => {
  it("stay the same calls while only other blocks change", () => {
    const first = [turn("t1", [call("c1", "TodoWrite", { todos: [{ content: "A", status: "pending" }] })])];
    const input = (first[0] as TurnItem).blocks[0];
    const grown = [turn("t1", [input, { kind: "text", id: "n1", text: "Working on it." }])];
    expect(samePlanOps(planOps(first), planOps(grown))).toBe(true);
    const answered = [turn("t1", [{ ...(input as ToolBlock), output: "done" }])];
    expect(samePlanOps(planOps(first), planOps(answered))).toBe(false);
    expect(planViews(planOps(grown)).size).toBe(1);
  });
});

describe("how long an entry took", () => {
  const at = (ms: number) => ({ startedMs: ms });
  const S = 1000;
  // One turn that has run from 0 on and still runs.
  const viewsOf = (...blocks: TurnBlock[]) => planViewsOf([{ ...turn("t1", blocks), startedMs: 0, durationMs: null, status: "running" }]);

  it("times an entry from the call that began it to the call that checked it off", () => {
    const views = viewsOf(
      call("k1", "TaskCreate", { subject: "Collect facts" }, "Task #1 created successfully: Collect facts", at(0)),
      call("k2", "TaskCreate", { subject: "Write draft" }, "Task #2 created successfully: Write draft", at(1 * S)),
      call("u1", "TaskUpdate", { taskId: "1", status: "in_progress" }, "Updated task #1 status", at(5 * S)),
      call("u2", "TaskUpdate", { taskId: "1", status: "completed" }, "Updated task #1 status", at(47 * S)),
      call("u3", "TaskUpdate", { taskId: "2", status: "in_progress" }, "Updated task #2 status", at(48 * S)),
    );
    const done = views.get("u3")!.items;
    expect(done[0]).toMatchObject({ status: "completed", startedMs: 5 * S, tookMs: 42 * S });
    // The entry in work has begun and has no time yet.
    expect(done[1]).toMatchObject({ status: "in_progress", startedMs: 48 * S });
    expect(done[1].tookMs).toBeUndefined();
  });

  it("times a whole-list tool's entries by text, the first one in work from the list's start", () => {
    const list = (...rows: [string, string][]) => ({ todos: rows.map(([content, status]) => ({ content, status })) });
    const views = viewsOf(
      call("p1", "TodoWrite", list(["Read", "in_progress"], ["Write", "pending"]), "ok", at(10 * S)),
      call("p2", "TodoWrite", list(["Read", "completed"], ["Write", "in_progress"]), "ok", at(70 * S)),
      call("p3", "TodoWrite", list(["Read", "completed"], ["Write", "completed"]), "ok", at(100 * S)),
    );
    expect(views.get("p3")!.items.map((item) => item.tookMs)).toEqual([60 * S, 30 * S]);
  });

  it("gives an entry checked off without being begun the time since the entry before it", () => {
    // Codex only says whether an entry is done.
    const plan = (...done: boolean[]) => ({ plan: done.map((value, index) => ({ step: `Step ${index + 1}`, status: value ? "completed" : "pending" })) });
    const views = viewsOf(
      call("c1", "update_plan", plan(false, false, false, false, false), "done", at(0)),
      call("c2", "update_plan", plan(true, false, false, false, false), "done", at(20 * S)),
      call("c3", "update_plan", plan(true, true, false, false, false), "done", at(50 * S)),
      call("c4", "update_plan", plan(true, true, true, false, false), "done", at(90 * S)),
      // Two at once: which one took how long is not known.
      call("c5", "update_plan", plan(true, true, true, true, true), "done", at(99 * S)),
    );
    expect(views.get("c5")!.items.map((item) => item.tookMs)).toEqual([20 * S, 30 * S, 40 * S, undefined, undefined]);
  });

  it("does not count two entries checked off in one call against each other", () => {
    const list = (...rows: [string, string][]) => ({ todos: rows.map(([content, status]) => ({ content, status })) });
    const views = viewsOf(
      call("p1", "TodoWrite", list(["Read", "in_progress"], ["Write", "pending"]), "ok", at(0)),
      call("p2", "TodoWrite", list(["Read", "completed"], ["Write", "completed"]), "ok", at(30 * S)),
    );
    expect(views.get("p2")!.items.map((item) => item.tookMs)).toEqual([30 * S, undefined]);
  });

  it("leaves out the time between turns, while the agent waited for the person", () => {
    const items: TimelineItem[] = [
      { ...turn("t1", [
        call("k1", "TaskCreate", { subject: "Ask about the colour" }, "Task #1 created successfully: Ask about the colour", at(1 * S)),
        call("u1", "TaskUpdate", { taskId: "1", status: "in_progress" }, "Updated task #1 status", at(2 * S)),
      ]), startedMs: 0, durationMs: 10 * S },
      // The person answered an hour later.
      { ...turn("t2", [
        call("u2", "TaskUpdate", { taskId: "1", status: "completed" }, "Updated task #1 status", at(3600 * S + 5 * S)),
      ]), startedMs: 3600 * S, durationMs: 60 * S },
    ];
    // 8 s in the first turn, 5 s in the second.
    expect(planViewsOf(items).get("u2")!.items[0].tookMs).toBe(13 * S);
  });

  it("counts a turn that still runs up to the moment the entry was checked off", () => {
    const items: TimelineItem[] = [
      { ...turn("t1", [
        call("p1", "TodoWrite", { todos: [{ content: "A", status: "in_progress" }] }, "ok", at(2 * S)),
        call("p2", "TodoWrite", { todos: [{ content: "A", status: "completed" }] }, "ok", at(9 * S)),
      ]), startedMs: 0, durationMs: null, status: "running" },
    ];
    expect(planViewsOf(items).get("p2")!.items[0].tookMs).toBe(7 * S);
  });

  it("knows no time for a change another agent made", () => {
    const views = viewsOf(
      call("k1", "TaskCreate", { subject: "Mine" }, "Task #1 created successfully: Mine", at(0)),
      call("u1", "TaskUpdate", { taskId: "1", status: "in_progress" }, "Updated task #1 status", at(1 * S)),
      call("l1", "TaskList", {}, "#1 [completed] Mine\n#2 [in_progress] Theirs", at(30 * S)),
      call("k2", "TaskCreate", { subject: "Next" }, "Task #3 created successfully: Next", at(31 * S)),
    );
    const items = views.get("k2")!.items;
    expect(items.find((item) => item.text === "Mine")?.tookMs).toBeUndefined();
    expect(items.find((item) => item.text === "Theirs")?.startedMs).toBeUndefined();
  });

  it("starts the times again when an entry is opened again", () => {
    const views = viewsOf(
      call("k1", "TaskCreate", { subject: "Fix" }, "Task #1 created successfully: Fix", at(0)),
      call("u1", "TaskUpdate", { taskId: "1", status: "in_progress" }, "Updated task #1 status", at(1 * S)),
      call("u2", "TaskUpdate", { taskId: "1", status: "completed" }, "Updated task #1 status", at(4 * S)),
      call("k2", "TaskCreate", { subject: "Other" }, "Task #2 created successfully: Other", at(5 * S)),
      call("u3", "TaskUpdate", { taskId: "1", status: "pending" }, "Updated task #1 status", at(6 * S)),
    );
    // A finished list began a new one at k2, so task 1 is gone from it.
    expect(views.get("u3")).toBeUndefined();
    expect(views.get("u2")!.items[0].tookMs).toBe(3 * S);
  });
});
