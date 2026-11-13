import { useCallback, useEffect, useId, useRef, useState } from "react";

import { getWSClient } from "@/hooks/useWebSocket";
import { translate } from "@/i18n";
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
  const sendTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  /** Run `decide` one tick later, after the composer has rendered the box. */
  const afterRender = useCallback((decide: () => void) => {
    if (sendTimerRef.current !== null) clearTimeout(sendTimerRef.current);
    sendTimerRef.current = setTimeout(() => {
      sendTimerRef.current = null;
      decide();
    }, 0);
  }, []);

  useEffect(() => {
    if (resultSeq === lastResultSeqRef.current) return;
    lastResultSeqRef.current = resultSeq;
    const result = useEventStore.getState().dictationResult;
    if (result.owner !== null && result.owner !== id) return; // another composer's dictation

    // The updaters below also report what they saw. A setter may run its
    // updater right away or at the next render, and a composer that is off
    // screen may not run it at all, so the flags are read a tick later.
    let landed = false;
    if (result.text) {
      setValueRef.current((current) => {
        landed = true;
        return appended(current, result.text);
      });
    }

    // Only this composer's own dictation settles a queued send.
    if (result.owner !== id || !sendQueuedRef.current) return;
    sendQueuedRef.current = false;
    setSendQueued(false);

    if (result.outcome === "text") {
      // Sent only when the text really is in the box.
      afterRender(() => {
        if (landed) onSendRef.current?.();
      });
    } else if (result.outcome === "empty") {
      // Nothing was said: what the person typed is the whole message.
      let holdsText = false;
      setValueRef.current((current) => {
        holdsText = current.trim().length > 0;
        return current;
      });
      afterRender(() => {
        if (holdsText) onSendRef.current?.();
      });
    } else {
      useEventStore
        .getState()
        .pushToast("error", translate("chats_view.dictation_failed_not_sent"));
    }
  }, [resultSeq, id, afterRender]);

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
      if (sendTimerRef.current !== null) clearTimeout(sendTimerRef.current);
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
