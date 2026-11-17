/**
 * The video editor's timeline: every track as a row, every piece as a block
 * as long as it runs, a ruler and a playhead across all of them.
 *
 * Rows, top to bottom: the captions, the text and overlay tracks (the top
 * layer first, as they stack in the picture), the main track, the sound
 * tracks. A block is picked with a click (Shift or Ctrl adds to the pick),
 * moved by dragging its body, trimmed by dragging an edge. While a block is
 * dragged only a ghost moves; the change lands as ONE undo step when the
 * pointer lets go, and the preview is drawn again once instead of on every
 * pixel. Edges and moved blocks snap to the playhead, the start and every
 * other edge (Alt drags freely, the magnet button turns it off).
 *
 * The main track is magnetic: dragging one of its pieces reorders it, and
 * trimming one moves everything after it. The other tracks keep their times;
 * an item dropped where another stands goes to the next free track.
 *
 * Pointer events rather than native drag and drop for the blocks, so the drag
 * behaves the same in every engine the app runs in; files from the media bin
 * come in by native drag and drop (`application/x-dodaios-media`).
 */
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent as ReactDragEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
  type WheelEvent as ReactWheelEvent,
} from "react";
import { AudioLines, Captions, Clapperboard, Eye, EyeOff, Image as ImageIcon, Lock, LockOpen, Type, Volume2, VolumeX } from "lucide-react";

import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { MenuItem, Popover } from "../controls";
import { fetchWave, mediaUrl, sideFile, type WavePeaks } from "./clipApi";
import {
  captionKey,
  clipDuration,
  itemKey,
  maxSeconds,
  ms,
  sceneKey,
  snapTargets,
  snapTime,
  type SelKey,
} from "./clipModel";
import {
  MIN_PIECE_SECONDS,
  MIN_SECONDS,
  TRANSITIONS,
  formatClock,
  sceneProblem,
  sceneStarts,
  sceneSummary,
  type MediaEntry,
  type MotionSpec,
  type Scene,
  type Track,
  type TrackItem,
  type Transition,
} from "./motionModel";
import { SCENE_ICONS, TRANSITION_ICONS, kindKey, transitionKey } from "./sceneKinds";

/** The width of the row names on the left. */
export const HEAD = 132;
/** The drag distance before a press on a block becomes a drag. */
const SLOP = 4;
/** How close, in pixels, an edge has to come to snap. */
const SNAP_PX = 8;
const RULER = 26;
export const MEDIA_DRAG_TYPE = "application/x-dodaios-media";

export type RowKind = "captions" | "text" | "overlay" | "main" | "audio";

interface Row {
  key: string;
  kind: RowKind;
  track?: Track;
  height: number;
  label: string;
}

export interface TrackTimelineProps {
  nodeId: string;
  spec: MotionSpec;
  playhead: number;
  playing: boolean;
  selection: Set<SelKey>;
  /** Pixels per second. */
  pps: number;
  snapping: boolean;
  onSelect: (keys: SelKey[], mode: "replace" | "toggle") => void;
  onSeek: (t: number) => void;
  onZoom: (pps: number, anchor?: number) => void;
  onMoveScene: (from: number, to: number) => void;
  onTrimScene: (index: number, edge: "start" | "end", value: number) => void;
  onMoveItem: (id: string, start: number, trackId: string) => void;
  onTrimItem: (id: string, edge: "start" | "end", t: number) => void;
  onMoveCaption: (index: number, start: number) => void;
  onTrimCaption: (index: number, edge: "start" | "end", t: number) => void;
  onTransition: (index: number, transition: Transition) => void;
  onDropMedia: (mediaId: string, t: number, row: RowKind, trackId?: string) => void;
  onTrackFlag: (trackId: string, flag: "muted" | "hidden" | "locked") => void;
}

type DragKind = "move" | "start" | "end";

interface Drag {
  key: SelKey;
  kind: DragKind;
  row: RowKind;
  x0: number;
  y0: number;
  /** The block's start and length when the drag began. */
  start: number;
  seconds: number;
  /** Main track: the piece's index. Captions: the line's index. */
  index: number;
  active: boolean;
  /** Where the ghost is now. */
  ghostStart: number;
  ghostSeconds: number;
  /** Main-track reorder: the slot the piece would land in. */
  slot: number;
  /** Track move: the track under the pointer. */
  trackId?: string;
  snapAt: number | null;
  shortest: number;
  longest: number;
}

function stepFor(pps: number): number {
  const steps = [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300];
  return steps.find((step) => step * pps >= 64) ?? 600;
}

function clockLabel(t: number, step: number): string {
  if (step >= 1) return formatClock(t);
  // Tenths of a second, as a clock writes them: 0:01.5.
  const whole = Math.floor(t + 1e-6);
  const tenths = Math.round((t - whole) * 10);
  return tenths ? `${formatClock(whole)}.${tenths}` : formatClock(whole);
}

export function TrackTimeline(props: TrackTimelineProps) {
  const { nodeId, spec, playhead, playing, selection, pps } = props;
  const t = useT();
  const scroller = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  const dragRef = useRef<Drag | null>(null);
  dragRef.current = drag;
  const [dropAt, setDropAt] = useState<{ row: string; t: number } | null>(null);
  const live = useRef(props);
  live.current = props;

  const duration = clipDuration(spec);
  const starts = useMemo(() => sceneStarts(spec), [spec]);
  const media = spec.media ?? {};
  const tracks = spec.tracks ?? [];
  const [viewWidth, setViewWidth] = useState(800);
  useEffect(() => {
    const box = scroller.current;
    if (!box || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => setViewWidth(box.clientWidth));
    observer.observe(box);
    setViewWidth(box.clientWidth);
    return () => observer.disconnect();
  }, []);
  const width = Math.max(viewWidth - HEAD, (duration + 8) * pps);

  const rows: Row[] = useMemo(() => {
    const out: Row[] = [];
    if (spec.captions?.items.length) out.push({ key: "captions", kind: "captions", height: 30, label: t("nodes.editor.motion.video.rows.captions") });
    const visual = tracks.filter((track) => track.kind !== "audio");
    let textN = 0;
    let overN = 0;
    const named = new Map<string, string>();
    for (const track of visual) {
      if (track.kind === "text") named.set(track.id, fill(t("nodes.editor.motion.video.rows.text"), { n: (textN += 1) }));
      else named.set(track.id, fill(t("nodes.editor.motion.video.rows.overlay"), { n: (overN += 1) }));
    }
    for (const track of [...visual].reverse())
      out.push({ key: track.id, kind: track.kind, track, height: track.kind === "text" ? 34 : 46, label: track.name || named.get(track.id) || "" });
    out.push({ key: "main", kind: "main", height: 62, label: t("nodes.editor.motion.video.rows.main") });
    let audioN = 0;
    for (const track of tracks.filter((each) => each.kind === "audio"))
      out.push({
        key: track.id,
        kind: "audio",
        track,
        height: 46,
        label: track.name || fill(t("nodes.editor.motion.video.rows.audio"), { n: (audioN += 1) }),
      });
    return out;
  }, [spec.captions, tracks, t]);

  // Keep the playhead in view while the clip plays.
  useEffect(() => {
    const box = scroller.current;
    if (!box || !playing) return;
    const x = playhead * pps;
    const visible = box.clientWidth - HEAD;
    if (x < box.scrollLeft || x > box.scrollLeft + visible - 40) box.scrollLeft = Math.max(0, x - visible * 0.2);
  }, [playhead, playing, pps]);

  /* ------------------------------------------------------------ pointer */

  const timeAt = (clientX: number): number => {
    const box = scroller.current;
    if (!box) return 0;
    const rect = box.getBoundingClientRect();
    return Math.max(0, (clientX - rect.left - HEAD + box.scrollLeft) / pps);
  };

  const rowAt = (clientY: number): Row | null => {
    const box = scroller.current;
    if (!box) return null;
    const rect = box.getBoundingClientRect();
    let y = clientY - rect.top - RULER + box.scrollTop;
    for (const row of rows) {
      if (y < row.height) return row;
      y -= row.height;
    }
    return null;
  };

  const seekFromRuler = (event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    const target = event.currentTarget;
    try {
      target.setPointerCapture(event.pointerId);
    } catch {
      // A synthetic pointer cannot be captured; the click still seeks.
    }
    live.current.onSeek(ms(timeAt(event.clientX)));
    const move = (e: PointerEvent) => live.current.onSeek(ms(timeAt(e.clientX)));
    const up = () => {
      target.removeEventListener("pointermove", move);
      target.removeEventListener("pointerup", up);
      target.removeEventListener("pointercancel", up);
    };
    target.addEventListener("pointermove", move);
    target.addEventListener("pointerup", up);
    target.addEventListener("pointercancel", up);
  };

  const beginDrag = (event: ReactPointerEvent<HTMLElement>, init: Omit<Drag, "x0" | "y0" | "active" | "ghostStart" | "ghostSeconds" | "slot" | "snapAt">) => {
    if (event.button !== 0) return;
    event.stopPropagation();
    const additive = event.shiftKey || event.ctrlKey || event.metaKey;
    if (additive) props.onSelect([init.key], "toggle");
    else if (!selection.has(init.key)) props.onSelect([init.key], "replace");
    const state: Drag = {
      ...init,
      x0: event.clientX,
      y0: event.clientY,
      active: false,
      ghostStart: init.start,
      ghostSeconds: init.seconds,
      slot: init.index,
      snapAt: null,
    };
    setDrag(state);
    const target = event.currentTarget;
    try {
      target.setPointerCapture(event.pointerId);
    } catch {
      // See seekFromRuler.
    }
    const targets = snapTargets(spec, playhead, new Set([init.key]));
    const onMove = (e: PointerEvent) => {
      const now = dragRef.current;
      if (!now) return;
      const dx = e.clientX - now.x0;
      if (!now.active && Math.abs(dx) < SLOP && Math.abs(e.clientY - now.y0) < SLOP) return;
      const dt = dx / pps;
      const free = !live.current.snapping || e.altKey;
      const tolerance = SNAP_PX / pps;
      const next: Drag = { ...now, active: true, snapAt: null };
      if (now.kind === "move") {
        let start = Math.max(0, now.start + dt);
        if (!free) {
          const a = snapTime(start, targets, tolerance);
          const b = snapTime(start + now.seconds, targets, tolerance);
          if (a.to !== null && (b.to === null || Math.abs(a.t - start) <= Math.abs(b.t - start - now.seconds))) {
            start = a.t;
            next.snapAt = a.to;
          } else if (b.to !== null) {
            start = b.t - now.seconds;
            next.snapAt = b.to;
          }
        }
        next.ghostStart = ms(Math.max(0, start));
        if (now.row === "main") next.slot = slotAt(e.clientX, now.index);
        if (now.row === "text" || now.row === "overlay" || now.row === "audio") {
          const over = rowAt(e.clientY);
          if (over?.track && over.kind === now.row) next.trackId = over.track.id;
        }
      } else if (now.kind === "start") {
        let edge = now.start + dt;
        if (!free) {
          const s = snapTime(edge, targets, tolerance);
          edge = s.t;
          next.snapAt = s.to;
        }
        const end = now.start + now.seconds;
        // How far the start may move: the shortest piece, and back to its source's start.
        edge = Math.min(edge, end - now.shortest);
        edge = Math.max(edge, end - now.longest, 0);
        next.ghostStart = ms(edge);
        next.ghostSeconds = ms(end - edge);
      } else {
        let edge = now.start + now.seconds + dt;
        if (!free) {
          const s = snapTime(edge, targets, tolerance);
          edge = s.t;
          next.snapAt = s.to;
        }
        next.ghostSeconds = ms(Math.min(now.longest, Math.max(now.shortest, edge - now.start)));
      }
      setDrag(next);
    };
    const onUp = () => {
      target.removeEventListener("pointermove", onMove);
      target.removeEventListener("pointerup", onUp);
      target.removeEventListener("pointercancel", onUp);
      const done = dragRef.current;
      setDrag(null);
      if (!done) return;
      if (!done.active) {
        if (!additive) {
          props.onSelect([done.key], "replace");
          // A click on a block also puts the playhead in it when it stands outside.
          const t0 = done.start;
          const t1 = done.start + done.seconds;
          if (live.current.playhead < t0 || live.current.playhead >= t1) live.current.onSeek(ms(t0));
        }
        return;
      }
      commit(done);
    };
    target.addEventListener("pointermove", onMove);
    target.addEventListener("pointerup", onUp);
    target.addEventListener("pointercancel", onUp);
  };

  const slotAt = (clientX: number, from: number): number => {
    const x = timeAt(clientX);
    let slot = spec.scenes.length;
    for (let n = 0; n < spec.scenes.length; n += 1) {
      if (x < starts[n] + spec.scenes[n].seconds / 2) {
        slot = n;
        break;
      }
    }
    void from;
    return slot;
  };

  const commit = (done: Drag) => {
    const p = live.current;
    const id = done.key.slice(2);
    if (done.row === "main") {
      if (done.kind === "move") {
        const to = done.slot > done.index ? done.slot - 1 : done.slot;
        if (to !== done.index) p.onMoveScene(done.index, to);
      } else if (done.kind === "start") p.onTrimScene(done.index, "start", ms(done.ghostStart - done.start));
      else p.onTrimScene(done.index, "end", done.ghostSeconds);
      return;
    }
    if (done.row === "captions") {
      if (done.kind === "move") p.onMoveCaption(done.index, done.ghostStart);
      else if (done.kind === "start") p.onTrimCaption(done.index, "start", done.ghostStart);
      else p.onTrimCaption(done.index, "end", done.ghostStart + done.ghostSeconds);
      return;
    }
    if (done.kind === "move") p.onMoveItem(id, done.ghostStart, done.trackId ?? "");
    else if (done.kind === "start") p.onTrimItem(id, "start", done.ghostStart);
    else p.onTrimItem(id, "end", done.ghostStart + done.ghostSeconds);
  };

  /* ------------------------------------------------------------ zoom, drop */

  const onWheel = (event: ReactWheelEvent<HTMLDivElement>) => {
    if (!(event.ctrlKey || event.metaKey)) return;
    event.preventDefault();
    const anchor = timeAt(event.clientX);
    props.onZoom(pps * (event.deltaY < 0 ? 1.2 : 1 / 1.2), anchor);
  };

  const onDragOver = (event: ReactDragEvent<HTMLDivElement>, row: Row) => {
    if (!event.dataTransfer.types.includes(MEDIA_DRAG_TYPE)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    setDropAt({ row: row.key, t: timeAt(event.clientX) });
  };

  const onDrop = (event: ReactDragEvent<HTMLDivElement>, row: Row) => {
    const id = event.dataTransfer.getData(MEDIA_DRAG_TYPE);
    setDropAt(null);
    if (!id) return;
    event.preventDefault();
    props.onDropMedia(id, ms(timeAt(event.clientX)), row.kind, row.track?.id);
  };

  /* ------------------------------------------------------------ drawing */

  const step = stepFor(pps);
  const ticks: ReactNode[] = [];
  for (let at = 0; at * pps <= width; at += step) {
    ticks.push(
      <div key={at} className="absolute top-0 h-full border-l border-border/70 pl-1 text-[10px] leading-[14px] text-muted-foreground" style={{ left: at * pps }}>
        {clockLabel(at, step)}
      </div>,
    );
  }

  const ghostFor = (key: SelKey, start: number, seconds: number) =>
    drag && drag.active && drag.key === key ? { start: drag.ghostStart, seconds: drag.ghostSeconds } : { start, seconds };

  const mainBlocks = () => {
    // The magnetic track: a trimmed piece moves the ones after it.
    let at = 0;
    return spec.scenes.map((scene, index) => {
      const key = sceneKey(scene.id ?? `#${index}`);
      let seconds = scene.seconds;
      let start = at;
      if (drag?.active && drag.key === key && drag.kind !== "move") {
        seconds = drag.ghostSeconds;
      }
      if (drag?.active && drag.key === key && drag.kind === "move") start = drag.ghostStart;
      const block = (
        <SceneBlock
          key={key}
          nodeId={nodeId}
          scene={scene}
          index={index}
          media={media}
          left={start * pps}
          width={Math.max(4, seconds * pps)}
          selected={selection.has(key)}
          dragging={!!drag?.active && drag.key === key}
          pps={pps}
          onPointerDown={(event, kind) =>
            beginDrag(event, {
              key,
              kind,
              row: "main",
              start: at,
              seconds: scene.seconds,
              index,
              shortest: scene.type === "video" ? MIN_PIECE_SECONDS : MIN_SECONDS,
              longest:
                kind === "end"
                  ? scene.type === "video"
                    ? maxSeconds(spec, scene)
                    : 20
                  : scene.type === "video"
                    ? scene.seconds + (scene.in ?? 0) / (scene.speed ?? 1)
                    : 20,
            })
          }
        />
      );
      if (!(drag?.active && drag.key === key && drag.kind === "move")) at += seconds;
      else at += scene.seconds;
      return block;
    });
  };

  const transitionChips = () =>
    spec.scenes.slice(1).map((scene, n) => {
      const index = n + 1;
      const Icon = TRANSITION_ICONS[scene.transition];
      return (
        <Popover
          key={`tr-${scene.id ?? index}`}
          label={fill(t("nodes.editor.motion.timeline.transition"), { n: index + 1, transition: t(transitionKey(scene.transition)) })}
          role="menu"
          trigger={
            <button
              type="button"
              className={cn(
                "absolute top-1/2 z-[3] grid h-5 w-5 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full border bg-background text-muted-foreground shadow-sm hover:text-foreground",
                scene.transition === "cut" ? "border-border opacity-60 hover:opacity-100" : "border-accent text-accent",
              )}
              style={{ left: starts[index] * pps }}
              aria-label={fill(t("nodes.editor.motion.timeline.transition"), { n: index + 1, transition: t(transitionKey(scene.transition)) })}
              data-testid={`clip-transition-${index}`}
            >
              <Icon className="h-3 w-3" aria-hidden />
            </button>
          }
        >
          <div className="w-44">
            {TRANSITIONS.map((kind) => {
              const KindIcon = TRANSITION_ICONS[kind];
              return (
                <MenuItem
                  key={kind}
                  label={t(transitionKey(kind))}
                  icon={<KindIcon aria-hidden />}
                  checked={scene.transition === kind}
                  onClick={() => props.onTransition(index, kind)}
                />
              );
            })}
          </div>
        </Popover>
      );
    });

  const itemBlocks = (row: Row) => {
    const track = row.track!;
    return track.items.map((item) => {
      const key = itemKey(item.id);
      const shown = ghostFor(key, item.start, item.seconds);
      const entry = item.media ? media[item.media] : undefined;
      const shortest = MIN_PIECE_SECONDS;
      return (
        <ItemBlock
          key={item.id}
          nodeId={nodeId}
          kind={track.kind}
          item={item}
          entry={entry}
          left={shown.start * pps}
          width={Math.max(4, shown.seconds * pps)}
          height={row.height}
          selected={selection.has(key)}
          dragging={!!drag?.active && drag.key === key}
          locked={!!track.locked}
          dim={!!track.hidden || !!track.muted}
          onPointerDown={(event, kind) =>
            track.locked
              ? props.onSelect([key], "replace")
              : beginDrag(event, {
                  key,
                  kind,
                  row: track.kind,
                  start: item.start,
                  seconds: item.seconds,
                  index: 0,
                  trackId: track.id,
                  shortest,
                  longest:
                    kind === "start"
                      ? entry && entry.kind !== "image"
                        ? item.seconds + (item.in ?? 0) / (item.speed ?? 1)
                        : item.start + item.seconds
                      : maxSeconds(spec, item),
                })
          }
        />
      );
    });
  };

  const captionBlocks = () =>
    (spec.captions?.items ?? []).map((line, index) => {
      const key = captionKey(index);
      const shown = ghostFor(key, line.start, line.end - line.start);
      return (
        <div
          key={`${index}-${line.start}`}
          role="option"
          aria-selected={selection.has(key)}
          className={cn(
            "group absolute top-1 bottom-1 cursor-grab overflow-hidden rounded border px-1.5 text-[11px] leading-[20px] text-foreground",
            selection.has(key) ? "border-accent bg-accent/25 ring-1 ring-accent" : "border-amber-500/40 bg-amber-500/15",
          )}
          style={{ left: shown.start * pps, width: Math.max(4, shown.seconds * pps) }}
          onPointerDown={(event) =>
            beginDrag(event, { key, kind: "move", row: "captions", start: line.start, seconds: line.end - line.start, index, shortest: 0.2, longest: 30 })
          }
          title={line.text}
          data-testid={`clip-caption-${index}`}
        >
          <span className="truncate">{line.text}</span>
          <Edge side="start" onPointerDown={(event) => beginDrag(event, { key, kind: "start", row: "captions", start: line.start, seconds: line.end - line.start, index, shortest: 0.2, longest: line.end })} />
          <Edge side="end" onPointerDown={(event) => beginDrag(event, { key, kind: "end", row: "captions", start: line.start, seconds: line.end - line.start, index, shortest: 0.2, longest: 30 })} />
        </div>
      );
    });

  const totalHeight = rows.reduce((sum, row) => sum + row.height, 0);

  return (
    <div
      ref={scroller}
      className="relative min-h-0 flex-1 overflow-auto border-t border-border bg-sidebar/60 select-none"
      onWheel={onWheel}
      data-testid="clip-timeline"
      role="listbox"
      aria-multiselectable="true"
      aria-label={t("nodes.editor.motion.video.timeline")}
    >
      <div className="relative" style={{ width: width + HEAD, height: RULER + totalHeight }}>
        {/* The ruler: a press or a drag moves the playhead. */}
        <div className="sticky top-0 z-[6] flex" style={{ height: RULER }}>
          <div className="sticky left-0 z-[7] shrink-0 border-b border-r border-border bg-sidebar" style={{ width: HEAD }} />
          <div className="relative flex-1 cursor-text border-b border-border bg-sidebar" onPointerDown={seekFromRuler} data-testid="clip-ruler">
            {ticks}
          </div>
        </div>
        {rows.map((row) => (
          <div key={row.key} className="relative flex border-b border-border/60" style={{ height: row.height }} data-row={row.kind}>
            <RowHead row={row} onFlag={props.onTrackFlag} />
            <div
              className={cn("relative flex-1", row.kind === "main" ? "bg-background/40" : "", dropAt?.row === row.key && "bg-accent/10")}
              onPointerDown={(event) => {
                if (event.target !== event.currentTarget) return;
                props.onSelect([], "replace");
                props.onSeek(ms(timeAt(event.clientX)));
              }}
              onDragOver={(event) => onDragOver(event, row)}
              onDragLeave={() => setDropAt(null)}
              onDrop={(event) => onDrop(event, row)}
            >
              {row.kind === "main" && (
                <>
                  {mainBlocks()}
                  {transitionChips()}
                  {drag?.active && drag.row === "main" && drag.kind === "move" && (
                    <div className="absolute top-0 bottom-0 z-[4] w-0.5 bg-accent" style={{ left: (starts[drag.slot] ?? duration) * pps }} />
                  )}
                </>
              )}
              {row.kind === "captions" && captionBlocks()}
              {row.track && itemBlocks(row)}
              {dropAt?.row === row.key && <div className="pointer-events-none absolute top-0 bottom-0 w-0.5 bg-accent" style={{ left: dropAt.t * pps }} />}
            </div>
          </div>
        ))}
        {/* The playhead and, while a drag snaps, the line it snapped to. */}
        <div
          className="pointer-events-none absolute top-0 z-[8] w-px bg-red-500"
          style={{ left: HEAD + playhead * pps, height: RULER + totalHeight }}
          data-testid="clip-playhead"
        >
          <div className="absolute -left-[5px] top-0 h-3 w-[11px] rounded-b-sm bg-red-500" />
        </div>
        {drag?.active && drag.snapAt !== null && (
          <div className="pointer-events-none absolute top-0 z-[8] w-px bg-amber-400" style={{ left: HEAD + drag.snapAt * pps, height: RULER + totalHeight }} />
        )}
      </div>
    </div>
  );
}

function RowHead({ row, onFlag }: { row: Row; onFlag: (trackId: string, flag: "muted" | "hidden" | "locked") => void }) {
  const t = useT();
  const Icon = row.kind === "captions" ? Captions : row.kind === "text" ? Type : row.kind === "overlay" ? ImageIcon : row.kind === "audio" ? AudioLines : Clapperboard;
  const track = row.track;
  const flagButton = (flag: "muted" | "hidden" | "locked", on: boolean, OnIcon: typeof Eye, OffIcon: typeof Eye, label: string) => (
    <button
      type="button"
      className={cn("grid h-5 w-5 place-items-center rounded hover:bg-muted", on ? "text-accent" : "text-muted-foreground")}
      aria-label={label}
      aria-pressed={on}
      title={label}
      onClick={() => track && onFlag(track.id, flag)}
    >
      {on ? <OnIcon className="h-3 w-3" aria-hidden /> : <OffIcon className="h-3 w-3" aria-hidden />}
    </button>
  );
  return (
    <div className="sticky left-0 z-[5] flex shrink-0 items-center gap-1.5 border-r border-border bg-sidebar px-2 text-xs" style={{ width: HEAD }}>
      <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
      <span className="min-w-0 flex-1 truncate font-medium" title={row.label}>
        {row.label}
      </span>
      {track && (
        <div className="flex shrink-0 items-center">
          {track.kind !== "text" && flagButton("muted", !!track.muted, VolumeX, Volume2, t("nodes.editor.motion.video.rows.mute"))}
          {track.kind !== "audio" && flagButton("hidden", !!track.hidden, EyeOff, Eye, t("nodes.editor.motion.video.rows.hide"))}
          {flagButton("locked", !!track.locked, Lock, LockOpen, t("nodes.editor.motion.video.rows.lock"))}
        </div>
      )}
    </div>
  );
}

function Edge({ side, onPointerDown }: { side: "start" | "end"; onPointerDown: (event: ReactPointerEvent<HTMLElement>) => void }) {
  return (
    <span
      aria-hidden
      onPointerDown={(event) => {
        event.stopPropagation();
        onPointerDown(event);
      }}
      className={cn(
        "absolute top-0 bottom-0 z-[2] w-2 cursor-ew-resize opacity-0 transition-opacity group-hover:opacity-100",
        side === "start" ? "left-0 rounded-l bg-white/40" : "right-0 rounded-r bg-white/40",
      )}
    />
  );
}

function SceneBlock({
  nodeId,
  scene,
  index,
  media,
  left,
  width,
  selected,
  dragging,
  pps,
  onPointerDown,
}: {
  nodeId: string;
  scene: Scene;
  index: number;
  media: Record<string, MediaEntry>;
  left: number;
  width: number;
  selected: boolean;
  dragging: boolean;
  pps: number;
  onPointerDown: (event: ReactPointerEvent<HTMLElement>, kind: DragKind) => void;
}) {
  const t = useT();
  const entry = scene.media ? media[scene.media] : undefined;
  const Icon = SCENE_ICONS[scene.type];
  const label = scene.type === "video" ? entry?.name ?? "" : sceneSummary(scene) || t(kindKey(scene.type));
  const problem = sceneProblem(scene);
  const strip = entry && entry.kind === "video" ? mediaUrl(nodeId, sideFile(entry.file, "strip.jpg")) : entry ? mediaUrl(nodeId, sideFile(entry.file, "poster.jpg")) : "";
  return (
    <div
      role="option"
      aria-selected={selected}
      aria-label={fill(t("nodes.editor.motion.video.block"), { n: index + 1, file: label, seconds: scene.seconds.toFixed(1) })}
      className={cn(
        "group absolute top-1.5 bottom-1.5 cursor-grab overflow-hidden rounded-md border text-[11px] text-white",
        scene.type === "video" ? "border-sky-400/50 bg-sky-900/70" : "border-violet-400/50 bg-violet-900/60",
        selected && "ring-2 ring-accent",
        dragging && "z-[3] opacity-80 shadow-lg",
        problem && "border-warning",
      )}
      style={{
        left,
        width,
        backgroundImage: strip ? `url("${strip}")` : undefined,
        // The strip shows the whole source: stretched to the source's length at
        // this zoom and shifted to where the piece starts in it.
        ...(entry && entry.kind === "video" && entry.seconds
          ? {
              backgroundSize: `${(entry.seconds / (scene.speed ?? 1)) * pps}px 100%`,
              backgroundPosition: `${-((scene.in ?? 0) / (scene.speed ?? 1)) * pps}px 0`,
              backgroundRepeat: "no-repeat",
            }
          : { backgroundSize: "auto 100%", backgroundRepeat: "repeat-x" }),
      }}
      onPointerDown={(event) => onPointerDown(event, "move")}
      data-testid={`clip-scene-${index}`}
    >
      <div className="absolute inset-x-0 top-0 flex items-center gap-1 bg-gradient-to-b from-black/70 to-transparent px-1.5 py-0.5">
        <Icon className="h-3 w-3 shrink-0" aria-hidden />
        <span className="truncate">{label}</span>
      </div>
      <span className="absolute bottom-0.5 right-1 rounded bg-black/50 px-1 text-[10px] tabular-nums">{scene.seconds.toFixed(1)}s</span>
      {scene.type === "video" && (scene.speed ?? 1) !== 1 && <span className="absolute bottom-0.5 left-1 rounded bg-black/50 px-1 text-[10px]">{scene.speed}×</span>}
      <Edge side="start" onPointerDown={(event) => onPointerDown(event, "start")} />
      <Edge side="end" onPointerDown={(event) => onPointerDown(event, "end")} />
    </div>
  );
}

function ItemBlock({
  nodeId,
  kind,
  item,
  entry,
  left,
  width,
  height,
  selected,
  dragging,
  locked,
  dim,
  onPointerDown,
}: {
  nodeId: string;
  kind: Track["kind"];
  item: TrackItem;
  entry?: MediaEntry;
  left: number;
  width: number;
  height: number;
  selected: boolean;
  dragging: boolean;
  locked: boolean;
  dim: boolean;
  onPointerDown: (event: ReactPointerEvent<HTMLElement>, kind: DragKind) => void;
}) {
  const colors =
    kind === "text" ? "border-fuchsia-400/50 bg-fuchsia-900/60" : kind === "overlay" ? "border-teal-400/50 bg-teal-900/60" : "border-emerald-400/50 bg-emerald-900/50";
  const label = kind === "text" ? item.text ?? "" : entry?.name ?? "";
  const poster = kind === "overlay" && entry ? mediaUrl(nodeId, sideFile(entry.file, "poster.jpg")) : "";
  return (
    <div
      role="option"
      aria-selected={selected}
      aria-label={label}
      className={cn(
        "group absolute top-1 bottom-1 overflow-hidden rounded-md border text-[11px] text-white",
        colors,
        locked ? "cursor-not-allowed" : "cursor-grab",
        selected && "ring-2 ring-accent",
        dragging && "z-[3] opacity-80 shadow-lg",
        dim && "opacity-50",
      )}
      style={{ left, width }}
      onPointerDown={(event) => onPointerDown(event, "move")}
      data-testid={`clip-item-${item.id}`}
    >
      {kind === "audio" && entry && <Waveform nodeId={nodeId} entry={entry} item={item} width={width} height={height - 8} />}
      {poster && <img src={poster} alt="" className="absolute left-0 top-0 h-full w-auto opacity-80" draggable={false} />}
      <span className={cn("relative block truncate px-1.5 leading-[18px]", poster && "pl-12")}>{label}</span>
      {kind === "audio" && item.duck && <span className="absolute bottom-0.5 right-1 rounded bg-black/40 px-1 text-[9px]">duck</span>}
      {!locked && <Edge side="start" onPointerDown={(event) => onPointerDown(event, "start")} />}
      {!locked && <Edge side="end" onPointerDown={(event) => onPointerDown(event, "end")} />}
    </div>
  );
}

/** A sound's peaks over the part of its source the item plays. */
function Waveform({ nodeId, entry, item, width, height }: { nodeId: string; entry: MediaEntry; item: TrackItem; width: number; height: number }) {
  const [wave, setWave] = useState<WavePeaks | null>(null);
  useEffect(() => {
    let alive = true;
    void fetchWave(nodeId, entry.file).then((found) => {
      if (alive) setWave(found);
    });
    return () => {
      alive = false;
    };
  }, [nodeId, entry.file]);
  const path = useMemo(() => {
    if (!wave || !wave.peaks.length || width < 4) return "";
    const from = (item.in ?? 0) * wave.rate;
    const span = item.seconds * (item.speed ?? 1) * wave.rate;
    const columns = Math.max(2, Math.floor(width / 2));
    const mid = height / 2;
    const volume = item.muted ? 0.15 : Math.max(0.15, item.volume ?? 1);
    let d = "";
    for (let c = 0; c < columns; c += 1) {
      const a = Math.floor(from + (span * c) / columns);
      const b = Math.max(a + 1, Math.floor(from + (span * (c + 1)) / columns));
      let peak = 0;
      for (let n = a; n < b && n < wave.peaks.length; n += 1) peak = Math.max(peak, wave.peaks[n] ?? 0);
      const h = Math.max(0.5, peak * volume * mid);
      const x = (c / columns) * width;
      d += `M${x.toFixed(1)} ${(mid - h).toFixed(1)}V${(mid + h).toFixed(1)}`;
    }
    return d;
  }, [wave, item.in, item.seconds, item.speed, item.volume, item.muted, width, height]);
  if (!path) return null;
  return (
    <svg className="pointer-events-none absolute left-0 top-1" width={width} height={height} aria-hidden>
      <path d={path} stroke="rgba(167,243,208,.75)" strokeWidth={1.2} />
    </svg>
  );
}
