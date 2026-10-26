import { create } from "zustand";

import { isSectionId, useEventStore, type SectionId } from "@/store/events";
import { sectionWindow } from "@/lib/sectionWindows";
import {
  dwindleDir,
  findLeaf,
  isTileable,
  layoutLeaves,
  leafForSection,
  leaves,
  MAX_TILES,
  parseTree,
  pickSections,
  PRESETS,
  removeLeaf,
  setLeafSection,
  setRatio,
  splitLeaf,
  swapLeaves,
  type PresetId,
  type TileDir,
  type TileNode,
} from "@/lib/tilingLayout";

/**
 * Which sections share the main window, and how.
 *
 * `tree` null is the classic shape: one section fills the stage. Two or more
 * leaves tile the stage over the wallpaper. The focused tile always shows the
 * active section, so every existing way of navigating (sidebar, quick
 * switcher, voice, back/forward) changes the focused tile — or focuses the
 * tile that already shows the target.
 *
 * The layout survives a reload through localStorage, which may be blocked —
 * every read and write degrades to the classic single section.
 */
const STORE_KEY = "jarvis.tiling.layout.v1";

/** Width / height the stage is assumed to have before it was measured. */
const DEFAULT_ASPECT = 16 / 9;

interface TilingState {
  tree: TileNode | null;
  focusedId: string | null;
  /** A tile temporarily filling the whole stage; the others stay mounted. */
  maximizedId: string | null;
  /** Measured stage width / height, for picking split directions. */
  stageAspect: number;
  setStageAspect: (aspect: number) => void;
  applyPreset: (preset: PresetId) => void;
  /** Open `section` in a new tile beside the focused one. */
  openBeside: (section: SectionId, dir?: TileDir) => void;
  splitTile: (id: string, dir: TileDir) => void;
  closeTile: (id: string) => void;
  focusTile: (id: string) => void;
  setTileSection: (id: string, section: SectionId) => void;
  swapTiles: (first: string, second: string) => void;
  resize: (splitId: string, ratio: number) => void;
  toggleMaximize: (id: string) => void;
  /** Keep the tiles in step with a navigation to `section`. */
  follow: (section: SectionId) => void;
}

function readStored(): { tree: TileNode | null; focusedIndex: number } {
  try {
    const raw = window.localStorage.getItem(STORE_KEY);
    if (!raw) return { tree: null, focusedIndex: 0 };
    const parsed = JSON.parse(raw) as { tree?: unknown; focused?: unknown };
    const tree = parseTree(parsed.tree, isSectionId);
    const focusedIndex = typeof parsed.focused === "number" ? parsed.focused : 0;
    return { tree, focusedIndex };
  } catch {
    return { tree: null, focusedIndex: 0 };
  }
}

function strip(node: TileNode): unknown {
  return node.kind === "leaf"
    ? { kind: "leaf", section: node.section }
    : { kind: "split", dir: node.dir, ratio: node.ratio, a: strip(node.a), b: strip(node.b) };
}

function persist(tree: TileNode | null, focusedId: string | null) {
  try {
    if (!tree) {
      window.localStorage.removeItem(STORE_KEY);
      return;
    }
    const focused = Math.max(0, leaves(tree).findIndex((item) => item.id === focusedId));
    window.localStorage.setItem(STORE_KEY, JSON.stringify({ tree: strip(tree), focused }));
  } catch {
    /* storage unavailable: the layout simply does not survive a reload */
  }
}

function navigate(section: SectionId) {
  const events = useEventStore.getState();
  if (events.activeSection !== section) events.setActiveSection(section);
}

const stored = readStored();
const storedLeaves = leaves(stored.tree);

export const useTilingStore = create<TilingState>((set, get) => {
  /** Commit a new tree; one leaf left collapses back to the classic shape. */
  const commit = (tree: TileNode | null, focusedId: string | null) => {
    const remaining = leaves(tree);
    if (remaining.length <= 1) {
      set({ tree: null, focusedId: null, maximizedId: null });
      persist(null, null);
      if (remaining[0]) navigate(remaining[0].section);
      return;
    }
    const focus = remaining.find((item) => item.id === focusedId) ?? remaining[0];
    const maximizedId = findLeaf(tree, get().maximizedId) ? get().maximizedId : null;
    set({ tree, focusedId: focus.id, maximizedId });
    persist(tree, focus.id);
    navigate(focus.section);
  };

  const currentSection = (): SectionId => {
    const active = useEventStore.getState().activeSection;
    if (isTileable(active)) return active;
    return findLeaf(get().tree, get().focusedId)?.section ?? "chats";
  };

  return {
    tree: stored.tree,
    focusedId: storedLeaves[Math.min(stored.focusedIndex, storedLeaves.length - 1)]?.id ?? null,
    maximizedId: null,
    stageAspect: DEFAULT_ASPECT,

    setStageAspect: (aspect) => {
      if (Number.isFinite(aspect) && aspect > 0 && Math.abs(aspect - get().stageAspect) > 0.01) {
        set({ stageAspect: aspect });
      }
    },

    applyPreset: (presetId) => {
      const preset = PRESETS.find((item) => item.id === presetId);
      if (!preset) return;
      const shown = leaves(get().tree).map((item) => item.section);
      const focused = currentSection();
      const sections = pickSections([focused, ...shown], preset.slots);
      if (preset.slots === 1) {
        commit(null, null);
        navigate(focused);
        return;
      }
      const tree = preset.build(sections);
      const focus = leafForSection(tree, focused);
      set({ maximizedId: null });
      commit(tree, focus?.id ?? null);
    },

    openBeside: (section, dir) => {
      if (!isTileable(section)) {
        navigate(section);
        return;
      }
      const { tree, focusedId, stageAspect } = get();
      const existing = leafForSection(tree, section);
      if (existing) {
        get().focusTile(existing.id);
        if (existing.section !== section) get().setTileSection(existing.id, section);
        return;
      }
      if (!tree) {
        const base = currentSection();
        if (sectionWindow(base) === sectionWindow(section)) {
          navigate(section);
          return;
        }
        const preset = PRESETS.find((item) => item.id === (dir === "column" ? "rows-2" : "columns-2"));
        if (!preset) return;
        const next = preset.build([base, section]);
        commit(next, leaves(next)[1].id);
        return;
      }
      if (leaves(tree).length >= MAX_TILES) {
        const target = findLeaf(tree, focusedId) ?? leaves(tree)[0];
        commit(setLeafSection(tree, target.id, section), target.id);
        return;
      }
      const target = layoutLeaves(tree).find((item) => item.leaf.id === focusedId) ?? layoutLeaves(tree)[0];
      const result = splitLeaf(tree, target.leaf.id, section, dir ?? dwindleDir(target.rect, stageAspect));
      commit(result.tree, result.added.id);
    },

    splitTile: (id, dir) => {
      const { tree } = get();
      if (!tree || leaves(tree).length >= MAX_TILES) return;
      const shown = leaves(tree).map((item) => item.section);
      const [next] = pickSections(shown, shown.length + 1).slice(shown.length);
      if (!next) return;
      const result = splitLeaf(tree, id, next, dir);
      commit(result.tree, result.added.id);
    },

    closeTile: (id) => {
      const { tree, focusedId } = get();
      if (!tree) return;
      const order = leaves(tree);
      const index = order.findIndex((item) => item.id === id);
      const next = removeLeaf(tree, id);
      const fallback = order[index + 1] ?? order[index - 1];
      commit(next, focusedId === id ? fallback?.id ?? null : focusedId);
    },

    focusTile: (id) => {
      const target = findLeaf(get().tree, id);
      if (!target) return;
      if (get().focusedId !== id) {
        set({ focusedId: id });
        persist(get().tree, id);
      }
      navigate(target.section);
    },

    setTileSection: (id, section) => {
      const { tree } = get();
      if (!tree || !isTileable(section)) return;
      const other = leafForSection(tree, section);
      if (other && other.id !== id) {
        commit(swapLeaves(tree, id, other.id), id);
        return;
      }
      commit(setLeafSection(tree, id, section), id);
    },

    swapTiles: (first, second) => {
      const { tree, focusedId } = get();
      if (!tree) return;
      commit(swapLeaves(tree, first, second), focusedId);
    },

    resize: (splitId, ratio) => {
      const { tree, focusedId } = get();
      if (!tree) return;
      const next = setRatio(tree, splitId, ratio);
      if (next === tree) return;
      set({ tree: next });
      persist(next, focusedId);
    },

    toggleMaximize: (id) => {
      if (!findLeaf(get().tree, id)) return;
      set({ maximizedId: get().maximizedId === id ? null : id });
      get().focusTile(id);
    },

    follow: (section) => {
      const { tree, focusedId, maximizedId } = get();
      if (!tree || !isTileable(section)) return;
      const existing = leafForSection(tree, section);
      if (existing) {
        const next = existing.section === section ? tree : setLeafSection(tree, existing.id, section);
        const patch: Partial<TilingState> = {};
        if (next !== tree) patch.tree = next;
        if (existing.id !== focusedId) patch.focusedId = existing.id;
        if (maximizedId && maximizedId !== existing.id) patch.maximizedId = null;
        if (Object.keys(patch).length) {
          set(patch);
          persist(next, existing.id);
        }
        return;
      }
      const target = findLeaf(tree, focusedId) ?? leaves(tree)[0];
      const next = setLeafSection(tree, target.id, section);
      set({ tree: next, focusedId: target.id });
      persist(next, target.id);
    },
  };
});

/** True while `section`'s window family is on screen: active, or in a tile. */
export function isSectionOnScreen(section: SectionId): boolean {
  const owner = sectionWindow(section);
  if (sectionWindow(useEventStore.getState().activeSection) === owner) return true;
  const { tree, maximizedId } = useTilingStore.getState();
  if (!tree || maximizedId) return false;
  return leaves(tree).some((item) => sectionWindow(item.section) === owner);
}

// Every navigation passes through the active section; the tiles follow it.
// Guarded: component tests replace the event store with a bare selector mock.
if (typeof useEventStore.subscribe === "function") {
  useEventStore.subscribe((state, previous) => {
    if (state.solo || state.activeSection === previous.activeSection) return;
    useTilingStore.getState().follow(state.activeSection);
  });

  // A deep link (`?view=`) or a restored section lands in the stored layout. A
  // dialog section (Settings, Plugins) simply opens over the tiles.
  if (stored.tree && !useEventStore.getState().solo) {
    useTilingStore.getState().follow(useEventStore.getState().activeSection);
  }
}
