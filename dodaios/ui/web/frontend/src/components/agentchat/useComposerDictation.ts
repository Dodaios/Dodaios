import { useCallback, useEffect, useId, useRef, useState } from "react";

import { getWSClient } from "@/hooks/useWebSocket";
import { translate } from "@/i18n";
import { robustCopy } from "@/lib/clipboard";
import { useEventStore } from "@/store/events";

/**
 * Microphone dictation into a composer's text box.
 *
 * ## One dictation, three phases
 *
 * The store holds the state machine (`dictationPhase`, `dictationOwner`,
 * `dictationResult` in store/events.ts); this hook is one composer's view of
 * it. Pressing the microphone makes this composer the owner and the phase
 * `recording`. Stop closes the microphone and the phase becomes
 * `transcribing` at once, so the button shows that work is going on without
 * waiting for the backend to say so. The dictation ends with a result: the
 * text, or the reason there is none.
 *
 * Nothing is written into the box before that result. The text arrives once,
 * complete, and is appended to whatever the box holds at that moment, so
 * words typed while the recording was transcribed are kept.
 *
 * ## Whose dictation it is
 *
 * Several composers can be mounted at once, and only one dictation runs at a
 * time. The owner alone shows the recording and transcribing states and takes
 * the result. Every other composer's microphone rests disabled until the
 * dictation is over (`micHeld`). A result without an owner (a dictation the
 * keyboard shortcut started, handed to the composers because no field had
 * focus) is taken by any composer.
 *
 * ## Send while the text is on its way
 *
 * `stopAndSend` is what Send does while this composer records or waits for
 * its text. It stops the recording if it still runs and remembers that a send
 * is owed (`sendQueued`). The message leaves only once the result is here,
 * however long that takes: there is no timeout that sends without the
 * dictated words. With text, the text goes into the box first and the send
 * follows. With nothing said, what was typed is sent. When the dictation
 * failed or was cancelled, nothing is sent, the box stays as it is and a
 * toast says so, because a message missing the spoken half is worse than a
 * message the person sends again.
 *
 * The setter and `onSend` are read through refs: callers pass inline
 * wrappers, and the effect that takes the result must run once per result,
 * not once per render of the composer.
 */

type Setter = (next: string | ((current: string) => string)) => void;

/** `text` after what the box holds, with a space between the two when one is needed. */
function appended(current: string, text: string): string {
  return current + (current && !/\s$/.test(current) ? " " : "") + text;
}

/** Ask the backend to start or stop the one dictation. */
export function sendDictate(mode: "start" | "stop"): void {
  getWSClient()?.send({ type: "command", action: "stt_dictate", payload: { mode } });
}

export function useComposerDictation(setValue: Setter, onSend?: () => void) {
  const id = useId();
  const dictating = useEventStore(
    (s) => s.dictationOwner === id && s.dictationPhase === "recording",
  );
  const finishing = useEventStore(
    (s) => s.dictationOwner === id && s.dictationPhase === "transcribing",
  );
  const heldElsewhere = useEventStore(
    (s) => (s.dictationPhase ?? "idle") !== "idle" && s.dictationOwner !== id,
  );
  // Read with care for a store that carries no dictation state at all: a
  // composer is also mounted where the store is a stand-in.
  const resultSeq = useEventStore((s) => s.dictationResult?.seq ?? 0);
  const [sendQueued, setSendQueued] = useState(false);
  // The same flag for the callbacks, which must not see a stale render.
  const sendQueuedRef = useRef(false);
  const lastResultSeqRef = useRef(resultSeq);
  const setValueRef = useRef(setValue);
  setValueRef.current = setValue;
  const onSendRef = useRef(onSend);
  onSendRef.current = onSend;

  // What the effect below decides once the composer has rendered the result.
  // The send must not run before that render: the composer's send reads the
  // box as it rendered last, and a send from before the text landed goes out
  // without the dictated words (with only the attached pictures) and then
  // clears the box, words included. An effect after the render that carries
  // the new text is the one moment the composer's send sees it.
  const landedRef = useRef(false);
  const holdsTextRef = useRef(false);
  const [settle, setSettle] = useState<{
    seq: number;
    text: string;
    send: "landed" | "holds_text" | null;
  } | null>(null);

  useEffect(() => {
    if (resultSeq === lastResultSeqRef.current) return;
    lastResultSeqRef.current = resultSeq;
    const result = useEventStore.getState().dictationResult;
    if (result.owner !== null && result.owner !== id) return; // another composer's dictation

    // The updaters below report what they saw. A setter may run its updater
    // at once or during the next render, and a composer that is off screen
    // may not run it at all, so the flags are read after that render.
    landedRef.current = false;
    holdsTextRef.current = false;
    if (result.text) {
      setValueRef.current((current) => {
        landedRef.current = true;
        return appended(current, result.text);
      });
    }

    // Only this composer's own dictation settles a queued send.
    const queued = result.owner === id && sendQueuedRef.current;
    if (queued) {
      sendQueuedRef.current = false;
      setSendQueued(false);
    }
    if (queued && result.outcome !== "text" && result.outcome !== "empty") {
      useEventStore
        .getState()
        .pushToast("error", translate("chats_view.dictation_failed_not_sent"));
      return;
    }
    if (queued && result.outcome === "empty") {
      // Nothing was said: what the person typed is the whole message.
      setValueRef.current((current) => {
        holdsTextRef.current = current.trim().length > 0;
        return current;
      });
    }
    if (!queued && !(result.owner === id && result.text)) return;
    setSettle({
      seq: result.seq,
      text: result.owner === id ? result.text : "",
      send: !queued ? null : result.outcome === "text" ? "landed" : "holds_text",
    });
  }, [resultSeq, id]);

  useEffect(() => {
    if (settle === null) return;
    setSettle(null);
    if (settle.text && !landedRef.current) {
      // This composer started the dictation, but its box would not take the
      // words (it left the screen, or another box took over). They must not
      // vanish: they go to the clipboard, and nothing is sent without them.
      void robustCopy(settle.text);
      useEventStore
        .getState()
        .pushToast("info", translate("chats_view.dictation_copied_not_inserted"));
      return;
    }
    if (settle.send === "landed" && landedRef.current) onSendRef.current?.();
    else if (settle.send === "holds_text" && holdsTextRef.current) onSendRef.current?.();
  }, [settle]);

  // A queued send belongs to the dictation it was queued for. Should that
  // dictation end without a result for this composer, the queue must not
  // stay set and swallow every later Send.
  const awaitingText = dictating || finishing;
  useEffect(() => {
    if (awaitingText || !sendQueuedRef.current) return;
    sendQueuedRef.current = false;
    setSendQueued(false);
  }, [awaitingText]);

  // A composer that goes away while it records closes the microphone, and no
  // other composer inherits a recording nobody can stop.
  const startedRef = useRef(false);
  useEffect(
    () => () => {
      // Only a composer that started a dictation has one to close.
      if (!startedRef.current) return;
      const store = useEventStore.getState();
      if (store.dictationOwner === id && store.dictationPhase === "recording") {
        sendDictate("stop");
        store.resetDictation();
      }
    },
    [id],
  );

  const start = useCallback(() => {
    const store = useEventStore.getState();
    // One dictation at a time: the backend refuses a second start.
    if (store.dictationPhase !== "idle") return;
    startedRef.current = true;
    store.beginDictation(id);
    sendDictate("start");
  }, [id]);

  const stop = useCallback(() => {
    const store = useEventStore.getState();
    if (store.dictationOwner !== id || store.dictationPhase !== "recording") return;
    sendDictate("stop");
    store.markDictationTranscribing();
  }, [id]);

  const toggle = useCallback(() => {
    const store = useEventStore.getState();
    if (store.dictationPhase === "idle") start();
    else if (store.dictationOwner === id && store.dictationPhase === "recording") stop();
  }, [id, start, stop]);

  const stopAndSend = useCallback(() => {
    if (sendQueuedRef.current) return;
    const store = useEventStore.getState();
    if (store.dictationOwner !== id || store.dictationPhase === "idle") return;
    sendQueuedRef.current = true;
    setSendQueued(true);
    if (store.dictationPhase === "recording") stop();
  }, [id, stop]);

  return {
    /** This composer's microphone is recording. */
    dictating,
    /** This composer's recording is being transcribed. */
    finishing,
    /** Recording or transcribing: Send waits for the result. */
    awaitingText,
    /** The microphone button cannot start a dictation right now. */
    micHeld: heldElsewhere || finishing,
    /** Send was pressed while the text was on its way; it goes out with the result. */
    sendQueued,
    start,
    stop,
    toggle,
    stopAndSend,
  };
}
