import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { useAgentNavigation } from "@/views/society/agentNavigation";
import { BrowserTakeoverNotice } from "./BrowserTakeoverNotice";
import { EMPTY_TIMELINE, reduceEvents } from "./reduce";
import type { NoticeItem } from "./reduce";

afterEach(cleanup);

const card = (resolved = ""): NoticeItem => ({
  type: "notice", id: "n-1", kind: "browser_takeover", text: "Solve the CAPTCHA on the login page.",
  agentName: "", agentId: "lead", status: "waiting", tsMs: 1,
  data: { agent_id: "lead", request_id: "r1" }, resolved,
});

it("shows the reason and opens the agent's live browser", () => {
  render(<BrowserTakeoverNotice item={card()} />);
  expect(screen.getByText(/Solve the CAPTCHA/)).toBeTruthy();
  fireEvent.click(screen.getByTestId("browser-takeover-open"));
  expect(useAgentNavigation.getState().request?.agentId).toBe("lead");
});

it("only says it was handed back once answered", () => {
  render(<BrowserTakeoverNotice item={card("handed_back")} />);
  expect(screen.queryByTestId("browser-takeover-open")).toBeNull();
  expect(screen.getByTestId("browser-takeover-closed")).toBeTruthy();
});

it("the answer patches the card and adds no row", () => {
  const ev = (payload: Record<string, unknown>, seq: number) =>
    ({ kind: "notice", seq, ts_ms: seq, payload }) as never;
  const tl = reduceEvents(EMPTY_TIMELINE, [
    ev({ kind: "browser_takeover", status: "waiting", text: "Enter the code", agent_id: "lead", request_id: "r1" }, 1),
    ev({ kind: "browser_takeover_done", request_id: "r1", status: "handed_back" }, 2),
  ]);
  expect(tl.items).toHaveLength(1);
  const item = tl.items[0];
  if (item.type !== "notice") throw new Error("unreachable");
  expect(item.resolved).toBe("handed_back");
});
