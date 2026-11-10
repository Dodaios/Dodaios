import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import SidebarDue, { dueLabel } from "@/components/layout/SidebarDue";

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

describe("SidebarDue", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("is absent on an empty week", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ items: [] }))));
    render(<SidebarDue />);
    await Promise.resolve();
    expect(screen.queryByTestId("sidebar-due")).toBeNull();
  });

  it("lists what falls due", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      items: [{ id: "m1", text: "Tax return deadline", due_at: "2030-01-02" }],
    }))));
    render(<SidebarDue />);
    expect((await screen.findByTestId("sidebar-due-row")).textContent).toContain("Tax return deadline");
  });
});
