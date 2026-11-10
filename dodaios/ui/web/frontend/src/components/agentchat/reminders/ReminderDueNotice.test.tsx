import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ReminderDueNotice } from "./ReminderDueNotice";
import type { NoticeItem } from "../reduce";

vi.mock("@/i18n", () => ({ useT: () => (key: string) => key, useUiLanguage: () => "en" }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const notice = (data: Record<string, unknown>): NoticeItem => ({
  type: "notice", id: "n-9", kind: "reminder_due", text: "", agentName: "", agentId: "",
  status: "", tsMs: 1, data, resolved: "",
});

it("shows the reminder with Done and the snooze choices, and ticks it off", async () => {
  const fetcher = vi.fn(async () => new Response(JSON.stringify({ ok: true })));
  vi.stubGlobal("fetch", fetcher);
  render(<ReminderDueNotice item={notice({ memory_id: "m1", text: "call the bank", due_at: "2026-11-10T14:00:00+00:00" })} />);
  expect(screen.getByText("call the bank")).toBeTruthy();
  expect(screen.getAllByTestId("reminder-snooze")).toHaveLength(4);
  fireEvent.click(screen.getByTestId("reminder-done"));
  await waitFor(() => expect(screen.getByText("reminders.marked_done")).toBeTruthy());
  const [doneUrl] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
  expect(doneUrl).toBe("/api/notify/reminders/m1/done");
  expect(screen.queryByTestId("reminder-done")).toBeNull();
});

it("snoozes through the backend and says until when", async () => {
  const fetcher = vi.fn(async () =>
    new Response(JSON.stringify({ id: "m2", text: "call the bank", due_at: "2026-11-10T15:00:00Z" })));
  vi.stubGlobal("fetch", fetcher);
  render(<ReminderDueNotice item={notice({ memory_id: "m1", text: "call the bank" })} />);
  fireEvent.click(screen.getAllByTestId("reminder-snooze")[0]);
  await waitFor(() => expect(screen.getByText(/reminders.snoozed_until/)).toBeTruthy());
  const [url, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
  expect(url).toBe("/api/notify/reminders/m1/snooze");
  expect(JSON.parse(String(init.body)).minutes).toBe(15);
});

it("names a failure instead of pretending", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 404 })));
  render(<ReminderDueNotice item={notice({ memory_id: "m1", text: "call the bank" })} />);
  fireEvent.click(screen.getByTestId("reminder-done"));
  await waitFor(() => expect(screen.getByRole("alert").textContent).toBe("reminders.failed"));
});

it("renders nothing without a text", () => {
  const { container } = render(<ReminderDueNotice item={notice({})} />);
  expect(container.textContent).toBe("");
});
