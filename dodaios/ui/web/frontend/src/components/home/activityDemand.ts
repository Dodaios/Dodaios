import type { TimelineItem } from "@/components/agentchat/reduce";

/**
 * When the front page's activity panel shows itself, and when its open
 * button wears a live dot.
 *
 * Small and pure on purpose: HomeView is on the first paint, the panel is
 * not, so the question "is there anything to show?" must not pull the panel
 * module in.
 */

/** Where the person's own open/close choice is kept. */
export const PANEL_KEY = "dodaios.home.activity.v1";

/** "open" / "closed" when the person chose; null (closed) while they never did. */
export type PanelChoice = "open" | "closed" | null;

export function readPanelChoice(): PanelChoice {
  try {
    const value = localStorage.getItem(PANEL_KEY);
    return value === "open" || value === "closed" ? value : null;
  } catch {
    // Storage denied: no remembered choice, the panel follows the work.
    return null;
  }
}

export function writePanelChoice(choice: Exclude<PanelChoice, null>): void {
  try {
    localStorage.setItem(PANEL_KEY, choice);
  } catch {
    // Storage denied: the choice holds for this visit only.
  }
}

/**
 * Something waits on the person (an approval or a question still open) or
 * work runs (a turn answering, a hand-off in the background, a side thread).
 */
export function hasActivityDemand(items: readonly TimelineItem[]): boolean {
  for (const item of items) {
    // A side thread still answering is work that runs.
    if (item.type === "notice" && item.kind === "side_thread_started" && item.resolved === "") return true;
    if (item.type !== "turn") continue;
    if (item.status === "running") return true;
    if ((item.background ?? []).length > 0) return true;
    const open = item.blocks.some(
      (block) => block.kind === "tool" && ((block.approval && !block.approval.decision) || (block.question && !block.question.closed)),
    );
    if (open) return true;
  }
  return false;
}

/**
 * Open only while the person keeps it open. Work that runs does not open it:
 * the assistant's own panel stays in place and says what the assistant is
 * doing, and the open button wears a live dot while something waits or runs.
 */
export function panelOpen(choice: PanelChoice): boolean {
  return choice === "open";
}
