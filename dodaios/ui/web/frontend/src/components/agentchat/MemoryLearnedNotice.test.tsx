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

it("links a learned memory back to the message it came from", async () => {
  const said = document.createElement("p");
  said.dataset.messageId = "u-41";
  said.textContent = "By the way, I live in Hamburg.";
  said.scrollIntoView = vi.fn();
  document.body.appendChild(said);
  try {
    render(<MemoryLearnedNotice item={notice([
      { op: "added", id: "m1", text: "Lives in Hamburg", message_seq: 41, evidence: "I live in Hamburg" },
      { op: "added", id: "m2", text: "Likes tea" },
    ])} />);
    const links = screen.getAllByTestId("memory-learned-source");
    // A row without any trace of where it was said offers no link.
    expect(links).toHaveLength(1);
    fireEvent.click(links[0]);
    await waitFor(() => expect(said.scrollIntoView).toHaveBeenCalled());
  } finally {
    said.remove();
  }
});

it("says so when the source message is not on screen", async () => {
  render(<MemoryLearnedNotice item={notice([
    { op: "added", id: "m1", text: "Lives in Hamburg", message_seq: 7, evidence: "I live in Hamburg" },
  ])} />);
  fireEvent.click(screen.getByTestId("memory-learned-source"));
  await waitFor(() => expect(screen.getByTestId("memory-learned-source-missing")).toBeTruthy());
});

it("renders nothing without rows", () => {
  const { container } = render(<MemoryLearnedNotice item={notice([])} />);
  expect(container.textContent).toBe("");
});
