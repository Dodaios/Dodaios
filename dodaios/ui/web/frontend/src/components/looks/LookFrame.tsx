/**
 * Shows a look (`docs/looks.md`) in a sandboxed frame.
 *
 * The frame has `sandbox="allow-scripts"` and no `allow-same-origin`, so the
 * look runs in an opaque origin: no cookies, no storage, no access to this
 * page, and the server refuses its requests to every route but its own files.
 * This component is the only thing that talks to it, and it sends only the
 * voice state and the audio levels.
 *
 * The frame takes no pointer input: clicks go to whatever holds the slot (the
 * orb button, the call window). A look that does not say `look:ready` within
 * `READY_TIMEOUT_MS` is reported through `onFail`, and the orb comes back.
 */
import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import { readVoiceInputLevel } from "@/lib/voiceInputLevel";
import { voiceOutputLevelRef } from "@/lib/voiceOutputLevel";
import { useDocumentVisible } from "@/hooks/useDocumentVisible";
import type { Look } from "@/lib/looksApi";
import type { VoiceState } from "@/store/events";

export const LOOK_FORMAT = "dodaios-look/1";
export const READY_TIMEOUT_MS = 5000;
const LEVEL_INTERVAL_MS = 33;

function reducedMotion(): boolean {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ?? false;
}

export function LookFrame({
  look,
  state,
  onFail,
  className,
}: {
  look: Look;
  state: VoiceState;
  onFail: () => void;
  className?: string;
}) {
  const frameRef = useRef<HTMLIFrameElement | null>(null);
  const readyRef = useRef(false);
  const stateRef = useRef<VoiceState>(state);
  const onFailRef = useRef(onFail);
  onFailRef.current = onFail;
  const visible = useDocumentVisible();

  const post = (message: Record<string, unknown>) => {
    // The frame's origin is opaque, so "*" is the only target that reaches it;
    // nothing private is ever sent.
    frameRef.current?.contentWindow?.postMessage(message, "*");
  };

  // Handshake: wait for look:ready, then send look:init. Give up after the timeout.
  useEffect(() => {
    readyRef.current = false;
    const onMessage = (event: MessageEvent) => {
      if (event.source !== frameRef.current?.contentWindow) return;
      const data = event.data as { type?: unknown } | null;
      if (!data || typeof data !== "object" || data.type !== "look:ready") return;
      if (readyRef.current) return;
      readyRef.current = true;
      post({
        type: "look:init",
        format: LOOK_FORMAT,
        state: stateRef.current,
        reducedMotion: reducedMotion(),
      });
    };
    window.addEventListener("message", onMessage);
    const timer = window.setTimeout(() => {
      if (!readyRef.current) onFailRef.current();
    }, READY_TIMEOUT_MS);
    return () => {
      window.removeEventListener("message", onMessage);
      window.clearTimeout(timer);
    };
  }, [look.frame_url]);

  useEffect(() => {
    stateRef.current = state;
    if (readyRef.current) post({ type: "look:state", state });
  }, [state]);

  // Audio levels, about 30 times a second while a conversation runs.
  useEffect(() => {
    if (!visible || state === "idle") return;
    const timer = window.setInterval(() => {
      if (!readyRef.current) return;
      const now = performance.now();
      post({
        type: "look:levels",
        input: readVoiceInputLevel(now),
        output: voiceOutputLevelRef.current ?? 0,
      });
    }, LEVEL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [visible, state]);

  return (
    <iframe
      ref={frameRef}
      src={look.frame_url}
      title={look.name}
      data-testid="look-frame"
      data-look-id={look.id}
      sandbox="allow-scripts"
      allow=""
      referrerPolicy="no-referrer"
      tabIndex={-1}
      aria-hidden
      className={cn("pointer-events-none block border-0 bg-transparent", className)}
      style={{ colorScheme: "normal" }}
    />
  );
}
