/**
 * The one bar a node is shaped with.
 *
 * The maintainer's request (2026-11-18), after the artifact bar of a desktop
 * chat app: an open node shows the whole node, and one small bar floats at
 * the bottom in the middle. It holds the type's own tools (the few used
 * most, as icons), "⋯" for the rest, a comment button and "Chat". Nothing
 * else on the node asks to be pressed: no Edit and Done, no second toolbar
 * row, no panels open by themselves.
 *
 * Every node type draws its tools into this same bar: the native editors
 * through `EditorShell`, the stage itself for a page (comments, an adopted
 * page, a picture), the whiteboard into its own dock. The comment button and
 * "Chat" are the stage's (`NodeBarCommonContext`), so each bar ends the same.
 */
import { createContext, useContext, type ReactNode } from "react";
import { MessageCircle, MoreHorizontal } from "lucide-react";

import { QuickTooltip } from "@/components/ui/tooltip";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { Popover, ToolbarButton, ToolbarSeparator, ToolbarTipSide } from "../editors/controls";

/** Room the bar takes at the bottom of an open node, for content to keep clear of. */
export const NODE_BAR_ROOM = 72;

/** What ends every node bar, handed down by the stage. */
export interface NodeBarCommon {
  /** The node's comment mode; absent where nobody can work comments in. */
  comment?: { on: boolean; onToggle: () => void };
  /** "Chat": ask the assistant for a change; absent where it cannot make one. */
  onChat?: () => void;
}

export const NodeBarCommonContext = createContext<NodeBarCommon>({});

export function useNodeBarCommon(): NodeBarCommon {
  return useContext(NodeBarCommonContext);
}

/**
 * The floating pill. It stands over the bottom of its positioned parent, in
 * the middle; `inset` lifts it over something that has to stay visible under
 * it (a sheet's tabs). Too narrow a node scrolls the bar sideways instead of
 * folding it into two rows.
 */
export function NodeBar({
  label,
  inset = 0,
  docked = false,
  className,
  testId = "node-bar",
  children,
}: {
  /** The bar's accessible name ("Document tools"). */
  label: string;
  inset?: number;
  /**
   * In a slim band of its own under the content instead of over it: for a
   * page the app cannot pad, whose own controls sit at its bottom edge.
   */
  docked?: boolean;
  className?: string;
  testId?: string;
  children: ReactNode;
}) {
  return (
    <ToolbarTipSide.Provider value="top">
      <div
        className={
          docked
            ? "flex shrink-0 justify-center px-3 py-2"
            : "pointer-events-none absolute inset-x-0 z-30 flex justify-center px-3"
        }
        style={docked ? undefined : { bottom: 12 + inset }}
      >
        <div
          role="toolbar"
          aria-label={label}
          data-testid={testId}
          className={cn(
            "pointer-events-auto flex max-w-full items-center gap-0.5 overflow-x-auto rounded-xl border border-border",
            "bg-popover/95 p-1 text-popover-foreground shadow-float backdrop-blur-md [scrollbar-width:none]",
            "animate-in fade-in-0 slide-in-from-bottom-1 duration-150 motion-reduce:animate-none",
            className,
          )}
        >
          {children}
        </div>
      </div>
    </ToolbarTipSide.Provider>
  );
}

/** A thin upright line between two runs of the bar's tools. */
export const NodeBarDivider = ToolbarSeparator;

/** "⋯": the type's tools used now and then, in a menu that opens over the bar. */
export function NodeBarMore({ children, testId = "node-bar-more" }: { children: ReactNode | ((close: () => void) => ReactNode); testId?: string }) {
  const t = useT();
  return (
    <Popover
      label={t("nodes.bar.more")}
      role="menu"
      align="end"
      className="w-64"
      trigger={<ToolbarButton label={t("nodes.bar.more")} icon={<MoreHorizontal aria-hidden />} data-testid={testId} />}
    >
      {children}
    </Popover>
  );
}

/**
 * The end of every bar: the comment button and "Chat", where the stage
 * offers them. Draws nothing where it offers neither.
 */
export function NodeBarEnd({ divider = true }: { divider?: boolean }) {
  const t = useT();
  const { comment, onChat } = useNodeBarCommon();
  if (!comment && !onChat) return null;
  return (
    <>
      {divider && <NodeBarDivider />}
      {comment && (
        <ToolbarButton
          label={t("nodes.comment.toggle")}
          icon={<MessageCircle aria-hidden />}
          active={comment.on}
          onClick={comment.onToggle}
          data-testid="visualization-comment"
        />
      )}
      {onChat && <NodeBarChat onChat={onChat} />}
    </>
  );
}

/** "Chat": the start of a request to the assistant, about this node. */
export function NodeBarChat({ onChat }: { onChat: () => void }) {
  const t = useT();
  return (
    <QuickTooltip content={t("nodes.menu.ask")} side="top" className="inline-flex">
      <button
        type="button"
        onClick={onChat}
        data-testid="visualization-ask-change"
        className={cn(
          "inline-flex h-8 shrink-0 items-center justify-center rounded-md px-3 text-sm font-medium text-foreground",
          "transition-colors hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        )}
      >
        {t("nodes.bar.chat")}
      </button>
    </QuickTooltip>
  );
}
