import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ArrowUp, Loader2, MessageSquarePlus, PencilLine, Shapes, ShieldCheck, Star } from "lucide-react";

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
  parseArtifactUtterance,
  runTitle,
  runWhen,
} from "@/components/visualization/galleryModel";
import { NodesLibrary } from "@/components/nodes/NodesLibrary";
import { askDodaiosToChange } from "@/components/nodes/askDodaios";
import {
  useNodeBridge,
  type NodeComment,
  type NodeEdit,
  type NodePageMode,
} from "@/components/nodes/nodeBridge";
import { useNodeCommentDraft } from "@/components/nodes/nodeCommentDraft";
import { useNodeCommentDictation } from "@/components/nodes/nodeCommentDictation";
import { NodesApiError, saveNodeField } from "@/components/nodes/useNodes";
import { isNodeSlug, isTypedNode, type NodeCard } from "@/components/nodes/nodeModel";
import { useNodesLibrary } from "@/components/nodes/useNodesLibrary";
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
  visualId,
  visualUrl,
  type VisualArtifact,
} from "@/hooks/useVisualArtifacts";

// Only a living page needs its refresh strip; load it when one is open.
const LivingPageBar = lazy(() => import("@/components/visualization/LivingPageBar"));
// The same for a typed node: its strip also tells the stage when it changed.
const NodeUpkeepBar = lazy(() => import("@/components/nodes/NodeUpkeepBar"));

/**
 * The Nodes section: a library first and a stage second.
 *
 * A node is a thing the person keeps and looks at: a document, a deck, a
 * sheet, a designed page, a dashboard, a whiteboard, a short film. The
 * assistant builds the seven typed kinds from a spec (`node` tool,
 * `dodaios/nodes`); everything older runs left behind (a worker-built page, a
 * report, a living page, a picture, a PDF) sits in the same library under the
 * type it is closest to. The section opens on the LIBRARY (`NodesLibrary`):
 * tabs, a row that starts a new node of each type, and a card per node with a
 * miniature of it on its cover. A click opens the STAGE: the page full-size
 * in its sandbox, the source one view away, every file of the run behind
 * "Files", and the run graph behind "Run"; back, previous and next walk the
 * library as it is shown.
 *
 * A run that drew no page or picture is listed too, under the library's
 * "Runs" tab; its stage composes a page from what it left behind
 * (`OutputPreview`).
 *
 * The library is one read of `/api/nodes`; the stage adds the run list
 * (`/api/outputs`) and a run's file listing when one is open. A run that is
 * still building its page shows as a "building" card until the page lands.
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

/** The stage's address of a library card. */
function selectionOf(card: NodeCard): { slug: string; path: string | null } {
  return { slug: card.slug, path: card.path };
}

/**
 * A library card's file as the stage takes it, or null for a card without
 * one (a run, a page still being built).
 */
function visualOf(card: NodeCard, run: OutputSummary | undefined): VisualArtifact | null {
  if (card.path === null || card.visual_kind === null) return null;
  return {
    slug: card.slug,
    // The run's own words when it recorded them: the toolbar reads the
    // request from the brief, which the card's short form no longer holds.
    utterance: run?.utterance ?? (card.request || undefined),
    status: run?.status,
    path: card.path,
    name: card.path.split("/").pop() ?? card.path,
    title: card.title,
    kind: card.visual_kind,
    size: card.size,
    mtime: card.updated_at,
    url: visualUrl(card.slug, card.path),
  };
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
  const outputs = useOutputsList();
  const runs = useMemo(() => outputs.data ?? [], [outputs.data]);
  /* The library's state lives here, not in the library: it stays alive while
   * a node is on stage, so back returns to the same tab, search and place. */
  const library = useNodesLibrary();
  const { allCards } = library;
  /* A card opened before the list knows it (a node just made from the
   * new-row) still has to reach the stage. */
  const [opened, setOpened] = useState<NodeCard | null>(null);

  const visuals = useMemo(() => {
    const runBySlug = new Map(runs.map((run) => [run.slug, run]));
    const cards =
      opened !== null && !allCards.some((card) => card.key === opened.key)
        ? [opened, ...allCards]
        : allCards;
    return cards.flatMap((card) => visualOf(card, runBySlug.get(card.slug)) ?? []);
  }, [allCards, opened, runs]);

  /* Runs still writing their artifact — recognised by the brief's lead line,
   * so an unrelated running mission does not pose as a page in the making. */
  const building = useMemo(
    () =>
      runs.filter(
        (run) => run.status === "running" && parseArtifactUtterance(run.utterance) !== null,
      ),
    [runs],
  );

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
   * What the stage shows. The card the user opened — a node's page, or a run
   * (its newest page once it has one, the run itself otherwise). For
   * "latest", whatever leads the whole library: the newest build in
   * progress, else the newest thing there is.
   */
  const target: StageTarget | null = useMemo(() => {
    if (selection === null) return null;
    const bySlug = (slug: string) => runs.find((r) => r.slug === slug) ?? null;
    if (selection === "latest") {
      const first = allCards[0];
      if (!first) return { run: null, visual: null, building: false };
      const run = bySlug(first.slug);
      if (first.origin === "build") return { run, visual: null, building: run !== null };
      const visual =
        first.path === null
          ? null
          : (visuals.find((v) => v.slug === first.slug && v.path === first.path) ?? null);
      return { run, visual, building: false };
    }
    if (selection.path !== null) {
      const visual = visuals.find((v) => v.slug === selection.slug && v.path === selection.path);
      if (visual) return { run: bySlug(visual.slug), visual, building: false };
      // A link names one file: wait for the library rather than show the
      // run's newest file first and switch a moment later.
      if (library.loading) return { run: null, visual: null, building: false };
    }
    const run = bySlug(selection.slug);
    const visual = visuals.find((v) => v.slug === selection.slug) ?? null;
    if (run === null && visual === null) return { run: null, visual: null, building: false };
    const isBuilding = run !== null && building.includes(run) && visual === null;
    return { run, visual, building: isBuilding };
  }, [selection, runs, visuals, building, allCards, library.loading]);

  const open = useCallback((card: NodeCard) => {
    setOpened(card);
    setSelection(selectionOf(card));
  }, []);
  const back = useCallback(() => setSelection(null), []);

  /* Previous / next: the stage's place in the library as currently shown.
   * Opened from elsewhere (a link, "latest") and not in the current view,
   * the stage simply has no neighbours. */
  const ordered = library.cards;
  const activeKey = target ? stageKey(target) : null;
  const position = activeKey ? ordered.findIndex((card) => card.key === activeKey) : -1;
  const step = useCallback(
    (delta: number) => {
      if (position < 0) return;
      const next = ordered[position + delta];
      if (next) setSelection(selectionOf(next));
    },
    [ordered, position],
  );
  /* The typed node on stage, when it is one: what "ask for a change" names. */
  const stagedNode = useMemo(() => {
    if (!activeKey) return null;
    // A node just made from the new-row is on stage before the list has it.
    const card =
      allCards.find((c) => c.key === activeKey) ?? (opened?.key === activeKey ? opened : undefined);
    return card && isTypedNode(card) ? card : null;
  }, [activeKey, allCards, opened]);

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

  const loading = outputs.isLoading || library.loading;
  const error = outputs.isError || library.failed;

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
              node={stagedNode}
              onJumpToRun={(slug) => setSelection({ slug, path: null })}
              nav={{ onBack: back, position, total: ordered.length, onStep: step }}
            />
          )}
        </section>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <NodesLibrary library={library} onOpen={open} />
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
 * A run the library did not look through for files (it is outside the
 * server's scan window, or was opened by a link before the library answered)
 * arrives without a file in hand; its listing is read here and the newest
 * page or picture in it goes on stage — an older dashboard is one click away
 * instead of "not scanned".
 */
function Stage({
  run,
  visual: pickedVisual,
  node,
  onJumpToRun,
  nav,
}: {
  run: OutputSummary | null;
  visual: VisualArtifact | null;
  /** The typed node on stage, or null for anything adopted. */
  node: NodeCard | null;
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

  /* What a click on the node's page does. COMMENT: it drops a pin with a
   * field; the comments wait there until the toolbar's "Send" hands them all
   * to the assistant at once, in the background, and it revises the node.
   * EDIT: the page's texts can be typed into, and each change is saved into
   * the node. Only a typed node takes either (its page carries the other half
   * of this, and its content is a spec), and only while its page is shown. */
  const canTouch = node !== null && visual?.kind === "page" && mode === "preview";
  const [pageMode, setPageMode] = useState<NodePageMode>("view");
  useEffect(() => setPageMode("view"), [currentId]);
  useEffect(() => {
    if (!canTouch) setPageMode("view");
  }, [canTouch]);
  const toggleMode = useCallback(
    (wanted: Exclude<NodePageMode, "view">) => setPageMode((now) => (now === wanted ? "view" : wanted)),
    [],
  );
  // Escape leaves the page's mode first, and the stage only after that. (A
  // field being typed in takes its own Escape inside the page: the key does
  // not reach this window then.)
  useEffect(() => {
    if (pageMode === "view") return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      event.preventDefault();
      setPageMode("view");
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [pageMode]);
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
        node={node}
        pageMode={canTouch ? { mode: pageMode, onToggle: toggleMode } : null}
        mode={mode}
        onMode={setMode}
        onJumpToRun={onJumpToRun}
        nav={nav}
      />
      {run && <RunCapacityDecision run={run} />}
      <div className="min-h-0 flex-1" data-testid="visualization-stage">
        {mode === "preview" && visual && (
          <ArtifactStage visual={visual} node={node} pageMode={canTouch ? pageMode : "view"} />
        )}
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
  node,
  pageMode,
  mode,
  onMode,
  onJumpToRun,
  nav,
}: {
  run: OutputSummary | null;
  visual: VisualArtifact | null;
  /** The output's primary text file when the run drew no page. */
  primary: ArtifactSummary | null;
  node: NodeCard | null;
  /** The page's mode and its switches, or null where the page takes neither comments nor edits. */
  pageMode: { mode: NodePageMode; onToggle: (mode: Exclude<NodePageMode, "view">) => void } | null;
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
  const waiting = useNodeCommentDraft((s) => s.pending.length);
  const sendingComments = useNodeCommentDraft((s) => s.sending);
  const sendComments = useCallback(async () => {
    if (node === null) return;
    const sent = await useNodeCommentDraft.getState().sendAll(node);
    if (!sent) pushToast("error", t("nodes.comment.failed"));
  }, [node, pushToast, t]);
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
          {pageMode && (
            <>
              <PageModeButton
                on={pageMode.mode === "edit"}
                onClick={() => pageMode.onToggle("edit")}
                testId="visualization-edit"
                icon={<PencilLine className="h-4 w-4" aria-hidden />}
                label={t("nodes.edit.toggle")}
              />
              <PageModeButton
                on={pageMode.mode === "comment"}
                onClick={() => pageMode.onToggle("comment")}
                testId="visualization-comment"
                icon={<MessageSquarePlus className="h-4 w-4" aria-hidden />}
                label={t("nodes.comment.toggle")}
              />
            </>
          )}
          {pageMode && waiting > 0 && (
            // The comments left on the page go out together, with one click.
            <button
              type="button"
              onClick={() => void sendComments()}
              disabled={sendingComments}
              data-testid="visualization-comments-send"
              className={
                "inline-flex h-9 shrink-0 items-center justify-center gap-2 rounded-full bg-foreground px-4 text-base " +
                "text-background transition-colors hover:bg-foreground/85 disabled:opacity-60 " +
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              }
            >
              {sendingComments ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <ArrowUp className="h-4 w-4" strokeWidth={2.5} aria-hidden />
              )}
              {waiting === 1
                ? t("nodes.comment.send_one")
                : t("nodes.comment.send_many").replace("{0}", String(waiting))}
            </button>
          )}
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
                {node !== null && (
                  <MenuItem
                    onSelect={() => {
                      close();
                      void askDodaiosToChange(node);
                    }}
                    testId="visualization-ask-change"
                  >
                    {t("nodes.menu.ask")}
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

/** One of the page's two modes in the stage bar: pressed while it is on. */
function PageModeButton({
  on,
  onClick,
  testId,
  icon,
  label,
}: {
  on: boolean;
  onClick: () => void;
  testId: string;
  icon: ReactNode;
  label: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      data-testid={testId}
      className={
        "inline-flex h-9 shrink-0 items-center justify-center gap-2 rounded-full border px-4 text-base " +
        "transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring " +
        (on
          ? "border-transparent bg-primary text-primary-foreground"
          : "border-border/70 text-foreground hover:bg-secondary")
      }
    >
      {icon}
      {label}
    </button>
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
function ArtifactStage({
  visual,
  node = null,
  pageMode = "view",
}: {
  visual: VisualArtifact;
  /** The typed node this page belongs to, or null for anything adopted. */
  node?: NodeCard | null;
  /** What a click on the page does (see `Stage`). */
  pageMode?: NodePageMode;
}) {
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

  /* The comments left on the page wait in the draft until the toolbar's
   * "Send". Those sent and not yet worked in are answered by the node's next
   * revision: the page is drawn again then, and the line below goes quiet. */
  const nodeKey = node === null ? null : (node.id ?? node.key);
  const openDraft = useNodeCommentDraft((s) => s.open);
  const settle = useNodeCommentDraft((s) => s.settle);
  const working = useNodeCommentDraft((s) => (s.nodeKey === nodeKey ? s.working : 0));
  const outcome = useNodeCommentDraft((s) => s.outcome);
  useEffect(() => openDraft(nodeKey), [nodeKey, openDraft]);
  /* The revision the page last got from someone else than the reader (the
   * assistant): only that one works comments in. A field the reader saved
   * with a redraw draws the page again too, but answers no comment. */
  const [revisedBy, setRevisedBy] = useState(0);
  useEffect(() => settle(), [id, revisedBy, settle]);
  const onComment = useCallback(
    async (comment: NodeComment) => {
      if (node === null) throw new Error("no node takes this comment");
      useNodeCommentDraft.getState().add(comment);
    },
    [node],
  );

  /* The reader's own edits. A saved value is already on the page, so the
   * revision it makes must NOT draw the page again (that would throw away
   * the caret, the slide, the scroll): the watcher's report of that revision
   * is skipped. A field that asks for it (`data-refresh`) is drawn again at
   * once instead, at the same scroll position. Any OTHER revision (the
   * assistant's) still draws the page again. */
  const ownRevisions = useRef(new Set<number>());
  const saving = useRef(0);
  const heldRevision = useRef<number | null>(null);
  const [editState, setEditState] = useState<{ saving: number; error: string }>({ saving: 0, error: "" });
  useEffect(() => {
    ownRevisions.current.clear();
    heldRevision.current = null;
    setEditState({ saving: 0, error: "" });
  }, [id]);
  const onNodeUpdated = useCallback((updatedAt: number) => {
    if (ownRevisions.current.has(updatedAt)) return;
    // While a save is on its way the revision it makes may be reported first.
    if (saving.current > 0) {
      heldRevision.current = updatedAt;
      return;
    }
    setLivingVersion(updatedAt);
    setRevisedBy(updatedAt);
  }, []);
  const onEdit = useCallback(
    async (edit: NodeEdit) => {
      if (node === null || node.id === null) throw new Error("no node takes this edit");
      saving.current += 1;
      setEditState((now) => ({ saving: now.saving + 1, error: "" }));
      try {
        const saved = await saveNodeField(node.id, { path: edit.path, value: edit.value, as: edit.as });
        ownRevisions.current.add(saved.updated_at);
        if (edit.refresh) setLivingVersion(saved.updated_at);
        setEditState((now) => ({ saving: now.saving - 1, error: "" }));
      } catch (error) {
        const reason = error instanceof NodesApiError && error.detail ? error.detail : "";
        setEditState((now) => ({ saving: now.saving - 1, error: reason || t("nodes.edit.failed") }));
        throw error;
      } finally {
        saving.current -= 1;
        const held = heldRevision.current;
        if (saving.current === 0 && held !== null) {
          heldRevision.current = null;
          if (!ownRevisions.current.has(held)) {
            setLivingVersion(held);
            setRevisedBy(held);
          }
        }
      }
    },
    [node, t],
  );

  const onRemove = useCallback((n: number) => useNodeCommentDraft.getState().remove(n), []);
  const tellCommentState = useNodeBridge(pageFrame, {
    mode: node !== null ? pageMode : "view",
    pageKey: id,
    onEdit,
    labels: {
      placeholder: t("nodes.comment.placeholder"),
      add: t("nodes.comment.add"),
      pending: t("nodes.comment.pending"),
      sent: t("nodes.comment.sent"),
      failed: t("nodes.comment.failed"),
      remove: t("nodes.comment.remove"),
      working: t("nodes.comment.working"),
      dictate: t("chats_view.dictation_start"),
      stopDictate: t("chats_view.dictation_stop"),
      listening: t("chats_view.dictation_listening"),
      transcribing: t("chats_view.dictation_transcribing"),
    },
    onComment,
    onRemove,
  });
  // A comment can be spoken: the page's microphone asks the app to dictate.
  useNodeCommentDictation(pageFrame, node !== null && pageMode === "comment");
  // The page learns which of its pins went out, or did not.
  useEffect(() => {
    if (outcome !== null) tellCommentState(outcome.ns, outcome.state);
  }, [outcome, tellCommentState]);

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
    const typed = isNodeSlug(visual.slug);
    const rewritten = living || typed;
    return (
      <div className="flex h-full flex-col">
        {living && (
          <Suspense fallback={null}>
            <LivingPageBar slug={visual.slug} onUpdated={setLivingVersion} />
          </Suspense>
        )}
        {typed && (
          <Suspense fallback={null}>
            <NodeUpkeepBar slug={visual.slug} onUpdated={onNodeUpdated} />
          </Suspense>
        )}
        <iframe
          ref={pageFrame}
          // A living page reloads when its refresh rewrote it, and a typed
          // node when the assistant revised it.
          key={`${id}:${theme}:${rewritten ? livingVersion : 0}`}
          src={`${artifactPageUrl(visual.slug, visual.path)}?theme=${theme}${rewritten ? `&v=${livingVersion}` : ""}`}
          title={visual.title}
          data-testid="visualization-frame"
          onError={() => setFailed(true)}
          // allow-scripts WITHOUT allow-same-origin: the page's JS runs in an
          // opaque origin. No forms, no popups, no navigation of the app.
          sandbox="allow-scripts"
          className="min-h-0 w-full flex-1 border-0 bg-background"
        />
        <p
          className="flex shrink-0 items-center gap-1.5 border-t border-border px-4 py-1.5 text-sm text-muted-foreground"
          data-testid="visualization-page-note"
          data-state={
            working > 0
              ? "working"
              : pageMode === "edit"
                ? editState.saving > 0
                  ? "saving"
                  : editState.error
                    ? "edit-failed"
                    : "editing"
                : pageMode === "comment"
                  ? "commenting"
                  : "idle"
          }
          aria-live="polite"
        >
          {working > 0 ? (
            <>
              <Loader2 className="h-3 w-3 shrink-0 animate-spin" aria-hidden />
              {working === 1
                ? t("nodes.comment.working")
                : t("nodes.comment.working_many").replace("{0}", String(working))}
            </>
          ) : pageMode === "edit" ? (
            editState.saving > 0 ? (
              <>
                <Loader2 className="h-3 w-3 shrink-0 animate-spin" aria-hidden />
                {t("nodes.edit.saving")}
              </>
            ) : editState.error ? (
              <span className="text-destructive">{editState.error}</span>
            ) : (
              <>
                <PencilLine className="h-3 w-3 shrink-0" aria-hidden />
                {t("nodes.edit.hint")}
              </>
            )
          ) : pageMode === "comment" ? (
            <>
              <MessageSquarePlus className="h-3 w-3 shrink-0" aria-hidden />
              {t("nodes.comment.hint")}
            </>
          ) : (
            <>
              <ShieldCheck className="h-3 w-3 shrink-0" aria-hidden />
              {t("visualization.page_sandbox_note")}
            </>
          )}
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
