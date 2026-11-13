import { useCallback, useEffect, useId, useRef } from "react";

import { getWSClient } from "@/hooks/useWebSocket";
import { useEventStore } from "@/store/events";

/**
 * Microphone dictation into a composer's text box. The words stand in the box
 * while they are recognized, and the final transcript takes their place when
 * the dictation ends.
 *
 * Lifted from components/ChatInput.tsx so the agent composer dictates the
 * same way the classic one does: the same `stt_dictate` command and the same
 * store flags.
 *
 * ## The words while speaking
 *
 * The backend publishes the transcript so far a few times a second (the
 * segments already read, plus a quick reading of the newest audio). The
 * composer whose button started the dictation writes it at the end of its box
 * and overwrites it with each newer reading. The last words can still change;
 * what was read earlier stays. Before, the box stayed empty until the whole
 * recording was transcribed: with a slow recognizer that was many seconds of
 * an empty box after Stop.
 *
 * Only the box's own text is touched. What the person typed before the
 * dictation, or types after the mirrored words while it runs, is kept: the
 * mirrored words are found again by their text and replaced in place. When
 * they are no longer there (the person edited them), the mirror stops and the
 * final text is appended; when the box is empty by then (the message was
 * sent), the final text is dropped.
 *
 * ## Whose dictation it is
 *
 * Several composers can be mounted at once. `start` names this instance as
 * the owner in the store (`dictationOwner`); only the owner mirrors, and only
 * the owner takes the commit of a dictation that has one. A dictation nobody
 * here started (the keyboard shortcut, the classic input) has no owner and
 * its commit appends as before.
 *
 * After Stop the microphone is closed but the last words are still being
 * recognized (`finishing`). The owner keeps the dictation until its final
 * text is here, so the final replaces the mirrored words instead of being
 * pasted after them. Until then no composer starts another one (`micHeld`):
 * the button rests dimmed, usually for about a second.
 *
 * The setter is read through a ref: callers pass an inline wrapper (the
 * society composer mirrors into its chip field), and with that wrapper in the
 * effect deps the commit effect would re-run on every render of the composer.
 * It must hand the updater the box as it is NOW, not as it was at the last
 * render: several readings can arrive between two renders, and each one looks
 * for the words the one before it wrote.
 *
 * `stopAndSend` lets Send end a running dictation: the mic stops, and the
 * composer's `onSend` runs once the final transcript has landed in the box
 * (or after FINAL_WAIT_MS, so a transcript that never comes cannot strand
 * the message; FINAL_WAIT_SHOWN_MS while the box shows words whose final
 * reading is still on its way). It does the same while `finishing`, so a Send right after
 * Stop goes out with the final words, not the quick reading. `onSend` is also
 * read through a ref, so the call made after the transcript lands sees the
 * box as it is then, not as it was at click.
 */
const FINAL_WAIT_MS = 8000;
/**
 * How long Send waits when the box already shows the words of a dictation
 * that is still being read. Those words are the quick reading; sending them
 * after 8 s would put a rough draft in front of the assistant while the real
 * transcript is seconds away (a local recognizer on a CPU needs 14 to 25 s
 * for a long recording).
 */
const FINAL_WAIT_SHOWN_MS = 30_000;
/** A final text that never comes must not keep the dictation forever. */
const SETTLE_MAX_MS = 60_000;

type Setter = (next: string | ((current: string) => string)) => void;

function joined(base: string, text: string): string {
  return base && !/\s$/.test(base) ? " " + text : text;
}

export function useComposerDictation(setValue: Setter, onSend?: () => void) {
  const id = useId();
  const dictating = useEventStore((s) => s.dictating);
  const finishing = useEventStore((s) => s.dictationSettling && s.dictationOwner === id);
  const micHeld = useEventStore((s) => s.dictationSettling);
  // The transcript so far, for the owner only: every other mounted composer
  // reads "" throughout and is not re-rendered by a reading.
  const reading = useEventStore((s) => (s.dictationOwner === id ? s.dictationText : ""));
  const dictationCommitSeq = useEventStore((s) => s.dictationCommitSeq);
  const dictationFinalSeq = useEventStore((s) => s.dictationFinalSeq);
  const setDictating = useEventStore((s) => s.setDictating);
  const settleDictation = useEventStore((s) => s.settleDictation);
  const lastCommitSeqRef = useRef(dictationCommitSeq);
  const setValueRef = useRef(setValue);
  setValueRef.current = setValue;
  const onSendRef = useRef(onSend);
  onSendRef.current = onSend;
  const sendTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastFinalSeqRef = useRef(dictationFinalSeq);
  /** The mirrored words exactly as they stand in the box, with their leading space. */
  const shownRef = useRef("");
  /** True once the person changed the mirrored words: hands off until the final. */
  const detachedRef = useRef(false);
  /** Put `text` where the mirrored words stand, or at the end when there are none. */
  const write = useCallback((text: string, final: boolean) => {
    setValueRef.current((current) => {
      const shown = shownRef.current;
      const at = shown ? current.lastIndexOf(shown) : -1;
      let output = current;
      if (shown && at < 0) {
        // The mirrored words are gone. An empty box was sent or cleared: the
        // final text belongs to a message that already left. Otherwise the
        // person edited them, and the final text is added rather than lost.
        detachedRef.current = true;
        if (final && current.trim()) output = current + joined(current, text);
      } else if (!detachedRef.current || final) {
        const base = shown ? current.slice(0, at) : current;
        const rest = shown ? current.slice(at + shown.length) : "";
        const next = joined(base, text);
        shownRef.current = next;
        output = base + next + rest;
      }
      if (final) shownRef.current = "";
      return output;
    });
  }, []);

  const flushSend = useCallback(() => {
    if (sendTimerRef.current === null) return;
    clearTimeout(sendTimerRef.current);
    sendTimerRef.current = null;
    // A tick later, so the box has re-rendered with the transcript first.
    setTimeout(() => onSendRef.current?.(), 0);
  }, []);

  useEffect(() => {
    if (dictationFinalSeq === lastFinalSeqRef.current) return;
    lastFinalSeqRef.current = dictationFinalSeq;
    flushSend();
  }, [dictationFinalSeq, flushSend]);

  useEffect(
    () => () => {
      if (sendTimerRef.current !== null) clearTimeout(sendTimerRef.current);
    },
    [],
  );

  // The words while they are recognized.
  useEffect(() => {
    if (reading) write(reading, false);
  }, [reading, write]);

  useEffect(() => {
    if (dictationCommitSeq === lastCommitSeqRef.current) return;
    lastCommitSeqRef.current = dictationCommitSeq;
    const { dictationCommitText: finalText, dictationCommitOwner: owner } =
      useEventStore.getState();
    if (owner !== null && owner !== id) return; // another composer's dictation
    if (!finalText) {
      // Nothing was recognized at the end: what the box shows stays, as text.
      shownRef.current = "";
      return;
    }
    if (owner === id) {
      write(finalText, true);
      return;
    }
    setValueRef.current((current) => current + joined(current, finalText));
  }, [dictationCommitSeq, id, write]);

  // A dictation whose final text never comes (the connection dropped) is let
  // go, so the next one into another field is not taken for this box.
  useEffect(() => {
    if (!finishing) return;
    const timer = setTimeout(() => {
      const state = useEventStore.getState();
      if (state.dictationSettling && state.dictationOwner === id) setDictating(false);
    }, SETTLE_MAX_MS);
    return () => clearTimeout(timer);
  }, [finishing, id, setDictating]);

  const start = useCallback(() => {
    shownRef.current = "";
    detachedRef.current = false;
    setDictating(true, id);
    getWSClient()?.send({ type: "command", action: "stt_dictate", payload: { mode: "start" } });
  }, [id, setDictating]);

  const stop = useCallback(() => {
    getWSClient()?.send({ type: "command", action: "stt_dictate", payload: { mode: "stop" } });
    settleDictation();
  }, [settleDictation]);

  const toggle = useCallback(() => {
    // The backend cannot open the microphone while the last dictation is
    // still being read. A press then would be refused, and the refusal would
    // let go of the dictation whose final text is on its way.
    if (useEventStore.getState().dictationSettling) return;
    if (dictating) stop();
    else start();
  }, [dictating, start, stop]);

  const stopAndSend = useCallback(() => {
    if (sendTimerRef.current !== null) return;
    const asked = Date.now();
    const giveUp = () => {
      const state = useEventStore.getState();
      const stillReading = state.dictationSettling && state.dictationOwner === id;
      const waited = Date.now() - asked;
      if (stillReading && shownRef.current && waited < FINAL_WAIT_SHOWN_MS) {
        sendTimerRef.current = setTimeout(giveUp, FINAL_WAIT_SHOWN_MS - waited);
        return;
      }
      flushSend();
    };
    sendTimerRef.current = setTimeout(giveUp, FINAL_WAIT_MS);
    if (useEventStore.getState().dictating) stop();
  }, [flushSend, id, stop]);

  return {
    dictating,
    /** Stop was pressed and the final text is not here yet. */
    finishing,
    /** Recording or finishing: Send waits for the final text. */
    awaitingText: dictating || finishing,
    /** Some composer's dictation is finishing: the microphone cannot start yet. */
    micHeld,
    start,
    stop,
    toggle,
    stopAndSend,
  };
}
