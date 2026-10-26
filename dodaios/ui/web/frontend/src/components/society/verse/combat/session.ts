/**
 * A duel against the bot, in-process: the one object the 3D view needs.
 *
 *   const duel = createLocalDuel({ difficulty: "hard" });
 *   // every animation frame:
 *   const { view, events } = duel.frame(dtMs, controlsFromKeysAndMouse);
 *   // view: players, bolts, HUD, match clock; events: shots, hits, parries...
 *   duel.forfeit();   // leave at any time
 *
 * Inside it is exactly the multiplayer shape: an authoritative MatchServer,
 * a LocalNetwork, a MatchClient for the person (prediction and
 * reconciliation) and a MatchClient for the bot whose controller is a
 * BotBrain reading only its own observations. PvP later swaps the bot client
 * for a remote player and the LocalNetwork for a WebSocket; nothing else
 * changes.
 */
import { buildArena, type Arena, type ArenaDef } from "./arena";
import { REACTOR_ARENA } from "./arenaReactor";
import { BotBrain } from "./bot/brain";
import { botParams, type BotParams, type BotTier } from "./bot/tiers";
import { MatchClient } from "./client";
import { idleControl, type ControlState } from "./input";
import { observe } from "./observe";
import { hash2 } from "./rng";
import { MatchServer } from "./server";
import type { SimContext } from "./sim";
import { LocalNetwork } from "./transport";
import { DEFAULT_TUNING, type CombatTuning } from "./tuning";
import type { CombatEvent, EndReason, MatchConfig, PlayerStats } from "./types";
import type { ViewState } from "./view";

export interface LocalDuelOptions {
  difficulty?: BotTier;
  /** Finer control over the bot than a tier. */
  bot?: Partial<BotParams>;
  seed?: number;
  arena?: ArenaDef;
  tuning?: CombatTuning;
  config?: Partial<MatchConfig>;
  playerId?: string;
  playerName?: string;
  /** Simulated one-way latency between the person and the in-process server, ms (0 = none). */
  latencyMs?: number;
  jitterMs?: number;
  loss?: number;
}

export interface DuelResult {
  outcome: "won" | "lost" | "draw" | "cancelled";
  reason: EndReason;
  /** Rounds won: [person, bot]. */
  rounds: [number, number];
  stats: { player: PlayerStats; bot: PlayerStats } | null;
}

export interface FrameResult {
  view: ViewState | null;
  events: CombatEvent[];
}

export interface LocalDuel {
  readonly arena: Arena;
  readonly ctx: SimContext;
  readonly difficulty: BotTier;
  /** Advance by `dtMs` with the person's controls; returns this frame's view and new events. Keep calling until `finished`. */
  frame(dtMs: number, control: ControlState): FrameResult;
  forfeit(): void;
  readonly result: DuelResult | null;
  readonly finished: boolean;
  dispose(): void;
}

export function createLocalDuel(o: LocalDuelOptions = {}): LocalDuel {
  const tuning = o.tuning ?? DEFAULT_TUNING;
  const arena = buildArena(o.arena ?? REACTOR_ARENA, tuning.body.radius);
  const ctx: SimContext = { arena, tuning };
  const seed = (o.seed ?? 1) >>> 0;
  const difficulty = o.difficulty ?? "hard";
  const net = new LocalNetwork(hash2(seed, 0x0e7));
  const laggy = (o.latencyMs ?? 0) > 0 || (o.jitterMs ?? 0) > 0;
  // Lag compensation on: shots are judged against what the shooter saw (the
  // opponent is drawn a little in the past), for the person and the bot alike.
  const server = new MatchServer({ ctx, seed, config: o.config, snapshotEvery: laggy ? 2 : 1, lagCompensation: true });
  const human = net.link({ latencyMs: o.latencyMs ?? 0, jitterMs: o.jitterMs ?? 0, loss: o.loss ?? 0 });
  const bot = net.link();
  server.accept(human.server);
  server.accept(bot.server);
  const playerId = o.playerId ?? "commander";
  // In-process every tick brings a snapshot, so the opponent is drawn just one tick back.
  const interpDelayTicks = laggy ? undefined : 1;
  const person = new MatchClient({ ctx, channel: human.client, playerId, name: o.playerName ?? "Commander", interpDelayTicks });
  const brain = { current: null as BotBrain | null };
  const botClient = new MatchClient({
    ctx, channel: bot.client, playerId: `bot-${difficulty}`, name: `Bot (${difficulty})`, interpDelayTicks: 1,
    controller: (view, slot) => {
      if (!brain.current) brain.current = new BotBrain(slot, botParams(difficulty, o.bot), arena, tuning, hash2(seed, 0xb07));
      return brain.current.think(observe(view, slot, arena, tuning));
    },
  });
  let now = 0;
  let disposed = false;
  const pump = () => net.advance(now);
  pump();

  const resultOf = (): DuelResult | null => {
    const s = server.state;
    if (!s || s.phase !== "ended") return null;
    const me = person.slot;
    const them = 1 - me;
    const outcome = s.endReason === "cancelled" ? "cancelled" : s.winner === me ? "won" : s.winner === them ? "lost" : "draw";
    return {
      outcome, reason: s.endReason ?? "cancelled", rounds: [s.scores[me] ?? 0, s.scores[them] ?? 0],
      stats: me >= 0 ? { player: { ...s.players[me].stats }, bot: { ...s.players[them].stats } } : null,
    };
  };

  return {
    arena, ctx, difficulty,
    frame(dtMs: number, control: ControlState): FrameResult {
      if (disposed) return { view: null, events: [] };
      now += Math.min(250, Math.max(0, dtMs));
      person.setControl(control);
      pump();
      server.update(now);
      pump();
      botClient.update(now);
      person.update(now);
      pump();
      botClient.drainEvents();
      return { view: person.view(now), events: person.drainEvents() };
    },
    forfeit() {
      person.setControl({ ...idleControl(), forfeit: true });
      person.forfeit();
      pump();
      server.update(now);
      pump();
    },
    get result() { return resultOf(); },
    // Over once the person's client has the end (so the last events reached the view).
    get finished() { return person.status === "ended" || person.status === "closed" || person.status === "rejected"; },
    dispose() {
      disposed = true;
      if (!server.finished) server.cancel();
      pump();
      person.dispose();
      botClient.dispose();
    },
  };
}
