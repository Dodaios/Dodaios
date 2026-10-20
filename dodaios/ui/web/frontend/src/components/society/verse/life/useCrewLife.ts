/**
 * The live crew of the ship and where crew life puts them on the deck on
 * screen: the society roster (officers) and the IDE's coding panes
 * (technicians), their duty status (the rank system's board), their part in
 * running team rounds, their rank looks, and the planner's placements, kept
 * stable across refreshes. Only reads existing feeds; adds no poll of its own
 * beyond re-planning when an off-duty routine moves on.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { chatGroupsKnown, useSocietyChatGroups } from "@/lib/societyChatGroups";
import { useSocietyRoster, type SocietyAgent } from "../../data";
import { useCodingFloorOccupants, type PaneOccupant } from "../../crewFeeds/codingFloor";
import { useTeamRounds } from "../../crewFeeds/useTeamRounds";
import { roundFor, roundRole, steadyRole, useTeamwork, type RoleMemory } from "../../crewFeeds/teamwork";
import { useProgression } from "../../progression/progressionStore";
import { agentSubject } from "../../progression/progressionApi";
import { useDutyBoard, type DutyStatus } from "../ranks";
import type { Deck } from "../content/deck";
import type { DeckId } from "../decks";
import { lookForLevel, type Look } from "../actors/look";
import { officerOf, technicianOf, type CrewMember } from "./crew";
import { useDevDuty } from "./devOverrides";
import { IDLE_SLOT_MS, placeOnDeck, socketKey, type Placement, type RoundPart } from "./planner";

/** How often off-duty routines are re-read (each member moves on its own clock within its slot). */
const REPLAN_MS = 20_000;
/** A new agent counts as arriving for this long (it walks in from the shuttle). */
const ARRIVAL_MS = 40_000;
const ROSTER_REFRESH_MS = 5000;

export interface CrewLife {
  ready: boolean;
  agents: ReadonlyMap<string, SocietyAgent>;
  panes: ReadonlyMap<string, PaneOccupant>;
  crew: ReadonlyMap<string, CrewMember>;
  statuses: ReadonlyMap<string, DutyStatus>;
  placements: ReadonlyMap<string, Placement>;
  /** Home console (seat id = screen id) by member, for the deck on screen. */
  homes: ReadonlyMap<string, string>;
  looks: ReadonlyMap<string, Look>;
  levels: ReadonlyMap<string, number>;
  /** Members that were on this deck when it opened (they stand in place, they do not arrive). */
  aboard: ReadonlySet<string>;
  arriving: ReadonlySet<string>;
  /** Team id → its running round's speaker (null while nobody speaks). */
  rounds: ReadonlyMap<string, string | null>;
  teams: readonly { id: string; name: string; members: readonly string[] }[];
}

function useRosterRefresh(awake: boolean): void {
  const client = useQueryClient();
  useEffect(() => {
    if (!awake) return;
    let timer: ReturnType<typeof setTimeout>;
    const tick = () => {
      timer = setTimeout(() => { void client.invalidateQueries({ queryKey: ["society", "roster"] }); tick(); }, ROSTER_REFRESH_MS + Math.random() * 1500);
    };
    tick();
    return () => clearTimeout(timer);
  }, [awake, client]);
}

export function useCrewLife(deck: Deck | null, deckId: DeckId, awake: boolean, messCall: boolean): CrewLife {
  const roster = useSocietyRoster(awake);
  useRosterRefresh(awake);
  const groups = useSocietyChatGroups(awake);
  const coding = useCodingFloorOccupants(awake && deckId === "engineering");
  const subjects = useProgression((s) => s.subjects);

  const agentList = useMemo(() => (roster.data?.agents ?? []).filter((a) => a.lifecycle !== "archived"), [roster.data]);
  const agents = useMemo(() => new Map(agentList.map((a) => [a.agentId, a])), [agentList]);
  const panes = useMemo(() => new Map(coding.occupants.map((o) => [o.agent.agentId, o])), [coding.occupants]);
  const dutyMembers = useMemo(() => agentList.map((a) => ({ agentId: a.agentId, state: a.state, lifecycle: a.lifecycle })), [agentList]);
  const board = useDutyBoard(dutyMembers);

  const teams = useMemo(() => (groups.data ?? []).map((g) => ({ id: g.group_id, name: g.name, members: g.members })), [groups.data]);
  const watch = useMemo(() => teams.map((t) => ({ teamId: t.id, members: t.members })), [teams]);
  useTeamRounds(watch, agents, awake && deckId === "bridge");
  const rawRounds = useTeamwork((s) => s.rounds);

  const devDuty = useDevDuty((s) => s.duty);
  const crew = useMemo(() => {
    const out = new Map<string, CrewMember>();
    for (const a of agentList) out.set(a.agentId, officerOf(a, board.get(a.agentId) ?? "idle"));
    for (const o of coding.occupants) out.set(o.agent.agentId, technicianOf(o));
    if (import.meta.env.DEV) for (const [id, status] of Object.entries(devDuty)) { const m = out.get(id); if (m) out.set(id, { ...m, status }); }
    return out;
  }, [agentList, board, coding.occupants, devDuty]);

  const statuses = useMemo(() => new Map([...crew].map(([id, m]) => [id, m.status])), [crew]);

  const levels = useMemo(() => new Map([...crew.keys()].map((id) => [id, subjects[agentSubject(id)]?.level ?? 1])), [crew, subjects]);
  const looks = useMemo(() => {
    const out = new Map<string, Look>();
    for (const [id, member] of crew) {
      const accent = (member.role === "technician" ? panes.get(id)?.agent.palette.accent : agents.get(id)?.palette.accent) ?? null;
      const look = lookForLevel(levels.get(id) ?? 1, accent);
      // Technicians wear the deck's work uniform whatever their record.
      out.set(id, member.role === "technician" ? { ...look, tier: "deck" } : look);
    }
    return out;
  }, [crew, levels, agents, panes]);

  // Parts in running rounds, held steady through the roster's and the meeting's different clocks.
  const memory = useRef(new Map<string, RoleMemory>());
  const homeTeam = useMemo(() => {
    const m = new Map<string, string>();
    for (const t of teams) for (const id of t.members) if (!m.has(id)) m.set(id, t.id);
    return m;
  }, [teams]);
  const roundParts = useMemo(() => {
    const parts = new Map<string, RoundPart>();
    const now = Date.now();
    for (const a of agentList) {
      const round = roundFor(rawRounds, a.agentId, homeTeam.get(a.agentId) ?? null);
      const mem = memory.current.get(a.agentId) ?? { role: "none", busySinceMs: null };
      memory.current.set(a.agentId, mem);
      const role = steadyRole(mem, roundRole(a, round), now);
      if (role === "speaker") parts.set(a.agentId, "speaker");
      else if (role === "gather") parts.set(a.agentId, "listener");
    }
    return parts;
  }, [agentList, rawRounds, homeTeam]);
  const rounds = useMemo(() => {
    const m = new Map<string, string | null>();
    for (const [id, r] of Object.entries(rawRounds)) if (r.running) m.set(id, r.speakerId);
    return m;
  }, [rawRounds]);

  // Off-duty routines move on with time.
  const [clock, setClock] = useState(() => Date.now());
  useEffect(() => {
    if (!awake) return;
    const timer = setInterval(() => setClock(Date.now()), REPLAN_MS);
    return () => clearInterval(timer);
  }, [awake]);
  const slot = Math.floor(clock / (IDLE_SLOT_MS / 12));

  const previous = useRef(new Map<string, string>());
  /** Home consoles by deck, so riding the lift and back changes nobody's console. */
  const lastHomes = useRef(new Map<DeckId, Map<string, string>>());
  const plan = useMemo(() => {
    if (!deck) return { placements: new Map<string, Placement>(), homes: new Map<string, string>() };
    const next = placeOnDeck({ deck, crew: [...crew.values()], rounds: roundParts, nowMs: clock, previous: previous.current, homes: lastHomes.current.get(deck.id), messCall });
    previous.current = new Map([...next.placements].map(([id, p]) => [id, socketKey(p.socket)]));
    lastHomes.current.set(deck.id, next.homes);
    return next;
    // `slot` stands in for the clock: re-plan when a routine slot can have changed.
  }, [deck, crew, roundParts, slot, messCall]);

  const placements = plan.placements;
  const homes = plan.homes;
  const ready = !!roster.data && chatGroupsKnown(groups) && (deckId !== "engineering" || coding.loaded);

  // Who was here when the deck opened, and who joined the ship while it was open.
  const [aboard, setAboard] = useState<ReadonlySet<string>>(new Set());
  const aboardFor = useRef<Deck | null>(null);
  useEffect(() => {
    if (!deck || !ready || aboardFor.current === deck) return;
    aboardFor.current = deck;
    setAboard(new Set(placements.keys()));
  }, [deck, ready, placements]);

  const known = useRef<Set<string> | null>(null);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const [arriving, setArriving] = useState<ReadonlySet<string>>(new Set());
  useEffect(() => {
    if (!roster.data) return;
    const ids = agentList.map((a) => a.agentId);
    if (!known.current) { known.current = new Set(ids); return; }
    const fresh = ids.filter((id) => !known.current?.has(id));
    for (const id of ids) known.current.add(id);
    if (fresh.length === 0) return;
    setArriving((prev) => new Set([...prev, ...fresh]));
    // Not cleared by the next roster refresh: only by unmounting.
    timers.current.push(setTimeout(() => setArriving((prev) => new Set([...prev].filter((id) => !fresh.includes(id)))), ARRIVAL_MS));
  }, [agentList, roster.data]);
  useEffect(() => () => { for (const timer of timers.current) clearTimeout(timer); }, []);

  return { ready, agents, panes, crew, statuses, placements, homes, looks, levels, aboard, arriving, rounds, teams };
}
