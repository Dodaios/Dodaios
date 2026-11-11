import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

const requestVisual = vi.fn();

vi.mock("@/i18n", () => ({ useT: () => (key: string) => key }));
vi.mock("@/store/events", () => ({
  useEventStore: (select: (s: { requestVisual: typeof requestVisual }) => unknown) => select({ requestVisual }),
}));

import { ReportCard, reportCardData } from "./ReportCard";
import type { NoticeItem } from "./reduce";

afterEach(() => {
  cleanup();
  requestVisual.mockReset();
});

const notice = (data: Record<string, unknown>, text = "Mails, 6-11 Nov"): NoticeItem => ({
  type: "notice", id: "n-1", kind: "report", text, agentName: "", agentId: "",
  status: "", tsMs: 1, data: { kind: "report", ...data }, resolved: "",
} as NoticeItem);

it("shows the report's title and gist and opens its page", () => {
  render(<ReportCard item={notice({ summary: "Two bills need you.", artifact: "run-1::tasks/report/artifacts/files/m.html", sections: 3 })} />);
  expect(screen.getByText("Mails, 6-11 Nov")).toBeTruthy();
  expect(screen.getByText("Two bills need you.")).toBeTruthy();
  expect(screen.getByText("reports.label · reports.sections")).toBeTruthy();
  fireEvent.click(screen.getByTestId("report-card"));
  expect(requestVisual).toHaveBeenCalledWith("run-1::tasks/report/artifacts/files/m.html");
});

it("draws nothing when the card cannot open a page", () => {
  expect(reportCardData(notice({ artifact: "no-separator" }))).toBeNull();
  expect(reportCardData(notice({ artifact: "a::b" }, " "))).toBeNull();
  const { container } = render(<ReportCard item={notice({})} />);
  expect(container.innerHTML).toBe("");
});
