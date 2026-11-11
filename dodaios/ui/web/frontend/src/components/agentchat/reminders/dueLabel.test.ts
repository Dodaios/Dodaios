import { describe, expect, it } from "vitest";

import { dueLabel } from "@/components/agentchat/reminders/dueLabel";

const t = (key: string) => key.split(".").pop() ?? key;

describe("dueLabel", () => {
  const now = new Date(2026, 10, 10, 12, 0);
  it("names overdue, today and tomorrow", () => {
    expect(dueLabel("2026-11-09", now, t, "en")).toBe("overdue");
    expect(dueLabel("2026-11-10", now, t, "en")).toBe("today");
    expect(dueLabel("2026-11-11", now, t, "en")).toBe("tomorrow");
    expect(dueLabel(new Date(2026, 10, 10, 9, 0).toISOString(), now, t, "en")).toBe("overdue");
  });
  it("gives a short date further out, and nothing for a broken date", () => {
    expect(dueLabel("2026-11-14", now, t, "en")).not.toBe("");
    expect(dueLabel("not a date", now, t, "en")).toBe("");
  });
});
