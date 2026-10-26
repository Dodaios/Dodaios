import { useEffect, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent, type RefObject } from "react";
import { GripVertical, Minus, X, type LucideIcon } from "lucide-react";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import type { SidePanelTabId } from "@/store/ideSidePanel";
import { zoneAt, type DropZone, type LayoutRect, type PlacedDivider, type PlacedLeaf } from "@/store/sidePanelLayout";

/** Height of the title bar each pane wears while the panel is split. */
export const PANE_HEADER_PX = 28;
/** How far a pressed tab must travel before it counts as dragged rather than clicked. */
const DRAG_SLOP_PX = 6;

/** Where a dragged tab would land if released now. */
export type DragTarget =
  | { kind: "pane"; paneId: string | null; zone: DropZone; rect: LayoutRect }
  /** Back onto the tab strip, or anywhere outside the panel: out of the split. */
  | { kind: "detach" };

const pct = (share: number) => `${(share * 100).toFixed(4)}%`;
const touchesStart = (start: number) => start > 0.0005;
const touchesEnd = (start: number, size: number) => start + size < 0.9995;

/**
 * Pane rectangle → CSS box inside the content area. Neighbouring panes keep a
 * 1px seam between them for the divider line; `header` reserves the title bar.
 */
export function paneBox(rect: LayoutRect, part: "body" | "header" | "whole"): CSSProperties {
  const left = touchesStart(rect.x) ? 1 : 0;
  const right = touchesEnd(rect.x, rect.w) ? 1 : 0;
  const top = touchesStart(rect.y) ? 1 : 0;
  const bottom = touchesEnd(rect.y, rect.h) ? 1 : 0;
  const box: CSSProperties = {
    left: `calc(${pct(rect.x)} + ${left}px)`,
    width: `calc(${pct(rect.w)} - ${left + right}px)`,
  };
  if (part === "header") return { ...box, top: `calc(${pct(rect.y)} + ${top}px)`, height: PANE_HEADER_PX };
  const headerPx = part === "body" ? PANE_HEADER_PX : 0;
  return { ...box, top: `calc(${pct(rect.y)} + ${top + headerPx}px)`, height: `calc(${pct(rect.h)} - ${top + bottom + headerPx}px)` };
}

/** The part of a pane a drop on `zone` fills, for the preview. */
function zoneRect(rect: LayoutRect, zone: DropZone): LayoutRect {
  const { x, y, w, h } = rect;
  switch (zone) {
    case "left": return { x, y, w: w / 2, h };
    case "right": return { x: x + w / 2, y, w: w / 2, h };
    case "top": return { x, y, w, h: h / 2 };
    case "bottom": return { x, y: y + h / 2, w, h: h / 2 };
    default: return rect;
  }
}

interface DragOptions {
  content: RefObject<HTMLElement | null>;
  strip: RefObject<HTMLElement | null>;
  /** Panes on screen; one pane with a null id while the panel is unsplit. */
  panes: { id: string | null; rect: LayoutRect }[];
  /** Whether a drop on an edge may add a pane for this tab. */
  canSplit: (id: SidePanelTabId) => boolean;
  /** Whether this tab sits in a pane of a split (only those can be taken out). */
  inSplit: (id: SidePanelTabId) => boolean;
  onDrop: (id: SidePanelTabId, target: DragTarget) => void;
}

/**
 * Drag a tab (from the strip or by a pane's title bar) onto a pane: an edge
 * splits it, the middle shows the tab there or swaps two panes. Dragging a
 * tab of a split back onto the strip, or out of the panel, takes it out of
 * the split. Pointer events rather than HTML drag and drop: those would arm
 * the file drop targets of the terminals, and a release outside the window
 * would never be heard.
 */
export function useTabDrag(options: DragOptions) {
  const [dragging, setDragging] = useState<SidePanelTabId | null>(null);
  const [target, setTarget] = useState<DragTarget | null>(null);
  const [pointer, setPointer] = useState<{ x: number; y: number } | null>(null);
  const swallowClick = useRef(false);
  const cleanupRef = useRef<(() => void) | null>(null);
  const optionsRef = useRef(options);
  optionsRef.current = options;

  useEffect(() => () => cleanupRef.current?.(), []);

  const targetAt = (id: SidePanelTabId, x: number, y: number): DragTarget | null => {
    const { content, strip, panes, canSplit, inSplit } = optionsRef.current;
    const stripBox = strip.current?.getBoundingClientRect();
    const inside = (box: DOMRect | undefined) => !!box && box.width > 0 && x >= box.left && x <= box.right && y >= box.top && y <= box.bottom;
    if (inside(stripBox)) return inSplit(id) ? { kind: "detach" } : null;
    const box = content.current?.getBoundingClientRect();
    if (!box || !inside(box)) return inSplit(id) ? { kind: "detach" } : null;
    const fx = (x - box.left) / box.width;
    const fy = (y - box.top) / box.height;
    const pane = panes.find(({ rect }) => fx >= rect.x && fx <= rect.x + rect.w && fy >= rect.y && fy <= rect.y + rect.h);
    if (!pane) return null;
    const zone = zoneAt((fx - pane.rect.x) / pane.rect.w, (fy - pane.rect.y) / pane.rect.h, canSplit(id));
    return { kind: "pane", paneId: pane.id, zone, rect: pane.rect };
  };

  const start = (event: ReactPointerEvent<HTMLElement>, id: SidePanelTabId) => {
    if (event.button !== 0) return;
    cleanupRef.current?.();
    const origin = { x: event.clientX, y: event.clientY };
    let active = false;
    let over: DragTarget | null = null;
    const move = (e: PointerEvent) => {
      if (!active) {
        if (Math.hypot(e.clientX - origin.x, e.clientY - origin.y) < DRAG_SLOP_PX) return;
        active = true;
        setDragging(id);
      }
      over = targetAt(id, e.clientX, e.clientY);
      setTarget(over);
      setPointer({ x: e.clientX, y: e.clientY });
    };
    const finish = (drop: boolean) => {
      cleanupRef.current?.();
      if (!active) return;
      swallowClick.current = true;
      // The click that follows a drag must not also select the tab.
      window.setTimeout(() => { swallowClick.current = false; }, 0);
      setDragging(null);
      setTarget(null);
      setPointer(null);
      if (drop && over) optionsRef.current.onDrop(id, over);
    };
    const up = () => finish(true);
    const cancel = () => finish(false);
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") finish(false); };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", cancel);
    window.addEventListener("keydown", key);
    cleanupRef.current = () => {
      cleanupRef.current = null;
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", cancel);
      window.removeEventListener("keydown", key);
    };
  };

  return {
    dragging,
    target,
    pointer,
    start,
    /** True once for the click a finished drag leaves behind. */
    consumeClick: () => {
      const swallow = swallowClick.current;
      swallowClick.current = false;
      return swallow;
    },
  };
}

const ZONE_LABEL: Record<Exclude<DropZone, "center">, string> = {
  left: "ide_side_panel.drop_left",
  right: "ide_side_panel.drop_right",
  top: "ide_side_panel.drop_top",
  bottom: "ide_side_panel.drop_bottom",
};

/** What releasing the drag would do, in words. */
export function useDropLabel(target: DragTarget | null, swaps: boolean): string | null {
  const t = useT();
  if (!target) return null;
  if (target.kind === "detach") return t("ide_side_panel.drop_detach");
  if (target.zone === "center") return t(swaps ? "ide_side_panel.drop_swap" : "ide_side_panel.drop_here");
  return t(ZONE_LABEL[target.zone]);
}

/**
 * The area a drop would fill, drawn over the panes while a tab is dragged.
 * Marked so the native browser window steps aside: it is drawn above the page
 * and would hide the preview.
 */
export function DropPreview({ target, label }: { target: DragTarget | null; label: string | null }) {
  const area = target?.kind === "pane" ? zoneRect(target.rect, target.zone) : null;
  return (
    <div data-hides-native-browser="" data-testid="ide-side-panel-drop-zones" className="pointer-events-none absolute inset-0 z-30 bg-background/30">
      {area && target?.kind === "pane" && (
        <div
          data-testid={`ide-side-panel-drop-${target.zone}`}
          className="absolute p-1.5 transition-all duration-100"
          style={{ left: pct(area.x), top: pct(area.y), width: pct(area.w), height: pct(area.h) }}
        >
          <div className="flex h-full w-full items-center justify-center rounded-lg border-2 border-dashed border-accent bg-accent/15 text-sm font-medium text-foreground">
            {label}
          </div>
        </div>
      )}
    </div>
  );
}

/** The grips between panes; dragging one moves only the two panes it divides. */
export function SplitDividers({ dividers, content, onResize, onEvenOut, label }: {
  dividers: PlacedDivider[];
  content: RefObject<HTMLElement | null>;
  onResize: (splitId: string, index: number, share: number) => void;
  onEvenOut: (splitId: string) => void;
  label: string;
}) {
  const [resizing, setResizing] = useState<string | null>(null);
  const start = (event: ReactPointerEvent<HTMLDivElement>, divider: PlacedDivider) => {
    const box = content.current?.getBoundingClientRect();
    if (!box || event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    const key = `${divider.splitId}:${divider.index}`;
    setResizing(key);
    const { splitRect, direction } = divider;
    const move = (e: PointerEvent) => {
      const share = direction === "row"
        ? ((e.clientX - box.left) / box.width - splitRect.x) / splitRect.w
        : ((e.clientY - box.top) / box.height - splitRect.y) / splitRect.h;
      if (Number.isFinite(share)) onResize(divider.splitId, divider.index, share);
    };
    const end = () => {
      setResizing(null);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", end);
      window.removeEventListener("pointercancel", end);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", end);
    window.addEventListener("pointercancel", end);
  };
  return (
    <>
      {dividers.map((divider) => {
        const key = `${divider.splitId}:${divider.index}`;
        const row = divider.direction === "row";
        const { rect } = divider;
        return (
          <div
            key={key}
            role="separator"
            aria-orientation={row ? "vertical" : "horizontal"}
            aria-label={label}
            title={label}
            tabIndex={0}
            data-testid={`ide-side-panel-divider-${divider.index}-${divider.direction}`}
            onPointerDown={(event) => start(event, divider)}
            onDoubleClick={() => onEvenOut(divider.splitId)}
            onKeyDown={(event) => {
              const step = (row ? ["ArrowLeft", "ArrowRight"] : ["ArrowUp", "ArrowDown"]).indexOf(event.key);
              if (step < 0) return;
              event.preventDefault();
              const span = row ? divider.splitRect.w : divider.splitRect.h;
              const origin = row ? divider.splitRect.x : divider.splitRect.y;
              onResize(divider.splitId, divider.index, (divider.at - origin) / span + (step ? 0.05 : -0.05));
            }}
            className={cn(
              "group absolute z-20 flex justify-center focus-visible:outline-none",
              row ? "w-3 -translate-x-1/2 cursor-col-resize" : "h-3 -translate-y-1/2 cursor-row-resize flex-col",
            )}
            style={row
              ? { left: pct(rect.x), top: pct(rect.y), height: pct(rect.h) }
              : { top: pct(rect.y), left: pct(rect.x), width: pct(rect.w) }}
          >
            <div className={cn(
              "bg-border transition-colors group-hover:bg-accent group-focus-visible:bg-accent",
              row ? "h-full w-px" : "h-px w-full",
              resizing === key && "bg-accent",
            )} />
          </div>
        );
      })}
      {/* While a divider moves, nothing under the pointer (a terminal, the browser) may take it. */}
      {resizing && <div data-hides-native-browser="" className={cn("absolute inset-0 z-10", resizing && "cursor-grabbing")} />}
    </>
  );
}

/** The title bar of one pane in a split: drag it to move the pane, or take it out. */
export function PaneHeader({ placed, label, icon: Icon, focused, onDragStart, onClick, onDetach, onClose }: {
  placed: PlacedLeaf<SidePanelTabId>;
  label: string;
  icon: LucideIcon;
  focused: boolean;
  onDragStart: (event: ReactPointerEvent<HTMLElement>) => void;
  onClick: () => void;
  onDetach: () => void;
  onClose: () => void;
}) {
  const t = useT();
  return (
    <div
      data-testid={`ide-side-panel-pane-header-${placed.leaf.tab}`}
      data-focused={focused ? "true" : undefined}
      className={cn(
        "absolute z-10 flex touch-none select-none items-center gap-1.5 border-b px-1.5 text-xs",
        focused ? "border-accent/70 text-foreground" : "border-border/60 text-muted-foreground",
      )}
      style={paneBox(placed.rect, "header")}
    >
      <div
        role="button"
        tabIndex={-1}
        title={t("ide_side_panel.pane_drag")}
        onPointerDown={onDragStart}
        onClick={onClick}
        className="flex min-w-0 flex-1 cursor-grab items-center gap-1.5 active:cursor-grabbing"
      >
        <GripVertical className="h-3.5 w-3.5 shrink-0 opacity-60" aria-hidden />
        <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden />
        <span className="truncate font-medium">{label}</span>
      </div>
      <button
        type="button"
        data-testid={`ide-side-panel-pane-detach-${placed.leaf.tab}`}
        aria-label={`${t("ide_side_panel.pane_detach")}: ${label}`}
        title={t("ide_side_panel.pane_detach")}
        onClick={onDetach}
        className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded hover:bg-secondary hover:text-foreground"
      >
        <Minus className="h-3.5 w-3.5" aria-hidden />
      </button>
      <button
        type="button"
        aria-label={`${t("ide_side_panel.close_tab")}: ${label}`}
        title={t("ide_side_panel.close_tab")}
        onClick={onClose}
        className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded hover:bg-secondary hover:text-foreground"
      >
        <X className="h-3.5 w-3.5" aria-hidden />
      </button>
    </div>
  );
}
