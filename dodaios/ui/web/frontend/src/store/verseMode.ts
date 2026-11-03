import { create } from "zustand";

/**
 * The full-window Verse lives in the Agents section (its "Verse" face). The
 * sidebar's Verse row asks for it from anywhere; the Agents view takes the
 * request when it mounts or while it is open, and reports back whether the
 * Verse is on screen so the row can light up.
 */
interface VerseModeState {
  /** Set by the sidebar row, cleared by the Agents view once it switched. */
  requested: boolean;
  /** True while the Agents view shows the Verse. */
  open: boolean;
  request: () => void;
  take: () => boolean;
  setOpen: (open: boolean) => void;
}

export const useVerseModeStore = create<VerseModeState>((set, get) => ({
  requested: false,
  open: false,
  request: () => set({ requested: true }),
  take: () => {
    if (!get().requested) return false;
    set({ requested: false });
    return true;
  },
  setOpen: (open) => set({ open }),
}));
