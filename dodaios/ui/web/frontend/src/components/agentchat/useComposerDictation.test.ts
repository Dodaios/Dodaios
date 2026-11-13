import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useEventStore } from "@/store/events";

import { useComposerDictation } from "./useComposerDictation";

/** A composer's box: text plus the setter the hook gets. */
function makeBox(initial = "") {
  const box = { text: initial };
  const setValue = (next: string | ((current: string) => string)) => {
    box.text = typeof next === "function" ? next(box.text) : next;
  };
  return { box, setValue };
}

const interim = (text: string) => act(() => useEventStore.getState().setDictationInterim(text));
const final = (text: string) =>
  act(() => {
    useEventStore.getState().commitDictation(text);
    useEventStore.getState().noteDictationFinal();
  });

describe("useComposerDictation", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    useEventStore.setState({
      dictating: false,
      dictationText: "",
      dictationOwner: null,
      dictationCommitOwner: null,
      dictationSettling: false,
    });
  });
  afterEach(() => vi.useRealTimers());

  it("shows the words in the box while they are recognized", () => {
    const { box, setValue } = makeBox("Fix");
    const { result } = renderHook(() => useComposerDictation(setValue));
    act(() => result.current.start());
    interim("the log");
    expect(box.text).toBe("Fix the log");
    interim("the login bug in");
    expect(box.text).toBe("Fix the login bug in");
  });

  it("puts the final transcript where the recognized words stood", () => {
    const { box, setValue } = makeBox("Fix");
    const { result } = renderHook(() => useComposerDictation(setValue));
    act(() => result.current.start());
    interim("the logging back");
    act(() => result.current.stop());
    expect(box.text).toBe("Fix the logging back");
    final("the login bug.");
    expect(box.text).toBe("Fix the login bug.");
  });

  it("keeps what was typed behind the recognized words", () => {
    const { box, setValue } = makeBox("");
    const { result } = renderHook(() => useComposerDictation(setValue));
    act(() => result.current.start());
    interim("ship it");
    box.text += " (typed)";
    interim("ship it today");
    expect(box.text).toBe("ship it today (typed)");
    final("Ship it today.");
    expect(box.text).toBe("Ship it today. (typed)");
  });

  it("stops mirroring once the person edits the words, and still adds the final text", () => {
    const { box, setValue } = makeBox("");
    const { result } = renderHook(() => useComposerDictation(setValue));
    act(() => result.current.start());
    interim("chip it");
    box.text = "ship it";
    interim("chip it today");
    expect(box.text).toBe("ship it");
    final("Ship it today.");
    expect(box.text).toBe("ship it Ship it today.");
  });

  it("drops the final text of a message that already left the box", () => {
    const { box, setValue } = makeBox("");
    const { result } = renderHook(() => useComposerDictation(setValue));
    act(() => result.current.start());
    interim("ship it");
    act(() => result.current.stop());
    box.text = ""; // sent
    final("Ship it.");
    expect(box.text).toBe("");
  });

  it("leaves the shown words in the box when nothing was recognized at the end", () => {
    const { box, setValue } = makeBox("");
    const { result } = renderHook(() => useComposerDictation(setValue));
    act(() => result.current.start());
    interim("ship it");
    act(() => result.current.stop());
    final("");
    expect(box.text).toBe("ship it");
    expect(result.current.awaitingText).toBe(false);
  });

  it("mirrors only in the composer whose button started the dictation", () => {
    const first = makeBox("");
    const second = makeBox("");
    const a = renderHook(() => useComposerDictation(first.setValue));
    renderHook(() => useComposerDictation(second.setValue));
    act(() => a.result.current.start());
    interim("hello");
    final("Hello.");
    expect(first.box.text).toBe("Hello.");
    expect(second.box.text).toBe("");
  });

  it("does not mirror a dictation no composer started", () => {
    const { box, setValue } = makeBox("Fix");
    renderHook(() => useComposerDictation(setValue));
    interim("hello wor");
    expect(box.text).toBe("Fix");
  });

  it("appends the final transcript of a dictation no composer started", () => {
    const { box, setValue } = makeBox("Fix");
    renderHook(() => useComposerDictation(setValue));
    act(() => useEventStore.getState().commitDictation("the login bug"));
    expect(box.text).toBe("Fix the login bug");
  });

  it("keeps the dictation after Stop until its final text is here", () => {
    const { setValue } = makeBox("");
    const { result } = renderHook(() => useComposerDictation(setValue));
    act(() => result.current.start());
    expect(result.current.dictating).toBe(true);
    act(() => result.current.stop());
    expect(result.current.dictating).toBe(false);
    expect(result.current.finishing).toBe(true);
    expect(result.current.awaitingText).toBe(true);
    final("done");
    expect(result.current.finishing).toBe(false);
    expect(result.current.awaitingText).toBe(false);
  });

  it("does not start another dictation while the last one is still being read", () => {
    const { box, setValue } = makeBox("");
    const { result } = renderHook(() => useComposerDictation(setValue));
    act(() => result.current.start());
    interim("ship it");
    act(() => result.current.stop());
    expect(result.current.micHeld).toBe(true);
    act(() => result.current.toggle());
    expect(result.current.dictating).toBe(false);
    final("Ship it.");
    expect(box.text).toBe("Ship it.");
    expect(result.current.micHeld).toBe(false);
    act(() => result.current.toggle());
    expect(result.current.dictating).toBe(true);
  });

  it("lets a dictation go whose final text never comes", () => {
    const { result } = renderHook(() => useComposerDictation(makeBox("").setValue));
    act(() => result.current.start());
    act(() => result.current.stop());
    act(() => vi.advanceTimersByTime(59_999));
    expect(result.current.finishing).toBe(true);
    act(() => vi.advanceTimersByTime(1));
    expect(result.current.finishing).toBe(false);
    expect(useEventStore.getState().dictationOwner).toBeNull();
  });

  it("sends after the final transcript when Send ended the dictation", () => {
    const onSend = vi.fn();
    const { result } = renderHook(() => useComposerDictation(vi.fn(), onSend));
    act(() => result.current.start());
    act(() => result.current.stopAndSend());
    expect(onSend).not.toHaveBeenCalled();
    final("ship it");
    act(() => vi.runOnlyPendingTimers());
    expect(onSend).toHaveBeenCalledTimes(1);
    // The fallback timer was cleared: no second send.
    act(() => vi.advanceTimersByTime(10_000));
    expect(onSend).toHaveBeenCalledTimes(1);
  });

  it("sends the final words when Send comes right after Stop", () => {
    const { box, setValue } = makeBox("");
    const sent: string[] = [];
    const { result } = renderHook(() =>
      useComposerDictation(setValue, () => sent.push(box.text)),
    );
    act(() => result.current.start());
    interim("chip it to day");
    act(() => result.current.stop());
    act(() => result.current.stopAndSend());
    expect(sent).toEqual([]);
    final("Ship it today.");
    act(() => vi.runOnlyPendingTimers());
    expect(sent).toEqual(["Ship it today."]);
  });

  it("still sends when no final transcript arrives", () => {
    const onSend = vi.fn();
    const { result } = renderHook(() => useComposerDictation(vi.fn(), onSend));
    act(() => result.current.start());
    act(() => result.current.stopAndSend());
    act(() => vi.advanceTimersByTime(7_999));
    expect(onSend).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(1));
    act(() => vi.runOnlyPendingTimers());
    expect(onSend).toHaveBeenCalledTimes(1);
  });
});
