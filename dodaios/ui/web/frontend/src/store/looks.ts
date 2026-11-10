/**
 * The active look (`docs/looks.md`), shared by every place the orb shows.
 * Loaded once on first use; a pick updates every slot at once.
 */
import { useEffect } from "react";
import { create } from "zustand";
import { fetchLooks, ORB_LOOK_ID, selectLook, type Look } from "@/lib/looksApi";

interface LooksStore {
  loaded: boolean;
  active: string;
  looks: Look[];
  /** Look ids that failed in this run; they fall back to the orb until a new pick. */
  failed: Record<string, true>;
  load: () => Promise<void>;
  pick: (id: string) => Promise<void>;
  markFailed: (id: string) => void;
}

let loading: Promise<void> | null = null;

export const useLooksStore = create<LooksStore>((set, get) => ({
  loaded: false,
  active: ORB_LOOK_ID,
  looks: [],
  failed: {},
  load: () => {
    if (!loading) {
      loading = fetchLooks()
        .then((state) => set({ loaded: true, active: state.active, looks: state.looks }))
        .catch(() => set({ loaded: true }))
        .finally(() => {
          loading = null;
        });
    }
    return loading;
  },
  pick: async (id) => {
    const state = await selectLook(id);
    const failed = { ...get().failed };
    delete failed[id];
    set({ loaded: true, active: state.active, looks: state.looks, failed });
  },
  markFailed: (id) => set((s) => ({ failed: { ...s.failed, [id]: true } })),
}));

/** The look to show now, or `null` for the orb. */
export function useActiveLook(): Look | null {
  const { loaded, active, looks, failed, load } = useLooksStore();
  useEffect(() => {
    if (!loaded) void load();
  }, [loaded, load]);
  if (active === ORB_LOOK_ID || failed[active]) return null;
  return looks.find((look) => look.id === active) ?? null;
}
