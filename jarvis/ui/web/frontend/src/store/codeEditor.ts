import { create } from "zustand";

import { setReloadHold } from "@/lib/reloadHold";
import type { LineEnding, TextEncoding } from "@/components/agentic/editor/editorApi";
import type { ViewKind } from "@/components/agentic/editor/fileKinds";

/**
 * The Agentic IDE's code editor: which files are open as tabs, and what is
 * known about each file on disk.
 *
 * The text itself lives in the editor engine's models (see
 * `components/agentic/editor/editorModels.ts`); this store holds only what the
 * React chrome draws — tabs, dirty dots, conflict bars, the status bar.
 *
 * Tabs follow the familiar desktop-editor rules: a single click opens a
 * *preview* tab (italic) that the next single click replaces; a double click,
 * an edit or a save keeps it. Tabs belong to one workspace, so switching
 * workspaces shows that workspace's own tabs.
 */
export type EditorMode = "edit" | "diff";

export interface EditorTab {
  key: string;
  fileKey: string;
  workspaceId: string;
  /** POSIX path relative to the workspace root. */
  path: string;
  mode: EditorMode;
  preview: boolean;
  /** The editor group (column) the tab sits in; groups stand side by side. */
  group: number;
}

/** `ready` = editable text; a ViewKind = shown with a viewer; the rest are read-only notices. */
export type FileStatus = "loading" | "ready" | "binary" | "too_large" | "error" | ViewKind;

export interface EditorFile {
  workspaceId: string;
  path: string;
  status: FileStatus;
  error: string;
  /** Version on disk the buffer is based on; null for a file not on disk. */
  version: string | null;
  encoding: TextEncoding;
  eol: LineEnding;
  dirty: boolean;
  /** Deleted on disk while open; the buffer is kept and a save recreates it. */
  deleted: boolean;
  /** The file changed on disk while the buffer had unsaved edits. */
  conflict: { diskVersion: string | null } | null;
  /** The file on disk mixes line endings; a save writes `eol` throughout. */
  mixedEol: boolean;
  saving: boolean;
}

export interface CursorInfo {
  line: number;
  column: number;
  selected: number;
  language: string;
  insertSpaces: boolean;
  tabSize: number;
}

export interface RevealRequest {
  fileKey: string;
  line: number;
  column: number;
  /** Characters to select from the column on (a search match); 0 = just place the cursor. */
  length: number;
  nonce: number;
}

interface ClosedTab {
  workspaceId: string;
  path: string;
  mode: EditorMode;
}

/** What a diff tab compares against instead of the last commit. */
export interface DiffBase {
  /** A commit id, or a unique key for a file base. */
  ref: string;
  /** Compare against this workspace file as it is on disk, instead of a commit. */
  path?: string;
  /** Shown in the diff badge in place of "Changes since the last commit". */
  label: string;
}

export interface OpenOptions {
  mode?: EditorMode;
  /** Diff only: compare against this commit (a pane review's base); omitted = the last commit. */
  base?: DiffBase;
  /** Single-click opens replace each other; false keeps the tab. */
  preview?: boolean;
  line?: number;
  column?: number;
  length?: number;
  /**
   * Open in the group to the right of the one that has the keyboard, creating
   * that group when there is none ("Open to the side").
   */
  side?: boolean;
  /** Always a new group, directly to the right of the one that has the keyboard ("Split right"). */
  split?: boolean;
  /** Open in this group; omitted = the group that has the keyboard. */
  group?: number;
}

/**
 * How the groups of a workspace are arranged: one group (its id), or a split
 * whose children stand side by side (`row`) or above each other (`column`).
 */
export type EditorLayout = number | { dir: "row" | "column"; children: EditorLayout[] };

/** A side of a group a new group can be put on. */
export type LayoutSide = "left" | "right" | "top" | "bottom";

/** Where a dragged tab lands. */
export type TabDrop =
  /** In a group's tab bar, in front of the tab `before`; at the end when omitted. */
  | { group: number; before?: string }
  /** In a new group directly beside an existing one: left or right of it, above or below it. */
  | { beside: number; side: LayoutSide };

interface CodeEditorState {
  tabs: EditorTab[];
  /** Per workspace: the tab shown by the group that has the keyboard. */
  active: Record<string, string | null>;
  files: Record<string, EditorFile>;
  /** Whether the editor covers the terminals (tabs stay open when hidden). */
  visible: boolean;
  quickOpen: boolean;
  cursor: CursorInfo | null;
  reveal: RevealRequest | null;
  closed: ClosedTab[];
  /** Per file: the commit its diff tab compares against, when it is not the last commit. */
  diffBases: Record<string, DiffBase>;
  /** Per workspace: how the editor groups are laid out; missing = one group. */
  layout: Record<string, EditorLayout>;
  /** Per workspace and group: the tab that group shows. */
  groupActive: Record<string, Record<number, string | null>>;
  /** Per workspace: the group that has the keyboard; opened files, saves and tab switches go to it. */
  focusedGroup: Record<string, number>;
  /** Open a file in the group to the right, splitting the view when there is none. */
  openToSide: (workspaceId: string, path: string, options?: OpenOptions) => void;
  /** Show a tab's file a second time, in a new group to the right of the tab's own. */
  splitRight: (key: string) => void;
  /** Hand the keyboard to a group. */
  focusGroup: (workspaceId: string, group: number) => void;
  /** Put a dragged tab where it was dropped: a spot in a tab bar, or a new group. */
  moveTab: (key: string, drop: TabDrop) => void;
  openFile: (workspaceId: string, path: string, options?: OpenOptions) => void;
  closeTab: (key: string) => void;
  closeTabs: (keys: string[]) => void;
  activate: (key: string) => void;
  pinTab: (key: string) => void;
  cycle: (workspaceId: string, step: 1 | -1) => void;
  reopenClosed: (workspaceId: string) => void;
  patchFile: (fileKey: string, patch: Partial<EditorFile>) => void;
  setVisible: (visible: boolean) => void;
  setQuickOpen: (open: boolean) => void;
  setCursor: (cursor: CursorInfo | null) => void;
  /** After a rename in the explorer: every open file under `from` moves to `to`. */
  renamePath: (workspaceId: string, from: string, to: string) => void;
  /** After a delete in the explorer: open files under `path` are marked deleted. */
  markDeleted: (workspaceId: string, path: string) => void;
  /**
   * Put back the tabs a workspace had open last run, without bringing the
   * editor forward; tabs already open stay as they are.
   */
  restoreTabs: (workspaceId: string, tabs: { path: string; mode: EditorMode; preview: boolean }[], active: string | null) => void;
}

export const fileKeyOf = (workspaceId: string, path: string) => `${workspaceId}\u0000${path}`;
/** A tab's key; the same file opened in two groups is two tabs. */
export const tabKeyOf = (mode: EditorMode, fileKey: string, group = 0) =>
  group === 0 ? `${mode}:${fileKey}` : `g${group}:${mode}:${fileKey}`;

/** True when `path` is `root` itself or lies inside the folder `root`. */
export const isUnder = (path: string, root: string) => path === root || path.startsWith(`${root}/`);

const MAX_CLOSED = 20;

const newFile = (workspaceId: string, path: string): EditorFile => ({
  workspaceId,
  path,
  status: "loading",
  error: "",
  version: null,
  encoding: "utf-8",
  eol: "\n",
  dirty: false,
  deleted: false,
  conflict: null,
  mixedEol: false,
  saving: false,
});

/** Drop file records no tab refers to any more. */
function prune(files: Record<string, EditorFile>, tabs: EditorTab[]): Record<string, EditorFile> {
  const used = new Set(tabs.map((tab) => tab.fileKey));
  const next: Record<string, EditorFile> = {};
  for (const [key, file] of Object.entries(files)) if (used.has(key)) next[key] = file;
  return next;
}

/** The tab to show once `key` closes: the nearest survivor to its right, else to its left. */
function successor(own: EditorTab[], key: string, closing: Set<string>): string | null {
  const index = own.findIndex((tab) => tab.key === key);
  const right = own.slice(index + 1).find((tab) => !closing.has(tab.key));
  const left = own
    .slice(0, Math.max(index, 0))
    .reverse()
    .find((tab) => !closing.has(tab.key));
  return (right ?? left)?.key ?? null;
}

type GroupState = Pick<CodeEditorState, "tabs" | "layout" | "groupActive" | "focusedGroup">;

/** The ids of a layout's groups, in reading order: left to right, top to bottom. */
export function leavesOf(layout: EditorLayout): number[] {
  return typeof layout === "number" ? [layout] : layout.children.flatMap(leavesOf);
}

/** Drop groups that are gone and collapse splits that are left with one child. */
function tidy(layout: EditorLayout, alive: ReadonlySet<number>): EditorLayout | null {
  if (typeof layout === "number") return alive.has(layout) ? layout : null;
  const children = layout.children
    .map((child) => tidy(child, alive))
    .filter((child): child is EditorLayout => child !== null)
    // A row inside a row is one row.
    .flatMap((child) => (typeof child !== "number" && child.dir === layout.dir ? child.children : [child]));
  if (children.length === 0) return null;
  return children.length === 1 ? children[0] : { dir: layout.dir, children };
}

/**
 * The layout for exactly these groups: the remembered one without the groups
 * that are gone, and any group it does not know yet added on the right.
 */
export function layoutFor(stored: EditorLayout | undefined, ids: number[]): EditorLayout {
  const kept = stored === undefined ? null : tidy(stored, new Set(ids));
  const placed = new Set(kept === null ? [] : leavesOf(kept));
  const missing = ids.filter((id) => !placed.has(id)).sort((a, b) => a - b);
  if (kept === null) return missing.length === 0 ? 0 : missing.length === 1 ? missing[0] : { dir: "row", children: missing };
  if (missing.length === 0) return kept;
  return typeof kept !== "number" && kept.dir === "row"
    ? { dir: "row", children: [...kept.children, ...missing] }
    : { dir: "row", children: [kept, ...missing] };
}

/** Put a new group directly beside an existing one. */
function insertBeside(layout: EditorLayout, target: number, id: number, side: LayoutSide): EditorLayout {
  const dir = side === "left" || side === "right" ? "row" : "column";
  const pair = side === "left" || side === "top" ? [id, target] : [target, id];
  if (typeof layout === "number") return layout === target ? { dir, children: pair } : layout;
  // Beside a group that already stands in a split of that direction: one more in it.
  if (layout.dir === dir && layout.children.includes(target)) {
    return { dir, children: layout.children.flatMap((child) => (child === target ? pair : [child])) };
  }
  return { dir: layout.dir, children: layout.children.map((child) => insertBeside(child, target, id, side)) };
}

/** One column of the editor: its own tabs, one of them shown. */
export interface EditorGroup {
  id: number;
  tabs: EditorTab[];
  /** The tab the group shows; null only for the single empty group. */
  active: EditorTab | null;
  /** This group has the keyboard. */
  focused: boolean;
}

/**
 * The editor groups of one workspace, in reading order.
 *
 * Derived from the tabs: a group exists exactly as long as it holds a tab, so
 * closing its last tab closes the column. With nothing open there is one empty
 * group.
 */
export function groupsOf(state: GroupState, workspaceId: string | null): EditorGroup[] {
  if (!workspaceId) return [];
  const byGroup = new Map<number, EditorTab[]>();
  for (const tab of state.tabs) {
    if (tab.workspaceId !== workspaceId) continue;
    const id = tab.group ?? 0;
    const tabs = byGroup.get(id);
    if (tabs) tabs.push(tab);
    else byGroup.set(id, [tab]);
  }
  if (byGroup.size === 0) return [{ id: 0, tabs: [], active: null, focused: true }];
  const order = leavesOf(layoutFor(state.layout[workspaceId], [...byGroup.keys()]));
  const wanted = state.focusedGroup[workspaceId];
  const focused = wanted !== undefined && order.includes(wanted) ? wanted : order[0];
  const actives = state.groupActive[workspaceId] ?? {};
  return order.map((id) => {
    const tabs = byGroup.get(id) ?? [];
    const active = tabs.find((tab) => tab.key === actives[id]) ?? tabs[tabs.length - 1] ?? null;
    return { id, tabs, active, focused: id === focused };
  });
}

/** Bring the group bookkeeping and `active` of these workspaces in line with the tabs. */
function settle(
  state: GroupState & Pick<CodeEditorState, "active">,
  workspaceIds: Iterable<string>,
): Pick<CodeEditorState, "active" | "layout" | "groupActive" | "focusedGroup"> {
  const active = { ...state.active };
  const layout = { ...state.layout };
  const groupActive = { ...state.groupActive };
  const focusedGroup = { ...state.focusedGroup };
  for (const workspaceId of workspaceIds) {
    const groups = groupsOf(state, workspaceId);
    const focused = groups.find((group) => group.focused) ?? groups[0];
    layout[workspaceId] = layoutFor(
      state.layout[workspaceId],
      groups.filter((group) => group.tabs.length > 0).map((group) => group.id),
    );
    groupActive[workspaceId] = Object.fromEntries(groups.map((group) => [group.id, group.active?.key ?? null]));
    focusedGroup[workspaceId] = focused.id;
    active[workspaceId] = focused.active?.key ?? null;
  }
  return { active, layout, groupActive, focusedGroup };
}

let revealNonce = 0;

export const useCodeEditorStore = create<CodeEditorState>((set, get) => ({
  tabs: [],
  active: {},
  files: {},
  visible: false,
  quickOpen: false,
  cursor: null,
  reveal: null,
  closed: [],
  diffBases: {},
  layout: {},
  groupActive: {},
  focusedGroup: {},

  openToSide: (workspaceId, path, options = {}) => get().openFile(workspaceId, path, { preview: false, ...options, side: true }),

  splitRight: (key) => {
    const tab = get().tabs.find((entry) => entry.key === key);
    if (!tab) return;
    get().focusGroup(tab.workspaceId, tab.group ?? 0);
    // A diff keeps comparing against what it compared against.
    const base = tab.mode === "diff" ? get().diffBases[tab.fileKey] : undefined;
    get().openFile(tab.workspaceId, tab.path, { mode: tab.mode, base, preview: false, split: true });
  },

  focusGroup: (workspaceId, group) => {
    const state = get();
    if (groupsOf(state, workspaceId).find((entry) => entry.focused)?.id === group) return;
    set(settle({ ...state, focusedGroup: { ...state.focusedGroup, [workspaceId]: group } }, [workspaceId]));
  },

  moveTab: (key, drop) =>
    set((state) => {
      const tab = state.tabs.find((entry) => entry.key === key);
      if (!tab) return {};
      const { workspaceId } = tab;
      const groups = groupsOf(state, workspaceId);
      const origin = tab.group ?? 0;
      const source = groups.find((entry) => entry.id === origin);
      const order = groups.map((entry) => entry.id);
      let layout = layoutFor(state.layout[workspaceId], order);
      let group: number;
      let before: string | undefined;
      if ("beside" in drop) {
        if (!order.includes(drop.beside)) return {};
        // A group's only tab dropped beside that same group is already there.
        if (drop.beside === origin && source?.tabs.length === 1) return {};
        group = Math.max(...order) + 1;
        layout = insertBeside(layout, drop.beside, group, drop.side);
      } else {
        if (!order.includes(drop.group) || drop.before === key) return {};
        group = drop.group;
        before = drop.before;
      }
      const movedKey = tabKeyOf(tab.mode, tab.fileKey, group);
      const rest = state.tabs.filter((entry) => entry.key !== key);
      let tabs = rest;
      // The same file already open in that group: the dragged tab closes into it.
      if (group === origin || !rest.some((entry) => entry.key === movedKey)) {
        const moved: EditorTab = { ...tab, key: movedKey, group };
        const inGroup = (entry: EditorTab) => entry.workspaceId === workspaceId && (entry.group ?? 0) === group;
        let at = before ? rest.findIndex((entry) => entry.key === before && inGroup(entry)) : -1;
        // No tab to land in front of: after the group's last one.
        if (at < 0) at = rest.reduce((last, entry, index) => (inGroup(entry) ? index + 1 : last), rest.length);
        tabs = [...rest.slice(0, at), moved, ...rest.slice(at)];
      }
      const actives: Record<number, string | null> = { ...state.groupActive[workspaceId], [group]: movedKey };
      if (group !== origin && source?.active?.key === key) actives[origin] = successor(source.tabs, key, new Set([key]));
      return {
        tabs,
        ...settle(
          {
            ...state,
            tabs,
            layout: { ...state.layout, [workspaceId]: layout },
            groupActive: { ...state.groupActive, [workspaceId]: actives },
            focusedGroup: { ...state.focusedGroup, [workspaceId]: group },
          },
          [workspaceId],
        ),
      };
    }),

  openFile: (workspaceId, path, options = {}) => {
    const mode = options.mode ?? "edit";
    const preview = options.preview ?? true;
    const fileKey = fileKeyOf(workspaceId, path);
    set((state) => {
      // The group that takes the file: the one named, the one to the right of
      // the group that has the keyboard ("to the side"), or that group itself.
      const groups = groupsOf(state, workspaceId);
      const focused = groups.find((entry) => entry.focused) ?? groups[0];
      const order = groups.map((entry) => entry.id);
      let layout = layoutFor(state.layout[workspaceId], order);
      let group = options.group !== undefined && order.includes(options.group) ? options.group : focused.id;
      // With nothing open there is nothing to stand beside: the file simply opens.
      if (options.group === undefined && (options.side || options.split) && focused.tabs.length > 0) {
        const at = order.indexOf(focused.id);
        // "To the side" uses the group already standing there; a split never does.
        const beside = options.split ? undefined : order[at + 1];
        if (beside !== undefined) group = beside;
        else {
          group = Math.max(...order) + 1;
          layout = insertBeside(layout, focused.id, group, "right");
        }
      }
      const target = groups.find((entry) => entry.id === group);
      const key = tabKeyOf(mode, fileKey, group);
      let tabs = state.tabs;
      const existing = tabs.find((tab) => tab.key === key);
      if (existing) {
        if (!preview && existing.preview) tabs = tabs.map((tab) => (tab.key === key ? { ...tab, preview: false } : tab));
      } else {
        const tab: EditorTab = { key, fileKey, workspaceId, path, mode, preview, group };
        // One preview tab per group: the next open in that group replaces it.
        const replaced = target?.tabs.find((entry) => entry.preview && !state.files[entry.fileKey]?.dirty);
        if (replaced) {
          tabs = tabs.map((entry) => (entry.key === replaced.key ? tab : entry));
        } else {
          const activeKey = target?.active?.key;
          const at = activeKey ? tabs.findIndex((entry) => entry.key === activeKey) : -1;
          tabs = at < 0 ? [...tabs, tab] : [...tabs.slice(0, at + 1), tab, ...tabs.slice(at + 1)];
        }
      }
      const files = state.files[fileKey] ? state.files : { ...state.files, [fileKey]: newFile(workspaceId, path) };
      const reveal =
        options.line != null
          ? { fileKey, line: options.line, column: options.column ?? 1, length: options.length ?? 0, nonce: ++revealNonce }
          : state.reveal;
      // A diff opened from a pane review compares against that review's base;
      // one opened anywhere else goes back to the last commit.
      let diffBases = state.diffBases;
      if (mode === "diff" && diffBases[fileKey]?.ref !== options.base?.ref) {
        diffBases = { ...diffBases };
        if (options.base) diffBases[fileKey] = options.base;
        else delete diffBases[fileKey];
      }
      return {
        tabs,
        files: prune(files, tabs),
        ...settle(
          {
            ...state,
            tabs,
            layout: { ...state.layout, [workspaceId]: layout },
            groupActive: { ...state.groupActive, [workspaceId]: { ...state.groupActive[workspaceId], [group]: key } },
            focusedGroup: { ...state.focusedGroup, [workspaceId]: group },
          },
          [workspaceId],
        ),
        visible: true,
        reveal,
        diffBases,
      };
    });
  },

  closeTab: (key) => get().closeTabs([key]),

  closeTabs: (keys) =>
    set((state) => {
      const closing = new Set(keys);
      const gone = state.tabs.filter((tab) => closing.has(tab.key));
      if (gone.length === 0) return {};
      const tabs = state.tabs.filter((tab) => !closing.has(tab.key));
      const groupActive = { ...state.groupActive };
      const focusedGroup = { ...state.focusedGroup };
      const workspaceIds = new Set(gone.map((tab) => tab.workspaceId));
      for (const workspaceId of workspaceIds) {
        const groups = groupsOf(state, workspaceId);
        const actives: Record<number, string | null> = { ...groupActive[workspaceId] };
        for (const group of groups) {
          if (group.active && closing.has(group.active.key)) actives[group.id] = successor(group.tabs, group.active.key, closing);
        }
        groupActive[workspaceId] = actives;
        // A group whose last tab closes disappears; the keyboard goes to the
        // group on its left, else to the one on its right.
        const survives = (group: EditorGroup) => group.tabs.some((tab) => !closing.has(tab.key));
        const at = groups.findIndex((group) => group.focused);
        if (at >= 0 && !survives(groups[at])) {
          const neighbour = groups.slice(0, at).reverse().find(survives) ?? groups.slice(at + 1).find(survives);
          if (neighbour) focusedGroup[workspaceId] = neighbour.id;
        }
      }
      const closed = [...state.closed, ...gone.map(({ workspaceId, path, mode }) => ({ workspaceId, path, mode }))];
      return {
        tabs,
        files: prune(state.files, tabs),
        closed: closed.slice(-MAX_CLOSED),
        ...settle({ ...state, tabs, groupActive, focusedGroup }, workspaceIds),
      };
    }),

  // A click on a tab shows it in its group and hands that group the keyboard.
  activate: (key) => {
    const tab = get().tabs.find((entry) => entry.key === key);
    if (!tab) return;
    const group = tab.group ?? 0;
    set((state) => ({
      ...settle(
        {
          ...state,
          groupActive: { ...state.groupActive, [tab.workspaceId]: { ...state.groupActive[tab.workspaceId], [group]: key } },
          focusedGroup: { ...state.focusedGroup, [tab.workspaceId]: group },
        },
        [tab.workspaceId],
      ),
      visible: true,
    }));
  },

  pinTab: (key) =>
    set((state) => ({ tabs: state.tabs.map((tab) => (tab.key === key && tab.preview ? { ...tab, preview: false } : tab)) })),

  cycle: (workspaceId, step) =>
    set((state) => {
      // Ctrl+Tab steps through the tabs of the group that has the keyboard.
      const group = groupsOf(state, workspaceId).find((entry) => entry.focused);
      if (!group || group.tabs.length === 0) return {};
      const index = group.tabs.findIndex((tab) => tab.key === group.active?.key);
      const next = group.tabs[(index + step + group.tabs.length) % group.tabs.length];
      return settle(
        { ...state, groupActive: { ...state.groupActive, [workspaceId]: { ...state.groupActive[workspaceId], [group.id]: next.key } } },
        [workspaceId],
      );
    }),

  reopenClosed: (workspaceId) => {
    const closed = [...get().closed];
    for (let index = closed.length - 1; index >= 0; index -= 1) {
      const entry = closed[index];
      if (entry.workspaceId !== workspaceId) continue;
      closed.splice(index, 1);
      set({ closed });
      get().openFile(entry.workspaceId, entry.path, { mode: entry.mode, preview: false });
      return;
    }
  },

  patchFile: (fileKey, patch) =>
    set((state) => {
      const current = state.files[fileKey];
      if (!current) return {};
      const file = { ...current, ...patch };
      // An edit keeps a preview tab, the way typing in it would.
      const tabs =
        patch.dirty && !current.dirty
          ? state.tabs.map((tab) => (tab.fileKey === fileKey && tab.preview ? { ...tab, preview: false } : tab))
          : state.tabs;
      return { files: { ...state.files, [fileKey]: file }, tabs };
    }),

  setVisible: (visible) => set({ visible }),
  setQuickOpen: (quickOpen) => set({ quickOpen }),
  setCursor: (cursor) => set({ cursor }),

  renamePath: (workspaceId, from, to) =>
    set((state) => {
      const moved = (path: string) => (isUnder(path, from) ? to + path.slice(from.length) : path);
      const rekeyed = new Map<string, string>();
      const tabs = state.tabs.map((tab) => {
        if (tab.workspaceId !== workspaceId || !isUnder(tab.path, from)) return tab;
        const path = moved(tab.path);
        const fileKey = fileKeyOf(workspaceId, path);
        const key = tabKeyOf(tab.mode, fileKey, tab.group ?? 0);
        rekeyed.set(tab.key, key);
        return { ...tab, path, fileKey, key };
      });
      const files: Record<string, EditorFile> = {};
      for (const [key, file] of Object.entries(state.files)) {
        if (file.workspaceId !== workspaceId || !isUnder(file.path, from)) files[key] = file;
        else {
          const path = moved(file.path);
          files[fileKeyOf(workspaceId, path)] = { ...file, path };
        }
      }
      // Each group keeps showing the tab it showed, under its new key.
      const actives: Record<number, string | null> = {};
      for (const group of groupsOf(state, workspaceId)) {
        const key = group.active?.key ?? null;
        actives[group.id] = key ? (rekeyed.get(key) ?? key) : null;
      }
      return {
        tabs,
        files,
        ...settle({ ...state, tabs, groupActive: { ...state.groupActive, [workspaceId]: actives } }, [workspaceId]),
      };
    }),

  restoreTabs: (workspaceId, restored, activePath) =>
    set((state) => {
      // Restored tabs go into the first group; a split is not remembered.
      const first = groupsOf(state, workspaceId)[0];
      const group = first.id;
      const known = new Set(state.tabs.map((tab) => tab.key));
      const files = { ...state.files };
      const added: EditorTab[] = [];
      for (const entry of restored) {
        const fileKey = fileKeyOf(workspaceId, entry.path);
        const key = tabKeyOf(entry.mode, fileKey, group);
        if (known.has(key)) continue;
        known.add(key);
        added.push({ key, fileKey, workspaceId, path: entry.path, mode: entry.mode, preview: entry.preview, group });
        files[fileKey] ??= newFile(workspaceId, entry.path);
      }
      if (added.length === 0) return {};
      const tabs = [...state.tabs, ...added];
      const activeKey =
        first.active?.key ??
        added.find((tab) => tab.path === activePath && tab.mode === "edit")?.key ??
        added.find((tab) => tab.path === activePath)?.key ??
        added[0].key;
      return {
        tabs,
        files,
        ...settle(
          { ...state, tabs, groupActive: { ...state.groupActive, [workspaceId]: { ...state.groupActive[workspaceId], [group]: activeKey } } },
          [workspaceId],
        ),
      };
    }),

  markDeleted: (workspaceId, path) =>
    set((state) => {
      const files = { ...state.files };
      for (const [key, file] of Object.entries(files)) {
        if (file.workspaceId === workspaceId && isUnder(file.path, path)) files[key] = { ...file, deleted: true, version: null };
      }
      return { files };
    }),
}));

/** The tabs of one workspace, every group's, in order. */
export function tabsOf(state: Pick<CodeEditorState, "tabs">, workspaceId: string | null): EditorTab[] {
  return workspaceId ? state.tabs.filter((tab) => tab.workspaceId === workspaceId) : [];
}

// An unsaved buffer holds off the automatic reload a new frontend build
// triggers (lib/bundleWatch), so a rebuild never throws away typed code.
useCodeEditorStore.subscribe((state) => {
  setReloadHold(
    "code-editor",
    Object.values(state.files).some((file) => file.dirty),
  );
});
