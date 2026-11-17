/**
 * A whiteboard node on the stage: an infinite canvas to draw on.
 *
 * The engine is the open-source editor `@excalidraw/excalidraw`: shapes,
 * arrows, text, freehand, pictures, frames, the library, the Mermaid dialog,
 * export, undo. Its own toolbars are hidden; the board draws its own controls
 * over it in the app's look (`canvas/BoardChrome.tsx`): a tool dock, an
 * inspector for the selection, a menu, undo and zoom. Lines are clean and the
 * font is the normal one by default; the ground is the app's dotted stage.
 * The view glides: the wheel, a pinch and the zoom buttons move it over a few
 * frames instead of in steps (`canvas/viewport.ts`). What reaches a web
 * service is left out or hidden (collaboration, the public library site, the
 * AI tools, web embeds, the project's links: see `whiteboard.css`), and its
 * fonts come from this app (`assetPath.ts`).
 *
 * The node's spec is the editor's scene. It is read once when the board
 * opens, and every change is saved back on its own after a short pause
 * (`BoardSync`): the person never presses "Save". The assistant draws on the
 * same board through its `whiteboard` tool. The open board asks every moment
 * whether the node changed (and the stage reports it too, `revision`); what
 * the assistant drew is merged into the open editor without taking away what
 * the person is drawing, and its new pieces land one by one under the
 * assistant's own cursor, so the person watches it draw (`canvas/liveBuild.ts`).
 *
 * This module is its own chunk (it is large): the stage loads it only when a
 * whiteboard is opened.
 */
import "./assetPath";
import "@excalidraw/excalidraw/index.css";
import "./whiteboard.css";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  CaptureUpdateAction,
  Excalidraw,
  FONT_FAMILY,
  convertToExcalidrawElements,
  getCommonBounds,
  loadFromBlob,
  newElementWith,
  reconcileElements,
  restoreElements,
  viewportCoordsToSceneCoords,
} from "@excalidraw/excalidraw";
import type { OrderedExcalidrawElement } from "@excalidraw/excalidraw/element/types";
import type { RemoteExcalidrawElement } from "@excalidraw/excalidraw/data/reconcile";
import type {
  AppState,
  BinaryFileData,
  BinaryFiles,
  ExcalidrawImperativeAPI,
  ExcalidrawInitialDataState,
  LibraryItems,
} from "@excalidraw/excalidraw/types";
import { AlertCircle, Check, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useT, useUiLanguage, type UiLanguage } from "@/i18n";
import { useThemeValue } from "@/hooks/useTheme";
import { openExternalUrl } from "@/lib/openExternal";
import { useEventStore } from "@/store/events";
import { NodesApiError } from "../useNodes";
import {
  fetchBoardFile,
  fetchBoardUpdatedAt,
  fetchScene,
  putScene,
  uploadBoardFile,
  type BoardElement,
  type SceneRead,
} from "./boardApi";
import { BoardSync, type EditorFile, type SaveState } from "./boardSync";
import { readBoardLibrary, writeBoardLibrary } from "./boardLibrary";
import {
  BoardDock,
  BoardInspector,
  BoardMenu,
  EmptyHint,
  FONTS,
  LiveBadge,
  TOOLS_THAT_DRAW,
  ZoomBar,
  type ChromeState,
  type DockTool,
} from "./canvas/BoardChrome";
import { CANVAS_OFFSETS, LiveBuild, freshAssistantIds } from "./canvas/liveBuild";
import { applyStyle, sendEditorKey, type StylePatch } from "./canvas/styleOps";
import { SmoothViewport } from "./canvas/viewport";
import { ToolOverlay, type OverlayTool } from "./canvas/ToolOverlay";
import { fillTarget, lassoPick, recognizeStroke, strokePoints, type Point, type ToolElement } from "./canvas/boardTools";

/** The editor's language for each UI language of the app. */
const EDITOR_LANGUAGE: Record<UiLanguage, string> = {
  en: "en",
  de: "de-DE",
  es: "es-ES",
  pt: "pt-PT",
  zh: "zh-CN",
};

/** Element types a board does not keep: they frame the web (see the plan's scene). */
const WEB_TOOLS = new Set(["embeddable", "iframe", "magicframe"]);

export interface WhiteboardEditorProps {
  /** The whiteboard node's id. */
  nodeId: string;
  /** Its title: the name an exported file gets. */
  title: string;
  /**
   * The node's latest update time as the stage last saw it (seconds), or
   * null before the first look. A change that this editor did not save
   * itself is drawn in.
   */
  revision: number | null;
}

export default function WhiteboardEditor({ nodeId, title, revision }: WhiteboardEditorProps) {
  const t = useT();
  const [attempt, setAttempt] = useState(0);
  const [load, setLoad] = useState<{ state: "loading" } | { state: "failed" } | { state: "ready"; read: SceneRead }>({
    state: "loading",
  });

  useEffect(() => {
    const controller = new AbortController();
    setLoad({ state: "loading" });
    fetchScene(nodeId, controller.signal).then(
      (read) => setLoad({ state: "ready", read }),
      () => {
        if (!controller.signal.aborted) setLoad({ state: "failed" });
      },
    );
    return () => controller.abort();
  }, [nodeId, attempt]);

  if (load.state === "loading") {
    return (
      <div className="flex h-full items-center justify-center gap-2 text-base text-muted-foreground" data-testid="whiteboard-loading">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        {t("nodes.whiteboard.loading")}
      </div>
    );
  }
  if (load.state === "failed") {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center" data-testid="whiteboard-load-failed">
        <p className="text-base text-muted-foreground">{t("nodes.whiteboard.load_failed")}</p>
        <Button variant="outline" size="sm" onClick={() => setAttempt((n) => n + 1)}>
          {t("nodes.whiteboard.retry")}
        </Button>
      </div>
    );
  }
  return <BoardCanvas key={nodeId} nodeId={nodeId} title={title} read={load.read} revision={revision} />;
}

/**
 * The server's elements in the shape the editor needs: text measured again,
 * bindings and frames repaired, missing fractional indices filled in.
 *
 * Repairing can raise an element's version; the server's version is put back,
 * so the merge compares what the two sides really hold (a repair alone is no
 * edit to save, and must not outrank the person's unsaved one).
 */
function restoreFromServer(elements: readonly BoardElement[]): OrderedExcalidrawElement[] {
  const restored = restoreElements(elements as never, null, { refreshDimensions: true, repairBindings: true });
  const byId = new Map(elements.map((element) => [element.id, element]));
  for (const element of restored) {
    const original = byId.get(element.id);
    if (original && (element.version !== original.version || element.versionNonce !== original.versionNonce)) {
      Object.assign(element, { version: original.version, versionNonce: original.versionNonce });
    }
  }
  return restored;
}

/** The editor's font names by the id a text element carries. */
const FONT_NAMES = new Map<number, string>(Object.entries(FONT_FAMILY).map(([name, id]) => [id, name]));

/**
 * Text from the server is measured when the board opens, which is before the
 * editor's own fonts have arrived: a label measured in a fallback font comes
 * out too narrow, and the editor then cuts the hand-drawn letters off at its
 * edges. So the fonts the board's texts use are loaded first, the texts are
 * measured again, and only then is the view fitted to the whole board (zoomed
 * out as far as it takes, never in past 100 %), clear of the board's own controls.
 */
/**
 * Load the fonts the given texts use (with their own letters), so a text is
 * measured in its real font. Returns how many fonts were asked for.
 */
export async function loadBoardFonts(elements: readonly BoardElement[]): Promise<number> {
  const used = new Map<string, string>();
  for (const element of elements) {
    if (element.type !== "text" || element.isDeleted) continue;
    const text = element as unknown as { fontFamily: number; text: string };
    const name = FONT_NAMES.get(text.fontFamily);
    if (name) used.set(name, ((used.get(name) ?? "") + text.text).slice(0, 4000));
  }
  if (typeof document !== "undefined" && document.fonts && used.size > 0) {
    await Promise.allSettled(
      [...used].map(([name, sample]) => document.fonts.load(`20px "${name}"`, sample || undefined)),
    );
  }
  return used.size;
}

export async function settleBoard(
  editor: ExcalidrawImperativeAPI,
  alive: () => boolean,
  expectElements = false,
): Promise<void> {
  // The editor hands out its API before it has taken the initial scene in.
  for (let wait = 0; expectElements && wait < 60 && editor.getSceneElements().length === 0; wait += 1) {
    await new Promise((resolve) => setTimeout(resolve, 50));
    if (!alive()) return;
  }
  const used = await loadBoardFonts(editor.getSceneElements() as unknown as readonly BoardElement[]);
  if (!alive()) return;
  if (used > 0) {
    editor.updateScene({
      elements: restoreFromServer(editor.getSceneElementsIncludingDeleted() as unknown as readonly BoardElement[]),
      captureUpdate: CaptureUpdateAction.NEVER,
    });
  }
  if (editor.getSceneElements().length > 0) {
    editor.scrollToContent(undefined, {
      fitToViewport: true,
      viewportZoomFactor: 0.9,
      animate: false,
      maxZoom: 1,
      canvasOffsets: CANVAS_OFFSETS,
    });
  }
}

function describeError(error: unknown): string {
  return error instanceof NodesApiError ? error.detail : "";
}

/** How often the open board asks whether the assistant drew something. */
export const WATCH_MS = 1_500;
/** The person's own moves keep the view theirs for this long. */
const BUSY_MS = 2_500;
/** Dots on the board, this far apart at 100 %. */
const DOT_STEP = 24;

/** Defaults for what the person draws: clean lines, the normal font, round corners. */
const CLEAN_DEFAULTS = {
  currentItemRoughness: 0,
  currentItemFontFamily: FONTS.sans,
  currentItemRoundness: "round",
  currentItemStrokeWidth: 2,
  currentItemFontSize: 20,
} as const;

/**
 * The board keeps its background as a colour; white (and no colour) is the
 * app's own dotted ground, drawn behind a see-through canvas.
 */
export function isDefaultBackground(color: string | undefined | null): boolean {
  if (!color) return true;
  const value = color.trim().toLowerCase();
  return value === "#ffffff" || value === "#fff" || value === "white" || value === "transparent";
}

/** The editor's background for a stored one. */
function toEditorBackground(color: string | undefined | null): string {
  return isDefaultBackground(color) ? "transparent" : (color as string);
}

/** The stored background for the editor's one (the default stays as stored). */
function toStoredBackground(editor: string | undefined, stored: string | undefined): string | undefined {
  if (editor === "transparent" || editor === undefined) return isDefaultBackground(stored) ? stored : "#ffffff";
  return editor;
}

const SAMPLE_KEYS = [
  "strokeColor",
  "backgroundColor",
  "strokeWidth",
  "strokeStyle",
  "roughness",
  "opacity",
  "roundness",
  "fontSize",
  "fontFamily",
  "textAlign",
  "startArrowhead",
  "endArrowhead",
] as const;

/** What the controls show, read from the editor. */
function readChrome(elements: readonly OrderedExcalidrawElement[], appState: AppState): ChromeState {
  const selectedIds = appState.selectedElementIds;
  const live = elements.filter((element) => !element.isDeleted);
  const selected = live.filter((element) => selectedIds[element.id]);
  const editing = appState.editingTextElement as unknown as Record<string, unknown> | null;
  const first = (editing ?? selected.find((element) => element.type !== "text") ?? selected[0]) as unknown as
    | Record<string, unknown>
    | undefined;
  const sample: Record<string, unknown> = {};
  if (first) {
    for (const key of SAMPLE_KEYS) sample[key] = first[key];
    const bound = (first.boundElements as { id: string; type: string }[] | null) ?? [];
    const label = bound.find((item) => item.type === "text");
    if (label) {
      const text = live.find((element) => element.id === label.id) as unknown as Record<string, unknown> | undefined;
      if (text) {
        sample.hasLabel = true;
        sample.fontSize = text.fontSize;
        sample.fontFamily = text.fontFamily;
        sample.textAlign = text.textAlign;
      }
    }
  } else {
    Object.assign(sample, {
      strokeColor: appState.currentItemStrokeColor,
      backgroundColor: appState.currentItemBackgroundColor,
      strokeWidth: appState.currentItemStrokeWidth,
      strokeStyle: appState.currentItemStrokeStyle,
      roughness: appState.currentItemRoughness,
      opacity: appState.currentItemOpacity,
      roundness: appState.currentItemRoundness === "round" ? { type: 3 } : null,
      fontSize: appState.currentItemFontSize,
      fontFamily: appState.currentItemFontFamily,
      textAlign: appState.currentItemTextAlign,
      startArrowhead: appState.currentItemStartArrowhead,
      endArrowhead: appState.currentItemEndArrowhead,
    });
  }
  return {
    tool: appState.activeTool.type,
    zoom: appState.zoom.value,
    selected: [
      ...new Set(
        selected
          .filter((element) => {
            const container = (element as unknown as { containerId?: string | null }).containerId;
            return !container || !selectedIds[container];
          })
          .map((element) => element.type),
      ),
    ],
    sample,
    editingText: Boolean(editing),
    hasElements: live.length > 0,
    gridOn: Boolean(appState.gridModeEnabled),
    toolLocked: Boolean(appState.activeTool.locked),
  };
}

function chromeKey(state: ChromeState): string {
  return JSON.stringify(state);
}

function BoardCanvas({
  nodeId,
  title,
  read,
  revision,
}: {
  nodeId: string;
  title: string;
  read: SceneRead;
  revision: number | null;
}) {
  const t = useT();
  const theme = useThemeValue();
  const language = useUiLanguage();
  const assistant = useEventStore((s) => s.assistantName) || "Dodaios";
  const assistantName = useRef(assistant);
  assistantName.current = assistant;
  const root = useRef<HTMLDivElement>(null);
  const ground = useRef<HTMLDivElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const api = useRef<ExcalidrawImperativeAPI | null>(null);
  const lastMove = useRef(0);
  const inspectorOpen = useRef(false);
  const storedBackground = useRef<string | undefined>(read.scene.appState.viewBackgroundColor);
  const [save, setSave] = useState<{ state: SaveState; detail: string }>({ state: "idle", detail: "" });
  const [chrome, setChrome] = useState<ChromeState>({
    tool: "selection",
    zoom: 1,
    selected: [],
    sample: {},
    editingText: false,
    hasElements: read.scene.elements.some((element) => !element.isDeleted),
    gridOn: Boolean(read.scene.appState.gridModeEnabled),
    toolLocked: false,
  });
  const chromeSeen = useRef("");
  const [background, setBackground] = useState(() => toEditorBackground(read.scene.appState.viewBackgroundColor));
  const [drawing, setDrawing] = useState(false);
  /** The board's own tool over the canvas (lasso, bucket), or none. */
  const [mode, setMode] = useState<OverlayTool | null>(null);
  /** Draw to shape: each finished pen stroke becomes the shape it looks like. */
  const [autoShape, setAutoShape] = useState(false);
  const toolState = useRef({ mode: null as OverlayTool | null, autoShape: false });
  toolState.current = { mode, autoShape };
  const strokesBefore = useRef<Set<string>>(new Set());
  const [width, setWidth] = useState(1200);

  const [viewport] = useState(
    () =>
      new SmoothViewport(
        () => api.current,
        () => {
          const box = root.current?.getBoundingClientRect();
          return { left: box?.left ?? 0, top: box?.top ?? 0 };
        },
      ),
  );
  const [live] = useState(
    () =>
      new LiveBuild({
        api: () => api.current,
        name: () => assistantName.current,
        personBusy: () => Date.now() - lastMove.current < BUSY_MS,
        onActive: setDrawing,
      }),
  );

  const [sync] = useState(
    () =>
      new BoardSync({
        initial: read,
        transport: {
          fetchScene: () => fetchScene(nodeId),
          putScene: (scene, init) => putScene(nodeId, scene, init),
          uploadFile: (file) => uploadBoardFile(nodeId, file),
          fetchFile: (fileId) => fetchBoardFile(nodeId, fileId),
        },
        editor: {
          applyRemote: (elements, appState) => {
            const editor = api.current;
            if (!editor) return;
            // A play still running lands first, so the merge sees all of it.
            live.finish();
            const before = editor.getSceneElementsIncludingDeleted();
            const held = new Set(before.map((element) => element.id));
            const remote = restoreFromServer(elements);
            const merged = reconcileElements(before, remote as RemoteExcalidrawElement[], editor.getAppState());
            if (appState) {
              storedBackground.current = appState.viewBackgroundColor;
              const next = toEditorBackground(appState.viewBackgroundColor);
              setBackground(next);
              editor.updateScene({
                appState: { viewBackgroundColor: next, gridModeEnabled: Boolean(appState.gridModeEnabled) },
              });
            }
            const fresh = new Set(
              merged.filter((element) => !element.isDeleted && !held.has(element.id)).map((element) => element.id),
            );
            // The assistant's strokes are not the person's to undo.
            if (fresh.size > 0) live.start(merged as unknown as BoardElement[], fresh);
            else editor.updateScene({ elements: merged, captureUpdate: CaptureUpdateAction.NEVER });
          },
          addFiles: (files) => api.current?.addFiles(files as BinaryFileData[]),
        },
        onState: (state, detail) => setSave({ state, detail }),
        describeError,
      }),
  );

  /** What the assistant drew in the last moments plays again when the board opens. */
  const [opening] = useState(() => {
    const all = restoreFromServer(read.scene.elements);
    const fresh = freshAssistantIds(all as unknown as BoardElement[]);
    return { all, fresh };
  });

  const initialData = useMemo<ExcalidrawInitialDataState>(
    () => ({
      elements: opening.all.filter((element) => !opening.fresh.has(element.id)),
      appState: {
        ...CLEAN_DEFAULTS,
        viewBackgroundColor: toEditorBackground(read.scene.appState.viewBackgroundColor),
        gridModeEnabled: Boolean(read.scene.appState.gridModeEnabled),
      } as never,
      scrollToContent: true,
      libraryItems: readBoardLibrary(),
    }),
    [read, opening],
  );

  const onApi = useCallback(
    (editor: ExcalidrawImperativeAPI) => {
      api.current = editor;
      // Draw to shape: a stroke the board has not seen yet when the pen
      // comes up is the one just drawn (the known ones are noted when the
      // mode starts and after every stroke).
      editor.onPointerUp(() => {
        if (!toolState.current.autoShape) return;
        // The editor finishes the stroke just after this event.
        setTimeout(() => {
          strokesToShapes(editor, strokesBefore.current);
          strokesBefore.current = knownStrokes(editor);
        }, 30);
      });
      void sync.loadMissingFiles(read.scene.elements);
      const expectElements = opening.all.some((element) => !element.isDeleted && !opening.fresh.has(element.id));
      void settleBoard(editor, () => api.current === editor, expectElements).then(async () => {
        if (api.current !== editor || opening.fresh.size === 0) return;
        // The pieces to play were read before the fonts were in: measure them
        // again in their own fonts, or a label is cut at its old width.
        await loadBoardFonts(read.scene.elements);
        if (api.current !== editor) return;
        live.start(restoreFromServer(read.scene.elements) as unknown as BoardElement[], opening.fresh);
      });
    },
    [sync, read, opening, live],
  );

  const onChange = useCallback(
    (elements: readonly OrderedExcalidrawElement[], appState: AppState, files: BinaryFiles) => {
      // Belt and braces for the hidden web embed tool (a keyboard path, a
      // file opened from disk): the board keeps no element that frames the web.
      if (WEB_TOOLS.has(appState.activeTool.type)) {
        api.current?.setActiveTool({ type: "selection" });
      }
      const tools = toolState.current;
      if (tools.autoShape && appState.activeTool.type !== "freedraw") setAutoShape(false);
      if (tools.mode && appState.activeTool.type !== "selection") setMode(null);
      const next = readChrome(elements, appState);
      const key = chromeKey(next);
      if (key !== chromeSeen.current) {
        chromeSeen.current = key;
        setChrome(next);
      }
      if (appState.viewBackgroundColor !== background) setBackground(appState.viewBackgroundColor);
      sync.onChange({
        elements: elements as unknown as readonly BoardElement[],
        appState: {
          viewBackgroundColor: toStoredBackground(appState.viewBackgroundColor, storedBackground.current),
          gridModeEnabled: appState.gridModeEnabled,
        },
        files: files as unknown as Record<string, EditorFile>,
      });
    },
    [sync, background],
  );

  /* The dotted ground follows the view. Set on the element, not in state: it
     changes at every frame of a pan. */
  const onScrollChange = useCallback((scrollX: number, scrollY: number, zoom: { value: number }) => {
    const el = ground.current;
    if (!el) return;
    let step = DOT_STEP * zoom.value;
    while (step < 12) step *= 4;
    el.style.backgroundSize = `${step}px ${step}px`;
    el.style.backgroundPosition = `${scrollX * zoom.value}px ${scrollY * zoom.value}px`;
  }, []);

  // The assistant (or another window) changed the node.
  useEffect(() => {
    if (revision !== null) void sync.onRevision(revision);
  }, [revision, sync]);

  // Watch the node closely while the board is open, so the assistant's work
  // arrives as it is drawn rather than a few seconds later.
  useEffect(() => {
    let alive = true;
    let controller: AbortController | null = null;
    const tick = async () => {
      if (!alive || document.visibilityState !== "visible") return;
      controller = new AbortController();
      try {
        const updatedAt = await fetchBoardUpdatedAt(nodeId, controller.signal);
        if (alive && updatedAt) void sync.onRevision(updatedAt);
      } catch {
        // The next tick asks again.
      }
    };
    const timer = window.setInterval(() => void tick(), WATCH_MS);
    return () => {
      alive = false;
      window.clearInterval(timer);
      controller?.abort();
    };
  }, [nodeId, sync]);

  // Unsaved strokes go out when the window hides or closes, and when the
  // board is left; the debounce would otherwise lose the last second.
  useEffect(() => {
    sync.revive();
    live.revive();
    const onHide = () => {
      if (document.visibilityState === "hidden") void sync.flush({ leaving: true });
    };
    const onPageHide = () => void sync.flush({ leaving: true });
    const onBlur = () => void sync.flush();
    document.addEventListener("visibilitychange", onHide);
    window.addEventListener("pagehide", onPageHide);
    window.addEventListener("blur", onBlur);
    return () => {
      document.removeEventListener("visibilitychange", onHide);
      window.removeEventListener("pagehide", onPageHide);
      window.removeEventListener("blur", onBlur);
      live.dispose();
      viewport.dispose();
      void sync.flush();
      sync.dispose();
    };
  }, [sync, live, viewport]);

  /*
   * The canvas owns its keys. The editor reads them on its own element; the
   * app's global shortcuts listen on the window (Escape back to the library,
   * arrows to the next node, `?` for the app's shortcut sheet). A key pressed
   * in the editor, or in one of its dialogs in the body, stops at the
   * document, so it never reaches those. The few chords the app catches
   * before anything else (the quick switcher, window zoom) stay global by
   * design.
   */
  useEffect(() => {
    // Where the person last pressed: on the board, keys with no focused
    // element (the focus fell to the page, a toast went away) are the board's.
    let pressedOnBoard = false;
    const onDown = (event: PointerEvent) => {
      const target = event.target;
      pressedOnBoard = target instanceof Node && Boolean(root.current?.contains(target) || (target instanceof Element && target.closest(".excalidraw")));
    };
    const keep = (event: KeyboardEvent) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      if (root.current?.contains(target) || target.closest(".excalidraw")) event.stopPropagation();
    };
    const reclaim = (event: KeyboardEvent) => {
      if (!pressedOnBoard || (event.target !== document.body && event.target !== document.documentElement)) return;
      const container = root.current?.querySelector<HTMLElement>(".excalidraw-container");
      if (!container) return;
      event.stopPropagation();
      event.preventDefault();
      container.focus({ preventScroll: true });
      container.dispatchEvent(
        new KeyboardEvent(event.type, {
          key: event.key,
          code: event.code,
          ctrlKey: event.ctrlKey,
          metaKey: event.metaKey,
          shiftKey: event.shiftKey,
          altKey: event.altKey,
          repeat: event.repeat,
          bubbles: true,
          cancelable: true,
        }),
      );
    };
    document.addEventListener("pointerdown", onDown, true);
    document.addEventListener("keydown", reclaim, true);
    document.addEventListener("keydown", keep);
    document.addEventListener("keyup", keep);
    return () => {
      document.removeEventListener("pointerdown", onDown, true);
      document.removeEventListener("keydown", reclaim, true);
      document.removeEventListener("keydown", keep);
      document.removeEventListener("keyup", keep);
    };
  }, []);

  const addNote = useCallback(() => {
    const editor = api.current;
    if (!editor) return;
    const state = editor.getAppState();
    const zoom = state.zoom.value;
    const center = { x: -state.scrollX + state.width / zoom / 2, y: -state.scrollY + state.height / zoom / 2 };
    // A note lands in the nearest free spot to the middle of the view.
    const { x, y } = freeSpot(
      editor.getSceneElements().map((element) => {
        const [x1, y1, x2, y2] = getCommonBounds([element]);
        return { x: x1, y: y1, w: x2 - x1, h: y2 - y1 };
      }),
      center,
      NOTE_SIZE,
    );
    const [note] = convertToExcalidrawElements([
      {
        type: "rectangle",
        x,
        y,
        width: NOTE_SIZE,
        height: NOTE_SIZE,
        backgroundColor: NOTE_COLOR,
        strokeColor: "transparent",
        fillStyle: "solid",
        strokeWidth: 1,
        roughness: 0,
        roundness: { type: 3 },
      },
    ] as never);
    editor.setActiveTool({ type: "selection" });
    editor.updateScene({
      elements: [...editor.getSceneElementsIncludingDeleted(), note],
      appState: { selectedElementIds: { [note.id]: true } } as never,
      captureUpdate: CaptureUpdateAction.IMMEDIATELY,
    });
    // Enter on a selected box starts typing its label.
    requestAnimationFrame(() => sendEditorKey(root.current, "edit-text"));
  }, []);

  /** Pick a tool: the editor's own, or one of the board's (lasso, bucket, draw to shape). */
  const chooseTool = useCallback(
    (tool: DockTool) => {
      const editor = api.current;
      if (!editor) return;
      viewport.stop();
      if (tool === "lasso" || tool === "bucket") {
        editor.setActiveTool({ type: "selection" });
        if (tool === "bucket") {
          const state = editor.getAppState();
          editor.updateScene({
            appState: {
              selectedElementIds: {},
              ...(state.currentItemBackgroundColor === "transparent" ? { currentItemBackgroundColor: BUCKET_COLOR } : {}),
            } as never,
          });
        }
        setAutoShape(false);
        setMode(tool);
        return;
      }
      setMode(null);
      if (tool === "shape") {
        strokesBefore.current = knownStrokes(editor);
        setAutoShape(true);
        editor.setActiveTool({ type: "freedraw" });
        return;
      }
      setAutoShape(false);
      editor.setActiveTool({ type: tool } as never);
    },
    [viewport],
  );

  /** Keep the tool after drawing, or not (the editor's lock, Q). */
  const toggleLock = useCallback(() => {
    const editor = api.current;
    if (!editor) return;
    const tool = editor.getAppState().activeTool;
    editor.setActiveTool({ type: tool.type === "custom" ? "selection" : tool.type, locked: !tool.locked } as never);
  }, []);

  const toScene = (point: Point): Point => {
    const state = api.current!.getAppState();
    return viewportCoordsToSceneCoords({ clientX: point.x, clientY: point.y }, state);
  };

  const onLasso = useCallback((loop: Point[], add: boolean) => {
    const editor = api.current;
    if (!editor) return;
    const state = editor.getAppState();
    const picked = lassoPick(editor.getSceneElements() as unknown as ToolElement[], loop.map(toScene));
    const selected: Record<string, true> = add ? { ...(state.selectedElementIds as Record<string, true>) } : {};
    for (const id of picked) selected[id] = true;
    editor.updateScene({ appState: { selectedElementIds: selected } as never });
    // Like any tool: once used it gives way to the selection, unless locked.
    if (!state.activeTool.locked) setMode(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onBucket = useCallback((at: Point) => {
    const editor = api.current;
    if (!editor) return;
    const target = fillTarget(editor.getSceneElements() as unknown as ToolElement[], toScene(at));
    if (!target) return;
    const chosen = editor.getAppState().currentItemBackgroundColor;
    const color = chosen && chosen !== "transparent" ? chosen : BUCKET_COLOR;
    editor.updateScene({
      elements: editor
        .getSceneElementsIncludingDeleted()
        .map((element) => (element.id === target.id ? newElementWith(element, { backgroundColor: color, fillStyle: "solid" }) : element)),
      captureUpdate: CaptureUpdateAction.IMMEDIATELY,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The wheel glides; pointer and keys mark the person as busy with the view.
  useEffect(() => {
    const el = root.current;
    if (!el) return;
    const onWheel = (event: WheelEvent) => {
      lastMove.current = Date.now();
      const over = event.target instanceof Element && event.target.closest("[data-board-overlay]");
      if (!(event.target instanceof HTMLCanvasElement) && !over) return;
      if (viewport.wheel(event)) {
        event.preventDefault();
        event.stopPropagation();
      }
    };
    const onPointer = (event: PointerEvent) => {
      lastMove.current = Date.now();
      viewport.stop();
      // The board takes the keyboard when it is touched (unless a field of its
      // own is), so Escape, Delete and the shortcuts act on the board, never
      // on the page behind it.
      const target = event.target as HTMLElement | null;
      if (target?.closest("input, textarea, select, [contenteditable=true]")) return;
      requestAnimationFrame(() => {
        const active = document.activeElement;
        if (active && el.contains(active) && active.closest(".excalidraw-container")) return;
        el.querySelector<HTMLElement>(".excalidraw-container")?.focus({ preventScroll: true });
      });
    };
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && (target.tagName === "TEXTAREA" || target.tagName === "INPUT" || target.isContentEditable)) return;
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      if (api.current?.getAppState().editingTextElement) return;
      const key = event.key.toLowerCase();
      const own = (action: () => void) => {
        event.preventDefault();
        event.stopPropagation();
        action();
      };
      if (key === "n" && !event.shiftKey) own(addNote);
      else if (key === "b" && !event.shiftKey) own(() => chooseTool("bucket"));
      else if (key === "w" && !event.shiftKey) own(() => chooseTool("lasso"));
      else if (key === "x" && event.shiftKey) own(() => chooseTool(toolState.current.autoShape ? "selection" : "shape"));
      else if (key === "escape" && (toolState.current.mode || toolState.current.autoShape)) own(() => chooseTool("selection"));
      else if (toolState.current.mode && /^[a-z0-9]$/.test(key)) setMode(null);
    };
    el.addEventListener("wheel", onWheel, { capture: true, passive: false });
    el.addEventListener("pointerdown", onPointer, true);
    el.addEventListener("keydown", onKey, true);
    const resize =
      typeof ResizeObserver === "undefined" ? null : new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    resize?.observe(el);
    return () => {
      el.removeEventListener("wheel", onWheel, true);
      el.removeEventListener("pointerdown", onPointer, true);
      el.removeEventListener("keydown", onKey, true);
      resize?.disconnect();
    };
  }, [viewport, addNote, chooseTool]);

  const onLinkOpen = useCallback(
    (element: { link: string | null }, event: CustomEvent<{ nativeEvent: MouseEvent | React.PointerEvent<HTMLCanvasElement> }>) => {
      const link = element.link ?? "";
      // A web or mail link opens in the person's browser, not in the app's
      // window; a link to another element of the board is the editor's own.
      if (/^(https?:|mailto:)/i.test(link)) {
        event.preventDefault();
        void openExternalUrl(link);
      }
    },
    [],
  );

  const onLibraryChange = useCallback((items: LibraryItems) => writeBoardLibrary(items), []);

  const size = () => {
    const box = root.current?.getBoundingClientRect();
    return { width: box?.width ?? 0, height: box?.height ?? 0 };
  };
  const fit = useCallback(() => {
    const editor = api.current;
    if (!editor) return;
    viewport.stop();
    const all = editor.getSceneElements();
    if (all.length === 0) {
      viewport.zoomTo(1, size());
      return;
    }
    editor.scrollToContent(all, {
      fitToViewport: true,
      viewportZoomFactor: 0.9,
      animate: true,
      duration: 350,
      maxZoom: 2,
      // The inspector, when open, covers the right edge: fit beside it.
      canvasOffsets: inspectorOpen.current ? { ...CANVAS_OFFSETS, right: 280 } : CANVAS_OFFSETS,
    });
  }, [viewport]);

  const openFile = useCallback(async (file: File) => {
    const editor = api.current;
    if (!editor) return;
    try {
      const data = await loadFromBlob(file, null, null);
      if (data.files) editor.addFiles(Object.values(data.files));
      editor.updateScene({ elements: data.elements, captureUpdate: CaptureUpdateAction.IMMEDIATELY });
      requestAnimationFrame(fit);
    } catch {
      editor.setToast({ message: t("nodes.whiteboard.menu.open_failed"), closable: true, duration: 4000 });
    }
  }, [fit, t]);

  const wide = width >= 900;
  const dockTool = mode ?? (autoShape ? "shape" : chrome.tool);
  const shownChrome: ChromeState = mode === "bucket" ? { ...chrome, tool: "bucket", selected: [] } : chrome;
  const showInspector = mode === "bucket" || (mode === null && (chrome.selected.length > 0 || TOOLS_THAT_DRAW.has(chrome.tool)));
  inspectorOpen.current = showInspector;

  return (
    <div
      ref={root}
      className="dodaios-board h-full w-full"
      data-testid="whiteboard-editor"
      data-theme={theme === "dark" ? "dark" : "light"}
      data-tool={dockTool}
      onBlur={(event) => {
        // Focus left the board for the app: save what is waiting.
        if (!root.current?.contains(event.relatedTarget as Node | null)) void sync.flush();
      }}
    >
      <div
        ref={ground}
        aria-hidden
        className="dodaios-board-ground"
        data-default={background === "transparent" ? "true" : "false"}
        style={background === "transparent" ? undefined : { backgroundColor: background, backgroundImage: "none" }}
      />
      <Excalidraw
        excalidrawAPI={onApi}
        initialData={initialData}
        onChange={onChange}
        onScrollChange={onScrollChange}
        theme={theme === "dark" ? "dark" : "light"}
        langCode={EDITOR_LANGUAGE[language] ?? "en"}
        name={title}
        autoFocus
        aiEnabled={false}
        validateEmbeddable={() => false}
        onLinkOpen={onLinkOpen}
        onLibraryChange={onLibraryChange}
        UIOptions={{
          canvasActions: {
            // The theme follows the app's own setting.
            toggleTheme: false,
            export: { saveFileToDisk: true },
            loadScene: true,
            saveToActiveFile: true,
            saveAsImage: true,
            clearCanvas: true,
            changeViewBackgroundColor: true,
          },
          tools: { image: true },
        }}
      />
      {mode ? <ToolOverlay tool={mode} onLasso={onLasso} onBucket={onBucket} /> : null}
      <input
        ref={fileInput}
        type="file"
        accept=".excalidraw,.json,application/json,image/png,image/svg+xml"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (file) void openFile(file);
        }}
      />
      <div
        className="dodaios-board-chrome pointer-events-none absolute inset-0 z-[3]"
        onMouseDown={(event) => {
          // The board's buttons do not take the focus from the canvas, so its
          // keys (Delete, Escape, N, shortcuts) keep working after a click.
          const target = event.target as HTMLElement;
          if (!target.closest("input, textarea, select")) event.preventDefault();
        }}
      >
        <div className="absolute left-3 top-3">
          <BoardMenu
            gridOn={chrome.gridOn}
            background={background === "transparent" ? "default" : background}
            onUndo={() => sendEditorKey(root.current, "undo")}
            onRedo={() => sendEditorKey(root.current, "redo")}
            onExportImage={() => api.current?.updateScene({ appState: { openDialog: { name: "imageExport" } } })}
            onSaveFile={() => api.current?.updateScene({ appState: { openDialog: { name: "jsonExport" } } })}
            onOpenFile={() => fileInput.current?.click()}
            onFind={() => api.current?.toggleSidebar({ name: "default", tab: "search", force: true })}
            onShortcuts={() => api.current?.updateScene({ appState: { openDialog: { name: "help" } } })}
            onGrid={() => api.current?.updateScene({ appState: { gridModeEnabled: !chrome.gridOn } })}
            onBackground={(color) => {
              const next = color === "default" ? "transparent" : color;
              setBackground(next);
              api.current?.updateScene({ appState: { viewBackgroundColor: next } });
            }}
            onClear={() => {
              const editor = api.current;
              if (!editor) return;
              editor.updateScene({
                elements: editor
                  .getSceneElementsIncludingDeleted()
                  .map((element) => (element.isDeleted ? element : newElementWith(element, { isDeleted: true }))),
                captureUpdate: CaptureUpdateAction.IMMEDIATELY,
              });
            }}
          />
        </div>
        <div className="absolute right-3 top-3 flex items-center gap-2">
          {drawing ? <LiveBadge name={assistant} /> : null}
          <SaveStatus state={save.state} detail={save.detail} />
          {!wide ? (
            <ZoomBar
              zoom={chrome.zoom}
              onIn={() => viewport.zoomBy(1.25, size())}
              onOut={() => viewport.zoomBy(0.8, size())}
              onFit={fit}
              onReset={() => viewport.zoomTo(1, size())}
            />
          ) : null}
        </div>
        {showInspector ? (
          <div className="dodaios-board-inspector absolute right-3 top-[64px] max-h-[calc(100%-160px)] overflow-y-auto rounded-xl">
            <BoardInspector
              state={shownChrome}
              onStyle={(patch: StylePatch) => {
                const editor = api.current;
                if (editor) applyStyle(editor, patch);
              }}
              onCommand={(command) => sendEditorKey(root.current, command)}
            />
          </div>
        ) : null}
        {!chrome.hasElements && !drawing ? (
          <div className="absolute inset-0 flex items-center justify-center">
            <EmptyHint name={assistant} />
          </div>
        ) : null}
        <div className="absolute bottom-3 left-1/2 max-w-[calc(100%-24px)] -translate-x-1/2 rounded-xl">
          <BoardDock
            tool={dockTool}
            locked={chrome.toolLocked}
            onLock={toggleLock}
            onTool={chooseTool}
            onNote={addNote}
            onMermaid={() => api.current?.updateScene({ appState: { openDialog: { name: "ttd", tab: "mermaid" } } })}
            onLibrary={() => api.current?.toggleSidebar({ name: "default", tab: "library" })}
          />
        </div>
        {wide ? (
          <div className="absolute bottom-3 right-3">
            <ZoomBar
              zoom={chrome.zoom}
              onIn={() => viewport.zoomBy(1.25, size())}
              onOut={() => viewport.zoomBy(0.8, size())}
              onFit={fit}
              onReset={() => viewport.zoomTo(1, size())}
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}

const NOTE_SIZE = 200;
/** The bucket's colour while none is chosen: a light blue of the palette. */
const BUCKET_COLOR = "#a5d8ff";

/** The ids of every pen stroke on the board (deleted ones too). */
function knownStrokes(editor: ExcalidrawImperativeAPI): Set<string> {
  return new Set(
    editor
      .getSceneElementsIncludingDeleted()
      .filter((element) => element.type === "freedraw")
      .map((element) => element.id),
  );
}

/**
 * Draw to shape: every pen stroke drawn since `before` that reads as a shape
 * (see `recognizeStroke`) is replaced by that shape, in the stroke's colour
 * and width, as one step the person can undo. A stroke that is no shape stays.
 */
export function strokesToShapes(editor: ExcalidrawImperativeAPI, before: ReadonlySet<string>): number {
  const state = editor.getAppState();
  // A stroke still being drawn is not finished yet.
  const drawingNow = state.newElement?.id;
  const all = editor.getSceneElementsIncludingDeleted();
  const made: ReturnType<typeof convertToExcalidrawElements> = [];
  const gone = new Set<string>();
  for (const element of all) {
    if (element.type !== "freedraw" || element.isDeleted || before.has(element.id) || element.id === drawingNow) continue;
    const shape = recognizeStroke(strokePoints(element as unknown as ToolElement));
    if (!shape) continue;
    const look = {
      strokeColor: element.strokeColor,
      strokeWidth: element.strokeWidth,
      opacity: element.opacity,
      roughness: state.currentItemRoughness,
      frameId: element.frameId,
    };
    const [made1] =
      shape.kind === "arrow"
        ? convertToExcalidrawElements([
            { type: "arrow", x: shape.x, y: shape.y, width: shape.dx, height: shape.dy, endArrowhead: "arrow", ...look },
          ] as never)
        : convertToExcalidrawElements([
            {
              type: shape.kind,
              x: shape.x,
              y: shape.y,
              width: shape.width,
              height: shape.height,
              backgroundColor: element.backgroundColor,
              fillStyle: "solid",
              roundness: shape.kind === "ellipse" ? null : { type: shape.kind === "rectangle" ? 3 : 2 },
              ...look,
            },
          ] as never);
    if (!made1) continue;
    made.push(made1);
    gone.add(element.id);
  }
  if (gone.size === 0) return 0;
  editor.updateScene({
    elements: [...all.map((element) => (gone.has(element.id) ? newElementWith(element, { isDeleted: true }) : element)), ...made],
    captureUpdate: CaptureUpdateAction.IMMEDIATELY,
  });
  return gone.size;
}

/**
 * The top-left corner of a free square of `size` nearest to `center`, looked
 * for on rings around it (a grid of 20 px), clear of every box by a margin.
 */
export function freeSpot(
  taken: readonly { x: number; y: number; w: number; h: number }[],
  center: { x: number; y: number },
  size: number,
): { x: number; y: number } {
  const margin = 24;
  const step = 40;
  const snap = (value: number) => Math.round(value / 20) * 20;
  const free = (x: number, y: number) =>
    taken.every(
      (box) => x + size + margin <= box.x || box.x + box.w + margin <= x || y + size + margin <= box.y || box.y + box.h + margin <= y,
    );
  const start = { x: snap(center.x - size / 2), y: snap(center.y - size / 2) };
  if (free(start.x, start.y)) return start;
  for (let ring = 1; ring <= 40; ring += 1) {
    const candidates: { x: number; y: number }[] = [];
    for (let i = -ring; i <= ring; i += 1) {
      candidates.push(
        { x: start.x + i * step, y: start.y - ring * step },
        { x: start.x + i * step, y: start.y + ring * step },
        { x: start.x - ring * step, y: start.y + i * step },
        { x: start.x + ring * step, y: start.y + i * step },
      );
    }
    candidates.sort((a, b) => Math.hypot(a.x - start.x, a.y - start.y) - Math.hypot(b.x - start.x, b.y - start.y));
    const found = candidates.find((spot) => free(spot.x, spot.y));
    if (found) return found;
  }
  return start;
}
const NOTE_COLOR = "#ffec99";

/** Saving, saved, or not saved: a quiet word in the board's corner. */
function SaveStatus({ state, detail }: { state: SaveState; detail: string }) {
  const t = useT();
  if (state === "idle") return null;
  return (
    <span
      data-testid="whiteboard-save-state"
      data-state={state}
      role="status"
      title={state === "failed" && detail ? detail : undefined}
      className={
        "pointer-events-auto inline-flex h-9 items-center gap-1.5 whitespace-nowrap rounded-lg px-2.5 text-sm " +
        (state === "failed" ? "text-destructive" : "text-muted-foreground")
      }
    >
      {state === "saving" ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
      ) : state === "saved" ? (
        <Check className="h-3.5 w-3.5" aria-hidden />
      ) : (
        <AlertCircle className="h-3.5 w-3.5" aria-hidden />
      )}
      {state === "saving"
        ? t("nodes.whiteboard.saving")
        : state === "saved"
          ? t("nodes.whiteboard.saved")
          : t("nodes.whiteboard.save_failed")}
    </span>
  );
}
