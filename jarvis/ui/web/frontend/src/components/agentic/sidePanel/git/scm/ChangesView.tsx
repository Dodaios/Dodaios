import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent, type ReactNode, type RefObject } from "react";
import { fill, useT } from "@/i18n";
import { isMacClient } from "@/lib/embeddedDesktop";
import { cn } from "@/lib/utils";
import { QuickTooltip } from "@/components/ui/tooltip";
import { useCodeEditorStore } from "@/store/codeEditor";
import { revealInExplorer } from "@/store/ideExplorer";
import { useEventStore } from "@/store/events";
import { fetchHeadText } from "../../../editor/editorApi";
import { FileTypeIcon } from "../../explorer/FileTypeIcon";
import type { ScmFile, ScmStatus } from "./scmApi";
import {
  baseName,
  buildRows,
  dirName,
  groupsOf,
  letterTone,
  pathsOfRow,
  primaryAction,
  statusKey,
  workspacePath,
  type GroupId,
  type Row,
  type SortKey,
  type ViewMode,
} from "./scmModel";
import { Codicon, Twistie } from "./Codicon";
import { ScmMenu, menuPointFor, type MenuItem } from "./ScmMenu";
import type { CommitOptions, ScmCommands } from "./useScm";
import type { DiffSource } from "./DiffDialog";
import { SessionChanges, type SessionPick } from "./SessionChanges";

export const ROW_HEIGHT = 22;
/** Each tree level steps in by 8 px. */
const INDENT = 8;
const OVERSCAN = 12;

export function IconButton({
  label,
  testId,
  onClick,
  disabled,
  children,
  className,
}: {
  label: string;
  testId: string;
  onClick: (event: MouseEvent<HTMLButtonElement>) => void;
  disabled?: boolean;
  children: ReactNode;
  className?: string;
}) {
  return (
    <QuickTooltip content={label} side="bottom" className="inline-flex shrink-0">
      <button
        type="button"
        aria-label={label}
        data-testid={testId}
        disabled={disabled}
        onClick={(event) => {
          event.stopPropagation();
          onClick(event);
        }}
        className={cn("scm-action", className)}
      >
        {children}
      </button>
    </QuickTooltip>
  );
}

const modKey = () => (typeof navigator !== "undefined" && isMacClient(navigator.userAgent) ? "Cmd" : "Ctrl");

/** The pane state the list and the menus share. */
export interface ListSettings {
  mode: ViewMode;
  sort: SortKey;
}

const FileRow = memo(function FileRow({
  row,
  selected,
  focused,
  mode,
  onPointer,
  onContext,
  onOpenFile,
  onDiscard,
  onStage,
  onUnstage,
}: {
  row: Extract<Row, { kind: "file" }>;
  selected: boolean;
  focused: boolean;
  mode: ViewMode;
  onPointer: (row: Row, event: MouseEvent) => void;
  onContext: (row: Row, event: MouseEvent) => void;
  onOpenFile: (row: Extract<Row, { kind: "file" }>) => void;
  onDiscard: (row: Row) => void;
  onStage: (row: Row) => void;
  onUnstage: (row: Row) => void;
}) {
  const t = useT();
  const { file, group } = row;
  const tone = letterTone(file.letter);
  const state = t(statusKey(file.status));
  const deleted = file.letter === "D";
  const description = mode === "list" ? dirName(file.path) : "";
  const tip = `${file.original ? `${file.original} → ` : ""}${file.path} • ${state}`;
  return (
    <div
      role="treeitem"
      aria-selected={selected}
      data-focused={focused || undefined}
      data-testid="scm-file"
      data-path={file.path}
      data-group={group}
      data-letter={file.letter}
      onClick={(event) => onPointer(row, event)}
      onDoubleClick={(event) => onPointer(row, event)}
      onContextMenu={(event) => onContext(row, event)}
      style={{ height: ROW_HEIGHT, paddingLeft: (row.depth + 1) * INDENT }}
      className="scm-row flex cursor-pointer select-none items-center"
    >
      <Twistie visible={false} />
      <FileTypeIcon path={file.path} className="mr-[6px] h-4 w-4" />
      <QuickTooltip content={tip} side="bottom" className="flex min-w-0 flex-1 items-baseline overflow-hidden whitespace-nowrap">
        <span className={cn("truncate", tone, deleted && "line-through")}>{baseName(file.path)}</span>
        {description && <span className="ml-[0.5em] min-w-0 truncate text-[0.9em] opacity-70">{description}</span>}
      </QuickTooltip>
      <span className="scm-actions shrink-0 items-center gap-[2px] pl-1">
        {file.letter !== "D" && (
          <IconButton label={t("ide_side_panel.git.scm.open_file")} testId="scm-open-file" onClick={() => onOpenFile(row)}>
            <Codicon name="go-to-file" />
          </IconButton>
        )}
        {group === "changes" && (
          <IconButton label={t("ide_side_panel.git.scm.discard_changes")} testId="scm-discard" onClick={() => onDiscard(row)}>
            <Codicon name="discard" />
          </IconButton>
        )}
        {group === "staged" ? (
          <IconButton label={t("ide_side_panel.git.scm.unstage_changes")} testId="scm-unstage" onClick={() => onUnstage(row)}>
            <Codicon name="remove" />
          </IconButton>
        ) : (
          <IconButton label={t("ide_side_panel.git.scm.stage_changes")} testId="scm-stage" onClick={() => onStage(row)}>
            <Codicon name="add" />
          </IconButton>
        )}
      </span>
      <QuickTooltip content={state} side="bottom" className="inline-flex shrink-0">
        <span data-testid="scm-letter" className={cn("ml-[5px] mr-[12px] w-4 text-center text-[12px] font-semibold opacity-90", tone)}>
          {file.letter}
        </span>
      </QuickTooltip>
    </div>
  );
});

function GroupRow({
  row,
  focused,
  onToggle,
  onContext,
  children,
}: {
  row: Extract<Row, { kind: "group" }>;
  focused: boolean;
  onToggle: () => void;
  onContext: (event: MouseEvent) => void;
  children: ReactNode;
}) {
  const t = useT();
  return (
    <div
      role="treeitem"
      aria-expanded={row.open}
      data-focused={focused || undefined}
      data-testid={`scm-group-${row.group}`}
      onClick={onToggle}
      onContextMenu={onContext}
      style={{ height: ROW_HEIGHT, paddingLeft: INDENT }}
      className="scm-row flex cursor-pointer select-none items-center pr-[12px]"
    >
      <Twistie open={row.open} />
      <span className="min-w-0 flex-1 truncate">{t(`ide_side_panel.git.scm.group.${row.group}`)}</span>
      <span className="scm-actions shrink-0 items-center gap-[2px] pr-1">{children}</span>
      <span data-testid="scm-group-count" className="scm-badge ml-1 shrink-0 tabular-nums">
        {row.count}
      </span>
    </div>
  );
}

/**
 * The upper half of the Git tab: the repository line, the commit message box
 * with its button, and every changed file in its group — Merge Changes,
 * Staged Changes, Changes — with the status letter beside each.
 */
export function ChangesView({
  workspaceId,
  repoName,
  status,
  commands,
  busy,
  settings,
  message,
  onMessage,
  messageError,
  messageRef,
  onCommit,
  onDiff,
  onRefresh,
  moreMenu,
  session = null,
  revision = "",
  onClearSession,
}: {
  workspaceId: string;
  repoName: string;
  status: ScmStatus;
  commands: ScmCommands;
  busy: string;
  settings: ListSettings;
  message: string;
  onMessage: (message: string) => void;
  /** Why the last commit attempt did not start ("A message is required"). */
  messageError: string;
  messageRef: RefObject<HTMLTextAreaElement>;
  onCommit: (options: CommitOptions) => void;
  onDiff: (source: DiffSource) => void;
  onRefresh: () => void;
  moreMenu: () => MenuItem[];
  /** Narrow the list to one agent session's own files; null = every change. */
  session?: SessionPick | null;
  /** Bumped when the repository changed (the session list reads again). */
  revision?: string;
  onClearSession?: () => void;
}) {
  const t = useT();
  const pushToast = useEventStore((state) => state.pushToast);
  const [closed, setClosed] = useState<Set<string>>(() => new Set());
  const [selection, setSelection] = useState<Set<string>>(() => new Set());
  const [anchor, setAnchor] = useState("");
  const [focusKey, setFocusKey] = useState("");
  const [menu, setMenu] = useState<{ items: MenuItem[]; x: number; y: number } | null>(null);
  // The repository row folds the commit box and every list under it away.
  const [repoOpen, setRepoOpen] = useState(true);
  const textarea = messageRef;
  const scroller = useRef<HTMLDivElement>(null);
  const listTop = useRef<HTMLDivElement>(null);
  const [viewport, setViewport] = useState({ top: 0, height: 600, offset: 0 });

  useEffect(() => setSelection(new Set()), [workspaceId]);

  const groups = useMemo(() => groupsOf(status), [status]);
  const rows = useMemo(() => buildRows(groups, settings.mode, settings.sort, closed), [groups, settings.mode, settings.sort, closed]);
  const rowIndex = useMemo(() => new Map(rows.map((row, index) => [row.key, index])), [rows]);
  const action = primaryAction(status);
  const branchLabel = status.detached ? status.head.slice(0, 8) : status.branch || "—";
  const dirty = status.staged.length + status.changes.length + status.merge.length > 0;

  // Drop a selection whose files are gone.
  useEffect(() => {
    setSelection((current) => {
      const next = new Set([...current].filter((key) => rowIndex.has(key)));
      return next.size === current.size ? current : next;
    });
  }, [rowIndex]);

  // The textarea grows with its text, up to ten lines.
  useLayoutEffect(() => {
    const element = textarea.current;
    if (!element) return;
    element.style.height = "auto";
    // scrollHeight leaves out the 1 px border on each side.
    const wanted = element.scrollHeight + 2;
    const limit = 10 * 18 + 12;
    element.style.height = `${Math.min(wanted, limit)}px`;
    element.style.overflowY = wanted > limit ? "auto" : "hidden";
  }, [message, textarea]);

  const measure = useCallback(() => {
    const element = scroller.current;
    const top = listTop.current;
    if (!element || !top) return;
    setViewport({ top: element.scrollTop, height: element.clientHeight, offset: top.offsetTop });
  }, []);
  useLayoutEffect(() => {
    measure();
    const element = scroller.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [measure, message, status.operation]);

  const first = Math.max(0, Math.floor((viewport.top - viewport.offset) / ROW_HEIGHT) - OVERSCAN);
  const last = Math.min(rows.length, Math.ceil((viewport.top - viewport.offset + viewport.height) / ROW_HEIGHT) + OVERSCAN);

  const filesOf = useCallback(
    (row: Row): ScmFile[] => {
      // A row inside the selection acts for the whole selection.
      const keys = selection.has(row.key) && selection.size > 1 ? [...selection] : [row.key];
      const picked: ScmFile[] = [];
      const seen = new Set<string>();
      for (const key of keys) {
        const target = rows[rowIndex.get(key) ?? -1];
        if (!target) continue;
        const group = groups.find((entry) => entry.id === target.group);
        for (const path of pathsOfRow(target, groups)) {
          const file = group?.files.find((entry) => entry.path === path);
          if (file && !seen.has(`${target.group}:${path}`)) {
            seen.add(`${target.group}:${path}`);
            picked.push(file);
          }
        }
      }
      return picked;
    },
    [selection, rows, rowIndex, groups],
  );

  const openFile = useCallback(
    (file: ScmFile, preview = true) => {
      const path = workspacePath(file.path, status.prefix);
      if (path === null) return pushToast("info", t("ide_side_panel.git.scm.outside_workspace"));
      useCodeEditorStore.getState().openFile(workspaceId, path, { preview });
    },
    [workspaceId, status.prefix, pushToast, t],
  );

  const openChanges = useCallback(
    (file: ScmFile, group: GroupId, preview = true) => {
      const path = workspacePath(file.path, status.prefix);
      if (path === null) return pushToast("info", t("ide_side_panel.git.scm.outside_workspace"));
      if (group === "merge" || file.letter === "U") return openFile(file, preview);
      if (file.letter === "D") {
        const fromIndex = group === "changes";
        return onDiff({
          title: `${baseName(file.path)} (${t(fromIndex ? "ide_side_panel.git.scm.working_tree" : "ide_side_panel.git.scm.index")})`,
          path: file.path,
          load: async () => ({ before: await fetchHeadText(workspaceId, path, fromIndex ? "index" : ""), after: null, binary: false }),
        });
      }
      const base =
        group === "changes" && status.staged.some((entry) => entry.path === file.path)
          ? { ref: "index", label: t("ide_side_panel.git.scm.diff_working_tree") }
          : undefined;
      useCodeEditorStore.getState().openFile(workspaceId, path, { mode: "diff", base, preview });
    },
    [workspaceId, status.prefix, status.staged, onDiff, openFile, pushToast, t],
  );

  const stageRow = useCallback((row: Row) => void commands.stage(filesOf(row).map((file) => file.path)), [commands, filesOf]);
  const unstageRow = useCallback((row: Row) => void commands.unstage(filesOf(row).map((file) => file.path)), [commands, filesOf]);
  const discardRow = useCallback((row: Row) => void commands.discardFiles(filesOf(row)), [commands, filesOf]);
  const openFileRow = useCallback((row: Extract<Row, { kind: "file" }>) => openFile(row.file, false), [openFile]);

  const toggle = useCallback((key: string) => {
    setClosed((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const onPointer = useCallback(
    (row: Row, event: MouseEvent) => {
      setFocusKey(row.key);
      if (event.shiftKey && anchor && rowIndex.has(anchor)) {
        const [from, to] = [rowIndex.get(anchor)!, rowIndex.get(row.key)!].sort((a, b) => a - b);
        setSelection(new Set(rows.slice(from, to + 1).filter((entry) => entry.kind === "file").map((entry) => entry.key)));
        return;
      }
      if (event.ctrlKey || event.metaKey) {
        setSelection((current) => {
          const next = new Set(current);
          if (next.has(row.key)) next.delete(row.key);
          else next.add(row.key);
          return next;
        });
        setAnchor(row.key);
        return;
      }
      setSelection(new Set([row.key]));
      setAnchor(row.key);
      if (row.kind === "folder") return toggle(row.key);
      if (row.kind === "file") openChanges(row.file, row.group, event.detail < 2);
    },
    [anchor, rowIndex, rows, toggle, openChanges],
  );

  const copy = useCallback(
    (text: string) => {
      void navigator.clipboard?.writeText(text).catch(() => pushToast("error", t("ide_side_panel.git.scm.copy_failed")));
    },
    [pushToast, t],
  );

  const fileMenu = useCallback(
    (row: Row): MenuItem[] => {
      const files = filesOf(row);
      const paths = files.map((file) => file.path);
      const single = row.kind === "file" && files.length === 1 ? row.file : null;
      const absolute = (path: string) => `${status.root.replace(/\\/g, "/")}/${path}`;
      const items: MenuItem[] = [];
      if (single) {
        items.push(
          { id: "open-changes", label: t("ide_side_panel.git.scm.open_changes"), run: () => openChanges(single, row.group, false) },
          { id: "open-file", label: t("ide_side_panel.git.scm.open_file"), disabled: single.letter === "D", run: () => openFile(single, false) },
          { kind: "separator", id: "s1" },
        );
      }
      if (row.group === "staged") items.push({ id: "unstage", label: t("ide_side_panel.git.scm.unstage_changes"), run: () => unstageRow(row) });
      else items.push({ id: "stage", label: t(row.group === "merge" ? "ide_side_panel.git.scm.mark_resolved" : "ide_side_panel.git.scm.stage_changes"), run: () => stageRow(row) });
      if (row.group === "changes") {
        items.push({ id: "discard", label: t("ide_side_panel.git.scm.discard_changes"), run: () => discardRow(row) });
        if (files.every((file) => file.letter === "U")) items.push({ id: "ignore", label: t("ide_side_panel.git.scm.add_to_gitignore"), run: () => void commands.ignore(paths) });
      }
      if (single) {
        const path = workspacePath(single.path, status.prefix);
        items.push(
          { kind: "separator", id: "s2" },
          {
            id: "reveal",
            label: t("ide_side_panel.git.scm.reveal_in_explorer"),
            disabled: path === null || single.letter === "D",
            run: () => path !== null && revealInExplorer({ workspaceId, path }),
          },
          { id: "copy-path", label: t("ide_side_panel.git.scm.copy_path"), run: () => copy(absolute(single.path)) },
          { id: "copy-relative", label: t("ide_side_panel.git.scm.copy_relative_path"), run: () => copy(single.path) },
        );
      }
      return items;
    },
    [filesOf, status.root, status.prefix, workspaceId, openChanges, openFile, stageRow, unstageRow, discardRow, commands, copy, t],
  );

  const groupMenu = useCallback(
    (group: GroupId): MenuItem[] => {
      if (group === "staged") return [{ id: "unstage-all", label: t("ide_side_panel.git.scm.unstage_all"), run: () => void commands.unstageAll() }];
      if (group === "merge") return [{ id: "stage-all", label: t("ide_side_panel.git.scm.stage_all_merge"), run: () => void commands.stage(status.merge.map((file) => file.path)) }];
      return [
        { id: "stage-all", label: t("ide_side_panel.git.scm.stage_all"), run: () => void commands.stage(status.changes.map((file) => file.path)) },
        { id: "discard-all", label: t("ide_side_panel.git.scm.discard_all"), run: () => void commands.discardAll() },
      ];
    },
    [commands, status.merge, status.changes, t],
  );

  const onContext = useCallback(
    (row: Row, event: MouseEvent) => {
      event.preventDefault();
      event.stopPropagation();
      if (!selection.has(row.key)) {
        setSelection(new Set([row.key]));
        setAnchor(row.key);
      }
      setFocusKey(row.key);
      setMenu({ items: row.kind === "group" ? groupMenu(row.group) : fileMenu(row), x: event.clientX, y: event.clientY });
    },
    [selection, fileMenu, groupMenu],
  );

  const runCommit = onCommit;

  const runPrimary = () => {
    if (action.kind === "commit") return void runCommit({ kind: "commit" });
    if (action.kind === "continue") return void commands.operation("continue");
    if (action.kind === "publish") return void commands.publish();
    return void commands.sync();
  };

  const commitMenu = (): MenuItem[] => [
    { id: "commit", label: t("ide_side_panel.git.scm.commit"), run: () => void runCommit({ kind: "commit" }) },
    { id: "commit-amend", label: t("ide_side_panel.git.scm.commit_amend"), run: () => void runCommit({ kind: "amend" }) },
    { id: "commit-push", label: t("ide_side_panel.git.scm.commit_push"), run: () => void runCommit({ kind: "push" }) },
    { id: "commit-sync", label: t("ide_side_panel.git.scm.commit_sync"), run: () => void runCommit({ kind: "sync" }) },
  ];

  const onListKey = (event: KeyboardEvent<HTMLDivElement>) => {
    const index = rowIndex.get(focusKey) ?? -1;
    const go = (next: number) => {
      const target = rows[Math.max(0, Math.min(rows.length - 1, next))];
      if (!target) return;
      setFocusKey(target.key);
      if (!event.shiftKey) {
        setSelection(new Set([target.key]));
        setAnchor(target.key);
      }
      const element = scroller.current;
      if (element) {
        const y = viewport.offset + (rows.indexOf(target)) * ROW_HEIGHT;
        if (y < element.scrollTop) element.scrollTop = y;
        else if (y + ROW_HEIGHT > element.scrollTop + element.clientHeight) element.scrollTop = y + ROW_HEIGHT - element.clientHeight;
      }
    };
    const row = rows[index];
    if (event.key === "ArrowDown") go(index + 1);
    else if (event.key === "ArrowUp") go(index - 1);
    else if (event.key === "Home") go(0);
    else if (event.key === "End") go(rows.length - 1);
    else if (event.key === "Enter" && row) {
      if (row.kind === "file") openChanges(row.file, row.group, false);
      else toggle(row.key);
    } else if ((event.key === "ArrowLeft" || event.key === "ArrowRight") && row && row.kind !== "file") {
      if ((event.key === "ArrowLeft") === row.open) toggle(row.key);
    } else if (event.key === "a" && (event.ctrlKey || event.metaKey)) {
      setSelection(new Set(rows.filter((entry) => entry.kind === "file").map((entry) => entry.key)));
    } else return;
    event.preventDefault();
  };

  const syncLabel =
    status.upstream && (status.ahead || status.behind)
      ? fill(t("ide_side_panel.git.scm.sync_tip"), { behind: status.behind, ahead: status.ahead, upstream: status.upstream })
      : status.upstream
        ? fill(t("ide_side_panel.git.scm.synced_tip"), { upstream: status.upstream })
        : t("ide_side_panel.git.scm.publish_branch");

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div ref={scroller} data-testid="scm-changes-scroller" onScroll={measure} className="min-h-0 flex-1 overflow-y-auto">
        <div
          data-testid="scm-repo-row"
          role="treeitem"
          aria-expanded={repoOpen}
          onClick={() => setRepoOpen((value) => !value)}
          className="scm-row flex h-[22px] cursor-pointer select-none items-center pr-[8px]"
        >
          <Twistie open={repoOpen} />
          <Codicon name="repo" className="mr-[6px]" />
          <span className="min-w-0 shrink truncate">{repoName}</span>
          <QuickTooltip content={t("ide_side_panel.git.scm.checkout_tip")} side="bottom" className="inline-flex min-w-0">
            <button
              type="button"
              data-testid="scm-branch"
              onClick={(event) => {
                event.stopPropagation();
                void commands.checkoutTo();
              }}
              className="ml-[0.5em] inline-flex min-w-0 items-center gap-[3px] text-[0.9em] opacity-70 hover:opacity-100"
            >
              <Codicon name="git-branch" className="!text-[14px]" />
              <span className="truncate">
                {branchLabel}
                {dirty ? "*" : ""}
              </span>
            </button>
          </QuickTooltip>
          <span className="ml-auto flex shrink-0 items-center gap-[2px] pl-1">
            {status.remotes.length > 0 && (
              <QuickTooltip content={syncLabel} side="bottom" className="inline-flex">
                <button
                  type="button"
                  data-testid="scm-sync"
                  aria-label={syncLabel}
                  disabled={busy !== ""}
                  onClick={(event) => {
                    event.stopPropagation();
                    void commands.sync();
                  }}
                  className="scm-action !w-auto gap-[2px] px-[3px] text-[12px] tabular-nums"
                >
                  {!status.upstream ? (
                    <Codicon name="cloud-upload" />
                  ) : status.ahead || status.behind ? (
                    <>
                      {status.behind > 0 && (
                        <>
                          {status.behind}
                          <Codicon name="arrow-down" className="!text-[14px]" />
                        </>
                      )}
                      {status.ahead > 0 && (
                        <>
                          {status.ahead}
                          <Codicon name="arrow-up" className="!text-[14px]" />
                        </>
                      )}
                    </>
                  ) : (
                    <Codicon name="sync" spin={busy === "sync"} />
                  )}
                </button>
              </QuickTooltip>
            )}
            <IconButton label={fill(t("ide_side_panel.git.scm.commit_tip"), { branch: branchLabel })} testId="scm-commit-icon" disabled={busy !== ""} onClick={() => void runCommit({ kind: "commit" })}>
              <Codicon name="check" />
            </IconButton>
            <IconButton label={t("ide_side_panel.git.scm.refresh")} testId="scm-refresh" onClick={onRefresh}>
              <Codicon name="refresh" />
            </IconButton>
            <IconButton
              label={t("ide_side_panel.git.scm.more_actions")}
              testId="scm-more"
              onClick={(event) => setMenu({ items: moreMenu(), ...menuPointFor(event.currentTarget) })}
            >
              <Codicon name="ellipsis" />
            </IconButton>
          </span>
        </div>

        {repoOpen && (
        <div className="pb-[6px] pl-[20px] pr-[12px] pt-[3px]">
          {status.operation && status.operation !== "bisect" && (
            <div data-testid="scm-operation" className="mb-[6px] flex items-start gap-2 rounded-sm border border-[var(--scm-modified)] px-[6px] py-[2px] text-[12px] leading-[18px]">
              <Codicon name="git-merge" className="mt-[1px]" />
              <span className="min-w-0 flex-1">{t(`ide_side_panel.git.scm.operation.${status.operation}`)}</span>
              <button type="button" data-testid="scm-abort" onClick={() => void commands.operation("abort")} className="shrink-0 text-[var(--scm-focus)] hover:underline">
                {t("ide_side_panel.git.scm.abort")}
              </button>
            </div>
          )}
          <div className="relative">
            <textarea
              ref={textarea}
              data-testid="scm-message"
              rows={1}
              value={message}
              spellCheck={false}
              aria-label={t("ide_side_panel.git.scm.message_label")}
              aria-invalid={Boolean(messageError) || undefined}
              placeholder={fill(t("ide_side_panel.git.scm.message_placeholder"), { key: modKey(), branch: branchLabel })}
              onChange={(event) => onMessage(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
                  event.preventDefault();
                  if (busy === "") void runCommit({ kind: "commit" });
                }
              }}
              style={messageError ? { borderColor: "var(--scm-error-border)", outlineColor: "var(--scm-error-border)" } : undefined}
              className="scm-input block min-h-[26px] w-full resize-none px-[6px] py-[2px] text-[13px] leading-[20px]"
            />
            {messageError && (
              <p
                data-testid="scm-message-error"
                className="border border-t-0 px-[6px] py-[2px] text-[12px] leading-[17px]"
                style={{ background: "var(--scm-error-bg)", borderColor: "var(--scm-error-border)" }}
              >
                {messageError}
              </p>
            )}
          </div>
          <div className="mt-[6px] flex h-[26px]">
            <button
              type="button"
              data-testid="scm-primary"
              data-action={action.kind}
              disabled={busy !== "" || (action.kind === "commit" && !action.enabled)}
              onClick={runPrimary}
              className={cn(
                "scm-button inline-flex min-w-0 flex-1 items-center justify-center gap-[4px] px-[4px] text-[13px] leading-[18px]",
                action.kind === "commit" ? "rounded-l-[2px]" : "rounded-[2px]",
              )}
            >
              {action.kind === "commit" && (
                <>
                  <Codicon name="check" />
                  <span className="truncate">{t("ide_side_panel.git.scm.commit")}</span>
                </>
              )}
              {action.kind === "continue" && (
                <>
                  <Codicon name="check" />
                  <span className="truncate">{t("ide_side_panel.git.scm.continue")}</span>
                </>
              )}
              {action.kind === "publish" && (
                <>
                  <Codicon name="cloud-upload" />
                  <span className="truncate">{t("ide_side_panel.git.scm.publish_branch")}</span>
                </>
              )}
              {action.kind === "sync" && (
                <>
                  <Codicon name="sync" spin={busy === "sync"} />
                  <span className="truncate">{t("ide_side_panel.git.scm.sync_changes")}</span>
                  <span className="shrink-0 tabular-nums">
                    {action.behind > 0 && `${action.behind}↓ `}
                    {action.ahead > 0 && `${action.ahead}↑`}
                  </span>
                </>
              )}
            </button>
            {action.kind === "commit" && (
              <>
                <span aria-hidden className="scm-button w-px shrink-0 py-[4px]" style={{ opacity: busy !== "" || !action.enabled ? 0.4 : 1 }}>
                  <span className="block h-full w-px" style={{ background: "var(--scm-button-separator)" }} />
                </span>
                <button
                  type="button"
                  data-testid="scm-primary-more"
                  aria-label={t("ide_side_panel.git.scm.commit_options")}
                  disabled={busy !== "" || !action.enabled}
                  onClick={(event) => setMenu({ items: commitMenu(), ...menuPointFor(event.currentTarget) })}
                  className="scm-button inline-flex w-[26px] shrink-0 items-center justify-center rounded-r-[2px]"
                >
                  <Codicon name="chevron-down" />
                </button>
              </>
            )}
          </div>
        </div>

        )}

        {repoOpen && session && (
          <SessionChanges
            workspaceId={workspaceId}
            session={session}
            status={status}
            commands={commands}
            revision={revision}
            onDiff={onDiff}
            onClear={() => onClearSession?.()}
          />
        )}

        {repoOpen && !session && (
        <div
          ref={listTop}
          role="tree"
          aria-label={t("ide_side_panel.git.scm.changes_aria")}
          aria-multiselectable
          tabIndex={0}
          onKeyDown={onListKey}
          className="scm-list relative outline-none"
          style={{ height: rows.length * ROW_HEIGHT }}
        >
          <div style={{ position: "absolute", top: first * ROW_HEIGHT, left: 0, right: 0 }}>
            {rows.slice(first, last).map((row) => {
              if (row.kind === "file") {
                return (
                  <FileRow
                    key={row.key}
                    row={row}
                    selected={selection.has(row.key)}
                    focused={focusKey === row.key}
                    mode={settings.mode}
                    onPointer={onPointer}
                    onContext={onContext}
                    onOpenFile={openFileRow}
                    onDiscard={discardRow}
                    onStage={stageRow}
                    onUnstage={unstageRow}
                  />
                );
              }
              if (row.kind === "folder") {
                return (
                  <div
                    key={row.key}
                    role="treeitem"
                    aria-expanded={row.open}
                    aria-selected={selection.has(row.key)}
                    data-focused={focusKey === row.key || undefined}
                    data-testid="scm-folder"
                    onClick={(event) => onPointer(row, event)}
                    onContextMenu={(event) => onContext(row, event)}
                    style={{ height: ROW_HEIGHT, paddingLeft: (row.depth + 1) * INDENT }}
                    className="scm-row flex cursor-pointer select-none items-center pr-[12px]"
                  >
                    <Twistie open={row.open} />
                    <Codicon name={row.open ? "folder-opened" : "folder"} className="mr-[6px]" />
                    <span className="min-w-0 flex-1 truncate">{row.label}</span>
                    <span className="scm-actions shrink-0 items-center gap-[2px]">
                      {row.group === "changes" && (
                        <IconButton label={t("ide_side_panel.git.scm.discard_changes")} testId="scm-folder-discard" onClick={() => discardRow(row)}>
                          <Codicon name="discard" />
                        </IconButton>
                      )}
                      {row.group === "staged" ? (
                        <IconButton label={t("ide_side_panel.git.scm.unstage_changes")} testId="scm-folder-unstage" onClick={() => unstageRow(row)}>
                          <Codicon name="remove" />
                        </IconButton>
                      ) : (
                        <IconButton label={t("ide_side_panel.git.scm.stage_changes")} testId="scm-folder-stage" onClick={() => stageRow(row)}>
                          <Codicon name="add" />
                        </IconButton>
                      )}
                    </span>
                  </div>
                );
              }
              return (
                <GroupRow key={row.key} row={row} focused={focusKey === row.key} onToggle={() => toggle(row.key)} onContext={(event) => onContext(row, event)}>
                  {row.group === "staged" && (
                    <IconButton label={t("ide_side_panel.git.scm.unstage_all")} testId="scm-unstage-all" onClick={() => void commands.unstageAll()}>
                      <Codicon name="remove" />
                    </IconButton>
                  )}
                  {row.group === "changes" && row.count > 0 && (
                    <>
                      <IconButton label={t("ide_side_panel.git.scm.discard_all")} testId="scm-discard-all" onClick={() => void commands.discardAll()}>
                        <Codicon name="discard" />
                      </IconButton>
                      <IconButton label={t("ide_side_panel.git.scm.stage_all")} testId="scm-stage-all" onClick={() => void commands.stage(status.changes.map((file) => file.path))}>
                        <Codicon name="add" />
                      </IconButton>
                    </>
                  )}
                  {row.group === "merge" && (
                    <IconButton label={t("ide_side_panel.git.scm.stage_all_merge")} testId="scm-stage-all-merge" onClick={() => void commands.stage(status.merge.map((file) => file.path))}>
                      <Codicon name="add" />
                    </IconButton>
                  )}
                </GroupRow>
              );
            })}
          </div>
        </div>
        )}
        {status.truncated && <p className="px-[20px] py-[4px] text-[12px] opacity-70">{t("ide_side_panel.git.scm.truncated")}</p>}
      </div>
      {menu && <ScmMenu items={menu.items} x={menu.x} y={menu.y} onClose={() => setMenu(null)} />}
    </div>
  );
}

/** "View & Sort" for the more menu: list or tree, and the sort order. */
export function viewSortMenu(settings: ListSettings, onSettings: (next: ListSettings) => void, t: (key: string) => string): MenuItem {
  return {
    kind: "submenu",
    id: "view-sort",
    label: t("ide_side_panel.git.scm.view_sort"),
    items: [
      { id: "view-list", label: t("ide_side_panel.git.scm.view_list"), checked: settings.mode === "list", run: () => onSettings({ ...settings, mode: "list" }) },
      { id: "view-tree", label: t("ide_side_panel.git.scm.view_tree"), checked: settings.mode === "tree", run: () => onSettings({ ...settings, mode: "tree" }) },
      { kind: "separator", id: "vs1" },
      { id: "sort-name", label: t("ide_side_panel.git.scm.sort_name"), checked: settings.sort === "name", run: () => onSettings({ ...settings, sort: "name" }) },
      { id: "sort-path", label: t("ide_side_panel.git.scm.sort_path"), checked: settings.sort === "path", run: () => onSettings({ ...settings, sort: "path" }) },
      { id: "sort-status", label: t("ide_side_panel.git.scm.sort_status"), checked: settings.sort === "status", run: () => onSettings({ ...settings, sort: "status" }) },
    ],
  };
}
