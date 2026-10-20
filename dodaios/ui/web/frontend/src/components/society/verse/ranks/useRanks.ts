/**
 * Hooks the stage uses to dress its figures: a subject's rank (derived from
 * its level with the Verse's own ladder), the commander's uniform (the
 * quartermaster's choice, or the highest issued) and the crew's duty status
 * (roster state plus the live signals the roster does not carry).
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useEventStore } from "@/store/events";
import { uniformFor } from "../../progression/cosmetics";
import { PERSON_SUBJECT, rewardsOf } from "../../progression/progressionApi";
import { useProgression } from "../../progression/progressionStore";
import type { AgentRunState } from "../../data";
import { dutyOf, type DutyStatus } from "./dutyStatus";
import { rankView, type RankView } from "./rankModel";
import type { UniformId } from "./ranks";

/** The rank view of `subjectId` (`person`, `agent:<id>`, `pet:<id>`); a new recruit until the server says more. */
export function useSubjectRank(subjectId: string): RankView {
  const subject = useProgression((s) => s.subjects[subjectId]);
  const levelXp = useProgression((s) => s.snapshot?.levelXp);
  return useMemo(() => rankView(subject, levelXp), [subject, levelXp]);
}

/** The commander's rank view. */
export function useCommanderRank(): RankView {
  return useSubjectRank(PERSON_SUBJECT);
}

/** The uniform the commander's figure wears. */
export function useCommanderUniform(): UniformId {
  const level = useProgression((s) => s.subjects[PERSON_SUBJECT]?.level ?? 1);
  const choice = useProgression((s) => s.uniform);
  const snapshot = useProgression((s) => s.snapshot);
  return useMemo(() => uniformFor(rewardsOf(snapshot), level, choice), [snapshot, level, choice]);
}

// ------------------------------------------------------------ duty signals

export interface DutySignalState {
  /** Agents whose latest result came back blocked. */
  errors: ReadonlySet<string>;
  /** Agents with an open question to the person. */
  asking: ReadonlySet<string>;
}

export const NO_SIGNALS: DutySignalState = { errors: new Set(), asking: new Set() };

interface BusEvent { name: string; payload?: unknown }

const PERSON_IDS = new Set(["user", "person", ""]);

function field(payload: unknown, key: string): string {
  const value = payload && typeof payload === "object" ? (payload as Record<string, unknown>)[key] : undefined;
  return typeof value === "string" ? value : "";
}

function without(set: ReadonlySet<string>, id: string): ReadonlySet<string> {
  if (!set.has(id)) return set;
  const next = new Set(set);
  next.delete(id);
  return next;
}

function adding(set: ReadonlySet<string>, id: string): ReadonlySet<string> {
  if (set.has(id)) return set;
  return new Set(set).add(id);
}

/**
 * One bus event's effect on the live signals.
 *
 * - `SocietyResultPosted`: `blocked` marks the agent in error, `done` clears
 *   it; either way the agent is no longer asking.
 * - `SocietyMessageSent`: a QUERY from an agent to the person marks it asking;
 *   anything the person sends to it answers.
 */
export function applyDutyEvent(state: DutySignalState, event: BusEvent): DutySignalState {
  if (event.name === "SocietyResultPosted") {
    const agent = field(event.payload, "agent_id");
    if (!agent) return state;
    const status = field(event.payload, "status");
    const errors = status === "blocked" ? adding(state.errors, agent) : without(state.errors, agent);
    const asking = without(state.asking, agent);
    return errors === state.errors && asking === state.asking ? state : { errors, asking };
  }
  if (event.name === "SocietyMessageSent") {
    const from = field(event.payload, "from_agent");
    const to = field(event.payload, "to_agent");
    const kind = field(event.payload, "msg_type");
    if (kind === "QUERY" && from && !PERSON_IDS.has(from) && PERSON_IDS.has(to) && !field(event.payload, "room_id")) {
      const asking = adding(state.asking, from);
      return asking === state.asking ? state : { ...state, asking };
    }
    if (PERSON_IDS.has(from) && to && !PERSON_IDS.has(to)) {
      const asking = without(state.asking, to);
      return asking === state.asking ? state : { ...state, asking };
    }
  }
  return state;
}

export interface DutyMember {
  agentId: string;
  state: AgentRunState;
  lifecycle?: "active" | "paused" | "archived";
}

/**
 * Every crew member's duty status, live. Reads the roster states the caller
 * passes and follows the bus for blocked results and open questions; an
 * agent that starts working again drops its old error.
 */
export function useDutyBoard(members: readonly DutyMember[]): ReadonlyMap<string, DutyStatus> {
  const [signals, setSignals] = useState<DutySignalState>(() => {
    // The store keeps the newest event first: replay oldest to newest.
    const events = [...useEventStore.getState().events].reverse();
    return events.reduce<DutySignalState>((state, event) => applyDutyEvent(state, event), NO_SIGNALS);
  });

  useEffect(() => {
    let lastId: string | null = useEventStore.getState().events[0]?.id ?? null;
    return useEventStore.subscribe((state) => {
      const fresh: BusEvent[] = [];
      for (const event of state.events) {
        if (event.id === lastId) break;
        fresh.push(event);
      }
      lastId = state.events[0]?.id ?? lastId;
      if (fresh.length === 0) return;
      setSignals((current) => fresh.reverse().reduce<DutySignalState>((s, event) => applyDutyEvent(s, event), current));
    });
  }, []);

  // A new run supersedes the old failure.
  const working = members.filter((m) => m.state === "working").map((m) => m.agentId).join(",");
  const seenWorking = useRef<string>("");
  useEffect(() => {
    if (working === seenWorking.current) return;
    seenWorking.current = working;
    if (!working) return;
    const ids = working.split(",");
    setSignals((current) => {
      let errors = current.errors;
      for (const id of ids) errors = without(errors, id);
      return errors === current.errors ? current : { ...current, errors };
    });
  }, [working]);

  return useMemo(() => {
    const board = new Map<string, DutyStatus>();
    for (const member of members) {
      board.set(member.agentId, dutyOf(member, { error: signals.errors.has(member.agentId), asking: signals.asking.has(member.agentId) }));
    }
    return board;
  }, [members, signals]);
}
