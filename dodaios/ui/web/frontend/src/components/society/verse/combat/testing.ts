/**
 * Helpers shared by the combat tests and the balance harness: a match that is
 * already live, players placed by hand, and a quick way to run ticks.
 */
import { idleControl, makeInput, type ControlState } from "./input";
import { yawOf } from "./math";
import { createContext, createMatch, step, type SimContext } from "./sim";
import { DEFAULT_TUNING, type CombatTuning } from "./tuning";
import type { CombatEvent, InputCommand, MatchConfig, MatchState } from "./types";

export function liveMatch(opts: { tuning?: CombatTuning; seed?: number; config?: Partial<MatchConfig> } = {}): { ctx: SimContext; state: MatchState } {
  const ctx = createContext(undefined, opts.tuning ?? DEFAULT_TUNING);
  let state = createMatch(ctx, { seed: opts.seed ?? 7, playerIds: ["a", "b"], config: opts.config });
  while (state.phase === "countdown") state = step(state, [null, null], ctx).state;
  return { ctx, state };
}

/** Put both players somewhere, facing each other unless told otherwise. */
export function place(state: MatchState, a: { x: number; z: number; yaw?: number }, b: { x: number; z: number; yaw?: number }): MatchState {
  const s: MatchState = JSON.parse(JSON.stringify(state));
  const [p, o] = s.players;
  p.x = a.x; p.z = a.z; p.vx = 0; p.vz = 0; p.yaw = a.yaw ?? yawOf(b.x - a.x, b.z - a.z);
  o.x = b.x; o.z = b.z; o.vx = 0; o.vz = 0; o.yaw = b.yaw ?? yawOf(a.x - b.x, a.z - b.z);
  s.history = { ticks: [], poses: [] };
  return s;
}

export interface Runner {
  state: MatchState;
  events: CombatEvent[];
  seq: number[];
  /** Run `n` ticks with these controls (functions are called every tick). */
  run(n: number, a?: Partial<ControlState> | ((s: MatchState) => Partial<ControlState>), b?: Partial<ControlState> | ((s: MatchState) => Partial<ControlState>)): CombatEvent[];
}

export function runner(ctx: SimContext, state: MatchState): Runner {
  const r: Runner = {
    state,
    events: [],
    seq: [0, 0],
    run(n, a, b) {
      const out: CombatEvent[] = [];
      for (let i = 0; i < n; i++) {
        const cmds: InputCommand[] = [a, b].map((c, slot) => {
          const p = r.state.players[slot];
          const partial = typeof c === "function" ? c(r.state) : c ?? {};
          return makeInput(r.seq[slot]++, { ...idleControl(p.yaw, p.pitch), ...partial });
        });
        const res = step(r.state, cmds, ctx);
        r.state = res.state;
        out.push(...res.events);
      }
      r.events.push(...out);
      return out;
    },
  };
  return r;
}

export function count(events: readonly CombatEvent[], type: CombatEvent["type"], player?: number): number {
  return events.filter((e) => e.type === type && (player === undefined || ("player" in e && e.player === player))).length;
}
