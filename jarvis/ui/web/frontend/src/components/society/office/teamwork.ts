/**
 * Real teamwork, as the office shows it. Two things, and only these two,
 * because they are what the app can actually see:
 *
 * - **A team's round.** A team is a chat group with one shared meeting. While
 *   a round is answering, its free members stand at their studio board and the
 *   member contributing right now is the speaker. The round's state and
 *   transcript come from `GET /api/society/chat-groups/{id}/meeting`; that a
 *   round opened or settled, and each line said in it, also arrive on the
 *   socket (`SocietyRoomChanged`, `SocietyMessageSent` with a
 *   `meeting:<group>:…` room id).
 * - **A message from one agent to another.** `SocietyMessageSent` without a
 *   room, from one roster agent to another: a task handed over (ASSIGN) or a
 *   direct line (SAY, QUERY, ANSWER, PROPOSE). Its sender walks over to the
 *   receiver once it is free. The lead's own messages are Gigi's errands
 *   (gigiErrands.ts) and are left to it.
 *
 * Nothing here is invented: no line is shown that was not said, nobody
 * gathers without a running round, and a working agent is never moved except
 * the one member whose work IS the round's current contribution.
 *
 * The reducers are pure and tested; the store holds what the walkers, the
 * bubbles and the studio boards read.
 */
import { create } from "zustand";
import type { SocietyMeeting } from "@/lib/societyChatGroups";
import type { AgentRunState, SocietyAgent } from "../data";
import type { Bubble } from "./officeTalk";

/** One line of a team's transcript; `speaker` is an agent id, or "user" for the person. */
export interface RoundLine { id: string; speaker: string; text: string }

export interface TeamRound {
  teamId: string;
  /** A round is answering right now. */
  running: boolean;
  /** The member contributing at the moment (the room's next speaker while it runs), or null. */
  speakerId: string | null;
  /** Everyone taking part in the round (the room's members); empty until a round was seen. */
  members: string[];
  /** The newest lines of the transcript, oldest first. */
  lines: RoundLine[];
  /** The last line a member said while the office was watching, and when it was seen. */
  spoke: (RoundLine & { atMs: number }) | null;
  /** The transcript has been fetched at least once. */
  loaded: boolean;
  fetchedMs: number;
  /** The socket reported something this snapshot does not hold yet: fetch again soon. */
  dirty: boolean;
  /** The last read of the meeting failed: what is shown is what was known before, or nothing. */
  unavailable?: boolean;
}

/** Lines kept per team; a board shows the newest that fit. */
export const MAX_ROUND_LINES = 12;
/** How long a line stays over its speaker's head after it was said. */
export const SPOKE_LINGER_MS = 9000;

export function emptyRound(teamId: string): TeamRound {
  return { teamId, running: false, speakerId: null, members: [], lines: [], spoke: null, loaded: false, fetchedMs: 0, dirty: false };
}

/** The team (chat group) a room belongs to, from its id `meeting:<group id>:<suffix>`; null for any other room. */
export function meetingTeamId(roomId: unknown): string | null {
  if (typeof roomId !== "string" || !roomId.startsWith("meeting:")) return null;
  const rest = roomId.slice("meeting:".length);
  const cut = rest.lastIndexOf(":");
  const teamId = cut > 0 ? rest.slice(0, cut) : rest;
  return teamId.length > 0 ? teamId : null;
}

function idList(value: unknown): string[] | null {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string" && v.length > 0) : null;
}

function tail(lines: RoundLine[]): RoundLine[] {
  return lines.filter((l) => l.text.trim().length > 0).slice(-MAX_ROUND_LINES);
}

/**
 * Fold a fetched meeting into a team's round. A line that is new since the
 * last snapshot counts as just said; the first snapshot never does, so an old
 * transcript is not replayed as fresh speech when the office opens.
 */
export function applySnapshot(prev: TeamRound | undefined, teamId: string, snapshot: SocietyMeeting, now: number): TeamRound {
  const lines = tail(snapshot.messages.map((m) => ({ id: m.id, speaker: m.speaker, text: m.text })));
  const running = snapshot.running === true;
  const speakerId = running && snapshot.room?.state === "running" ? snapshot.room.next_speaker ?? null : null;
  let spoke = prev?.spoke ?? null;
  if (prev?.loaded) {
    const known = new Set(prev.lines.map((l) => l.id));
    const fresh = [...lines].reverse().find((l) => l.speaker !== "user" && !known.has(l.id));
    if (fresh && fresh.id !== spoke?.id) spoke = { ...fresh, atMs: now };
  }
  // The room lists its members on the wire; the declared type names only what the chat view reads.
  const members = idList((snapshot.room as { members?: unknown } | null)?.members) ?? prev?.members ?? [];
  return { teamId, running, speakerId, members, lines, spoke, loaded: true, fetchedMs: now, dirty: false, unavailable: false };
}

/** A round opened or settled (the socket's `SocietyRoomChanged`). */
export function applyRoomChange(prev: TeamRound | undefined, teamId: string, phase: unknown, members?: unknown): TeamRound {
  const round = prev ?? emptyRound(teamId);
  const listed = idList(members);
  if (phase === "open") return { ...round, running: true, dirty: true, members: listed && listed.length > 0 ? listed : round.members };
  if (phase === "settle") return { ...round, running: false, speakerId: null, dirty: true };
  return round;
}

/** A line said in a round (the socket's `SocietyMessageSent` with a meeting room id). */
export function applyRoomLine(prev: TeamRound | undefined, teamId: string, line: RoundLine, now: number): TeamRound {
  const round = prev ?? emptyRound(teamId);
  if (!line.text.trim() || round.lines.some((l) => l.id === line.id)) return { ...round, dirty: true };
  return {
    ...round, lines: tail([...round.lines, line]), dirty: true,
    spoke: line.speaker === "user" ? round.spoke : { ...line, atMs: now },
    // Whoever just spoke is no longer the one contributing; the next fetch names the next speaker.
    speakerId: round.speakerId === line.speaker ? null : round.speakerId,
  };
}

/**
 * An agent's part in its team's round:
 * - `gather`: free, so it stands at the studio board;
 * - `speaker`: it is contributing right now (its run state says "working", and that work is the round);
 * - `busy`: working on something else, or waiting for the person: it stays where its state puts it;
 * - `none`: no round, or the agent rests.
 */
export type RoundRole = "none" | "gather" | "speaker" | "busy";

export function roundRole(agent: { agentId: string; state: AgentRunState }, round: TeamRound | undefined): RoundRole {
  if (!round?.running || agent.state === "paused") return "none";
  if (round.speakerId === agent.agentId && agent.state !== "waiting") return "speaker";
  if (agent.state === "idle") return "gather";
  return "busy";
}

/**
 * The running round an agent takes part in: its home team's first, else any round that lists it as a member
 * (an agent can be in several teams and sits in only one studio).
 */
export function roundFor(rounds: Record<string, TeamRound>, agentId: string, homeTeamId: string | null): TeamRound | undefined {
  const home = homeTeamId ? rounds[homeTeamId] : undefined;
  if (home?.running) return home;
  for (const round of Object.values(rounds)) if (round.running && round.members.includes(agentId)) return round;
  return undefined;
}

/**
 * A member at the board keeps its place this long after its part reads
 * "busy". The roster and the meeting are polled on different clocks: the next
 * speaker's run state turns "working" a few seconds before the meeting names
 * it, and the last speaker's stays "working" a moment after its line. Without
 * the grace both would walk to their desk and straight back.
 */
export const ROLE_GRACE_MS = 7000;

export interface RoleMemory { role: RoundRole; busySinceMs: number | null }

/** The part an agent plays for the walkers: `raw`, held steady through the grace above. Mutates `memory`. */
export function steadyRole(memory: RoleMemory, raw: RoundRole, now: number): RoundRole {
  const atBoard = memory.role === "gather" || memory.role === "speaker";
  if (raw === "busy" && atBoard) {
    memory.busySinceMs ??= now;
    if (now - memory.busySinceMs < ROLE_GRACE_MS) return "gather";
  }
  memory.role = raw;
  memory.busySinceMs = null;
  return raw;
}

/** A message one agent sent another, waiting to be walked over. */
export interface Handoff {
  id: string;
  from: string;
  to: string;
  /** The receiver's name, for the sender's bubble. */
  toName: string;
  /** The board's bubble-sized preview of what was sent. */
  text: string;
  /** ASSIGN = a task handed over; anything else is a direct line. */
  msgType: string;
  /** When the office saw it. */
  atMs: number;
  /** `queued` until the sender is free and has walked over; `delivering` while it stands with the receiver. */
  phase: "queued" | "delivering";
  untilMs: number;
}

/** Board message types that count as one agent addressing another. */
const HANDOFF_TYPES = new Set(["ASSIGN", "SAY", "QUERY", "ANSWER", "PROPOSE"]);
/** A message whose sender has not got free within this time is no longer walked over. */
export const HANDOFF_FRESH_MS = 90_000;
/** How long the line stays over a sender that keeps working at its desk. */
export const HANDOFF_BUBBLE_MS = 9000;
/** Pending messages kept per sender; older ones give way. */
const MAX_PER_SENDER = 2;

/**
 * The hand-off a board event describes, or null. Both ends must be roster
 * agents other than the lead (the lead is the person's pet, not a desk mate;
 * its own messages are Gigi's errands), and a line said in a room is not one.
 */
export function handoffFrom(payload: unknown, agents: ReadonlyMap<string, Pick<SocietyAgent, "tier" | "name">>, now: number): Handoff | null {
  if (!payload || typeof payload !== "object") return null;
  const p = payload as Record<string, unknown>;
  const from = typeof p.from_agent === "string" ? p.from_agent : "";
  const to = typeof p.to_agent === "string" ? p.to_agent : "";
  const msgType = typeof p.msg_type === "string" ? p.msg_type : "";
  if (!HANDOFF_TYPES.has(msgType) || !from || !to || from === to || p.room_id) return null;
  const sender = agents.get(from), receiver = agents.get(to);
  if (!sender || !receiver || sender.tier === "lead" || receiver.tier === "lead") return null;
  const text = typeof p.text === "string" ? p.text.trim() : "";
  if (!text) return null;
  const id = typeof p.event_id === "string" && p.event_id ? p.event_id : `${from}>${to}:${now}`;
  return { id, from, to, toName: receiver.name, text, msgType, atMs: now, phase: "queued", untilMs: now + HANDOFF_FRESH_MS };
}

/** Add a hand-off: no duplicates, and at most two pending per sender (the newest stay). */
export function queueHandoff(list: readonly Handoff[], handoff: Handoff): Handoff[] {
  if (list.some((h) => h.id === handoff.id)) return list as Handoff[];
  const own = list.filter((h) => h.from === handoff.from);
  const drop = own.length >= MAX_PER_SENDER ? own.find((h) => h.phase === "queued")?.id : undefined;
  return [...list.filter((h) => h.id !== drop), handoff];
}

/** Drop hand-offs whose time has passed. Returns the same array when nothing changed. */
export function freshHandoffs(list: readonly Handoff[], now: number): Handoff[] {
  const kept = list.filter((h) => h.untilMs > now);
  return kept.length === list.length ? (list as Handoff[]) : kept;
}

interface TeamworkState {
  rounds: Record<string, TeamRound>;
  handoffs: Handoff[];
  setRound: (round: TeamRound) => void;
  /** Forget teams that no longer exist. */
  keepTeams: (teamIds: ReadonlySet<string>) => void;
  /** Mark every round as due for a fetch (the office woke up: what it knows may be stale). */
  markStale: () => void;
  addHandoff: (handoff: Handoff) => void;
  /** The sender reached the receiver: it stays for `forMs`. */
  deliverHandoff: (id: string, now: number, forMs: number) => void;
  finishHandoff: (id: string) => void;
  prune: (now: number) => void;
  reset: () => void;
}

export const useTeamwork = create<TeamworkState>((set) => ({
  rounds: {},
  handoffs: [],
  setRound: (round) => set((s) => (s.rounds[round.teamId] === round ? s : { rounds: { ...s.rounds, [round.teamId]: round } })),
  keepTeams: (teamIds) => set((s) => {
    const kept = Object.entries(s.rounds).filter(([id]) => teamIds.has(id));
    return kept.length === Object.keys(s.rounds).length ? s : { rounds: Object.fromEntries(kept) };
  }),
  markStale: () => set((s) => ({ rounds: Object.fromEntries(Object.entries(s.rounds).map(([id, r]) => [id, { ...r, dirty: true }])) })),
  addHandoff: (handoff) => set((s) => {
    const handoffs = queueHandoff(s.handoffs, handoff);
    return handoffs === s.handoffs ? s : { handoffs };
  }),
  deliverHandoff: (id, now, forMs) => set((s) => ({
    handoffs: s.handoffs.map((h) => (h.id === id && h.phase === "queued" ? { ...h, phase: "delivering", untilMs: now + forMs } : h)),
  })),
  finishHandoff: (id) => set((s) => (s.handoffs.some((h) => h.id === id) ? { handoffs: s.handoffs.filter((h) => h.id !== id) } : s)),
  prune: (now) => set((s) => {
    const handoffs = freshHandoffs(s.handoffs, now);
    return handoffs === s.handoffs ? s : { handoffs };
  }),
  reset: () => set({ rounds: {}, handoffs: [] }),
}));

/** The message `agentId` still has to walk over, oldest first; null when there is none. */
export function pendingHandoff(handoffs: readonly Handoff[], agentId: string, now: number): Handoff | null {
  return handoffs.find((h) => h.from === agentId && h.untilMs > now) ?? null;
}

/**
 * The newest line an agent said in any round the office watched, or null. A
 * line gives way the moment somebody else has the word in that round: only
 * one member of a team carries a bubble at a time.
 */
export function lastSpokeBy(rounds: Record<string, TeamRound>, agentId: string): (RoundLine & { atMs: number }) | null {
  let last: (RoundLine & { atMs: number }) | null = null;
  for (const round of Object.values(rounds)) {
    if (round.spoke?.speaker !== agentId) continue;
    if (round.running && round.speakerId !== null && round.speakerId !== agentId) continue;
    if (!last || round.spoke.atMs > last.atMs) last = round.spoke;
  }
  return last;
}

/** True while the agent is the one contributing to a running round. */
export function isSpeaking(rounds: Record<string, TeamRound>, agentId: string): boolean {
  for (const round of Object.values(rounds)) if (round.running && round.speakerId === agentId) return true;
  return false;
}

/**
 * What teamwork puts over an agent's head, most telling first: the message it
 * is delivering to a colleague, the line it just said in its team's round, a
 * thought while it is the round's speaker (its line is not written yet), and
 * a message it sent while it keeps working at its desk. Every text is the
 * real one; `thinking` and `to` ("To {0}: {1}") are the only labels.
 */
export function teamBubble(input: {
  spoke: (RoundLine & { atMs: number }) | null; speaking: boolean; handoff: Handoff | null; now: number;
  labels: { thinking: string; to: string };
  /** Shortens a line to bubble size (officeTalk's `bubbleText`). */
  short: (text: string, max: number) => string;
}): Bubble | null {
  const { spoke, speaking, handoff, now, labels, short } = input;
  const sent = handoff ? labels.to.replace("{0}", handoff.toName || "…").replace("{1}", short(handoff.text, 130)) : "";
  if (handoff?.phase === "delivering" && handoff.untilMs > now) return { kind: "speech", text: sent, live: false, atMs: handoff.atMs };
  if (spoke && now - spoke.atMs < SPOKE_LINGER_MS) return { kind: "speech", text: short(spoke.text, 170), live: false, atMs: spoke.atMs };
  if (speaking) return { kind: "thought", text: labels.thinking, live: true, atMs: 0 };
  if (handoff && now - handoff.atMs < HANDOFF_BUBBLE_MS) return { kind: "speech", text: sent, live: false, atMs: handoff.atMs };
  return null;
}

/**
 * Is anything of this agent's teamwork still on its way out of view: a line
 * it said that still lingers, or a message it sent that is still shown? The
 * bubble's clock ticks only that long; a line said an hour ago must not keep
 * a bubble re-rendering every second for the rest of the session.
 */
export function teamBubbleLive(spoke: { atMs: number } | null, handoff: Handoff | null, now: number): boolean {
  if (spoke && now - spoke.atMs < SPOKE_LINGER_MS) return true;
  if (!handoff) return false;
  return handoff.phase === "delivering" ? handoff.untilMs > now : now - handoff.atMs < HANDOFF_BUBBLE_MS;
}

const watchers = new Map<symbol, ReadonlySet<string>>();

/**
 * Teams whose board a camera is close to right now. Every mounted floor
 * writes its own set under its own key (two floors can be awake at once: the
 * Agents view and the IDE's side panel), and the poll reads the union: one
 * floor going to sleep or unmounting never blinds the other.
 */
export const boardWatch = {
  set(stage: symbol, near: ReadonlySet<string>): void { watchers.set(stage, near); },
  clear(stage: symbol): void { watchers.delete(stage); },
  near(): Set<string> {
    const all = new Set<string>();
    for (const set of watchers.values()) for (const id of set) all.add(id);
    return all;
  },
  /** Forget every floor (tests). */
  reset(): void { watchers.clear(); },
};
