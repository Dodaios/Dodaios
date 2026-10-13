import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { NoticeItem } from "@/components/agentchat/reduce";
import { TeamReportNotice } from "./TeamReportNotice";

vi.mock("@/i18n", () => ({ useT: () => (key: string) => key }));
vi.mock("@/components/agentchat/ChatMarkdown", () => ({ ChatMarkdown: ({ text }: { text: string }) => <p>{text}</p> }));

afterEach(cleanup);

function notice(status: string, over: Partial<NoticeItem> = {}): NoticeItem {
  return {
    type: "notice", id: "n-1", kind: "team_report", text: "Which market?", agentName: "Boss", agentId: "boss",
    status, tsMs: 1, data: { title: "Plan the launch" }, resolved: "", ...over,
  };
}

it.each([
  ["done", "society.lead.card_done"],
  ["needs_input", "society.lead.card_needs_input"],
  ["failed", "society.lead.card_failed"],
  ["progress", "society.lead.card_progress"],
  ["something-new", "society.lead.card_progress"],
])("shows a %s report in the chat with its goal and its words", (status, label) => {
  render(<TeamReportNotice item={notice(status)} />);
  const card = screen.getByTestId("team-report-notice");
  expect(card.getAttribute("data-status")).toBe(status);
  expect(screen.getByText(label)).toBeTruthy();
  expect(screen.getByText("· Plan the launch")).toBeTruthy();
  expect(screen.getByText("Which market?")).toBeTruthy();
});

it("shows a report whose goal has no title", () => {
  render(<TeamReportNotice item={notice("done", { data: {} })} />);
  expect(screen.getByText("society.lead.card_done")).toBeTruthy();
  expect(screen.queryByText(/^· /)).toBeNull();
});
