import { create } from "zustand";

/** Where the collapsed/expanded choice for the nav sidebar is remembered. */
export const NAV_COLLAPSED_KEY = "jarvis.sidebar.collapsed.v1";

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(NAV_COLLAPSED_KEY) === "true";
  } catch {
    return false;
  }
}

interface NavSidebarStore {
  /** The sidebar is deliberately collapsed to its icon rail. */
  collapsed: boolean;
  setCollapsed: (collapsed: boolean) => void;
}

/**
 * The app sidebar's rail state, shared so a view can make room for itself:
 * the thread layout's maximize button folds the sidebar to its rail and back.
 * A storage write that throws only means the choice does not survive a restart.
 */
export const useNavSidebarStore = create<NavSidebarStore>((set) => ({
  collapsed: readCollapsed(),
  setCollapsed: (collapsed) => {
    try {
      window.localStorage.setItem(NAV_COLLAPSED_KEY, String(collapsed));
    } catch {
      /* storage unavailable */
    }
    set({ collapsed });
  },
}));
