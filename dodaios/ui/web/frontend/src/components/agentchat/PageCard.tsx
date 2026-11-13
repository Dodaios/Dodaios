/**
 * How a page the assistant made shows in the conversation.
 *
 * A page or node the turn made: a preview card. The top of the page itself,
 * live and inert, fading out at the bottom; under it the page's name, what it
 * is, and a download button. The whole card opens the page in the Nodes
 * section. Up to `MAX_PREVIEWS_PER_TURN` different pages in a turn each get
 * their card.
 *
 * The same page posted twice in a turn (made, then revised) is ONE page: only
 * its last notice is drawn, so a revision does not turn the card into links.
 *
 * More pages than that in a turn: one line each, the page's name as a link
 * with a page mark (`pageNoticeModes` decides). A stack of previews would bury
 * the short reply they belong to.
 *
 * The same link (`PageLink`) is what a page named inside an answer's text is
 * drawn as (`pageRefFromMarkdownUrl` in chatLinks.ts).
 */
import { useEffect, useRef, useState } from "react";
import { ArrowDown, FileChartColumn } from "lucide-react";

import { useNearViewport, useBoxSize } from "@/components/visualization/ArtifactCovers";
import { artifactDownloadUrl } from "@/hooks/useOutputs";
import { useThemeValue } from "@/hooks/useTheme";
import { artifactPageUrl } from "@/hooks/useVisualArtifacts";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";
import { NODE_TYPE_LABEL_KEY } from "@/components/nodes/nodeTheme";
import { isNodeType, type NodeType } from "@/components/nodes/nodeModel";
import type { NoticeItem, TimelineItem } from "./reduce";

export interface PageCardData {
  title: string;
  summary: string;
  /** `slug::path`, the Artifacts section's address of the page. */
  artifact: string;
  slug: string;
  path: string;
  sections: number;
  /** A node's type (`sheets`, `slides` …); null for a page that is no node. */
  nodeType: NodeType | null;
}

/** The notice kind a written page arrives as (`write_report`, `create_artifact`). */
export const PAGE_NOTICE_KIND = "report";

/** `slug` and `path` of a `slug::path` address, or null. */
export function splitPageRef(ref: string): { slug: string; path: string } | null {
  const at = ref.indexOf("::");
  if (at <= 0 || at + 2 >= ref.length) return null;
  return { slug: ref.slice(0, at), path: ref.slice(at + 2) };
}

/** The card's data from a notice payload, or null when it cannot open anything. */
export function pageCardData(item: Pick<NoticeItem, "text" | "data">): PageCardData | null {
  const data = item.data ?? {};
  const artifact = typeof data.artifact === "string" ? data.artifact : "";
  const parts = splitPageRef(artifact);
  const title = (item.text || "").trim();
  if (!parts || !title) return null;
  const sections = typeof data.sections === "number" && Number.isFinite(data.sections) ? Math.max(0, Math.floor(data.sections)) : 0;
  return {
    title,
    summary: typeof data.summary === "string" ? data.summary.trim() : "",
    artifact,
    ...parts,
    sections,
    nodeType: isNodeType(data.node_type) ? data.node_type : null,
  };
}

/** `hidden`: an earlier notice of a page the same turn posted again. */
export type PageNoticeMode = "preview" | "link" | "hidden";

/** Different pages in one turn that still each get a preview card. */
export const MAX_PREVIEWS_PER_TURN = 3;

/**
 * How the page notices of one turn are drawn, in their order: the last
 * notice of each page is shown (a preview card while the turn made at most
 * `MAX_PREVIEWS_PER_TURN` different pages, a link beyond that), every earlier
 * notice of the same page is hidden.
 */
export function pageModesForTurn(
  notices: readonly Pick<NoticeItem, "id" | "text" | "data">[],
): Map<string, PageNoticeMode> {
  const lastOf = new Map<string, string>();
  for (const notice of notices) {
    const page = pageCardData(notice);
    if (page) lastOf.set(page.artifact, notice.id);
  }
  const shown = lastOf.size > MAX_PREVIEWS_PER_TURN ? "link" : "preview";
  const modes = new Map<string, PageNoticeMode>();
  for (const notice of notices) {
    const page = pageCardData(notice);
    if (page) modes.set(notice.id, lastOf.get(page.artifact) === notice.id ? shown : "hidden");
  }
  return modes;
}

/**
 * How each page notice of a conversation is drawn (`pageModesForTurn`, turn
 * by turn). A turn runs from one message of the person to the next.
 */
export function pageNoticeModes(items: readonly TimelineItem[]): Map<string, PageNoticeMode> {
  const modes = new Map<string, PageNoticeMode>();
  let turn: NoticeItem[] = [];
  const close = () => {
    for (const [id, mode] of pageModesForTurn(turn)) modes.set(id, mode);
    turn = [];
  };
  for (const item of items) {
    if (item.type === "user") close();
    else if (item.type === "notice" && item.kind === PAGE_NOTICE_KIND && pageCardData(item)) turn.push(item);
  }
  close();
  return modes;
}

/** A page's name as a link with the page mark; opens it in the Artifacts section. */
export function PageLink({ pageRef, label, className }: { pageRef: string; label: string; className?: string }) {
  const t = useT();
  const requestVisual = useEventStore((s) => s.requestVisual);
  const name = label.trim() || splitPageRef(pageRef)?.path.split("/").pop() || pageRef;
  return (
    <button
      type="button"
      data-testid="page-link"
      onClick={() => requestVisual(pageRef)}
      title={`${t("reports.open")}: ${name}`}
      className={cn(
        "inline-flex max-w-full items-baseline gap-1.5 rounded-sm text-left align-baseline text-foreground",
        "underline decoration-foreground/40 decoration-1 underline-offset-4 hover:decoration-foreground",
        className,
      )}
    >
      <FileChartColumn className="h-[1em] w-[1em] shrink-0 translate-y-[0.14em] text-muted-foreground" aria-hidden />
      <span className="min-w-0 [overflow-wrap:anywhere]">{name}</span>
    </button>
  );
}

/** The page is laid out a little wider than the card and scaled to fit it. */
const PREVIEW_SCALE = 0.86;
const PREVIEW_MIN_WIDTH = 640;
const PREVIEW_MAX_WIDTH = 900;
/** Room for the page's own scrollbar, kept outside the card's edge. */
const SCROLLBAR_ALLOWANCE = 24;

/** The top of the live page, inert: no pointer, no focus, hidden from assistive tech. */
function PagePreview({ src, title }: { src: string; title: string }) {
  const box = useRef<HTMLDivElement>(null);
  const near = useNearViewport(box);
  const { width, height } = useBoxSize(box);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => setLoaded(false), [src]);
  const virtual = Math.min(PREVIEW_MAX_WIDTH, Math.max(PREVIEW_MIN_WIDTH, Math.round(width / PREVIEW_SCALE)));
  const scale = width > 0 ? width / virtual : 0;
  return (
    <div
      ref={box}
      aria-hidden
      className="absolute inset-0 overflow-hidden"
      // The page fades into the card instead of ending on a cut line.
      style={{ maskImage: "linear-gradient(to bottom, #000 calc(100% - 64px), transparent)", WebkitMaskImage: "linear-gradient(to bottom, #000 calc(100% - 64px), transparent)" }}
    >
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
          data-testid="page-card-frame"
          className={cn("pointer-events-none absolute left-0 top-0 origin-top-left border-0 transition-opacity duration-300", loaded ? "opacity-100" : "opacity-0")}
          style={{ width: virtual + SCROLLBAR_ALLOWANCE, height: height / scale, transform: `scale(${scale})` }}
        />
      )}
    </div>
  );
}

export function PageCard({ item, mode = "preview" }: { item: NoticeItem; mode?: PageNoticeMode }) {
  const t = useT();
  const theme = useThemeValue();
  const requestVisual = useEventStore((s) => s.requestVisual);
  const page = pageCardData(item);
  if (!page || mode === "hidden") return null;
  if (mode === "link") {
    return (
      <div data-message-id={item.id} data-testid="page-link-row" className="flex w-full max-w-[720px] px-1 text-body">
        <PageLink pageRef={page.artifact} label={page.title} />
      </div>
    );
  }
  const open = () => requestVisual(page.artifact);
  const openLabel = `${t("reports.open")}: ${page.title}`;
  const fileName = page.path.split("/").pop() || "page.html";
  return (
    <article
      data-message-id={item.id}
      data-testid="page-card"
      className="group w-full max-w-[720px] overflow-hidden rounded-2xl border border-border bg-card shadow-rim transition-colors hover:border-border-strong"
    >
      <button type="button" data-testid="page-card-preview" onClick={open} aria-label={openLabel} className="relative block h-[300px] w-full cursor-pointer overflow-hidden text-left">
        <PagePreview src={`${artifactPageUrl(page.slug, page.path)}?theme=${theme}`} title={page.title} />
      </button>
      <footer className="flex items-center gap-3 border-t border-border px-4 py-3">
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-border bg-background text-muted-foreground">
          <FileChartColumn className="h-5 w-5" aria-hidden />
        </span>
        <button type="button" data-testid="page-card-title" onClick={open} aria-label={openLabel} className="min-w-0 flex-1 text-left">
          <span className="block truncate text-[15px] font-medium text-foreground">{page.title}</span>
          <span className="block truncate text-sm text-muted-foreground" data-testid="page-card-kind">
            {page.nodeType ? t(NODE_TYPE_LABEL_KEY[page.nodeType]) : t("reports.page")}
          </span>
        </button>
        <a
          href={artifactDownloadUrl(page.slug, page.path)}
          download={fileName}
          data-testid="page-card-download"
          aria-label={`${t("reports.download")}: ${page.title}`}
          title={t("reports.download")}
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-border bg-background text-foreground transition-colors hover:bg-secondary"
        >
          <ArrowDown className="h-4 w-4" aria-hidden />
        </a>
      </footer>
    </article>
  );
}
