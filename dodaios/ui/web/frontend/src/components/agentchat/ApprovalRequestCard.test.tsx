import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ActionBlockedCard, ApprovalRequestCard } from "./ApprovalRequestCard";
import { publishBrowserFrame, clearBrowserFrame } from "@/components/society/card/liveFrames";
import { OPEN_AGENT_BROWSER_EVENT } from "@/components/home/chatBrowser/openEvent";
import { EMPTY_TIMELINE, reduceEvents } from "./reduce";
import type { NoticeItem } from "./reduce";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  clearBrowserFrame("jarvis");
});

/** The buttons wait a moment after the card appears (``ARM_DELAY_MS``). */
async function click(testId: string) {
  const button = screen.getByTestId(testId) as HTMLButtonElement;
  await waitFor(() => expect(button.disabled).toBe(false));
  fireEvent.click(button);
}

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
  await click("approval-request-yes");
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
  expect(url).toBe("/api/society/approvals/a1/resolve");
  expect(JSON.parse(String(init.body))).toEqual({ approve: true });
});

it("a no answers the same row with a refusal", async () => {
  const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({}) }) as Response);
  vi.stubGlobal("fetch", fetchMock);
  render(<ApprovalRequestCard item={card()} />);
  await click("approval-request-no");
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
  expect(JSON.parse(String(init.body))).toEqual({ approve: false });
});

it("closes at once on the person's own click, and shows an answer given elsewhere", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({ approval: { state: "approved" } }) }) as Response));
  const { unmount } = render(<ApprovalRequestCard item={card()} />);
  await click("approval-request-yes");
  await waitFor(() => expect(screen.getByTestId("approval-request-closed")).toBeTruthy());
  expect(screen.queryByTestId("approval-request-yes")).toBeNull();
  unmount();
  // The row was already declined on another surface: a late yes does not read as approved.
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({ approval: { state: "denied" } }) }) as Response));
  render(<ApprovalRequestCard item={card()} />);
  await click("approval-request-yes");
  await waitFor(() => expect(screen.getByTestId("approval-request-closed").textContent).toMatch(/Declined/));
});

it("says so when the answer did not arrive and keeps the buttons", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false }) as Response));
  render(<ApprovalRequestCard item={card()} />);
  await click("approval-request-yes");
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

it("a click in the first moment after the card appears answers nothing", () => {
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  render(<ApprovalRequestCard item={card()} />);
  fireEvent.click(screen.getByTestId("approval-request-yes"));
  expect(fetchMock).not.toHaveBeenCalled();
});

it("money says it asks in every mode, Bypass too", () => {
  render(<ApprovalRequestCard item={card("", { label: "Place your order", severity: "confirm", step_kind: "buy" })} />);
  const root = screen.getByTestId("approval-request-card");
  expect(root.dataset.severity).toBe("confirm");
  expect(screen.getByTestId("approval-request-chip").textContent).toBe("Always asks");
  expect(screen.getByTestId("approval-request-kind").textContent).toBe("Purchase");
  expect(screen.getByTestId("approval-request-always-note").textContent).toMatch(/Bypass/);
});

it("payment details are asked for without quoting what is typed", () => {
  render(<ApprovalRequestCard item={card("", { label: "Card number", severity: "confirm", step_kind: "payment_details", detail: "" })} />);
  expect(screen.getByTestId("approval-request-title").textContent).toBe("May I enter your payment details on play.google.com?");
});

it("shows the live page of the browser it waits in, small", async () => {
  render(<ApprovalRequestCard item={card()} />);
  const live = screen.getByTestId("approval-request-live");
  expect(live.querySelector("img")).toBeNull();
  publishBrowserFrame("jarvis", "data:image/jpeg;base64,AAAA");
  await waitFor(() => expect(live.querySelector("img")?.getAttribute("src")).toBe("data:image/jpeg;base64,AAAA"));
});

it("take over answers the row as taken over and hands the browser to the person", async () => {
  const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ approval: { state: "denied" } }) }) as Response);
  vi.stubGlobal("fetch", fetchMock);
  const opened: unknown[] = [];
  const onOpen = (event: Event) => { opened.push((event as CustomEvent).detail); event.preventDefault(); };
  window.addEventListener(OPEN_AGENT_BROWSER_EVENT, onOpen);
  try {
    render(<ApprovalRequestCard item={card()} />);
    await click("approval-request-take-over");
    await waitFor(() => expect(opened).toEqual([{ agentId: "jarvis", takeover: true }]));
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({ approve: false, note: "taken_over" });
    await waitFor(() => expect(screen.getByTestId("approval-request-closed").textContent).toMatch(/took over/));
  } finally {
    window.removeEventListener(OPEN_AGENT_BROWSER_EVENT, onOpen);
  }
});

it("a blocked action has no buttons and says why", () => {
  const blocked: NoticeItem = {
    type: "notice", id: "b-1", kind: "action_blocked", text: "x is a dark-web address.",
    agentName: "", agentId: "jarvis", status: "blocked", tsMs: 1, resolved: "",
    data: { kind: "action_blocked", category: "dark_web", where: "abc.onion", agent_id: "jarvis" },
  };
  render(<ActionBlockedCard item={blocked} />);
  expect(screen.getByTestId("action-blocked-card").querySelector("button")).toBeNull();
  expect(screen.getByTestId("action-blocked-reason").textContent).toMatch(/dark-web/);
});
