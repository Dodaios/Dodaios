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

export interface NewNodeRowProps {
  /** The reader picked a type to make a new node of. */
  onPick: (type: NodeType) => void;
  disabled?: boolean;
}

/**
 * The "Make something new" row: one tinted tile per node type, its name
 * under it. The seven tiles share the row; on a narrow window they keep a
 * minimum width and the row scrolls sideways.
 */
export function NewNodeRow({ onPick, disabled }: NewNodeRowProps) {
  const t = useT();
  return (
    <div
      data-testid="nodes-new-row"
      // The padding gives the lift and the focus ring room inside the
      // scroller, which would otherwise clip them; the negative margin hands
      // that room back to the layout.
      className="-mx-1 -my-1.5 flex gap-3.5 overflow-x-auto px-1 py-1.5 [scrollbar-width:none]"
    >
      {NODE_TYPES.map((type) => (
        <button
          key={type}
          type="button"
          disabled={disabled}
          data-testid={`nodes-new-${type}`}
          onClick={() => onPick(type)}
          style={nodeHueStyle(type)}
          className={cn(
            "group flex min-w-[132px] max-w-[240px] flex-1 basis-0 flex-col gap-2.5 text-left outline-none",
            "disabled:cursor-default disabled:opacity-50",
          )}
        >
          <span
            className={cn(
              "relative flex aspect-[190/132] w-full items-center justify-center overflow-hidden rounded-[14px]",
              NODE_FILL_CLASS,
              "transition-[transform,background-color] duration-fast ease-out-soft",
              "group-[:enabled:hover]:-translate-y-0.5 group-[:enabled:hover]:bg-[color:var(--node-fill-hover)]",
              "group-[:enabled:active]:translate-y-0 group-[:enabled:active]:scale-[0.98]",
              "group-focus-visible:ring-2 group-focus-visible:ring-ring group-focus-visible:ring-offset-2 group-focus-visible:ring-offset-background",
            )}
          >
            <span aria-hidden className="pointer-events-none absolute inset-0" style={NODE_SHEEN_STYLE} />
            <NodeTypeIcon type={type} className={cn("relative h-[34px] w-[34px]", NODE_INK_CLASS)} />
          </span>
          <span className="truncate px-0.5 text-lg font-normal text-foreground">
            {t(NODE_TYPE_LABEL_KEY[type])}
          </span>
        </button>
      ))}
    </div>
  );
}
