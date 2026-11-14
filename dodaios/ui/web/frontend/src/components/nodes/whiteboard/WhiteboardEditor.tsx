/**
 * A whiteboard node on the stage: an infinite canvas to draw on.
 *
 * The canvas is the open-source editor `@excalidraw/excalidraw`, embedded
 * whole: shapes, arrows, text, freehand, pictures, frames, the library, the
 * Mermaid dialog, export to PNG and SVG files, zoom, grid. What reaches a web
 * service is left out or hidden (collaboration, the public library site, the
 * AI tools, web embeds, the project's links: see `whiteboard.css`), and its
 * fonts come from this app (`assetPath.ts`).
 *
 * The node's spec is the editor's scene. It is read once when the board
 * opens, and every change is saved back on its own after a short pause
 * (`BoardSync`): the person never presses "Save". The assistant draws on the
 * same board through its `whiteboard` tool; the stage reports when the node
 * changed (`revision`), and what the assistant drew is merged into the open
 * editor without taking away what the person is drawing or has selected.
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
  MainMenu,
  WelcomeScreen,
  reconcileElements,
  restoreElements,
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
  fetchScene,
  putScene,
  uploadBoardFile,
  type BoardElement,
  type SceneRead,
} from "./boardApi";
import { BoardSync, type EditorFile, type SaveState } from "./boardSync";
import { readBoardLibrary, writeBoardLibrary } from "./boardLibrary";

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
 * out as far as it takes, never in past 100 %).
 */
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
  const texts = editor
    .getSceneElements()
    .filter((element) => element.type === "text") as unknown as { fontFamily: number; text: string }[];
  const used = new Map<string, string>();
  for (const text of texts) {
    const name = FONT_NAMES.get(text.fontFamily);
    if (name) used.set(name, ((used.get(name) ?? "") + text.text).slice(0, 4000));
  }
  if (typeof document !== "undefined" && document.fonts && used.size > 0) {
    await Promise.allSettled(
      [...used].map(([name, sample]) => document.fonts.load(`20px "${name}"`, sample || undefined)),
    );
  }
  if (!alive()) return;
  if (used.size > 0) {
    editor.updateScene({
      elements: restoreFromServer(editor.getSceneElementsIncludingDeleted() as unknown as readonly BoardElement[]),
      captureUpdate: CaptureUpdateAction.NEVER,
    });
  }
  if (editor.getSceneElements().length > 0) editor.scrollToContent(undefined, { fitToContent: true, animate: false });
}

function describeError(error: unknown): string {
  return error instanceof NodesApiError ? error.detail : "";
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
  const assistant = useEventStore((s) => s.assistantName);
  const root = useRef<HTMLDivElement>(null);
  const api = useRef<ExcalidrawImperativeAPI | null>(null);
  const [save, setSave] = useState<{ state: SaveState; detail: string }>({ state: "idle", detail: "" });

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
            const merged = reconcileElements(
              editor.getSceneElementsIncludingDeleted(),
              restoreFromServer(elements) as RemoteExcalidrawElement[],
              editor.getAppState(),
            );
            editor.updateScene({
              elements: merged,
              appState: appState
                ? {
                    viewBackgroundColor: appState.viewBackgroundColor ?? editor.getAppState().viewBackgroundColor,
                    gridModeEnabled: Boolean(appState.gridModeEnabled),
                  }
                : undefined,
              // The assistant's strokes are not the person's to undo.
              captureUpdate: CaptureUpdateAction.NEVER,
            });
          },
          addFiles: (files) => api.current?.addFiles(files as BinaryFileData[]),
        },
        onState: (state, detail) => setSave({ state, detail }),
        describeError,
      }),
  );

  const initialData = useMemo<ExcalidrawInitialDataState>(
    () => ({
      elements: restoreFromServer(read.scene.elements),
      appState: {
        viewBackgroundColor: read.scene.appState.viewBackgroundColor ?? "#ffffff",
        gridModeEnabled: Boolean(read.scene.appState.gridModeEnabled),
      },
      scrollToContent: true,
      libraryItems: readBoardLibrary(),
    }),
    [read],
  );

  const onApi = useCallback(
    (editor: ExcalidrawImperativeAPI) => {
      api.current = editor;
      void sync.loadMissingFiles(read.scene.elements);
      const expectElements = read.scene.elements.some((element) => !element.isDeleted);
      void settleBoard(editor, () => api.current === editor, expectElements);
    },
    [sync, read],
  );

  const onChange = useCallback(
    (elements: readonly OrderedExcalidrawElement[], appState: AppState, files: BinaryFiles) => {
      // Belt and braces for the hidden web embed tool (a keyboard path, a
      // file opened from disk): the board keeps no element that frames the web.
      if (WEB_TOOLS.has(appState.activeTool.type)) {
        api.current?.setActiveTool({ type: "selection" });
      }
      sync.onChange({
        elements: elements as unknown as readonly BoardElement[],
        appState,
        files: files as unknown as Record<string, EditorFile>,
      });
    },
    [sync],
  );

  // The assistant (or another window) changed the node.
  useEffect(() => {
    if (revision !== null) void sync.onRevision(revision);
  }, [revision, sync]);

  // Unsaved strokes go out when the window hides or closes, and when the
  // board is left; the debounce would otherwise lose the last second.
  useEffect(() => {
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
      void sync.flush();
      sync.dispose();
    };
  }, [sync]);

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
    const keep = (event: KeyboardEvent) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      if (root.current?.contains(target) || target.closest(".excalidraw")) event.stopPropagation();
    };
    document.addEventListener("keydown", keep);
    document.addEventListener("keyup", keep);
    return () => {
      document.removeEventListener("keydown", keep);
      document.removeEventListener("keyup", keep);
    };
  }, []);

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

  const renderTopRightUI = useCallback(
    () => <SaveStatus state={save.state} detail={save.detail} />,
    [save.state, save.detail],
  );

  return (
    <div
      ref={root}
      className="dodaios-board h-full w-full"
      data-testid="whiteboard-editor"
      onBlur={(event) => {
        // Focus left the board for the app: save what is waiting.
        if (!root.current?.contains(event.relatedTarget as Node | null)) void sync.flush();
      }}
    >
      <Excalidraw
        excalidrawAPI={onApi}
        initialData={initialData}
        onChange={onChange}
        theme={theme === "dark" ? "dark" : "light"}
        langCode={EDITOR_LANGUAGE[language] ?? "en"}
        name={title}
        autoFocus
        aiEnabled={false}
        validateEmbeddable={() => false}
        onLinkOpen={onLinkOpen}
        onLibraryChange={onLibraryChange}
        renderTopRightUI={renderTopRightUI}
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
      >
        <MainMenu>
          <MainMenu.DefaultItems.LoadScene />
          <MainMenu.DefaultItems.SaveToActiveFile />
          <MainMenu.DefaultItems.Export />
          <MainMenu.DefaultItems.SaveAsImage />
          <MainMenu.DefaultItems.SearchMenu />
          <MainMenu.DefaultItems.CommandPalette />
          <MainMenu.DefaultItems.Help />
          <MainMenu.DefaultItems.ClearCanvas />
          <MainMenu.Separator />
          <MainMenu.DefaultItems.ChangeCanvasBackground />
        </MainMenu>
        <WelcomeScreen>
          <WelcomeScreen.Hints.MenuHint>{t("nodes.whiteboard.welcome.menu")}</WelcomeScreen.Hints.MenuHint>
          <WelcomeScreen.Hints.ToolbarHint>{t("nodes.whiteboard.welcome.toolbar")}</WelcomeScreen.Hints.ToolbarHint>
          <WelcomeScreen.Hints.HelpHint>{t("nodes.whiteboard.welcome.help")}</WelcomeScreen.Hints.HelpHint>
          <WelcomeScreen.Center>
            <WelcomeScreen.Center.Heading>{t("nodes.whiteboard.welcome.heading")}</WelcomeScreen.Center.Heading>
            <WelcomeScreen.Center.Heading>
              {t("nodes.whiteboard.welcome.assistant").replace("{assistant}", () => assistant || "Dodaios")}
            </WelcomeScreen.Center.Heading>
            <WelcomeScreen.Center.Menu>
              <WelcomeScreen.Center.MenuItemLoadScene />
              <WelcomeScreen.Center.MenuItemHelp />
            </WelcomeScreen.Center.Menu>
          </WelcomeScreen.Center>
        </WelcomeScreen>
      </Excalidraw>
    </div>
  );
}

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
