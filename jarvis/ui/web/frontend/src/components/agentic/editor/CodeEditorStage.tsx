import { Fragment, Suspense, lazy, useEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import { useShallow } from "zustand/react/shallow";
import {
  AlertTriangle,
  ChevronRight,
  Code2,
  Columns2,
  Copy,
  Eye,
  ExternalLink,
  FileDiff,
  FileText,
  FolderSearch,
  Loader2,
  SquareArrowOutUpRight,
  SquareTerminal,
  X,
} from "lucide-react";

import { fill, useT } from "@/i18n";
import { attachToTerminal, openTerminalTarget } from "@/lib/agenticIdeApi";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";
import { revealInExplorer } from "@/store/ideExplorer";
import { groupsOf, layoutFor, tabsOf, useCodeEditorStore, type EditorGroup, type EditorLayout, type EditorTab } from "@/store/codeEditor";
import { FileTypeIcon } from "@/components/agentic/sidePanel/explorer/FileTypeIcon";
import { absoluteWorkspacePath } from "@/components/agentic/sidePanel/explorer/explorerApi";
import { ThreadMenuHeading, ThreadMenuItem, ThreadMenuSeparator, ThreadPopover } from "@/components/agentic/threads/ThreadPopover";
import { checkDisk, discardFile, languageName, reopenWithEncoding, revertFile, saveAll, saveFile, setLineEnding } from "./editorModels";
import { ENCODINGS, encodingLabel } from "./encodings";
import { QuickOpen } from "./QuickOpen";
import { restoreWorkspace } from "./editorPersistence";
import { SEARCH_FOCUS_EVENT } from "@/components/agentic/sidePanel/search/SearchPanel";
import { useIdeSidePanelStore } from "@/store/ideSidePanel";
import { renderKindOf } from "./fileKinds";

const EditorSurface = lazy(() => import("./EditorSurface"));

/** How often the open file is compared with the disk while the editor is on screen. */
const DISK_POLL_MS = 3000;
const DISK_JITTER_MS = 1500;

/** How far the divider between two groups may be dragged, as a share of their joint width. */
const SPLIT_MIN = 0.15;
const SPLIT_MAX = 0.85;
const clampSplit = (ratio: number) => Math.min(SPLIT_MAX, Math.max(SPLIT_MIN, ratio));

/** A tab being dragged: within its tab bar, to another group, or out into a new one. */
const TAB_DRAG_TYPE = "application/x-jarvis-editor-tab";

type DropZone = "left" | "right" | "top" | "bottom" | "center";

/** The part of a group's text area a dropped tab would take. */
const ZONE_BOX: Record<DropZone, CSSProperties> = {
  left: { left: 8, right: "50%", top: 8, bottom: 8 },
  right: { left: "50%", right: 8, top: 8, bottom: 8 },
  top: { left: 8, right: 8, top: 8, bottom: "50%" },
  bottom: { left: 8, right: 8, top: "50%", bottom: 8 },
  center: { left: 8, right: 8, top: 8, bottom: 8 },
};

/** A stable name for a part of the layout, to remember its size under. */
const nodeKey = (node: EditorLayout): string =>
  typeof node === "number" ? `g${node}` : `${node.dir}(${node.children.map(nodeKey).join(",")})`;

/** The group in the top right corner, which carries the "Terminals" button. */
const cornerOf = (node: EditorLayout): number =>
  typeof node === "number" ? node : cornerOf(node.dir === "row" ? node.children[node.children.length - 1] : node.children[0]);
/** Where the dragged tab would land: a spot in a tab bar, or a zone of a group's text area. */
type DropHint = { group: number; before: number } | { group: number; zone: DropZone };

/** The index of the tab a pointer at `x` would insert in front of; the tab count = after the last. */
function insertionIndex(bar: HTMLElement, x: number): number {
  const tabs = bar.querySelectorAll<HTMLElement>('[data-testid="code-editor-tab"]');
  for (let index = 0; index < tabs.length; index += 1) {
    const rect = tabs[index].getBoundingClientRect();
    if (x < rect.left + rect.width / 2) return index;
  }
  return tabs.length;
}

const baseName = (path: string) => path.split("/").pop() ?? path;

interface PendingClose {
  keys: string[];
  fileKeys: string[];
}

function copyText(text: string): void {
  void navigator.clipboard?.writeText(text).catch((error: unknown) =>
    useEventStore.getState().pushToast("error", (error as Error).message),
  );
}

/**
 * The code editor, laid over the terminal grid of the Agentic IDE.
 *
 * It shows one or more editor groups, side by side or above each other. Each
 * group has its own tab bar, breadcrumbs and text; "Open to the side" adds
 * one, a dragged tab makes one where it is dropped, and closing a group's last
 * tab removes it. The group last clicked in has the
 * keyboard: opened files, shortcuts and the status bar go to it.
 *
 * Files open here from the side panel's Folder and Changes tabs, from a
 * Ctrl+click on a path in a terminal, and from Go to File (Ctrl+P). The
 * terminals stay mounted underneath; "Terminals" in the tab bar brings them
 * back without closing a tab.
 */
export function CodeEditorStage({
  workspaceId,
  workspacePath,
  stagedPane,
}: {
  workspaceId: string | null;
  workspacePath: string;
  stagedPane: string | null;
}) {
  const t = useT();
  const stage = useRef<HTMLDivElement>(null);
  const tabs = useCodeEditorStore(useShallow((state) => tabsOf(state, workspaceId)));
  const activeKey = useCodeEditorStore((state) => (workspaceId ? (state.active[workspaceId] ?? null) : null));
  const storedLayout = useCodeEditorStore((state) => (workspaceId ? state.layout[workspaceId] : undefined));
  const groupActive = useCodeEditorStore((state) => (workspaceId ? state.groupActive[workspaceId] : undefined));
  const focusedGroupId = useCodeEditorStore((state) => (workspaceId ? state.focusedGroup[workspaceId] : undefined));
  const visible = useCodeEditorStore((state) => state.visible);
  const quickOpen = useCodeEditorStore((state) => state.quickOpen);
  const files = useCodeEditorStore((state) => state.files);
  const diffBases = useCodeEditorStore((state) => state.diffBases);
  const [pending, setPending] = useState<PendingClose | null>(null);
  const [menu, setMenu] = useState<EditorTab | null>(null);
  // Each part of the layout's share of its split, as a weight; one never resized has 1.
  const [weights, setWeights] = useState<Readonly<Record<string, number>>>({});
  const dragging = useRef(false);
  // The tab being dragged, and where it would land if dropped now.
  const [dragKey, setDragKey] = useState<string | null>(null);
  const [dropHint, setDropHint] = useState<DropHint | null>(null);
  // Tabs whose Markdown, HTML or SVG is shown rendered (Ctrl+Shift+V).
  const [rendered, setRendered] = useState<ReadonlySet<string>>(() => new Set());
  const toggleRendered = (key: string) =>
    setRendered((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  const toggleRenderedRef = useRef(toggleRendered);
  toggleRenderedRef.current = toggleRendered;
  const menuAnchor = useRef<HTMLElement | null>(null);
  const pushToast = useEventStore((state) => state.pushToast);

  const groups = useMemo(
    () =>
      workspaceId
        ? groupsOf(
            {
              tabs,
              layout: storedLayout === undefined ? {} : { [workspaceId]: storedLayout },
              groupActive: { [workspaceId]: groupActive ?? {} },
              focusedGroup: focusedGroupId === undefined ? {} : { [workspaceId]: focusedGroupId },
            },
            workspaceId,
          )
        : [],
    [workspaceId, tabs, storedLayout, groupActive, focusedGroupId],
  );
  const tree = useMemo(
    () =>
      layoutFor(
        storedLayout,
        groups.filter((group) => group.tabs.length > 0).map((group) => group.id),
      ),
    [storedLayout, groups],
  );
  // The tab of the group that has the keyboard: what shortcuts and the status bar act on.
  const activeTab = tabs.find((tab) => tab.key === activeKey) ?? groups.find((group) => group.focused)?.active ?? null;
  const shown = visible && activeTab !== null;

  // Reopen what this workspace had open last run, unsaved text included.
  useEffect(() => {
    if (workspaceId) void restoreWorkspace(workspaceId);
  }, [workspaceId]);

  // Closing the last tab hands the stage back to the terminals.
  useEffect(() => {
    if (visible && workspaceId && tabs.length === 0) useCodeEditorStore.getState().setVisible(false);
  }, [visible, workspaceId, tabs.length]);

  /** Close tabs, asking first when that would throw away unsaved edits. */
  const requestClose = (keys: string[]) => {
    const state = useCodeEditorStore.getState();
    const closing = new Set(keys);
    const remaining = new Set(state.tabs.filter((tab) => !closing.has(tab.key)).map((tab) => tab.fileKey));
    const fileKeys = [
      ...new Set(
        state.tabs
          .filter((tab) => closing.has(tab.key) && !remaining.has(tab.fileKey) && state.files[tab.fileKey]?.dirty)
          .map((tab) => tab.fileKey),
      ),
    ];
    if (fileKeys.length === 0) state.closeTabs(keys);
    else setPending({ keys, fileKeys });
  };

  const requestCloseRef = useRef(requestClose);
  requestCloseRef.current = requestClose;

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!workspaceId || !(event.ctrlKey || event.metaKey) || event.altKey) return;
      if (useEventStore.getState().activeSection !== "agentic-ide") return;
      const target = event.target instanceof HTMLElement ? event.target : null;
      // A terminal keeps every Ctrl key for its shell (Ctrl+P, Ctrl+W, …).
      if (target?.closest(".xterm")) return;
      const key = event.key.toLowerCase();
      const state = useCodeEditorStore.getState();
      if (key === "p" && !event.shiftKey) {
        // A text field outside the editor (a rename box, the chat composer)
        // keeps its keys; the editor's own text area does not count as one.
        const field = target?.closest("input, textarea, [contenteditable='true']");
        if (field && !stage.current?.contains(field)) return;
        event.preventDefault();
        event.stopPropagation();
        state.setQuickOpen(true);
        return;
      }
      if (key === "f" && event.shiftKey) {
        // Search in all files lives in the side panel, like the explorer.
        event.preventDefault();
        event.stopPropagation();
        useIdeSidePanelStore.getState().openTab("search");
        window.setTimeout(() => window.dispatchEvent(new Event(SEARCH_FOCUS_EVENT)), 0);
        return;
      }
      const host = stage.current;
      if (!state.visible || !host) return;
      if (target && target !== document.body && !host.contains(target)) return;
      const own = tabsOf(state, workspaceId);
      // Keys go to the group that has the keyboard.
      const current = own.find((tab) => tab.key === state.active[workspaceId]) ?? own[own.length - 1];
      if (!current) return;
      const handled = () => {
        event.preventDefault();
        event.stopPropagation();
      };
      if (key === "s") {
        handled();
        if (event.shiftKey) void saveAll(workspaceId);
        else void saveFile(current.fileKey);
      } else if (key === "w" && !event.shiftKey) {
        handled();
        requestCloseRef.current([current.key]);
      } else if (key === "tab" || key === "pagedown" || key === "pageup") {
        handled();
        state.cycle(workspaceId, event.shiftKey || key === "pageup" ? -1 : 1);
      } else if (key === "t" && event.shiftKey) {
        handled();
        state.reopenClosed(workspaceId);
      } else if (key === "v" && event.shiftKey && current.mode === "edit" && renderKindOf(current.path)) {
        handled();
        toggleRenderedRef.current(current.key);
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [workspaceId]);

  // Notice an agent's edit to the open files: on a timer and when the window regains focus.
  const watchedFileKeys = shown ? [...new Set(groups.flatMap((group) => (group.active ? [group.active.fileKey] : [])))].join("\n") : "";
  useEffect(() => {
    if (!watchedFileKeys) return;
    let alive = true;
    let timer: number | undefined;
    const check = () => {
      if (document.visibilityState === "visible" && useEventStore.getState().activeSection === "agentic-ide") {
        for (const fileKey of watchedFileKeys.split("\n")) void checkDisk(fileKey);
      }
    };
    const tick = () => {
      check();
      if (alive) timer = window.setTimeout(tick, DISK_POLL_MS + Math.random() * DISK_JITTER_MS);
    };
    timer = window.setTimeout(tick, DISK_POLL_MS);
    window.addEventListener("focus", check);
    return () => {
      alive = false;
      window.clearTimeout(timer);
      window.removeEventListener("focus", check);
    };
  }, [watchedFileKeys]);

  const duplicateNames = useMemo(() => {
    // Two different files with one name get their folder beside it; the edit
    // and diff tab of one file do not.
    const counts = new Map<string, number>();
    for (const path of new Set(tabs.map((tab) => tab.path))) counts.set(baseName(path), (counts.get(baseName(path)) ?? 0) + 1);
    return counts;
  }, [tabs]);

  if (!workspaceId) return null;

  const openExternally = (path: string) =>
    void openTerminalTarget(workspaceId, path).catch((error: unknown) => pushToast("error", (error as Error).message));
  const absolute = (path: string) => absoluteWorkspacePath(workspacePath, path);

  const quick = quickOpen ? <QuickOpen workspaceId={workspaceId} /> : null;
  if (!shown) return quick;

  const store = useCodeEditorStore.getState();
  const starting = (
    <p className="flex h-full items-center justify-center gap-2 text-sm text-muted-foreground">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
      {t("code_editor.starting")}
    </p>
  );
  const focusTab = activeTab;

  const weightOf = (node: EditorLayout) => weights[nodeKey(node)] ?? 1;
  /** Move the divider between two neighbours of a split; their joint size stays. */
  const resizePair = (first: EditorLayout, second: EditorLayout, ratio: number) => {
    const total = weightOf(first) + weightOf(second);
    const share = clampSplit(ratio);
    setWeights((current) => ({ ...current, [nodeKey(first)]: total * share, [nodeKey(second)]: total * (1 - share) }));
  };
  const dragDivider = (event: ReactPointerEvent<HTMLDivElement>, first: EditorLayout, second: EditorLayout, dir: "row" | "column") => {
    if (!dragging.current) return;
    const before = event.currentTarget.previousElementSibling?.getBoundingClientRect();
    const after = event.currentTarget.nextElementSibling?.getBoundingClientRect();
    if (!before || !after) return;
    const [start, end, at] = dir === "row" ? [before.left, after.right, event.clientX] : [before.top, after.bottom, event.clientY];
    if (end > start) resizePair(first, second, (at - start) / (end - start));
  };

  const draggedTab = dragKey ? (tabs.find((tab) => tab.key === dragKey) ?? null) : null;
  const endDrag = () => {
    setDragKey(null);
    setDropHint(null);
  };
  /** Whether dropping the dragged tab on this zone of a group's text changes anything. */
  const zoneTakes = (group: EditorGroup, zone: DropZone) => {
    if (!draggedTab) return false;
    const own = draggedTab.group === group.id;
    // The middle moves the tab into the group; a side opens a new group there.
    return zone === "center" ? !own : !(own && group.tabs.length === 1);
  };
  /** The zone of a group's text area under the pointer. */
  const zoneAt = (group: EditorGroup, area: HTMLElement, x: number, y: number): DropZone => {
    const rect = area.getBoundingClientRect();
    const across = rect.width > 0 ? (x - rect.left) / rect.width : 0.5;
    const down = rect.height > 0 ? (y - rect.top) / rect.height : 0.5;
    // The middle takes the tab into the group; outside it, the nearest edge
    // wins. A group's own tab can only go to an edge.
    const inMiddle = across > 1 / 3 && across < 2 / 3 && down > 1 / 3 && down < 2 / 3;
    if (inMiddle && zoneTakes(group, "center")) return "center";
    const edges: [DropZone, number][] = [
      ["left", across],
      ["right", 1 - across],
      ["top", down],
      ["bottom", 1 - down],
    ];
    return edges.reduce((best, edge) => (edge[1] < best[1] ? edge : best))[0];
  };

  const renderGroup = (group: EditorGroup) => {
    const shownTab = group.active;
    if (!shownTab) return null;
    const hint = dropHint?.group === group.id ? dropHint : null;
    const marker = hint && "before" in hint ? hint.before : -1;
    const zone = hint && "zone" in hint ? hint.zone : null;
    const shownFile = files[shownTab.fileKey];
    const segments = shownTab.path.split("/");
    const last = group.id === cornerOf(tree);
    return (
      <section
        key={group.id}
        aria-label={fill(t("code_editor.group_label"), { n: String(groups.indexOf(group) + 1) })}
        data-testid="code-editor-group"
        data-group={group.id}
        data-path={shownTab.path}
        data-focused={group.focused || undefined}
        className="flex min-h-0 min-w-0 flex-col"
        style={{ flex: `${weightOf(group.id)} 1 0%` }}
        onFocusCapture={() => store.focusGroup(workspaceId, group.id)}
        onPointerDownCapture={() => store.focusGroup(workspaceId, group.id)}
      >
        {/* Tab bar */}
        <div
          data-testid="code-editor-tabbar"
          className="flex h-9 shrink-0 items-stretch border-b border-border/70 bg-sidebar"
          // A dragged tab lands in front of the tab under the pointer, or at the end.
          onDragOver={(event) => {
            if (!event.dataTransfer.types.includes(TAB_DRAG_TYPE)) return;
            event.preventDefault();
            event.dataTransfer.dropEffect = "move";
            const before = insertionIndex(event.currentTarget, event.clientX);
            if (marker !== before) setDropHint({ group: group.id, before });
          }}
          onDragLeave={(event) => {
            if (marker >= 0 && !event.currentTarget.contains(event.relatedTarget as Node | null)) setDropHint(null);
          }}
          onDrop={(event) => {
            const key = event.dataTransfer.getData(TAB_DRAG_TYPE);
            if (!key) return;
            event.preventDefault();
            const before = group.tabs[insertionIndex(event.currentTarget, event.clientX)]?.key;
            endDrag();
            store.moveTab(key, { group: group.id, before });
          }}
        >
          <div role="tablist" aria-label={t("code_editor.tabs")} className="scrollbar-none flex min-w-0 flex-1 items-stretch overflow-x-auto">
            {group.tabs.map((tab, position) => {
              const file = files[tab.fileKey];
              const active = tab.key === shownTab.key;
              const name = baseName(tab.path);
              const folder = tab.path.split("/").slice(-2, -1)[0];
              return (
                <div
                  key={tab.key}
                  role="tab"
                  aria-selected={active}
                  data-testid="code-editor-tab"
                  data-path={tab.path}
                  data-preview={tab.preview || undefined}
                  data-dirty={file?.dirty || undefined}
                  tabIndex={0}
                  draggable
                  data-dragging={dragKey === tab.key || undefined}
                  onDragStart={(event) => {
                    event.dataTransfer.setData(TAB_DRAG_TYPE, tab.key);
                    event.dataTransfer.effectAllowed = "move";
                    // Once the browser has taken its picture of the tab: the
                    // drop zones come up over every group's text.
                    window.setTimeout(() => setDragKey(tab.key), 0);
                  }}
                  onDragEnd={endDrag}
                  title={tab.path}
                  onClick={() => store.activate(tab.key)}
                  onDoubleClick={() => store.pinTab(tab.key)}
                  onAuxClick={(event) => {
                    if (event.button === 1) {
                      event.preventDefault();
                      requestClose([tab.key]);
                    }
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") store.activate(tab.key);
                  }}
                  onContextMenu={(event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    menuAnchor.current = event.currentTarget;
                    setMenu(tab);
                  }}
                  className={cn(
                    "group relative flex min-w-0 max-w-[220px] shrink-0 cursor-pointer items-center gap-1.5 border-r border-border/50 pl-3 pr-1.5 text-[13px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring data-[dragging]:opacity-50",
                    active ? "bg-background text-foreground-strong" : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
                  )}
                >
                  {active && <span className={cn("absolute inset-x-0 top-0 h-px", group.focused ? "bg-primary" : "bg-muted-foreground/50")} aria-hidden />}
                  {marker === position && <span className="pointer-events-none absolute inset-y-1 left-0 z-10 w-0.5 rounded bg-primary" aria-hidden />}
                  {tab.mode === "diff" ? <FileDiff className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden /> : <FileTypeIcon path={tab.path} />}
                  <span className={cn("truncate", tab.preview && "italic", file?.deleted && "line-through decoration-destructive/70")}>{name}</span>
                  {(duplicateNames.get(name) ?? 0) > 1 && folder && <span className="shrink-0 truncate text-[11px] text-muted-foreground">{folder}</span>}
                  <button
                    type="button"
                    aria-label={fill(t("code_editor.close_tab"), { file: name })}
                    title={t("code_editor.close_tab_hint")}
                    onClick={(event) => {
                      event.stopPropagation();
                      requestClose([tab.key]);
                    }}
                    className="group/close relative inline-flex h-5 w-5 shrink-0 items-center justify-center rounded text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    {file?.dirty ? (
                      <>
                        <span className="h-2 w-2 rounded-full bg-foreground/70 group-hover/close:hidden" aria-hidden />
                        <X className="hidden h-3.5 w-3.5 group-hover/close:block" aria-hidden />
                      </>
                    ) : (
                      <X className={cn("h-3.5 w-3.5", !active && "opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100")} aria-hidden />
                    )}
                  </button>
                </div>
              );
            })}
            {marker === group.tabs.length && <span className="pointer-events-none my-1 w-0.5 shrink-0 rounded bg-primary" aria-hidden />}
          </div>
          <button
            type="button"
            data-testid="code-editor-split"
            aria-label={t("code_editor.split_right")}
            title={t("code_editor.split_right")}
            onClick={() => store.splitRight(shownTab.key)}
            className="inline-flex w-8 shrink-0 items-center justify-center text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
          >
            <Columns2 className="h-3.5 w-3.5" aria-hidden />
          </button>
          {last && (
            <button
              type="button"
              data-testid="code-editor-hide"
              onClick={() => store.setVisible(false)}
              title={t("code_editor.show_terminals_hint")}
              className="inline-flex shrink-0 items-center gap-1.5 border-l border-border/60 px-3 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
            >
              <SquareTerminal className="h-3.5 w-3.5" aria-hidden />
              {t("code_editor.show_terminals")}
            </button>
          )}
        </div>

        {/* Breadcrumbs and file actions */}
        <div className="flex h-8 shrink-0 items-center gap-2 border-b border-border/50 px-3 text-xs text-muted-foreground">
          <nav aria-label={t("code_editor.breadcrumbs")} className="flex min-w-0 flex-1 items-center gap-0.5 overflow-hidden">
            {segments.map((segment, index) => (
              <span key={`${segment}-${index}`} className="flex min-w-0 shrink items-center gap-0.5">
                {index > 0 && <ChevronRight className="h-3 w-3 shrink-0 opacity-60" aria-hidden />}
                <span className={cn("truncate", index === segments.length - 1 && "text-foreground")}>{segment}</span>
              </span>
            ))}
            {shownTab.mode === "diff" && <span className="ml-1.5 shrink-0 rounded bg-secondary px-1.5 py-px text-[11px]">{diffBases[shownTab.fileKey]?.label ?? t("code_editor.diff_badge")}</span>}
          </nav>
          {shownTab.mode === "edit" && shownFile?.status === "ready" && renderKindOf(shownTab.path) && (
            <ActionButton
              onClick={() => toggleRendered(shownTab.key)}
              icon={rendered.has(shownTab.key) ? <Code2 className="h-3.5 w-3.5" aria-hidden /> : <Eye className="h-3.5 w-3.5" aria-hidden />}
              label={rendered.has(shownTab.key) ? t("code_editor.show_source") : t("code_editor.preview")}
              hint="Ctrl+Shift+V"
              wide
            />
          )}
          {/* A text comparison only means something for a text file. */}
          {(shownTab.mode === "diff" || shownFile?.status === "ready") && (
            <ActionButton
              onClick={() => store.openFile(workspaceId, shownTab.path, { mode: shownTab.mode === "diff" ? "edit" : "diff", preview: false })}
              icon={shownTab.mode === "diff" ? <FileText className="h-3.5 w-3.5" aria-hidden /> : <FileDiff className="h-3.5 w-3.5" aria-hidden />}
              label={shownTab.mode === "diff" ? t("code_editor.open_file") : t("code_editor.open_changes")}
            />
          )}
          {stagedPane && (
            <ActionButton
              onClick={() =>
                void attachToTerminal(stagedPane, { paths: [absolute(shownTab.path)] }).catch((error: unknown) =>
                  pushToast("error", (error as Error).message),
                )
              }
              icon={<SquareArrowOutUpRight className="h-3.5 w-3.5" aria-hidden />}
              label={fill(t("code_editor.reference_in"), { pane: stagedPane })}
            />
          )}
          <ActionButton
            onClick={() => openExternally(shownTab.path)}
            icon={<ExternalLink className="h-3.5 w-3.5" aria-hidden />}
            label={t("code_editor.open_externally")}
            iconOnly
          />
        </div>

        {shownFile?.conflict && (
          <Banner tone="warning" testId="code-editor-conflict" text={t("code_editor.conflict")}>
            <BannerButton onClick={() => void revertFile(shownTab.fileKey)}>{t("code_editor.conflict_load_disk")}</BannerButton>
            <BannerButton onClick={() => void saveFile(shownTab.fileKey, { overwrite: true })}>{t("code_editor.conflict_keep_mine")}</BannerButton>
          </Banner>
        )}
        {shownFile?.mixedEol && !shownFile.conflict && (
          <Banner
            tone="muted"
            testId="code-editor-mixed-eol"
            text={fill(t("code_editor.mixed_eol"), { eol: shownFile.eol === "\r\n" ? "CRLF" : "LF" })}
          />
        )}
        {shownFile?.deleted && !shownFile.conflict && (
          <Banner tone="muted" testId="code-editor-deleted" text={t("code_editor.deleted")} />
        )}

        <div className="relative min-h-0 flex-1">
          <Suspense fallback={starting}>
            <EditorSurface
              tab={shownTab}
              rendered={rendered.has(shownTab.key)}
              focused={group.focused}
              secondary={groups.length > 1}
              onOpenExternally={openExternally}
            />
          </Suspense>
          {/* While a tab is dragged, the text area takes the drop: its middle
              moves the tab into this group, each of its four sides opens a
              new group there. Laid over the editor so the text never sees it. */}
          {draggedTab && (zoneTakes(group, "center") || zoneTakes(group, "left")) && (
            <div
              data-testid="code-editor-drop"
              data-zone={zone ?? undefined}
              className="absolute inset-0 z-10"
              onDragOver={(event) => {
                if (!event.dataTransfer.types.includes(TAB_DRAG_TYPE)) return;
                const next = zoneAt(group, event.currentTarget, event.clientX, event.clientY);
                event.preventDefault();
                event.dataTransfer.dropEffect = "move";
                if (zone !== next) setDropHint({ group: group.id, zone: next });
              }}
              onDragLeave={() => {
                if (zone) setDropHint(null);
              }}
              onDrop={(event) => {
                const key = event.dataTransfer.getData(TAB_DRAG_TYPE);
                if (!key) return;
                event.preventDefault();
                // Where the pointer is now, not where the last painted hint was.
                const landed = zoneAt(group, event.currentTarget, event.clientX, event.clientY);
                endDrag();
                store.moveTab(key, landed === "center" ? { group: group.id } : { beside: group.id, side: landed });
              }}
            >
              <div className="pointer-events-none absolute inset-1 rounded-lg border-2 border-dashed border-primary/30" aria-hidden />
              {zone && (
                <div
                  aria-hidden
                  className="pointer-events-none absolute rounded-md bg-primary/25 ring-2 ring-primary transition-all duration-150 motion-reduce:transition-none"
                  style={ZONE_BOX[zone]}
                />
              )}
            </div>
          )}
        </div>
      </section>
    );
  };

  /** A group, or a split with a draggable divider between each two of its parts. */
  const renderNode = (node: EditorLayout): ReactNode => {
    if (typeof node === "number") {
      const group = groups.find((entry) => entry.id === node);
      return group ? renderGroup(group) : null;
    }
    const row = node.dir === "row";
    return (
      <div
        key={nodeKey(node)}
        data-testid="code-editor-layout"
        data-dir={node.dir}
        className={cn("flex min-h-0 min-w-0", row ? "flex-row" : "flex-col")}
        style={{ flex: `${weightOf(node)} 1 0%` }}
      >
        {node.children.map((child, index) => {
          const previous = node.children[index - 1];
          return (
            <Fragment key={nodeKey(child)}>
              {previous !== undefined && (
                <div
                  role="separator"
                  aria-orientation={row ? "vertical" : "horizontal"}
                  aria-label={t("code_editor.resize_split")}
                  tabIndex={0}
                  title={t("code_editor.resize_split")}
                  data-testid="code-editor-split-handle"
                  onPointerDown={(event) => {
                    event.preventDefault();
                    dragging.current = true;
                    event.currentTarget.setPointerCapture?.(event.pointerId);
                  }}
                  onPointerMove={(event) => dragDivider(event, previous, child, node.dir)}
                  onPointerUp={(event) => {
                    dragging.current = false;
                    event.currentTarget.releasePointerCapture?.(event.pointerId);
                  }}
                  onPointerCancel={() => {
                    dragging.current = false;
                  }}
                  onDoubleClick={() => resizePair(previous, child, 0.5)}
                  onKeyDown={(event) => {
                    const back = row ? "ArrowLeft" : "ArrowUp";
                    const forth = row ? "ArrowRight" : "ArrowDown";
                    if (event.key !== back && event.key !== forth) return;
                    event.preventDefault();
                    const share = weightOf(previous) / (weightOf(previous) + weightOf(child));
                    resizePair(previous, child, share + (event.key === back ? -0.05 : 0.05));
                  }}
                  className={cn(
                    "shrink-0 bg-border/70 transition-colors hover:bg-primary/60 focus-visible:bg-primary/60 focus-visible:outline-none",
                    row ? "w-1 cursor-col-resize" : "h-1 cursor-row-resize",
                  )}
                />
              )}
              {renderNode(child)}
            </Fragment>
          );
        })}
      </div>
    );
  };

  return (
    <>
      <div
        ref={stage}
        data-testid="code-editor"
        data-path={focusTab.path}
        className="absolute inset-0 z-20 flex min-h-0 flex-col bg-background"
      >
        <div className="flex min-h-0 flex-1">{renderNode(tree)}</div>

        <StatusBar fileKey={focusTab.fileKey} />
      </div>

      <ThreadPopover anchor={menuAnchor} open={menu !== null} onClose={() => setMenu(null)} label={t("code_editor.tab_menu")} width={230}>
        {menu && (
          <div role="menu">
            <ThreadMenuItem icon={<X className="h-4 w-4" />} label={t("code_editor.menu.close")} hint="Ctrl+W" onSelect={() => { setMenu(null); requestClose([menu.key]); }} />
            <ThreadMenuItem icon={<span aria-hidden />} label={t("code_editor.menu.close_others")} onSelect={() => { setMenu(null); requestClose(tabs.filter((tab) => tab.group === menu.group && tab.key !== menu.key).map((tab) => tab.key)); }} />
            <ThreadMenuItem icon={<span aria-hidden />} label={t("code_editor.menu.close_saved")} onSelect={() => { setMenu(null); requestClose(tabs.filter((tab) => tab.group === menu.group && !files[tab.fileKey]?.dirty).map((tab) => tab.key)); }} />
            <ThreadMenuItem icon={<span aria-hidden />} label={t("code_editor.menu.close_all")} onSelect={() => { setMenu(null); requestClose(tabs.filter((tab) => tab.group === menu.group).map((tab) => tab.key)); }} />
            <ThreadMenuSeparator />
            <ThreadMenuItem icon={<Columns2 className="h-4 w-4" />} label={t("code_editor.split_right")} onSelect={() => { setMenu(null); store.splitRight(menu.key); }} />
            <ThreadMenuSeparator />
            <ThreadMenuItem icon={<Copy className="h-4 w-4" />} label={t("code_editor.menu.copy_path")} onSelect={() => { setMenu(null); copyText(absolute(menu.path)); }} />
            <ThreadMenuItem icon={<span aria-hidden />} label={t("code_editor.menu.copy_relative_path")} onSelect={() => { setMenu(null); copyText(menu.path); }} />
            <ThreadMenuItem icon={<FolderSearch className="h-4 w-4" />} label={t("code_editor.menu.reveal")} onSelect={() => { setMenu(null); revealInExplorer({ workspaceId, path: menu.path }); }} />
          </div>
        )}
      </ThreadPopover>

      {pending && (
        <UnsavedDialog
          count={pending.fileKeys.length}
          name={baseName(files[pending.fileKeys[0]]?.path ?? "")}
          onCancel={() => setPending(null)}
          onDiscard={() => {
            for (const key of pending.fileKeys) discardFile(key);
            useCodeEditorStore.getState().closeTabs(pending.keys);
            setPending(null);
          }}
          onSave={async () => {
            const results = await Promise.all(pending.fileKeys.map((key) => saveFile(key)));
            setPending(null);
            if (results.every(Boolean)) useCodeEditorStore.getState().closeTabs(pending.keys);
          }}
        />
      )}
      {quick}
    </>
  );
}

function ActionButton({
  onClick,
  icon,
  label,
  hint,
  iconOnly = false,
  wide = false,
}: {
  onClick: () => void;
  icon: ReactNode;
  label: string;
  hint?: string;
  iconOnly?: boolean;
  /** Keep the label visible at every window width. */
  wide?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={hint ? `${label} (${hint})` : label}
      aria-label={label}
      className="inline-flex h-6 shrink-0 items-center gap-1.5 rounded px-1.5 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      {icon}
      {!iconOnly && <span className={wide ? "inline" : "hidden xl:inline"}>{label}</span>}
    </button>
  );
}

function Banner({ tone, text, testId, children }: { tone: "warning" | "muted"; text: string; testId: string; children?: ReactNode }) {
  return (
    <div
      role="status"
      data-testid={testId}
      className={cn(
        "flex shrink-0 flex-wrap items-center gap-2 border-b px-3 py-1.5 text-xs",
        tone === "warning" ? "border-warning/40 bg-warning/10 text-foreground" : "border-border/60 bg-secondary/60 text-muted-foreground",
      )}
    >
      <AlertTriangle className={cn("h-3.5 w-3.5 shrink-0", tone === "warning" ? "text-warning" : "text-muted-foreground")} aria-hidden />
      <span className="min-w-0 flex-1">{text}</span>
      {children}
    </div>
  );
}

function BannerButton({ onClick, children }: { onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex h-6 items-center rounded-md border border-border bg-background px-2 text-xs text-foreground hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      {children}
    </button>
  );
}

function StatusBar({ fileKey }: { fileKey: string }) {
  const t = useT();
  const file = useCodeEditorStore((state) => state.files[fileKey]);
  const cursor = useCodeEditorStore((state) => state.cursor);
  const [menu, setMenu] = useState<"encoding" | "eol" | null>(null);
  const anchor = useRef<HTMLElement | null>(null);
  if (!file) return null;
  const ready = file.status === "ready" && cursor;
  const openMenu = (kind: "encoding" | "eol", target: HTMLElement) => {
    anchor.current = target;
    setMenu(kind);
  };
  const statusButton =
    "rounded px-1 hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
  return (
    <div
      data-testid="code-editor-status"
      className="flex h-6 shrink-0 items-center gap-3 border-t border-border/60 bg-sidebar px-3 text-[11px] tabular-nums text-muted-foreground"
    >
      <span className="min-w-0 flex-1 truncate">
        {file.saving ? t("code_editor.status.saving") : file.dirty ? t("code_editor.status.unsaved") : file.status === "ready" ? t("code_editor.status.saved") : ""}
      </span>
      {ready && (
        <>
          <span>
            {fill(t("code_editor.status.position"), { line: String(cursor.line), column: String(cursor.column) })}
            {cursor.selected > 0 && ` ${fill(t("code_editor.status.selected"), { count: String(cursor.selected) })}`}
          </span>
          <span>{cursor.insertSpaces ? fill(t("code_editor.status.spaces"), { size: String(cursor.tabSize) }) : fill(t("code_editor.status.tabs"), { size: String(cursor.tabSize) })}</span>
          <button
            type="button"
            data-testid="code-editor-encoding"
            title={t("code_editor.status.change_encoding")}
            onClick={(event) => openMenu("encoding", event.currentTarget)}
            className={statusButton}
          >
            {encodingLabel(file.encoding)}
          </button>
          <button
            type="button"
            data-testid="code-editor-eol"
            title={t("code_editor.status.line_endings")}
            onClick={(event) => openMenu("eol", event.currentTarget)}
            className={statusButton}
          >
            {file.eol === "\r\n" ? "CRLF" : "LF"}
          </button>
          <span>{languageName(cursor.language)}</span>
        </>
      )}
      <ThreadPopover
        anchor={anchor}
        open={menu !== null}
        onClose={() => setMenu(null)}
        side="top"
        align="end"
        width={menu === "encoding" ? 300 : 200}
        label={menu === "encoding" ? t("code_editor.status.change_encoding") : t("code_editor.status.line_endings")}
      >
        {menu === "eol" && (
          <div role="menu">
            {(["\n", "\r\n"] as const).map((eol) => (
              <ThreadMenuItem
                key={eol}
                label={eol === "\r\n" ? "CRLF (Windows)" : "LF (macOS, Linux)"}
                selected={file.eol === eol}
                onSelect={() => {
                  setMenu(null);
                  setLineEnding(fileKey, eol);
                }}
              />
            ))}
          </div>
        )}
        {menu === "encoding" && (
          <div role="menu" data-testid="code-editor-encoding-menu">
            <ThreadMenuHeading>{t("code_editor.status.save_with")}</ThreadMenuHeading>
            {ENCODINGS.map((entry) => (
              <ThreadMenuItem
                key={`save-${entry.id}`}
                label={entry.label}
                selected={file.encoding === entry.id}
                onSelect={() => {
                  setMenu(null);
                  void saveFile(fileKey, { encoding: entry.id });
                }}
              />
            ))}
            <ThreadMenuSeparator />
            <ThreadMenuHeading>{t("code_editor.status.reopen_with")}</ThreadMenuHeading>
            {ENCODINGS.map((entry) => (
              <ThreadMenuItem
                key={`reopen-${entry.id}`}
                label={entry.label}
                disabled={file.dirty}
                onSelect={() => {
                  setMenu(null);
                  void reopenWithEncoding(fileKey, entry.id);
                }}
              />
            ))}
          </div>
        )}
      </ThreadPopover>
    </div>
  );
}

function UnsavedDialog({
  count,
  name,
  onSave,
  onDiscard,
  onCancel,
}: {
  count: number;
  name: string;
  onSave: () => void;
  onDiscard: () => void;
  onCancel: () => void;
}) {
  const t = useT();
  const saveButton = useRef<HTMLButtonElement>(null);
  useEffect(() => saveButton.current?.focus(), []);
  return (
    <div
      role="presentation"
      className="fixed inset-0 z-[86] flex items-center justify-center bg-background/60 p-4"
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.stopPropagation();
          onCancel();
        }
      }}
    >
      <section
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="code-editor-unsaved-title"
        data-testid="code-editor-unsaved"
        className="w-full max-w-sm rounded-xl border border-border bg-popover p-4 text-popover-foreground shadow-float"
      >
        <h2 id="code-editor-unsaved-title" className="text-sm font-semibold text-foreground-strong">
          {count === 1 ? fill(t("code_editor.unsaved.title_one"), { file: name }) : fill(t("code_editor.unsaved.title_many"), { count: String(count) })}
        </h2>
        <p className="mt-1.5 text-xs text-muted-foreground">{t("code_editor.unsaved.body")}</p>
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" onClick={onCancel} className="h-8 rounded-md px-3 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            {t("code_editor.unsaved.cancel")}
          </button>
          <button type="button" onClick={onDiscard} className="h-8 rounded-md border border-border px-3 text-xs text-foreground hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            {t("code_editor.unsaved.discard")}
          </button>
          <button ref={saveButton} type="button" onClick={onSave} className="h-8 rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            {t("code_editor.unsaved.save")}
          </button>
        </div>
      </section>
    </div>
  );
}
