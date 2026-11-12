/**
 * The standing task the assistant's page should open on, requested from
 * OUTSIDE the page: the panel on the front page, a suggestion card or a
 * notice line in the conversation.
 *
 * The page may not be mounted yet, so the request is parked here, the section
 * opens, and the page takes it over on mount: a one-shot hand-off like
 * `settingsJump` and `selfBuildFocus`.
 */
import { create } from "zustand";
import { useEventStore } from "@/store/events";

/** `taskId: ""` asks for the list itself, not one task. */
export interface StandingFocus {
  taskId: string;
}

interface StandingFocusState {
  target: StandingFocus | null;
  request: (taskId: string) => void;
  take: () => StandingFocus | null;
}

export const useStandingFocus = create<StandingFocusState>((set, get) => ({
  target: null,
  request: (taskId) => set({ target: { taskId } }),
  take: () => {
    const { target } = get();
    if (target !== null) set({ target: null });
    return target;
  },
}));

/** Open the assistant's page on its standing tasks, or on one of them. */
export function openStandingTasks(taskId = ""): void {
  useStandingFocus.getState().request(taskId);
  useEventStore.getState().setActiveSection("agent-instructions");
}
