import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

vi.mock("@/i18n", () => ({ useT: () => (key: string) => key }));
vi.mock("@/hooks/useTheme", () => ({ useThemeValue: () => "light" }));
// The window's chunk is fetched ahead of the click; here only the asking counts.
const preloadNodePeek = vi.hoisted(() => vi.fn());
vi.mock("@/components/nodes/peek/peekFrame", () => ({ preloadNodePeek }));

import { useAgentChatStore } from "@/store/agentChat";
import { useNodePeek } from "@/store/nodePeek";
import { PageCard, PageLink, pageCardData, pageNoticeModes, splitPageRef } from "./PageCard";
import type { NoticeItem, TimelineItem } from "./reduce";

afterEach(() => {
  cleanup();
  useNodePeek.setState({ peek: null, touched: {} });
  preloadNodePeek.mockClear();
});

const PAGE = "run-1::tasks/report/artifacts/files/plan.html";

const notice = (data: Record<string, unknown>, text = "Business plan v1", id = "n-1"): NoticeItem => ({
  type: "notice", id, kind: "report", text, agentName: "", agentId: "",
  status: "", tsMs: 1, data: { kind: "report", ...data }, resolved: "",
} as NoticeItem);

const user = (id: string): TimelineItem => ({ type: "user", id } as TimelineItem);

it("shows one page as a preview card that opens the page beside its conversation and offers the file", () => {
  render(<PageCard item={notice({ summary: "Three decisions are open.", artifact: PAGE, sections: 9 })} />);
  expect(screen.getByText("Business plan v1")).toBeTruthy();
  // What the thing is, in one word under its name.
  expect(screen.getByText("reports.page")).toBeTruthy();
  expect(screen.getByTestId("page-card").getAttribute("data-open")).toBeNull();
  fireEvent.click(screen.getByTestId("page-card-preview"));
  // The node window, not the Nodes section: with the page, its name, and the
  // chat the card stands in (the front page's, with no provider round it).
  const first = useNodePeek.getState().peek;
  expect(first).toMatchObject({ ref: PAGE, slug: "run-1", path: "tasks/report/artifacts/files/plan.html", title: "Business plan v1" });
  expect(first?.chat).toBe(useAgentChatStore);
  // The card of the page that is open says so.
  expect(screen.getByTestId("page-card").getAttribute("data-open")).toBe("true");
  fireEvent.click(screen.getByTestId("page-card-title"));
  expect(useNodePeek.getState().peek?.seq).toBe((first?.seq ?? 0) + 1);
  const download = screen.getByTestId("page-card-download") as HTMLAnchorElement;
  expect(download.getAttribute("href")).toBe("/api/outputs/run-1/files/tasks/report/artifacts/files/plan.html/download?disposition=attachment");
  expect(download.getAttribute("download")).toBe("plan.html");
});

it("shows a page as a link when the turn made several", () => {
  render(<PageCard item={notice({ artifact: PAGE })} mode="link" />);
  expect(screen.queryByTestId("page-card")).toBeNull();
  fireEvent.click(screen.getByTestId("page-link"));
  expect(useNodePeek.getState().peek?.ref).toBe(PAGE);
});

it("fetches the window's code when the pointer or the keyboard reaches a card or a link, before the click", () => {
  render(<PageCard item={notice({ artifact: PAGE })} />);
  expect(preloadNodePeek).not.toHaveBeenCalled();
  fireEvent.pointerEnter(screen.getByTestId("page-card"));
  expect(preloadNodePeek).toHaveBeenCalledTimes(1);
  fireEvent.focus(screen.getByTestId("page-card-title"));
  expect(preloadNodePeek).toHaveBeenCalledTimes(2);
  cleanup();
  preloadNodePeek.mockClear();
  render(<PageLink pageRef={PAGE} label="Plan" />);
  fireEvent.pointerEnter(screen.getByTestId("page-link"));
  expect(preloadNodePeek).toHaveBeenCalledTimes(1);
});

it("draws the preview again once the page's window was closed, so an edit made there shows", () => {
  render(<PageCard item={notice({ artifact: PAGE })} />);
  // jsdom lays nothing out, so the frame itself is not mounted; the card's
  // address for it is what changes.
  useNodePeek.getState().open(PAGE);
  expect(useNodePeek.getState().touched[PAGE]).toBeUndefined();
  useNodePeek.getState().close();
  expect(useNodePeek.getState().touched[PAGE]).toBeGreaterThan(0);
  expect(screen.getByTestId("page-card").getAttribute("data-open")).toBeNull();
});

const SHEET = "run-2__node__abc::tasks/node/artifacts/files/costs.html";
const DECK = "run-3__node__def::tasks/node/artifacts/files/deck.html";
const BOARD = "run-4__node__ghi::tasks/node/artifacts/files/board.html";

it("draws a page the turn posted twice (made, then revised) as ONE card, its last", () => {
  const items = [
    user("u-1"),
    notice({ artifact: SHEET, node_type: "sheets" }, "Trip analysis", "n-1"),
    { type: "turn", id: "t-1" } as TimelineItem,
    notice({ artifact: SHEET, node_type: "sheets" }, "Trip analysis", "n-2"),
    // A notice that cannot open a page does not count as one.
    notice({ artifact: "broken" }, "Broken", "n-3"),
  ];
  const modes = pageNoticeModes(items);
  expect(modes.get("n-1")).toBe("hidden");
  expect(modes.get("n-2")).toBe("preview");
  expect(modes.has("n-3")).toBe(false);

  const { container } = render(<PageCard item={notice({ artifact: SHEET }, "Trip analysis", "n-1")} mode="hidden" />);
  expect(container.innerHTML).toBe("");
});

it("gives every page of a turn its card, and turns to links only for many", () => {
  const few = pageNoticeModes([
    user("u-1"),
    notice({ artifact: PAGE }, "Plan", "n-1"),
    notice({ artifact: SHEET }, "Costs", "n-2"),
    notice({ artifact: PAGE }, "Plan, revised", "n-3"),
    notice({ artifact: DECK }, "Deck", "n-4"),
    user("u-2"),
    notice({ artifact: BOARD }, "Board", "n-5"),
  ]);
  expect(Object.fromEntries(few)).toEqual({
    "n-1": "hidden",
    "n-2": "preview",
    "n-3": "preview",
    "n-4": "preview",
    "n-5": "preview",
  });

  const many = pageNoticeModes([
    user("u-1"),
    notice({ artifact: PAGE }, "Plan", "n-1"),
    notice({ artifact: SHEET }, "Costs", "n-2"),
    notice({ artifact: DECK }, "Deck", "n-3"),
    notice({ artifact: BOARD }, "Board", "n-4"),
    notice({ artifact: BOARD }, "Board", "n-5"),
  ]);
  expect(Object.fromEntries(many)).toEqual({
    "n-1": "link",
    "n-2": "link",
    "n-3": "link",
    "n-4": "hidden",
    "n-5": "link",
  });
});

it("says what a node is under its name, and 'page' for any other page", () => {
  render(<PageCard item={notice({ artifact: SHEET, node_type: "sheets" }, "Costs", "n-1")} />);
  expect(screen.getByTestId("page-card-kind").textContent).toBe("nodes.type.sheets");
  cleanup();
  render(<PageCard item={notice({ artifact: PAGE, node_type: "spreadsheet!" }, "Plan", "n-2")} />);
  expect(screen.getByTestId("page-card-kind").textContent).toBe("reports.page");
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
