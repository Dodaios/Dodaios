/**
 * Headless duels for tests and balance: two controllers (bots or scripted
 * strategies) observe the authoritative state through `observe` (the same
 * perception a player has) and answer with controls, turned into
 * InputCommands exactly as for a human. No network; see netcode tests for
 * the same duel over a transport.
 */
import { makeInput, type ControlState } from "../input";
import { observe, type Observation } from "../observe";
import { createMatch, step, type SimContext } from "../sim";
import type { CombatEvent, EndReason, MatchConfig, PlayerStats } from "../types";

export interface Controller {
  readonly label: string;
  think(obs: Observation): ControlState;
}

export type ControllerFactory = (slot: number, seed: number, ctx: SimContext) => Controller;

export interface RoundRecord {
  round: number;
  winner: number;
  reason: "kill" | "time" | "trade";
  ticks: number;
  /** Side (spawn) each slot had. */
  sides: number[];
}

export interface DuelResult {
  seed: number;
  labels: string[];
  winner: number;
  reason: EndReason;
  scores: number[];
  ticks: number;
  rounds: RoundRecord[];
  stats: PlayerStats[];
  /** Ticks from the first hit on a full-health player to their death. */
  ttk: number[];
  /** Bolts that reached each player (blocks, parries, deflects, hits). */
  incoming: number[];
  events?: CombatEvent[];
}

export interface DuelOptions {
  ctx: SimContext;
  seed: number;
  players: readonly [ControllerFactory, ControllerFactory];
  config?: Partial<MatchConfig>;
  /** Safety cap (ticks). */
  maxTicks?: number;
  keepEvents?: boolean;
}

export function runDuel(o: DuelOptions): DuelResult {
  const { ctx, seed } = o;
  const ctrls = o.players.map((f, slot) => f(slot, seed * 2 + slot + 1, ctx));
  let state = createMatch(ctx, { seed, playerIds: ctrls.map((c, i) => `${c.label}#${i}`), config: o.config });
  const seq = [0, 0];
  let prev: readonly CombatEvent[] = [];
  const rounds: RoundRecord[] = [];
  const ttk: number[] = [];
  const engaged = [-1, -1];
  const incoming = [0, 0];
  const all: CombatEvent[] = [];
  let roundStart = 0;
  const max = o.maxTicks ?? 60 * 60 * 12;
  while (state.phase !== "ended" && state.tick < max) {
    const view = { ...state, events: prev };
    const cmds = [0, 1].map((slot) => makeInput(seq[slot]++, ctrls[slot].think(observe(view, slot, ctx.arena, ctx.tuning))));
    const res = step(state, cmds, ctx);
    for (const e of res.events) {
      if (e.type === "round_start") { roundStart = e.tick; engaged[0] = engaged[1] = -1; }
      else if (e.type === "hit" && engaged[e.target] < 0) engaged[e.target] = e.tick;
      else if (e.type === "death" && engaged[e.player] >= 0) ttk.push(e.tick - engaged[e.player]);
      else if (e.type === "round_end") rounds.push({ round: e.round, winner: e.winner, reason: e.reason, ticks: e.tick - roundStart, sides: state.players.map((p) => p.side) });
      if (e.type === "hit") incoming[e.target]++;
      else if (e.type === "block" || e.type === "parry" || e.type === "deflect") incoming[e.player]++;
    }
    state = res.state;
    for (const p of state.players) if (p.health >= ctx.tuning.health.max) engaged[p.slot] = -1;
    if (o.keepEvents) all.push(...res.events);
    prev = res.events;
  }
  return {
    seed,
    labels: ctrls.map((c) => c.label),
    winner: state.winner ?? -1,
    reason: state.endReason ?? "cancelled",
    scores: state.scores.slice(),
    ticks: state.tick,
    rounds,
    stats: state.players.map((p) => ({ ...p.stats })),
    ttk,
    incoming,
    events: o.keepEvents ? all : undefined,
  };
}
