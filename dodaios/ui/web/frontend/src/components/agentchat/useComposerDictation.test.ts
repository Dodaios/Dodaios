import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useI18nStore } from "@/i18n";
import {
  DICTATION_TRANSCRIBING_LIMIT_MS,
  useEventStore,
  type DictationOutcome,
} from "@/store/events";

import { useComposerDictation } from "./useComposerDictation";

/** Stands in for the socket, so the commands a composer sends can be read. */
const wsSend = vi.hoisted(() => vi.fn());
vi.mock("@/hooks/useWebSocket", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useWebSocket")>()),
  getWSClient: () => ({ send: wsSend }),
}));

/** A composer's box: text plus the setter the hook gets. */
function makeBox(initial = "") {
  const box = { text: initial };
  const setValue = (next: string | ((current: string) => string)) => {
    box.text = typeof next === "function" ? next(box.text) : next;
  };
  return { box, setValue };
}

/** The dictation ends the way the websocket handler ends it. */
const finish = (text: string, outcome: DictationOutcome) =>
  act(() => useEventStore.getState().finishDictation(text, outcome));

/** The next tick, where a queued send goes out. */
const tick = () =>
  act(() => {
    vi.advanceTimersByTime(0);
  });

/** The `stt_dictate` modes sent so far, in order. */
const sentModes = () =>
  wsSend.mock.calls.map(([frame]) => (frame as { payload: { mode: string } }).payload.mode);

const toastMessages = () => useEventStore.getState().toasts.map((toast) => toast.message);

describe("useComposerDictation", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    wsSend.mockClear();
    useI18nStore.getState().setUi("en", { push: false });
    useEventStore.getState().resetDictation();
    useEventStore.setState({ toasts: [] });
  });
  afterEach(() => {
    cleanup();
    useEventStore.getState().resetDictation();
    vi.useRealTimers();
  });

  it("moves from recording to transcribing to idle and sends the two commands", () => {
    const { result } = renderHook(() => useComposerDictation(makeBox().setValue));
    expect(result.current.dictating).toBe(false);

    act(() => result.current.start());
    expect(result.current.dictating).toBe(true);
    expect(result.current.finishing).toBe(false);
    expect(result.current.awaitingText).toBe(true);

    act(() => result.current.stop());
    // At once, before the backend says anything.
    expect(result.current.dictating).toBe(false);
    expect(result.current.finishing).toBe(true);
    expect(result.current.awaitingText).toBe(true);
    expect(sentModes()).toEqual(["start", "stop"]);

    finish("done", "text");
    expect(result.current.finishing).toBe(false);
    expect(result.current.awaitingText).toBe(false);
  });

  it("appends the result to what the box holds, with one space between", () => {
    const { box, setValue } = makeBox("Fix");
    const { result } = renderHook(() => useComposerDictation(setValue));
    act(() => result.current.start());
    act(() => result.current.stop());
    finish("the login bug.", "text");
    expect(box.text).toBe("Fix the login bug.");
  });

  it("adds no space in an empty box or after whitespace", () => {
    const empty = makeBox("");
    const first = renderHook(() => useComposerDictation(empty.setValue));
    act(() => first.result.current.start());
    finish("Ship it.", "text");
    expect(empty.box.text).toBe("Ship it.");
    first.unmount();

    const spaced = makeBox("Note:\n");
    const second = renderHook(() => useComposerDictation(spaced.setValue));
    act(() => second.result.current.start());
    finish("ship it.", "text");
    expect(spaced.box.text).toBe("Note:\nship it.");
  });

  it("keeps what was typed while the recording was transcribed", () => {
    const { box, setValue } = makeBox("");
    const { result } = renderHook(() => useComposerDictation(setValue));
    act(() => result.current.start());
    act(() => result.current.stop());
    box.text = "typed meanwhile";
    finish("and dictated", "text");
    expect(box.text).toBe("typed meanwhile and dictated");
  });

  it("writes nothing into the box while recording or transcribing", () => {
    const setValue = vi.fn();
    const { result } = renderHook(() => useComposerDictation(setValue));
    act(() => result.current.start());
    act(() => vi.advanceTimersByTime(5_000));
    act(() => result.current.stop());
    act(() => vi.advanceTimersByTime(5_000));
    expect(setValue).not.toHaveBeenCalled();
  });

  it("leaves the box alone when nothing was said", () => {
    const { box, setValue } = makeBox("Fix");
    const { result } = renderHook(() => useComposerDictation(setValue));
    act(() => result.current.start());
    act(() => result.current.stop());
    finish("", "empty");
    expect(box.text).toBe("Fix");
    expect(result.current.awaitingText).toBe(false);
  });

  it("toggle starts when idle, stops while recording and does nothing while transcribing", () => {
    const { result } = renderHook(() => useComposerDictation(makeBox().setValue));
    act(() => result.current.toggle());
    expect(result.current.dictating).toBe(true);
    act(() => result.current.toggle());
    expect(result.current.finishing).toBe(true);
    act(() => result.current.toggle());
    expect(result.current.finishing).toBe(true);
    expect(sentModes()).toEqual(["start", "stop"]);

    finish("Ship it.", "text");
    act(() => result.current.toggle());
    expect(result.current.dictating).toBe(true);
  });

  it("Send during recording stops the microphone and sends only after the text is in the box", () => {
    const { box, setValue } = makeBox("Fix");
    const sent: string[] = [];
    const { result } = renderHook(() =>
      useComposerDictation(setValue, () => sent.push(box.text)),
    );
    act(() => result.current.start());
    act(() => result.current.stopAndSend());
    expect(sentModes()).toEqual(["start", "stop"]);
    expect(result.current.finishing).toBe(true);
    expect(result.current.sendQueued).toBe(true);

    // However long the transcription takes, nothing goes out without it.
    act(() => vi.advanceTimersByTime(60_000));
    expect(sent).toEqual([]);

    finish("the login bug.", "text");
    expect(box.text).toBe("Fix the login bug.");
    expect(result.current.sendQueued).toBe(false);
    tick();
    expect(sent).toEqual(["Fix the login bug."]);

    act(() => vi.advanceTimersByTime(60_000));
    expect(sent).toHaveLength(1);
  });

  it("Send during transcribing waits for the text", () => {
    const { box, setValue } = makeBox("");
    const sent: string[] = [];
    const { result } = renderHook(() =>
      useComposerDictation(setValue, () => sent.push(box.text)),
    );
    act(() => result.current.start());
    act(() => result.current.stop());
    act(() => result.current.stopAndSend());
    // The microphone is closed already: no second stop.
    expect(sentModes()).toEqual(["start", "stop"]);
    expect(result.current.sendQueued).toBe(true);

    act(() => vi.advanceTimersByTime(100_000));
    expect(sent).toEqual([]);

    finish("Ship it today.", "text");
    tick();
    expect(sent).toEqual(["Ship it today."]);
  });

  it("a second Send while one is queued changes nothing", () => {
    const onSend = vi.fn();
    const { result } = renderHook(() => useComposerDictation(makeBox().setValue, onSend));
    act(() => result.current.start());
    act(() => result.current.stopAndSend());
    act(() => result.current.stopAndSend());
    expect(sentModes()).toEqual(["start", "stop"]);
    finish("ship it", "text");
    tick();
    expect(onSend).toHaveBeenCalledTimes(1);
  });

  it("Send with no dictation of this composer under way does nothing", () => {
    const onSend = vi.fn();
    const { result } = renderHook(() => useComposerDictation(makeBox().setValue, onSend));
    act(() => result.current.stopAndSend());
    expect(result.current.sendQueued).toBe(false);
    expect(sentModes()).toEqual([]);
    tick();
    expect(onSend).not.toHaveBeenCalled();
  });

  it.each(["failed", "cancelled"] as const)(
    "a %s dictation with a queued send does not send and says so",
    (outcome) => {
      const { box, setValue } = makeBox("typed");
      const onSend = vi.fn();
      const { result } = renderHook(() => useComposerDictation(setValue, onSend));
      act(() => result.current.start());
      act(() => result.current.stopAndSend());

      finish("", outcome);
      expect(toastMessages()).toEqual([
        "The dictation could not be transcribed, so the message was not sent.",
      ]);
      expect(useEventStore.getState().toasts[0]?.kind).toBe("error");
      expect(result.current.sendQueued).toBe(false);
      tick();
      expect(onSend).not.toHaveBeenCalled();
      expect(box.text).toBe("typed");
    },
  );

  it("a failed dictation without a queued send shows no toast", () => {
    const { result } = renderHook(() => useComposerDictation(makeBox("typed").setValue));
    act(() => result.current.start());
    act(() => result.current.stop());
    finish("", "failed");
    expect(toastMessages()).toEqual([]);
    expect(result.current.awaitingText).toBe(false);
  });

  it("an empty dictation with typed text and a queued send sends the typed text", () => {
    const { box, setValue } = makeBox("typed by hand");
    const sent: string[] = [];
    const { result } = renderHook(() =>
      useComposerDictation(setValue, () => sent.push(box.text)),
    );
    act(() => result.current.start());
    act(() => result.current.stopAndSend());
    finish("", "empty");
    expect(result.current.sendQueued).toBe(false);
    tick();
    expect(sent).toEqual(["typed by hand"]);
    expect(toastMessages()).toEqual([]);
  });

  it("an empty dictation with an empty box and a queued send sends nothing", () => {
    const onSend = vi.fn();
    const { result } = renderHook(() => useComposerDictation(makeBox("  ").setValue, onSend));
    act(() => result.current.start());
    act(() => result.current.stopAndSend());
    finish("", "empty");
    tick();
    expect(onSend).not.toHaveBeenCalled();
    expect(result.current.sendQueued).toBe(false);
  });

  it("does not send when the box did not take the text", () => {
    // A composer that is off screen ignores what it is handed.
    const onSend = vi.fn();
    const { result } = renderHook(() => useComposerDictation(() => undefined, onSend));
    act(() => result.current.start());
    act(() => result.current.stopAndSend());
    finish("ship it", "text");
    tick();
    expect(onSend).not.toHaveBeenCalled();
    expect(result.current.sendQueued).toBe(false);
  });

  it("ignores another composer's result", () => {
    const first = makeBox("");
    const second = makeBox("mine");
    const onSendSecond = vi.fn();
    const a = renderHook(() => useComposerDictation(first.setValue));
    const b = renderHook(() => useComposerDictation(second.setValue, onSendSecond));
    act(() => a.result.current.start());
    act(() => a.result.current.stop());
    finish("Hello.", "text");
    tick();
    expect(first.box.text).toBe("Hello.");
    expect(second.box.text).toBe("mine");
    expect(b.result.current.dictating).toBe(false);
    expect(onSendSecond).not.toHaveBeenCalled();
  });

  it("holds the microphone of every other composer until the dictation is over", () => {
    const a = renderHook(() => useComposerDictation(makeBox().setValue));
    const b = renderHook(() => useComposerDictation(makeBox().setValue));
    expect(a.result.current.micHeld).toBe(false);
    expect(b.result.current.micHeld).toBe(false);

    act(() => a.result.current.start());
    // The owner's button is its Stop; the other composer cannot start.
    expect(a.result.current.micHeld).toBe(false);
    expect(b.result.current.micHeld).toBe(true);
    expect(b.result.current.dictating).toBe(false);
    expect(b.result.current.awaitingText).toBe(false);

    // Pressing the other composer's button neither starts nor stops anything.
    act(() => b.result.current.toggle());
    act(() => b.result.current.stop());
    act(() => b.result.current.stopAndSend());
    expect(sentModes()).toEqual(["start"]);
    expect(a.result.current.dictating).toBe(true);
    expect(b.result.current.sendQueued).toBe(false);

    act(() => a.result.current.stop());
    expect(a.result.current.micHeld).toBe(true);
    expect(b.result.current.micHeld).toBe(true);

    finish("Hello.", "text");
    expect(a.result.current.micHeld).toBe(false);
    expect(b.result.current.micHeld).toBe(false);
  });

  it("takes the result of a dictation no composer started", () => {
    const { box, setValue } = makeBox("Fix");
    const onSend = vi.fn();
    renderHook(() => useComposerDictation(setValue, onSend));
    finish("the login bug", "text");
    tick();
    expect(box.text).toBe("Fix the login bug");
    expect(onSend).not.toHaveBeenCalled();
  });

  it("does not replay a result that was there before the composer mounted", () => {
    finish("old words", "text");
    const { box, setValue } = makeBox("");
    renderHook(() => useComposerDictation(setValue));
    expect(box.text).toBe("");
  });

  it("gives up a transcription whose result never arrives, and a queued send with it", () => {
    const onSend = vi.fn();
    const { result } = renderHook(() => useComposerDictation(makeBox("typed").setValue, onSend));
    act(() => result.current.start());
    act(() => result.current.stopAndSend());

    act(() => vi.advanceTimersByTime(DICTATION_TRANSCRIBING_LIMIT_MS - 1));
    expect(result.current.finishing).toBe(true);
    expect(result.current.sendQueued).toBe(true);

    act(() => vi.advanceTimersByTime(1));
    expect(result.current.finishing).toBe(false);
    expect(result.current.micHeld).toBe(false);
    expect(result.current.sendQueued).toBe(false);
    expect(toastMessages()).toHaveLength(1);
    tick();
    expect(onSend).not.toHaveBeenCalled();
  });

  it("closes the microphone when the composer goes away while recording", () => {
    const { result, unmount } = renderHook(() => useComposerDictation(makeBox().setValue));
    act(() => result.current.start());
    unmount();
    expect(sentModes()).toEqual(["start", "stop"]);
    expect(useEventStore.getState().dictationPhase).toBe("idle");
    expect(useEventStore.getState().dictationOwner).toBeNull();
  });

  it("leaves another composer's recording alone when it goes away", () => {
    const a = renderHook(() => useComposerDictation(makeBox().setValue));
    const b = renderHook(() => useComposerDictation(makeBox().setValue));
    act(() => a.result.current.start());
    b.unmount();
    expect(sentModes()).toEqual(["start"]);
    expect(a.result.current.dictating).toBe(true);
  });
});
