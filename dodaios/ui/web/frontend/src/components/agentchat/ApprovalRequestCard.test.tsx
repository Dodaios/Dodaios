import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ApprovalRequestCard } from "./ApprovalRequestCard";
import { EMPTY_TIMELINE, reduceEvents } from "./reduce";
import type { NoticeItem } from "./reduce";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const card = (resolved = "", data: Record<string, unknown> = {}): NoticeItem => ({
  type: "notice", id: "n-1", kind: "approval_request", text: "Click \"Cancel subscription\" on play.google.com",
  agentName: "", agentId: "jarvis", status: "pending", tsMs: 1,
  data: {
    agent_id: "jarvis", approval_id: "a1", label: "Cancel subscription", where: "play.google.com",
    detail: "SuperGrok 33.99 per month", browser: true, ...data,
  },
  resolved,
});

it("names the click, the site and what the page says, and a yes answers the row", async () => {
  const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({}) }) as Response);
  vi.stubGlobal("fetch", fetchMock);
  render(<ApprovalRequestCard item={card()} />);
  const title = screen.getByTestId("approval-request-title").textContent ?? "";
  expect(title).toContain("Cancel subscription");
  expect(title).toContain("play.google.com");
  expect(screen.getByTestId("approval-request-detail").textContent).toContain("SuperGrok");
  fireEvent.click(screen.getByTestId("approval-request-yes"));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
  expect(url).toBe("/api/society/approvals/a1/resolve");
  expect(JSON.parse(String(init.body))).toEqual({ approve: true });
});

it("a no answers the same row with a refusal", async () => {
  const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({}) }) as Response);
  vi.stubGlobal("fetch", fetchMock);
  render(<ApprovalRequestCard item={card()} />);
  fireEvent.click(screen.getByTestId("approval-request-no"));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
  expect(JSON.parse(String(init.body))).toEqual({ approve: false });
});

it("closes at once on the person's own click, and shows an answer given elsewhere", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({ approval: { state: "approved" } }) }) as Response));
  const { unmount } = render(<ApprovalRequestCard item={card()} />);
  fireEvent.click(screen.getByTestId("approval-request-yes"));
  await waitFor(() => expect(screen.getByTestId("approval-request-closed")).toBeTruthy());
  expect(screen.queryByTestId("approval-request-yes")).toBeNull();
  unmount();
  // The row was already declined on another surface: a late yes does not read as approved.
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({ approval: { state: "denied" } }) }) as Response));
  render(<ApprovalRequestCard item={card()} />);
  fireEvent.click(screen.getByTestId("approval-request-yes"));
  await waitFor(() => expect(screen.getByTestId("approval-request-closed").textContent).toMatch(/Declined/));
});

it("says so when the answer did not arrive and keeps the buttons", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false }) as Response));
  render(<ApprovalRequestCard item={card()} />);
  fireEvent.click(screen.getByTestId("approval-request-yes"));
  await waitFor(() => expect(screen.getByTestId("approval-request-failed")).toBeTruthy());
  expect(screen.getByTestId("approval-request-yes")).toBeTruthy();
});

it("a tool's own ask shows its words when there is no button label", () => {
  render(<ApprovalRequestCard item={card("", { label: "", detail: "", browser: false })} />);
  expect(screen.getByText(/Cancel subscription/)).toBeTruthy();
  expect(screen.queryByTestId("approval-request-open")).toBeNull();
});

it("once answered it only says how", () => {
  render(<ApprovalRequestCard item={card("declined")} />);
  expect(screen.queryByTestId("approval-request-yes")).toBeNull();
  expect(screen.getByTestId("approval-request-closed")).toBeTruthy();
});

it("the answer patches the card and adds no row", () => {
  const ev = (payload: Record<string, unknown>, seq: number) =>
    ({ kind: "notice", seq, ts_ms: seq, payload }) as never;
  const tl = reduceEvents(EMPTY_TIMELINE, [
    ev({ kind: "approval_request", status: "pending", text: "Click", agent_id: "jarvis", approval_id: "a1" }, 1),
    ev({ kind: "approval_request_done", approval_id: "a1", status: "approved" }, 2),
  ]);
  expect(tl.items).toHaveLength(1);
  const item = tl.items[0];
  if (item.type !== "notice") throw new Error("unreachable");
  expect(item.resolved).toBe("approved");
});
