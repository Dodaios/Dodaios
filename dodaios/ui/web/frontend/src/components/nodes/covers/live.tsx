/**
 * The covers that show a file itself instead of a drawing of it: a page as a
 * live miniature, a picture as the picture, a PDF as a sheet with its tag;
 * and the paper of a node that is still being built.
 *
 * The live miniature is the only cover that costs a frame. It mounts while
 * its card is near the viewport and goes away again when the card scrolls
 * off, so a long library costs what a screenful costs.
 *
 * Rest the pointer on a card and its page scrolls itself, slowly, so the
 * reader sees what is further down without opening it (`peek`).
 */
import { memo, useCallback, useEffect, useRef, useState } from "react";

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
/** How far a resting pointer scrolls a page, in paper heights, and how fast (screen px/s). */
const PEEK_TRAVEL = 3;
const PEEK_SPEED = 40;
/** How long the page takes to glide back to its top when the pointer leaves. */
export const PEEK_RETURN_MS = 520;

/** True while the reader asks for less motion: then nothing scrolls by itself. */
function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(
    () =>
      typeof window !== "undefined" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const onChange = () => setReduced(query.matches);
    query.addEventListener?.("change", onChange);
    return () => query.removeEventListener?.("change", onChange);
  }, []);
  return reduced;
}

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
  /** The pointer rests on the card: a page that flows scrolls itself. */
  peek?: boolean;
  /** Called when the page has drawn (a cover that waits for it to show). */
  onShown?: () => void;
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
 *
 * While `peek` holds, a page that flows grows downwards and glides up, so it
 * scrolls past at a slow reading pace. It is only made taller for that
 * moment: a page that sizes its opening to the window keeps its real
 * proportions on the resting card. An artboard is already shown whole.
 */
export const LivePage = memo(function LivePage({
  slug,
  path,
  title,
  revision,
  canvas,
  background,
  peek = false,
  onShown,
}: LivePageProps) {
  const theme = useThemeValue();
  const box = useRef<HTMLDivElement>(null);
  const near = useNearViewport(box);
  const { width, height } = useBoxSize(box);
  const reduced = usePrefersReducedMotion();
  const src = `${artifactPageUrl(slug, path)}?theme=${theme}`;
  const frameKey = `${src}#${revision}`;
  const [loaded, setLoaded] = useState(false);
  useEffect(() => setLoaded(false), [frameKey, near]);
  const onLoad = useCallback(() => {
    setLoaded(true);
    onShown?.();
  }, [onShown]);

  const virtualWidth = canvas ? canvas.width : pageVirtualWidth(width);
  const scale = width > 0 ? width / virtualWidth : 0;
  const visible = scale > 0 ? height / scale : 0;
  const virtualHeight = canvas ? canvas.height : visible;
  const ground = background !== "" ? { backgroundColor: background } : undefined;

  const scrolling = peek && loaded && !reduced && canvas === null;
  // Taller while scrolling and until the page has glided back to its top.
  const [grown, setGrown] = useState(false);
  useEffect(() => {
    if (scrolling) {
      setGrown(true);
      return;
    }
    const timer = window.setTimeout(() => setGrown(false), PEEK_RETURN_MS + 80);
    return () => window.clearTimeout(timer);
  }, [scrolling]);
  const travel = visible * PEEK_TRAVEL;
  const glide = scrolling
    ? `transform ${Math.round(((travel * scale) / PEEK_SPEED) * 1000)}ms linear`
    : `transform ${PEEK_RETURN_MS}ms cubic-bezier(0.22, 1, 0.36, 1)`;

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
          onLoad={onLoad}
          data-testid="node-cover-frame"
          data-scrolling={scrolling || undefined}
          className={cn(
            "pointer-events-none absolute left-0 top-0 origin-top-left border-0",
            loaded ? "opacity-100" : "opacity-0",
          )}
          style={{
            // A flowing page is laid out a little wider than the paper shows,
            // so its own scrollbar falls outside instead of striping the edge.
            width: canvas ? virtualWidth : virtualWidth + SCROLLBAR_ALLOWANCE,
            height: grown ? visible + travel : virtualHeight,
            transform: `scale(${scale}) translateY(${scrolling ? -travel : 0}px)`,
            transition: `${glide}, opacity 300ms`,
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
