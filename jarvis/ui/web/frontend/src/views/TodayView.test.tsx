import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { PersonalTask } from "@/types/today";
import { TodayView } from "./TodayView";

const TODAY = "2026-10-14";

function task(over: Partial<PersonalTask>): PersonalTask {
  return {
    id: "t1",
    title: "Task",
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

type Call = { url: string; method: string; body: unknown };

let calls: Call[];
let tasks: PersonalTask[];

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  calls = [];
  tasks = [
    task({ id: "late", title: "Pay invoice", due_date: "2026-10-10", priority: "high" }),
    task({ id: "now", title: "Call the bank", due_date: TODAY }),
    task({ id: "imp", title: "Prepare offer", priority: "high", notes: "two options" }),
    task({ id: "later", title: "Book the trip", due_date: "2026-11-02", priority: "low" }),
    task({
      id: "old",
      title: "Renew passport",
      status: "done",
      completed_at: "2026-10-12T09:00:00+00:00",
    }),
  ];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ url, method, body });
      if (method === "GET") return json({ view: "all", today: TODAY, tasks });
      if (method === "POST" && url === "/api/today/tasks") {
        return json(task({ id: "new", ...(body as object) }), 201);
      }
      if (method === "DELETE") return json({ id: url.split("/").pop(), deleted: true });
      if (url.endsWith("/complete")) return json(task({ status: "done" }));
      return json(task({}));
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderView() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TodayView />
    </QueryClientProvider>,
  );
}

const mutations = () => calls.filter((c) => c.method !== "GET");

describe("TodayView", () => {
  it("shows overdue, due today and high priority in their groups, in server order", async () => {
    renderView();
    const overdue = await screen.findByTestId("today-group-overdue");
    expect(within(overdue).getByText("Pay invoice")).toBeTruthy();
    expect(within(screen.getByTestId("today-group-due_today")).getByText("Call the bank")).toBeTruthy();
    expect(within(screen.getByTestId("today-group-high")).getByText("Prepare offer")).toBeTruthy();
    expect(screen.queryByText("Book the trip")).toBeNull(); // not on Today
    expect(screen.queryByText("Renew passport")).toBeNull();
    expect(screen.getByText("two options")).toBeTruthy();
    // The voice tip names the user's own assistant, never a fixed name.
    const tip = screen.getByTestId("today-view").textContent ?? "";
    expect(tip).not.toContain("{name}");
    expect(tip).not.toContain("Hey Jarvis");
  });

  it("lists every open task under All open and completed ones under Done", async () => {
    renderView();
    await screen.findByText("Pay invoice");
    fireEvent.click(screen.getByTestId("today-tab-open"));
    expect(screen.getByText("Book the trip")).toBeTruthy();
    expect(screen.getByTestId("today-group-other")).toBeTruthy();
    fireEvent.click(screen.getByTestId("today-tab-done"));
    expect(screen.getByText("Renew passport")).toBeTruthy();
    expect(screen.queryByText("Pay invoice")).toBeNull();
  });

  it("adds a task with title, priority and due date", async () => {
    renderView();
    await screen.findByText("Pay invoice");
    fireEvent.change(screen.getByTestId("today-add-title"), { target: { value: "  Water plants " } });
    fireEvent.click(screen.getByTestId("today-add-priority-high"));
    fireEvent.change(screen.getByTestId("today-add-due"), { target: { value: "2026-10-20" } });
    fireEvent.click(screen.getByTestId("today-add-submit"));
    await waitFor(() => expect(mutations()).toHaveLength(1));
    expect(mutations()[0]).toEqual({
      url: "/api/today/tasks",
      method: "POST",
      body: { title: "Water plants", priority: "high", due_date: "2026-10-20" },
    });
    await waitFor(() =>
      expect((screen.getByTestId("today-add-title") as HTMLInputElement).value).toBe(""),
    );
  });

  it("sets the due date to today from a labelled shortcut", async () => {
    renderView();
    await screen.findByText("Pay invoice");
    const shortcut = screen.getByTestId("today-add-due-today");
    expect(shortcut.getAttribute("aria-label")).toBeTruthy();
    expect(shortcut.tagName).toBe("BUTTON");
    fireEvent.click(shortcut);
    expect((screen.getByTestId("today-add-due") as HTMLInputElement).value).toBe(TODAY);
    expect(screen.queryByTestId("today-add-due-today")).toBeNull(); // already today
  });

  it("does not add an empty task", async () => {
    renderView();
    await screen.findByText("Pay invoice");
    fireEvent.change(screen.getByTestId("today-add-title"), { target: { value: "   " } });
    expect((screen.getByTestId("today-add-submit") as HTMLButtonElement).disabled).toBe(true);
    fireEvent.submit(screen.getByTestId("today-add"));
    expect(mutations()).toHaveLength(0);
  });

  it("completes an open task and reopens a done one", async () => {
    renderView();
    await screen.findByText("Pay invoice");
    fireEvent.click(screen.getByTestId("today-toggle-late"));
    await waitFor(() =>
      expect(mutations()[0]).toMatchObject({ url: "/api/today/tasks/late/complete", method: "POST" }),
    );
    fireEvent.click(screen.getByTestId("today-tab-done"));
    fireEvent.click(screen.getByTestId("today-toggle-old"));
    await waitFor(() =>
      expect(mutations()[1]).toMatchObject({ url: "/api/today/tasks/old/reopen", method: "POST" }),
    );
  });

  it("deletes only after a second click", async () => {
    renderView();
    await screen.findByText("Pay invoice");
    const remove = screen.getByTestId("today-delete-imp");
    fireEvent.click(remove);
    expect(mutations()).toHaveLength(0);
    fireEvent.click(remove);
    await waitFor(() =>
      expect(mutations()[0]).toMatchObject({ url: "/api/today/tasks/imp", method: "DELETE" }),
    );
  });

  it("edits a task in a dialog and can remove its due date", async () => {
    renderView();
    await screen.findByText("Pay invoice");
    fireEvent.click(screen.getByTestId("today-edit-late"));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.parentElement).toBe(document.body.lastElementChild);
    fireEvent.change(screen.getByTestId("today-dialog-title-input"), {
      target: { value: "Pay the invoice" },
    });
    fireEvent.click(screen.getByTestId("today-dialog-priority-low"));
    fireEvent.click(screen.getByTestId("today-dialog-clear-due"));
    fireEvent.click(screen.getByTestId("today-dialog-save"));
    await waitFor(() => expect(mutations()).toHaveLength(1));
    expect(mutations()[0]).toEqual({
      url: "/api/today/tasks/late",
      method: "PATCH",
      body: { title: "Pay the invoice", notes: null, priority: "low", due_date: null },
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("shows the empty state and a load error", async () => {
    tasks = [];
    renderView();
    expect(await screen.findByTestId("today-empty")).toBeTruthy();
    vi.stubGlobal("fetch", vi.fn(async () => json({ detail: "down" }, 503)));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <TodayView />
      </QueryClientProvider>,
    );
    expect((await screen.findByTestId("today-error")).textContent).toContain("down");
  });
});
