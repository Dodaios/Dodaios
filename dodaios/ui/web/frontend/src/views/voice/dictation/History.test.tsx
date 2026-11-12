import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";

import type { DictationEntry } from "@/hooks/useDictation";
import { loadLocaleChunk } from "@/i18n";
import { useEventStore } from "@/store/events";

import { History } from "./History";
import { testEntry } from "./testEntry";

beforeAll(async () => {
  await loadLocaleChunk("voice");
});

beforeEach(() => {
  useEventStore.setState({ toasts: [] });
});

afterEach(cleanup);

function show(entries: DictationEntry[], { loading = false } = {}) {
  const calls = {
    copyEntry: vi.fn().mockResolvedValue(true),
    discardEntry: vi.fn().mockResolvedValue(undefined),
    restoreEntry: vi.fn().mockResolvedValue({
      ok: true,
      entry: entries[0],
      retranscribed: false,
      detail: null,
    }),
    deleteEntry: vi.fn().mockResolvedValue(undefined),
    clearHistory: vi.fn().mockResolvedValue(undefined),
  };
  render(<History entries={entries} loading={loading} rewriteChosen={false} {...calls} />);
  return calls;
}

async function press(name: string) {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name }));
  });
}

const toasts = () => useEventStore.getState().toasts.map(({ kind, message }) => ({ kind, message }));
const shownTexts = () =>
  screen.queryAllByTestId("dictation-entry-text").map((node) => node.textContent);

const hoursAgo = (hours: number) => new Date(Date.now() - hours * 3_600_000).toISOString();

describe("the dictation history", () => {
  it("stands at its place while it loads, without a list or an empty state", () => {
    show([], { loading: true });

    expect(screen.getByTestId("dictation-history-loading")).toBeTruthy();
    expect(screen.queryByTestId("dictation-history-empty")).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete all" })).toBeNull();
  });

  it("says in one sentence that nothing has been dictated yet", () => {
    show([]);

    expect(screen.getByTestId("dictation-history-empty").textContent).toBe(
      "Your dictations appear here.",
    );
    expect(screen.queryByRole("textbox", { name: "Search" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete all" })).toBeNull();
  });

  it("groups entries under their day", () => {
    show([
      testEntry({ id: "now", created_at: new Date().toISOString(), text: "From today." }),
      testEntry({
        id: "old",
        created_at: new Date(2020, 0, 15, 10, 0).toISOString(),
        text: "From long ago.",
      }),
    ]);

    const titles = screen.getAllByRole("heading").map((heading) => heading.textContent);
    expect(titles).toEqual(["Today", "January 15, 2020"]);
    expect(shownTexts()).toEqual(["From today.", "From long ago."]);
  });

  it("searches the delivered and the heard text", () => {
    show([
      testEntry({ id: "a", created_at: hoursAgo(0), text: "Send the report.", raw_text: "um send the report" }),
      testEntry({ id: "b", created_at: hoursAgo(0), text: "Call Anna.", raw_text: "call Anna" }),
    ]);
    const search = screen.getByRole("textbox", { name: "Search" });

    fireEvent.change(search, { target: { value: "anna" } });
    expect(shownTexts()).toEqual(["Call Anna."]);

    fireEvent.change(search, { target: { value: "um send" } });
    expect(shownTexts()).toEqual(["Send the report."]);

    fireEvent.change(search, { target: { value: "nothing like it" } });
    expect(shownTexts()).toEqual([]);
    expect(screen.getByTestId("dictation-history-no-matches").textContent).toBe("No results");
  });

  it("asks once before it deletes everything", async () => {
    const { clearHistory } = show([testEntry()]);

    await press("Delete all");
    expect(clearHistory).not.toHaveBeenCalled();

    await press("Cancel");
    expect(clearHistory).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull();

    await press("Delete all");
    await act(async () => {
      fireEvent.click(screen.getByTestId("dictation-delete-all-confirm"));
    });
    expect(clearHistory).toHaveBeenCalledTimes(1);
  });

  it("passes each action on with the entry's id", async () => {
    const { copyEntry, discardEntry } = show([testEntry({ id: "abc" })]);

    await press("Copy");
    expect(copyEntry).toHaveBeenCalledWith("abc");

    await press("Delete");
    expect(discardEntry).toHaveBeenCalledWith("abc");
    expect(toasts()).toEqual([]);
  });

  it("restores a discarded entry and deletes it for good only on the second step", async () => {
    const { restoreEntry, deleteEntry } = show([testEntry({ id: "abc", discarded: true })]);

    await press("Restore");
    expect(restoreEntry).toHaveBeenCalledWith("abc");
    expect(toasts()).toEqual([]);

    await press("Delete forever");
    expect(deleteEntry).toHaveBeenCalledWith("abc");
  });

  it("says so when a restored recording still gave no words", async () => {
    const entry = testEntry({ id: "abc", discarded: true, text: "", raw_text: "" });
    const { restoreEntry } = show([entry]);
    restoreEntry.mockResolvedValue({
      ok: true,
      entry,
      retranscribed: false,
      detail: "No speech-to-text provider is reachable on this computer.",
    });

    await press("Restore");
    expect(toasts()).toEqual([
      { kind: "warning", message: "The recording could not be transcribed again." },
    ]);
  });

  it("turns a failed action into one plain sentence", async () => {
    const { discardEntry } = show([testEntry()]);
    discardEntry.mockRejectedValue(new Error("HTTP 500"));

    await press("Delete");
    expect(toasts()).toEqual([{ kind: "error", message: "That did not work." }]);
  });

  it("says so when the text could not be copied", async () => {
    const { copyEntry } = show([testEntry()]);
    copyEntry.mockResolvedValue(false);

    await press("Copy");
    expect(toasts()).toEqual([{ kind: "error", message: "Could not copy." }]);
    expect(screen.queryByRole("button", { name: "Copied" })).toBeNull();
  });
});
