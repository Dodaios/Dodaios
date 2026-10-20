/**
 * Duty status: what a crew member is doing right now, read from its real run
 * state, and how the Verse shows it.
 *
 * | Status    | Where the figure is             | Beacon                 |
 * |-----------|---------------------------------|------------------------|
 * | working   | seated at its console, typing   | steady green           |
 * | waiting   | stands, turns to the commander  | amber, slow pulse      |
 * | idle      | off duty: mess, corridor, views | none                   |
 * | paused    | in its bunk                     | none                   |
 * | error     | at its console, not typing      | red, slow pulse        |
 *
 * Inputs:
 * - a society agent's roster state (`AgentRunState`: the backend says
 *   `working`, `idle` or `paused`; sample rows may say `waiting`),
 * - live signals the roster does not carry: an open question to the person
 *   (`asking`), and a run that ended blocked (`error`, from the
 *   `SocietyResultPosted` push; see `useDutyBoard`),
 * - a coding pane's own reading (`AgentDotKind`: working / waiting / idle /
 *   error, plus `stopped` behind it).
 *
 * Precedence: paused (the person put it to rest) > waiting (it needs the
 * person now) > working > error (its last run failed and nothing newer has
 * happened) > idle. A working agent is never shown in error: the new run is
 * what counts.
 */
import type { AgentDotKind, AgentStateKey } from "@/components/agentic/sidePanel/agentStatus";
import type { AgentRunState } from "../../data";

export const DUTY_STATUSES = ["working", "waiting", "idle", "paused", "error"] as const;
export type DutyStatus = (typeof DUTY_STATUSES)[number];

/** Where the stage puts a figure of this status. */
export type DutyPlace = "console" | "stand" | "offduty" | "bunk";

export interface DutyStyle {
  /** Locale key of the status word (`verse.ranks.duty.<status>`). */
  labelKey: string;
  /** Beacon colour above the figure; null = no beacon. */
  beacon: string | null;
  /** The beacon blinks slowly (draws the eye without nagging). */
  pulse: boolean;
  place: DutyPlace;
  /** At the console, the screen is live. */
  screenLive: boolean;
  /** Higher = needs the commander sooner (summaries list these first). */
  attention: number;
}

/** Indicator colours, the ship's own lamps (style bible §5.1): status green, amber, signal red. */
export const BEACON = { green: "#4fb86a", amber: "#f2a33a", red: "#e3242b" } as const;

export const DUTY: Readonly<Record<DutyStatus, DutyStyle>> = {
  working: { labelKey: "verse.ranks.duty.working", beacon: BEACON.green, pulse: false, place: "console", screenLive: true, attention: 2 },
  waiting: { labelKey: "verse.ranks.duty.waiting", beacon: BEACON.amber, pulse: true, place: "stand", screenLive: true, attention: 4 },
  idle: { labelKey: "verse.ranks.duty.idle", beacon: null, pulse: false, place: "offduty", screenLive: false, attention: 1 },
  paused: { labelKey: "verse.ranks.duty.paused", beacon: null, pulse: false, place: "bunk", screenLive: false, attention: 0 },
  error: { labelKey: "verse.ranks.duty.error", beacon: BEACON.red, pulse: true, place: "console", screenLive: true, attention: 3 },
};

/** Summary order: what needs the commander first. */
export const DUTY_ORDER: readonly DutyStatus[] = [...DUTY_STATUSES].sort((a, b) => DUTY[b].attention - DUTY[a].attention);

export interface DutySignals {
  /** An open question or approval is waiting on the person. */
  asking?: boolean;
  /** The latest run ended blocked or failed. */
  error?: boolean;
}

export interface DutySubject {
  state: AgentRunState;
  /** The durable lifecycle behind `state`; a paused lifecycle is paused whatever the run says. */
  lifecycle?: "active" | "paused" | "archived";
}

/** A society agent's duty status. */
export function dutyOf(agent: DutySubject, signals: DutySignals = {}): DutyStatus {
  if (agent.state === "paused" || agent.lifecycle === "paused") return "paused";
  if (signals.asking || agent.state === "waiting") return "waiting";
  if (agent.state === "working") return "working";
  if (signals.error) return "error";
  return "idle";
}

/** A coding pane's duty status, from the IDE's own reading of it. */
export function dutyOfPane(dot: AgentDotKind, stateKey?: AgentStateKey): DutyStatus {
  if (stateKey === "stopped") return "paused";
  switch (dot) {
    case "working": return "working";
    case "waiting": return "waiting";
    case "error": return "error";
    default: return "idle";
  }
}

export function isDutyStatus(value: unknown): value is DutyStatus {
  return typeof value === "string" && (DUTY_STATUSES as readonly string[]).includes(value);
}

/** How many crew are in each status. */
export function dutyCounts(statuses: Iterable<DutyStatus>): Record<DutyStatus, number> {
  const counts: Record<DutyStatus, number> = { working: 0, waiting: 0, idle: 0, paused: 0, error: 0 };
  for (const status of statuses) counts[status] += 1;
  return counts;
}
