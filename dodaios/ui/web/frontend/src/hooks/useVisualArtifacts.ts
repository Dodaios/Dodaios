/**
 * Which of a run's files a person can look at, and where each is served from.
 *
 * No REST surface of its own: `/api/outputs/{slug}/artifacts` already lists a
 * run's files. What this module adds is the SELECTION (`classifyVisual`,
 * `toVisuals`): which of those files are pages and pictures. The stage of the
 * Nodes section uses it for a run it opens directly, the home panel and the
 * run graph for their own previews. The library does not scan runs from here:
 * the server lists its cards in one read (`/api/nodes`).
 */
import type { ArtifactSummary, OutputStatus, OutputSummary } from "@/hooks/useOutputs";

/** How a visual is put on screen — one branch of the stage per kind. */
export type VisualKind = "image" | "vector" | "page" | "document";

/**
 * Extension → kind. Deliberately narrow: everything here must render inside the
 * desktop WebView without a plugin or a converter. A format that only *some*
 * hosts can draw would make the stage a coin flip, and a blank frame is a worse
 * answer than not listing the file at all (it still shows up under the
 * run's Files tab).
 */
const VISUAL_EXTENSIONS: ReadonlyArray<readonly [string, VisualKind]> = [
  [".png", "image"],
  [".jpg", "image"],
  [".jpeg", "image"],
  [".gif", "image"],
  [".webp", "image"],
  [".bmp", "image"],
  [".avif", "image"],
  [".svg", "vector"],
  [".html", "page"],
  [".htm", "page"],
  [".pdf", "document"],
];

/** The kind this filename renders as, or null when it is not a visual. */
export function classifyVisual(path: string): VisualKind | null {
  const lower = path.toLowerCase();
  for (const [extension, kind] of VISUAL_EXTENSIONS) {
    if (lower.endsWith(extension)) return kind;
  }
  return null;
}

/** One renderable artifact, already carrying the run it belongs to. */
export interface VisualArtifact {
  /** Run directory name — the `/api/outputs/{slug}` path segment. */
  slug: string;
  /** What the user asked for, when the run recorded it. */
  utterance?: string;
  /** The run's status — a page from a run that failed its review still shows. */
  status?: OutputStatus;
  /** Artifact path relative to the run directory. */
  path: string;
  /** Last path segment — the fallback label. */
  name: string;
  /**
   * What the library calls it: a page's own `<title>`, else the title its
   * brief asked for, otherwise the filename. The title is what the user asked
   * for in their words ("Umsatz-Dashboard"), the filename is its slug.
   */
  title: string;
  kind: VisualKind;
  size: number;
  mtime: number;
  /** Ready-to-use `src` for an `<img>`/`<iframe>` (served inline, no scripts). */
  url: string;
}

/**
 * Encode an artifact path segment by segment.
 *
 * Same rule as `useOutputs.encodeArtifactPath` (not exported there): `encodeURI`
 * leaves `#`, `?` and `&` raw, so a file called `chart#2.png` would be truncated
 * at the `#` and 404.
 */
function encodeArtifactPath(path: string): string {
  return path.split("/").map(encodeURIComponent).join("/");
}

/** The inline URL a visual is rendered from. */
export function visualUrl(slug: string, path: string): string {
  return `/api/outputs/${encodeURIComponent(slug)}/files/${encodeArtifactPath(
    path,
  )}/download?disposition=inline`;
}

/**
 * The ARTIFACT PAGE url of an HTML deliverable: served with scripts allowed
 * and every network path shut (`ARTIFACT_PAGE_CSP`, outputs_routes.py). The
 * stage frames it with `sandbox="allow-scripts"` and no same-origin, so the
 * page's own JavaScript runs — a dashboard filters, a chart draws — inside an
 * opaque origin that cannot reach the app. Non-HTML files keep `visualUrl`.
 */
export function artifactPageUrl(slug: string, path: string): string {
  return `/api/outputs/${encodeURIComponent(slug)}/files/${encodeArtifactPath(path)}/page`;
}

/** A stable identity for one artifact — the selection key and the React key. */
export function visualId(artifact: Pick<VisualArtifact, "slug" | "path">): string {
  return `${artifact.slug}::${artifact.path}`;
}

/** The server-rendered node-graph page for one run (no JS, brand-themed). */
export function missionMapUrl(slug: string): string {
  return `/api/outputs/${encodeURIComponent(slug)}/graph`;
}

const TITLE_RE = /<title[^>]*>([\s\S]*?)<\/title>/i;

/** A page's `<title>` from the listing's text preview, or null. */
export function pageTitleFromPreview(preview: string | null | undefined): string | null {
  if (!preview) return null;
  const match = TITLE_RE.exec(preview);
  if (!match) return null;
  const title = match[1].replace(/\s+/g, " ").trim();
  return title.length > 0 ? decodeEntities(title) : null;
}

/**
 * The handful of entities a `<title>` realistically carries. `&amp;` is
 * decoded last so `&amp;lt;` stays the literal text `&lt;` (no double decode).
 */
function decodeEntities(text: string): string {
  return text
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;|&apos;/g, "'")
    .replace(/&amp;/g, "&");
}

/** The title a `create_artifact` brief leads with (`Artifact: <title>`), or null. */
function briefTitle(utterance: string | undefined): string | null {
  const match = /^Artifact:[ \t]*([^\n]+)/.exec((utterance ?? "").trim());
  return match ? match[1].trim() || null : null;
}

/** The visuals among a run's files, carrying the run they belong to. */
export function toVisuals(run: OutputSummary, files: ArtifactSummary[]): VisualArtifact[] {
  const visuals: VisualArtifact[] = [];
  // A run that built exactly one page was asked for that page by name — the
  // brief's title is the page's name when the file itself does not say.
  const pages = files.filter((file) => classifyVisual(file.path) === "page").length;
  const asked = pages === 1 ? briefTitle(run.utterance) : null;
  for (const file of files) {
    const kind = classifyVisual(file.path);
    if (kind === null) continue;
    const name = file.path.split("/").pop() ?? file.path;
    const ownTitle =
      kind === "page" ? file.title?.trim() || pageTitleFromPreview(file.preview) || asked : null;
    visuals.push({
      slug: run.slug,
      utterance: run.utterance,
      status: run.status,
      path: file.path,
      name,
      title: ownTitle ?? name,
      kind,
      size: file.size,
      mtime: file.mtime,
      url: visualUrl(run.slug, file.path),
    });
  }
  return visuals;
}
