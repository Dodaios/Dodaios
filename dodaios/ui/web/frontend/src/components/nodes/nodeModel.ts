/**
 * The Nodes library's data model: what `/api/nodes` hands out.
 *
 * A node is a thing the person keeps and looks at: a document, a deck, a
 * sheet, a designed page, a dashboard, a whiteboard, a short film. The seven
 * types below are the ones the assistant builds from a typed spec
 * (`dodaios/nodes` on the backend); everything older that a run left behind
 * (a worker-built page, a picture, a PDF, a report, a living page) is adopted
 * into the same list under the type it is closest to, so the library is one
 * place and not two.
 *
 * (Not to be confused with `lib/nodeSpec.ts`, which describes the nodes of
 * the RUN GRAPH.)
 */

/** The seven node types, in the order the library offers them. */
export const NODE_TYPES = [
  "docs",
  "slides",
  "sheets",
  "design",
  "data",
  "whiteboard",
  "motion",
] as const;

export type NodeType = (typeof NODE_TYPES)[number];

/** A card's type: a node type, or `output` for a run that left no page. */
export type CardType = NodeType | "output";

export function isNodeType(value: unknown): value is NodeType {
  return typeof value === "string" && (NODE_TYPES as readonly string[]).includes(value);
}

/** Where a card comes from. Only `node` is built from a spec and revisable. */
export type NodeOrigin =
  | "node" // a typed node (`dodaios/nodes`)
  | "living" // a living page of the older kind: a table kept current
  | "report" // a report page the assistant wrote from Markdown
  | "page" // a page a worker built (`create_artifact`)
  | "file" // a picture, a vector or a PDF a run left behind
  | "run" // a run without anything to look at: its answer is the card
  | "build"; // a page a worker is still building

/** How the stage puts the card's file on screen (null: no file, a run). */
export type NodeVisualKind = "page" | "image" | "vector" | "document";

/* --- what the card's cover is drawn from, per type ------------------------ */

export interface DocsPreview {
  heading: string;
  lines: string[];
  bullets: boolean;
}

export interface SlidesPreview {
  title: string;
  subtitle: string;
  count: number;
  dark: boolean;
  /** A CSS color, or "" for the default accent. */
  accent: string;
}

export interface SheetsPreview {
  columns: string[];
  rows: string[][];
  /** Per column: right-aligned (a number). */
  numeric: boolean[];
  count: number;
}

export interface DesignPreview {
  /** A CSS color, or "". */
  background: string;
  fit: "page" | "canvas";
  width: number;
  height: number;
}

export interface DataPreview {
  metrics: { label: string; value: string }[];
  /** The first chart's first series, scaled into 0..1. */
  bars: number[];
  chart: "line" | "bar";
}

export type WhiteboardColor = "yellow" | "pink" | "blue" | "green" | "violet" | "orange" | "gray";

export interface WhiteboardPreview {
  notes: { text: string; color: WhiteboardColor }[];
  count: number;
}

export interface MotionPreview {
  title: string;
  subtitle: string;
  seconds: number;
  dark: boolean;
  accent: string;
  format: "wide" | "square" | "tall";
}

/** A run without a page: the first lines of its answer. */
export interface OutputPreview {
  text: string;
}

export interface NodePreviewByType {
  docs: DocsPreview;
  slides: SlidesPreview;
  sheets: SheetsPreview;
  design: DesignPreview;
  data: DataPreview;
  whiteboard: WhiteboardPreview;
  motion: MotionPreview;
  output: OutputPreview;
}

/** One card of the library, exactly as `/api/nodes` lists it. */
export interface NodeCard {
  /**
   * Stable identity: `slug::path` for anything with a file (the same key the
   * favorites and the stage use), `run:<slug>` for a run, `build:<slug>` for
   * a page still being built.
   */
  key: string;
  /** The node id of a typed node; null for everything adopted. */
  id: string | null;
  type: CardType;
  origin: NodeOrigin;
  title: string;
  /** Run directory name: the `/api/outputs/{slug}` path segment. */
  slug: string;
  /** The file inside the run, or null for a run or a build. */
  path: string | null;
  visual_kind: NodeVisualKind | null;
  /** Seconds since the epoch. */
  created_at: number;
  updated_at: number;
  /** Bytes of the file (0 when there is none). */
  size: number;
  /** Content revision of a typed node; 0 for everything adopted. */
  version: number;
  status: "ready" | "building" | "error";
  /** The assistant refreshes it on a schedule. */
  kept_current: boolean;
  /** That refresh is running (not stopped or paused). */
  refreshing: boolean;
  every_minutes: number;
  /** What the person asked for, when the run recorded it; "" otherwise. */
  request: string;
  /**
   * What the cover is drawn from, in the shape of the card's `type`; null for
   * an adopted file, whose cover is the file itself.
   */
  preview: NodePreviewByType[CardType] | null;
}

export interface NodesResponse {
  nodes: NodeCard[];
  /** Runs looked at for adopted files, and runs outside that window. */
  scanned_runs: number;
  skipped_runs: number;
}

/** The card's cover data, narrowed to its type (null when there is none). */
export function previewOf<T extends CardType>(
  card: NodeCard,
  type: T,
): NodePreviewByType[T] | null {
  return card.type === type && card.preview !== null
    ? (card.preview as NodePreviewByType[T])
    : null;
}

/** Only a typed node can be renamed, duplicated, reverted or revised. */
export function isTypedNode(card: NodeCard): card is NodeCard & { id: string } {
  return card.origin === "node" && card.id !== null;
}

/** The run-directory infix of a typed node (`dodaios/nodes` on the backend). */
export const NODE_SLUG_INFIX = "__node__";

/** Whether a run slug is a typed node's. */
export function isNodeSlug(slug: string | null | undefined): boolean {
  return !!slug && slug.includes(NODE_SLUG_INFIX);
}
