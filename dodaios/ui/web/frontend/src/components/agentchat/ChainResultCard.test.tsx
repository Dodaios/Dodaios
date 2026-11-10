import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

const requestVisual = vi.fn();
const openExternalUrl = vi.fn(async (_url: string) => true);

vi.mock("@/i18n", () => ({ useT: () => (key: string) => key }));
vi.mock("@/lib/openExternal", () => ({ openExternalUrl: (url: string) => openExternalUrl(url) }));
vi.mock("@/store/events", () => ({
  useEventStore: (select: (s: { requestVisual: typeof requestVisual }) => unknown) => select({ requestVisual }),
}));

import { ChainResultCard, chainResultRows } from "./ChainResultCard";
import type { NoticeItem } from "./reduce";

afterEach(() => {
  cleanup();
  requestVisual.mockReset();
  openExternalUrl.mockClear();
});

const notice = (items: unknown[], text = "Mail from Anna"): NoticeItem => ({
  type: "notice", id: "n-1", kind: "chain_result", text, agentName: "", agentId: "",
  status: "", tsMs: 1, data: { kind: "chain_result", items }, resolved: "",
});

it("lists what was made with its state and opens each in its place", () => {
  render(<ChainResultCard item={notice([
    { kind: "event", label: "Lunch, Fri 12:30", state: "created", url: "https://cal.example/e/1" },
    { kind: "draft", label: "Reply to Anna", state: "waiting" },
    { kind: "page", label: "My parcels", state: "created", artifact: "run-1::tasks/living/artifacts/files/p.html" },
  ])} />);
  expect(screen.getByTestId("chain-result-card")).toBeTruthy();
  expect(screen.getByText("Lunch, Fri 12:30")).toBeTruthy();
  expect(screen.getByText("living_pages.state_waiting")).toBeTruthy();
  const opens = screen.getAllByRole("button");
  // The draft has no link, so two rows open something.
  expect(opens).toHaveLength(2);
  fireEvent.click(opens[0]);
  expect(openExternalUrl).toHaveBeenCalledWith("https://cal.example/e/1");
  fireEvent.click(opens[1]);
  expect(requestVisual).toHaveBeenCalledWith("run-1::tasks/living/artifacts/files/p.html");
});

it("drops unsafe links, unknown kinds and empty rows", () => {
  const rows = chainResultRows({
    items: [
      { kind: "bomb", label: "Thing", state: "weird", url: "javascript:alert(1)" },
      { kind: "task", label: "" },
      "junk",
    ],
  });
  expect(rows).toEqual([
    { kind: "other", label: "Thing", state: "created", url: undefined, artifact: undefined, detail: undefined },
  ]);
});

it("renders nothing without rows", () => {
  const { container } = render(<ChainResultCard item={notice([])} />);
  expect(container.textContent).toBe("");
});
