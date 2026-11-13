/**
 * The covers that show a file itself instead of a drawing of it: a page as a
 * live miniature, a picture as the picture, a PDF as a sheet with its tag;
 * and the paper of a node that is still being built.
 *
 * The live miniature is the only cover that costs a frame. It mounts while
 * its card is near the viewport and goes away again when the card scrolls
 * off, so a long library costs what a screenful costs.
 */
import { memo, useEffect, useRef, useState } from "react";

import { useThemeValue } from "@/hooks/useTheme";
import { artifactPageUrl, visualUrl } from "@/hooks/useVisualArtifacts";
import { pageVirtualWidth, useBoxSize, useNearViewport } from "@/components/visualization/ArtifactCovers";
import { cn } from "@/lib/utils";

import { Artboard, Paper, TextBars } from "./kit";

/** CSS px a framed page may spend on its own vertical scrollbar. */
const SCROLLBAR_ALLOWANCE = 24;
/** The sides of an artboard a miniature will lay out, in CSS px. */
const CANVAS_MIN_SIDE = 160;
const CANVAS_MAX_SIDE = 4000;

export interface LivePageProps {
  slug: string;
  path: string;
  title: string;
  /** Changes when the page's content does, so the frame loads it again. */
  revision: string;
  /** An artboard's size when the page is one (`fit: "canvas"`); null for a page that flows. */
  canvas: { width: number; height: number } | null;
  /** The page's own ground (a CSS color), shown until the page has drawn; "" for the paper. */
  background: string;
}

/** An artboard size a miniature can lay out, or null. */
export function canvasSize(width: number, height: number): { width: number; height: number } | null {
  const fits = (side: number) => Number.isFinite(side) && side >= CANVAS_MIN_SIDE && side <= CANVAS_MAX_SIDE;
  return fits(width) && fits(height) ? { width, height } : null;
}

/**
 * The page itself, scaled onto the paper. Inert: no pointer, no focus, the
 * same sandbox as the stage (scripts, and nothing else).
 *
 * A page that flows is laid out at a reading width and shows its top; an
 * artboard is laid out at its own size and shown whole, in its proportions.
 */
export const LivePage = memo(function LivePage({ slug, path, title, revision, canvas, background }: LivePageProps) {
  const theme = useThemeValue();
  const box = useRef<HTMLDivElement>(null);
  const near = useNearViewport(box);
  const { width, height } = useBoxSize(box);
  const src = `${artifactPageUrl(slug, path)}?theme=${theme}`;
  const frameKey = `${src}#${revision}`;
  const [loaded, setLoaded] = useState(false);
  useEffect(() => setLoaded(false), [frameKey, near]);

  const virtualWidth = canvas ? canvas.width : pageVirtualWidth(width);
  const scale = width > 0 ? width / virtualWidth : 0;
  const virtualHeight = canvas ? canvas.height : scale > 0 ? height / scale : 0;
  const ground = background !== "" ? { backgroundColor: background } : undefined;

  const content = (
    <>
      {!loaded && (
        <div className="px-[10%] pt-[10%]">
          <TextBars />
        </div>
      )}
      {near && scale > 0 && (
        <iframe
          key={frameKey}
          src={src}
          title={title}
          tabIndex={-1}
          // allow-scripts WITHOUT allow-same-origin, exactly as on the stage.
          sandbox="allow-scripts"
          loading="lazy"
          onLoad={() => setLoaded(true)}
          data-testid="node-cover-frame"
          className={cn(
            "pointer-events-none absolute left-0 top-0 origin-top-left border-0 transition-opacity duration-slow",
            loaded ? "opacity-100" : "opacity-0",
          )}
          style={{
            // A flowing page is laid out a little wider than the paper shows,
            // so its own scrollbar falls outside instead of striping the edge.
            width: canvas ? virtualWidth : virtualWidth + SCROLLBAR_ALLOWANCE,
            height: virtualHeight,
            transform: `scale(${scale})`,
            ...ground,
          }}
        />
      )}
    </>
  );

  return canvas ? (
    <Artboard ratio={canvas.width / canvas.height} paperRef={box} style={ground}>
      {content}
    </Artboard>
  ) : (
    <Paper paperRef={box} style={ground}>
      {content}
    </Paper>
  );
});

/**
 * A picture as itself, edge to edge on a white ground (a drawing with a
 * transparent ground would vanish into a dark cover). A photograph fills the
 * cover; a vector is shown whole, with air, because a cropped logo is no logo.
 */
export const PictureCover = memo(function PictureCover({
  slug,
  path,
  whole,
}: {
  slug: string;
  path: string;
  whole: boolean;
}) {
  const [failed, setFailed] = useState(false);
  if (failed) {
    return (
      <Paper>
        <div className="px-[10%] pt-[10%]">
          <TextBars />
        </div>
      </Paper>
    );
  }
  return (
    <div data-node-mini="picture" className="absolute inset-0 bg-white">
      <img
        src={visualUrl(slug, path)}
        alt=""
        loading="lazy"
        decoding="async"
        draggable={false}
        onError={() => setFailed(true)}
        className={cn("absolute inset-0 h-full w-full", whole ? "object-contain p-[6%]" : "object-cover")}
      />
    </div>
  );
});

/** A PDF: a sheet of gray text with a small tag saying what it is. */
export function DocumentMini() {
  return (
    <Paper>
      <div data-node-mini="document" className="px-[10%] pt-[10%]">
        <TextBars count={6} />
      </div>
      <span className="absolute right-[7%] top-[8%] rounded-[4px] bg-[hsl(var(--node-hue)/0.14)] px-[5px] text-[10px] font-semibold leading-[16px] tracking-[0.04em] text-[hsl(var(--node-hue))]">
        PDF
      </span>
    </Paper>
  );
}

/** A node still being built: the paper, with a highlight passing over bars. */
export function BuildingMini() {
  return (
    <Paper>
      <div data-node-mini="building" className="px-[10%] pt-[10%]">
        <TextBars count={6} shimmer />
      </div>
    </Paper>
  );
}
