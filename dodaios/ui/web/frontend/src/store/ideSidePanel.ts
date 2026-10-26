import { create } from "zustand";
import {
  MAX_PANES,
  evenOut,
  findLeaf,
  findLeafByTab,
  insertBeside,
  leaf,
  leaves,
  parseLayout,
  prune,
  removeLeaf,
  replaceTab,
  resizeAt,
  type DropZone,
  type LayoutNode,
} from "./sidePanelLayout";

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

const LAYOUT_KEY = "jarvis.agenticIde.sidePanelLayout.v1";

const DEFAULT_TABS: SidePanelTabId[] = [];

export type SidePanelLayout = LayoutNode<SidePanelTabId>;
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

function storedLayout(tabs: SidePanelTabId[]): { layout: SidePanelLayout | null; focusedPane: string | null } {
  try {
    const raw = JSON.parse(localStorage.getItem(LAYOUT_KEY) ?? "null") as { layout?: unknown; focused?: unknown } | null;
    const layout = keepTwo(prune(parseLayout(raw?.layout, isTabId), (tab) => tabs.includes(tab)));
    const focused = typeof raw?.focused === "string" && findLeaf(layout, raw.focused) ? raw.focused : leaves(layout)[0]?.id ?? null;
    return { layout, focusedPane: focused };
  } catch {
    return { layout: null, focusedPane: null };
  }
}

function persistLayout(layout: SidePanelLayout | null, focusedPane: string | null): void {
  try {
    // A shell does not survive a reload, so its pane is not kept either.
    localStorage.setItem(LAYOUT_KEY, JSON.stringify({ layout: keepTwo(prune(layout, isTabId)), focused: focusedPane }));
  } catch {
    /* a convenience only */
  }
}

/** One pane left is no split: the panel then shows that tab alone. */
function keepTwo(layout: SidePanelLayout | null): SidePanelLayout | null {
  return leaves(layout).length >= 2 ? layout : null;
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
   * Several tabs on screen at once: a tree of panes, side by side and on top
   * of each other. Null shows `active` alone. Persisted.
   */
  layout: SidePanelLayout | null;
  /** Pane a tab click fills; its tab is `active`. */
  focusedPane: string | null;
  focusPane: (paneId: string) => void;
  /**
   * A tab dropped on a pane. `center` shows it there (two visible tabs trade
   * places); an edge splits that pane and puts the tab beside it, moving it
   * out of its old pane. `paneId` null means the unsplit panel.
   */
  dropTab: (id: SidePanelTabId, paneId: string | null, zone: DropZone) => void;
  /** Take a tab out of the split; it stays open in the strip. */
  detachTab: (id: SidePanelTabId) => void;
  /** Split with the tab next to the one in front, or back to one tab. */
  toggleSplit: () => void;
  /** Move divider `index` of split `splitId` to `share` of that split. */
  resizeSplit: (splitId: string, index: number, share: number) => void;
  /** Give every pane of split `splitId` the same size. */
  evenOutSplit: (splitId: string) => void;
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
const initialLayout = storedLayout(initialTabs.tabs);

/** The tab beside `id` in the strip: the next one, else the previous one. */
function neighbour(tabs: SidePanelTabId[], id: SidePanelTabId): SidePanelTabId | null {
  const index = tabs.indexOf(id);
  return tabs[index + 1] ?? tabs[index - 1] ?? null;
}

export const useIdeSidePanelStore = create<IdeSidePanelState>((set, get) => {
  type Committed = Pick<IdeSidePanelState, "open" | "tabs" | "active" | "layout" | "focusedPane">;
  const commit = (next: Partial<Committed>) => {
    const merged: Committed = {
      open: get().open, tabs: get().tabs, active: get().active, layout: get().layout, focusedPane: get().focusedPane, ...next,
    };
    merged.layout = keepTwo(prune(merged.layout, (tab) => merged.tabs.includes(tab)));
    if (merged.layout) {
      const focused = findLeaf(merged.layout, merged.focusedPane ?? "") ?? leaves(merged.layout)[0];
      merged.focusedPane = focused.id;
      merged.active = focused.tab;
    } else {
      merged.focusedPane = null;
    }
    set(merged);
    persist(merged.open, merged.tabs, merged.active);
    persistLayout(merged.layout, merged.focusedPane);
  };
  /** Bring an open tab into view: into the focused pane while split. */
  const show = (id: SidePanelTabId, tabs: SidePanelTabId[]) => {
    const { layout, focusedPane } = get();
    if (!layout) return commit({ open: true, tabs, active: id });
    const visible = findLeafByTab(layout, id);
    if (visible) return commit({ open: true, tabs, focusedPane: visible.id });
    commit({ open: true, tabs, layout: replaceTab(layout, focusedPane ?? "", id) });
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
    layout: initialLayout.layout,
    focusedPane: initialLayout.focusedPane,
    focusPane: (paneId) => {
      if (get().focusedPane !== paneId && findLeaf(get().layout, paneId)) commit({ focusedPane: paneId });
    },
    dropTab: (id, paneId, zone) => {
      const { tabs, active, layout } = get();
      if (!tabs.includes(id)) return;
      if (!layout) {
        if (zone === "center") return show(id, tabs);
        // The tab in front dropped on its own edge: its neighbour fills the other side.
        const other = id === active ? neighbour(tabs, id) : active;
        if (!other) return;
        const base = leaf(other);
        const added = leaf(id);
        return commit({ open: true, layout: insertBeside(base, base.id, id, zone, added), focusedPane: added.id });
      }
      const target = findLeaf(layout, paneId ?? "");
      if (!target) return;
      const source = findLeafByTab(layout, id);
      if (source?.id === target.id) return commit({ focusedPane: target.id });
      if (zone === "center") {
        // Two visible tabs trade places; a hidden one takes the pane over.
        let next = replaceTab(layout, target.id, id);
        if (source) next = replaceTab(next, source.id, target.tab);
        return commit({ open: true, layout: next, focusedPane: target.id });
      }
      if (!source && leaves(layout).length >= MAX_PANES) return;
      const added = leaf(id);
      const rest = source ? removeLeaf(layout, source.id) : layout;
      const next = rest ? insertBeside(rest, target.id, id, zone, added) : null;
      commit({ open: true, layout: next, focusedPane: added.id });
    },
    detachTab: (id) => {
      const { layout, focusedPane } = get();
      const pane = findLeafByTab(layout, id);
      if (!layout || !pane) return;
      const next = removeLeaf(layout, pane.id);
      const remaining = leaves(next);
      if (!keepTwo(next)) return commit({ layout: null, active: remaining[0]?.tab ?? get().active });
      commit({ layout: next, focusedPane: focusedPane === pane.id ? remaining[0].id : focusedPane });
    },
    toggleSplit: () => {
      const { layout, tabs, active } = get();
      if (layout) return commit({ layout: null, active });
      const other = neighbour(tabs, active);
      if (!other) return;
      const base = leaf(active);
      const added = leaf(other);
      commit({ open: true, layout: insertBeside(base, base.id, other, "right", added), focusedPane: added.id });
    },
    resizeSplit: (splitId, index, share) => {
      const next = resizeAt(get().layout, splitId, index, share);
      if (next === get().layout) return;
      set({ layout: next });
      persistLayout(next, get().focusedPane);
    },
    evenOutSplit: (splitId) => commit({ layout: evenOut(get().layout, splitId) }),
    openTab: (id) => {
      const { tabs } = get();
      show(id, tabs.includes(id) ? tabs : [...tabs, id]);
    },
    select: (id) => {
      if (get().tabs.includes(id)) show(id, get().tabs);
    },
    closeTab: (id) => {
      const { tabs, active, layout } = get();
      const index = tabs.indexOf(id);
      if (index < 0) return;
      const rest = tabs.filter((tab) => tab !== id);
      set({ terminals: get().terminals.filter((terminal) => terminal.id !== id) });
      // A tab on screen in a split takes its pane with it; the others close up.
      if (layout && findLeafByTab(layout, id)) {
        const next = removeLeaf(layout, findLeafByTab(layout, id)!.id);
        return commit({ tabs: rest, layout: next, active: keepTwo(next) ? active : leaves(next)[0]?.tab ?? active });
      }
      if (rest.length === 0) {
        set({ spotlight: null, maximized: false });
        commit({ tabs: DEFAULT_TABS, active: NO_TAB });
        return;
      }
      commit({ tabs: rest, active: active === id ? rest[Math.max(0, index - 1)] : active });
    },
  };
});
