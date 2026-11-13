import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Loader2, Shapes, ShieldCheck, Star } from "lucide-react";

import { EmptyState } from "@/components/ui/empty-state";
import { OutputPreview } from "@/components/visualization/OutputPreview";
import { RunGraphPanel } from "@/components/visualization/RunGraphPanel";
import {
  RunActions,
  RunFiles,
  RunStatusBadge,
  deliverableFiles,
} from "@/components/visualization/RunPanels";
import {
  MenuChoice,
  MenuHeading,
  MenuItem,
  MenuSeparator,
  MoreMenu,
  ShareMenu,
  StageBar,
  TitlePill,
} from "@/components/visualization/ArtifactStageBar";
import {
  ArtifactGallery,
  GALLERY_VIEWS,
  LibraryHeader,
  LibraryTabs,
  TILE_LABELS,
  TILE_SIZES,
  type GalleryView,
  type TileLabels,
  type TileSize,
} from "@/components/visualization/ArtifactGallery";
import {
  RAIL_FILTERS,
  buildRailRows,
  countByFilter,
  filterRailRows,
  groupRailRows,
  parseArtifactUtterance,
  runTitle,
  runWhen,
  searchRailRows,
  sortRailRows,
  type GallerySort,
  type RailFilter,
  type RailRow,
} from "@/components/visualization/galleryModel";
import { useT } from "@/i18n";
import { useArtifactFavorites } from "@/hooks/useArtifactFavorites";
import { useFramedPageLinks } from "@/hooks/useFramedPageLinks";
import { useThemeValue } from "@/hooks/useTheme";
import { artifactKind, isTextKind } from "@/lib/artifactKind";
import { CapacityDecisionPanel } from "@/components/missions/CapacityDecisionPanel";
import { isLivingSlug } from "@/components/visualization/livingPage";
import { cleanRequest } from "@/lib/runRequest";
import { useEventStore } from "@/store/events";
import { openExternalUrl } from "@/lib/openExternal";
import {
  artifactDownloadUrl,
  artifactOpenUrl,
  revealArtifact,
  useArtifactFile,
  useArtifactsForOutput,
  useOutputsCapabilities,
  useOutputsList,
  type ArtifactSummary,
  type OutputSummary,
} from "@/hooks/useOutputs";
import {
  artifactPageUrl,
  missionMapUrl,
  toVisuals,
  useVisualArtifacts,
  visualId,
  type VisualArtifact,
} from "@/hooks/useVisualArtifacts";

export { buildRailRows, filterRailRows, parseArtifactUtterance };
export type { RailFilter };

// Only a living page needs its refresh strip; load it when one is open.
const LivingPageBar = lazy(() => import("@/components/visualization/LivingPageBar"));

/**
 * The Artifacts section — everything a run produced, as a library first and
 * a stage second.
 *
 * An artifact is the thing the user asked to LOOK AT: the dashboard, the
 * report, the diagram a background agent wrote as one self-contained HTML
 * file (`create_artifact`), or any image/PDF a worker left behind. The
 * section opens on a WALL: every artifact as a tile with the artifact itself
 * drawn on it edge to edge (a live, scaled page that scrolls itself under a
 * resting pointer; the picture; a PDF's first sheet), narrowed by a row of
 * tabs — Suggested, Favorites, the four kinds, All — and by search, sorted
 * newest, oldest or by name, and drawn as a list instead when the reader
 * wants names rather than pictures. A click opens the STAGE: the page
 * full-size in its sandbox, the source one tab away, every file of the run
 * behind "Files", and the run graph behind "Run"; back, previous and next
 * walk the same list.
 *
 * Every other run lands here too (the Outputs section folded in on
 * 2026-08-23): a run that drew no page or picture is an "Output" card with
 * its own answer as the cover, and its stage composes a page from what it
 * left behind (`OutputPreview`).
 *
 * It owns no data: runs come from `/api/outputs`, files from the artifact
 * listing (`useVisualArtifacts`, `useArtifactsForOutput`), a page's source
 * from `/raw`. A run that is still building its artifact shows as a
 * "building…" card the gallery follows until the page lands — the listings
 * of running runs poll, nothing else does.
 *
 * Detachable (`DETACHABLE_VIEWS` in dodaios/ui/desktop_app.py): an artifact is
 * the thing people put on a second monitor.
 */

type StageMode = "preview" | "code" | "files" | "run";

/**
 * What is open: an artifact (`path`) or a whole run (`null`), "latest" for
 * whatever leads the library (another surface asked for the newest), or
 * nothing — the gallery.
 */
type Selection = { slug: string; path: string | null } | "latest" | null;

/** What the stage shows: a run (always), and its artifact when it has one. */
interface StageTarget {
  run: OutputSummary | null;
  visual: VisualArtifact | null;
  /** The run is a `create_artifact` build still writing its page. */
  building: boolean;
}

const FILTER_KEY = "jarvis.artifacts.rail-filter";
const SORT_KEY = "jarvis.artifacts.sort";
const VIEW_KEY = "jarvis.artifacts.view";
const SIZE_KEY = "jarvis.artifacts.tile-size";
const LABELS_KEY = "jarvis.artifacts.tile-labels";

function readStored<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const stored = window.localStorage.getItem(key);
    if (stored !== null && (allowed as readonly string[]).includes(stored)) return stored as T;
  } catch {
    // Storage can be unavailable (private window, blocked site data) — the default then.
  }
  return fallback;
}

function store(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // A remembered category or order is a convenience, never a requirement.
  }
}

const SORTS: readonly GallerySort[] = ["newest", "oldest", "name"];

/** The stage's timestamp — what tells two same-named artifacts apart. */
function formatWhen(seconds: number): string {
  if (!seconds) return "";
  return new Date(seconds * 1000).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** The card's key for what the stage shows. */
function stageKey(target: StageTarget): string | null {
  if (target.building && target.run) return `build:${target.run.slug}`;
  if (target.visual) return visualId(target.visual);
  if (target.run) return `run:${target.run.slug}`;
  return null;
}

function selectionOf(row: RailRow): { slug: string; path: string | null } {
  return row.kind === "visual"
    ? { slug: row.visual.slug, path: row.visual.path }
    : { slug: row.run.slug, path: null };
}

/** A choice the reader made once and expects to find again. */
function useStoredChoice<T extends string>(
  key: string,
  allowed: readonly T[],
  fallback: T,
): [T, (next: T) => void] {
  const [value, setValue] = useState<T>(() => readStored(key, allowed, fallback));
  const choose = useCallback(
    (next: T) => {
      setValue(next);
      store(key, next);
    },
    [key],
  );
  return [value, choose];
}

/** A key press that belongs to a text field, not to the gallery's navigation. */
function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return (
    target.isContentEditable ||
    target.tagName === "INPUT" ||
    target.tagName === "TEXTAREA" ||
    target.tagName === "SELECT"
  );
}

export function VisualizationView() {
  const t = useT();
  const outputs = useOutputsList();
  const runs = useMemo(() => outputs.data ?? [], [outputs.data]);
  const gallery = useVisualArtifacts();
  const visuals = gallery.visuals;

  /* Runs still writing their artifact — recognised by the brief's lead line,
   * so an unrelated running mission does not pose as a page in the making. */
  const building = useMemo(
    () =>
      runs.filter(
        (run) => run.status === "running" && parseArtifactUtterance(run.utterance) !== null,
      ),
    [runs],
  );

  const allRows = useMemo(() => buildRailRows(runs, visuals, building), [runs, visuals, building]);
  const { favorites, toggle: toggleFavorite } = useArtifactFavorites();
  /* What the two pick tabs go by. The clock is read when the library or the
   * stars change — "new this week" does not need to tick. */
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const picks = useMemo(() => ({ favorites, now: Date.now() }), [favorites, allRows]);
  const counts = useMemo(() => countByFilter(allRows, picks), [allRows, picks]);

  const [filter, setFilter] = useStoredChoice<RailFilter>(FILTER_KEY, RAIL_FILTERS, "suggested");
  const [sort, setSort] = useStoredChoice<GallerySort>(SORT_KEY, SORTS, "newest");
  const [view, setView] = useStoredChoice<GalleryView>(VIEW_KEY, GALLERY_VIEWS, "wall");
  const [size, setSize] = useStoredChoice<TileSize>(SIZE_KEY, TILE_SIZES, "m");
  const [labels, setLabels] = useStoredChoice<TileLabels>(LABELS_KEY, TILE_LABELS, "hover");
  const [query, setQuery] = useState("");

  /* The library as shown: tab, then search, then order. The stage's
   * previous / next walk exactly this list. */
  const rows = useMemo(
    () => sortRailRows(searchRailRows(filterRailRows(allRows, filter, picks), query), sort),
    [allRows, filter, picks, query, sort],
  );
  const groups = useMemo(() => groupRailRows(rows, sort, Date.now()), [rows, sort]);
  /* The order the cards appear in on screen — groups pull work in progress
   * to the top, so this is not always `rows`. */
  const ordered = useMemo(() => groups.flatMap((group) => group.rows), [groups]);

  /* A `?run=<slug>` in the URL opens that run's newest artifact (or the one
   * `&artifact=` names) — what makes a detached window or a pasted link open
   * on the page it talks about. Read once at mount; clicks own it after. */
  const [selection, setSelection] = useState<Selection>(() => {
    const params = new URLSearchParams(window.location.search);
    const slug = params.get("run");
    // `&artifact=<path>` names one file of the run — what the stage's
    // "Copy link" writes, so the link opens exactly that artifact.
    return slug ? { slug, path: params.get("artifact") || null } : null;
  });

  /*
   * Another surface asked for something to be staged ("show visuals" on the
   * agent strip, the `create_artifact` tool via NavigateSidebar). A target
   * names a `visualId` (slug::path) or "latest"; see VisualStageRequest.
   */
  const visualStage = useEventStore((s) => s.visualStage);
  useEffect(() => {
    if (visualStage === null) return;
    if (visualStage.target === "latest") {
      setSelection("latest");
      return;
    }
    const separator = visualStage.target.indexOf("::");
    if (separator > 0) {
      setSelection({
        slug: visualStage.target.slice(0, separator),
        path: visualStage.target.slice(separator + 2),
      });
    }
  }, [visualStage]);

  /*
   * What the stage shows. The card the user opened — an artifact, or a run
   * (its newest artifact once it has one, the run itself otherwise). For
   * "latest", whatever leads the whole library: the newest build in
   * progress, else the newest thing there is.
   */
  const target: StageTarget | null = useMemo(() => {
    if (selection === null) return null;
    const bySlug = (slug: string) => runs.find((r) => r.slug === slug) ?? null;
    if (selection === "latest") {
      const first = allRows[0];
      if (!first) return { run: null, visual: null, building: false };
      if (first.kind === "build") return { run: first.run, visual: null, building: true };
      if (first.kind === "visual") return { run: first.run, visual: first.visual, building: false };
      return { run: first.run, visual: null, building: false };
    }
    if (selection.path !== null) {
      const visual = visuals.find((v) => v.slug === selection.slug && v.path === selection.path);
      if (visual) return { run: bySlug(visual.slug), visual, building: false };
    }
    const run = bySlug(selection.slug);
    const visual = visuals.find((v) => v.slug === selection.slug) ?? null;
    if (run === null && visual === null) return { run: null, visual: null, building: false };
    const isBuilding = run !== null && building.includes(run) && visual === null;
    return { run, visual, building: isBuilding };
  }, [selection, runs, visuals, building, allRows]);

  const refetch = useCallback(() => {
    void outputs.refetch();
    gallery.refetch();
  }, [outputs, gallery]);

  const open = useCallback((row: RailRow) => setSelection(selectionOf(row)), []);
  const back = useCallback(() => setSelection(null), []);

  /* Previous / next: the stage's place in the library as currently shown.
   * Opened from elsewhere (a link, "latest") and not in the current view,
   * the stage simply has no neighbours. */
  const activeKey = target ? stageKey(target) : null;
  const position = activeKey ? ordered.findIndex((row) => row.key === activeKey) : -1;
  const step = useCallback(
    (delta: number) => {
      if (position < 0) return;
      const next = ordered[position + delta];
      if (next) setSelection(selectionOf(next));
    },
    [ordered, position],
  );

  /* Escape goes back to the library, ←/→ walk it — unless a text field has
   * the keys. A framed page keeps its own keys (its events never reach us). */
  const staged = target !== null;
  useEffect(() => {
    if (!staged) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || isTypingTarget(event.target)) return;
      if (event.altKey || event.ctrlKey || event.metaKey) return;
      if (event.key === "Escape") back();
      else if (event.key === "ArrowLeft") step(-1);
      else if (event.key === "ArrowRight") step(1);
      else return;
      event.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [staged, back, step]);

  const loading = outputs.isLoading || gallery.isLoading;
  const error = outputs.isError || gallery.isError;

  if (target !== null) {
    return (
      <div className="flex h-full min-h-0 flex-col">
        <section className="flex min-h-0 min-w-0 flex-1 flex-col">
          {target.building && target.run !== null ? (
            <>
              <StageBar onClose={back} />
              <RunCapacityDecision run={target.run} />
              <BuildingStage run={target.run} />
            </>
          ) : target.run === null && target.visual === null ? (
            <>
              <StageBar onClose={back} />
              <EmptyStage loading={loading} error={error} />
            </>
          ) : (
            <Stage
              key={target.run?.slug ?? target.visual?.slug}
              run={target.run}
              visual={target.visual}
              onJumpToRun={(slug) => setSelection({ slug, path: null })}
              nav={{ onBack: back, position, total: ordered.length, onStep: step }}
            />
          )}
        </section>
      </div>
    );
  }

  const nothingAtAll = !loading && allRows.length === 0;
  const searching = query.trim().length > 0;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <LibraryHeader
        query={query}
        onQuery={setQuery}
        sort={sort}
        onSort={setSort}
        view={view}
        onView={setView}
        size={size}
        onSize={setSize}
        labels={labels}
        onLabels={setLabels}
        loading={loading}
        onRefresh={refetch}
        bare={nothingAtAll}
      />
      {nothingAtAll ? (
        <EmptyStage loading={false} error={error} />
      ) : (
        <>
          <LibraryTabs
            filter={filter}
            counts={counts}
            loading={loading && allRows.length === 0}
            onChange={setFilter}
          />
          <ArtifactGallery
            rows={ordered}
            groups={groups}
            view={view}
            size={size}
            labels={labels}
            // The newest artifact leads the pick — not a search result, not
            // an alphabetical list, where "first" means nothing.
            feature={filter === "suggested" && !searching && sort === "newest"}
            favorites={favorites}
            onToggleFavorite={toggleFavorite}
            loading={loading}
            empty={searching ? "search" : filter === "favorites" ? "favorites" : "category"}
            onOpen={open}
            footer={
              gallery.skippedRuns > 0 ? (
                <p className="pt-8 text-sm text-foreground-faint">
                  {t("visualization.older_not_scanned").replace("{0}", String(gallery.scannedRuns))}
                </p>
              ) : null
            }
          />
        </>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------------- */

/** What the stage needs to know about its place in the library. */
interface StageNavigation {
  onBack: () => void;
  /** Index in the library as shown, or -1 when the open item is not in it. */
  position: number;
  total: number;
  onStep: (delta: number) => void;
}

/* ------------------------------------------------------------------------- */

/**
 * The stage for one run: its artifact under Preview / Code when it drew one,
 * the composed output page under Preview and the primary file's source under
 * Code when it did not; every file under Files, the graph under Run. Keyed
 * by run in the caller, so a new run opens on Preview.
 *
 * A run outside the rail's scan window arrives without artifacts in hand; its
 * listing is read here (same cache entry the rail's scan fills) and the newest
 * page or picture in it goes on stage — an older dashboard is one click away
 * instead of "not scanned".
 */
function Stage({
  run,
  visual: pickedVisual,
  onJumpToRun,
  nav,
}: {
  run: OutputSummary | null;
  visual: VisualArtifact | null;
  onJumpToRun: (slug: string) => void;
  /** Back to the library and previous / next — the ends of the stage's bar. */
  nav: StageNavigation;
}) {
  const slug = run?.slug ?? pickedVisual?.slug ?? null;
  const listing = useArtifactsForOutput(run !== null ? slug : null);
  const visual: VisualArtifact | null = useMemo(() => {
    if (pickedVisual) return pickedVisual;
    if (run === null) return null;
    const found = toVisuals(run, listing.data?.files ?? []);
    found.sort((a, b) => b.mtime - a.mtime);
    return found[0] ?? null;
  }, [pickedVisual, run, listing.data]);
  // The output's primary file — what Code shows and the toolbar's file
  // actions act on when the run drew no page: the first text deliverable.
  const primary: ArtifactSummary | null = useMemo(() => {
    if (visual !== null) return null;
    return primaryTextFile(listing.data?.files ?? []);
  }, [visual, listing.data]);

  const [mode, setMode] = useState<StageMode>("preview");
  // "Open in Files" on the output page lands the reader on that file.
  const [filesPath, setFilesPath] = useState<string | null>(null);
  const currentId = visual ? visualId(visual) : null;
  // A new artifact opens on its page, whatever tab the previous one was on; a
  // run that turns out to have one (its listing just arrived) moves to it too.
  useEffect(() => {
    setMode("preview");
  }, [currentId]);
  const openFile = useCallback((path: string) => {
    setFilesPath(path);
    setMode("files");
  }, []);

  return (
    <>
      <ArtifactToolbar
        run={run}
        visual={visual}
        primary={primary}
        mode={mode}
        onMode={setMode}
        onJumpToRun={onJumpToRun}
        nav={nav}
      />
      {run && <RunCapacityDecision run={run} />}
      <div className="min-h-0 flex-1" data-testid="visualization-stage">
        {mode === "preview" && visual && <ArtifactStage visual={visual} />}
        {mode === "preview" && !visual && run && (
          <OutputPreview key={run.slug} run={run} onOpenFile={openFile} />
        )}
        {mode === "code" && visual && <ArtifactSource slug={visual.slug} path={visual.path} />}
        {mode === "code" && !visual && run && primary && (
          <ArtifactSource slug={run.slug} path={primary.path} />
        )}
        {mode === "files" && run && <RunFiles run={run} initialPath={filesPath} />}
        {mode === "run" && run && <RunGraphPanel key={run.slug} run={run} />}
      </div>
    </>
  );
}

/** The `/view` page follows the app's theme like an artifact page does. */
function withTheme(url: string | null, theme: string): string | null {
  if (url === null) return null;
  return url.includes("?") ? url : `${url}?theme=${theme}`;
}

/** The first deliverable whose bytes are text — the output's "source". */
function primaryTextFile(files: ArtifactSummary[]): ArtifactSummary | null {
  return (
    deliverableFiles(files).find((f) => isTextKind(artifactKind(f.path, f.is_text))) ?? null
  );
}

function ArtifactToolbar({
  run,
  visual,
  primary,
  mode,
  onMode,
  onJumpToRun,
  nav,
}: {
  run: OutputSummary | null;
  visual: VisualArtifact | null;
  /** The output's primary text file when the run drew no page. */
  primary: ArtifactSummary | null;
  mode: StageMode;
  onMode: (mode: StageMode) => void;
  onJumpToRun: (slug: string) => void;
  nav: StageNavigation;
}) {
  const t = useT();
  const { favorites, toggle: toggleFavorite } = useArtifactFavorites();
  // The same key the library's card carries, so a star set here shows there.
  const favoriteKey = visual ? visualId(visual) : run ? `run:${run.slug}` : null;
  const favorite = favoriteKey !== null && favorites.has(favoriteKey);
  const pushToast = useEventStore((s) => s.pushToast);
  const capabilities = useOutputsCapabilities();
  const parsed = parseArtifactUtterance(visual?.utterance ?? run?.utterance);
  const slug = visual?.slug ?? run?.slug ?? "";
  // The file the toolbar's Download / Reveal / Open act on: the artifact, or
  // the output's primary file.
  const file: { slug: string; path: string } | null = visual
    ? { slug: visual.slug, path: visual.path }
    : run && primary
      ? { slug: run.slug, path: primary.path }
      : null;

  const onReveal = useCallback(async () => {
    if (!file) return;
    try {
      await revealArtifact(file.slug, file.path);
    } catch {
      pushToast("error", t("visualization.reveal_failed"));
    }
  }, [file, pushToast, t]);

  const theme = useThemeValue();
  const externalUrl = visual
    ? visual.kind === "page"
      ? `${artifactPageUrl(visual.slug, visual.path)}?theme=${theme}`
      : visual.url
    : file
      ? withTheme(artifactOpenUrl(file.slug, file.path), theme)
      : null;

  const title = visual?.title ?? (run ? runTitle(run) : "");
  // When and how big — the request is not repeated: it usually IS the title.
  const request =
    parsed?.request ||
    (visual ? cleanRequest(visual.utterance) : run ? cleanRequest(run.utterance) : "");
  const details = [
    visual ? formatWhen(visual.mtime) : run ? formatWhen(runWhen(run)) : "",
    visual ? formatSize(visual.size) : "",
    run && typeof run.duration_s === "number" ? `${run.duration_s.toFixed(1)} s` : "",
    request && request !== title ? request : "",
  ]
    .filter(Boolean)
    .join(" · ");

  // Every run has the same views; Code is absent only when there is no
  // source to show (a picture, a run that left no text file).
  const views: Array<{ id: StageMode; label: string; show: boolean }> = [
    { id: "preview", label: t("visualization.tab_preview"), show: visual !== null || run !== null },
    {
      id: "code",
      label: t("visualization.tab_code"),
      show: visual !== null ? visual.kind === "page" || visual.kind === "vector" : primary !== null,
    },
    { id: "files", label: t("visualization.tab_files"), show: run !== null },
    { id: "run", label: t("visualization.tab_run"), show: run !== null },
  ];
  const shownViews = views.filter((view) => view.show);
  const modeLabel = mode === "preview" ? undefined : views.find((view) => view.id === mode)?.label;
  // A run that simply succeeded says nothing; anything else is worth a word.
  const showStatus = run !== null && (run.status ?? "unknown") !== "success";
  const { position, total, onStep } = nav;
  const walkable = position >= 0 && total > 1;

  return (
    <StageBar
      onClose={nav.onBack}
      center={
        <>
          <TitlePill
            title={title}
            picture={visual !== null && (visual.kind === "image" || visual.kind === "vector")}
            suffix={modeLabel}
            status={showStatus && run ? <RunStatusBadge run={run} /> : undefined}
          />
          {run && <RunActions run={run} onJumpToRun={onJumpToRun} />}
        </>
      }
      actions={
        <>
          <ShareMenu
            target={{
              slug: file?.slug ?? slug,
              path: file?.path ?? null,
              title,
              page: visual?.kind === "page",
            }}
            pageExport={capabilities.data?.page_export === true}
            theme={theme === "dark" ? "dark" : "light"}
          />
          <MoreMenu>
            {(close) => (
              <>
                <MenuHeading title={title} detail={details} />
                {shownViews.length > 1 && (
                  <>
                    <MenuSeparator />
                    <div role="group" aria-label={t("visualization.stage_tabs")}>
                      {shownViews.map((view) => (
                        <MenuChoice
                          key={view.id}
                          chosen={mode === view.id}
                          onSelect={() => {
                            onMode(view.id);
                            close();
                          }}
                          testId={`visualization-tab-${view.id}`}
                        >
                          {view.label}
                        </MenuChoice>
                      ))}
                    </div>
                  </>
                )}
                <MenuSeparator />
                {favoriteKey !== null && (
                  <MenuItem
                    onSelect={() => toggleFavorite(favoriteKey)}
                    testId="visualization-favorite"
                    trailing={favorite ? <Star className="h-4 w-4 shrink-0 fill-current text-warning" aria-hidden /> : null}
                  >
                    {t(favorite ? "visualization.favorite_remove" : "visualization.favorite_add")}
                  </MenuItem>
                )}
                {mode === "run" && slug && (
                  <MenuItem
                    onSelect={() => {
                      close();
                      void openExternalUrl(`${window.location.origin}${missionMapUrl(slug)}`);
                    }}
                    testId="visualization-open-map"
                  >
                    {t("visualization.open_map_page")}
                  </MenuItem>
                )}
                {externalUrl && (
                  <MenuItem
                    onSelect={() => {
                      close();
                      void openExternalUrl(`${window.location.origin}${externalUrl}`);
                    }}
                    testId="visualization-open-external"
                  >
                    {t("visualization.open_external")}
                  </MenuItem>
                )}
                {file && (
                  <a
                    href={artifactDownloadUrl(file.slug, file.path)}
                    download
                    role="menuitem"
                    onClick={close}
                    data-testid="visualization-download"
                    className="flex w-full items-center rounded-lg px-2.5 py-2 text-base text-foreground transition-colors hover:bg-secondary focus-visible:bg-secondary focus-visible:outline-none"
                  >
                    {t("visualization.download")}
                  </a>
                )}
                {/* Desktop only: a headless host has no file manager to open. */}
                {file && capabilities.data?.native_file_actions && (
                  <MenuItem
                    onSelect={() => {
                      close();
                      void onReveal();
                    }}
                    testId="visualization-reveal"
                  >
                    {t("visualization.reveal")}
                  </MenuItem>
                )}
                {walkable && (
                  <>
                    <MenuSeparator />
                    <MenuItem
                      onSelect={() => onStep(-1)}
                      disabled={position === 0}
                      testId="visualization-previous"
                      trailing={<Kbd>←</Kbd>}
                    >
                      {t("visualization.previous")}
                    </MenuItem>
                    <MenuItem
                      onSelect={() => onStep(1)}
                      disabled={position >= total - 1}
                      testId="visualization-next"
                      trailing={<Kbd>→</Kbd>}
                    >
                      {t("visualization.next")}
                    </MenuItem>
                    <p className="px-2.5 pb-1 pt-1.5 text-sm tabular-nums text-muted-foreground">
                      {t("visualization.position")
                        .replace("{0}", String(position + 1))
                        .replace("{1}", String(total))}
                    </p>
                  </>
                )}
              </>
            )}
          </MoreMenu>
        </>
      }
    />
  );
}

/** A key hint beside a menu item. */
function Kbd({ children }: { children: string }) {
  return (
    <kbd className="shrink-0 rounded border border-border px-1.5 font-sans text-sm text-muted-foreground">
      {children}
    </kbd>
  );
}

/* ------------------------------------------------------------------------- */

/**
 * The artifact on stage, full-size.
 *
 * A PAGE is framed from `/page` — served with scripts allowed and every
 * network path shut — inside `sandbox="allow-scripts"` WITHOUT
 * `allow-same-origin`: its JavaScript runs in an opaque origin that cannot
 * reach the app's cookies, storage or API. Raster and vector go through
 * `<img>`, which executes nothing. A PDF renders in the browser's own viewer;
 * that viewer is a plugin and plugins never load inside a sandboxed frame, so
 * its frame is not sandboxed — the bytes are same-origin and inert.
 */
function ArtifactStage({ visual }: { visual: VisualArtifact }) {
  const t = useT();
  /* The page follows the APP's theme, not the OS's: the artifact brief has every
   * page stamp `data-theme` from this query (design_guide.THEME_BOOTSTRAP_JS),
   * so a light app shows a light artifact even on a dark-mode machine. */
  const theme = useThemeValue();
  const [failed, setFailed] = useState(false);
  const [livingVersion, setLivingVersion] = useState(0);
  // A web link in the page opens in the person's browser, not in the frame.
  const pageFrame = useRef<HTMLIFrameElement>(null);
  useFramedPageLinks(pageFrame);
  const id = visualId(visual);
  // A new file must not inherit the previous file's failure verdict.
  useEffect(() => setFailed(false), [id]);

  if (failed) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-center">
        <p className="max-w-sm text-base text-muted-foreground">
          {t("visualization.render_failed")}
        </p>
      </div>
    );
  }

  if (visual.kind === "image" || visual.kind === "vector") {
    return (
      <div className="flex h-full items-center justify-center overflow-auto bg-sidebar p-8">
        <img
          src={visual.url}
          alt={visual.title}
          data-testid="visualization-image"
          onError={() => setFailed(true)}
          // White behind the picture in both themes: a drawing made with dark
          // strokes on a transparent ground would vanish into a dark stage.
          className="max-h-full max-w-full rounded-xl border border-border bg-white object-contain shadow-float"
        />
      </div>
    );
  }

  if (visual.kind === "page") {
    const living = isLivingSlug(visual.slug);
    return (
      <div className="flex h-full flex-col">
        {living && (
          <Suspense fallback={null}>
            <LivingPageBar slug={visual.slug} onUpdated={setLivingVersion} />
          </Suspense>
        )}
        <iframe
          ref={pageFrame}
          // A living page reloads when its refresh rewrote it.
          key={`${id}:${theme}:${living ? livingVersion : 0}`}
          src={`${artifactPageUrl(visual.slug, visual.path)}?theme=${theme}${living ? `&v=${livingVersion}` : ""}`}
          title={visual.title}
          data-testid="visualization-frame"
          onError={() => setFailed(true)}
          // allow-scripts WITHOUT allow-same-origin: the page's JS runs in an
          // opaque origin. No forms, no popups, no navigation of the app.
          sandbox="allow-scripts"
          className="min-h-0 w-full flex-1 border-0 bg-background"
        />
        <p className="flex shrink-0 items-center gap-1.5 border-t border-border px-4 py-1.5 text-sm text-muted-foreground">
          <ShieldCheck className="h-3 w-3 shrink-0" aria-hidden />
          {t("visualization.page_sandbox_note")}
        </p>
      </div>
    );
  }

  return (
    <iframe
      key={id}
      src={visual.url}
      title={visual.title}
      data-testid="visualization-frame"
      onError={() => setFailed(true)}
      className="h-full w-full border-0 bg-white"
    />
  );
}

/** The page's source, read through `/raw` — what "Code" shows. */
function ArtifactSource({ slug, path }: { slug: string; path: string }) {
  const t = useT();
  const file = useArtifactFile(slug, path);
  if (file.isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" aria-hidden />
      </div>
    );
  }
  if (file.isError || !file.data) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-center">
        <p className="text-base text-muted-foreground">{t("visualization.source_failed")}</p>
      </div>
    );
  }
  return (
    <pre
      className="h-full overflow-auto whitespace-pre-wrap break-words p-4 font-mono text-sm leading-relaxed text-foreground/90"
      data-testid="visualization-source"
    >
      {file.data.text}
      {file.data.truncated ? `\n…` : ""}
    </pre>
  );
}

/* ------------------------------------------------------------------------- */

/**
 * A mission parked in WAITING_CAPACITY asks here: wait for its own
 * subscription, approve paid API use for this one mission, or cancel. Nothing
 * is billed without that explicit approval.
 */
function RunCapacityDecision({ run }: { run: OutputSummary }) {
  if (!run.waiting_capacity || !run.mission_id) return null;
  return <CapacityDecisionPanel missionId={run.mission_id} state="WAITING_CAPACITY" />;
}

function BuildingStage({ run }: { run: OutputSummary }) {
  const t = useT();
  const parsed = parseArtifactUtterance(run.utterance);
  return (
    <div
      className="flex min-h-0 flex-1 flex-col items-center justify-center p-8"
      data-testid="visualization-building"
    >
      <EmptyState
        icon={<Loader2 className="animate-spin" aria-hidden />}
        title={t("visualization.building_title").replace("{0}", parsed?.title ?? "")}
        description={t("visualization.building_body")}
      />
      {parsed?.request && (
        <p className="max-w-md truncate text-sm text-foreground-faint">{parsed.request}</p>
      )}
    </div>
  );
}

function EmptyStage({ loading, error }: { loading: boolean; error: boolean }) {
  const t = useT();
  return (
    <div
      className="flex min-h-0 flex-1 flex-col items-center justify-center p-8"
      data-testid="visualization-empty"
    >
      <EmptyState
        icon={
          loading && !error ? (
            <Loader2 className="animate-spin" aria-hidden />
          ) : (
            <Shapes aria-hidden />
          )
        }
        title={t(error ? "visualization.error_title" : "visualization.empty_title")}
        description={t(error ? "visualization.error_body" : "visualization.empty_body")}
      />
    </div>
  );
}
