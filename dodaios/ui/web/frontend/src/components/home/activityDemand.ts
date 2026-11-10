import type { TimelineItem } from "@/components/agentchat/reduce";

/**
 * When the front page's activity panel shows itself.
 *
 * Small and pure on purpose: HomeView is on the first paint, the panel is
 * not, so the question "is there anything to show?" must not pull the panel
 * module in.
 */

/** Where the person's own open/close choice is kept. */
export const PANEL_KEY = "dodaios.home.activity.v1";

/** "open" / "closed" when the person chose; null while it follows the work. */
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
 * work runs (a turn answering, a hand-off in the background).
 */
export function hasActivityDemand(items: readonly TimelineItem[]): boolean {
  for (const item of items) {
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
 * Closed by default; open while there is something to show. The person's
 * explicit choice wins over both: "open" keeps it open on a quiet page,
 * "closed" keeps it shut while work runs.
 */
export function panelOpen(choice: PanelChoice, demand: boolean): boolean {
  if (choice === "open") return true;
  if (choice === "closed") return false;
  return demand;
}
