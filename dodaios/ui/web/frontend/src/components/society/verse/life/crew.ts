/**
 * The crew as crew life sees it: who, which kind, and their duty status (the
 * rank system's reading of the real run state, ranks/dutyStatus.ts). Pure.
 */
import type { SocietyAgent } from "../../data";
import type { PaneOccupant } from "../../crewFeeds/codingFloor";
import { dutyOfPane, type DutyStatus } from "../ranks";

export type { DutyStatus };

export interface CrewMember {
  id: string;
  name: string;
  /** Officers are the agents (bridge consoles); technicians are coding panes (engineering terminals). */
  role: "officer" | "technician";
  status: DutyStatus;
  createdMs: number;
  /** The assistant's lead agent. */
  lead: boolean;
}

export function officerOf(agent: Pick<SocietyAgent, "agentId" | "name" | "createdMs" | "tier">, status: DutyStatus): CrewMember {
  return { id: agent.agentId, name: agent.name, role: "officer", status, createdMs: agent.createdMs, lead: agent.tier === "lead" };
}

export function technicianOf(occupant: Pick<PaneOccupant, "agent" | "dot" | "stateKey">): CrewMember {
  return {
    id: occupant.agent.agentId, name: occupant.agent.name, role: "technician",
    status: dutyOfPane(occupant.dot, occupant.stateKey), createdMs: occupant.agent.createdMs, lead: false,
  };
}

/** Lead first, then by arrival, then by id: the order consoles are handed out in. */
export function byServiceOrder(a: CrewMember, b: CrewMember): number {
  return Number(b.lead) - Number(a.lead) || a.createdMs - b.createdMs || a.id.localeCompare(b.id);
}

/** A stable 32-bit hash for seeded choices. */
export function hash32(text: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}
