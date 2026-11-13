import { useT } from "@/i18n";
import { cn } from "@/lib/utils";

import { NODE_TYPES, type NodeType } from "./nodeModel";
import {
  NODE_FILL_CLASS,
  NODE_INK_CLASS,
  NODE_SHEEN_STYLE,
  NODE_TYPE_LABEL_KEY,
  nodeHueStyle,
} from "./nodeTheme";
import { NodeTypeIcon } from "./NodeTypeIcon";

export interface NodeTypeRowProps {
  /** The type the library is narrowed to, or null for all of them. */
  selected: NodeType | null;
  /** The reader picked a tile: show that type (the selected tile again: show all). */
  onSelect: (type: NodeType | null) => void;
  /** How many nodes of each type the current tab holds; shown beside the name. */
  counts?: Partial<Record<NodeType, number>>;
}

/**
 * The shelf of node types: one tinted tile per type, its name under it. A
 * tile is a way IN, not a way to make something: it narrows the library to
 * the nodes of that type, and picking it again shows everything. The seven
 * tiles share the row; on a narrow window they keep a minimum width and the
 * row scrolls sideways.
 */
export function NodeTypeRow({ selected, onSelect, counts }: NodeTypeRowProps) {
  const t = useT();
  return (
    <div
      data-testid="nodes-type-row"
      // The padding gives the lift and the focus ring room inside the
      // scroller, which would otherwise clip them; the negative margin hands
      // that room back to the layout.
      className="-mx-1 -my-1.5 flex gap-3.5 overflow-x-auto px-1 py-1.5 [scrollbar-width:none]"
    >
      {NODE_TYPES.map((type) => {
        const chosen = selected === type;
        const count = counts?.[type] ?? 0;
        return (
          <button
            key={type}
            type="button"
            aria-pressed={chosen}
            data-testid={`nodes-type-${type}`}
            onClick={() => onSelect(chosen ? null : type)}
            style={nodeHueStyle(type)}
            className={cn(
              "group flex min-w-[132px] max-w-[240px] flex-1 basis-0 flex-col gap-2.5 text-left outline-none",
              // With one type picked, the others step back without going away.
              "transition-opacity duration-fast ease-out-soft",
              selected !== null && !chosen && "opacity-55 hover:opacity-100 focus-visible:opacity-100",
            )}
          >
            <span
              className={cn(
                "relative flex aspect-[190/132] w-full items-center justify-center overflow-hidden rounded-[14px]",
                NODE_FILL_CLASS,
                "transition-[transform,background-color,box-shadow] duration-fast ease-out-soft",
                "group-hover:-translate-y-0.5 group-hover:bg-[color:var(--node-fill-hover)]",
                "group-active:translate-y-0 group-active:scale-[0.98]",
                "group-focus-visible:ring-2 group-focus-visible:ring-ring group-focus-visible:ring-offset-2 group-focus-visible:ring-offset-background",
                // The picked type wears its own hue as a rim.
                chosen && "ring-2 ring-[hsl(var(--node-hue))] ring-offset-2 ring-offset-background",
              )}
            >
              <span aria-hidden className="pointer-events-none absolute inset-0" style={NODE_SHEEN_STYLE} />
              <NodeTypeIcon type={type} className={cn("relative h-[34px] w-[34px]", NODE_INK_CLASS)} />
            </span>
            <span className="flex items-baseline gap-2 px-0.5">
              <span
                className={cn(
                  "truncate text-lg text-foreground",
                  chosen ? "font-medium text-foreground-strong" : "font-normal",
                )}
              >
                {t(NODE_TYPE_LABEL_KEY[type])}
              </span>
              {count > 0 && (
                <span className="shrink-0 text-sm tabular-nums text-muted-foreground" data-testid={`nodes-type-count-${type}`}>
                  {count}
                </span>
              )}
            </span>
          </button>
        );
      })}
    </div>
  );
}
