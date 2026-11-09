import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent, type WheelEvent } from "react";
import { Download, MonitorUp, RotateCcw, Unplug } from "lucide-react";
import { useEventStore } from "@/store/events";
import { useVerseModeStore } from "@/store/verseMode";
import { encodeKey, encodeMouseButton, encodeMouseMove, encodeWheel, type PanelPoint } from "./panelInput";
import { browserDeps, VerseStreamSession, type StreamDeps, type StreamPhase, type VerseHostStatus } from "./streamSession";
import { usePanelVisibility } from "./usePanelVisibility";
import { useVerseStreamText } from "./strings";

/** Retry delays while the panel stays visible and the Verse is not there yet. */
const RETRY_MS = [2_000, 5_000, 10_000];

interface VerseStreamPanelProps {
  /** Test seam; the browser's fetch, WebSocket and RTCPeerConnection by default. */
  deps?: StreamDeps;
}

/**
 * Opens the full-window Verse (the Agents section's Verse face), where WP17's launcher card
 * offers the optional download with its size, progress and cancel.
 */
export function openVerseDownload(): void {
  useVerseModeStore.getState().request();
  useEventStore.getState().setActiveSection("agents");
}

/**
 * The IDE side panel's live view of the Unreal Verse (WP20.3).
 *
 * Streams only while the panel is on screen; hidden, scrolled away or minimised, the session
 * closes in the same task. When the full Verse window opens the panel keeps the last frame and
 * says "Verse is open" (WP20.5). The Verse is an optional download: while the host reports
 * `not_installed` the panel shows a plain card with a link to download it and never starts a
 * stream. Without a GPU (`unsupported`), without a Verse host or after a failed start it shows a
 * plain card too.
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
  const [hostStatus, setHostStatus] = useState<VerseHostStatus | null>(null);
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

  // One session per visible stretch; hiding the panel ends it at once. Each showing asks the
  // host first, so a Verse downloaded meanwhile streams on the next showing.
  useEffect(() => {
    if (!visible) return;
    let live = true;
    let session: VerseStreamSession | null = null;
    const begin = (status: VerseHostStatus | null) => {
      if (!live) return;
      setHostStatus(status);
      if (status === "not_installed" || status === "unsupported") return;
      session = startSession();
    };
    const startSession = () => {
      const next = new VerseStreamSession(streamDeps, geometryRef.current, {
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
      sessionRef.current = next;
      void next.start();
      return next;
    };
    if (streamDeps.fetchStatus) {
      void streamDeps.fetchStatus().then(begin, () => begin(null));
    } else {
      begin(null);
    }
    return () => {
      live = false;
      const current = session as VerseStreamSession | null;
      current?.stop();
      if (current && sessionRef.current === current) sessionRef.current = null;
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

  const notInstalled = hostStatus === "not_installed";
  const unsupported = hostStatus === "unsupported";
  const showCard = !notInstalled && (unsupported || phase === "unavailable" || phase === "failed");
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
      {phase === "connecting" && !notInstalled && !unsupported && (
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
          {(unsupported || phase === "unavailable") && <p className="text-xs text-muted-foreground">{text.unavailableHint}</p>}
          {!unsupported && <button
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
          </button>}
        </div>
      )}
      {notInstalled && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-background p-6 text-center" data-testid="verse-stream-not-installed">
          <p className="text-sm text-foreground">{text.notInstalled}</p>
          <p className="text-xs text-muted-foreground">{text.notInstalledHint}</p>
          <button
            type="button"
            onPointerDown={(event) => event.stopPropagation()}
            onClick={openVerseDownload}
            className="inline-flex items-center gap-1.5 text-sm text-foreground underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <Download className="h-3.5 w-3.5" aria-hidden />
            {text.download}
          </button>
        </div>
      )}
    </div>
  );
}
