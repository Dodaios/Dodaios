import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ArrowUp, Loader2, MessageSquarePlus, MousePointerClick, PencilLine, Shapes, ShieldCheck, Star } from "lucide-react";

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
  ShareMenu,
  StageBar,
  TitlePill,
  type StageBarLayout,
} from "@/components/visualization/ArtifactStageBar";
import { NodeBar, NodeBarCommonContext, NodeBarEnd, useNodeBarCommon, type NodeBarCommon } from "@/components/nodes/bar/NodeBar";
import { ToolbarButton } from "@/components/nodes/editors/controls";
import { LeaveGuardContext, createLeaveGuard, type LeaveGuard } from "@/components/nodes/editors/leaveGuard";
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
  type NodeEditHere,
  type NodePageMode,
} from "@/components/nodes/nodeBridge";
import { useNodeCommentDraft } from "@/components/nodes/nodeCommentDraft";
import { useNodeCommentDictation } from "@/components/nodes/nodeCommentDictation";
import { RenameNodeDialog } from "@/components/nodes/RenameNodeDialog";
import { NodesApiError, saveNodeField, useNodeActions } from "@/components/nodes/useNodes";
import { isNodeSlug, isTypedNode, type NodeCard } from "@/components/nodes/nodeModel";
import { NODE_TYPE_LABEL_KEY } from "@/components/nodes/nodeTheme";
import { isEditableType, type EditableType, type NodeEditorStart } from "@/components/nodes/editors/types";
import { useNodesLibrary } from "@/components/nodes/useNodesLibrary";
import { useNewWhiteboard } from "@/components/nodes/whiteboard/useNewWhiteboard";
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
// A whiteboard's canvas is a large editor: loaded when a board is opened.
const WhiteboardEditor = lazy(() => import("@/components/nodes/whiteboard/WhiteboardEditor"));
// Every other typed node has a native editor of its type, loaded on "Edit".
const NodeEditorHost = lazy(() => import("@/components/nodes/editors/NodeEditorHost"));

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
export function visualOf(card: NodeCard, run: OutputSummary | undefined): VisualArtifact | null {
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
export function isTypingTarget(target: EventTarget | null): boolean {
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
  /* A node the reader just started blank opens ready to be typed into, the
   * way a new file does in an office suite: its key waits here until the
   * stage has switched its page to Edit. */
  const [startEditingKey, setStartEditingKey] = useState<string | null>(null);
  const openNew = useCallback(
    (card: NodeCard) => {
      setStartEditingKey(card.key);
      open(card);
    },
    [open],
  );
  const editingStarted = useCallback(() => setStartEditingKey(null), []);
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
  /* The library's card of what is on stage (what "Chat" names), and the typed
   * node it is, when it is one (what is edited and commented). */
  const stagedCard = useMemo(() => {
    if (!activeKey) return null;
    // A node just made from the new-row is on stage before the list has it.
    return allCards.find((c) => c.key === activeKey) ?? (opened?.key === activeKey ? opened : null);
  }, [activeKey, allCards, opened]);
  const stagedNode = stagedCard !== null && isTypedNode(stagedCard) ? stagedCard : null;

  /* Escape goes back to the library, ←/→ walk it — unless a text field has
   * the keys. A framed page keeps its own keys (its events never reach us).
   * An open node editor keeps them all: its arrows move a selection, and
   * leaving it is its own Done. */
  const staged = target !== null;
  const [editorOpen, setEditorOpen] = useState(false);
  useEffect(() => {
    if (!staged || editorOpen) return;
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
  }, [staged, editorOpen, back, step]);

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
              card={stagedCard}
              startEditing={stagedNode !== null && stagedNode.key === startEditingKey}
              onEditingStarted={editingStarted}
              onEditorOpen={setEditorOpen}
              onOpenNode={open}
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
      <NodesLibrary library={library} onOpen={open} onCreated={openNew} />
    </div>
  );
}

/* ------------------------------------------------------------------------- */

/** What the stage needs to know about its place in the library. */
export interface StageNavigation {
  onBack: () => void;
  /** Index in the library as shown, or -1 when the open item is not in it. */
  position: number;
  total: number;
  onStep: (delta: number) => void;
}

/**
 * What changes when the stage stands in the node window instead of the Nodes
 * section (components/nodes/peek): the bar is a window's title row, the
 * window adds its own buttons to it, and "ask for a change" drafts into the
 * conversation beside the node instead of leaving for the front page.
 */
export interface StageChrome {
  layout: StageBarLayout;
  /** The window's own buttons, between the stage's actions and the close button. */
  trailing?: ReactNode;
  /** False while the window's close button stands right of the stage (see `StageBar`). */
  closeButton?: boolean;
  /** Takes "ask for a change" instead of the lead conversation's composer. */
  onAskChange?: (node: NodeCard) => void;
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
export function Stage({
  run,
  visual: pickedVisual,
  node,
  card = node,
  startEditing = false,
  onEditingStarted,
  onEditorOpen,
  onOpenNode,
  onJumpToRun,
  nav,
  chrome,
  leaveGuard,
}: {
  run: OutputSummary | null;
  visual: VisualArtifact | null;
  /** The typed node on stage, or null for anything adopted. */
  node: NodeCard | null;
  /** The library's card of what is on stage, typed or adopted: what "Chat" names. */
  card?: NodeCard | null;
  /** The node was just started blank: its editor takes the caret as soon as it can. */
  startEditing?: boolean;
  /** The node opened ready for `startEditing`; it is not asked again. */
  onEditingStarted?: () => void;
  /** The node's editor opened or closed (the stage's own keys pause while it is open). */
  onEditorOpen?: (open: boolean) => void;
  /** Put another node on stage (one just made from the toolbar). */
  onOpenNode: (card: NodeCard) => void;
  onJumpToRun: (slug: string) => void;
  /** Back to the library and previous / next — the ends of the stage's bar. */
  nav: StageNavigation;
  /** Set where the stage stands in the node window; absent in the section. */
  chrome?: StageChrome;
  /** Closing asks an open editor to save first; the node window passes its own so its other ways out ask too. */
  leaveGuard?: LeaveGuard;
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
   * field; the comments wait there until the bar's "Send" hands them all to
   * the assistant at once, in the background, and it revises the node.
   * EDIT: the page's texts can be typed into, and each change is saved into
   * the node. Only a typed node takes either (its page carries the other half
   * of this, and its content is a spec), and only while its page is shown. */
  /* A whiteboard is drawn on in its editor, always editable: its page (the
   * picture of the board the library and chat show) takes neither mode. */
  const board = node !== null && isTypedNode(node) && node.type === "whiteboard" ? node : null;
  const canTouch = node !== null && board === null && visual?.kind === "page" && mode === "preview";
  /* A type with a native editor (every type but the whiteboard) OPENS in it:
   * the node is shaped where it is shown, from the bar at its bottom, with no
   * Edit before and no Done after (the maintainer's request, 2026-11-18).
   * The page comes back for comments, and when the editor could not load
   * (its message leads back to the page). The page's own Edit (typing into
   * its texts) stays for a type without a native editor. */
  const editorType: EditableType | null =
    canTouch && node !== null && isTypedNode(node) && isEditableType(node.type) ? node.type : null;
  const [editing, setEditing] = useState(true);
  /* Back on the page after the editor gave up, a click into one of the
   * page's texts opens the editor again with the caret there. Not a film: a
   * click on it plays and pauses. */
  const [startAt, setStartAt] = useState<NodeEditorStart | null>(null);
  useEffect(() => setEditing(true), [currentId]);
  useEffect(() => {
    if (!editing) setStartAt(null);
  }, [editing]);
  const [pageMode, setPageMode] = useState<NodePageMode>("view");
  useEffect(() => setPageMode("view"), [currentId]);
  useEffect(() => {
    if (!canTouch) setPageMode("view");
  }, [canTouch]);
  const editorOpen = editing && editorType !== null && pageMode !== "comment";
  useEffect(() => {
    onEditorOpen?.(editorOpen);
  }, [editorOpen, onEditorOpen]);
  useEffect(() => () => onEditorOpen?.(false), [onEditorOpen]);
  // After the resets above, so a node started blank ends up ready to type into.
  useEffect(() => {
    if (!startEditing) return;
    // A blank board is already open for drawing: nothing to switch on.
    if (board !== null) {
      onEditingStarted?.();
      return;
    }
    if (!canTouch) return;
    if (editorType !== null) {
      setPageMode("view");
      setEditing(true);
    } else {
      setPageMode("edit");
    }
    onEditingStarted?.();
  }, [startEditing, canTouch, board, editorType, onEditingStarted]);
  const toggleMode = useCallback(
    (wanted: Exclude<NodePageMode, "view">) => {
      if (wanted === "edit" && editorType !== null) {
        setPageMode("view");
        setEditing(true);
        return;
      }
      setPageMode((now) => (now === wanted ? "view" : wanted));
    },
    [editorType],
  );
  const closeEditor = useCallback(() => setEditing(false), []);
  const editHere = useCallback((at: NodeEditHere) => {
    setStartAt(at);
    setPageMode("view");
    setEditing(true);
  }, []);
  const tapToEdit = editorType !== null && editorType !== "motion" && pageMode === "view" && !editing;
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

  /* Closing the node: an open editor saves first (and stays, saying so, when
   * it cannot). A guard handed in belongs to a window that routes its own
   * ways out through it, the stage's close button among them. */
  const ownGuard = useMemo(createLeaveGuard, []);
  const guard = leaveGuard ?? ownGuard;
  const guardedNav = useMemo(
    () => (leaveGuard ? nav : { ...nav, onBack: () => ownGuard.leave(nav.onBack) }),
    [leaveGuard, nav, ownGuard],
  );

  /* The end of every bar: the comment button where the node takes comments,
   * and "Chat", which starts a request for a change in the conversation (the
   * one beside the node in the node window). Not for a run that drew no
   * file: there is nothing to point at. */
  const chatCard = card ?? node;
  const onAskChange = chrome?.onAskChange;
  const common: NodeBarCommon = useMemo(
    () => ({
      comment: canTouch ? { on: pageMode === "comment", onToggle: () => toggleMode("comment") } : undefined,
      onChat:
        chatCard !== null && visual !== null && mode === "preview"
          ? () => {
              if (onAskChange) onAskChange(chatCard);
              else void askDodaiosToChange(chatCard);
            }
          : undefined,
    }),
    [canTouch, pageMode, toggleMode, chatCard, visual, mode, onAskChange],
  );

  return (
    <NodeBarCommonContext.Provider value={common}>
      <LeaveGuardContext.Provider value={guard}>
        <ArtifactToolbar
          run={run}
          visual={visual}
          primary={primary}
          node={node}
          onNewBoard={board !== null ? onOpenNode : null}
          mode={mode}
          onMode={setMode}
          onJumpToRun={onJumpToRun}
          nav={guardedNav}
          chrome={chrome}
        />
        {run && <RunCapacityDecision run={run} />}
        <div className="relative min-h-0 flex-1" data-testid="visualization-stage">
          {mode === "preview" && visual && board !== null && <WhiteboardStage node={board} visual={visual} />}
          {mode === "preview" && visual && board === null && editorOpen && editorType !== null && node?.id && (
            <Suspense fallback={<EditorWaiting />}>
              <NodeEditorHost
                node={node as NodeCard & { id: string }}
                type={editorType}
                slug={visual.slug}
                startAt={startAt}
                onDone={closeEditor}
              />
            </Suspense>
          )}
          {mode === "preview" && visual && board === null && !editorOpen && (
            <ArtifactStage
              visual={visual}
              node={node}
              pageMode={canTouch ? pageMode : "view"}
              onEditHere={tapToEdit ? editHere : undefined}
              barItems={
                canTouch ? (
                  <PageModeTools
                    node={node}
                    pageMode={pageMode}
                    // The page's own Edit: for a type without a native editor,
                    // or the way back to the editor after it gave up.
                    canEdit={editorType === null || !editing}
                    onToggle={toggleMode}
                  />
                ) : null
              }
            />
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
      </LeaveGuardContext.Provider>
    </NodeBarCommonContext.Provider>
  );
}

/** The editor's chunk is on its way: the same quiet line the editor shows while it reads the node. */
function EditorWaiting() {
  const t = useT();
  return (
    <div className="flex h-full items-center justify-center gap-2 text-base text-muted-foreground">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
      {t("nodes.editor.loading")}
    </div>
  );
}

/**
 * The page's own tools in its bar: Edit where the page itself is typed into
 * (a type without a native editor, or the way back to the editor), and
 * "Send" for the comments left on it, all at once.
 */
function PageModeTools({
  node,
  pageMode,
  canEdit,
  onToggle,
}: {
  node: NodeCard | null;
  pageMode: NodePageMode;
  canEdit: boolean;
  onToggle: (mode: Exclude<NodePageMode, "view">) => void;
}) {
  const t = useT();
  const pushToast = useEventStore((s) => s.pushToast);
  const waiting = useNodeCommentDraft((s) => s.pending.length);
  const sending = useNodeCommentDraft((s) => s.sending);
  const send = useCallback(async () => {
    if (node === null) return;
    const sent = await useNodeCommentDraft.getState().sendAll(node);
    if (!sent) pushToast("error", t("nodes.comment.failed"));
  }, [node, pushToast, t]);
  return (
    <>
      {canEdit && (
        <ToolbarButton
          label={t("nodes.edit.toggle")}
          icon={<PencilLine aria-hidden />}
          active={pageMode === "edit"}
          onClick={() => onToggle("edit")}
          data-testid="visualization-edit"
        />
      )}
      {waiting > 0 && (
        // The comments left on the page go out together, with one click.
        <button
          type="button"
          onClick={() => void send()}
          disabled={sending}
          data-testid="visualization-comments-send"
          className={
            "ml-0.5 inline-flex h-8 shrink-0 items-center justify-center gap-1.5 rounded-md bg-foreground px-3 text-sm font-medium " +
            "text-background transition-colors hover:bg-foreground/85 disabled:opacity-60 " +
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          }
        >
          {sending ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          ) : (
            <ArrowUp className="h-4 w-4" strokeWidth={2.5} aria-hidden />
          )}
          <span>
            {waiting === 1
              ? t("nodes.comment.send_one")
              : t("nodes.comment.send_many").replace("{0}", String(waiting))}
          </span>
        </button>
      )}
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

/**
 * The stage's top bar, kept to what every node needs: the name, which opens
 * the menu of what is used now and then, "Share", and close. What shapes the
 * node is in the bar at its bottom (`NodeBar`), never up here.
 */
function ArtifactToolbar({
  run,
  visual,
  primary,
  node,
  onNewBoard,
  mode,
  onMode,
  onJumpToRun,
  nav,
  chrome,
}: {
  run: OutputSummary | null;
  visual: VisualArtifact | null;
  /** The output's primary text file when the run drew no page. */
  primary: ArtifactSummary | null;
  node: NodeCard | null;
  /** On a whiteboard: opens the blank board "New whiteboard" makes. Null elsewhere. */
  onNewBoard: ((card: NodeCard) => void) | null;
  mode: StageMode;
  onMode: (mode: StageMode) => void;
  onJumpToRun: (slug: string) => void;
  nav: StageNavigation;
  chrome?: StageChrome;
}) {
  const t = useT();
  const windowed = chrome?.layout === "window";
  /* A typed node keeps its name and its last revision: both can be changed
   * from where the node is open, not only from its card in the library. */
  const nodeActions = useNodeActions();
  const [renaming, setRenaming] = useState<NodeCard | null>(null);
  const { favorites, toggle: toggleFavorite } = useArtifactFavorites();
  // The same key the library's card carries, so a star set here shows there.
  const favoriteKey = visual ? visualId(visual) : run ? `run:${run.slug}` : null;
  const favorite = favoriteKey !== null && favorites.has(favoriteKey);
  const pushToast = useEventStore((s) => s.pushToast);
  const undoLastChange = useCallback(() => {
    if (node === null || !isTypedNode(node)) return;
    // The page is drawn again by the stage's watcher once the node went back.
    nodeActions.revertNode(node.id).then(
      () => pushToast("success", t("nodes.revert.done")),
      (failure: unknown) => {
        const nothing = failure instanceof NodesApiError && failure.status === 400;
        pushToast(nothing ? "info" : "error", t(nothing ? "nodes.revert.nothing" : "nodes.revert.failed"));
      },
    );
  }, [node, nodeActions, pushToast, t]);
  /* "New whiteboard" on a board: a blank board, opened at once. */
  const newBoardTarget = useRef(onNewBoard);
  newBoardTarget.current = onNewBoard;
  const openMadeBoard = useCallback((card: NodeCard) => newBoardTarget.current?.(card), []);
  const newBoard = useNewWhiteboard(openMadeBoard);
  const capabilities = useOutputsCapabilities();
  const parsed = parseArtifactUtterance(visual?.utterance ?? run?.utterance);
  const slug = visual?.slug ?? run?.slug ?? "";
  // The file the menu's Download / Reveal / Open act on: the artifact, or
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
    visual && visual.size > 0 ? formatSize(visual.size) : "",
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
  // A window's title also says what the thing is and when it last changed.
  const titleDetail = [
    node !== null && isTypedNode(node) ? t(NODE_TYPE_LABEL_KEY[node.type]) : "",
    visual ? formatWhen(visual.mtime) : run ? formatWhen(runWhen(run)) : "",
  ]
    .filter(Boolean)
    .join(" · ");

  const menu = (close: () => void) => (
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
      {onNewBoard && (
        <MenuItem
          onSelect={() => {
            close();
            void newBoard.create();
          }}
          disabled={newBoard.creating}
          testId="visualization-new-whiteboard"
        >
          {t("nodes.whiteboard.new")}
        </MenuItem>
      )}
      {favoriteKey !== null && (
        <MenuItem
          onSelect={() => toggleFavorite(favoriteKey)}
          testId="visualization-favorite"
          trailing={favorite ? <Star className="h-4 w-4 shrink-0 fill-current text-warning" aria-hidden /> : null}
        >
          {t(favorite ? "visualization.favorite_remove" : "visualization.favorite_add")}
        </MenuItem>
      )}
      {node !== null && isTypedNode(node) && (
        <>
          <MenuItem
            onSelect={() => {
              close();
              setRenaming(node);
            }}
            testId="visualization-rename"
          >
            {t("nodes.menu.rename")}
          </MenuItem>
          <MenuItem
            onSelect={() => {
              close();
              undoLastChange();
            }}
            testId="visualization-revert"
          >
            {t("nodes.menu.revert")}
          </MenuItem>
        </>
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
      {/* What used to stand under every page, said where it is looked for. */}
      {visual?.kind === "page" && (
        <p
          className="flex items-start gap-1.5 border-t border-border px-2.5 pb-1 pt-2 text-sm text-muted-foreground"
          data-testid="visualization-sandbox-note"
        >
          <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          {t("visualization.page_sandbox_note")}
        </p>
      )}
    </>
  );

  return (
    <>
    <RenameNodeDialog
      card={renaming}
      onClose={() => setRenaming(null)}
      onRename={async (card, name) => {
        if (isTypedNode(card)) await nodeActions.renameNode(card.id, name);
      }}
    />
    <StageBar
      onClose={nav.onBack}
      layout={chrome?.layout}
      trailing={chrome?.trailing}
      closeButton={chrome?.closeButton}
      center={
        <>
          <TitlePill
            title={title}
            picture={visual !== null && (visual.kind === "image" || visual.kind === "vector")}
            suffix={modeLabel}
            status={showStatus && run ? <RunStatusBadge run={run} /> : undefined}
            plain={windowed}
            detail={titleDetail}
            menu={menu}
          />
          {run && <RunActions run={run} onJumpToRun={onJumpToRun} />}
        </>
      }
      actions={
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
      }
    />
    </>
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
  onEditHere,
  barItems,
}: {
  visual: VisualArtifact;
  /** The typed node this page belongs to, or null for anything adopted. */
  node?: NodeCard | null;
  /** What a click on the page does (see `Stage`). */
  pageMode?: NodePageMode;
  /** A click into the page's text opens the node's editor there; absent where it does not. */
  onEditHere?: (at: NodeEditHere) => void;
  /** The page's own tools for its bar (Edit, Send), where it takes them. */
  barItems?: ReactNode;
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
  /* What the watcher said last. Its first word about a page is the revision
   * that page was just loaded in, not a change: drawing the page again for
   * it loaded every typed node twice, with an empty frame in between. */
  const knownRevision = useRef<number | null>(null);
  useEffect(() => {
    ownRevisions.current.clear();
    heldRevision.current = null;
    knownRevision.current = null;
    setEditState({ saving: 0, error: "" });
  }, [id]);
  const onNodeUpdated = useCallback((updatedAt: number) => {
    const known = knownRevision.current;
    knownRevision.current = updatedAt;
    if (known === null || known === updatedAt) return;
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
    onEditHere: node !== null ? onEditHere : undefined,
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
      <div className="flex h-full flex-col bg-sidebar">
        <div className="flex min-h-0 flex-1 items-center justify-center overflow-auto p-8">
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
        <PageBar />
      </div>
    );
  }

  if (visual.kind === "page") {
    const living = isLivingSlug(visual.slug);
    const typed = isNodeSlug(visual.slug);
    const rewritten = living || typed;
    const noteState =
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
            : onEditHere
              ? "tap-to-edit"
              : "idle";
    const note =
      working > 0 ? (
        <>
          <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" aria-hidden />
          <span className="truncate">
            {working === 1
              ? t("nodes.comment.working")
              : t("nodes.comment.working_many").replace("{0}", String(working))}
          </span>
        </>
      ) : pageMode === "edit" ? (
        editState.saving > 0 ? (
          <>
            <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" aria-hidden />
            <span className="truncate">{t("nodes.edit.saving")}</span>
          </>
        ) : editState.error ? (
          <span className="truncate text-destructive">{editState.error}</span>
        ) : (
          <>
            <PencilLine className="h-3.5 w-3.5 shrink-0" aria-hidden />
            <span className="truncate">{t("nodes.edit.hint")}</span>
          </>
        )
      ) : pageMode === "comment" ? (
        <>
          <MessageSquarePlus className="h-3.5 w-3.5 shrink-0" aria-hidden />
          <span className="truncate">{t("nodes.comment.hint")}</span>
        </>
      ) : onEditHere ? (
        <>
          <MousePointerClick className="h-3.5 w-3.5 shrink-0" aria-hidden />
          <span className="truncate">{t("nodes.edit.tap_hint")}</span>
        </>
      ) : null;
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
        <PageBar note={{ state: noteState, content: note }}>{barItems}</PageBar>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <iframe
        key={id}
        src={visual.url}
        title={visual.title}
        data-testid="visualization-frame"
        onError={() => setFailed(true)}
        className="min-h-0 w-full flex-1 border-0 bg-white"
      />
      <PageBar />
    </div>
  );
}

/**
 * The bar under a page, a picture or a PDF the stage shows itself: the same
 * pill every editor floats, here in a slim band of its own so it never
 * covers the page's own controls (a deck's arrows, a sheet's tabs). It holds
 * what the page's mode says (commenting, the assistant working the comments
 * in), the page's own tools, and the comment button and "Chat". Nothing
 * where none of that applies.
 */
function PageBar({ note, children }: { note?: { state: string; content: ReactNode }; children?: ReactNode }) {
  const t = useT();
  const { comment, onChat } = useNodeBarCommon();
  const said = note !== undefined && note.content !== null;
  // The line's state is read by the page's tests and by screen readers, said or not.
  const noteElement =
    note === undefined ? null : (
      <span
        className={said ? "flex min-w-0 max-w-[22rem] items-center gap-1.5 px-2 text-sm text-muted-foreground" : "sr-only"}
        data-testid="visualization-page-note"
        data-state={note.state}
        aria-live="polite"
      >
        {note.content}
      </span>
    );
  const tools = Boolean(children) && children !== false;
  if (!said && !tools && !comment && !onChat) return noteElement;
  return (
    <NodeBar label={t("nodes.bar.label")} docked testId="visualization-page-bar">
      {noteElement}
      {children}
      <NodeBarEnd divider={said || tools} />
    </NodeBar>
  );
}
/**
 * A whiteboard on stage: its editor, filling the stage. The node's watcher
 * (mounted for every typed node) reports when the node changed, so what the
 * assistant draws appears in the open editor.
 */
function WhiteboardStage({ node, visual }: { node: NodeCard & { id: string }; visual: VisualArtifact }) {
  const t = useT();
  const [revision, setRevision] = useState<number | null>(null);
  return (
    <div className="flex h-full flex-col" data-testid="visualization-whiteboard">
      <Suspense fallback={null}>
        <NodeUpkeepBar slug={visual.slug} onUpdated={setRevision} />
      </Suspense>
      <div className="min-h-0 flex-1">
        <Suspense
          fallback={
            <div className="flex h-full items-center justify-center gap-2 text-base text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              {t("nodes.whiteboard.loading")}
            </div>
          }
        >
          <WhiteboardEditor key={node.id} nodeId={node.id} title={node.title} revision={revision} />
        </Suspense>
      </div>
    </div>
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

export function BuildingStage({ run }: { run: OutputSummary }) {
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

export function EmptyStage({ loading, error }: { loading: boolean; error: boolean }) {
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
