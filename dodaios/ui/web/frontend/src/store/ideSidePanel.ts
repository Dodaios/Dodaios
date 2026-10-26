import { create } from "zustand";

/**
 * The Agentic IDE's right-hand side panel: open or shut, which tabs it holds,
 * and which one is in front.
 *
 * The panel, its closed-state rail and the explorer path routing all need the
 * answer, so it lives in one store. The state survives a reload through localStorage, which may be
 * blocked — every read and write degrades to the defaults instead of throwing.
 */

/** Every function the panel can show. A new one is a new id plus a registry entry. */
export type SidePanelTabId = "browser" | "agents" | "changes" | "files" | "search" | "git" | "skills" | "chat" | "subscriptions" | "office" | `terminal:${string}`;

export interface SidePanelTerminal {
  id: `terminal:${string}`;
  workspaceId: string;
  workspaceName: string;
  number: number;
  /** Absolute folder the shell starts in; omitted = the workspace's own folder. */
  folder?: string;
}

export const MAX_TERMINAL_TABS = 16;

export const SIDE_PANEL_TAB_IDS: readonly SidePanelTabId[] = ["browser", "agents", "changes", "files", "search", "git", "skills", "chat", "subscriptions", "office"];

/**
 * DOM id of the panel host, for the toggle's `aria-controls`.
 *
 * It lives here rather than in the panel's module because the toggle sits in
 * the always-loaded window caption: importing it from `IdeSidePanel` linked the
 * whole panel (explorer, git overview, agents overview) into the entry chunk.
 */
export const SIDE_PANEL_ID = "ide-side-panel";

const OPEN_KEY = "jarvis.agenticIde.sidePanelOpen";
// v5: the panel starts empty and offers the "Open a surface" launcher; the
// reader picks what to open (maintainer, 2026-10-07). Older lists reopened
// every tab they had ever added.
const TABS_KEY = "jarvis.agenticIde.sidePanelTabs.v5";

const SPLIT_KEY = "jarvis.agenticIde.sidePanelSplit.v1";

const DEFAULT_TABS: SidePanelTabId[] = [];
/** Share of the panel the first column takes while two tabs sit side by side. */
export const DEFAULT_SPLIT_RATIO = 0.5;
export const MIN_SPLIT_RATIO = 0.2;
export const MAX_SPLIT_RATIO = 0.8;

/** The two columns of a split panel: 0 holds `active`, 1 holds `split`. */
export type SidePanelColumn = 0 | 1;

const clampRatio = (value: number) => Math.min(MAX_SPLIT_RATIO, Math.max(MIN_SPLIT_RATIO, value));
/** Stand-in for `active` while no tab is open; the panel then shows the launcher. */
const NO_TAB: SidePanelTabId = "agents";

const isTabId = (value: unknown): value is SidePanelTabId =>
  typeof value === "string" && (SIDE_PANEL_TAB_IDS as readonly string[]).includes(value);

function storedOpen(): boolean {
  try {
    return localStorage.getItem(OPEN_KEY) === "1";
  } catch {
    return false;
  }
}

function storedSplit(tabs: SidePanelTabId[], active: SidePanelTabId): { split: SidePanelTabId | null; splitRatio: number } {
  try {
    const raw = JSON.parse(localStorage.getItem(SPLIT_KEY) ?? "null") as { split?: unknown; ratio?: unknown } | null;
    const ratio = typeof raw?.ratio === "number" && Number.isFinite(raw.ratio) ? clampRatio(raw.ratio) : DEFAULT_SPLIT_RATIO;
    const split = isTabId(raw?.split) && tabs.includes(raw.split) && raw.split !== active ? raw.split : null;
    return { split, splitRatio: ratio };
  } catch {
    return { split: null, splitRatio: DEFAULT_SPLIT_RATIO };
  }
}

function persistSplit(split: SidePanelTabId | null, ratio: number): void {
  try {
    // A shell does not survive a reload, so a split onto one is not kept either.
    localStorage.setItem(SPLIT_KEY, JSON.stringify({ split: split && isTabId(split) ? split : null, ratio }));
  } catch {
    /* a convenience only */
  }
}

function storedTabs(): { tabs: SidePanelTabId[]; active: SidePanelTabId } {
  try {
    const raw = JSON.parse(localStorage.getItem(TABS_KEY) ?? "null") as {
      tabs?: unknown;
      active?: unknown;
    } | null;
    const tabs = Array.isArray(raw?.tabs) ? [...new Set(raw.tabs.filter(isTabId))] : [];
    if (tabs.length === 0) return { tabs: DEFAULT_TABS, active: NO_TAB };
    return { tabs, active: isTabId(raw?.active) && tabs.includes(raw.active) ? raw.active : tabs[0] };
  } catch {
    return { tabs: DEFAULT_TABS, active: NO_TAB };
  }
}

function persist(open: boolean, tabs: SidePanelTabId[], active: SidePanelTabId): void {
  try {
    localStorage.setItem(OPEN_KEY, open ? "1" : "0");
    // Shell processes belong to this window. A reload must not silently start
    // replacements for commands that were running before the window closed.
    const saved = tabs.filter(isTabId);
    localStorage.setItem(TABS_KEY, JSON.stringify({ tabs: saved, active: isTabId(active) ? active : saved[0] ?? NO_TAB }));
  } catch {
    /* a convenience only: the panel still works for this session */
  }
}

/**
 * The pane an agent card pointed at: the grid frames it in the signal blue
 * until the user focuses another pane, picks another card, or closes the panel.
 */
export interface PaneSpotlight {
  workspaceId: string;
  pane: string;
}

interface IdeSidePanelState {
  open: boolean;
  tabs: SidePanelTabId[];
  active: SidePanelTabId;
  terminals: SidePanelTerminal[];
  /** `folder` starts the shell in that folder of the workspace instead of its root. */
  addTerminalTab: (workspaceId: string, workspaceName: string, folder?: string) => void;
  setOpen: (open: boolean) => void;
  /**
   * Second tab shown beside `active` (the panel split into two columns), or
   * null for one tab at a time.
   */
  split: SidePanelTabId | null;
  /** Width share of the first column while split. Persisted. */
  splitRatio: number;
  setSplitRatio: (ratio: number) => void;
  /** Column a tab click or a newly opened tab goes to while split. */
  focusedColumn: SidePanelColumn;
  setFocusedColumn: (column: SidePanelColumn) => void;
  /**
   * Show `id` in `column`, splitting the panel when it was not. The other
   * column keeps what it showed; when that was `id` itself, the neighbouring
   * tab fills it. No-op with a single tab open.
   */
  splitWith: (id: SidePanelTabId, column: SidePanelColumn) => void;
  /** Split the panel with the tab next to the one in front, or join it back. */
  toggleSplit: () => void;
  /** Back to one tab: the focused column's tab stays in front. */
  unsplit: () => void;
  /** Open a tab (or bring it forward when it is already open). */
  openTab: (id: SidePanelTabId) => void;
  select: (id: SidePanelTabId) => void;
  /** Closing the last tab leaves the panel open on the "Open a surface" launcher. */
  closeTab: (id: SidePanelTabId) => void;
  spotlight: PaneSpotlight | null;
  setSpotlight: (spotlight: PaneSpotlight | null) => void;
  /**
   * The panel covers the whole IDE view (the office walked full-size). Not
   * persisted: a reload always comes back to the terminals.
   */
  maximized: boolean;
  setMaximized: (maximized: boolean) => void;
  /**
   * The reader is working in the panel: their last press landed in it rather
   * than in a terminal. The panel then wears the blue "you are here" frame a
   * focused terminal wears, and the terminal lets go of its own. A press on
   * a pane hands it back. Not persisted.
   */
  inUse: boolean;
  setInUse: (inUse: boolean) => void;
}

const initialTabs = storedTabs();
const initialSplit = storedSplit(initialTabs.tabs, initialTabs.active);

/** The tab beside `id` in the strip: the next one, else the previous one. */
function neighbour(tabs: SidePanelTabId[], id: SidePanelTabId): SidePanelTabId | null {
  const index = tabs.indexOf(id);
  return tabs[index + 1] ?? tabs[index - 1] ?? null;
}

export const useIdeSidePanelStore = create<IdeSidePanelState>((set, get) => {
  const commit = (next: Partial<Pick<IdeSidePanelState, "open" | "tabs" | "active" | "split">>) => {
    const merged = { open: get().open, tabs: get().tabs, active: get().active, split: get().split, ...next };
    if (merged.split && (merged.split === merged.active || !merged.tabs.includes(merged.split))) merged.split = null;
    set(merged.split ? merged : { ...merged, focusedColumn: 0 });
    persist(merged.open, merged.tabs, merged.active);
    persistSplit(merged.split, get().splitRatio);
  };
  /** Bring an open tab into view: into the focused column while split. */
  const show = (id: SidePanelTabId, tabs: SidePanelTabId[]) => {
    const { split, active, focusedColumn } = get();
    if (!split) return commit({ open: true, tabs, active: id });
    if (id === active) {
      set({ focusedColumn: 0 });
      return commit({ open: true, tabs });
    }
    if (id === split) {
      set({ focusedColumn: 1 });
      return commit({ open: true, tabs });
    }
    commit(focusedColumn === 1 ? { open: true, tabs, split: id } : { open: true, tabs, active: id });
  };
  return {
    open: storedOpen(),
    tabs: initialTabs.tabs,
    active: initialTabs.active,
    terminals: [],
    addTerminalTab: (workspaceId, workspaceName, folder) => {
      if (!workspaceId) return;
      const { terminals, tabs } = get();
      const siblings = terminals.filter((terminal) => terminal.workspaceId === workspaceId);
      if (siblings.length >= MAX_TERMINAL_TABS) return;
      const id = `terminal:${crypto.randomUUID()}` as const;
      const number = Math.max(0, ...siblings.map((terminal) => terminal.number)) + 1;
      set({ terminals: [...terminals, { id, workspaceId, workspaceName, number, ...(folder ? { folder } : {}) }] });
      show(id, [...tabs, id]);
    },
    spotlight: null,
    setSpotlight: (spotlight) => set({ spotlight }),
    maximized: false,
    setMaximized: (maximized) => set({ maximized: maximized && get().open }),
    inUse: false,
    setInUse: (inUse) => { if (get().inUse !== inUse) set({ inUse: inUse && get().open }); },
    setOpen: (open) => {
      if (!open) set({ spotlight: null, maximized: false, inUse: false });
      commit({ open });
    },
    split: initialSplit.split,
    splitRatio: initialSplit.splitRatio,
    setSplitRatio: (ratio) => {
      const splitRatio = clampRatio(ratio);
      set({ splitRatio });
      persistSplit(get().split, splitRatio);
    },
    focusedColumn: 0,
    setFocusedColumn: (column) => { if (get().split && get().focusedColumn !== column) set({ focusedColumn: column }); },
    splitWith: (id, column) => {
      const { tabs, active, split } = get();
      if (!tabs.includes(id)) return;
      const first: SidePanelTabId | null = active;
      const second: SidePanelTabId | null = split ?? (active === id ? neighbour(tabs, id) : active);
      // The column that does not get `id` keeps its tab; if it held `id`, the
      // two trade places (or the neighbour steps in when there was no split).
      const other = column === 0 ? (second === id ? first : second) : (first === id ? second : first);
      if (!other || other === id) return;
      set({ focusedColumn: column });
      commit(column === 0 ? { open: true, active: id, split: other } : { open: true, active: other, split: id });
    },
    toggleSplit: () => {
      const { split, tabs, active } = get();
      if (split) return get().unsplit();
      const other = neighbour(tabs, active);
      if (other) get().splitWith(other, 1);
    },
    unsplit: () => {
      const { split, active, focusedColumn } = get();
      if (!split) return;
      commit({ active: focusedColumn === 1 ? split : active, split: null });
    },
    openTab: (id) => {
      const { tabs } = get();
      show(id, tabs.includes(id) ? tabs : [...tabs, id]);
    },
    select: (id) => {
      if (get().tabs.includes(id)) show(id, get().tabs);
    },
    closeTab: (id) => {
      const { tabs, active, split } = get();
      const index = tabs.indexOf(id);
      if (index < 0) return;
      const rest = tabs.filter((tab) => tab !== id);
      set({ terminals: get().terminals.filter((terminal) => terminal.id !== id) });
      // Closing either half of a split leaves the other half in front, alone.
      if (split && id === split) return commit({ tabs: rest, split: null });
      if (split && id === active) return commit({ tabs: rest, active: split, split: null });
      if (rest.length === 0) {
        set({ spotlight: null, maximized: false });
        commit({ tabs: DEFAULT_TABS, active: NO_TAB });
        return;
      }
      commit({ tabs: rest, active: active === id ? rest[Math.max(0, index - 1)] : active });
    },
  };
});
