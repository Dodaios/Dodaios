/**
 * The designs and the one on screen (docs/designs.md).
 *
 * The backend owns the list (`/api/designs`); this store mirrors it, paints
 * the active design's colours into one <style> element and keeps a copy in
 * localStorage. The boot script in index.html reads that copy before the first
 * paint, so a person with a design never sees the standard colours flash at
 * launch. `UiDesignChanged` over /ws (a design Dodaios just made, a switch in
 * another window) reloads the list.
 */
import { create } from "zustand";
import {
  activateDesign,
  deleteDesign,
  fetchDesigns,
  renameDesign,
  resetDesign,
  STANDARD_DESIGN_ID,
  type Design,
  type DesignsState,
} from "@/lib/designs/designsApi";
import { designCss } from "@/lib/designs/tokens";

/** Shared verbatim with the boot script in index.html. */
export const DESIGN_CACHE_KEY = "jarvis.design";
export const DESIGN_STYLE_ID = "dodaios-design";
export const DESIGN_CLASS = "dodaios-design";

interface CachedDesign {
  css: string;
  design: Design;
}

function readCache(): CachedDesign | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(DESIGN_CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<CachedDesign>;
    if (typeof parsed.css !== "string" || !parsed.design || typeof parsed.design.id !== "string") return null;
    return { css: parsed.css, design: parsed.design };
  } catch {
    return null; // storage blocked or an old, unreadable copy: start standard
  }
}

function writeCache(design: Design | null, css: string): void {
  try {
    if (design) window.localStorage.setItem(DESIGN_CACHE_KEY, JSON.stringify({ css, design }));
    else window.localStorage.removeItem(DESIGN_CACHE_KEY);
  } catch {
    /* storage blocked: the backend still has the choice, only the boot flash returns */
  }
}

/** Put a design's colours on the document, or take them off with `null`. */
export function paintDesign(design: Design | null): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  let style = document.getElementById(DESIGN_STYLE_ID) as HTMLStyleElement | null;
  if (!design) {
    root.classList.remove(DESIGN_CLASS);
    style?.remove();
    writeCache(null, "");
    return;
  }
  const css = designCss(design);
  if (!style) {
    style = document.createElement("style");
    style.id = DESIGN_STYLE_ID;
    document.head.appendChild(style);
  }
  if (style.textContent !== css) style.textContent = css;
  root.classList.add(DESIGN_CLASS);
  writeCache(design, css);
}

interface DesignsStore {
  loaded: boolean;
  active: string;
  designs: Design[];
  /** The design on screen; from the boot cache until the first load lands. */
  current: Design | null;
  load: () => Promise<void>;
  activate: (id: string) => Promise<void>;
  reset: () => Promise<void>;
  remove: (id: string) => Promise<void>;
  rename: (id: string, name: string) => Promise<void>;
}

function currentOf(state: DesignsState): Design | null {
  if (state.active === STANDARD_DESIGN_ID) return null;
  return state.designs.find((d) => d.id === state.active) ?? null;
}

let loading: Promise<void> | null = null;
const cached = readCache();

export const useDesignsStore = create<DesignsStore>((set) => {
  const take = (state: DesignsState) => {
    const current = currentOf(state);
    paintDesign(current);
    set({ loaded: true, active: state.active, designs: state.designs, current });
  };
  return {
    loaded: false,
    active: cached?.design.id ?? STANDARD_DESIGN_ID,
    designs: [],
    current: cached?.design ?? null,
    load: () => {
      if (!loading) {
        loading = fetchDesigns()
          .then(take)
          .catch((err: unknown) => {
            // Offline or the route is not mounted: keep whatever the cache painted.
            if (import.meta.env?.DEV) console.debug("designs load skipped", err);
            set({ loaded: true });
          })
          .finally(() => {
            loading = null;
          });
      }
      return loading;
    },
    activate: async (id) => take(await activateDesign(id)),
    reset: async () => take(await resetDesign()),
    remove: async (id) => take(await deleteDesign(id)),
    rename: async (id, name) => take(await renameDesign(id, name)),
  };
});
