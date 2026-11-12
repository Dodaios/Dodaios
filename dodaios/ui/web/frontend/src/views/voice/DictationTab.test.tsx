import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";

import type { DictationStatus } from "@/hooks/useDictation";
import { loadLocaleChunk } from "@/i18n";
import { useEventStore } from "@/store/events";
import { formatCombo } from "@/views/settings/KeybindRow";
import { testEntry } from "@/views/voice/dictation/testEntry";

import { DictationTab } from "./DictationTab";

const hook = vi.hoisted(() => ({ value: {} as Record<string, unknown> }));

vi.mock("@/hooks/useDictation", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useDictation")>()),
  useDictation: () => hook.value,
}));

function status(overrides: Partial<DictationStatus> = {}): DictationStatus {
  return {
    available: true,
    active: false,
    reason: "",
    hotkey: "ctrl+alt",
    hotkey_toggle: "",
    mode: "hold",
    target: "auto",
    insertion: { can_insert: true, reason: "", detail: "" },
    ...overrides,
  };
}

/** What the data hook returns; a case overrides the part it is about. */
function dictation(overrides: Record<string, unknown> = {}) {
  hook.value = {
    status: status(),
    settings: null,
    entries: [],
    loading: false,
    error: null,
    start: vi.fn().mockResolvedValue(undefined),
    stop: vi.fn().mockResolvedValue(undefined),
    copyEntry: vi.fn().mockResolvedValue(true),
    discardEntry: vi.fn().mockResolvedValue(undefined),
    restoreEntry: vi.fn().mockResolvedValue({ ok: true, retranscribed: false, detail: null }),
    deleteEntry: vi.fn().mockResolvedValue(undefined),
    clearHistory: vi.fn().mockResolvedValue(undefined),
    refetch: vi.fn().mockResolvedValue(undefined),
    refetchStatus: vi.fn().mockResolvedValue(undefined),
    refetchHistory: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
  return hook.value as Record<string, ReturnType<typeof vi.fn>>;
}

async function press(name: string) {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name }));
  });
}

const headline = () => screen.queryByTestId("dictation-headline");
const toggle = () => screen.queryByTestId("dictation-toggle") as HTMLButtonElement | null;
const toasts = () => useEventStore.getState().toasts.map(({ kind, message }) => ({ kind, message }));

beforeAll(async () => {
  await loadLocaleChunk("voice");
});

beforeEach(() => {
  useEventStore.setState({ toasts: [], activeSection: "dictation" });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("the Dictation tab", () => {
  it("shows placeholders while it loads, and no button, notice or empty state", () => {
    dictation({ status: null, loading: true });
    render(<DictationTab />);

    expect(screen.getByTestId("dictation-row-loading")).toBeTruthy();
    expect(screen.getByTestId("dictation-history-loading")).toBeTruthy();
    expect(toggle()).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByTestId("dictation-history-empty")).toBeNull();
  });

  it("names the configured shortcut, one cap per key", () => {
    dictation();
    render(<DictationTab />);

    const caps = [...(headline()?.querySelectorAll("kbd") ?? [])].map((cap) => cap.textContent);
    expect(caps).toEqual(formatCombo("ctrl+alt").split(" + "));
    expect(caps).toHaveLength(2);
    expect(headline()?.textContent).toMatch(/^Hold.*to dictate$/);
  });

  it("names the press-once shortcut when there is no hold shortcut", () => {
    dictation({ status: status({ hotkey: "", hotkey_toggle: "f9" }) });
    render(<DictationTab />);

    expect(headline()?.textContent).toMatch(/^Press.*to dictate$/);
    expect(headline()?.querySelectorAll("kbd")).toHaveLength(1);
  });

  it("points at the microphone when no shortcut is set", () => {
    dictation({ status: status({ hotkey: "", hotkey_toggle: "" }) });
    render(<DictationTab />);

    expect(headline()?.textContent).toBe("Click the microphone to dictate");
  });

  it("starts a dictation from the microphone button", async () => {
    const { start, stop } = dictation();
    render(<DictationTab />);

    await press("Start dictation");
    expect(start).toHaveBeenCalledWith("auto");
    expect(stop).not.toHaveBeenCalled();
  });

  it("says it is listening while one runs, and the button stops it", async () => {
    const { start, stop } = dictation({ status: status({ active: true }) });
    render(<DictationTab />);

    expect(headline()?.textContent).toBe("Listening");
    await press("Stop dictation");
    expect(stop).toHaveBeenCalledTimes(1);
    expect(start).not.toHaveBeenCalled();
  });

  it("keeps checking whether a running dictation still runs", () => {
    vi.useFakeTimers();
    const { refetchStatus } = dictation({ status: status({ active: true }) });
    render(<DictationTab />);

    expect(refetchStatus).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(4500);
    });
    expect(refetchStatus).toHaveBeenCalledTimes(2);
  });

  it("does not poll while nothing runs", () => {
    vi.useFakeTimers();
    const { refetchStatus } = dictation();
    render(<DictationTab />);

    act(() => {
      vi.advanceTimersByTime(10_000);
    });
    expect(refetchStatus).not.toHaveBeenCalled();
  });

  it("reloads the history when a dictation has ended", () => {
    const first = dictation({ status: status({ active: true }) });
    const { rerender } = render(<DictationTab />);
    expect(first.refetchHistory).not.toHaveBeenCalled();

    const second = dictation({ status: status({ active: false }) });
    rerender(<DictationTab />);
    expect(second.refetchHistory).toHaveBeenCalledTimes(1);
  });

  it("says in one sentence when a dictation could not start", async () => {
    const { start } = dictation();
    start.mockRejectedValue(new Error("Dictation could not start — a voice session is running."));
    render(<DictationTab />);

    await press("Start dictation");
    expect(toasts()).toEqual([{ kind: "error", message: "Dictation could not start." }]);
    expect(toggle()?.disabled).toBe(false);
  });

  it("says when dictation is not set up, and leads to the API keys", async () => {
    dictation({ status: status({ available: false, reason: "No microphone." }) });
    render(<DictationTab />);

    const notice = screen.getByTestId("dictation-unavailable");
    expect(notice.querySelector("p")?.textContent).toBe(
      "Dictation is not set up on this computer.",
    );
    expect(toggle()).toBeNull();
    expect(headline()).toBeNull();
    expect(screen.queryByText(/No microphone/)).toBeNull();

    await press("API Keys");
    expect(useEventStore.getState().activeSection).toBe("voice-api-keys");
  });

  it("says when text cannot be typed into other apps", () => {
    dictation({
      status: status({
        insertion: { can_insert: false, reason: "wayland", detail: "Wayland blocks it." },
      }),
    });
    render(<DictationTab />);

    expect(screen.getByTestId("dictation-cannot-type").textContent).toBe(
      "Text cannot be typed into other apps right now.",
    );
    expect(screen.queryByText(/wayland/i)).toBeNull();
    expect(toggle()?.disabled).toBe(false);
  });

  it("has no notice when nothing stands in the way", () => {
    dictation();
    render(<DictationTab />);

    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("says when loading failed, without guessing at this computer, and can try again", async () => {
    const { refetch } = dictation({ status: null, error: "HTTP 500" });
    render(<DictationTab />);

    expect(screen.getByRole("alert").querySelector("p")?.textContent).toBe(
      "Dictation could not be loaded.",
    );
    expect(screen.queryByText(/HTTP 500/)).toBeNull();
    expect(screen.queryByTestId("dictation-unavailable")).toBeNull();
    expect(toggle()).toBeNull();

    await press("Try again");
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("shows the history under the instruction", () => {
    dictation({ entries: [testEntry({ text: "Send the report." })] });
    render(<DictationTab />);

    expect(screen.getByTestId("dictation-entry-text").textContent).toBe("Send the report.");
  });

  it("mentions a fallen-back wording pass only while a rewrite is switched on", () => {
    const entries = [testEntry({ polish_status: "provider_error" })];

    dictation({ entries, settings: { translate: false, prompt_mode: false } });
    render(<DictationTab />);
    expect(screen.queryByTestId("dictation-entry-remark")).toBeNull();
    cleanup();

    dictation({ entries, settings: { translate: true, prompt_mode: false } });
    render(<DictationTab />);
    expect(screen.getByTestId("dictation-entry-remark").textContent).toContain(
      "Model unreachable",
    );
  });
});
