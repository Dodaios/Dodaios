/**
 * Test support: the cards `/api/nodes` lists for a set of fixture runs.
 *
 * The section's tests describe an archive the way the run archive hands it
 * out: runs (`/api/outputs`) and, per run, a file listing
 * (`/api/outputs/{slug}/artifacts`). The library reads `/api/nodes` instead,
 * so a fetch mock has to answer that one from the same fixtures. The rules
 * here are the server's adoption rules (`dodaios/nodes/library.py`), as far
 * as a fixture needs them.
 *
 * Imported by tests only.
 */
import { parseArtifactUtterance, runTitle, runWhen } from "@/components/visualization/galleryModel";
import { LIVING_SLUG_INFIX } from "@/components/visualization/livingPage";
import type { ArtifactSummary, OutputSummary } from "@/hooks/useOutputs";
import { classifyVisual, pageTitleFromPreview } from "@/hooks/useVisualArtifacts";
import { cleanRequest } from "@/lib/runRequest";
import { NODE_SLUG_INFIX, type NodeCard, type NodesResponse } from "./nodeModel";

/** The run-directory infix of a report page (`dodaios/artifacts/report.py`). */
const REPORT_SLUG_INFIX = "__report__";

/** A card with every field set; `over` says what the test is about. */
export function nodeCard(over: Partial<NodeCard> & Pick<NodeCard, "key" | "slug">): NodeCard {
  return {
    id: null,
    type: "design",
    origin: "page",
    title: over.slug,
    path: null,
    visual_kind: null,
    created_at: 0,
    updated_at: 0,
    size: 0,
    version: 0,
    status: "ready",
    kept_current: false,
    refreshing: false,
    every_minutes: 0,
    request: "",
    preview: null,
    ...over,
  };
}

/** The card of a typed node: its run slug carries the node infix and its id. */
export function typedNodeCard(id: string, over: Partial<NodeCard> = {}): NodeCard {
  const slug = over.slug ?? `2026-11-13${NODE_SLUG_INFIX}${id}`;
  return nodeCard({
    key: `${slug}::index.html`,
    id,
    slug,
    type: "docs",
    origin: "node",
    title: id,
    path: "index.html",
    visual_kind: "page",
    version: 1,
    ...over,
  });
}

/** The card's `request`: the run's request, a page brief reduced to its title. */
function requestOf(run: OutputSummary): string {
  return parseArtifactUtterance(run.utterance)?.title ?? cleanRequest(run.utterance);
}

/** The cards of a run's files a person can look at. */
function fileCards(run: OutputSummary, files: ArtifactSummary[]): NodeCard[] {
  const living = run.slug.includes(LIVING_SLUG_INFIX);
  const report = run.slug.includes(REPORT_SLUG_INFIX);
  // A run that built exactly one page was asked for that page by name.
  const pages = files.filter((file) => classifyVisual(file.path) === "page").length;
  const asked = pages === 1 ? parseArtifactUtterance(run.utterance)?.title : undefined;
  const cards: NodeCard[] = [];
  for (const file of files) {
    const kind = classifyVisual(file.path);
    // A report run also holds the Markdown it was made from: the page is the report.
    if (kind === null || (report && kind !== "page")) continue;
    const name = file.path.split("/").pop() ?? file.path;
    const page = kind === "page";
    const [type, origin]: [NodeCard["type"], NodeCard["origin"]] = !page
      ? [kind === "document" ? "docs" : "design", "file"]
      : living
        ? ["sheets", "living"]
        : report
          ? ["docs", "report"]
          : ["design", "page"];
    cards.push(
      nodeCard({
        key: `${run.slug}::${file.path}`,
        slug: run.slug,
        type,
        origin,
        title: page ? file.title?.trim() || pageTitleFromPreview(file.preview) || asked || name : name,
        path: file.path,
        visual_kind: kind,
        created_at: run.started_at || file.mtime,
        updated_at: file.mtime,
        size: file.size,
        status: run.status === "error" ? "error" : "ready",
        kept_current: page && living,
        request: requestOf(run),
      }),
    );
  }
  return cards;
}

/** Work in progress first, then last changed first: the order the server lists in. */
function inServerOrder(cards: NodeCard[]): NodeCard[] {
  return [...cards].sort(
    (a, b) =>
      Number(b.status === "building") - Number(a.status === "building") || b.updated_at - a.updated_at,
  );
}

/**
 * The cards the server adopts from `runs` and their file listings: one per
 * page, picture or PDF; a "building" card for a page a worker is still
 * writing; and a run card for a run that left nothing to look at.
 */
export function cardsFromRuns(
  runs: OutputSummary[],
  filesBySlug: Record<string, ArtifactSummary[]> = {},
): NodeCard[] {
  const cards: NodeCard[] = [];
  for (const run of runs) {
    // A typed node's run is that node's card; its files are never adopted.
    if (run.slug.includes(NODE_SLUG_INFIX)) continue;
    const found = fileCards(run, filesBySlug[run.slug] ?? []);
    cards.push(...found);
    const shared = {
      slug: run.slug,
      title: runTitle(run),
      created_at: run.started_at ?? 0,
      updated_at: runWhen(run),
      request: requestOf(run),
    };
    const building =
      run.status === "running" &&
      parseArtifactUtterance(run.utterance) !== null &&
      !found.some((card) => card.visual_kind === "page");
    if (building) {
      cards.push(nodeCard({ ...shared, key: `build:${run.slug}`, origin: "build", status: "building" }));
    } else if (found.length === 0) {
      cards.push(
        nodeCard({
          ...shared,
          key: `run:${run.slug}`,
          type: "output",
          origin: "run",
          status: run.status === "running" ? "building" : run.status === "error" ? "error" : "ready",
          preview: { text: run.summary ?? "" },
        }),
      );
    }
  }
  return inServerOrder(cards);
}

/** What `GET /api/nodes` answers for these fixtures, plus any typed nodes. */
export function nodesResponse(
  runs: OutputSummary[],
  filesBySlug: Record<string, ArtifactSummary[]> = {},
  typed: NodeCard[] = [],
): NodesResponse {
  return {
    nodes: inServerOrder([...typed, ...cardsFromRuns(runs, filesBySlug)]),
    scanned_runs: runs.filter((run) => !run.slug.includes(NODE_SLUG_INFIX)).length,
    skipped_runs: 0,
  };
}
