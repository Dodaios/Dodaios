/**
 * The clip's timeline: every scene as a block as long as it runs.
 *
 * A block is picked with a click or the arrow keys, dragged sideways to a new
 * place (or moved with Alt+arrow), and its right edge is a handle that drags
 * its length (or takes the arrow keys, a tenth of a second at a time, half a
 * second with Shift). Between two blocks sits the transition the later scene
 * comes in with; a click picks another. While the clip plays, a playhead runs
 * across and the playing scene is marked.
 *
 * Why blocks sized by time rather than a list of equal cards: the length of a
 * scene IS its rhythm, and a clip's pacing is read best at a glance. The
 * blocks never get narrower than a readable minimum, so a long clip scrolls.
 *
 * Reordering is done with pointer events rather than the browser's native
 * drag and drop: it behaves the same in every engine the app runs in (the
 * macOS web view included), and the drop place can be drawn exactly.
 */
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { AlertCircle, Plus } from "lucide-react";

import { fill, useT, useUiLanguage } from "@/i18n";
import { cn } from "@/lib/utils";
import { MenuItem, Popover } from "../controls";
import {
  MAX_SCENES,
  MAX_SECONDS,
  MIN_SECONDS,
  SCENE_KINDS,
  TRANSITIONS,
  clampSeconds,
  dropIndex,
  formatClock,
  formatSeconds,
  sceneProblem,
  sceneStarts,
  sceneSummary,
  totalSeconds,
  type MotionSpec,
  type SceneKind,
  type Transition,
} from "./motionModel";
import { SCENE_ICONS, TRANSITION_ICONS, kindKey, transitionKey } from "./sceneKinds";

/** The gap between two blocks: room for the transition chip. */
const GAP = 22;
/** A block is never narrower than this, whatever its length. */
const MIN_BLOCK = 76;
/** Pixels per second when the timeline has not been measured (tests, first paint). */
const FALLBACK_PPS = 48;
/** Pointer travel before a press on a block becomes a drag. */
const DRAG_SLOP = 5;

export interface TimelineProps {
  spec: MotionSpec;
  selected: number;
  onSelect: (index: number) => void;
  onMove: (from: number, to: number) => void;
  /** A length drag in progress (`final` false) or ended (`final` true). */
  onSeconds: (index: number, seconds: number, final: boolean) => void;
  onTransition: (index: number, transition: Transition) => void;
  onAdd: (kind: SceneKind) => void;
  onDuplicate: (index: number) => void;
  onRemove: (index: number) => void;
  /** Where the playing clip is, or null when it stands. */
  playhead: { t: number; scene: number } | null;
}

/** Each block's left edge and width at `pps` pixels per second. */
export function layoutBlocks(seconds: readonly number[], pps: number): { left: number; width: number }[] {
  let left = 0;
  return seconds.map((length) => {
    const width = Math.max(MIN_BLOCK, length * pps);
    const box = { left, width };
    left += width + GAP;
    return box;
  });
}

/** The drop slot (0…count) for a pointer at `x` over blocks laid out as `boxes`. */
export function slotAt(boxes: readonly { left: number; width: number }[], x: number): number {
  for (let index = 0; index < boxes.length; index += 1) {
    if (x < boxes[index].left + boxes[index].width / 2) return index;
  }
  return boxes.length;
}

type Drag =
  | { kind: "move"; index: number; startX: number; pointer: number; active: boolean; slot: number }
  | { kind: "length"; index: number; startX: number; pointer: number; start: number; pps: number };

export function Timeline({
  spec,
  selected,
  onSelect,
  onMove,
  onSeconds,
  onTransition,
  onAdd,
  onDuplicate,
  onRemove,
  playhead,
}: TimelineProps) {
  const t = useT();
  const language = useUiLanguage();
  const track = useRef<HTMLDivElement>(null);
  const blocks = useRef<(HTMLDivElement | null)[]>([]);
  const [width, setWidth] = useState(0);
  const [drag, setDrag] = useState<Drag | null>(null);
  const dragRef = useRef<Drag | null>(null);
  dragRef.current = drag;

  // Fit the whole clip into the visible width, down to the readable minimum.
  useLayoutEffect(() => {
    const node = track.current;
    if (!node || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => setWidth(node.clientWidth));
    observer.observe(node);
    setWidth(node.clientWidth);
    return () => observer.disconnect();
  }, []);
  const total = totalSeconds(spec);
  const count = spec.scenes.length;
  const room = width - (count - 1) * GAP - 56;
  const fitted = width > 0 && total > 0 ? room / total : FALLBACK_PPS;
  // A length drag keeps the scale it started with, so the edge stays under the pointer.
  const pps = drag?.kind === "length" ? drag.pps : Math.max(18, fitted);
  const boxes = layoutBlocks(
    spec.scenes.map((scene) => scene.seconds),
    pps,
  );
  const starts = sceneStarts(spec);

  // Keep the picked block in view (after a move with the keyboard, an add).
  useEffect(() => {
    blocks.current[selected]?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  }, [selected, count]);

  const focusBlock = useCallback((index: number) => {
    window.requestAnimationFrame(() => blocks.current[index]?.focus());
  }, []);

  const trackX = (clientX: number) => {
    const node = track.current;
    if (!node) return clientX;
    return clientX - node.getBoundingClientRect().left + node.scrollLeft;
  };

  const onBlockPointerDown = (event: ReactPointerEvent<HTMLDivElement>, index: number) => {
    if (event.button !== 0) return;
    onSelect(index);
    setDrag({ kind: "move", index, startX: event.clientX, pointer: event.pointerId, active: false, slot: index });
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      // A synthetic pointer (a test) cannot be captured; moves still arrive.
    }
  };

  const onHandlePointerDown = (event: ReactPointerEvent<HTMLDivElement>, index: number) => {
    if (event.button !== 0) return;
    event.stopPropagation();
    event.preventDefault();
    onSelect(index);
    setDrag({ kind: "length", index, startX: event.clientX, pointer: event.pointerId, start: spec.scenes[index].seconds, pps });
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      // As above.
    }
  };

  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const now = dragRef.current;
    if (!now || event.pointerId !== now.pointer) return;
    if (now.kind === "length") {
      const seconds = clampSeconds(now.start + (event.clientX - now.startX) / now.pps);
      if (seconds !== spec.scenes[now.index]?.seconds) onSeconds(now.index, seconds, false);
      return;
    }
    const active = now.active || Math.abs(event.clientX - now.startX) > DRAG_SLOP;
    if (!active) return;
    const slot = slotAt(boxes, trackX(event.clientX));
    if (active !== now.active || slot !== now.slot) setDrag({ ...now, active, slot });
  };

  const endDrag = (event: ReactPointerEvent<HTMLDivElement>, cancelled: boolean) => {
    const now = dragRef.current;
    if (!now || event.pointerId !== now.pointer) return;
    setDrag(null);
    if (now.kind === "length") {
      onSeconds(now.index, spec.scenes[now.index]?.seconds ?? now.start, true);
      return;
    }
    if (!now.active || cancelled) return;
    const to = dropIndex(now.index, now.slot);
    if (to !== now.index) {
      onMove(now.index, to);
      onSelect(to);
    }
  };

  const onBlockKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>, index: number) => {
    const mod = event.metaKey || event.ctrlKey;
    let next: number | null = null;
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      const step = event.key === "ArrowLeft" ? -1 : 1;
      if (event.altKey) {
        const to = Math.max(0, Math.min(count - 1, index + step));
        if (to !== index) {
          onMove(index, to);
          onSelect(to);
          focusBlock(to);
        }
        event.preventDefault();
        return;
      }
      next = Math.max(0, Math.min(count - 1, index + step));
    } else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = count - 1;
    else if ((event.key === "Delete" || event.key === "Backspace") && count > 1) {
      event.preventDefault();
      onRemove(index);
      const after = Math.min(index, count - 2);
      onSelect(after);
      focusBlock(after);
      return;
    } else if (mod && event.key.toLowerCase() === "d") {
      event.preventDefault();
      if (count < MAX_SCENES) {
        onDuplicate(index);
        onSelect(index + 1);
        focusBlock(index + 1);
      }
      return;
    }
    if (next !== null) {
      event.preventDefault();
      onSelect(next);
      focusBlock(next);
    }
  };

  const onHandleKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>, index: number) => {
    const scene = spec.scenes[index];
    const step = event.shiftKey ? 0.5 : 0.1;
    let seconds: number | null = null;
    if (event.key === "ArrowRight" || event.key === "ArrowUp") seconds = scene.seconds + step;
    else if (event.key === "ArrowLeft" || event.key === "ArrowDown") seconds = scene.seconds - step;
    else if (event.key === "Home") seconds = MIN_SECONDS;
    else if (event.key === "End") seconds = MAX_SECONDS;
    if (seconds === null) return;
    event.preventDefault();
    event.stopPropagation();
    // Key presses in a row are one undo step, as one drag is.
    onSeconds(index, clampSeconds(seconds), false);
  };

  const playX =
    playhead && boxes[playhead.scene]
      ? boxes[playhead.scene].left +
        Math.min(boxes[playhead.scene].width, Math.max(0, playhead.t - (starts[playhead.scene] ?? 0)) * pps)
      : null;
  const insertAt =
    drag?.kind === "move" && drag.active && dropIndex(drag.index, drag.slot) !== drag.index
      ? drag.slot === count
        ? boxes[count - 1].left + boxes[count - 1].width + GAP / 2
        : boxes[drag.slot].left - GAP / 2
      : null;
  const end = count > 0 ? boxes[count - 1].left + boxes[count - 1].width : 0;

  return (
    <div className="flex min-h-0 flex-col border-t border-border bg-sidebar" data-testid="motion-timeline">
      <div className="flex h-8 shrink-0 items-center gap-3 px-3 text-xs text-muted-foreground">
        <span className="font-medium text-foreground">{t("nodes.editor.motion.timeline.label")}</span>
        <span aria-live="polite" data-testid="motion-total">
          {fill(t("nodes.editor.motion.timeline.summary"), { count, clock: formatClock(total), seconds: formatSeconds(total, language) })}
        </span>
        <span className="ml-auto hidden md:inline">{t("nodes.editor.motion.timeline.keys")}</span>
      </div>
      <div
        ref={track}
        className="relative min-h-0 overflow-x-auto overflow-y-hidden px-3 pb-3"
        onPointerMove={onPointerMove}
        onPointerUp={(event) => endDrag(event, false)}
        onPointerCancel={(event) => endDrag(event, true)}
      >
        <div
          role="listbox"
          aria-label={t("nodes.editor.motion.timeline.label")}
          aria-orientation="horizontal"
          className="relative h-[92px]"
          style={{ width: end + 56 }}
        >
          {spec.scenes.map((scene, index) => {
            const Icon = SCENE_ICONS[scene.type];
            const box = boxes[index];
            const isSelected = index === selected;
            const isPlaying = playhead?.scene === index;
            const problem = sceneProblem(scene);
            const summary = sceneSummary(scene);
            const kind = t(kindKey(scene.type));
            const dragging = drag?.kind === "move" && drag.active && drag.index === index;
            return (
              <div key={index}>
                {index > 0 && (
                  <TransitionChip
                    left={box.left - GAP}
                    index={index}
                    value={scene.transition}
                    onChange={(value) => onTransition(index, value)}
                  />
                )}
                <div
                  ref={(node) => {
                    blocks.current[index] = node;
                  }}
                  role="option"
                  aria-selected={isSelected}
                  aria-label={fill(t("nodes.editor.motion.timeline.scene"), {
                    n: index + 1,
                    kind,
                    seconds: formatSeconds(scene.seconds, language),
                    text: summary,
                  })}
                  aria-invalid={problem !== null || undefined}
                  tabIndex={isSelected ? 0 : -1}
                  data-testid={`motion-scene-${index}`}
                  onPointerDown={(event) => onBlockPointerDown(event, index)}
                  onKeyDown={(event) => onBlockKeyDown(event, index)}
                  onFocus={() => {
                    if (!isSelected) onSelect(index);
                  }}
                  className={cn(
                    "group absolute top-1 flex h-[84px] cursor-grab touch-none select-none flex-col overflow-hidden rounded-lg border bg-card px-2.5 py-2 text-left outline-none transition-[border-color,box-shadow,opacity]",
                    "focus-visible:ring-2 focus-visible:ring-ring",
                    isSelected ? "border-accent shadow-[0_0_0_1px_hsl(var(--accent))]" : "border-border hover:border-border-strong",
                    isPlaying && !isSelected && "border-foreground/40",
                    dragging && "cursor-grabbing opacity-50",
                  )}
                  style={{ left: box.left, width: box.width }}
                >
                  <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    <span className="tabular-nums">{index + 1}</span>
                    <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden />
                    <span className="truncate">{kind}</span>
                    {problem !== null && <AlertCircle className="ml-auto h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />}
                  </div>
                  <div className="mt-1 line-clamp-2 min-h-0 flex-1 text-sm leading-tight text-foreground">{summary}</div>
                  <div className="text-xs tabular-nums text-muted-foreground">
                    {fill(t("nodes.editor.motion.timeline.seconds"), { seconds: formatSeconds(scene.seconds, language) })}
                  </div>
                  <div
                    role="slider"
                    tabIndex={0}
                    aria-label={fill(t("nodes.editor.motion.timeline.length"), { n: index + 1 })}
                    aria-valuemin={MIN_SECONDS}
                    aria-valuemax={MAX_SECONDS}
                    aria-valuenow={scene.seconds}
                    aria-valuetext={fill(t("nodes.editor.motion.timeline.seconds"), { seconds: formatSeconds(scene.seconds, language) })}
                    data-testid={`motion-length-${index}`}
                    onPointerDown={(event) => onHandlePointerDown(event, index)}
                    onKeyDown={(event) => onHandleKeyDown(event, index)}
                    className={cn(
                      "absolute inset-y-0 right-0 flex w-2.5 cursor-ew-resize items-center justify-center outline-none",
                      "focus-visible:bg-accent/30 hover:bg-accent/20",
                    )}
                  >
                    <span className="h-6 w-0.5 rounded-full bg-border-strong group-hover:bg-foreground/50" aria-hidden />
                  </div>
                </div>
              </div>
            );
          })}
          {insertAt !== null && (
            <div className="pointer-events-none absolute top-0 h-[92px] w-0.5 -translate-x-1/2 rounded-full bg-accent" style={{ left: insertAt }} aria-hidden />
          )}
          {playX !== null && (
            <div
              className="pointer-events-none absolute -top-1 h-[100px] w-0.5 -translate-x-1/2 bg-foreground"
              style={{ left: playX }}
              data-testid="motion-playhead"
              aria-hidden
            />
          )}
          <Popover
            label={t("nodes.editor.motion.add")}
            role="menu"
            trigger={
              <button
                type="button"
                aria-label={t("nodes.editor.motion.add")}
                disabled={count >= MAX_SCENES}
                className="absolute top-1 flex h-[84px] w-11 items-center justify-center rounded-lg border border-dashed border-border-strong text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-40"
                style={{ left: end + GAP / 2 }}
                data-testid="motion-timeline-add"
              >
                <Plus className="h-4 w-4" aria-hidden />
              </button>
            }
          >
            <AddSceneItems onAdd={onAdd} />
          </Popover>
        </div>
      </div>
    </div>
  );
}

/** The scene types as menu items: name and what it is for. */
export function AddSceneItems({ onAdd }: { onAdd: (kind: SceneKind) => void }) {
  const t = useT();
  return (
    <div className="w-64">
      {SCENE_KINDS.map((kind) => {
        const Icon = SCENE_ICONS[kind];
        return (
          <MenuItem
            key={kind}
            label={t(kindKey(kind))}
            icon={<Icon aria-hidden />}
            onClick={() => onAdd(kind)}
            data-testid={`motion-add-${kind}`}
          />
        );
      })}
    </div>
  );
}

function TransitionChip({
  left,
  index,
  value,
  onChange,
}: {
  left: number;
  index: number;
  value: Transition;
  onChange: (value: Transition) => void;
}) {
  const t = useT();
  const Icon = TRANSITION_ICONS[value];
  const name = t(transitionKey(value));
  return (
    <Popover
      label={fill(t("nodes.editor.motion.timeline.transition"), { n: index + 1, transition: name })}
      role="menu"
      trigger={
        <button
          type="button"
          aria-label={fill(t("nodes.editor.motion.timeline.transition"), { n: index + 1, transition: name })}
          title={name}
          className="absolute top-[34px] z-10 flex h-6 w-[22px] items-center justify-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          style={{ left }}
          onPointerDown={(event) => event.stopPropagation()}
          data-testid={`motion-transition-${index}`}
        >
          <Icon className="h-3.5 w-3.5" aria-hidden />
        </button>
      }
    >
      {TRANSITIONS.map((option) => {
        const OptionIcon = TRANSITION_ICONS[option];
        return (
          <MenuItem
            key={option}
            label={t(transitionKey(option))}
            icon={<OptionIcon aria-hidden />}
            // The menu closes on a plain menu item only, so the current
            // choice is marked by weight and for assistive technology.
            aria-current={option === value || undefined}
            className={option === value ? "font-semibold" : undefined}
            onClick={() => onChange(option)}
            data-testid={`motion-transition-${index}-${option}`}
          />
        );
      })}
    </Popover>
  );
}
