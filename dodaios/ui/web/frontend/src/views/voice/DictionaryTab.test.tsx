import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { DictionaryEntry } from "@/hooks/useDictionary";
import { loadLocaleChunk, useI18nStore } from "@/i18n";
import { DictionaryTab } from "@/views/voice/DictionaryTab";

const hook = vi.hoisted(() => ({
  state: {
    entries: [] as unknown[],
    loading: false,
    error: null as string | null,
    refetch: vi.fn(),
    createEntry: vi.fn(),
    updateEntry: vi.fn(),
    removeEntry: vi.fn(),
  },
}));

vi.mock("@/hooks/useDictionary", () => ({
  useDictionary: () => hook.state,
}));

function entry(id: string, word: string, misheard: string[] = []): DictionaryEntry {
  return { id, word, misheard, created_at: "", updated_at: "" };
}

function rowTexts(): string[] {
  return [...document.querySelectorAll('[data-testid^="word-row-"]')].map(
    (row) => row.textContent ?? "",
  );
}

function type(testId: string, value: string) {
  fireEvent.change(screen.getByTestId(testId), { target: { value } });
}

beforeAll(async () => {
  useI18nStore.setState({ ui: "en" });
  await loadLocaleChunk("voice");
});

beforeEach(() => {
  hook.state.entries = [];
  hook.state.loading = false;
  hook.state.error = null;
  hook.state.refetch = vi.fn().mockResolvedValue(undefined);
  hook.state.createEntry = vi.fn().mockResolvedValue(entry("new", "x"));
  hook.state.updateEntry = vi.fn().mockResolvedValue(entry("a", "x"));
  hook.state.removeEntry = vi.fn().mockResolvedValue(undefined);
});

afterEach(cleanup);

describe("DictionaryTab states", () => {
  it("shows a loading group, and no empty state, while the words load", () => {
    hook.state.loading = true;
    render(<DictionaryTab />);
    expect(screen.getByTestId("words-loading")).toBeTruthy();
    expect(screen.queryByTestId("words-empty")).toBeNull();
    expect(screen.queryByTestId("word-add")).toBeNull();
  });

  it("says in one sentence that loading failed and offers to try again", () => {
    hook.state.error = "HTTP 500";
    render(<DictionaryTab />);
    expect(screen.getByTestId("words-load-failed").textContent).toContain(
      "Your words could not be loaded.",
    );
    // The backend's own wording is not shown.
    expect(screen.queryByText(/HTTP 500/)).toBeNull();
    expect(screen.queryByTestId("words-empty")).toBeNull();
  });

  it("loads again on retry and shows the loading group meanwhile", async () => {
    hook.state.error = "HTTP 500";
    let finish: () => void = () => {};
    hook.state.refetch = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    render(<DictionaryTab />);
    fireEvent.click(screen.getByTestId("words-retry"));
    expect(hook.state.refetch).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("words-loading")).toBeTruthy();
    finish();
    await waitFor(() => expect(screen.queryByTestId("words-loading")).toBeNull());
  });

  it("shows one sentence and the Add action when there are no words", () => {
    render(<DictionaryTab />);
    const empty = screen.getByTestId("words-empty");
    expect(empty.textContent).toContain("No words yet.");
    expect(screen.queryByTestId("word-search")).toBeNull();
    fireEvent.click(screen.getByTestId("word-add"));
    expect(screen.getByTestId("word-editor")).toBeTruthy();
    expect(screen.queryByTestId("words-empty")).toBeNull();
  });

  it("never shows a raw string key", () => {
    hook.state.entries = [entry("a", "Quokka")];
    const { container } = render(<DictionaryTab />);
    fireEvent.click(screen.getByTestId("word-add"));
    expect(container.textContent).not.toContain("voiceui.");
    expect(container.innerHTML).not.toContain("voiceui.");
  });
});

describe("DictionaryTab list", () => {
  it("lists words in alphabetical order, a correction as heard and word", () => {
    hook.state.entries = [
      entry("a", "Zebra"),
      entry("b", "the", ["teh", "tee"]),
      entry("c", "apple"),
    ];
    render(<DictionaryTab />);
    expect(rowTexts()).toEqual(["apple", "the teh, tee", "Zebra"]);
  });

  it("filters by the word and by what it is heard as", () => {
    hook.state.entries = [entry("a", "Zebra"), entry("b", "the", ["teh"]), entry("c", "apple")];
    render(<DictionaryTab />);
    type("word-search", "ZEB");
    expect(rowTexts()).toEqual(["Zebra"]);
    type("word-search", "teh");
    expect(rowTexts()).toEqual(["the teh"]);
  });

  it("says so when the search finds nothing", () => {
    hook.state.entries = [entry("a", "Zebra")];
    render(<DictionaryTab />);
    type("word-search", "qqq");
    expect(rowTexts()).toEqual([]);
    expect(screen.getByTestId("words-no-results").textContent).toContain("No results");
  });

  it("deletes an entry through the hook", async () => {
    hook.state.entries = [entry("a", "Zebra"), entry("b", "apple")];
    render(<DictionaryTab />);
    fireEvent.click(screen.getByTestId("word-delete-a"));
    expect(hook.state.removeEntry).toHaveBeenCalledWith("a");
    await waitFor(() =>
      expect((screen.getByTestId("word-delete-a") as HTMLButtonElement).disabled).toBe(false),
    );
    expect(screen.queryByTestId("words-delete-failed")).toBeNull();
  });

  it("says in one sentence that a delete failed", async () => {
    hook.state.entries = [entry("a", "Zebra")];
    hook.state.removeEntry = vi.fn().mockRejectedValue(new Error("HTTP 500"));
    render(<DictionaryTab />);
    fireEvent.click(screen.getByTestId("word-delete-a"));
    const notice = await screen.findByTestId("words-delete-failed");
    expect(notice.textContent).toContain("This word could not be deleted.");
    expect(screen.queryByText(/HTTP 500/)).toBeNull();
  });
});

describe("DictionaryTab editor", () => {
  it("has a visible label for each of its two fields", () => {
    hook.state.entries = [entry("a", "Zebra")];
    render(<DictionaryTab />);
    fireEvent.click(screen.getByTestId("word-add"));
    expect(screen.getByLabelText("Word")).toBe(screen.getByTestId("word-field"));
    expect(screen.getByLabelText("Heard as")).toBe(screen.getByTestId("heard-as-field"));
  });

  it("cannot save without a word", () => {
    render(<DictionaryTab />);
    fireEvent.click(screen.getByTestId("word-add"));
    expect((screen.getByTestId("word-save") as HTMLButtonElement).disabled).toBe(true);
    type("word-field", "   ");
    expect((screen.getByTestId("word-save") as HTMLButtonElement).disabled).toBe(true);
    type("word-field", "Quokka");
    expect((screen.getByTestId("word-save") as HTMLButtonElement).disabled).toBe(false);
  });

  it("adds a plain word with no heard-as spellings", async () => {
    render(<DictionaryTab />);
    fireEvent.click(screen.getByTestId("word-add"));
    type("word-field", "  Quokka ");
    fireEvent.submit(screen.getByTestId("word-editor"));
    expect(hook.state.createEntry).toHaveBeenCalledWith({ word: "Quokka", misheard: [] });
    await waitFor(() => expect(screen.queryByTestId("word-editor")).toBeNull());
  });

  it("adds a correction, splitting what is heard at the commas", () => {
    render(<DictionaryTab />);
    fireEvent.click(screen.getByTestId("word-add"));
    type("word-field", "Quokka");
    type("heard-as-field", "kwoka, , quocka ");
    fireEvent.click(screen.getByTestId("word-save"));
    expect(hook.state.createEntry).toHaveBeenCalledWith({
      word: "Quokka",
      misheard: ["kwoka", "quocka"],
    });
  });

  it("clears the search when adding, so the new word is not filtered away", () => {
    hook.state.entries = [entry("a", "Zebra")];
    render(<DictionaryTab />);
    type("word-search", "zeb");
    fireEvent.click(screen.getByTestId("word-add"));
    expect((screen.getByTestId("word-search") as HTMLInputElement).value).toBe("");
  });

  it("edits an entry in place with its values filled in", async () => {
    hook.state.entries = [entry("a", "the", ["teh", "tee"]), entry("b", "Zebra")];
    render(<DictionaryTab />);
    fireEvent.click(screen.getByTestId("word-edit-a"));
    expect(screen.queryByTestId("word-row-a")).toBeNull();
    expect(screen.getByTestId("word-row-b")).toBeTruthy();
    expect((screen.getByTestId("word-field") as HTMLInputElement).value).toBe("the");
    expect((screen.getByTestId("heard-as-field") as HTMLInputElement).value).toBe("teh, tee");
    type("heard-as-field", "");
    fireEvent.click(screen.getByTestId("word-save"));
    expect(hook.state.updateEntry).toHaveBeenCalledWith("a", { word: "the", misheard: [] });
    expect(hook.state.createEntry).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getByTestId("word-row-a")).toBeTruthy());
  });

  it("keeps the edited entry in view while the search changes", () => {
    hook.state.entries = [entry("a", "the"), entry("b", "Zebra")];
    render(<DictionaryTab />);
    fireEvent.click(screen.getByTestId("word-edit-a"));
    type("word-search", "zeb");
    expect(screen.getByTestId("word-editor")).toBeTruthy();
    expect(rowTexts()).toEqual(["Zebra"]);
  });

  it("says at the field that a word is already there, and does not send it", () => {
    hook.state.entries = [entry("a", "Zebra")];
    render(<DictionaryTab />);
    fireEvent.click(screen.getByTestId("word-add"));
    type("word-field", "zebra");
    fireEvent.click(screen.getByTestId("word-save"));
    expect(hook.state.createEntry).not.toHaveBeenCalled();
    expect(screen.getByTestId("word-editor-fault").textContent).toContain(
      "This word is already in your list.",
    );
    // Typing again takes the sentence away.
    type("word-field", "zebras");
    expect(screen.queryByTestId("word-editor-fault")).toBeNull();
  });

  it("lets an entry keep its own word when it is edited", () => {
    hook.state.entries = [entry("a", "Zebra")];
    render(<DictionaryTab />);
    fireEvent.click(screen.getByTestId("word-edit-a"));
    type("heard-as-field", "sebra");
    fireEvent.click(screen.getByTestId("word-save"));
    expect(hook.state.updateEntry).toHaveBeenCalledWith("a", { word: "Zebra", misheard: ["sebra"] });
  });

  it("stays open with one sentence when the save fails", async () => {
    hook.state.createEntry = vi.fn().mockRejectedValue(new Error("Dictionary is full"));
    render(<DictionaryTab />);
    fireEvent.click(screen.getByTestId("word-add"));
    type("word-field", "Quokka");
    fireEvent.click(screen.getByTestId("word-save"));
    const fault = await screen.findByTestId("word-editor-fault");
    expect(fault.textContent).toContain("This word could not be saved.");
    expect(screen.queryByText(/Dictionary is full/)).toBeNull();
    expect((screen.getByTestId("word-field") as HTMLInputElement).value).toBe("Quokka");
    expect((screen.getByTestId("word-save") as HTMLButtonElement).disabled).toBe(false);
  });

  it("closes without saving on Cancel and on Escape", () => {
    hook.state.entries = [entry("a", "Zebra")];
    render(<DictionaryTab />);
    fireEvent.click(screen.getByTestId("word-add"));
    type("word-field", "Quokka");
    fireEvent.click(screen.getByTestId("word-cancel"));
    expect(screen.queryByTestId("word-editor")).toBeNull();

    fireEvent.click(screen.getByTestId("word-edit-a"));
    fireEvent.keyDown(screen.getByTestId("word-field"), { key: "Escape" });
    expect(screen.queryByTestId("word-editor")).toBeNull();
    expect(hook.state.createEntry).not.toHaveBeenCalled();
    expect(hook.state.updateEntry).not.toHaveBeenCalled();
  });
});
