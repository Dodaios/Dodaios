import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent, type KeyboardEvent as ReactKeyboardEvent, type MouseEvent as ReactMouseEvent, type ReactNode } from "react";
import {
  ChevronRight,
  ChevronsDownUp,
  ClipboardPaste,
  Columns2,
  Copy,
  CopyPlus,
  ExternalLink,
  FileDiff,
  FilePlus,
  Folder,
  FolderOpen,
  FolderPlus,
  FolderSearch,
  GitBranch,
  GitCompareArrows,
  Loader2,
  Pencil,
  Redo2,
  RefreshCw,
  Scissors,
  Search,
  SquareArrowOutUpRight,
  SquarePen,
  SquareTerminal,
  Trash2,
  Undo2,
  X,
} from "lucide-react";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import {
  attachToTerminal,
  fetchWorkspaceFiles,
  openTerminalTarget,
  revealTerminalTarget,
  type WorkspaceFileItem,
} from "@/lib/agenticIdeApi";
import { setWorkspaceDragPaths } from "@/components/agentic/paneDrop";
import { AgentMark } from "@/components/agentic/AgentMark";
import { TrashUnavailableError } from "@/components/agentic/editor/editorApi";
import { forgetFileList } from "@/components/agentic/editor/QuickOpen";
import { ThreadMenuItem, ThreadMenuSeparator, ThreadPopover } from "@/components/agentic/threads/ThreadPopover";
import { useCodeEditorStore, isUnder } from "@/store/codeEditor";
import { useEventStore } from "@/store/events";
import { useIdeChatStore } from "@/store/ideChat";
import { useIdeExplorerStore, type ExplorerView } from "@/store/ideExplorer";
import { MAX_TERMINAL_TABS, useIdeSidePanelStore } from "@/store/ideSidePanel";
import { isMacClient } from "@/lib/embeddedDesktop";
import { searchInFolder } from "@/components/agentic/sidePanel/search/SearchPanel";
import { paneTitleFrom, recapsFor, usePaneRecapPoll, usePaneRecapsStore } from "@/store/paneRecaps";
import { useWorkspacePanesStore } from "@/store/workspacePanes";
import {
  absoluteWorkspacePath,
  fetchWorkspaceChanges,
  type ChangeAuthor,
  type ChangeStatus,
  type ChangedFile,
  type WorkspaceChanges,
} from "./explorerApi";
import { FileTypeIcon } from "./FileTypeIcon";
import {
  entryDeletes,
  peekFileUndo,
  recordFileUndo,
  replayFileUndo,
  runFileOp,
  setConfirm,
  shouldConfirm,
  useFileUndoStore,
  type ConfirmKind,
  type FileOp,
  type FileUndoEntry,
  type UndoDirection,
} from "./explorerUndo";

/** How often git is asked what changed while the Changes or Folder tab is on screen. */
const CHANGES_POLL_MS = 6000;
const CHANGES_JITTER_MS = 1200;

/** Deleted is red; everything an agent added or edited is green. */
const STATUS_TONE: Record<ChangeStatus, string> = {
  modified: "text-success",
  added: "text-success",
  untracked: "text-success",
  deleted: "text-destructive",
  conflicted: "text-warning",
};
const STATUS_LETTER: Record<ChangeStatus, string> = {
  modified: "M",
  added: "A",
  untracked: "U",
  deleted: "D",
  conflicted: "!",
};

const baseName = (path: string) => path.split("/").filter(Boolean).pop() ?? path;
const parentPath = (path: string) => path.split("/").slice(0, -1).join("/");
const joinPath = (folder: string, name: string) => (folder ? `${folder}/${name}` : name);

/** How long after Ctrl+K the second key of a two-step shortcut still counts. */
const CHORD_WINDOW_MS = 2000;

/** The file manager goes by a different name on each system. */
function revealLabelKey(): string {
  const agent = typeof navigator === "undefined" ? "" : navigator.userAgent;
  if (isMacClient(agent)) return "ide_side_panel.explorer.reveal_mac";
  return /win/i.test(agent) ? "ide_side_panel.explorer.reveal_windows" : "ide_side_panel.explorer.reveal_linux";
}

/** The tree's own drag payload: the workspace paths being moved. */
const EXPLORER_DRAG_TYPE = "application/x-jarvis-explorer-paths";

/**
 * The paths of the tree drag in progress. A dragover cannot read the payload
 * (the browser hides it until the drop), but it must know whether the folder
 * under the pointer can take the drop at all.
 */
let draggedPaths: string[] | null = null;

/** How long a drag must rest on a closed folder before it opens. */
const DRAG_EXPAND_MS = 600;

/**
 * Start a drag that a terminal pane turns into file references, and that a
 * folder in the tree turns into a move (`moving` lists the workspace paths).
 */
function startFileDrag(event: DragEvent, absolute: string | string[], moving?: string[]): void {
  const paths = Array.isArray(absolute) ? absolute : [absolute];
  if (!setWorkspaceDragPaths(event.dataTransfer, paths)) {
    event.preventDefault();
    return;
  }
  event.dataTransfer.setData("text/plain", paths.join("\n"));
  if (moving) event.dataTransfer.setData(EXPLORER_DRAG_TYPE, JSON.stringify(moving));
  event.dataTransfer.effectAllowed = moving ? "copyMove" : "copy";
}

/** Drop the paths that lie inside another listed path: moving the folder moves them. */
function topLevel(paths: string[]): string[] {
  return paths.filter((path) => !paths.some((other) => other !== path && isUnder(path, other)));
}

function useWorkspaceChanges(workspaceId: string | null) {
  const [changes, setChanges] = useState<WorkspaceChanges | null>(null);
  const [error, setError] = useState("");
  const [nonce, setNonce] = useState(0);
  useEffect(() => {
    if (!workspaceId) {
      setChanges(null);
      return;
    }
    let alive = true;
    let timer: number | undefined;
    const tick = async () => {
      if (useEventStore.getState().activeSection === "agentic-ide") {
        try {
          const next = await fetchWorkspaceChanges(workspaceId);
          if (alive) {
            setChanges(next);
            setError("");
          }
        } catch (err) {
          // Keep the last answer; the next tick tries again.
          if (alive) setError((err as Error).message);
        }
      }
      if (alive) timer = window.setTimeout(tick, CHANGES_POLL_MS + Math.random() * CHANGES_JITTER_MS);
    };
    void tick();
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [workspaceId, nonce]);
  return { changes, error, refresh: () => setNonce((value) => value + 1) };
}

function ChangeCounts({ file }: { file: Pick<ChangedFile, "added" | "removed"> }) {
  if (file.added == null && file.removed == null) return null;
  return (
    <span className="shrink-0 font-mono text-[11px] tabular-nums">
      {file.added ? <span className="text-success">+{file.added}</span> : null}
      {file.added && file.removed ? " " : null}
      {file.removed ? <span className="text-destructive">−{file.removed}</span> : null}
    </span>
  );
}

function StatusLetter({ status }: { status: ChangeStatus }) {
  return (
    <span
      data-status={status}
      className={cn("w-3 shrink-0 text-center font-mono text-[11px] font-semibold", STATUS_TONE[status])}
    >
      {STATUS_LETTER[status]}
    </span>
  );
}

/**
 * Which coding agents wrote a changed file: each one's brand mark and the
 * pane's title (its call-sign's CLI when it has none yet), newest first.
 */
function ChangeAuthors({ authors, workspaceId }: { authors: ChangeAuthor[]; workspaceId: string }) {
  const t = useT();
  const recaps = usePaneRecapsStore((state) => recapsFor(state, workspaceId));
  const rows = useWorkspacePanesStore((state) => state.panes);
  if (authors.length === 0) return null;
  const named = authors.map((author) => {
    const row = rows.find((pane) => pane.history_id === author.history_id);
    const title = paneTitleFrom(recaps?.[author.pane], row);
    return { ...author, label: title || author.display_name || author.agent };
  });
  const who = named.map((author) => `${author.label} (${author.pane}, ${author.display_name})`).join(", ");
  const [first, ...rest] = named;
  return (
    <span
      data-testid="explorer-change-authors"
      title={fill(t("ide_side_panel.explorer.changed_by"), { who })}
      className="flex min-w-0 max-w-[60%] shrink items-center gap-1 text-[10.5px] text-muted-foreground"
    >
      <span className="flex shrink-0 items-center -space-x-1">
        {named.slice(0, 3).map((author) => (
          <AgentMark
            key={author.history_id}
            agent={author.agent}
            label={author.display_name}
            size="sm"
            variant="plain"
            className="h-3.5 w-3.5"
          />
        ))}
      </span>
      <span className="truncate">{first.label}</span>
      {rest.length > 0 && <span className="shrink-0 tabular-nums">+{rest.length}</span>}
    </span>
  );
}

function HeaderButton({ label, onClick, children, testId }: { label: string; onClick: () => void; children: ReactNode; testId?: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      data-testid={testId}
      className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      {children}
    </button>
  );
}

/**
 * The Changes tab (what the agents changed, and which agent) or the Folder tab
 * (the workspace's folder as a tree). A click opens the file in the code
 * editor — a changed file as its diff; drag a row onto a terminal to
 * reference that file.
 */
export function ExplorerPanel({ view }: { view: ExplorerView }) {
  const t = useT();
  const workspace = useIdeChatStore((state) => state.workspace);
  // Pane titles for the "changed by" line.
  usePaneRecapPoll();
  const [filter, setFilter] = useState("");
  const workspaceId = workspace?.id ?? null;
  const { changes, error: changesError, refresh } = useWorkspaceChanges(workspaceId);
  const [treeNonce, setTreeNonce] = useState(0);
  const [collapseNonce, setCollapseNonce] = useState(0);
  // `folder: null` = where the selection is, as the header's New File / New Folder do.
  const [creating, setCreating] = useState<CreateRequest | null>(null);
  const editorTabs = useCodeEditorStore((state) => (workspaceId ? state.tabs.filter((tab) => tab.workspaceId === workspaceId).length : 0));
  const editorVisible = useCodeEditorStore((state) => state.visible);

  const changeMap = useMemo(() => {
    const map = new Map<string, ChangedFile>();
    for (const file of changes?.files ?? []) map.set(file.path, file);
    return map;
  }, [changes]);
  // Every folder that holds a change, so a collapsed tree still shows where to look.
  const changedFolders = useMemo(() => {
    const folders = new Set<string>();
    for (const file of changes?.files ?? []) {
      const parts = file.path.split("/");
      for (let index = 1; index < parts.length; index += 1) folders.add(parts.slice(0, index).join("/"));
      if (file.is_directory) folders.add(file.path);
    }
    return folders;
  }, [changes]);

  if (!workspace || !workspaceId) {
    return <p className="px-4 py-3 text-sm text-muted-foreground">{t("ide_side_panel.explorer.no_workspace")}</p>;
  }

  const absolute = (relative: string) => absoluteWorkspacePath(workspace.path, relative);
  const needle = filter.trim().toLowerCase();
  const changedFiles = (changes?.files ?? []).filter((file) => !needle || file.path.toLowerCase().includes(needle));
  const changeCount = changes?.files.length ?? 0;
  const editor = useCodeEditorStore.getState();

  return (
    <section
      data-testid="ide-explorer"
      data-view={view}
      aria-label={t(view === "changes" ? "ide_side_panel.tabs.changes" : "ide_side_panel.tabs.files")}
      className="flex h-full min-h-0 flex-col"
    >
      <div className="shrink-0 space-y-2 border-b border-border/60 px-3 pb-2.5 pt-3">
        <div className="flex items-center gap-1.5">
          <FolderOpen className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
          <span className="min-w-0 truncate text-sm font-semibold text-foreground" title={workspace.path}>
            {baseName(workspace.path.replace(/\\/g, "/")) || workspace.name}
          </span>
          {changes?.branch && (
            <span
              data-testid="explorer-branch"
              className="flex min-w-0 shrink items-center gap-1 rounded-md bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground"
            >
              <GitBranch className="h-3 w-3 shrink-0" aria-hidden />
              <span className="truncate">{changes.branch}</span>
            </span>
          )}
          {view === "changes" && changeCount > 0 && (
            <span
              data-testid="explorer-change-count"
              className="shrink-0 rounded bg-success/15 px-1 text-[10px] tabular-nums text-success"
            >
              {changeCount}
            </span>
          )}
          <span className="ml-auto flex shrink-0 items-center">
            {view === "files" && (
              <>
                <HeaderButton label={t("ide_side_panel.explorer.new_file")} testId="explorer-new-file" onClick={() => setCreating({ folder: null, kind: "file", nonce: Date.now() })}>
                  <FilePlus className="h-3.5 w-3.5" aria-hidden />
                </HeaderButton>
                <HeaderButton label={t("ide_side_panel.explorer.new_folder")} onClick={() => setCreating({ folder: null, kind: "directory", nonce: Date.now() })}>
                  <FolderPlus className="h-3.5 w-3.5" aria-hidden />
                </HeaderButton>
                <HeaderButton label={t("ide_side_panel.explorer.collapse_all")} onClick={() => setCollapseNonce((value) => value + 1)}>
                  <ChevronsDownUp className="h-3.5 w-3.5" aria-hidden />
                </HeaderButton>
              </>
            )}
            <HeaderButton
              label={t("ide_side_panel.explorer.refresh")}
              onClick={() => {
                refresh();
                setTreeNonce((value) => value + 1);
                forgetFileList(workspaceId);
              }}
            >
              <RefreshCw className="h-3.5 w-3.5" aria-hidden />
            </HeaderButton>
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <label className="flex h-8 min-w-0 flex-1 items-center gap-2 rounded-lg border border-border/60 bg-background/50 px-2.5 focus-within:border-ring">
            <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
            <input
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
              placeholder={t("ide_side_panel.explorer.filter")}
              aria-label={t("ide_side_panel.explorer.filter")}
              className="min-w-0 flex-1 bg-transparent text-xs text-foreground outline-none placeholder:text-muted-foreground"
            />
            {filter && (
              <button type="button" aria-label={t("ide_side_panel.explorer.clear_filter")} onClick={() => setFilter("")} className="text-muted-foreground hover:text-foreground">
                <X className="h-3.5 w-3.5" aria-hidden />
              </button>
            )}
          </label>
          <button
            type="button"
            onClick={() => editor.setQuickOpen(true)}
            title={t("ide_side_panel.explorer.quick_open_hint")}
            className="inline-flex h-8 shrink-0 items-center rounded-lg border border-border/60 px-2 text-[11px] text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            Ctrl+P
          </button>
        </div>
        {editorTabs > 0 && !editorVisible && (
          <button
            type="button"
            data-testid="explorer-show-editor"
            onClick={() => editor.setVisible(true)}
            className="flex h-8 w-full items-center justify-center gap-1.5 rounded-lg border border-border/60 text-xs text-foreground hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <SquarePen className="h-3.5 w-3.5" aria-hidden />
            {fill(t("ide_side_panel.explorer.show_editor"), { count: editorTabs })}
          </button>
        )}
      </div>

      <div className="scrollbar-jarvis min-h-0 flex-1 overflow-y-auto py-1.5">
        {view === "changes" ? (
          !changes && changesError ? (
            <p className="px-4 py-3 text-xs text-muted-foreground">
              {fill(t("ide_side_panel.explorer.changes_error"), { error: changesError })}
            </p>
          ) : !changes ? (
            <p className="flex items-center gap-2 px-4 py-3 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
              {t("ide_side_panel.explorer.loading")}
            </p>
          ) : !changes.available ? (
            <p className="px-4 py-3 text-xs text-muted-foreground">{changes.reason || t("ide_side_panel.explorer.no_git")}</p>
          ) : changedFiles.length === 0 ? (
            <p className="px-4 py-3 text-xs text-muted-foreground">
              {needle ? t("ide_side_panel.explorer.no_match") : t("ide_side_panel.explorer.clean")}
            </p>
          ) : (
            <ul data-testid="explorer-changes" data-keeps-keyboard>
              {changedFiles.map((file) => {
                const authors = file.authors ?? [];
                return (
                  <li key={file.path}>
                    <button
                      type="button"
                      draggable
                      onDragStart={(event) => startFileDrag(event, absolute(file.path))}
                      onClick={() => !file.is_directory && editor.openFile(workspaceId, file.path, { mode: "diff" })}
                      onDoubleClick={() => !file.is_directory && editor.openFile(workspaceId, file.path, { mode: "diff", preview: false })}
                      data-testid="explorer-change-row"
                      data-path={file.path}
                      title={`${file.path} — ${t("ide_side_panel.explorer.drag_hint")}`}
                      className="group flex min-h-9 w-full items-center gap-2 px-3 py-1 text-left hover:bg-muted/60 focus-visible:bg-muted/60 focus-visible:outline-none"
                    >
                      {file.is_directory ? (
                        <Folder className={cn("h-4 w-4 shrink-0", STATUS_TONE[file.status])} aria-hidden />
                      ) : (
                        <FileTypeIcon path={file.path} />
                      )}
                      <span className="flex min-w-0 flex-1 flex-col leading-tight">
                        <span className={cn("truncate text-[13px] text-foreground", file.status === "deleted" && "line-through decoration-destructive/60")}>
                          {baseName(file.path)}
                        </span>
                        {(parentPath(file.path) || authors.length > 0) && (
                          <span className="flex min-w-0 items-center gap-1.5">
                            {parentPath(file.path) && (
                              <span className="min-w-0 truncate text-[10.5px] text-muted-foreground">{parentPath(file.path)}</span>
                            )}
                            {parentPath(file.path) && authors.length > 0 && (
                              <span className="shrink-0 text-[10.5px] text-muted-foreground/60" aria-hidden>
                                ·
                              </span>
                            )}
                            <ChangeAuthors authors={authors} workspaceId={workspaceId} />
                          </span>
                        )}
                      </span>
                      <ChangeCounts file={file} />
                      <StatusLetter status={file.status} />
                    </button>
                  </li>
                );
              })}
              {changes.truncated && <li className="px-3 py-2 text-[11px] text-muted-foreground">{t("ide_side_panel.explorer.truncated")}</li>}
            </ul>
          )
        ) : (
          <FileTree
            workspaceId={workspaceId}
            filter={needle}
            changeMap={changeMap}
            changedFolders={changedFolders}
            changesKey={changes?.files.map((file) => `${file.path}:${file.status}`).join("|") ?? ""}
            reloadNonce={treeNonce}
            collapseNonce={collapseNonce}
            creating={creating}
            onCreatingDone={() => setCreating(null)}
            onCreate={(folder, kind) => setCreating({ folder, kind, nonce: Date.now() })}
            absolute={absolute}
          />
        )}
      </div>
    </section>
  );
}

interface CreateRequest {
  /** The folder to create in; null = the selected folder, or the selected file's folder. */
  folder: string | null;
  kind: "file" | "directory";
  nonce: number;
}

interface TreeProps {
  workspaceId: string;
  filter: string;
  changeMap: Map<string, ChangedFile>;
  changedFolders: Set<string>;
  /** Changes whenever git's list of changed files does: agents created or deleted something. */
  changesKey: string;
  reloadNonce: number;
  collapseNonce: number;
  creating: CreateRequest | null;
  onCreatingDone: () => void;
  onCreate: (folder: string, kind: "file" | "directory") => void;
  absolute: (relative: string) => string;
}

type Row =
  | { kind: "item"; item: WorkspaceFileItem; depth: number }
  | { kind: "create"; folder: string; entry: "file" | "directory"; depth: number };

/** The inline name field for a new entry or a rename. */
function NameField({
  initial,
  depth,
  icon,
  where,
  onSubmit,
  onCancel,
}: {
  initial: string;
  depth: number;
  icon: ReactNode;
  /** The folder the name lands in, shown on hover. */
  where?: string;
  onSubmit: (name: string) => void;
  onCancel: () => void;
}) {
  const field = useRef<HTMLInputElement>(null);
  const done = useRef(false);
  useEffect(() => {
    const input = field.current;
    if (!input) return;
    input.focus();
    // Select the name without its extension, the way a rename usually wants it.
    const dot = initial.lastIndexOf(".");
    input.setSelectionRange(0, dot > 0 ? dot : initial.length);
  }, [initial]);
  const finish = (submit: boolean) => {
    if (done.current) return;
    done.current = true;
    const value = field.current?.value.trim() ?? "";
    if (submit && value && value !== initial) onSubmit(value);
    else onCancel();
  };
  return (
    <div style={{ paddingLeft: 10 + depth * 14 + 20 }} className="flex h-7 items-center gap-1.5 pr-3">
      {icon}
      <input
        ref={field}
        defaultValue={initial}
        data-testid="explorer-name-field"
        title={where}
        onKeyDown={(event) => {
          event.stopPropagation();
          if (event.key === "Enter") finish(true);
          else if (event.key === "Escape") finish(false);
        }}
        onBlur={() => finish(true)}
        className="min-w-0 flex-1 rounded border border-ring bg-background px-1.5 py-0.5 text-[13px] text-foreground outline-none"
      />
    </div>
  );
}

/** The folder, one lazily loaded level at a time, with the usual file actions. */
function FileTree({
  workspaceId,
  filter,
  changeMap,
  changedFolders,
  changesKey,
  reloadNonce,
  collapseNonce,
  creating,
  onCreatingDone,
  onCreate,
  absolute,
}: TreeProps) {
  const t = useT();
  const pushToast = useEventStore((state) => state.pushToast);
  const stagedPane = useIdeChatStore((state) => state.stagedPane);
  const activePath = useCodeEditorStore((state) => {
    const key = state.active[workspaceId];
    return state.tabs.find((tab) => tab.key === key)?.path ?? null;
  });
  const revealed = useIdeExplorerStore((state) => state.revealed);
  const [children, setChildren] = useState<Record<string, WorkspaceFileItem[]>>({});
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set([""]));
  const [loading, setLoading] = useState<Set<string>>(() => new Set());
  const [error, setError] = useState("");
  const [renaming, setRenaming] = useState<string | null>(null);
  const [focused, setFocused] = useState<string | null>(null);
  const workspaceName = useIdeChatStore((state) => state.workspace?.name ?? "");
  const [menu, setMenu] = useState<{ path: string; isDirectory: boolean; point: { x: number; y: number } } | null>(null);
  // "Select for compare" remembers one file; "Compare with …" on another opens the two side by side.
  const [compareFrom, setCompareFrom] = useState<string | null>(null);
  const chordAt = useRef(0);
  // The one question on screen (move, delete, replace, undo); answering resolves its promise.
  const [ask, setAsk] = useState<AskRequest | null>(null);
  // Several rows can be selected (Ctrl/Cmd+click, Shift+click) for delete,
  // cut/copy/paste and drag; a plain click selects one row again.
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set());
  const anchorRef = useRef<string | null>(null);
  const [clip, setClip] = useState<{ paths: string[]; cut: boolean } | null>(null);
  const [dropTarget, setDropTarget] = useState<string | null>(null);
  const dragExpand = useRef<{ path: string; timer: number } | null>(null);
  const menuAnchor = useRef<HTMLElement | null>(null);
  const list = useRef<HTMLUListElement>(null);
  const loaded = useRef<Set<string>>(new Set());
  const undoNext = useFileUndoStore((state) => state.undo[workspaceId]?.at(-1) ?? null);
  const redoNext = useFileUndoStore((state) => state.redo[workspaceId]?.at(-1) ?? null);

  const load = useCallback(
    async (path: string) => {
      setLoading((current) => new Set(current).add(path));
      try {
        const answer = await fetchWorkspaceFiles(workspaceId, path);
        loaded.current.add(path);
        setChildren((current) => ({ ...current, [path]: answer.entries }));
        setError(answer.error ?? "");
        return answer.entries;
      } catch (err) {
        setError((err as Error).message);
        return null;
      } finally {
        setLoading((current) => {
          const next = new Set(current);
          next.delete(path);
          return next;
        });
      }
    },
    [workspaceId],
  );

  useEffect(() => {
    loaded.current = new Set();
    setChildren({});
    setExpanded(new Set([""]));
    void load("");
  }, [load]);

  useEffect(() => {
    if (collapseNonce) setExpanded(new Set([""]));
  }, [collapseNonce]);

  // Agents add and delete files all the time: re-read the open folders when
  // git's picture changes, and on Refresh.
  const expandedRef = useRef(expanded);
  expandedRef.current = expanded;
  const reloadOpen = useCallback(() => {
    for (const path of loaded.current) if (expandedRef.current.has(path)) void load(path);
  }, [load]);
  const firstKey = useRef(true);
  useEffect(() => {
    if (firstKey.current) {
      firstKey.current = false;
      return;
    }
    reloadOpen();
  }, [changesKey, reloadNonce, reloadOpen]);

  const expand = useCallback(
    (path: string) => {
      setExpanded((current) => (current.has(path) ? current : new Set(current).add(path)));
      if (!loaded.current.has(path)) void load(path);
    },
    [load],
  );

  const toggle = (path: string) => {
    if (expanded.has(path)) {
      setExpanded((current) => {
        const next = new Set(current);
        next.delete(path);
        return next;
      });
    } else expand(path);
  };

  // "Reveal in Explorer": open every folder above the path and scroll to it.
  useEffect(() => {
    if (!revealed || revealed.workspaceId !== workspaceId) return;
    const parts = revealed.path.split("/");
    for (let index = 1; index < parts.length; index += 1) expand(parts.slice(0, index).join("/"));
    setFocused(revealed.path);
  }, [revealed, workspaceId, expand]);

  useEffect(() => {
    if (!focused) return;
    const rows = list.current?.querySelectorAll<HTMLElement>('[data-testid="explorer-tree-row"]') ?? [];
    const row = [...rows].find((entry) => entry.dataset.path === focused);
    row?.scrollIntoView?.({ block: "nearest" });
  }, [focused, children]);

  // The file on screen in the editor is shown in the tree, folders opened to it.
  useEffect(() => {
    if (!activePath) return;
    const parts = activePath.split("/");
    for (let index = 1; index < parts.length; index += 1) expand(parts.slice(0, index).join("/"));
    setFocused(activePath);
  }, [activePath, expand]);

  // Where a new entry goes, fixed when New File / New Folder is pressed: the
  // folder the request names, else the selected folder, else the selected
  // file's folder, else the workspace root. That folder opens for the name field.
  const [createAt, setCreateAt] = useState<string | null>(null);
  const focusedRef = useRef(focused);
  focusedRef.current = focused;
  const childrenRef = useRef(children);
  childrenRef.current = children;
  useEffect(() => {
    if (!creating) {
      setCreateAt(null);
      return;
    }
    let folder = creating.folder;
    if (folder === null) {
      const selected = focusedRef.current;
      const item = selected
        ? Object.values(childrenRef.current).flat().find((entry) => entry.path === selected)
        : undefined;
      folder = !selected ? "" : item?.is_directory ? selected : parentPath(selected);
    }
    setCreateAt(folder);
    if (folder) expand(folder);
  }, [creating, expand]);

  const editor = useCodeEditorStore.getState();
  const fail = (err: unknown) => pushToast("error", (err as Error).message);

  /** Ask one question in the dialog; resolves true on the confirm button. */
  const confirmWith = (request: Omit<AskRequest, "resolve">) =>
    new Promise<boolean>((resolve) => setAsk({ ...request, resolve }));

  /** Show an action as done, with an Undo button while it is still the newest one. */
  const announce = (message: string, entry: FileUndoEntry | null) => {
    pushToast(
      "success",
      message,
      entry ? { action: { label: t("ide_side_panel.explorer.undo"), onAction: () => undoFromToast(entry) } } : undefined,
    );
  };

  /** Re-read the folders around paths that changed; folders under them are read again when opened. */
  const reloadAround = async (paths: string[]) => {
    const folders = new Set<string>();
    for (const path of paths) {
      folders.add(parentPath(path));
      loaded.current = new Set([...loaded.current].filter((entry) => entry === "" || !isUnder(entry, path)));
    }
    await Promise.all(
      // Every folder read before, open or not: a closed one may open right after (a drop target).
      [...folders].filter((folder) => folder === "" || loaded.current.has(folder)).map((folder) => load(folder)),
    );
  };

  /** Open folders keep their open state when they move. */
  const followMove = (from: string, to: string) => {
    setExpanded((current) => {
      const next = new Set<string>();
      for (const entry of current) next.add(isUnder(entry, from) ? to + entry.slice(from.length) : entry);
      return next;
    });
  };

  const create = async (folder: string, kind: "file" | "directory", name: string) => {
    onCreatingDone();
    const path = joinPath(folder, name.replace(/\\/g, "/"));
    try {
      const created = await runFileOp(workspaceId, { kind: "create", path, entry: kind });
      recordFileUndo(
        workspaceId,
        t(kind === "file" ? "ide_side_panel.explorer.new_file" : "ide_side_panel.explorer.new_folder"),
        [created.inverse],
      );
      // "a/b/c.ts" may have created folders on the way; re-read from the top one.
      const top = joinPath(folder, path.slice(folder ? folder.length + 1 : 0).split("/")[0]);
      await load(folder);
      if (top !== created.path) expand(top);
      setFocused(created.path);
      if (kind === "file") editor.openFile(workspaceId, created.path, { preview: false });
    } catch (err) {
      fail(err);
    }
  };

  const rename = async (path: string, name: string) => {
    setRenaming(null);
    try {
      const moved = await runFileOp(workspaceId, { kind: "move", from: path, to: joinPath(parentPath(path), name) });
      followMove(path, moved.path);
      recordFileUndo(workspaceId, t("ide_side_panel.explorer.rename"), [moved.inverse]);
      await reloadAround([path, moved.path]);
      setFocused(moved.path);
      setSelected(new Set([moved.path]));
    } catch (err) {
      fail(err);
    }
  };

  const isDirectory = (path: string) =>
    (children[parentPath(path)] ?? []).find((entry) => entry.path === path)?.is_directory ?? false;
  /** The folder a paste or a drop lands in: the folder itself, or a file's folder. */
  const folderFor = (path: string | null) => (!path ? "" : isDirectory(path) ? path : parentPath(path));
  /** What an action on `path` covers: the whole selection when the row is part of it. */
  const selectionFor = (path: string) => (selected.has(path) && selected.size > 1 ? topLevel([...selected]) : [path]);

  /** The folder's name as the dialogs show it; the workspace's name for the root. */
  const folderLabel = (folder: string) => (folder ? baseName(folder) : workspaceName || baseName(fullPath("").replace(/\\/g, "/")));

  /** Which of `paths` would really move into `folder` (not already there, not into itself). */
  const movable = (paths: string[], folder: string) =>
    topLevel(paths).filter((path) => parentPath(path) !== folder && !isUnder(folder, path));

  /**
   * Move entries into a folder as one undoable step. A name already taken
   * there asks before the existing entry is replaced (it goes to the trash).
   */
  const moveInto = async (paths: string[], folder: string): Promise<string[]> => {
    const moving = movable(paths, folder);
    if (moving.length === 0) return [];
    const existing = new Set(((await load(folder)) ?? childrenRef.current[folder] ?? []).map((entry) => entry.name));
    const ops: FileOp[] = [];
    const landed: string[] = [];
    const touched: string[] = [];
    for (const path of moving) {
      const name = baseName(path);
      const target = joinPath(folder, name);
      try {
        if (existing.has(name)) {
          const replace = await confirmWith({
            title: fill(t("ide_side_panel.explorer.replace_title"), { file: name, folder: folderLabel(folder) }),
            body: t("ide_side_panel.explorer.replace_body"),
            confirmLabel: t("ide_side_panel.explorer.replace"),
            danger: true,
          });
          if (!replace) continue;
          const removed = await runFileOp(workspaceId, { kind: "delete", path: target });
          ops.push(removed.inverse);
          touched.push(target);
        }
        const moved = await runFileOp(workspaceId, { kind: "move", from: path, to: target });
        followMove(path, moved.path);
        ops.push(moved.inverse);
        landed.push(moved.path);
        touched.push(...moved.touched);
      } catch (err) {
        fail(err);
      }
    }
    const entry = recordFileUndo(workspaceId, t("ide_side_panel.explorer.action_move"), ops);
    await reloadAround(touched);
    if (folder) expand(folder);
    if (landed.length > 0) {
      setFocused(landed[landed.length - 1]);
      setSelected(new Set(landed));
      announce(
        landed.length === 1
          ? fill(t("ide_side_panel.explorer.moved_one"), { file: baseName(landed[0]), folder: folderLabel(folder) })
          : fill(t("ide_side_panel.explorer.moved_many"), { count: landed.length, folder: folderLabel(folder) }),
        entry,
      );
    }
    return landed;
  };

  /** A drag dropped on a folder: ask first (unless told not to), then move. */
  const dropInto = async (paths: string[], folder: string) => {
    const moving = movable(paths, folder);
    if (moving.length === 0) return;
    if (shouldConfirm("move")) {
      const ok = await confirmWith({
        title:
          moving.length === 1
            ? fill(t("ide_side_panel.explorer.move_one_title"), { file: baseName(moving[0]), folder: folderLabel(folder) })
            : fill(t("ide_side_panel.explorer.move_many_title"), { count: moving.length, folder: folderLabel(folder) }),
        body: t("ide_side_panel.explorer.move_body"),
        items: moving.length > 1 ? moving : undefined,
        confirmLabel: t("ide_side_panel.explorer.action_move"),
        dontAsk: "move",
      });
      if (!ok) return;
    }
    await moveInto(moving, folder);
    list.current?.focus({ preventScroll: true });
  };

  const paste = async (folder: string) => {
    if (!clip) return;
    if (clip.cut) {
      await moveInto(clip.paths, folder);
      setClip(null);
      return;
    }
    const ops: FileOp[] = [];
    const landed: string[] = [];
    for (const path of topLevel(clip.paths)) {
      try {
        const copied = await runFileOp(workspaceId, {
          kind: "copy",
          source: path,
          to: joinPath(folder, baseName(path)),
          unique: true,
        });
        ops.push(copied.inverse);
        landed.push(copied.path);
      } catch (err) {
        fail(err);
      }
    }
    recordFileUndo(workspaceId, t("ide_side_panel.explorer.paste"), ops);
    await load(folder);
    if (folder) expand(folder);
    if (landed.length > 0) {
      setFocused(landed[landed.length - 1]);
      setSelected(new Set(landed));
    }
  };

  /** Delete after the question (always asked for a permanent delete). */
  const requestDelete = async (paths: string[], permanent = false) => {
    if (paths.length === 0) return;
    if (permanent || shouldConfirm("delete")) {
      const single = paths.length === 1;
      const title = !single
        ? "ide_side_panel.explorer.delete_many_title"
        : permanent
          ? "ide_side_panel.explorer.delete_permanent_title"
          : isDirectory(paths[0])
            ? "ide_side_panel.explorer.delete_folder_title"
            : "ide_side_panel.explorer.delete_file_title";
      const ok = await confirmWith({
        title: fill(t(title), { file: baseName(paths[0]), count: paths.length }),
        body: t(permanent ? "ide_side_panel.explorer.delete_permanent_body" : "ide_side_panel.explorer.delete_body"),
        items: single ? undefined : paths,
        confirmLabel: t(permanent ? "ide_side_panel.explorer.delete_permanent" : "ide_side_panel.explorer.delete_trash"),
        danger: true,
        dontAsk: permanent ? undefined : "delete",
      });
      if (!ok) return;
    }
    await remove(paths, permanent);
  };

  const remove = async (paths: string[], permanent: boolean) => {
    const ops: FileOp[] = [];
    let rest: string[] = [];
    for (const [index, path] of paths.entries()) {
      try {
        ops.push((await runFileOp(workspaceId, { kind: "delete", path, permanent })).inverse);
      } catch (err) {
        if (err instanceof TrashUnavailableError) {
          // No trash on this computer: ask once for the rest, permanently.
          rest = paths.slice(index);
          break;
        }
        fail(err);
      }
    }
    const entry = recordFileUndo(workspaceId, t("ide_side_panel.explorer.delete"), ops);
    setSelected(new Set());
    await reloadAround(paths);
    if (ops.length > 0) {
      announce(
        ops.length === 1
          ? fill(t("ide_side_panel.explorer.deleted_one"), { file: baseName(paths[0]) })
          : fill(t("ide_side_panel.explorer.deleted_many"), { count: ops.length }),
        entry,
      );
    }
    list.current?.focus({ preventScroll: true });
    if (rest.length > 0) await requestDelete(rest, true);
  };

  /** Ctrl+Z / Ctrl+Y in the tree, and the menu's Undo / Redo. */
  const replay = async (direction: UndoDirection) => {
    const entry = peekFileUndo(workspaceId, direction);
    if (!entry) return;
    if (entryDeletes(entry) && shouldConfirm("undo")) {
      const ok = await confirmWith({
        title: fill(
          t(direction === "undo" ? "ide_side_panel.explorer.undo_confirm_title" : "ide_side_panel.explorer.redo_confirm_title"),
          { action: entry.label },
        ),
        body: t("ide_side_panel.explorer.undo_confirm_body"),
        confirmLabel: t(direction === "undo" ? "ide_side_panel.explorer.undo" : "ide_side_panel.explorer.redo"),
        dontAsk: "undo",
      });
      if (!ok) return;
    }
    const result = await replayFileUndo(workspaceId, direction);
    if (!result) return;
    // Open folders follow a folder moved back.
    for (const op of entry.ops) if (op.kind === "move") followMove(op.from, op.to);
    await reloadAround(result.touched);
    const shown = result.paths.filter((path) => !entry.ops.some((op) => op.kind === "delete" && op.path === path));
    if (shown.length > 0) {
      setFocused(shown[shown.length - 1]);
      setSelected(new Set(shown));
      for (const path of shown) {
        const parts = path.split("/");
        for (let index = 1; index < parts.length; index += 1) expand(parts.slice(0, index).join("/"));
      }
    }
    if (result.error) fail(result.error);
    else {
      pushToast(
        "info",
        fill(t(direction === "undo" ? "ide_side_panel.explorer.undone" : "ide_side_panel.explorer.redone"), { action: result.label }),
      );
    }
    list.current?.focus({ preventScroll: true });
  };

  /** The toast's Undo only takes back its own action, never a newer one. */
  const undoFromToast = (entry: FileUndoEntry) => {
    if (peekFileUndo(workspaceId, "undo") !== entry) {
      pushToast("info", t("ide_side_panel.explorer.undo_stale"));
      return;
    }
    void replay("undo");
  };

  const copy = (text: string) => void navigator.clipboard?.writeText(text).catch(fail);
  /** The path as the system writes it; the workspace folder itself for "". */
  const fullPath = (path: string) => (path ? absolute(path) : absolute("").replace(/[\\/]+$/, ""));

  /** Show the entry selected in the system file manager. */
  const revealInSystem = (path: string) => void revealTerminalTarget(workspaceId, path || ".").catch(fail);

  /** A plain terminal in the side panel, started in `folder`. */
  const openTerminal = (folder: string) => {
    const panel = useIdeSidePanelStore.getState();
    if (panel.terminals.filter((terminal) => terminal.workspaceId === workspaceId).length >= MAX_TERMINAL_TABS) {
      pushToast("error", t("ide_side_panel.terminal_limit"));
      return;
    }
    panel.addTerminalTab(workspaceId, folder ? baseName(folder) : workspaceName, folder ? absolute(folder) : undefined);
  };

  const compareWith = (path: string) => {
    if (!compareFrom) return;
    editor.openFile(workspaceId, path, {
      mode: "diff",
      preview: false,
      base: { ref: `file:${compareFrom}`, path: compareFrom, label: `${baseName(compareFrom)} ↔ ${baseName(path)}` },
    });
  };

  const rows: Row[] = [];
  const walk = (path: string, depth: number) => {
    if (creating && createAt === path) rows.push({ kind: "create", folder: path, entry: creating.kind, depth });
    for (const item of sortEntries(children[path] ?? [])) {
      // Only entries that really sit inside this folder; a bad listing must not loop.
      if (path && !item.path.startsWith(`${path}/`)) continue;
      const matches = !filter || item.name.toLowerCase().includes(filter);
      if (matches || item.is_directory) {
        if (matches) rows.push({ kind: "item", item, depth });
        if (item.is_directory && expanded.has(item.path)) walk(item.path, matches ? depth + 1 : depth);
      }
    }
  };
  walk("", 0);

  const onRowKey = (event: ReactKeyboardEvent, item: WorkspaceFileItem) => {
    // The physical key: Alt changes the typed character on some keyboards.
    const letter = event.code?.startsWith("Key") ? event.code.slice(3).toLowerCase() : event.key.toLowerCase();
    const mod = event.ctrlKey || event.metaKey;
    if (event.shiftKey && event.altKey && !mod && ["r", "c", "f"].includes(letter)) {
      event.preventDefault();
      if (letter === "r") revealInSystem(item.path);
      else if (letter === "c") copy(fullPath(item.path));
      else searchInFolder(folderFor(item.path));
    } else if (mod && !event.shiftKey && !event.altKey && letter === "k") {
      // First half of Ctrl+K Ctrl+Shift+C.
      event.preventDefault();
      chordAt.current = Date.now();
    } else if (mod && event.shiftKey && letter === "c" && Date.now() - chordAt.current < CHORD_WINDOW_MS) {
      event.preventDefault();
      chordAt.current = 0;
      copy(item.path);
    } else if (event.key === "Enter" && mod && !item.is_directory) {
      // Ctrl+Enter: beside the file already open, instead of in its place.
      event.preventDefault();
      editor.openToSide(workspaceId, item.path);
    } else if (event.key === "F2") {
      event.preventDefault();
      setRenaming(item.path);
    } else if (event.key === "Delete") {
      event.preventDefault();
      // Shift+Delete skips the trash, as in every file manager.
      void requestDelete(selectionFor(item.path), event.shiftKey);
    } else if ((event.ctrlKey || event.metaKey) && ["c", "x"].includes(event.key.toLowerCase())) {
      event.preventDefault();
      setClip({ paths: selectionFor(item.path), cut: event.key.toLowerCase() === "x" });
    } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "v") {
      event.preventDefault();
      void paste(folderFor(item.path));
    } else if (event.key === "Escape" && (selected.size > 1 || clip)) {
      event.preventDefault();
      setSelected(new Set([item.path]));
      setClip(null);
    } else if (event.key === "ArrowRight" && item.is_directory && !expanded.has(item.path)) {
      event.preventDefault();
      expand(item.path);
    } else if (event.key === "ArrowLeft" && item.is_directory && expanded.has(item.path)) {
      event.preventDefault();
      toggle(item.path);
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const buttons = [...(list.current?.querySelectorAll<HTMLElement>('[data-testid="explorer-tree-row"]') ?? [])];
      const index = buttons.indexOf(event.currentTarget as HTMLElement);
      buttons[index + (event.key === "ArrowDown" ? 1 : -1)]?.focus();
    }
  };

  const openMenu = (event: ReactMouseEvent<HTMLElement>, path: string, isDirectory: boolean) => {
    event.preventDefault();
    event.stopPropagation();
    menuAnchor.current = event.currentTarget;
    // The menu acts on the row under the pointer; a row outside the selection replaces it.
    if (path) {
      setFocused(path);
      if (!selected.has(path)) setSelected(new Set([path]));
    }
    setMenu({ path, isDirectory, point: { x: event.clientX, y: event.clientY } });
  };

  if (!children[""] && loading.has("")) {
    return (
      <p className="flex items-center gap-2 px-4 py-3 text-xs text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
        {t("ide_side_panel.explorer.loading")}
      </p>
    );
  }

  /** Dragging over a folder: accept only a move that would change something; rest on a closed folder to open it. */
  const dragOverFolder = (event: DragEvent, folder: string, closedFolder: string | null = null) => {
    if (!event.dataTransfer.types.includes(EXPLORER_DRAG_TYPE)) return;
    if (draggedPaths && movable(draggedPaths, folder).length === 0) {
      event.dataTransfer.dropEffect = "none";
      if (dropTarget !== null) setDropTarget(null);
      return;
    }
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    if (dropTarget !== folder) setDropTarget(folder);
    if (dragExpand.current?.path !== closedFolder) {
      if (dragExpand.current) window.clearTimeout(dragExpand.current.timer);
      dragExpand.current = closedFolder
        ? { path: closedFolder, timer: window.setTimeout(() => expand(closedFolder), DRAG_EXPAND_MS) }
        : null;
    }
  };

  const endDragHover = () => {
    setDropTarget(null);
    if (dragExpand.current) window.clearTimeout(dragExpand.current.timer);
    dragExpand.current = null;
  };

  const dropOn = (event: DragEvent, folder: string) => {
    endDragHover();
    const raw = event.dataTransfer.getData(EXPLORER_DRAG_TYPE);
    draggedPaths = null;
    if (!raw) return;
    event.preventDefault();
    let paths: unknown;
    try {
      paths = JSON.parse(raw);
    } catch {
      return;
    }
    if (Array.isArray(paths) && paths.every((path) => typeof path === "string")) void dropInto(paths as string[], folder);
  };

  const askingOff = (["move", "delete", "undo"] as ConfirmKind[]).some((kind) => !shouldConfirm(kind));

  const menuFolder = menu ? (menu.isDirectory ? menu.path : parentPath(menu.path)) : "";
  const pick = (action: () => void) => () => {
    setMenu(null);
    action();
  };

  return (
    <>
      <ul
        ref={list}
        data-testid="explorer-tree"
        data-keeps-keyboard
        role="tree"
        aria-label={t("ide_side_panel.explorer.view_files")}
        className={cn("min-h-full focus-visible:outline-none", dropTarget === "" && "bg-primary/5 ring-1 ring-inset ring-primary/40")}
        // A click on the empty space below the rows clears the selection, so
        // New File / New Folder go to the workspace root again.
        onClick={(event) => {
          if (event.target === event.currentTarget) {
            setFocused(null);
            setSelected(new Set());
          }
        }}
        onContextMenu={(event) => openMenu(event, "", true)}
        tabIndex={-1}
        onKeyDown={(event) => {
          // Undo / redo of the tree's own file actions, while the tree has focus.
          if (!(event.ctrlKey || event.metaKey) || event.altKey) return;
          if ((event.target as HTMLElement).tagName === "INPUT") return;
          const letter = event.code?.startsWith("Key") ? event.code.slice(3).toLowerCase() : event.key.toLowerCase();
          if (letter === "z" && !event.shiftKey) {
            event.preventDefault();
            void replay("undo");
          } else if (letter === "y" || (letter === "z" && event.shiftKey)) {
            event.preventDefault();
            void replay("redo");
          }
        }}
        // Dropped on the empty space below the rows: into the workspace root.
        onDragOver={(event) => {
          if (event.target !== event.currentTarget) return;
          dragOverFolder(event, "");
        }}
        onDragLeave={(event) => {
          // Moving between rows fires a leave on each; only leaving the tree counts.
          if (!event.currentTarget.contains(event.relatedTarget as Node | null)) endDragHover();
        }}
        onDrop={(event) => dropOn(event, "")}
      >
        {error && <li className="px-3 py-2 text-[11px] text-destructive">{error}</li>}
        {rows.map((row) => {
          if (row.kind === "create") {
            return (
              <li key={`create-${row.folder}`} role="none">
                <NameField
                  initial=""
                  depth={row.depth}
                  where={absolute(row.folder).replace(/[\\/]+$/, "")}
                  icon={row.entry === "directory" ? <Folder className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden /> : <FilePlus className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />}
                  onSubmit={(name) => void create(row.folder, row.entry, name)}
                  onCancel={onCreatingDone}
                />
              </li>
            );
          }
          const { item, depth } = row;
          const change = changeMap.get(item.path);
          const open = expanded.has(item.path);
          const FolderIcon = open ? FolderOpen : Folder;
          const hasChangeInside = item.is_directory && changedFolders.has(item.path);
          const icon = item.is_directory ? (
            <FolderIcon aria-hidden className={cn("h-4 w-4 shrink-0", change ? STATUS_TONE[change.status] : "text-muted-foreground")} />
          ) : (
            <FileTypeIcon path={item.name} />
          );
          if (renaming === item.path) {
            return (
              <li key={item.path} role="none">
                <NameField initial={item.name} depth={depth} icon={icon} onSubmit={(name) => void rename(item.path, name)} onCancel={() => setRenaming(null)} />
              </li>
            );
          }
          const current = !item.is_directory && item.path === activePath;
          return (
            <li key={item.path} role="treeitem" aria-expanded={item.is_directory ? open : undefined} aria-selected={current || undefined}>
              <button
                type="button"
                draggable
                onDragStart={(event) => {
                  const paths = selectionFor(item.path);
                  // Dragging a row outside the selection drags that row alone, and selects it.
                  if (!selected.has(item.path)) setSelected(new Set([item.path]));
                  startFileDrag(event, paths.map(absolute), paths);
                  draggedPaths = paths;
                }}
                onDragEnd={() => {
                  draggedPaths = null;
                  endDragHover();
                }}
                onDragOver={(event) => {
                  event.stopPropagation();
                  dragOverFolder(event, folderFor(item.path), item.is_directory && !open ? item.path : null);
                }}
                onDrop={(event) => {
                  event.stopPropagation();
                  dropOn(event, folderFor(item.path));
                }}
                onClick={(event) => {
                  setFocused(item.path);
                  if (event.ctrlKey || event.metaKey) {
                    setSelected((current) => {
                      const next = new Set(current);
                      if (next.has(item.path)) next.delete(item.path);
                      else next.add(item.path);
                      return next;
                    });
                    anchorRef.current = item.path;
                    return;
                  }
                  if (event.shiftKey && anchorRef.current) {
                    const order = rows.flatMap((entry) => (entry.kind === "item" ? [entry.item.path] : []));
                    const from = order.indexOf(anchorRef.current);
                    const to = order.indexOf(item.path);
                    if (from >= 0 && to >= 0) {
                      setSelected(new Set(order.slice(Math.min(from, to), Math.max(from, to) + 1)));
                      return;
                    }
                  }
                  setSelected(new Set([item.path]));
                  anchorRef.current = item.path;
                  if (item.is_directory) toggle(item.path);
                  else editor.openFile(workspaceId, item.path);
                }}
                onDoubleClick={() => !item.is_directory && editor.openFile(workspaceId, item.path, { preview: false })}
                onKeyDown={(event) => onRowKey(event, item)}
                onContextMenu={(event) => openMenu(event, item.path, item.is_directory)}
                data-testid="explorer-tree-row"
                data-path={item.path}
                data-active={current || undefined}
                data-selected={selected.has(item.path) || undefined}
                title={item.path}
                style={{ paddingLeft: 10 + depth * 14 }}
                className={cn(
                  "flex h-7 w-full items-center gap-1.5 pr-3 text-left text-[13px] hover:bg-muted/60 focus-visible:bg-muted/60 focus-visible:outline-none",
                  current && "bg-secondary",
                  selected.has(item.path) && selected.size > 1 && "bg-primary/10",
                  focused === item.path && "ring-1 ring-inset ring-ring/50",
                  // The whole folder the drop lands in lights up, as in VS Code.
                  dropTarget !== null && dropTarget !== "" && isUnder(item.path, dropTarget) && "bg-primary/10",
                  dropTarget === item.path && "ring-1 ring-inset ring-primary/60",
                  clip?.cut && clip.paths.includes(item.path) && "opacity-50",
                )}
              >
                <ChevronRight
                  aria-hidden
                  className={cn(
                    "h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform duration-150 motion-reduce:transition-none",
                    !item.is_directory && "invisible",
                    open && "rotate-90",
                  )}
                />
                {icon}
                <span className={cn("min-w-0 flex-1 truncate", change ? STATUS_TONE[change.status] : "text-foreground/90")}>{item.name}</span>
                {loading.has(item.path) && <Loader2 className="h-3 w-3 shrink-0 animate-spin text-muted-foreground" aria-hidden />}
                {hasChangeInside && !change && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-success/80" aria-hidden />}
                {change && <StatusLetter status={change.status} />}
              </button>
            </li>
          );
        })}
      </ul>

      <ThreadPopover anchor={menuAnchor} point={menu?.point} open={menu !== null} onClose={() => setMenu(null)} label={t("ide_side_panel.explorer.menu_label")} width={300}>
        {menu && (
          <div role="menu" data-testid="explorer-menu">
            <ThreadMenuItem icon={<FilePlus className="h-4 w-4" />} label={t("ide_side_panel.explorer.new_file")} onSelect={pick(() => onCreate(menuFolder, "file"))} />
            <ThreadMenuItem icon={<FolderPlus className="h-4 w-4" />} label={t("ide_side_panel.explorer.new_folder")} onSelect={pick(() => onCreate(menuFolder, "directory"))} />
            <ThreadMenuSeparator />
            {menu.path && !menu.isDirectory && (
              <>
                <ThreadMenuItem icon={<SquarePen className="h-4 w-4" />} label={t("ide_side_panel.explorer.open_editor")} onSelect={pick(() => editor.openFile(workspaceId, menu.path, { preview: false }))} />
                <ThreadMenuItem icon={<Columns2 className="h-4 w-4" />} label={t("ide_side_panel.explorer.open_side")} hint="Ctrl+Enter" onSelect={pick(() => editor.openToSide(workspaceId, menu.path))} />
                <ThreadMenuItem icon={<ExternalLink className="h-4 w-4" />} label={t("ide_side_panel.explorer.open_externally")} onSelect={pick(() => void openTerminalTarget(workspaceId, menu.path).catch(fail))} />
              </>
            )}
            <ThreadMenuItem icon={<FolderSearch className="h-4 w-4" />} label={t(revealLabelKey())} hint="Shift+Alt+R" onSelect={pick(() => revealInSystem(menu.path))} />
            <ThreadMenuItem icon={<SquareTerminal className="h-4 w-4" />} label={t("ide_side_panel.explorer.open_terminal")} onSelect={pick(() => openTerminal(menuFolder))} />
            {menu.isDirectory && (
              <>
                <ThreadMenuSeparator />
                <ThreadMenuItem icon={<Search className="h-4 w-4" />} label={t("ide_side_panel.explorer.find_in_folder")} hint="Shift+Alt+F" onSelect={pick(() => searchInFolder(menu.path))} />
              </>
            )}
            {menu.path && !menu.isDirectory && (
              <>
                <ThreadMenuSeparator />
                <ThreadMenuItem icon={<GitCompareArrows className="h-4 w-4" />} label={t("ide_side_panel.explorer.select_compare")} onSelect={pick(() => setCompareFrom(menu.path))} />
                {compareFrom && compareFrom !== menu.path && (
                  <ThreadMenuItem
                    icon={<FileDiff className="h-4 w-4" />}
                    label={fill(t("ide_side_panel.explorer.compare_with"), { file: baseName(compareFrom) })}
                    onSelect={pick(() => compareWith(menu.path))}
                  />
                )}
              </>
            )}
            {menu.path && stagedPane && (
              <>
                <ThreadMenuSeparator />
                <ThreadMenuItem
                  icon={<SquareArrowOutUpRight className="h-4 w-4" />}
                  label={fill(t("ide_side_panel.explorer.reference_in"), { pane: stagedPane })}
                  onSelect={pick(() => void attachToTerminal(stagedPane, { paths: selectionFor(menu.path).map(absolute) }).catch(fail))}
                />
              </>
            )}
            <ThreadMenuSeparator />
            {menu.path && (
              <>
                <ThreadMenuItem
                  icon={<Scissors className="h-4 w-4" />}
                  label={t("ide_side_panel.explorer.cut")}
                  hint="Ctrl+X"
                  onSelect={pick(() => setClip({ paths: selectionFor(menu.path), cut: true }))}
                />
                <ThreadMenuItem
                  icon={<CopyPlus className="h-4 w-4" />}
                  label={t("ide_side_panel.explorer.copy")}
                  hint="Ctrl+C"
                  onSelect={pick(() => setClip({ paths: selectionFor(menu.path), cut: false }))}
                />
              </>
            )}
            <ThreadMenuItem
              icon={<ClipboardPaste className="h-4 w-4" />}
              label={t("ide_side_panel.explorer.paste")}
              hint="Ctrl+V"
              disabled={!clip}
              onSelect={pick(() => void paste(menuFolder))}
            />
            <ThreadMenuSeparator />
            <ThreadMenuItem icon={<Copy className="h-4 w-4" />} label={t("ide_side_panel.explorer.copy_path")} hint="Shift+Alt+C" onSelect={pick(() => copy(fullPath(menu.path)))} />
            {menu.path && (
              <>
                <ThreadMenuItem icon={<span aria-hidden />} label={t("ide_side_panel.explorer.copy_relative_path")} hint="Ctrl+K Ctrl+Shift+C" onSelect={pick(() => copy(menu.path))} />
                <ThreadMenuSeparator />
                <ThreadMenuItem icon={<Pencil className="h-4 w-4" />} label={t("ide_side_panel.explorer.rename")} hint="F2" onSelect={pick(() => setRenaming(menu.path))} />
                <ThreadMenuItem
                  icon={<Trash2 className="h-4 w-4" />}
                  label={t("ide_side_panel.explorer.delete")}
                  hint="Del"
                  danger
                  onSelect={pick(() => void requestDelete(selectionFor(menu.path)))}
                />
              </>
            )}
            {(undoNext || redoNext || askingOff) && <ThreadMenuSeparator />}
            {undoNext && (
              <ThreadMenuItem
                icon={<Undo2 className="h-4 w-4" />}
                label={fill(t("ide_side_panel.explorer.undo_action"), { action: undoNext.label })}
                hint="Ctrl+Z"
                onSelect={pick(() => void replay("undo"))}
              />
            )}
            {redoNext && (
              <ThreadMenuItem
                icon={<Redo2 className="h-4 w-4" />}
                label={fill(t("ide_side_panel.explorer.redo_action"), { action: redoNext.label })}
                hint="Ctrl+Y"
                onSelect={pick(() => void replay("redo"))}
              />
            )}
            {askingOff && (
              <ThreadMenuItem
                icon={<span aria-hidden />}
                label={t("ide_side_panel.explorer.ask_again")}
                onSelect={pick(() => {
                  for (const kind of ["move", "delete", "undo"] as ConfirmKind[]) setConfirm(kind, true);
                })}
              />
            )}
          </div>
        )}
      </ThreadPopover>

      {ask && (
        <ConfirmDialog
          key={ask.title}
          request={ask}
          onDone={(ok, dontAskAgain) => {
            setAsk(null);
            if (ok && dontAskAgain && ask.dontAsk) setConfirm(ask.dontAsk, false);
            ask.resolve(ok);
          }}
        />
      )}
    </>
  );
}

/** One question the Folder tab asks before a move, delete, replace or undo. */
interface AskRequest {
  title: string;
  body?: string;
  /** Workspace paths the question is about, listed when there are several. */
  items?: string[];
  confirmLabel: string;
  danger?: boolean;
  /** Offers "Don't ask me again" for this kind of question. */
  dontAsk?: ConfirmKind;
  resolve: (ok: boolean) => void;
}

/** How many entries a dialog lists before it says "and N more". */
const DIALOG_LIST_MAX = 8;

function ConfirmDialog({ request, onDone }: { request: AskRequest; onDone: (ok: boolean, dontAskAgain: boolean) => void }) {
  const t = useT();
  const confirmButton = useRef<HTMLButtonElement>(null);
  const [dontAsk, setDontAsk] = useState(false);
  useEffect(() => confirmButton.current?.focus(), []);
  const items = request.items ?? [];
  const hidden = items.length - DIALOG_LIST_MAX;
  return (
    <div
      role="presentation"
      data-testid="explorer-dialog-backdrop"
      className="fixed inset-0 z-[86] flex items-center justify-center bg-background/60 p-4"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onDone(false, false);
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.stopPropagation();
          onDone(false, false);
        }
      }}
    >
      <section
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="explorer-dialog-title"
        aria-describedby={request.body ? "explorer-dialog-body" : undefined}
        data-testid="explorer-dialog"
        className="w-full max-w-sm rounded-xl border border-border bg-popover p-4 text-popover-foreground shadow-float"
      >
        <h2 id="explorer-dialog-title" className="break-words text-sm font-semibold text-foreground-strong">
          {request.title}
        </h2>
        {items.length > 0 && (
          <ul className="scrollbar-jarvis mt-2 max-h-40 overflow-y-auto rounded-md border border-border/60 bg-background/40 px-2 py-1.5 font-mono text-[11px] text-muted-foreground">
            {items.slice(0, DIALOG_LIST_MAX).map((path) => (
              <li key={path} className="truncate" title={path}>
                {path}
              </li>
            ))}
            {hidden > 0 && <li>{fill(t("ide_side_panel.explorer.and_more"), { count: hidden })}</li>}
          </ul>
        )}
        {request.body && (
          <p id="explorer-dialog-body" className="mt-2 text-xs text-muted-foreground">
            {request.body}
          </p>
        )}
        {request.dontAsk && (
          <label className="mt-3 flex cursor-pointer select-none items-center gap-2 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={dontAsk}
              onChange={(event) => setDontAsk(event.target.checked)}
              data-testid="explorer-dialog-dont-ask"
              className="h-3.5 w-3.5 accent-primary"
            />
            {t("ide_side_panel.explorer.dont_ask_again")}
          </label>
        )}
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={() => onDone(false, false)}
            data-testid="explorer-dialog-cancel"
            className="h-8 rounded-md px-3 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {t("ide_side_panel.explorer.cancel")}
          </button>
          <button
            ref={confirmButton}
            type="button"
            onClick={() => onDone(true, dontAsk)}
            data-testid="explorer-dialog-confirm"
            className={cn(
              "h-8 rounded-md px-3 text-xs font-medium hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              request.danger ? "bg-destructive text-destructive-foreground" : "bg-primary text-primary-foreground",
            )}
          >
            {request.confirmLabel}
          </button>
        </div>
      </section>
    </div>
  );
}

/** Tool-owned folders nobody browses; the agents' own config folders stay visible. */
const HIDDEN_ENTRIES = new Set([".git", "__pycache__", ".DS_Store", "Thumbs.db", ".pytest_cache", ".mypy_cache", ".ruff_cache"]);

function sortEntries(entries: WorkspaceFileItem[]): WorkspaceFileItem[] {
  return entries
    .filter((entry) => !HIDDEN_ENTRIES.has(entry.name))
    .sort((a, b) =>
      a.is_directory === b.is_directory
        ? a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: "base" })
        : a.is_directory
          ? -1
          : 1,
    );
}
