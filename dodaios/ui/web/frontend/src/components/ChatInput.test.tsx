import { act, cleanup, fireEvent, render as rtlRender, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { ChatInput } from "@/components/ChatInput";
import { useEventStore, type DictationOutcome } from "@/store/events";

/** Stands in for the socket, so what the composer sends can be read. */
const wsSend = vi.hoisted(() => vi.fn());
vi.mock("@/hooks/useWebSocket", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useWebSocket")>()),
  getWSClient: () => ({ send: wsSend }),
}));

// The composer names the model that will answer (useVoiceEngineDisplay →
// useVoiceMode, a query), so it mounts under a query client like the app.
function render(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  return rtlRender(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("ChatInput offline/warming placeholder", () => {
  beforeEach(() => {
    useEventStore.setState({
      connected: false,
      wsWarming: true,
      chatThinking: false,
    });
    useEventStore.getState().resetDictation();
  });
  afterEach(() => cleanup());

  test("shows the booting placeholder while warming", () => {
    render(<ChatInput />);
    const box = screen.getByPlaceholderText("Starting…") as HTMLTextAreaElement;
    expect(box.disabled).toBe(true);
  });

  test("shows the offline placeholder when truly offline", () => {
    useEventStore.setState({ connected: false, wsWarming: false });
    render(<ChatInput />);
    expect(screen.getByPlaceholderText("Offline")).toBeTruthy();
  });
});

/*
 * A dictation started by the keyboard shortcut never runs through this
 * component's microphone button. Its text reaches the composer as a result
 * without an owner and is appended to whatever the box holds then.
 */
describe("ChatInput dictation", () => {
  beforeEach(() => {
    wsSend.mockClear();
    useEventStore.setState({
      connected: true,
      wsWarming: false,
      chatThinking: false,
      toasts: [],
      // A saved text thread, so sending needs no request to create one.
      activeThreadId: "thread-1",
      activeKind: "text",
    });
    useEventStore.getState().resetDictation();
  });
  afterEach(() => {
    cleanup();
    useEventStore.getState().resetDictation();
    useEventStore.setState({ chatThinking: false, activeThreadId: null });
  });

  function finish(text: string, outcome: DictationOutcome = "text"): void {
    act(() => {
      useEventStore.getState().finishDictation(text, outcome);
    });
  }

  /* Found the way the delivery path finds it — the attribute is what tells it
   * whether the fallback sink is on screen at all (lib/dictationTarget.ts). */
  function composer(): HTMLTextAreaElement {
    const box = document.querySelector("textarea[data-jarvis-chat-input]");
    if (!box) throw new Error("the chat composer is not marked as one");
    return box as HTMLTextAreaElement;
  }

  /** The chat messages sent over the socket so far. */
  function sentMessages(): string[] {
    return wsSend.mock.calls
      .map(([frame]) => frame as { type?: string; content?: string })
      .filter((frame) => frame.type === "message")
      .map((frame) => frame.content ?? "");
  }

  /** The `stt_dictate` modes sent over the socket so far. */
  function sentModes(): string[] {
    return wsSend.mock.calls
      .map(([frame]) => frame as { action?: string; payload?: { mode?: string } })
      .filter((frame) => frame.action === "stt_dictate")
      .map((frame) => frame.payload?.mode ?? "");
  }

  test("appends to what the user already typed", () => {
    render(<ChatInput />);
    const box = composer();
    fireEvent.change(box, { target: { value: "already typed" } });

    finish("and dictated");

    expect(box.value).toBe("already typed and dictated");
  });

  test("appends a later dictation to the box as it is then", () => {
    render(<ChatInput />);
    const box = composer();

    fireEvent.change(box, { target: { value: "first" } });
    finish("one");
    expect(box.value).toBe("first one");

    // Send clears the box; the next dictation starts from what is there now.
    fireEvent.change(box, { target: { value: "" } });
    finish("two");
    expect(box.value).toBe("two");
  });

  test("after Stop the button shows the transcription, and the text lands when it is done", () => {
    render(<ChatInput />);
    const box = composer();
    fireEvent.change(box, { target: { value: "typed" } });

    fireEvent.click(screen.getByTestId("dictation-button"));
    expect(screen.getByTestId("dictation-status")).toBeTruthy();
    expect(sentModes()).toEqual(["start"]);

    fireEvent.click(screen.getByTestId("dictation-stop"));
    expect(sentModes()).toEqual(["start", "stop"]);
    expect(screen.getByTestId("dictation-transcribing").textContent).toBe("Transcribing…");
    // Nothing is written before the text is here.
    expect(box.value).toBe("typed");

    finish("and dictated");
    expect(box.value).toBe("typed and dictated");
    expect(screen.queryByTestId("dictation-transcribing")).toBeNull();
    expect(screen.getByTestId("dictation-button")).toBeTruthy();
    expect(sentMessages()).toEqual([]);
  });

  test("Send while recording waits for the text and sends the message with it", async () => {
    render(<ChatInput />);
    const box = composer();
    fireEvent.change(box, { target: { value: "typed" } });
    fireEvent.click(screen.getByTestId("dictation-button"));

    fireEvent.click(screen.getByTestId("composer-send"));
    expect(sentModes()).toEqual(["start", "stop"]);
    expect(screen.getByTestId("dictation-transcribing").textContent).toBe("Sending when ready…");
    expect(sentMessages()).toEqual([]);
    expect(box.value).toBe("typed");

    finish("and dictated");
    expect(box.value).toBe("typed and dictated");
    await waitFor(() => expect(sentMessages()).toEqual(["typed and dictated"]));
    await waitFor(() => expect(box.value).toBe(""));
  });

  test("Send is live while recording into an empty box", () => {
    render(<ChatInput />);
    const send = screen.getByTestId("composer-send") as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    fireEvent.click(screen.getByTestId("dictation-button"));
    expect(send.disabled).toBe(false);
  });

  test("a dictation that fails with Send queued sends nothing and keeps the box", async () => {
    render(<ChatInput />);
    const box = composer();
    fireEvent.change(box, { target: { value: "typed" } });
    fireEvent.click(screen.getByTestId("dictation-button"));
    fireEvent.click(screen.getByTestId("composer-send"));

    finish("", "failed");

    expect(useEventStore.getState().toasts.map((toast) => toast.message)).toEqual([
      "The dictation could not be transcribed, so the message was not sent.",
    ]);
    // Past the tick a send would have taken.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    expect(sentMessages()).toEqual([]);
    expect(box.value).toBe("typed");
    expect(screen.getByTestId("dictation-button")).toBeTruthy();
  });
});
