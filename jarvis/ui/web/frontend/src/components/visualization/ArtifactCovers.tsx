import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type RefObject,
} from "react";
import { Ban, CircleAlert, FileImage, FileText, Files, Globe, Loader2, PenTool, StickyNote } from "lucide-react";

import { useT, useUiLanguage } from "@/i18n";
import { useThemeValue } from "@/hooks/useTheme";
import { cn } from "@/lib/utils";
import type { OutputStatus } from "@/hooks/useOutputs";
import { artifactPageUrl, type VisualArtifact, type VisualKind } from "@/hooks/useVisualArtifacts";
import {
  relativeWhen,
  rowTitle,
  rowWhen,
  type RailRow,
} from "@/components/visualization/galleryModel";

/**
 * What a tile on the Artifacts wall shows — the artifact itself, edge to edge.
 *
 * A page is the live page: laid out narrow enough that its headline is still
 * readable at tile size, scripts running, network shut (the same sandbox as
 * the stage). Rest the pointer on it and it scrolls itself, so the reader sees
 * what is further down without opening it. A picture fills its tile, a vector
 * sits on a white mat, a PDF shows its first sheet, and a run that drew
 * nothing is a note: its title, a mark for how it ended, and when.
 *
 * Live covers mount only while their tile is near the viewport, so a library
 * of a hundred dashboards costs what a screenful costs — and a WebGL map
 * scrolled out of view gives its context back (AP-32).
 */

export const KIND_ICON: Record<VisualKind, typeof Globe> = {
  page: Globe,
  image: FileImage,
  vector: PenTool,
  document: FileText,
};

/** The share of a tile's width one CSS pixel of a framed page is drawn at. */
const PAGE_TARGET_SCALE = 0.36;
/** A page is never laid out narrower or wider than this, whatever the tile. */
const PAGE_MIN_WIDTH = 680;
const PAGE_MAX_WIDTH = 1200;
/** Layout widths move in steps, so dragging the window does not re-flow every page per pixel. */
const PAGE_WIDTH_STEP = 40;
const DOCUMENT_VIRTUAL_WIDTH = 820;
/** CSS px a framed page may spend on its own vertical scrollbar. */
const SCROLLBAR_ALLOWANCE = 24;
/** How far a resting pointer scrolls a page, in tile heights, and how fast (screen px/s). */
const PEEK_TRAVEL = 1.6;
const PEEK_SPEED = 64;
const PEEK_RETURN_MS = 520;

/** The width a page is laid out at for a tile this wide. */
export function pageVirtualWidth(tileWidth: number): number {
  const wanted = tileWidth / PAGE_TARGET_SCALE;
  const stepped = Math.round(wanted / PAGE_WIDTH_STEP) * PAGE_WIDTH_STEP;
  return Math.min(PAGE_MAX_WIDTH, Math.max(PAGE_MIN_WIDTH, stepped));
}

/* ------------------------------------------------------------------------- */

/**
 * True while the element is on, or about to scroll onto, the screen. Without
 * an IntersectionObserver (a test DOM) nothing is ever mounted — a cover then
 * stays its quiet placeholder, never a dozen live frames.
 */
export function useNearViewport(ref: RefObject<HTMLElement | null>): boolean {
  const [near, setNear] = useState(false);
  useEffect(() => {
    const node = ref.current;
    if (!node || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => setNear(entries.some((entry) => entry.isIntersecting)),
      { rootMargin: "400px 0px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [ref]);
  return near;
}

/** The element's size, known before the first paint and kept current. */
export function useBoxSize(ref: RefObject<HTMLElement | null>): { width: number; height: number } {
  const [size, setSize] = useState({ width: 0, height: 0 });
  useLayoutEffect(() => {
    const node = ref.current;
    if (!node) return;
    const update = (width: number, height: number) =>
      setSize((prev) => (prev.width === width && prev.height === height ? prev : { width, height }));
    update(node.clientWidth, node.clientHeight);
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      update(entry.contentRect.width, entry.contentRect.height);
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [ref]);
  return size;
}

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  return reduced;
}

/* ------------------------------------------------------------------------- */

/*
 * The proportions of the pictures seen so far. A picture's tile takes its
 * shape from them, so the wall has to hear when one becomes known — and keeps
 * them for the session, so a second visit lays out right at once.
 */
const ratios = new Map<string, number>();
const ratioListeners = new Set<() => void>();
let ratioVersion = 0;

function reportRatio(key: string, ratio: number): void {
  if (!Number.isFinite(ratio) || ratio <= 0) return;
  const known = ratios.get(key);
  if (known !== undefined && Math.abs(known - ratio) < 0.01) return;
  ratios.set(key, ratio);
  ratioVersion += 1;
  for (const listener of ratioListeners) listener();
}

function subscribeRatios(listener: () => void): () => void {
  ratioListeners.add(listener);
  return () => ratioListeners.delete(listener);
}

/** Width / height of every picture measured so far, by card key. */
export function useImageRatios(): ReadonlyMap<string, number> {
  useSyncExternalStore(
    subscribeRatios,
    () => ratioVersion,
    () => 0,
  );
  return ratios;
}

/* ------------------------------------------------------------------------- */

/** What fills a tile: the artifact itself, or a composed note. */
export function TileCover({ row, peek }: { row: RailRow; peek: boolean }) {
  const theme = useThemeValue();
  if (row.kind === "build") return <BuildingCover title={rowTitle(row)} />;
  if (row.kind === "run") {
    return (
      <NoteCover
        title={rowTitle(row)}
        status={row.run.status ?? "unknown"}
        when={rowWhen(row)}
        files={row.run.artifact_count ?? 0}
      />
    );
  }
  const { visual } = row;
  if (visual.kind === "image" || visual.kind === "vector") {
    return <ImageCover visual={visual} cardKey={row.key} />;
  }
  if (visual.kind === "page") {
    return (
      <PageCover
        src={`${artifactPageUrl(visual.slug, visual.path)}?theme=${theme}`}
        title={visual.title}
        peek={peek}
      />
    );
  }
  return <DocumentCover src={`${visual.url}#toolbar=0&navpanes=0&scrollbar=0&view=FitH`} title={visual.title} />;
}

/**
 * The live page, scaled onto its tile. Inert: no pointer, no focus, hidden
 * from assistive tech (the tile's button carries the name).
 *
 * While `peek` holds, the frame grows downwards and glides up, so the page
 * scrolls past at reading-glance speed; it is only made taller for that
 * moment — a page that sizes its hero to the viewport keeps its real
 * proportions on the resting tile.
 */
function PageCover({ src, title, peek }: { src: string; title: string; peek: boolean }) {
  const box = useRef<HTMLDivElement>(null);
  const near = useNearViewport(box);
  const { width, height } = useBoxSize(box);
  const reduced = usePrefersReducedMotion();
  const [loaded, setLoaded] = useState(false);
  useEffect(() => setLoaded(false), [src]);

  const scrolling = peek && loaded && !reduced;
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

  const virtualWidth = pageVirtualWidth(width);
  const scale = width > 0 ? width / virtualWidth : 0;
  const visible = scale > 0 ? height / scale : 0;
  const travel = visible * PEEK_TRAVEL;

  return (
    <div ref={box} className="absolute inset-0 bg-background" aria-hidden>
      {!loaded && <div className="absolute inset-0 animate-pulse bg-foreground/5" />}
      {near && scale > 0 && (
        <iframe
          key={src}
          src={src}
          title={title}
          tabIndex={-1}
          // allow-scripts WITHOUT allow-same-origin, exactly as on the stage.
          sandbox="allow-scripts"
          loading="lazy"
          onLoad={() => setLoaded(true)}
          data-testid="artifact-card-frame"
          className={cn(
            "pointer-events-none absolute left-0 top-0 origin-top-left border-0 bg-background",
            loaded ? "opacity-100" : "opacity-0",
          )}
          style={{
            // A little wider than the box shows: the page's own scrollbar
            // falls outside the tile instead of striping its edge.
            width: virtualWidth + SCROLLBAR_ALLOWANCE,
            height: grown ? visible + travel : visible,
            transform: `scale(${scale}) translateY(${scrolling ? -travel : 0}px)`,
            transition: scrolling
              ? `transform ${Math.round(((travel * scale) / PEEK_SPEED) * 1000)}ms linear, opacity 300ms`
              : `transform ${PEEK_RETURN_MS}ms cubic-bezier(0.22, 1, 0.36, 1), opacity 300ms`,
          }}
        />
      )}
    </div>
  );
}

/**
 * A PDF's first sheet, drawn by the browser's own viewer on white. That
 * viewer is a plugin, and plugins never load inside a sandboxed frame, so
 * this one is not sandboxed — the bytes are same-origin and inert.
 */
function DocumentCover({ src, title }: { src: string; title: string }) {
  const box = useRef<HTMLDivElement>(null);
  const near = useNearViewport(box);
  const { width, height } = useBoxSize(box);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => setLoaded(false), [src]);
  const scale = width > 0 ? width / DOCUMENT_VIRTUAL_WIDTH : 0;

  return (
    <div ref={box} className="absolute inset-0 bg-white" aria-hidden>
      {!loaded && <div className="absolute inset-0 animate-pulse bg-black/5" />}
      {near && scale > 0 && (
        <iframe
          key={src}
          src={src}
          title={title}
          tabIndex={-1}
          loading="lazy"
          onLoad={() => setLoaded(true)}
          data-testid="artifact-card-frame"
          className={cn(
            "pointer-events-none absolute left-0 top-0 origin-top-left border-0 bg-white transition-opacity duration-300",
            loaded ? "opacity-100" : "opacity-0",
          )}
          style={{
            // Both of the viewer's scrollbars fall outside the tile.
            width: DOCUMENT_VIRTUAL_WIDTH + SCROLLBAR_ALLOWANCE,
            height: height / scale + SCROLLBAR_ALLOWANCE,
            transform: `scale(${scale})`,
          }}
        />
      )}
    </div>
  );
}

/**
 * How a picture sits in its tile. A photograph fills it, cropped. A drawing
 * with a plain ground — a logo, a diagram, a banner — is shown whole, on a mat
 * of exactly that ground, so the tile reads as more of the same picture. One
 * with a transparent ground gets a white mat and some air: a drawing made
 * with dark strokes on nothing would vanish into a dark tile.
 */
interface PictureFit {
  whole: boolean;
  mat: string;
  air: boolean;
}

const FILLED: PictureFit = { whole: false, mat: "#ffffff", air: false };
const ON_WHITE: PictureFit = { whole: true, mat: "#ffffff", air: true };
/** The fits worked out so far, by card key — a second visit does not re-measure. */
const fits = new Map<string, PictureFit>();

const SAMPLE = 24;
/** How far an edge pixel may stray from the edge's average and still count as ground. */
const GROUND_TOLERANCE = 22;

/** Reads the picture's edge: a transparent ground, a plain one, or neither. */
export function measurePictureFit(image: HTMLImageElement): PictureFit | null {
  try {
    const canvas = document.createElement("canvas");
    canvas.width = SAMPLE;
    canvas.height = SAMPLE;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (!context) return null;
    context.drawImage(image, 0, 0, SAMPLE, SAMPLE);
    const { data } = context.getImageData(0, 0, SAMPLE, SAMPLE);
    const edge: number[][] = [];
    for (let y = 0; y < SAMPLE; y += 1) {
      for (let x = 0; x < SAMPLE; x += 1) {
        if (x !== 0 && y !== 0 && x !== SAMPLE - 1 && y !== SAMPLE - 1) continue;
        const at = (y * SAMPLE + x) * 4;
        edge.push([data[at], data[at + 1], data[at + 2], data[at + 3]]);
      }
    }
    const mean = [0, 1, 2, 3].map(
      (channel) => edge.reduce((sum, pixel) => sum + pixel[channel], 0) / edge.length,
    );
    if (mean[3] < 24) return ON_WHITE;
    if (mean[3] < 250) return null;
    const ground = edge.filter((pixel) =>
      [0, 1, 2].every((channel) => Math.abs(pixel[channel] - mean[channel]) <= GROUND_TOLERANCE),
    );
    if (ground.length < edge.length * 0.9) return null;
    const [r, g, b] = mean.map(Math.round);
    return { whole: true, mat: `rgb(${r}, ${g}, ${b})`, air: false };
  } catch {
    // A canvas that cannot be read (a tainted source, no 2D context) just
    // leaves the picture as it was going to be shown anyway.
    return null;
  }
}

/**
 * A picture on its tile. The tile learns the picture's proportions here and
 * takes its shape from them; how the picture then sits in that shape is
 * `PictureFit`.
 */
function ImageCover({ visual, cardKey }: { visual: VisualArtifact; cardKey: string }) {
  const vector = visual.kind === "vector";
  const [failed, setFailed] = useState(false);
  const [fit, setFit] = useState<PictureFit>(() => fits.get(cardKey) ?? (vector ? ON_WHITE : FILLED));
  if (failed) {
    return (
      <div className="absolute inset-0 flex items-center justify-center text-foreground-faint">
        <FileImage className="h-8 w-8" aria-hidden />
      </div>
    );
  }
  return (
    <div className="absolute inset-0" style={{ backgroundColor: fit.mat }}>
      <img
        src={visual.url}
        alt=""
        loading="lazy"
        decoding="async"
        draggable={false}
        onLoad={(event) => {
          const image = event.currentTarget;
          if (image.naturalHeight > 0) reportRatio(cardKey, image.naturalWidth / image.naturalHeight);
          const measured = measurePictureFit(image) ?? (vector ? ON_WHITE : FILLED);
          fits.set(cardKey, measured);
          setFit(measured);
        }}
        onError={() => setFailed(true)}
        className={cn(
          "absolute inset-0 h-full w-full transition-transform duration-500 ease-out",
          "group-hover/tile:scale-[1.03] motion-reduce:transition-none motion-reduce:group-hover/tile:scale-100",
          fit.whole ? "object-contain" : "object-cover",
          fit.air && "p-[9%]",
        )}
      />
    </div>
  );
}

/** How a note marks the way its run ended. */
function NoteMark({ status }: { status: OutputStatus }) {
  if (status === "running") return <Loader2 className="h-7 w-7 animate-spin text-accent" aria-hidden />;
  if (status === "error") return <CircleAlert className="h-7 w-7 text-destructive" aria-hidden />;
  if (status === "cancelled") return <Ban className="h-7 w-7 text-warning" aria-hidden />;
  return <StickyNote className="h-7 w-7 text-accent" aria-hidden />;
}

/** A run that drew nothing: a note with its title, its mark, and when. */
function NoteCover({
  title,
  status,
  when,
  files,
}: {
  title: string;
  status: OutputStatus;
  when: number;
  files: number;
}) {
  const t = useT();
  const language = useUiLanguage();
  const date = relativeWhen(when, Date.now(), language);
  return (
    <div className="absolute inset-0 flex flex-col p-5">
      <p className="line-clamp-3 shrink-0 text-lg font-semibold leading-snug text-foreground-strong [overflow-wrap:anywhere]">
        {title}
      </p>
      <div className="flex min-h-0 flex-1 items-center justify-center">
        <NoteMark status={status} />
      </div>
      <p className="flex shrink-0 items-center gap-3 truncate text-sm text-muted-foreground">
        {date && <span className="truncate">{date}</span>}
        {files > 0 && (
          <span className="inline-flex shrink-0 items-center gap-1.5 text-foreground-faint">
            <Files className="h-3.5 w-3.5" aria-hidden />
            {files === 1
              ? t("visualization.file_one")
              : t("visualization.files_count").replace("{0}", String(files))}
          </span>
        )}
      </p>
    </div>
  );
}

/** A page being written: its name on a sheet that is still filling in. */
function BuildingCover({ title }: { title: string }) {
  const t = useT();
  return (
    <div className="absolute inset-0 flex flex-col p-5">
      <p className="line-clamp-3 shrink-0 text-lg font-semibold leading-snug text-foreground-strong [overflow-wrap:anywhere]">
        {title}
      </p>
      <div className="flex min-h-0 flex-1 flex-col justify-center gap-2.5 py-3">
        <div className="h-2.5 w-4/5 animate-pulse rounded-full bg-foreground/10" />
        <div className="h-2.5 w-3/5 animate-pulse rounded-full bg-foreground/10 [animation-delay:150ms]" />
        <div className="h-2.5 w-2/3 animate-pulse rounded-full bg-foreground/10 [animation-delay:300ms]" />
      </div>
      <p className="inline-flex shrink-0 items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 animate-spin text-accent" aria-hidden />
        {t("visualization.building")}
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------------- */

/** The small square a list row leads with — the picture, or the kind's mark. */
export function RowThumb({ row }: { row: RailRow }) {
  const [failed, setFailed] = useState(false);
  const picture =
    row.kind === "visual" && (row.visual.kind === "image" || row.visual.kind === "vector") && !failed;
  if (picture && row.kind === "visual") {
    return (
      <span className="relative h-11 w-11 shrink-0 overflow-hidden rounded-lg border border-border bg-white">
        <img
          src={row.visual.url}
          alt=""
          loading="lazy"
          decoding="async"
          draggable={false}
          onError={() => setFailed(true)}
          className={cn(
            "absolute inset-0 h-full w-full",
            row.visual.kind === "vector" ? "object-contain p-1.5" : "object-cover",
          )}
        />
      </span>
    );
  }
  const Icon =
    row.kind === "visual" ? KIND_ICON[row.visual.kind] : row.kind === "build" ? Loader2 : StickyNote;
  return (
    <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-secondary text-muted-foreground">
      <Icon className={cn("h-5 w-5", row.kind === "build" && "animate-spin")} aria-hidden />
    </span>
  );
}
