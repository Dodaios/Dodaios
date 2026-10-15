import { useCallback, useRef, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

export interface ViewSpec {
  id: string;
  title: string;
  open: boolean;
  onToggle: () => void;
  /** Icon buttons at the header's right edge, shown while the pointer is over the view. */
  actions?: ReactNode;
  body: ReactNode;
  /** Share of the free height this view takes while open. */
  weight: number;
}

const HEADER = 22;
const MIN_BODY = 44;

/**
 * Collapsible views stacked in one column. Open views share the height by
 * weight; the sash between two open views moves the line between them.
 */
export function ScmViews({ views, onWeights }: { views: ViewSpec[]; onWeights: (weights: Record<string, number>) => void }) {
  const bodies = useRef<Record<string, HTMLDivElement | null>>({});
  const startDrag = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>, above: string, below: string) => {
      event.preventDefault();
      const open = views.filter((view) => view.open);
      const sizes: Record<string, number> = {};
      for (const view of open) sizes[view.id] = bodies.current[view.id]?.getBoundingClientRect().height ?? MIN_BODY;
      const startY = event.clientY;
      const total = sizes[above] + sizes[below];
      const handle = event.currentTarget;
      handle.setPointerCapture?.(event.pointerId);
      const move = (moveEvent: PointerEvent) => {
        const delta = moveEvent.clientY - startY;
        const top = Math.max(MIN_BODY, Math.min(total - MIN_BODY, sizes[above] + delta));
        onWeights({ ...sizes, [above]: top, [below]: total - top });
      };
      const up = () => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", up);
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
    },
    [views, onWeights],
  );

  let previousOpen = "";
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {views.map((view, index) => {
        const sashAbove = view.open && previousOpen ? previousOpen : "";
        if (view.open) previousOpen = view.id;
        return (
          <section
            key={view.id}
            data-testid={`scm-view-${view.id}`}
            data-open={view.open || undefined}
            className={cn("group/view relative flex min-h-0 flex-col", index > 0 && "border-t border-border/60")}
            style={view.open ? { flex: `${view.weight} 1 0px`, minHeight: HEADER + MIN_BODY } : { flex: "0 0 auto" }}
          >
            {sashAbove && (
              <div
                role="separator"
                aria-orientation="horizontal"
                data-testid={`scm-sash-${view.id}`}
                onPointerDown={(event) => startDrag(event, sashAbove, view.id)}
                className="absolute inset-x-0 -top-[3px] z-10 h-[6px] cursor-row-resize hover:bg-accent/40"
              />
            )}
            <div className="flex shrink-0 items-center pr-1" style={{ height: HEADER }}>
              <button
                type="button"
                data-testid={`scm-view-toggle-${view.id}`}
                aria-expanded={view.open}
                onClick={view.onToggle}
                className="flex h-full min-w-0 flex-1 items-center gap-0.5 pl-0.5 text-left focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring"
              >
                {view.open ? <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden /> : <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />}
                <span className="truncate text-[11px] font-bold uppercase tracking-wide text-foreground/80">{view.title}</span>
              </button>
              {view.open && view.actions && <span className="hidden shrink-0 items-center group-hover/view:flex group-focus-within/view:flex">{view.actions}</span>}
            </div>
            {view.open && (
              <div ref={(element) => (bodies.current[view.id] = element)} className="min-h-0 flex-1 overflow-hidden">
                {view.body}
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}
