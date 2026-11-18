/**
 * The type chip of a node asked for from the chat ("Dodaios Slides").
 *
 * "New" in the Nodes library opens the lead conversation with this chip in
 * front of the composer; the reader writes what the node should be about
 * behind it. The message goes out with the chip as its first line,
 * `[node: slides]` (the backend turns that into the request the turn
 * receives, `dodaios/agent_chat/node_request.py`), and the sent bubble draws
 * that line as the same chip, so it stays clear which type was asked for.
 */
import { X } from "lucide-react";

import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { isNodeType, type NodeType } from "./nodeModel";
import { NODE_TYPE_LABEL_KEY, nodeHueStyle } from "./nodeTheme";
import { NodeTypeIcon } from "./NodeTypeIcon";

/** The product's name in front of the type, as on the chip of the reference ("Claude Docs"). */
const BRAND = "Dodaios";

/** The chip line: the message's first line, nothing else on it. */
const CHIP_LINE = /^\[node:\s*([a-z]+)\]\s*(?:\n|$)/;

/** The message that asks for a new node of `type`: the chip line, then the description. */
export function nodeRequestMessage(type: NodeType, text: string): string {
  return `[node: ${type}]\n${text.trim()}`;
}

/** `{ type, text }` for a message that starts with a known chip line, else null. */
export function splitNodeRequest(message: string): { type: NodeType; text: string } | null {
  const trimmed = message.trimStart();
  const match = CHIP_LINE.exec(trimmed);
  if (!match || !isNodeType(match[1])) return null;
  return { type: match[1], text: trimmed.slice(match[0].length).trim() };
}

export function NodeRequestChip({
  type,
  onRemove,
  className,
}: {
  type: NodeType;
  /** Given in the composer: the chip can be taken out again. */
  onRemove?: () => void;
  className?: string;
}) {
  const t = useT();
  const label = `${BRAND} ${t(NODE_TYPE_LABEL_KEY[type])}`;
  return (
    <span
      style={nodeHueStyle(type)}
      data-testid="node-request-chip"
      data-node-type={type}
      className={cn(
        "inline-flex h-7 max-w-full shrink-0 items-center gap-1.5 rounded-md px-2 align-middle text-sm font-medium leading-none",
        "bg-[hsl(var(--node-hue)/0.16)] text-[hsl(var(--node-hue))]",
        className,
      )}
    >
      <NodeTypeIcon type={type} className="h-4 w-4 shrink-0" />
      <span className="truncate">{label}</span>
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          aria-label={t("nodes.new.chip_remove").replace("{0}", () => label)}
          data-testid="node-request-chip-remove"
          className="-mr-1 inline-flex h-5 w-5 items-center justify-center rounded opacity-70 transition-opacity duration-fast hover:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-current"
        >
          <X className="h-3.5 w-3.5" aria-hidden />
        </button>
      )}
    </span>
  );
}
