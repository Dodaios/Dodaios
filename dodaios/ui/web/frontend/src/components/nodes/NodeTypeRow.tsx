import type { CSSProperties } from "react";

import { useT } from "@/i18n";
import { cn } from "@/lib/utils";

import { NODE_TYPES, type NodeType } from "./nodeModel";
import { NODE_INK_CLASS, NODE_TYPE_LABEL_KEY, nodeHueStyle } from "./nodeTheme";
import { NodeTypeIcon } from "./NodeTypeIcon";
import { NodeTypeScene } from "./NodeTypeScene";

export interface NodeTypeRowProps {
  /** The type the library is narrowed to, or null for all of them. */
  selected: NodeType | null;
  /** The reader picked a card: show that type (the selected card again: show all). */
  onSelect: (type: NodeType | null) => void;
  /** How many nodes of each type the current tab holds; shown on the card. */
  counts?: Partial<Record<NodeType, number>>;
}

/**
 * The card's ground: the neutral card colour, with the type's hue glowing up
 * from the bottom edge where the scene stands. `--node-glow` sets how strong
 * the glow is, so hover and the picked state only change one number.
 */
const CARD_GROUND: CSSProperties = {
  backgroundImage:
    "radial-gradient(130% 95% at 50% 115%, hsl(var(--node-hue) / var(--node-glow)) 0%, transparent 72%)",
};

/**
 * The shelf of node types: one card per type. A card names its type and
 * says how many nodes of it the tab holds, and a small scene shows what such
 * a node looks like inside. A card is a way IN, not a way to make something:
 * it narrows the library to the nodes of that type, and picking it again
 * shows everything. The seven cards share the row; on a narrow window they
 * keep a minimum width and the row scrolls sideways.
 */
export function NodeTypeRow({ selected, onSelect, counts }: NodeTypeRowProps) {
  const t = useT();
  return (
    <div
      data-testid="nodes-type-row"
      // The padding gives the lift and the focus ring room inside the
      // scroller, which would otherwise clip them; the negative margin hands
      // that room back to the layout.
      className="-mx-1 -my-1.5 flex gap-3 overflow-x-auto px-1 py-1.5 [scrollbar-width:none]"
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
            style={{ ...nodeHueStyle(type), ...CARD_GROUND }}
            className={cn(
              "group relative flex h-[136px] min-w-[148px] max-w-[260px] flex-1 basis-0 flex-col overflow-hidden",
              "rounded-2xl border bg-card text-left outline-none",
              "[--node-glow:0.16] dark:[--node-glow:0.2]",
              "transition-[opacity,transform,border-color,box-shadow] duration-fast ease-out-soft",
              "hover:[--node-glow:0.26] dark:hover:[--node-glow:0.3]",
              "motion-safe:hover:-translate-y-0.5 motion-safe:active:translate-y-0 motion-safe:active:scale-[0.985]",
              "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
              chosen
                ? "border-[hsl(var(--node-hue)/0.75)] shadow-[0_0_0_1px_hsl(var(--node-hue)/0.75),0_8px_24px_-12px_hsl(var(--node-hue)/0.6)] [--node-glow:0.32] dark:[--node-glow:0.36]"
                : "border-[hsl(var(--node-hue)/0.16)] hover:border-[hsl(var(--node-hue)/0.4)]",
              // With one type picked, the others step back without going away.
              selected !== null && !chosen && "opacity-55 hover:opacity-100 focus-visible:opacity-100",
            )}
          >
            <span className="relative z-10 flex items-center gap-1.5 px-3.5 pt-3">
              <NodeTypeIcon type={type} className={cn("h-4 w-4 shrink-0", NODE_INK_CLASS)} />
              <span
                className={cn(
                  "min-w-0 truncate text-[15px] leading-5",
                  chosen ? "font-semibold text-foreground-strong" : "font-medium text-foreground",
                )}
              >
                {t(NODE_TYPE_LABEL_KEY[type])}
              </span>
              {count > 0 && (
                <span
                  className={cn(
                    "ml-auto inline-flex h-5 min-w-5 shrink-0 items-center justify-center rounded-full px-1.5",
                    "text-xs font-medium tabular-nums",
                    chosen
                      ? "bg-[hsl(var(--node-hue))] text-background"
                      : "bg-[hsl(var(--node-hue)/0.14)] text-[hsl(var(--node-hue))]",
                  )}
                  data-testid={`nodes-type-count-${type}`}
                >
                  {count}
                </span>
              )}
            </span>
            {/* The scene stands on the bottom edge like a sheet pulled half
                out of a pocket; under the pointer it rises a little. */}
            <span
              aria-hidden
              className={cn(
                "absolute inset-x-3.5 bottom-0 top-[46px] overflow-hidden rounded-t-[10px] border border-b-0",
                "border-[hsl(var(--node-hue)/0.22)] bg-[hsl(var(--node-hue)/0.07)]",
                "translate-y-2 transition-transform duration-base ease-out-soft",
                "motion-safe:group-hover:translate-y-0.5",
                chosen && "translate-y-0.5 border-[hsl(var(--node-hue)/0.4)]",
              )}
            >
              <NodeTypeScene type={type} className={cn("mx-auto mt-2.5 block w-[86%] max-w-[180px]", NODE_INK_CLASS)} />
            </span>
          </button>
        );
      })}
    </div>
  );
}
