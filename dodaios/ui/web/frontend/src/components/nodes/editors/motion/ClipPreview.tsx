/**
 * The clip itself, drawn by the server from the unsaved spec, as the editor's
 * live preview.
 *
 * The page is the very film the stage shows (`POST /api/nodes/{id}/preview`),
 * so what the person sees while editing is what they get. It is steered with
 * the film's own messages (`dodaios/nodes/kinds/motion.py`):
 *
 * * While the clip stands, the page is in the bridge's EDIT mode: it shows
 *   the picked scene settled, and its texts can be clicked and written into
 *   right there. Each such edit comes back as `dodaios-node-edit`; the editor
 *   applies it to the spec (one undo step) and answers whether it was taken.
 * * "Play" switches the page to view mode and asks it to play from a scene
 *   (`dodaios-film-seek`); the page reports where it is
 *   (`dodaios-film-time`), so the timeline's playhead follows.
 *
 * A page drawn again would blank the frame for a moment on every change, so
 * there are two frames: the new page loads in the hidden one and takes over
 * once it said it is ready and was put on the right scene. The page opens on
 * the picked scene by itself (`data-film-scene`), never playing from the
 * start first.
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

export interface FilmTime {
  t: number;
  scene: number;
  playing: boolean;
}

export interface ClipPreviewProps {
  nodeId: string;
  title: string;
  spec: unknown;
  /** The picked scene: where the standing clip is shown. */
  selected: number;
  /** When each scene starts, in seconds. */
  starts: readonly number[];
  /** Play from `selected`; false stands the clip on it, ready to be written into. */
  playing: boolean;
  /** Changes whenever "Play" is pressed, so pressing it again restarts. */
  playToken: number;
  /** A text written in the page: apply it, return whether it was taken. */
  onEdit: (path: string, value: string | boolean, as: string) => boolean;
  onTime: (time: FilmTime) => void;
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
  selected,
  starts,
  playing,
  playToken,
  onEdit,
  onTime,
  className,
}: ClipPreviewProps) {
  const t = useT();
  const theme = useThemeValue();
  const preview = useNodePreview(nodeId, spec, { delayMs: 300 });
  const frames = [useRef<HTMLIFrameElement>(null), useRef<HTMLIFrameElement>(null)];
  const [slots, setSlots] = useState<[Slot, Slot]>([
    { doc: "", serial: 0 },
    { doc: "", serial: 0 },
  ]);
  const [active, setActive] = useState<0 | 1>(0);
  const [shown, setShown] = useState(false);
  // The newest state, for the message handler (registered once).
  const live = useRef({ selected, starts, playing, active, onEdit, onTime, loading: -1 as -1 | 0 | 1 });
  live.current = { ...live.current, selected, starts, playing, active, onEdit, onTime };

  const post = useCallback((slot: 0 | 1, message: Record<string, unknown>) => {
    try {
      frames[slot].current?.contentWindow?.postMessage(message, "*");
    } catch {
      // A frame being replaced has no window to talk to; the next page asks again.
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** Put the page in `slot` where the editor stands: playing, or settled on the picked scene. */
  const steer = useCallback(
    (slot: 0 | 1, play: boolean) => {
      const now = live.current;
      const at = now.starts[now.selected] ?? 0;
      post(slot, { type: NODE_MODE_MESSAGE, mode: play ? "view" : "edit" });
      post(slot, { type: FILM_SEEK_MESSAGE, t: at, play });
    },
    [post],
  );

  // A new page goes into the hidden frame.
  useEffect(() => {
    if (preview.html === null) return;
    const doc = preparePreviewHtml(withScene(preview.html, live.current.selected), theme);
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
        steer(slot as 0 | 1, now.playing);
        if (slot === now.loading) {
          live.current.loading = -1;
          setActive(slot as 0 | 1);
          setShown(true);
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
        const scene = Number(message.scene);
        if (Number.isFinite(time) && Number.isInteger(scene)) now.onTime({ t: time, scene, playing: message.playing === true });
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [steer, post]);

  // Picking another scene, or Play and Stop, steer the page on screen.
  useEffect(() => {
    if (shown) steer(active, playing);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, playing, playToken]);

  return (
    <div className={cn("relative min-h-0 overflow-hidden bg-muted/30", className)} data-testid="motion-preview">
      {slots.map((slot, index) => (
        <iframe
          key={index}
          ref={frames[index]}
          title={index === active ? fill(t("nodes.editor.motion.preview.label"), { title }) : ""}
          aria-hidden={index !== active || undefined}
          tabIndex={index === active ? 0 : -1}
          srcDoc={slot.doc}
          sandbox="allow-scripts"
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
