import { memo, useCallback, useEffect, useState } from "react";

import { cn } from "@/lib/utils";

import { BuildingMini, DocumentMini, LivePage, PEEK_RETURN_MS, PictureCover, canvasSize } from "./covers/live";
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
  /**
   * The pointer rests on the card: the node's page scrolls itself, slowly, so
   * the reader sees further down without opening it.
   */
  peek?: boolean;
}

/**
 * The typed kinds whose page reads from top to bottom. Their cover is a
 * drawing; under a resting pointer the real page takes its place and
 * scrolls. A deck, a board and a film fill their window and have no "down".
 */
const PEEKS_AS_PAGE: ReadonlySet<CardType> = new Set<CardType>(["docs", "data", "sheets"]);

/** The hue a card wears: its type's, or the neutral one for a type unknown here. */
function hueType(type: string): CardType {
  return (NODE_TYPES as readonly string[]).includes(type) ? (type as CardType) : "output";
}

/** What changes when a card's file does: the frame of a live cover reloads on it. */
function revisionOf(card: NodeCard): string {
  return `${card.version}:${card.updated_at}:${card.size}`;
}

/** A page shown as a live miniature, when the card has a file to show. */
function livePage(
  card: NodeCard,
  canvas: { width: number; height: number } | null,
  background: string,
  peek: boolean,
) {
  if (card.path === null || card.path === "") return <PlaceholderMini />;
  return (
    <LivePage
      slug={card.slug}
      path={card.path}
      title={card.title}
      revision={revisionOf(card)}
      canvas={canvas}
      background={background}
      peek={peek}
    />
  );
}

/**
 * The real page over a drawn cover, for as long as the pointer rests on the
 * card. It costs a frame, so it exists only then: it mounts when the peek
 * starts, shows once the page has drawn, and leaves after it has glided back.
 */
function PeekPage({ card, peek }: { card: NodeCard; peek: boolean }) {
  const [mounted, setMounted] = useState(false);
  const [drawn, setDrawn] = useState(false);
  useEffect(() => {
    if (peek) {
      setMounted(true);
      return;
    }
    const timer = window.setTimeout(() => {
      setMounted(false);
      setDrawn(false);
    }, PEEK_RETURN_MS + 120);
    return () => window.clearTimeout(timer);
  }, [peek]);
  const onShown = useCallback(() => setDrawn(true), []);
  if (!mounted || card.path === null || card.path === "") return null;
  return (
    <div
      data-node-peek=""
      className={cn(
        "absolute inset-0 transition-opacity duration-base ease-out-soft",
        peek && drawn ? "opacity-100" : "opacity-0",
      )}
    >
      <LivePage
        slug={card.slug}
        path={card.path}
        title={card.title}
        revision={revisionOf(card)}
        canvas={null}
        background=""
        peek={peek && drawn}
        onShown={onShown}
      />
    </div>
  );
}

/** An adopted file has no preview: its cover is the file itself. */
function adoptedMiniature(card: NodeCard, peek: boolean) {
  if (card.path === null || card.path === "") return <PlaceholderMini />;
  switch (card.visual_kind) {
    case "page":
      return livePage(card, null, "", peek);
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
const Miniature = memo(function Miniature({ card, peek }: { card: NodeCard; peek: boolean }) {
  if (card.origin === "build" || card.status === "building") return <BuildingMini />;
  if (card.preview === null || card.preview === undefined) {
    return card.type === "output" ? <OutputMini preview={null} /> : adoptedMiniature(card, peek);
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
      return livePage(card, canvas, background, peek);
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
export function NodeCover({ card, className, peek = false }: NodeCoverProps) {
  const drawn = card.preview !== null && card.preview !== undefined;
  const working = card.origin === "build" || card.status === "building";
  // A drawn cover of a kind that reads downwards: the real page peeks in.
  const peeksAsPage = drawn && !working && PEEKS_AS_PAGE.has(card.type);
  return (
    <div
      data-testid="node-cover"
      data-node-type={card.type}
      data-peek={peek || undefined}
      className={cn(
        "relative isolate aspect-[2/1.02] w-full overflow-hidden [container-type:size]",
        NODE_FILL_CLASS,
        className,
      )}
      style={nodeHueStyle(hueType(card.type))}
    >
      {/* A picture of the node, not content: the card around it carries the name. */}
      <div aria-hidden="true" className="absolute inset-0">
        <Miniature card={card} peek={peek && !peeksAsPage} />
        {peeksAsPage && <PeekPage card={card} peek={peek} />}
      </div>
    </div>
  );
}
