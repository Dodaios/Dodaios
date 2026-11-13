/**
 * Speaking a comment into a node's page.
 *
 * The comment field lives in the node's sandboxed page, and the sandbox gives
 * the page no microphone. So the field's microphone only asks: the page sends
 * `dodaios-node-dictate` (`dodaios/nodes/bridge.py`), and the app records
 * with its own dictation, the one the chat composer uses (the backend's
 * `stt_dictate`, the state machine in `store/events.ts`). The page is told
 * where that dictation stands, so its microphone shows it, and then the words.
 *
 * Only one dictation runs at a time in the app. While another one has the
 * microphone (the chat composer's, say), the field's microphone rests
 * disabled (`held`), as every other composer's does. The page itself never
 * hears anything: it gets the finished text, as plain text.
 */
import { useCallback, useEffect, useId, useRef, type RefObject } from "react";

import { sendDictate } from "@/components/agentchat/useComposerDictation";
import { useEventStore } from "@/store/events";
import {
  MAX_COMMENT_CHARS,
  NODE_DICTATION_STATE_MESSAGE,
  NODE_DICTATION_TEXT_MESSAGE,
  NODE_READY_MESSAGE,
  parseNodeDictate,
} from "./nodeBridge";

/**
 * Let the comment field of the framed page dictate while `active` (the page
 * is in comment mode).
 */
export function useNodeCommentDictation(frame: RefObject<HTMLIFrameElement | null>, active: boolean): void {
  const id = useId();
  // The comment the running dictation is for.
  const pin = useRef(0);
  const activeRef = useRef(active);
  activeRef.current = active;
  // Read with care for a store that carries no dictation state at all.
  const phase = useEventStore((s) => s.dictationPhase ?? "idle");
  const owner = useEventStore((s) => s.dictationOwner ?? null);
  const resultSeq = useEventStore((s) => s.dictationResult?.seq ?? 0);
  const lastSeq = useRef(resultSeq);

  const tell = useCallback(
    (message: Record<string, unknown>) => {
      // The page's origin is opaque: "*" is the only target that reaches it.
      frame.current?.contentWindow?.postMessage(message, "*");
    },
    [frame],
  );

  const tellState = useCallback(() => {
    const store = useEventStore.getState();
    const now = store.dictationPhase ?? "idle";
    if (store.dictationOwner === id && now !== "idle") {
      tell({ type: NODE_DICTATION_STATE_MESSAGE, n: pin.current, state: now });
    } else {
      tell({ type: NODE_DICTATION_STATE_MESSAGE, n: 0, state: now === "idle" ? "idle" : "held" });
    }
  }, [id, tell]);

  // The words first, then the state: a comment the reader already added waits
  // for them, and goes once they are in.
  useEffect(() => {
    if (resultSeq === lastSeq.current) return;
    lastSeq.current = resultSeq;
    const result = useEventStore.getState().dictationResult;
    if (!result || result.owner !== id) return;
    tell({
      type: NODE_DICTATION_TEXT_MESSAGE,
      n: pin.current,
      outcome: result.outcome,
      text: result.text.slice(0, MAX_COMMENT_CHARS),
    });
  }, [resultSeq, id, tell]);

  useEffect(() => {
    tellState();
  }, [phase, owner, tellState]);

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      const node = frame.current;
      if (!node || event.source !== node.contentWindow) return;
      const data = event.data as { type?: unknown } | null;
      if (data && typeof data === "object" && data.type === NODE_READY_MESSAGE) {
        // A page drawn again knows nothing yet: it learns whether the
        // microphone is free.
        tellState();
        return;
      }
      const ask = parseNodeDictate(event.data);
      if (ask === null) return;
      const store = useEventStore.getState();
      if (ask.mode === "start") {
        // A comment is only spoken while the page takes comments, and the
        // backend runs one dictation at a time.
        if (!activeRef.current || (store.dictationPhase ?? "idle") !== "idle") return;
        pin.current = ask.n;
        store.beginDictation(id);
        sendDictate("start");
      } else if (store.dictationOwner === id && store.dictationPhase === "recording" && ask.n === pin.current) {
        sendDictate("stop");
        store.markDictationTranscribing();
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [frame, id, tellState]);

  // Leaving comment mode, or the page, closes a microphone that still records
  // for it. Its words still come and are written down; leaving the page,
  // nobody waits for them.
  useEffect(() => {
    if (active) return;
    const store = useEventStore.getState();
    if (store.dictationOwner === id && store.dictationPhase === "recording") {
      sendDictate("stop");
      store.markDictationTranscribing();
    }
  }, [active, id]);

  useEffect(
    () => () => {
      const store = useEventStore.getState();
      if (store.dictationOwner === id && store.dictationPhase === "recording") {
        sendDictate("stop");
        store.resetDictation();
      }
    },
    [id],
  );
}
