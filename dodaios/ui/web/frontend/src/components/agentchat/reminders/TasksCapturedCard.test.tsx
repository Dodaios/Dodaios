import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { TasksCapturedCard } from "./TasksCapturedCard";
import type { NoticeItem } from "../reduce";

vi.mock("@/i18n", () => ({ useT: () => (key: string) => key, useUiLanguage: () => "en" }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const notice = (items: unknown[]): NoticeItem => ({
  type: "notice", id: "n-4", kind: "tasks_captured", text: "", agentName: "", agentId: "",
  status: "done", tsMs: 1, data: { items }, resolved: "",
});

it("lists every item as a reminder or a task and forgets one on undo", async () => {
  const fetcher = vi.fn(async () => new Response(JSON.stringify({ forgotten: 1 })));
  vi.stubGlobal("fetch", fetcher);
  const tomorrow = new Date(Date.now() + 86_400_000).toISOString();
  render(<TasksCapturedCard item={notice([
    { id: "m1", text: "dentist", due_at: tomorrow, reminder: true },
    { id: "m2", text: "buy milk", due_at: null, reminder: false },
  ])} />);
  expect(screen.getByText("reminders.captured_title")).toBeTruthy();
  expect(screen.getAllByTestId("tasks-captured-row")).toHaveLength(2);
  expect(screen.getByText(/sidebar\.due\.tomorrow/)).toBeTruthy();
  expect(screen.getByText("reminders.task")).toBeTruthy();
  fireEvent.click(screen.getAllByTestId("tasks-captured-undo")[1]);
  await waitFor(() => expect(screen.getByText("reminders.undone")).toBeTruthy());
  const [forgetUrl] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
  expect(forgetUrl).toContain("/items/m2");
  expect(screen.getAllByTestId("tasks-captured-undo")).toHaveLength(1);
});

it("says so when one item was captured, and renders nothing for none", () => {
  render(<TasksCapturedCard item={notice([{ id: "m1", text: "buy milk", due_at: null, reminder: false }])} />);
  expect(screen.getByText("reminders.captured_one")).toBeTruthy();
  cleanup();
  const { container } = render(<TasksCapturedCard item={notice([])} />);
  expect(container.textContent).toBe("");
});
