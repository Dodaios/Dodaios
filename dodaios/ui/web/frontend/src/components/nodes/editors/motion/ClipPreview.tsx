/**
 * The clip itself, drawn by the server from the unsaved spec, as the video
 * editor's live preview.
 *
 * The page is the very film the stage shows and the export renders
 * (`POST /api/nodes/{id}/preview`), so what the person sees while editing is
 * what they get. The editor shows it bare (`dodaios-film-view`: no controls
 * of its own, the safe-zone guide on request) and steers it with the film's
 * own messages (`dodaios/nodes/kinds/motion.py`):
 *
 * * standing, the page shows the exact frame at the playhead; scrubbing moves
 *   it (`dodaios-film-seek` without play);
 * * "Play" plays from the playhead; the page reports where it is
 *   (`dodaios-film-time`), so the timeline's playhead follows;
 * * in text mode the page is in the bridge's EDIT mode: the card under the
 *   playhead stands settled and its texts can be written into right there
 *   (`dodaios-node-edit`, applied as one undo step);
 * * a click on a text or picture layer picks it (`dodaios-film-pick`), a drag
 *   moves it (`dodaios-film-move` with its new centre).
 *
 * A page drawn again would blank the frame for a moment on every change, so
 * there are two frames: the new page loads in the hidden one and takes over
 * once it said it is ready and was put on the right frame.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, Loader2 } from "lucide-react";

import { useThemeValue } from "@/hooks/useTheme";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { NODE_EDIT_MESSAGE, NODE_EDIT_STATE_MESSAGE, NODE_MODE_MESSAGE, NODE_READY_MESSAGE } from "../../nodeBridge";
import { preparePreviewHtml, useNodePreview } from "../PreviewFrame";

export const FILM_SEEK_MESSAGE = "dodaios-film-seek";
export const FILM_TIME_MESSAGE = "dodaios-film-time";
export const FILM_VIEW_MESSAGE = "dodaios-film-view";
export const FILM_PICK_MESSAGE = "dodaios-film-pick";
export const FILM_MOVE_MESSAGE = "dodaios-film-move";
export const FILM_KEY_MESSAGE = "dodaios-film-key";

export interface FilmTime {
  t: number;
  scene: number;
  playing: boolean;
}

export interface ClipPreviewProps {
  nodeId: string;
  title: string;
  spec: unknown;
  /** The playhead, in seconds: the frame the standing clip shows. */
  at: number;
  /** The scene under the playhead (where a fresh page opens). */
  scene: number;
  /** Play from `at`; false stands the clip on it. */
  playing: boolean;
  /** Changes whenever "Play" is pressed, so pressing it again restarts. */
  playToken: number;
  /** The card's texts are fields to write into (the bridge's edit mode). */
  editText: boolean;
  /** The platforms' safe zone drawn over the frame. */
  guides: boolean;
  /** A text written in the page: apply it, return whether it was taken. */
  onEdit: (path: string, value: string | boolean, as: string) => boolean;
  onTime: (time: FilmTime) => void;
  /** A layer picked in the frame ("" for the background). */
  onPick?: (id: string) => void;
  /** A layer dragged to a new centre (percent of the frame). */
  onMoveLayer?: (id: string, x: number, y: number) => void;
  /** A key pressed in the bare page, passed on to the editor. */
  onKey?: (key: string, shift: boolean, ctrl: boolean, alt: boolean) => void;
  className?: string;
}

/** The page with the scene it should open standing on. */
export function withScene(html: string, scene: number): string {
  const at = ` data-film-scene="${Math.max(0, Math.floor(scene))}"`;
  return /<html[^>]*>/i.test(html) ? html.replace(/<html([^>]*)>/i, (_match, attrs: string) => `<html${attrs}${at}>`) : html;
}

interface Slot {
  doc: string;
  /** Bumped per page, so a ready message of an older page in this slot is ignored. */
  serial: number;
}

/** Bounded, plain reading of a message from the page. */
function readMessage(data: unknown): Record<string, unknown> | null {
  return data !== null && typeof data === "object" && !Array.isArray(data) ? (data as Record<string, unknown>) : null;
}

export function ClipPreview({
  nodeId,
  title,
  spec,
  at,
  scene,
  playing,
  playToken,
  editText,
  guides,
  onEdit,
  onTime,
  onPick,
  onMoveLayer,
  onKey,
  className,
}: ClipPreviewProps) {
  const t = useT();
  const theme = useThemeValue();
  const preview = useNodePreview(nodeId, spec, { delayMs: 250 });
  const frames = [useRef<HTMLIFrameElement>(null), useRef<HTMLIFrameElement>(null)];
  const [slots, setSlots] = useState<[Slot, Slot]>([
    { doc: "", serial: 0 },
    { doc: "", serial: 0 },
  ]);
  const [active, setActive] = useState<0 | 1>(0);
  const [shown, setShown] = useState(false);
  // The newest state, for the message handler (registered once).
  const live = useRef({ at, scene, playing, editText, guides, active, onEdit, onTime, onPick, onMoveLayer, onKey, loading: -1 as -1 | 0 | 1 });
  live.current = { ...live.current, at, scene, playing, editText, guides, active, onEdit, onTime, onPick, onMoveLayer, onKey };

  const post = useCallback((slot: 0 | 1, message: Record<string, unknown>) => {
    try {
      frames[slot].current?.contentWindow?.postMessage(message, "*");
    } catch {
      // A frame being replaced has no window to talk to; the next page asks again.
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** Put the page in `slot` where the editor stands: playing, or on the playhead's frame. */
  const steer = useCallback(
    (slot: 0 | 1, play: boolean) => {
      const now = live.current;
      post(slot, { type: FILM_VIEW_MESSAGE, bare: true, guides: now.guides && !play });
      post(slot, { type: NODE_MODE_MESSAGE, mode: now.editText && !play ? "edit" : "view" });
      post(slot, { type: FILM_SEEK_MESSAGE, t: now.at, play });
    },
    [post],
  );

  // A new page goes into the hidden frame.
  useEffect(() => {
    if (preview.html === null) return;
    const doc = preparePreviewHtml(withScene(preview.html, live.current.scene), theme);
    setSlots((now) => {
      const target = (live.current.loading === -1 ? 1 - live.current.active : live.current.loading) as 0 | 1;
      live.current.loading = target;
      const next: [Slot, Slot] = [now[0], now[1]];
      next[target] = { doc, serial: now[target].serial + 1 };
      return next;
    });
  }, [preview.html, theme]);

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      const slot = frames.findIndex((frame) => frame.current !== null && event.source === frame.current.contentWindow);
      if (slot < 0) return;
      const message = readMessage(event.data);
      if (!message) return;
      const now = live.current;
      if (message.type === NODE_READY_MESSAGE) {
        // A fresh page while the clip plays keeps playing from where it is.
        steer(slot as 0 | 1, now.playing);
        if (slot === now.loading) {
          live.current.loading = -1;
          setActive(slot as 0 | 1);
          setShown(true);
          // The page it replaces falls silent.
          post((1 - slot) as 0 | 1, { type: FILM_SEEK_MESSAGE, t: now.at, play: false });
        }
        return;
      }
      // Only the page on screen speaks for the clip.
      if (slot !== now.active) return;
      if (message.type === NODE_EDIT_MESSAGE) {
        const id = Number(message.id);
        const path = typeof message.path === "string" ? message.path.slice(0, 400) : "";
        const value = typeof message.value === "boolean" ? message.value : String(message.value ?? "").slice(0, 2000);
        const as = typeof message.as === "string" ? message.as : "text";
        const taken = path !== "" && now.onEdit(path, value, as);
        post(slot as 0 | 1, { type: NODE_EDIT_STATE_MESSAGE, id, state: taken ? "saved" : "failed" });
      } else if (message.type === FILM_TIME_MESSAGE) {
        const time = Number(message.t);
        const index = Number(message.scene);
        if (Number.isFinite(time) && Number.isInteger(index)) now.onTime({ t: time, scene: index, playing: message.playing === true });
      } else if (message.type === FILM_PICK_MESSAGE) {
        now.onPick?.(typeof message.id === "string" ? message.id.slice(0, 40) : "");
      } else if (message.type === FILM_KEY_MESSAGE) {
        if (typeof message.key === "string") now.onKey?.(message.key.slice(0, 20), message.shift === true, message.ctrl === true, message.alt === true);
      } else if (message.type === FILM_MOVE_MESSAGE) {
        const x = Number(message.x);
        const y = Number(message.y);
        if (typeof message.id === "string" && Number.isFinite(x) && Number.isFinite(y)) now.onMoveLayer?.(message.id.slice(0, 40), x, y);
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [steer, post]);

  // Play and Stop, text mode and the guide steer the page on screen at once.
  useEffect(() => {
    if (shown) steer(active, playing);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing, playToken, editText, guides]);

  // Scrubbing: the standing page follows the playhead, at most once a frame.
  const pending = useRef(0);
  useEffect(() => {
    if (!shown || playing) return;
    if (pending.current) cancelAnimationFrame(pending.current);
    pending.current = requestAnimationFrame(() => {
      pending.current = 0;
      post(live.current.active, { type: FILM_SEEK_MESSAGE, t: live.current.at, play: false });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [at]);

  return (
    <div className={cn("relative min-h-0 overflow-hidden bg-black/90", className)} data-testid="motion-preview">
      {slots.map((slot, index) => (
        <iframe
          key={index}
          ref={frames[index]}
          title={index === active ? fill(t("nodes.editor.motion.preview.label"), { title }) : ""}
          aria-hidden={index !== active || undefined}
          tabIndex={index === active ? 0 : -1}
          srcDoc={slot.doc}
          sandbox="allow-scripts"
          allow="autoplay"
          data-testid={`motion-preview-frame-${index}`}
          data-active={index === active && shown ? "true" : "false"}
          className={cn(
            "absolute inset-0 h-full w-full border-0 bg-transparent",
            index === active && shown ? "visible" : "invisible",
          )}
        />
      ))}
      {!shown && (
        <div className="absolute inset-0 flex items-center justify-center gap-2 text-sm text-muted-foreground" role="status">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          {t("nodes.editor.motion.preview.loading")}
        </div>
      )}
      {preview.error && (
        <div
          role="status"
          className="absolute inset-x-3 top-3 flex items-start gap-2 rounded-md border border-warning/40 bg-background/95 px-3 py-2 text-sm text-warning shadow-sm"
          data-testid="motion-preview-error"
        >
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          <span>{fill(t("nodes.editor.motion.preview.error"), { reason: preview.error })}</span>
        </div>
      )}
    </div>
  );
}
