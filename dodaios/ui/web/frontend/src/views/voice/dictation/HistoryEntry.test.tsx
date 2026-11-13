import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";

import type { DictationEntry } from "@/hooks/useDictation";
import { loadLocaleChunk } from "@/i18n";

import { HistoryEntry } from "./HistoryEntry";
import { testEntry } from "./testEntry";

beforeAll(async () => {
  await loadLocaleChunk("voice");
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

function show(entry: DictationEntry, { rewriteChosen = false } = {}) {
  const actions = {
    onCopy: vi.fn().mockResolvedValue(true),
    onDiscard: vi.fn().mockResolvedValue(undefined),
    onRestore: vi.fn().mockResolvedValue(undefined),
    onDelete: vi.fn().mockResolvedValue(undefined),
  };
  render(
    <HistoryEntry entry={entry} locale="en-US" rewriteChosen={rewriteChosen} {...actions} />,
  );
  return actions;
}

const text = () => screen.getByTestId("dictation-entry-text");
const remark = () => screen.queryByTestId("dictation-entry-remark");
const action = (name: string) => screen.queryByRole("button", { name });

async function press(name: string) {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name }));
  });
}

describe("a history entry", () => {
  it("shows the delivered text and the time, and no remark when it simply arrived", () => {
    const entry = testEntry({ text: "Send the report.", raw_text: "send the report" });
    show(entry);

    expect(text().textContent).toBe("Send the report.");
    const time = new Date(entry.created_at).toLocaleTimeString("en-US", {
      hour: "numeric",
      minute: "2-digit",
    });
    expect(screen.getByText(time).tagName).toBe("TIME");
    expect(remark()).toBeNull();
  });

  it.each(["inserted", "paste_sent", "chat"])("has no remark for the outcome %s", (outcome) => {
    show(testEntry({ outcome }));
    expect(remark()).toBeNull();
  });

  it.each([
    ["partial", "Partly transcribed"],
    ["clipboard_only", "Copied to clipboard"],
    ["unavailable", "Could not insert"],
    ["empty", "Nothing heard"],
    ["cancelled", "Cancelled"],
    ["failed", "Failed"],
  ])("says what became of a dictation that ended as %s", (outcome, words) => {
    show(testEntry({ outcome }));
    expect(remark()?.textContent).toBe(words);
  });

  it("shows nothing for an outcome this build does not know", () => {
    show(testEntry({ outcome: "beamed_up" }));
    expect(remark()).toBeNull();
    expect(screen.queryByText(/beamed_up/)).toBeNull();
  });

  it("says why a transcription failed", () => {
    show(testEntry({ outcome: "failed", text: "", raw_text: "", error: "no_credit" }));
    expect(remark()?.textContent).toBe("The speech recognition account is out of credit.");
  });

  it("never prints a failure it does not know", () => {
    show(
      testEntry({
        outcome: "failed",
        text: "",
        raw_text: "",
        error: "HTTPStatusError: 429 https://example.invalid",
      }),
    );
    expect(remark()?.textContent).toBe("Speech recognition failed.");
    expect(screen.queryByText(/HTTPStatusError/)).toBeNull();
  });

  it("mentions a wording pass that fell back only while a rewrite is switched on", () => {
    const entry = testEntry({ polish_status: "timeout" });

    show(entry);
    expect(remark()).toBeNull();
    cleanup();

    show(entry, { rewriteChosen: true });
    expect(remark()?.textContent).toContain("Took too long");
  });

  it.each(["applied", "translated", "prompted", "unchanged", "off", "skipped_short", "skipped_long"])(
    "has no remark for the ordinary wording status %s",
    (status) => {
      show(testEntry({ polish_status: status }), { rewriteChosen: true });
      expect(remark()).toBeNull();
    },
  );

  it("keeps what was heard closed until the entry is opened", async () => {
    show(testEntry({ text: "Send the report.", raw_text: "um send the the report" }));

    expect(screen.queryByTestId("dictation-entry-heard")).toBeNull();
    await press("What was heard");
    expect(screen.getByTestId("dictation-entry-heard").textContent).toBe("um send the the report");
    expect(action("What was heard")?.getAttribute("aria-expanded")).toBe("true");

    await press("What was heard");
    expect(screen.queryByTestId("dictation-entry-heard")).toBeNull();
  });

  it("offers nothing to open when the delivered text is what was heard", () => {
    show(testEntry({ text: "Same words.", raw_text: "Same words." }));
    expect(action("What was heard")).toBeNull();
  });

  it("copies, and says so for a moment", async () => {
    vi.useFakeTimers();
    const entry = testEntry();
    const { onCopy } = show(entry);

    await press("Copy");
    expect(onCopy).toHaveBeenCalledWith(entry);
    expect(action("Copied")).not.toBeNull();

    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(action("Copied")).toBeNull();
    expect(action("Copy")).not.toBeNull();
  });

  it("does not claim a copy that did not happen", async () => {
    const { onCopy } = show(testEntry());
    onCopy.mockResolvedValue(false);

    await press("Copy");
    expect(action("Copied")).toBeNull();
  });

  it("discards on delete, and does not remove the entry for good", async () => {
    const entry = testEntry();
    const { onDiscard, onDelete } = show(entry);

    await press("Delete");
    expect(onDiscard).toHaveBeenCalledWith(entry);
    expect(onDelete).not.toHaveBeenCalled();
    expect(action("Delete forever")).toBeNull();
  });

  it("strikes a discarded entry out and offers to restore it or delete it for good", async () => {
    const entry = testEntry({ discarded: true });
    const { onRestore, onDelete, onDiscard } = show(entry);

    expect(text().className).toContain("line-through");
    expect(action("Copy")).toBeNull();
    expect(action("Delete")).toBeNull();

    await press("Restore");
    expect(onRestore).toHaveBeenCalledWith(entry);

    await press("Delete forever");
    expect(onDelete).toHaveBeenCalledWith(entry);
    expect(onDiscard).not.toHaveBeenCalled();
  });

  it("offers to transcribe a kept recording again when no words arrived", async () => {
    const entry = testEntry({
      outcome: "failed",
      text: "",
      raw_text: "",
      error: "unavailable",
      audio_available: true,
    });
    const { onRestore } = show(entry);

    expect(screen.queryByTestId("dictation-entry-text")).toBeNull();
    expect(action("Copy")).toBeNull();

    await press("Transcribe again");
    expect(onRestore).toHaveBeenCalledWith(entry);
  });

  it("offers to transcribe a partly transcribed recording again", async () => {
    const entry = testEntry({
      outcome: "partial",
      text: "Only the first words",
      raw_text: "Only the first words",
      error: "engine_busy",
      audio_available: true,
    });
    const { onRestore } = show(entry);

    await press("Transcribe again");
    expect(onRestore).toHaveBeenCalledWith(entry);
  });

  it("does not offer it for a partial entry whose recording is gone", () => {
    show(testEntry({ outcome: "partial", audio_available: false }));
    expect(action("Transcribe again")).toBeNull();
  });

  it("does not offer to transcribe again when the words are already there", () => {
    show(testEntry({ audio_available: true }));
    expect(action("Transcribe again")).toBeNull();
  });

  it("holds its actions while one is under way", async () => {
    const { onDiscard } = show(testEntry());
    let finish: () => void = () => {};
    onDiscard.mockReturnValue(
      new Promise<void>((resolve) => {
        finish = resolve;
      }),
    );

    await press("Delete");
    expect((action("Delete") as HTMLButtonElement).disabled).toBe(true);

    await act(async () => {
      finish();
    });
    expect((action("Delete") as HTMLButtonElement).disabled).toBe(false);
  });
});
