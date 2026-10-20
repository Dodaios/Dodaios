/**
 * The build "Built for you" should open on, requested from OUTSIDE the view.
 *
 * A "built by" badge on an agent, a skill or a routine links to the build that
 * made it. The view may not be mounted yet, so the request is parked here, the
 * section opens, and the view takes the id over on mount — a one-shot hand-off
 * like `settingsJump`.
 */
import { create } from "zustand";
import { useEventStore } from "@/store/events";

interface SelfBuildFocusState {
  buildId: string | null;
  request: (buildId: string) => void;
  take: () => string | null;
}

export const useSelfBuildFocus = create<SelfBuildFocusState>((set, get) => ({
  buildId: null,
  request: (buildId) => set({ buildId }),
  take: () => {
    const { buildId } = get();
    if (buildId !== null) set({ buildId: null });
    return buildId;
  },
}));

/** Open "Built for you" on one build. */
export function openBuild(buildId: string): void {
  useSelfBuildFocus.getState().request(buildId);
  useEventStore.getState().setActiveSection("self-build");
}
