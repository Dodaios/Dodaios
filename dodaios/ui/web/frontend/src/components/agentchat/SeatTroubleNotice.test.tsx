import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { useEventStore } from "@/store/events";
import { SeatTroubleNotice } from "./SeatTroubleNotice";
import type { NoticeItem } from "./reduce";

afterEach(cleanup);

const notice = (fixes: unknown[]): NoticeItem => ({
  type: "notice", id: "n-1", kind: "seat_trouble", text: "Scout could not work the last 3 times.",
  agentName: "Scout", agentId: "a1", status: "", tsMs: 1, data: { fixes }, resolved: "",
});

it("shows the cause and opens the fix screen with one click", () => {
  render(<SeatTroubleNotice item={notice([{ label: "Open API keys", section: "apikeys" }])} />);
  expect(screen.getByText(/last 3 times/)).toBeTruthy();
  fireEvent.click(screen.getByTestId("seat-trouble-fix"));
  expect(useEventStore.getState().activeSection).toBe("apikeys");
});

it("shows no button when the notice names no fix", () => {
  render(<SeatTroubleNotice item={notice([])} />);
  expect(screen.queryByTestId("seat-trouble-fix")).toBeNull();
});
