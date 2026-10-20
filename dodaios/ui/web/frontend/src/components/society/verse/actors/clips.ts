/**
 * Which animation clip plays for what a body is doing. Each activity lists
 * the clip names it accepts in order of preference, so a body plays the best
 * clip its file has; the character contract owns the names. Pure.
 */
import type { Activity } from "../life/planner";

export type Motion = Activity | "idle" | "walk" | "sit_down" | "stand_up" | "hover" | "follow" | "drive" | "salute";

const CANDIDATES: Readonly<Record<Motion, readonly string[]>> = {
  idle: ["A_Idle", "A_Stand_Idle"],
  walk: ["A_Walk"],
  sit_down: ["A_Sit_Down"],
  stand_up: ["A_Stand_Up"],
  sit_type: ["A_Sit_Type", "A_Sit_Idle"],
  sit_rest: ["A_Sit_Idle", "A_Sit_Listen"],
  listen: ["A_Sit_Listen", "A_Sit_Idle"],
  talk: ["A_Talk", "A_Idle"],
  // Waving for the commander's attention (the character contract's "waiting" clip).
  stand_wait: ["A_Wave", "A_Attention", "A_Idle"],
  stand_guard: ["A_Attention", "A_Idle"],
  salute: ["A_Salute"],
  stand_alert: ["A_Stand_Type", "A_Idle"],
  stand_rest: ["A_Idle", "A_Stand_Idle"],
  sleep: ["A_Sleep"],
  hover: ["A_Hover", "A_Idle"],
  follow: ["A_Follow", "A_Hover"],
  drive: ["A_Drive", "A_Walk"],
};

/** Activities played seated on a seat socket. */
export const SEATED: ReadonlySet<Motion> = new Set<Motion>(["sit_type", "sit_rest", "listen"]);

export function clipFor(motion: Motion, available: ReadonlySet<string>): string | null {
  for (const name of CANDIDATES[motion]) if (available.has(name)) return name;
  return null;
}
