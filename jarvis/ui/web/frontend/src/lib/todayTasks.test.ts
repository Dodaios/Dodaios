import { describe, expect, it } from "vitest";

import type { PersonalTask } from "@/types/today";
import { groupRuns, localDayString, parseDay, splitTasks, taskGroup } from "./todayTasks";

const TODAY = "2026-10-14";

function task(over: Partial<PersonalTask>): PersonalTask {
  return {
    id: over.title ?? "t",
    title: "t",
    notes: null,
    priority: "normal",
    due_date: null,
    status: "open",
    created_at: "2026-10-14T07:00:00+00:00",
    updated_at: "2026-10-14T07:00:00+00:00",
    completed_at: null,
    ...over,
  };
}

describe("taskGroup", () => {
  it("follows the store's buckets", () => {
    expect(taskGroup(task({ due_date: "2026-10-13" }), TODAY)).toBe("overdue");
    expect(taskGroup(task({ due_date: TODAY, priority: "low" }), TODAY)).toBe("due_today");
    expect(taskGroup(task({ priority: "high" }), TODAY)).toBe("high");
    expect(taskGroup(task({ priority: "high", due_date: "2026-10-20" }), TODAY)).toBe("high");
    expect(taskGroup(task({ due_date: "2026-10-20" }), TODAY)).toBe("other");
    expect(taskGroup(task({}), TODAY)).toBe("other");
  });

  it("an overdue date wins over high priority", () => {
    expect(taskGroup(task({ priority: "high", due_date: "2026-01-01" }), TODAY)).toBe("overdue");
  });
});

describe("splitTasks", () => {
  const all = [
    task({ title: "overdue", due_date: "2026-10-01" }),
    task({ title: "high", priority: "high" }),
    task({ title: "later", due_date: "2026-11-01" }),
    task({ title: "done", status: "done", completed_at: "2026-10-14T08:00:00+00:00" }),
  ];

  it("keeps the server order and splits today, open and done", () => {
    const split = splitTasks(all, TODAY);
    expect(split.today.map((t) => t.title)).toEqual(["overdue", "high"]);
    expect(split.open.map((t) => t.title)).toEqual(["overdue", "high", "later"]);
    expect(split.done.map((t) => t.title)).toEqual(["done"]);
  });

  it("groups consecutive tasks of one group", () => {
    const runs = groupRuns(splitTasks(all, TODAY).open, TODAY);
    expect(runs.map((r) => [r.group, r.tasks.length])).toEqual([
      ["overdue", 1],
      ["high", 1],
      ["other", 1],
    ]);
  });
});

describe("dates", () => {
  it("reads YYYY-MM-DD as a local calendar day", () => {
    const day = parseDay("2026-03-01");
    expect([day.getFullYear(), day.getMonth(), day.getDate()]).toEqual([2026, 2, 1]);
  });

  it("formats a local day back", () => {
    expect(localDayString(new Date(2026, 0, 5, 23, 30))).toBe("2026-01-05");
  });
});
