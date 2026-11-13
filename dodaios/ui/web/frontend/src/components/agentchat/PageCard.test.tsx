import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

const requestVisual = vi.fn();

vi.mock("@/i18n", () => ({ useT: () => (key: string) => key }));
vi.mock("@/hooks/useTheme", () => ({ useThemeValue: () => "light" }));
vi.mock("@/store/events", () => ({
  useEventStore: (select: (s: { requestVisual: typeof requestVisual }) => unknown) => select({ requestVisual }),
}));

import { PageCard, PageLink, pageCardData, pageNoticeModes, splitPageRef } from "./PageCard";
import type { NoticeItem, TimelineItem } from "./reduce";

afterEach(() => {
  cleanup();
  requestVisual.mockReset();
});

const PAGE = "run-1::tasks/report/artifacts/files/plan.html";

const notice = (data: Record<string, unknown>, text = "Business plan v1", id = "n-1"): NoticeItem => ({
  type: "notice", id, kind: "report", text, agentName: "", agentId: "",
  status: "", tsMs: 1, data: { kind: "report", ...data }, resolved: "",
} as NoticeItem);

const user = (id: string): TimelineItem => ({ type: "user", id } as TimelineItem);

it("shows one page as a preview card that opens the page and offers the file", () => {
  render(<PageCard item={notice({ summary: "Three decisions are open.", artifact: PAGE, sections: 9 })} />);
  expect(screen.getByText("Business plan v1")).toBeTruthy();
  // What the thing is, in one word under its name.
  expect(screen.getByText("reports.page")).toBeTruthy();
  fireEvent.click(screen.getByTestId("page-card-preview"));
  fireEvent.click(screen.getByTestId("page-card-title"));
  expect(requestVisual.mock.calls).toEqual([[PAGE], [PAGE]]);
  const download = screen.getByTestId("page-card-download") as HTMLAnchorElement;
  expect(download.getAttribute("href")).toBe("/api/outputs/run-1/files/tasks/report/artifacts/files/plan.html/download?disposition=attachment");
  expect(download.getAttribute("download")).toBe("plan.html");
});

it("shows a page as a link when the turn made several", () => {
  render(<PageCard item={notice({ artifact: PAGE })} mode="link" />);
  expect(screen.queryByTestId("page-card")).toBeNull();
  fireEvent.click(screen.getByTestId("page-link"));
  expect(requestVisual).toHaveBeenCalledWith(PAGE);
});

it("decides per turn: one page is a preview, several are links", () => {
  const items = [
    user("u-1"),
    notice({ artifact: PAGE }, "Alone", "n-1"),
    user("u-2"),
    notice({ artifact: PAGE }, "First", "n-2"),
    { type: "turn", id: "t-1" } as TimelineItem,
    notice({ artifact: PAGE }, "Second", "n-3"),
    // A notice that cannot open a page does not count as one.
    notice({ artifact: "broken" }, "Broken", "n-4"),
  ];
  const modes = pageNoticeModes(items);
  expect(modes.get("n-1")).toBe("preview");
  expect(modes.get("n-2")).toBe("link");
  expect(modes.get("n-3")).toBe("link");
  expect(modes.has("n-4")).toBe(false);
});

it("draws nothing when the card cannot open a page", () => {
  expect(pageCardData(notice({ artifact: "no-separator" }))).toBeNull();
  expect(pageCardData(notice({ artifact: "a::b" }, " "))).toBeNull();
  expect(splitPageRef("::b")).toBeNull();
  const { container } = render(<PageCard item={notice({})} />);
  expect(container.innerHTML).toBe("");
});

it("names a link after the file when the answer gave no label", () => {
  render(<PageLink pageRef={PAGE} label=" " />);
  expect(screen.getByText("plan.html")).toBeTruthy();
});
