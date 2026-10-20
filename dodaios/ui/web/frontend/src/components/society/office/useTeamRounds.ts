/**
 * Keeps the office's picture of team rounds and agent-to-agent messages
 * current (see teamwork.ts for what that picture is).
 *
 * The socket pushes the moments (a round opened or settled, a line was said,
 * one agent addressed another), but the office never depends on it: a round
 * that was already running when the office opened, or whose event was missed,
 * is found by reading. Reads of a team's meeting are scheduled here: every
 * team once after the stage wakes and again about once a minute (the sweep),
 * a running round every few seconds for who speaks next, and a team whose
 * board the camera is close to now and then for its transcript. Jittered so
 * windows never read in lockstep (AP-33), capped per tick, and silent while
 * the stage is asleep. The ticks do not wait for the reads: each read is
 * folded in when its answer comes, has a timeout, and is aborted when the
 * poller stops, so a request hanging on a half-open socket costs one of a
 * tick's places for a few seconds and nothing else. A failed read keeps what
 * is known; it is logged, not shown.
 *
 * The store is one for the whole app, so there is one poller: when two
 * floors are awake at once (the Agents view and the IDE's side panel), the
 * first holds the lease and the other takes over when it sleeps or unmounts.
 */
import { useEffect, useRef, useState } from "react";
import { fetchSocietyMeeting } from "@/lib/societyChatGroups";
import { useEventStore } from "@/store/events";
import type { SocietyAgent } from "../data";
import type { Studio } from "./officeLayout";
import { withReadSignal } from "./pollSignal";
import {
  applyRoomChange, applyRoomLine, applySnapshot, boardWatch, emptyRound, handoffFrom, meetingTeamId, useTeamwork, type TeamRound,
} from "./teamwork";

/** Time between two scheduling ticks, plus up to JITTER_MS. */
export const ROUND_POLL_MS = 2400;
const JITTER_MS = 1200;
/** A board near the camera refreshes its transcript this often while no round runs. */
export const BOARD_REFRESH_MS = 18_000;
/** A team whose member the roster shows in a room, without a known round, is checked this often. */
const SUSPECT_REFRESH_MS = 6000;
/** Every team is read again after about this long, wherever the camera is: the sweep that finds a round nobody announced. */
export const SWEEP_MS = 60_000;
/** The sweep's share of a tick, so it never crowds out the rounds that are running. */
export const SWEEP_READS_PER_TICK = 2;
/** Never more meeting reads per tick than this, however many teams there are. */
export const MAX_READS_PER_TICK = 4;
/** A running round that could not be read this many times in a row is no longer shown as running. */
export const MAX_FAILED_READS = 5;
/** Newest socket events inspected per update, the same bound as the errand feed. */
const MAX_CATCHUP = 64;

export interface DueInput {
  teamIds: readonly string[];
  rounds: Record<string, TeamRound>;
  /** Teams whose board is near the camera. */
  near: ReadonlySet<string>;
  /** Teams with a member the roster shows in a running room. */
  inRoom: ReadonlySet<string>;
  now: number;
  /** After how long a team is swept again; the caller jitters it. Default SWEEP_MS. */
  sweepMs?: number;
  /** Teams whose meeting is being read right now: not asked again, and counted against the cap. */
  inFlight?: ReadonlySet<string>;
}

/**
 * Which teams' meetings to read on this tick: running and freshly changed
 * rounds first (longest unread first), then teams the roster suggests are in
 * a round, then boards near the camera whose transcript has aged, then the
 * sweep: teams never read since the office opened, and teams not read for
 * about a minute. The sweep takes at most two reads of a tick, so a campus of
 * twelve teams is known within a few ticks and costs twelve reads a minute
 * while nothing happens. Pure.
 */
export function dueTeams({ teamIds: allTeams, rounds, near, inRoom, now, sweepMs = SWEEP_MS, inFlight }: DueInput, limit = MAX_READS_PER_TICK): string[] {
  const teamIds = inFlight && inFlight.size > 0 ? allTeams.filter((id) => !inFlight.has(id)) : allTeams;
  const cap = Math.max(0, limit - (inFlight?.size ?? 0));
  if (cap === 0) return [];
  const age = (id: string) => now - (rounds[id]?.fetchedMs ?? 0);
  const oldestFirst = (a: string, b: string) => age(b) - age(a) || a.localeCompare(b);
  const live = teamIds.filter((id) => rounds[id]?.running || rounds[id]?.dirty).sort(oldestFirst);
  const taken = new Set(live);
  const suspected = teamIds.filter((id) => !taken.has(id) && inRoom.has(id) && age(id) >= SUSPECT_REFRESH_MS).sort(oldestFirst);
  for (const id of suspected) taken.add(id);
  const boards = teamIds.filter((id) => !taken.has(id) && near.has(id) && age(id) >= BOARD_REFRESH_MS).sort(oldestFirst);
  for (const id of boards) taken.add(id);
  const sweep = teamIds.filter((id) => !taken.has(id) && age(id) >= sweepMs).sort(oldestFirst).slice(0, SWEEP_READS_PER_TICK);
  // The sweep's two places are kept even on a tick full of running rounds, or a busy campus would never look further.
  const first = [...live, ...suspected, ...boards];
  return [...first.slice(0, Math.max(0, cap - sweep.length)), ...sweep].slice(0, cap);
}

/**
 * A team's round after a read of its meeting failed for the `misses`-th time
 * in a row. The read counts as done, so one failing team cannot take every
 * tick's places. A round nobody can read any more is not shown as running,
 * or its members would stand at the board for ever; a team that has never
 * been read is marked unavailable, so its board can say so instead of
 * "reading" for ever. Pure.
 */
export function afterFailedRead(prev: TeamRound | undefined, teamId: string, misses: number, now: number): TeamRound {
  const round = prev ?? emptyRound(teamId);
  const lost = round.running && misses >= MAX_FAILED_READS;
  return { ...round, fetchedMs: now, dirty: false, unavailable: true, ...(lost ? { running: false, speakerId: null } : {}) };
}

/** The one poller of the app-wide teamwork store: who holds it, and who waits for it. */
const lease: { owner: symbol | null; waiting: Set<() => void> } = { owner: null, waiting: new Set() };

/** True while this caller is the one poller. Others wait and take over when the holder lets go. */
function usePollerLease(wanted: boolean): boolean {
  const [holds, setHolds] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (!wanted) return;
    const id = Symbol("team-rounds-poller");
    if (lease.owner !== null) {
      const again = () => setRetry((n) => n + 1);
      lease.waiting.add(again);
      return () => { lease.waiting.delete(again); };
    }
    lease.owner = id;
    setHolds(true);
    return () => {
      setHolds(false);
      if (lease.owner === id) lease.owner = null;
      for (const wake of [...lease.waiting]) wake();
    };
  }, [wanted, retry]);
  return wanted && holds;
}

/**
 * Feed the teamwork store while `awake`. `studios` are the floor's studios
 * (a team = a studio with a team id); `agents` is the roster.
 */
export function useTeamRounds(studios: readonly Studio[], agents: ReadonlyMap<string, SocietyAgent>, awake: boolean): void {
  const roster = useRef(agents);
  roster.current = agents;
  const teams = useRef(studios);
  teams.current = studios;
  const teamKey = studios.map((s) => s.teamId ?? "").filter(Boolean).join(",");
  const polls = usePollerLease(awake);

  // Teams that no longer exist take their rounds with them.
  useEffect(() => {
    if (!polls) return;
    useTeamwork.getState().keepTeams(new Set(teamKey ? teamKey.split(",") : []));
  }, [teamKey, polls]);

  // The moments, pushed: rounds opening and settling, lines said in them, and messages between two agents.
  useEffect(() => {
    if (!polls) return;
    let cursor: string | null = useEventStore.getState().events[0]?.id ?? null;
    return useEventStore.subscribe((state) => {
      const log = state.events;
      const top = log[0];
      if (!top || top.id === cursor) return;
      const fresh = [];
      for (let i = 0; i < log.length && i < MAX_CATCHUP; i += 1) {
        if (log[i].id === cursor) break;
        fresh.push(log[i]);
      }
      cursor = top.id;
      const now = Date.now();
      const store = useTeamwork.getState();
      const known = new Set(teams.current.map((s) => s.teamId).filter((id): id is string => id !== null));
      for (let i = fresh.length - 1; i >= 0; i -= 1) {
        const { name, payload } = fresh[i];
        if (name !== "SocietyMessageSent" && name !== "SocietyRoomChanged") continue;
        const p = (payload ?? {}) as Record<string, unknown>;
        const teamId = meetingTeamId(p.room_id);
        if (name === "SocietyRoomChanged") {
          if (teamId && known.has(teamId)) store.setRound(applyRoomChange(useTeamwork.getState().rounds[teamId], teamId, p.phase, p.members));
          continue;
        }
        if (teamId) {
          if (!known.has(teamId) || p.msg_type !== "SAY") continue;
          const id = typeof p.event_id === "string" ? p.event_id : "";
          const speaker = typeof p.from_agent === "string" ? p.from_agent : "";
          const text = typeof p.text === "string" ? p.text : "";
          if (id && speaker) store.setRound(applyRoomLine(useTeamwork.getState().rounds[teamId], teamId, { id, speaker, text }, now));
          continue;
        }
        const handoff = handoffFrom(p, roster.current, now);
        if (handoff) store.addHandoff(handoff);
      }
    });
  }, [polls]);

  // The reads, scheduled: jittered, capped, and only while the stage is awake. The loop also runs on a floor
  // without teams, where it only clears out messages whose time has passed.
  useEffect(() => {
    if (!polls) return;
    const stop = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const failed = new Map<string, number>();
    const inFlight = new Set<string>();
    // What the office knew before it slept may be stale.
    useTeamwork.getState().markStale();
    const read = async (teamId: string) => {
      inFlight.add(teamId);
      try {
        const snapshot = await withReadSignal(stop.signal, (signal) => fetchSocietyMeeting(teamId, signal));
        if (stop.signal.aborted) return;
        failed.delete(teamId);
        useTeamwork.getState().setRound(applySnapshot(useTeamwork.getState().rounds[teamId], teamId, snapshot, Date.now()));
      } catch (error) {
        if (stop.signal.aborted) return;
        // The board keeps its last good transcript; the team's own chat view reports real failures.
        console.debug("Team round read failed", teamId, error);
        const misses = (failed.get(teamId) ?? 0) + 1;
        failed.set(teamId, misses);
        useTeamwork.getState().setRound(afterFailedRead(useTeamwork.getState().rounds[teamId], teamId, misses, Date.now()));
      } finally {
        inFlight.delete(teamId);
      }
    };
    const tick = () => {
      const now = Date.now();
      useTeamwork.getState().prune(now);
      const teamIds = teams.current.map((s) => s.teamId).filter((id): id is string => id !== null);
      for (const id of [...failed.keys()]) if (!teamIds.includes(id)) failed.delete(id);
      const inRoom = new Set<string>();
      for (const studio of teams.current) {
        if (studio.teamId && studio.members.some((id) => roster.current.get(id)?.checkpoint === "meeting")) inRoom.add(studio.teamId);
      }
      // The sweep's period is jittered per tick, so two windows never sweep in step.
      const due = dueTeams({
        teamIds, rounds: useTeamwork.getState().rounds, near: boardWatch.near(), inRoom, now, inFlight,
        sweepMs: SWEEP_MS * (0.9 + Math.random() * 0.25),
      });
      for (const teamId of due) void read(teamId);
      // The next tick does not wait for these reads: one that hangs holds nothing back.
      timer = setTimeout(tick, ROUND_POLL_MS + Math.random() * JITTER_MS);
    };
    timer = setTimeout(tick, Math.random() * JITTER_MS);
    return () => { stop.abort(); clearTimeout(timer); };
  }, [polls, teamKey]);
}
