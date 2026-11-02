import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent, type WheelEvent } from "react";
import { MonitorUp, RotateCcw, Unplug } from "lucide-react";
import { encodeKey, encodeMouseButton, encodeMouseMove, encodeWheel, type PanelPoint } from "./panelInput";
import { browserDeps, VerseStreamSession, type StreamDeps, type StreamPhase } from "./streamSession";
import { usePanelVisibility } from "./usePanelVisibility";
import { useVerseStreamText } from "./strings";

/** Retry delays while the panel stays visible and the Verse is not there yet. */
const RETRY_MS = [2_000, 5_000, 10_000];

interface VerseStreamPanelProps {
  /** Test seam; the browser's fetch, WebSocket and RTCPeerConnection by default. */
  deps?: StreamDeps;
}

/**
 * The IDE side panel's live view of the Unreal Verse (WP20.3).
 *
 * Streams only while the panel is on screen; hidden, scrolled away or minimised, the session
 * closes in the same task. When the full Verse window opens the panel keeps the last frame and
 * says "Verse is open" (WP20.5). Without a Verse (not installed, no GPU) or after a failed start
 * it shows a plain card instead.
 */
export function VerseStreamPanel({ deps }: VerseStreamPanelProps) {
  const text = useVerseStreamText();
  const frameRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const stillRef = useRef<HTMLCanvasElement>(null);
  const sessionRef = useRef<VerseStreamSession | null>(null);
  const lastPointer = useRef<{ x: number; y: number } | null>(null);
  const [phase, setPhase] = useState<StreamPhase>("connecting");
  const [attempt, setAttempt] = useState(0);
  const [hasStill, setHasStill] = useState(false);
  const { visible, geometry } = usePanelVisibility(frameRef);
  const geometryRef = useRef(geometry);
  geometryRef.current = geometry;
  const [streamDeps] = useState<StreamDeps>(() => deps ?? browserDeps());

  const keepLastFrame = useCallback(() => {
    const video = videoRef.current;
    const canvas = stillRef.current;
    if (!video || !canvas || !video.videoWidth) return;
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.drawImage(video, 0, 0);
    setHasStill(true);
  }, []);

  // One session per visible stretch; hiding the panel ends it at once.
  useEffect(() => {
    if (!visible) return;
    const session = new VerseStreamSession(streamDeps, geometryRef.current, {
      onPhase: (next) => {
        if (next === "verse_open") keepLastFrame();
        if (next === "streaming") setHasStill(false);
        setPhase(next);
      },
      onStream: (stream) => {
        const video = videoRef.current;
        if (video && video.srcObject !== stream) {
          video.srcObject = stream;
          void video.play?.()?.catch?.(() => undefined);
        }
      },
    });
    sessionRef.current = session;
    void session.start();
    return () => {
      session.stop();
      if (sessionRef.current === session) sessionRef.current = null;
    };
  }, [visible, attempt, streamDeps, keepLastFrame]);

  useEffect(() => {
    if (visible && geometry.w > 0 && geometry.h > 0) sessionRef.current?.resize(geometry);
  }, [visible, geometry]);

  // The Verse may simply not be up yet: try again a few times while the panel is visible.
  useEffect(() => {
    if (!visible || phase !== "unavailable" || attempt >= RETRY_MS.length) return;
    const timer = window.setTimeout(() => setAttempt((n) => n + 1), RETRY_MS[attempt]);
    return () => window.clearTimeout(timer);
  }, [visible, phase, attempt]);

  const point = (event: { clientX: number; clientY: number }): PanelPoint | null => {
    const rect = frameRef.current?.getBoundingClientRect();
    if (!rect || rect.width <= 0 || rect.height <= 0) return null;
    return { x: (event.clientX - rect.left) / rect.width, y: (event.clientY - rect.top) / rect.height };
  };

  const onKey = (down: boolean) => (event: KeyboardEvent<HTMLDivElement>) => {
    if (sessionRef.current?.sendInput(encodeKey(down, event.code, event.repeat))) event.preventDefault();
  };
  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    frameRef.current?.focus();
    const at = point(event);
    lastPointer.current = { x: event.clientX, y: event.clientY };
    if (at) sessionRef.current?.sendInput(encodeMouseButton(true, event.button, at));
  };
  const onPointerUp = (event: PointerEvent<HTMLDivElement>) => {
    const at = point(event);
    lastPointer.current = null;
    if (at) sessionRef.current?.sendInput(encodeMouseButton(false, event.button, at));
  };
  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const last = lastPointer.current;
    const at = point(event);
    const rect = frameRef.current?.getBoundingClientRect();
    if (!last || !at || !rect || event.buttons === 0) return;
    lastPointer.current = { x: event.clientX, y: event.clientY };
    sessionRef.current?.sendInput(encodeMouseMove(at, { dx: event.clientX - last.x, dy: event.clientY - last.y }, rect));
  };
  const onWheel = (event: WheelEvent<HTMLDivElement>) => {
    const at = point(event);
    if (at) sessionRef.current?.sendInput(encodeWheel(event.deltaY, at));
  };

  const showCard = phase === "unavailable" || phase === "failed";
  return (
    <div
      ref={frameRef}
      data-testid="verse-stream-panel"
      data-phase={phase}
      role="application"
      aria-label={text.label}
      tabIndex={0}
      onKeyDown={onKey(true)}
      onKeyUp={onKey(false)}
      onPointerDown={onPointerDown}
      onPointerUp={onPointerUp}
      onPointerMove={onPointerMove}
      onWheel={onWheel}
      onContextMenu={(event) => event.preventDefault()}
      className="relative h-full min-h-0 w-full overflow-hidden bg-black outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <video
        ref={videoRef}
        data-testid="verse-stream-video"
        className={`absolute inset-0 h-full w-full object-contain ${phase === "streaming" ? "" : "invisible"}`}
        autoPlay
        muted
        playsInline
        disablePictureInPicture
      />
      <canvas
        ref={stillRef}
        data-testid="verse-stream-still"
        className={`absolute inset-0 h-full w-full object-contain opacity-60 ${phase === "verse_open" && hasStill ? "" : "hidden"}`}
      />
      {phase === "connecting" && (
        <div className="absolute inset-0 flex items-center justify-center text-sm text-muted-foreground" data-testid="verse-stream-connecting">
          {text.connecting}
        </div>
      )}
      {phase === "verse_open" && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 p-6 text-center" data-testid="verse-stream-open">
          <MonitorUp className="h-5 w-5 text-foreground" aria-hidden />
          <p className="text-sm font-medium text-foreground">{text.verseOpen}</p>
          <p className="text-xs text-muted-foreground">{text.verseOpenHint}</p>
        </div>
      )}
      {showCard && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-background p-6 text-center" data-testid="verse-stream-fallback">
          <Unplug className="h-5 w-5 text-muted-foreground" aria-hidden />
          <p className="text-sm text-foreground">{phase === "failed" ? text.failed : text.unavailable}</p>
          {phase === "unavailable" && <p className="text-xs text-muted-foreground">{text.unavailableHint}</p>}
          <button
            type="button"
            onPointerDown={(event) => event.stopPropagation()}
            onClick={() => {
              setPhase("connecting");
              setAttempt((n) => (n >= RETRY_MS.length ? 0 : n) + 1);
            }}
            className="inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-sm text-foreground hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <RotateCcw className="h-3.5 w-3.5" aria-hidden />
            {text.retry}
          </button>
        </div>
      )}
    </div>
  );
}
