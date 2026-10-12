import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  ArrowDownUp,
  Check,
  Ellipsis,
  LayoutGrid,
  List,
  Loader2,
  RefreshCw,
  Search,
  SlidersHorizontal,
  Star,
} from "lucide-react";

import { EmptyState } from "@/components/ui/empty-state";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useT, useUiLanguage } from "@/i18n";
import { useThemeValue } from "@/hooks/useTheme";
import { cn } from "@/lib/utils";
import { endMissionDrag, startMissionDrag } from "@/lib/missionDnd";
import { openExternalUrl } from "@/lib/openExternal";
import { useEventStore } from "@/store/events";
import {
  DeleteOutputError,
  artifactDownloadUrl,
  deleteOutput,
  revealArtifact,
  revealOutput,
  useOutputsCapabilities,
  type OutputStatus,
} from "@/hooks/useOutputs";
import { artifactPageUrl } from "@/hooks/useVisualArtifacts";
import {
  RAIL_FILTERS,
  featureIndex,
  layoutWall,
  relativeWhen,
  rowRequest,
  rowTitle,
  rowWhen,
  tileShape,
  wallColumns,
  type GalleryGroup,
  type GallerySort,
  type RailFilter,
  type RailRow,
  type TileShape,
} from "@/components/visualization/galleryModel";
import {
  ArtifactCardMenu,
  ConfirmDeleteArtifact,
  rowIsWorking,
  type ArtifactMenuState,
} from "@/components/visualization/ArtifactCardMenu";
import {
  RowThumb,
  TileCover,
  useBoxSize,
  useImageRatios,
} from "@/components/visualization/ArtifactCovers";

/**
 * The Artifacts library: a title, a row of tabs, and a wall.
 *
 * The wall is the point. Every artifact is a tile with the artifact itself
 * drawn on it, edge to edge, and nothing underneath — no caption strip, no
 * icon chip, no date heading. A tile's name, kind and age rise over its lower
 * edge when the pointer or the keyboard reaches it (or always, when the reader
 * asks for that), next to a star and a menu. Tiles come in three shapes on one
 * half-tile lattice, so pictures keep their proportions and the wall still
 * reads as one surface; they are placed by hand (`layoutWall`) rather than by
 * CSS columns, which keeps the DOM in reading order and lets a tile glide to
 * its new place when a tab or a search narrows the wall.
 *
 * The same cards as a list are one toggle away, for when the reader is
 * looking for a name rather than a picture.
 */

/** How the library is drawn, how big its tiles are, and when they are named. */
export type GalleryView = "wall" | "list";
export type TileSize = "s" | "m" | "l";
export type TileLabels = "hover" | "always";

export const GALLERY_VIEWS: readonly GalleryView[] = ["wall", "list"];
export const TILE_SIZES: readonly TileSize[] = ["s", "m", "l"];
export const TILE_LABELS: readonly TileLabels[] = ["hover", "always"];

/** The narrowest a tile of each size may get before the wall drops a column. */
const TILE_MINIMUM: Record<TileSize, number> = { s: 168, m: 228, l: 320 };
const WALL_GAP = 16;
/** How long the pointer rests on a tile before its page starts to scroll. */
const PEEK_DELAY_MS = 420;

/** What a status chip's dot means — the run vocabulary, one language. */
const STATUS_DOT: Record<OutputStatus, string> = {
  success: "bg-success",
  error: "bg-destructive",
  running: "bg-success animate-pulse",
  cancelled: "bg-warning",
  unknown: "bg-muted-foreground",
};

const ROW_TESTID: Record<RailRow["kind"], string> = {
  build: "visualization-building-row",
  visual: "visualization-artifact-row",
  run: "visualization-run-row",
};

function rowStatus(row: RailRow): OutputStatus {
  return row.kind === "visual" ? (row.visual.status ?? "unknown") : (row.run.status ?? "unknown");
}

/** The kind word in a tile's caption and a list row's column. */
function kindLabel(row: RailRow, t: (key: string) => string): string {
  if (row.kind === "build") return t("visualization.building");
  if (row.kind === "run") return t("visualization.output_kind");
  return t(`visualization.kind_${row.visual.kind}`);
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/* ------------------------------------------------------------------------- */

const ICON_BUTTON =
  "inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors " +
  "hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring " +
  "disabled:pointer-events-none disabled:opacity-50 [&_svg]:h-[18px] [&_svg]:w-[18px]";

/**
 * A button that opens a small panel under itself. Closes on a click outside,
 * on Escape, and when focus leaves it.
 */
function HeaderPopover({
  label,
  icon,
  testId,
  children,
}: {
  label: string;
  icon: ReactNode;
  testId: string;
  children: (close: () => void) => ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.stopPropagation();
      setOpen(false);
      root.current?.querySelector<HTMLButtonElement>("button")?.focus();
    };
    window.addEventListener("pointerdown", onPointerDown, true);
    window.addEventListener("keydown", onKeyDown, true);
    return () => {
      window.removeEventListener("pointerdown", onPointerDown, true);
      window.removeEventListener("keydown", onKeyDown, true);
    };
  }, [open]);

  return (
    <div ref={root} className="relative">
      <button
        type="button"
        aria-haspopup="true"
        aria-expanded={open}
        aria-label={label}
        title={label}
        onClick={() => setOpen((value) => !value)}
        data-testid={testId}
        className={cn(ICON_BUTTON, open && "bg-secondary text-foreground")}
      >
        {icon}
      </button>
      {open && (
        <div
          className={cn(
            "absolute right-0 top-full z-50 mt-2 min-w-56 rounded-xl border border-border bg-popover p-1.5 shadow-float",
            "animate-in fade-in-0 zoom-in-95 duration-150",
          )}
        >
          {children(close)}
        </div>
      )}
    </div>
  );
}

/** One choice in a header panel; the chosen one carries a check. */
function PanelChoice({
  chosen,
  onChoose,
  testId,
  children,
}: {
  chosen: boolean;
  onChoose: () => void;
  testId?: string;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      role="menuitemradio"
      aria-checked={chosen}
      onClick={onChoose}
      data-testid={testId}
      className={cn(
        "flex h-9 w-full items-center gap-2.5 rounded-lg px-2.5 text-left text-base transition-colors",
        "hover:bg-secondary focus-visible:bg-secondary focus-visible:outline-none",
        chosen ? "font-medium text-foreground-strong" : "text-foreground",
      )}
    >
      <span className="min-w-0 flex-1 truncate">{children}</span>
      {chosen && <Check className="h-4 w-4 shrink-0 text-accent" aria-hidden />}
    </button>
  );
}

function PanelHeading({ children }: { children: ReactNode }) {
  return <p className="px-2.5 pb-1 pt-2 text-sm font-medium text-foreground-faint">{children}</p>;
}

/** A row of mutually exclusive words — the tile sizes. */
function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
  testId,
}: {
  value: T;
  options: ReadonlyArray<{ id: T; label: string }>;
  onChange: (next: T) => void;
  label: string;
  testId: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="mx-1 flex rounded-full bg-secondary p-1">
      {options.map((option) => (
        <button
          key={option.id}
          type="button"
          role="radio"
          aria-checked={value === option.id}
          onClick={() => onChange(option.id)}
          data-testid={`${testId}-${option.id}`}
          className={cn(
            "h-7 flex-1 whitespace-nowrap rounded-full px-3 text-sm font-medium transition-colors",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            value === option.id
              ? "bg-background text-foreground-strong shadow-sm"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

/**
 * The library's head: its name on the left; order, wall-or-list, search,
 * display options and refresh on the right. With `bare` (nothing in the
 * library at all) only the name and refresh remain.
 */
export function LibraryHeader({
  query,
  onQuery,
  sort,
  onSort,
  view,
  onView,
  size,
  onSize,
  labels,
  onLabels,
  loading,
  onRefresh,
  bare,
}: {
  query: string;
  onQuery: (next: string) => void;
  sort: GallerySort;
  onSort: (next: GallerySort) => void;
  view: GalleryView;
  onView: (next: GalleryView) => void;
  size: TileSize;
  onSize: (next: TileSize) => void;
  labels: TileLabels;
  onLabels: (next: TileLabels) => void;
  loading: boolean;
  onRefresh: () => void;
  bare: boolean;
}) {
  const t = useT();
  const sorts: GallerySort[] = ["newest", "oldest", "name"];
  return (
    <header className="relative z-20 flex shrink-0 flex-wrap items-center gap-x-2 gap-y-3 px-8 pt-8">
      <h1 className="mr-auto pr-4 text-3xl font-semibold tracking-tight text-foreground-strong">
        {t("visualization.title")}
      </h1>
      {!bare && (
        <>
          <HeaderPopover
            label={t("visualization.sort_label")}
            icon={<ArrowDownUp aria-hidden />}
            testId="visualization-sort"
          >
            {(close) => (
              <div role="menu" aria-label={t("visualization.sort_label")}>
                {sorts.map((id) => (
                  <PanelChoice
                    key={id}
                    chosen={sort === id}
                    testId={`visualization-sort-${id}`}
                    onChoose={() => {
                      onSort(id);
                      close();
                    }}
                  >
                    {t(`visualization.sort_${id}`)}
                  </PanelChoice>
                ))}
              </div>
            )}
          </HeaderPopover>

          <div
            role="group"
            aria-label={t("visualization.view_label")}
            className="flex items-center rounded-full"
          >
            {(
              [
                { id: "wall", Icon: LayoutGrid },
                { id: "list", Icon: List },
              ] as const
            ).map(({ id, Icon }) => (
              <button
                key={id}
                type="button"
                aria-pressed={view === id}
                aria-label={t(`visualization.view_${id}`)}
                title={t(`visualization.view_${id}`)}
                onClick={() => onView(id)}
                data-testid={`visualization-view-${id}`}
                className={cn(ICON_BUTTON, view === id && "bg-secondary text-foreground-strong")}
              >
                <Icon aria-hidden />
              </button>
            ))}
          </div>

          <div className="relative mx-1 w-72 max-w-full">
            <Search
              className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-foreground-faint"
              aria-hidden
            />
            <input
              type="search"
              value={query}
              onChange={(event) => onQuery(event.target.value)}
              placeholder={t("visualization.search_placeholder")}
              aria-label={t("visualization.search_placeholder")}
              data-testid="visualization-search"
              className={cn(
                "h-9 w-full rounded-full border border-border bg-secondary/60 pl-10 pr-4 text-base text-foreground",
                "placeholder:text-foreground-faint transition-colors",
                "hover:border-border-strong focus-visible:border-accent focus-visible:bg-background focus-visible:outline-none",
                "focus-visible:ring-2 focus-visible:ring-ring",
              )}
            />
          </div>

          <HeaderPopover
            label={t("visualization.display_options")}
            icon={<SlidersHorizontal aria-hidden />}
            testId="visualization-display"
          >
            {() => (
              <div className="w-72 pb-1">
                <PanelHeading>{t("visualization.tile_size")}</PanelHeading>
                <Segmented
                  value={size}
                  onChange={onSize}
                  label={t("visualization.tile_size")}
                  testId="visualization-size"
                  options={[
                    { id: "s", label: t("visualization.size_s") },
                    { id: "m", label: t("visualization.size_m") },
                    { id: "l", label: t("visualization.size_l") },
                  ]}
                />
                <PanelHeading>{t("visualization.labels_title")}</PanelHeading>
                <Segmented
                  value={labels}
                  onChange={onLabels}
                  label={t("visualization.labels_title")}
                  testId="visualization-labels"
                  options={[
                    { id: "hover", label: t("visualization.labels_hover") },
                    { id: "always", label: t("visualization.labels_always") },
                  ]}
                />
              </div>
            )}
          </HeaderPopover>
        </>
      )}
      <button
        type="button"
        onClick={onRefresh}
        disabled={loading}
        title={t("visualization.refresh")}
        aria-label={t("visualization.refresh")}
        data-testid="visualization-refresh"
        className={ICON_BUTTON}
      >
        {loading ? <Loader2 className="animate-spin" aria-hidden /> : <RefreshCw aria-hidden />}
      </button>
    </header>
  );
}

/** The library's tabs: two picks, four kinds, and everything. */
export function LibraryTabs({
  filter,
  counts,
  loading,
  onChange,
}: {
  filter: RailFilter;
  counts: Record<RailFilter, number>;
  /** No answer yet — counts are left out rather than shown as zeros. */
  loading: boolean;
  onChange: (next: RailFilter) => void;
}) {
  const t = useT();
  return (
    <nav
      aria-label={t("visualization.rail_filter")}
      className="flex shrink-0 flex-wrap items-center gap-1 px-8 pb-2 pt-5"
      data-testid="visualization-filter"
    >
      {RAIL_FILTERS.map((id) => {
        const active = filter === id;
        return (
          <button
            key={id}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(id)}
            data-testid={`visualization-filter-${id}`}
            className={cn(
              "inline-flex h-9 items-center gap-2 rounded-full px-4 text-base font-medium transition-colors",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              active
                ? "bg-secondary text-foreground-strong"
                : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
            )}
          >
            {t(`visualization.filter_${id}`)}
            {!loading && (
              <span
                className={cn(
                  "text-sm tabular-nums",
                  active ? "text-muted-foreground" : "text-foreground-faint",
                )}
              >
                {counts[id]}
              </span>
            )}
          </button>
        );
      })}
    </nav>
  );
}

/* ------------------------------------------------------------------------- */

interface CardHandlers {
  onOpen: (row: RailRow) => void;
  onMenu: (row: RailRow, x: number, y: number) => void;
  onDeleteKey: (row: RailRow) => void;
  onToggleFavorite: (key: string) => void;
}

/** The library itself — the wall, or the same cards as a list. */
export function ArtifactGallery({
  rows,
  groups,
  view,
  size,
  labels,
  feature,
  favorites,
  onToggleFavorite,
  loading,
  empty: emptyReason,
  footer,
  onOpen,
}: {
  /** Every card, in the order it appears on screen. */
  rows: RailRow[];
  /** The same cards under their date headings — what the list is cut by. */
  groups: GalleryGroup[];
  view: GalleryView;
  size: TileSize;
  labels: TileLabels;
  /** Give the wall's first artifact a tile of four. */
  feature: boolean;
  favorites: ReadonlySet<string>;
  onToggleFavorite: (key: string) => void;
  loading: boolean;
  /** Why the wall would be empty: a search, the favourites tab, or a kind. */
  empty: "search" | "favorites" | "category";
  footer?: ReactNode;
  onOpen: (row: RailRow) => void;
}) {
  const t = useT();
  const actions = useCardActions();
  const nothing = rows.length === 0;
  const handlers: CardHandlers = {
    onOpen,
    onMenu: actions.openMenu,
    onDeleteKey: actions.askDelete,
    onToggleFavorite,
  };

  return (
    <ScrollArea className="min-h-0 flex-1">
      <div className="w-full px-8 pb-12 pt-3" data-testid="visualization-artifacts">
        {loading && nothing ? (
          <SkeletonWall />
        ) : nothing ? (
          <div className="flex min-h-80 items-center justify-center" data-testid="visualization-no-matches">
            <EmptyState
              icon={emptyReason === "favorites" ? <Star aria-hidden /> : <Search aria-hidden />}
              title={t(`visualization.${EMPTY_KEYS[emptyReason]}_title`)}
              description={t(`visualization.${EMPTY_KEYS[emptyReason]}_body`)}
            />
          </div>
        ) : view === "list" ? (
          <ArtifactList groups={groups} favorites={favorites} handlers={handlers} />
        ) : (
          <ArtifactWall
            rows={rows}
            size={size}
            labels={labels}
            feature={feature}
            favorites={favorites}
            handlers={handlers}
          />
        )}
        {footer}
      </div>
      {actions.menu && (
        <ArtifactCardMenu
          row={actions.menu.row}
          x={actions.menu.x}
          y={actions.menu.y}
          canReveal={actions.canReveal}
          favorite={favorites.has(actions.menu.row.key)}
          onDismiss={actions.closeMenu}
          onOpen={() => actions.run(onOpen)}
          onToggleFavorite={() => actions.run((row) => onToggleFavorite(row.key))}
          onOpenExternal={() => actions.run(actions.openExternal)}
          onDownload={() => actions.run(actions.download)}
          onReveal={() => actions.run(actions.reveal)}
          onDelete={() => actions.run(actions.askDelete)}
        />
      )}
      {actions.pendingDelete && (
        <ConfirmDeleteArtifact
          row={actions.pendingDelete}
          busy={actions.deleting}
          onCancel={actions.cancelDelete}
          onConfirm={() => void actions.confirmDelete()}
        />
      )}
    </ScrollArea>
  );
}

const EMPTY_KEYS = {
  search: "no_matches",
  favorites: "favorites_empty",
  category: "category_empty",
} as const;

/**
 * What a card's menu does. One menu and one pending delete for the whole
 * library — the card only reports where it was clicked.
 */
function useCardActions() {
  const t = useT();
  const theme = useThemeValue();
  const queryClient = useQueryClient();
  const pushToast = useEventStore((s) => s.pushToast);
  const capabilities = useOutputsCapabilities();
  const [menu, setMenu] = useState<ArtifactMenuState | null>(null);
  const [pendingDelete, setPendingDelete] = useState<RailRow | null>(null);
  const [deleting, setDeleting] = useState(false);

  const openMenu = useCallback((row: RailRow, x: number, y: number) => setMenu({ row, x, y }), []);
  const closeMenu = useCallback(() => setMenu(null), []);

  /** Close the menu, then act on the row it was opened for. */
  const run = useCallback(
    (action: (row: RailRow) => void) => {
      if (!menu) return;
      setMenu(null);
      action(menu.row);
    },
    [menu],
  );

  const openExternal = useCallback(
    (row: RailRow) => {
      if (row.kind !== "visual") return;
      const { visual } = row;
      const url =
        visual.kind === "page" ? `${artifactPageUrl(visual.slug, visual.path)}?theme=${theme}` : visual.url;
      void openExternalUrl(`${window.location.origin}${url}`);
    },
    [theme],
  );

  const download = useCallback((row: RailRow) => {
    if (row.kind !== "visual") return;
    const link = document.createElement("a");
    link.href = artifactDownloadUrl(row.visual.slug, row.visual.path);
    link.download = row.visual.name;
    document.body.appendChild(link);
    link.click();
    link.remove();
  }, []);

  const reveal = useCallback(
    (row: RailRow) => {
      const request =
        row.kind === "visual"
          ? revealArtifact(row.visual.slug, row.visual.path)
          : revealOutput(row.run.slug);
      request.catch(() => pushToast("error", t("visualization.reveal_failed")));
    },
    [pushToast, t],
  );

  const askDelete = useCallback((row: RailRow) => {
    if (!rowIsWorking(row)) setPendingDelete(row);
  }, []);
  const cancelDelete = useCallback(() => {
    if (!deleting) setPendingDelete(null);
  }, [deleting]);

  const confirmDelete = useCallback(async () => {
    const row = pendingDelete;
    if (!row || row.kind === "build") return;
    const slug = row.kind === "visual" ? row.visual.slug : row.run.slug;
    setDeleting(true);
    try {
      await deleteOutput(slug, row.kind === "visual" ? row.visual.path : null);
      setPendingDelete(null);
      pushToast("success", t("visualization.deleted"));
    } catch (error) {
      const running = error instanceof DeleteOutputError && error.status === 409;
      pushToast("error", t(running ? "visualization.delete_running" : "visualization.delete_failed"));
    } finally {
      setDeleting(false);
      void queryClient.invalidateQueries({ queryKey: ["outputs"] });
      void queryClient.invalidateQueries({ queryKey: ["output-artifacts", slug] });
    }
  }, [pendingDelete, pushToast, queryClient, t]);

  return {
    menu,
    openMenu,
    closeMenu,
    run,
    canReveal: capabilities.data?.native_file_actions === true,
    openExternal,
    download,
    reveal,
    pendingDelete,
    deleting,
    askDelete,
    cancelDelete,
    confirmDelete,
  };
}

/** What a card shares between the wall and the list: its keys and its drag. */
function useCardInteractions(row: RailRow, handlers: CardHandlers) {
  // Every card can be dragged onto the Jarvis dock — the run is what the dock
  // takes, whichever of its artifacts the card happens to show.
  const dragRun = row.run;
  const dragProps = dragRun
    ? {
        draggable: true,
        onDragStart: (event: DragEvent) => startMissionDrag(event, dragRun),
        onDragEnd: endMissionDrag,
      }
    : {};

  const onContextMenu = (event: ReactMouseEvent<HTMLElement>) => {
    // The app-wide Cut/Copy/Paste menu lives on document; a card offers its
    // own actions instead. The menu key reports no pointer, so the menu then
    // opens at the card's corner.
    event.preventDefault();
    event.stopPropagation();
    if (event.clientX === 0 && event.clientY === 0) {
      const box = event.currentTarget.getBoundingClientRect();
      handlers.onMenu(row, box.left + 16, box.top + 16);
    } else {
      handlers.onMenu(row, event.clientX, event.clientY);
    }
  };

  const onKeyDown = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    if (event.key === "Delete") {
      event.preventDefault();
      handlers.onDeleteKey(row);
    } else if (event.key === "f" || event.key === "F") {
      event.preventDefault();
      handlers.onToggleFavorite(row.key);
    }
  };

  /** The "…" button: the same menu, opened under the button. */
  const onMore = (event: ReactMouseEvent<HTMLElement>) => {
    event.stopPropagation();
    const box = event.currentTarget.getBoundingClientRect();
    handlers.onMenu(row, box.left, box.bottom + 6);
  };

  return { dragProps, onContextMenu, onKeyDown, onMore };
}

/* ------------------------------------------------------------------------- */

/** The wall: tiles of three shapes, each in the column that is shortest. */
function ArtifactWall({
  rows,
  size,
  labels,
  feature,
  favorites,
  handlers,
}: {
  rows: RailRow[];
  size: TileSize;
  labels: TileLabels;
  feature: boolean;
  favorites: ReadonlySet<string>;
  handlers: CardHandlers;
}) {
  const box = useRef<HTMLDivElement>(null);
  const { width } = useBoxSize(box);
  const ratios = useImageRatios();
  const columns = wallColumns(width, TILE_MINIMUM[size], WALL_GAP);

  // The newest page or picture leads as a tile of four — when there is room
  // for it to lead something.
  const lead = feature && columns >= 3 && rows.length >= 4 ? featureIndex(rows) : -1;
  const shapes = rows.map(
    (row, index): TileShape => (index === lead ? "feature" : tileShape(row, ratios.get(row.key))),
  );
  const shapeKey = shapes.join(",");
  const layout = useMemo(
    () => (width > 0 ? layoutWall(shapes, width, columns, WALL_GAP) : null),
    // `shapes` is rebuilt every render; its joined form is what changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [shapeKey, width, columns],
  );

  // One container either way, so what measures it keeps measuring it. Before
  // the wall knows its width (and in a DOM without layout) the tiles are a
  // plain grid of squares — every card is there from the first paint.
  return (
    <div
      ref={box}
      className={
        layout ? "relative w-full" : "grid grid-cols-[repeat(auto-fill,minmax(14rem,1fr))] gap-4"
      }
      style={layout ? { height: layout.height } : undefined}
    >
      {rows.map((row, index) => {
        const place = layout?.boxes[index];
        return (
          <div
            key={row.key}
            className={
              place
                ? "absolute left-0 top-0 transition-[transform,width,height] duration-500 ease-out motion-reduce:transition-none"
                : "relative aspect-square"
            }
            style={
              place && {
                width: place.width,
                height: place.height,
                transform: `translate3d(${place.x}px, ${place.y}px, 0)`,
              }
            }
          >
            <div
              className="h-full w-full animate-in fade-in-0 zoom-in-95 fill-mode-both duration-500 motion-reduce:animate-none"
              style={{ animationDelay: `${Math.min(index, 14) * 28}ms` }}
            >
              <WallTile
                row={row}
                labels={labels}
                short={place !== undefined && shapes[index] === "wide"}
                favorite={favorites.has(row.key)}
                handlers={handlers}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function SkeletonWall() {
  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(14rem,1fr))] gap-4" aria-hidden>
      {Array.from({ length: 10 }, (_, index) => (
        <div
          key={index}
          className="aspect-square animate-pulse rounded-2xl bg-foreground/[0.06]"
          style={{ animationDelay: `${index * 90}ms` }}
        />
      ))}
    </div>
  );
}

/** The round buttons that sit on a tile's corner. */
const TILE_BUTTON =
  "inline-flex h-8 w-8 items-center justify-center rounded-full transition-[background-color,color,transform] " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring active:scale-95 [&_svg]:h-4 [&_svg]:w-4";

/** One tile: the cover, and over it a caption, a star, a menu and a status. */
function WallTile({
  row,
  labels,
  short,
  favorite,
  handlers,
}: {
  row: RailRow;
  labels: TileLabels;
  /** A half-height tile: its caption is one line, so the picture keeps the rest. */
  short: boolean;
  favorite: boolean;
  handlers: CardHandlers;
}) {
  const t = useT();
  const language = useUiLanguage();
  const title = rowTitle(row);
  const status = rowStatus(row);
  const { dragProps, onContextMenu, onKeyDown, onMore } = useCardInteractions(row, handlers);
  // A cover drawn by the artifact (a page, a picture) is imagery: what sits on
  // it is light on a dark veil in both themes. A note is app surface.
  const imagery = row.kind === "visual";
  const meta = [kindLabel(row, t), relativeWhen(rowWhen(row), Date.now(), language)]
    .filter(Boolean)
    .join(" · ");

  // The pointer has to rest before a page starts to scroll — passing over the
  // wall must not set a dozen pages moving.
  const [peek, setPeek] = useState(false);
  const peekTimer = useRef<number | null>(null);
  const stopPeek = useCallback(() => {
    if (peekTimer.current !== null) window.clearTimeout(peekTimer.current);
    peekTimer.current = null;
    setPeek(false);
  }, []);
  useEffect(() => stopPeek, [stopPeek]);

  const overTile = imagery
    ? "bg-black/55 text-white backdrop-blur-md hover:bg-black/75"
    : "bg-secondary text-muted-foreground hover:bg-border hover:text-foreground";
  const revealed =
    "opacity-0 transition-opacity duration-200 group-hover/tile:opacity-100 group-focus-within/tile:opacity-100";

  return (
    <div
      className="group/tile relative h-full w-full"
      onPointerEnter={(event) => {
        if (event.pointerType === "touch") return;
        peekTimer.current = window.setTimeout(() => setPeek(true), PEEK_DELAY_MS);
      }}
      onPointerLeave={stopPeek}
    >
      <button
        type="button"
        onClick={() => handlers.onOpen(row)}
        onContextMenu={onContextMenu}
        onKeyDown={onKeyDown}
        aria-label={title}
        data-testid={ROW_TESTID[row.kind]}
        data-kind={row.kind === "visual" ? row.visual.kind : undefined}
        data-status={row.kind === "run" ? status : undefined}
        className={cn(
          "absolute inset-0 overflow-hidden rounded-2xl border border-border bg-card text-left",
          "transition-[border-color,box-shadow] duration-200",
          "hover:border-border-strong hover:shadow-float",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        )}
        {...dragProps}
      >
        <TileCover row={row} peek={peek} />
        {imagery && (
          <span
            className={cn(
              // A pane of dark glass, so the name reads on any page or picture.
              "pointer-events-none absolute inset-x-2 bottom-2 flex flex-col gap-0.5 rounded-xl px-3",
              "bg-black/70 backdrop-blur-md",
              short ? "py-1.5" : "py-2.5",
              labels === "hover" &&
                "translate-y-1 opacity-0 transition-[opacity,transform] duration-200 group-hover/tile:translate-y-0 group-hover/tile:opacity-100 group-focus-within/tile:translate-y-0 group-focus-within/tile:opacity-100",
            )}
            data-testid="artifact-tile-caption"
          >
            <span
              className={cn(
                "text-base font-semibold leading-snug text-white [overflow-wrap:anywhere]",
                short ? "line-clamp-1" : "line-clamp-2",
              )}
            >
              {title}
            </span>
            {!short && <span className="truncate text-sm text-white/70">{meta}</span>}
          </span>
        )}
      </button>

      {status !== "success" && status !== "unknown" && row.kind === "visual" && (
        <span className="pointer-events-none absolute left-3 top-3 inline-flex items-center gap-1.5 rounded-full bg-black/60 px-2.5 py-1 text-sm text-white backdrop-blur-md">
          <span className={cn("h-1.5 w-1.5 rounded-full", STATUS_DOT[status])} aria-hidden />
          {t(`visualization.status_word_${status}`)}
        </span>
      )}

      <div className="absolute right-2.5 top-2.5 flex items-center gap-1.5">
        <button
          type="button"
          aria-pressed={favorite}
          aria-label={t(favorite ? "visualization.favorite_remove" : "visualization.favorite_add")}
          title={t(favorite ? "visualization.favorite_remove" : "visualization.favorite_add")}
          onClick={() => handlers.onToggleFavorite(row.key)}
          data-testid="artifact-favorite"
          className={cn(TILE_BUTTON, overTile, !favorite && revealed)}
        >
          <Star className={cn(favorite && "fill-current text-warning")} aria-hidden />
        </button>
        <button
          type="button"
          aria-haspopup="menu"
          aria-label={t("visualization.menu_aria")}
          title={t("visualization.menu_aria")}
          onClick={onMore}
          data-testid="artifact-more"
          className={cn(TILE_BUTTON, overTile, revealed)}
        >
          <Ellipsis aria-hidden />
        </button>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------------- */

/** The same cards as rows, under their date headings. */
function ArtifactList({
  groups,
  favorites,
  handlers,
}: {
  groups: GalleryGroup[];
  favorites: ReadonlySet<string>;
  handlers: CardHandlers;
}) {
  const t = useT();
  return (
    <div className="-mx-3 w-full max-w-6xl">
      {groups.map((group) => (
        <section key={group.id} aria-label={t(`visualization.group_${group.id}`)} className="pt-4">
          <h2 className="px-3 pb-1.5 text-sm font-medium text-foreground-faint">
            {t(`visualization.group_${group.id}`)}
          </h2>
          {group.rows.map((row) => (
            <ListRow key={row.key} row={row} favorite={favorites.has(row.key)} handlers={handlers} />
          ))}
        </section>
      ))}
    </div>
  );
}

function ListRow({
  row,
  favorite,
  handlers,
}: {
  row: RailRow;
  favorite: boolean;
  handlers: CardHandlers;
}) {
  const t = useT();
  const language = useUiLanguage();
  const title = rowTitle(row);
  const request = rowRequest(row);
  const status = rowStatus(row);
  const { dragProps, onContextMenu, onKeyDown, onMore } = useCardInteractions(row, handlers);
  const quiet =
    "opacity-0 transition-opacity group-hover/row:opacity-100 group-focus-within/row:opacity-100";

  return (
    <div className="group/row flex items-center gap-1 rounded-xl pr-2 transition-colors hover:bg-secondary/70 focus-within:bg-secondary/70">
      <button
        type="button"
        onClick={() => handlers.onOpen(row)}
        onContextMenu={onContextMenu}
        onKeyDown={onKeyDown}
        data-testid={ROW_TESTID[row.kind]}
        data-kind={row.kind === "visual" ? row.visual.kind : undefined}
        data-status={row.kind === "run" ? status : undefined}
        className="flex min-w-0 flex-1 items-center gap-4 rounded-xl px-3 py-2 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        {...dragProps}
      >
        <RowThumb row={row} />
        <span className="min-w-0 flex-1">
          <span className="flex min-w-0 items-center gap-2">
            <span className="truncate text-base font-medium text-foreground-strong">{title}</span>
            {status !== "success" && status !== "unknown" && row.kind !== "build" && (
              <span className="inline-flex shrink-0 items-center gap-1.5 text-sm text-muted-foreground">
                <span className={cn("h-1.5 w-1.5 rounded-full", STATUS_DOT[status])} aria-hidden />
                {t(`visualization.status_word_${status}`)}
              </span>
            )}
          </span>
          {request && request !== title && (
            <span className="block truncate text-sm text-foreground-faint">{request}</span>
          )}
        </span>
        <span className="hidden w-32 shrink-0 truncate text-sm text-muted-foreground md:block">
          {kindLabel(row, t)}
        </span>
        <span className="hidden w-28 shrink-0 truncate text-sm text-muted-foreground sm:block">
          {relativeWhen(rowWhen(row), Date.now(), language)}
        </span>
        <span className="hidden w-20 shrink-0 text-right text-sm tabular-nums text-foreground-faint lg:block">
          {row.kind === "visual" ? formatSize(row.visual.size) : ""}
        </span>
      </button>
      <button
        type="button"
        aria-pressed={favorite}
        aria-label={t(favorite ? "visualization.favorite_remove" : "visualization.favorite_add")}
        title={t(favorite ? "visualization.favorite_remove" : "visualization.favorite_add")}
        onClick={() => handlers.onToggleFavorite(row.key)}
        data-testid="artifact-favorite"
        className={cn(
          TILE_BUTTON,
          "text-muted-foreground hover:bg-border hover:text-foreground",
          !favorite && quiet,
        )}
      >
        <Star className={cn(favorite && "fill-current text-warning")} aria-hidden />
      </button>
      <button
        type="button"
        aria-haspopup="menu"
        aria-label={t("visualization.menu_aria")}
        title={t("visualization.menu_aria")}
        onClick={onMore}
        data-testid="artifact-more"
        className={cn(TILE_BUTTON, "text-muted-foreground hover:bg-border hover:text-foreground", quiet)}
      >
        <Ellipsis aria-hidden />
      </button>
    </div>
  );
}
