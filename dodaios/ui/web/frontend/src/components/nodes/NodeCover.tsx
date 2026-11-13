import { memo } from "react";

import { cn } from "@/lib/utils";

import { BuildingMini, DocumentMini, LivePage, PictureCover, canvasSize } from "./covers/live";
import {
  DataMini,
  DocsMini,
  MotionMini,
  OutputMini,
  PlaceholderMini,
  SheetsMini,
  SlidesMini,
  WhiteboardMini,
} from "./covers/typed";
import { NODE_TYPES, previewOf, type CardType, type NodeCard } from "./nodeModel";
import { NODE_FILL_CLASS, nodeHueStyle } from "./nodeTheme";

export interface NodeCoverProps {
  card: NodeCard;
  className?: string;
}

/** The hue a card wears: its type's, or the neutral one for a type unknown here. */
function hueType(type: string): CardType {
  return (NODE_TYPES as readonly string[]).includes(type) ? (type as CardType) : "output";
}

/** What changes when a card's file does: the frame of a live cover reloads on it. */
function revisionOf(card: NodeCard): string {
  return `${card.version}:${card.updated_at}:${card.size}`;
}

/** A page shown as a live miniature, when the card has a file to show. */
function livePage(card: NodeCard, canvas: { width: number; height: number } | null, background: string) {
  if (card.path === null || card.path === "") return <PlaceholderMini />;
  return (
    <LivePage
      slug={card.slug}
      path={card.path}
      title={card.title}
      revision={revisionOf(card)}
      canvas={canvas}
      background={background}
    />
  );
}

/** An adopted file has no preview: its cover is the file itself. */
function adoptedMiniature(card: NodeCard) {
  if (card.path === null || card.path === "") return <PlaceholderMini />;
  switch (card.visual_kind) {
    case "page":
      return livePage(card, null, "");
    case "image":
    case "vector":
      return <PictureCover key={card.key} slug={card.slug} path={card.path} whole={card.visual_kind === "vector"} />;
    case "document":
      return <DocumentMini />;
    default:
      return <PlaceholderMini />;
  }
}

/**
 * The miniature on a cover. Memoized on the card object: the list keeps a
 * card's identity while nothing about it changes, so a re-render of the
 * library redraws only the covers whose card did.
 */
const Miniature = memo(function Miniature({ card }: { card: NodeCard }) {
  if (card.origin === "build" || card.status === "building") return <BuildingMini />;
  if (card.preview === null || card.preview === undefined) {
    return card.type === "output" ? <OutputMini preview={null} /> : adoptedMiniature(card);
  }
  switch (card.type) {
    case "docs":
      return <DocsMini preview={previewOf(card, "docs")} />;
    case "slides":
      return <SlidesMini preview={previewOf(card, "slides")} />;
    case "sheets":
      return <SheetsMini preview={previewOf(card, "sheets")} />;
    case "data":
      return <DataMini preview={previewOf(card, "data")} />;
    case "whiteboard":
      return <WhiteboardMini preview={previewOf(card, "whiteboard")} />;
    case "motion":
      return <MotionMini preview={previewOf(card, "motion")} />;
    case "design": {
      const preview = previewOf(card, "design");
      const canvas = preview?.fit === "canvas" ? canvasSize(preview.width, preview.height) : null;
      const background = typeof preview?.background === "string" ? preview.background.trim() : "";
      return livePage(card, canvas, background);
    }
    case "output":
      return <OutputMini preview={previewOf(card, "output")} />;
    default:
      return <PlaceholderMini />;
  }
});

/**
 * The cover of a library card: the type's tint with a miniature of the node
 * on it, drawn from the card's `preview` (or from the file itself for an
 * adopted page or picture).
 *
 * The cover is a size container: the miniatures measure themselves in its
 * units, so they keep their proportions at any card width without a script.
 */
export function NodeCover({ card, className }: NodeCoverProps) {
  return (
    <div
      data-testid="node-cover"
      data-node-type={card.type}
      className={cn(
        "relative isolate aspect-[2/1.02] w-full overflow-hidden [container-type:size]",
        NODE_FILL_CLASS,
        className,
      )}
      style={nodeHueStyle(hueType(card.type))}
    >
      {/* A picture of the node, not content: the card around it carries the name. */}
      <div aria-hidden="true" className="absolute inset-0">
        <Miniature card={card} />
      </div>
    </div>
  );
}
