import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { MemoryLearnedNotice } from "./MemoryLearnedNotice";
import type { NoticeItem } from "./reduce";

vi.mock("@/i18n", () => ({ useT: () => (key: string) => key }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const notice = (items: unknown[]): NoticeItem => ({
  type: "notice", id: "n-1", kind: "memory_learned", text: "", agentName: "", agentId: "",
  status: "done", tsMs: 1, data: { items }, resolved: "",
});

it("shows each learned memory and forgets an added one on undo", async () => {
  const fetcher = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify({ forgotten: 1 })));
  vi.stubGlobal("fetch", fetcher);
  render(<MemoryLearnedNotice item={notice([
    { op: "added", id: "m1", text: "Sister's wedding is in Lisbon in June" },
    { op: "updated", id: "m2", text: "Lives in Berlin" },
  ])} />);
  expect(screen.getByText(/Lisbon/)).toBeTruthy();
  expect(screen.getByText(/Berlin/)).toBeTruthy();
  // Only an added memory offers an undo; forgetting an update would erase its history.
  const undo = screen.getAllByTestId("memory-learned-undo");
  expect(undo).toHaveLength(1);
  fireEvent.click(undo[0]);
  await waitFor(() => expect(screen.getByText("society.chat.memory_learned_undone")).toBeTruthy());
  expect(String(fetcher.mock.calls[0][0])).toContain("/items/m1");
});

it("renders nothing without rows", () => {
  const { container } = render(<MemoryLearnedNotice item={notice([])} />);
  expect(container.textContent).toBe("");
});
