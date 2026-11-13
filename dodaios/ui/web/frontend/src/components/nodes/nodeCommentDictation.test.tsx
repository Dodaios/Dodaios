/**
 * The app's side of a spoken comment: a microphone pressed in the node's page
 * starts the app's own dictation, and the page learns where it stands and,
 * at the end, the words.
 */
import { useRef } from "react";
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useEventStore } from "@/store/events";
import {
  NODE_DICTATE_MESSAGE,
  NODE_DICTATION_STATE_MESSAGE,
  NODE_DICTATION_TEXT_MESSAGE,
  NODE_READY_MESSAGE,
  parseNodeDictate,
} from "./nodeBridge";
import { useNodeCommentDictation } from "./nodeCommentDictation";

const sentToBackend = vi.fn();
vi.mock("@/hooks/useWebSocket", () => ({ getWSClient: () => ({ send: sentToBackend }) }));

function Harness({ active = true }: { active?: boolean }) {
  const frame = useRef<HTMLIFrameElement>(null);
  useNodeCommentDictation(frame, active);
  return <iframe ref={frame} title="page" data-testid="frame" />;
}

function fromFrame(data: unknown, source?: Window | null) {
  const frame = screen.getByTestId("frame") as HTMLIFrameElement;
  act(() => {
    window.dispatchEvent(new MessageEvent("message", { data, source: source ?? frame.contentWindow }));
  });
}

function postedToPage() {
  const frame = screen.getByTestId("frame") as HTMLIFrameElement;
  return vi.spyOn(frame.contentWindow as Window, "postMessage");
}

const dictateCommands = () =>
  sentToBackend.mock.calls.map(([command]) => command).filter((command) => command.action === "stt_dictate");

beforeEach(() => {
  useEventStore.getState().resetDictation();
  sentToBackend.mockClear();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  useEventStore.getState().resetDictation();
});

describe("parseNodeDictate", () => {
  it("takes only a press for one comment", () => {
    expect(parseNodeDictate({ type: NODE_DICTATE_MESSAGE, n: 2, mode: "start" })).toEqual({ n: 2, mode: "start" });
    expect(parseNodeDictate({ type: NODE_DICTATE_MESSAGE, n: 2, mode: "record" })).toBeNull();
    expect(parseNodeDictate({ type: NODE_DICTATE_MESSAGE, n: 0, mode: "start" })).toBeNull();
    expect(parseNodeDictate({ type: NODE_DICTATE_MESSAGE, n: "2", mode: "start" })).toBeNull();
    expect(parseNodeDictate({ type: "dodaios-node-comment", n: 2, mode: "start" })).toBeNull();
  });
});

describe("useNodeCommentDictation", () => {
  it("records for the comment whose microphone was pressed, and hands its words back", () => {
    render(<Harness />);
    const posted = postedToPage();

    fromFrame({ type: NODE_DICTATE_MESSAGE, n: 3, mode: "start" });
    expect(dictateCommands()).toEqual([{ type: "command", action: "stt_dictate", payload: { mode: "start" } }]);
    expect(useEventStore.getState().dictationPhase).toBe("recording");
    expect(posted).toHaveBeenLastCalledWith({ type: NODE_DICTATION_STATE_MESSAGE, n: 3, state: "recording" }, "*");

    fromFrame({ type: NODE_DICTATE_MESSAGE, n: 3, mode: "stop" });
    expect(dictateCommands().at(-1)).toEqual({ type: "command", action: "stt_dictate", payload: { mode: "stop" } });
    expect(posted).toHaveBeenLastCalledWith({ type: NODE_DICTATION_STATE_MESSAGE, n: 3, state: "transcribing" }, "*");

    posted.mockClear();
    act(() => useEventStore.getState().finishDictation("Use the cheaper flight", "text"));
    // The words first, then the microphone is free again.
    expect(posted.mock.calls.map(([message]) => message)).toEqual([
      { type: NODE_DICTATION_TEXT_MESSAGE, n: 3, outcome: "text", text: "Use the cheaper flight" },
      { type: NODE_DICTATION_STATE_MESSAGE, n: 0, state: "idle" },
    ]);
  });

  it("tells the page the outcome when nothing came of it", () => {
    render(<Harness />);
    const posted = postedToPage();
    fromFrame({ type: NODE_DICTATE_MESSAGE, n: 1, mode: "start" });
    act(() => useEventStore.getState().finishDictation("", "failed"));
    expect(posted).toHaveBeenCalledWith({ type: NODE_DICTATION_TEXT_MESSAGE, n: 1, outcome: "failed", text: "" }, "*");
  });

  it("keeps the microphone resting while another dictation has it, and takes none of its words", () => {
    render(<Harness />);
    const posted = postedToPage();
    act(() => useEventStore.getState().beginDictation("chat-composer"));
    expect(posted).toHaveBeenLastCalledWith({ type: NODE_DICTATION_STATE_MESSAGE, n: 0, state: "held" }, "*");

    fromFrame({ type: NODE_DICTATE_MESSAGE, n: 1, mode: "start" });
    expect(dictateCommands()).toEqual([]);
    expect(useEventStore.getState().dictationOwner).toBe("chat-composer");

    posted.mockClear();
    act(() => useEventStore.getState().finishDictation("for the chat", "text"));
    expect(posted.mock.calls.map(([message]) => message)).toEqual([
      { type: NODE_DICTATION_STATE_MESSAGE, n: 0, state: "idle" },
    ]);
  });

  it("hears only its own frame, and only while the page takes comments", () => {
    const view = render(<Harness active={false} />);
    fromFrame({ type: NODE_DICTATE_MESSAGE, n: 1, mode: "start" });
    expect(dictateCommands()).toEqual([]);

    view.rerender(<Harness active />);
    fromFrame({ type: NODE_DICTATE_MESSAGE, n: 1, mode: "start" }, window);
    expect(dictateCommands()).toEqual([]);
  });

  it("tells a page that loads again whether the microphone is free", () => {
    render(<Harness />);
    act(() => useEventStore.getState().beginDictation("chat-composer"));
    const posted = postedToPage();
    fromFrame({ type: NODE_READY_MESSAGE });
    expect(posted).toHaveBeenLastCalledWith({ type: NODE_DICTATION_STATE_MESSAGE, n: 0, state: "held" }, "*");
  });

  it("stops its recording when comment mode ends, and when the page goes away", () => {
    const view = render(<Harness />);
    fromFrame({ type: NODE_DICTATE_MESSAGE, n: 1, mode: "start" });
    view.rerender(<Harness active={false} />);
    expect(dictateCommands().at(-1)?.payload).toEqual({ mode: "stop" });
    expect(useEventStore.getState().dictationPhase).toBe("transcribing");
    act(() => useEventStore.getState().finishDictation("", "empty"));

    view.rerender(<Harness active />);
    fromFrame({ type: NODE_DICTATE_MESSAGE, n: 2, mode: "start" });
    sentToBackend.mockClear();
    view.unmount();
    expect(dictateCommands()).toEqual([{ type: "command", action: "stt_dictate", payload: { mode: "stop" } }]);
    expect(useEventStore.getState().dictationPhase).toBe("idle");
  });
});
