/**
 * The data of a duel: what a player sends each tick (InputCommand), the
 * authoritative match state (plain, JSON-serialisable, no classes), and the
 * events a step emits for presentation.
 */

/** Button bits of an InputCommand. */
export const BTN = {
  FIRE: 1,
  ADS: 2,
  SHIELD: 4,
  DODGE: 8,
  VENT: 16,
  SPRINT: 32,
  FORFEIT: 64,
} as const;

/** Buttons that act on the press, not while held. */
export const EDGE_BUTTONS = BTN.DODGE | BTN.VENT | BTN.FORFEIT;

/**
 * One tick of one player's control. The only thing a client ever sends.
 * Values are quantised on creation (`makeInput`) so client prediction and the
 * server see the same numbers.
 */
export interface InputCommand {
  /** Per-player sequence number, +1 per tick. */
  seq: number;
  /** Strafe right (-1..1) and forward (-1..1), in the aim frame. */
  mx: number;
  my: number;
  /** Absolute aim (radians). Recoil is added on top by the simulation. */
  yaw: number;
  pitch: number;
  buttons: number;
  /**
   * The server tick the client was displaying when it made this command
   * (its interpolation time). Lag compensation rewinds a shot to it; -1 = none.
   */
  viewTick: number;
}

export type MatchPhase = "countdown" | "live" | "round_end" | "ended";
export type EndReason = "rounds" | "forfeit" | "disconnect" | "draw" | "cancelled";

export interface MatchConfig {
  roundsToWin: number;
  maxRounds: number;
  countdownTicks: number;
  roundEndTicks: number;
  roundTimeLimitTicks: number;
  surgeAfterTicks: number;
  pingEveryTicks: number;
}

export interface PlayerStats {
  shots: number;
  hits: number;
  headshots: number;
  damageDealt: number;
  damageTaken: number;
  blocks: number;
  parries: number;
  deflects: number;
  dodges: number;
  overheats: number;
  perfectVents: number;
  ventMisses: number;
  kills: number;
}

export interface PlayerState {
  slot: number;
  id: string;
  /** Spawn side this round (0 or 1); sides swap every round. */
  side: number;
  x: number;
  z: number;
  vx: number;
  vz: number;
  yaw: number;
  pitch: number;
  recoilPitch: number;
  recoilYaw: number;
  alive: boolean;
  health: number;
  lastDamageTick: number;
  /** Last input applied (repeated by the server when a client's input is late). */
  mx: number;
  my: number;
  buttons: number;
  lastSeq: number;
  /** Blaster. */
  heat: number;
  lastShotTick: number;
  nextShotTick: number;
  bloom: number;
  shotCount: number;
  /** Vent cycle in progress (manual or forced by an overheat); -1 = none. */
  ventStart: number;
  ventEnd: number;
  ventWinStart: number;
  ventWinEnd: number;
  ventFromHeat: number;
  ventForced: boolean;
  ventAttempted: boolean;
  /** Aim-down-sights blend 0..1. */
  ads: number;
  sprinting: boolean;
  sprintEndTick: number;
  /** Shield. */
  shieldUp: boolean;
  shieldEnergy: number;
  shieldRaisedAt: number;
  shieldLoweredAt: number;
  shieldBrokenUntil: number;
  /** After a break or a dodge the shield key must be released before it raises again. */
  shieldNeedsRelease: boolean;
  /** A bolt met the shield inside this raise's parry window. */
  shieldParryUsed: boolean;
  /** Raises before this tick get no parry window (whiff penalty). */
  parryReadyAt: number;
  /** Dodge roll. */
  dodgeStart: number;
  dodgeUntil: number;
  dodgeReadyAt: number;
  dodgeDx: number;
  dodgeDz: number;
  stats: PlayerStats;
}

export type BoltKind = "shot" | "deflect" | "parry";

export interface BoltState {
  id: number;
  /** Who it belongs to now (a parry or deflection hands it to the blocker). */
  owner: number;
  /** Who fired it first. */
  shooter: number;
  kind: BoltKind;
  x: number;
  y: number;
  z: number;
  vx: number;
  vy: number;
  vz: number;
  /** Damage multiplier on the falloff curve (1 for a shot, less for a deflection). */
  damageMul: number;
  /** Metres flown since it was fired or last turned by a shield (falloff runs on this). */
  traveled: number;
  bornTick: number;
  reflections: number;
}

/** Recent poses for lag compensation: ring of [tick, x0, z0, x1, z1]. */
export interface PoseHistory {
  ticks: number[];
  poses: number[][];
}

export interface MatchState {
  v: 1;
  seed: number;
  tick: number;
  phase: MatchPhase;
  /** Tick the current phase began and the tick it is due to end (countdown, round time limit, pause). */
  phaseStart: number;
  phaseEndsAt: number;
  round: number;
  roundStartTick: number;
  scores: number[];
  /** Winning slot, -1 for a draw, null while the match runs. */
  winner: number | null;
  endReason: EndReason | null;
  config: MatchConfig;
  players: PlayerState[];
  bolts: BoltState[];
  nextBoltId: number;
  history: PoseHistory;
}

export type Surface = "wall" | "floor" | "prop" | "ceiling";

export type CombatEvent =
  | { type: "shot"; tick: number; player: number; bolt: number; shot: number; x: number; y: number; z: number; dx: number; dy: number; dz: number; heat: number; ads: boolean }
  | { type: "hit"; tick: number; bolt: number; owner: number; target: number; damage: number; headshot: boolean; health: number; x: number; y: number; z: number; fromX: number; fromZ: number }
  | { type: "impact"; tick: number; bolt: number; surface: Surface; collider: string | null; x: number; y: number; z: number; nx: number; ny: number; nz: number }
  | { type: "block"; tick: number; player: number; bolt: number; energy: number; x: number; y: number; z: number }
  | { type: "deflect"; tick: number; player: number; bolt: number; x: number; y: number; z: number }
  | { type: "parry"; tick: number; player: number; bolt: number; target: number; x: number; y: number; z: number }
  | { type: "bolt_expire"; tick: number; bolt: number }
  | { type: "shield_up"; tick: number; player: number; seq: number }
  | { type: "shield_down"; tick: number; player: number }
  | { type: "shield_break"; tick: number; player: number }
  | { type: "shield_ready"; tick: number; player: number }
  | { type: "overheat"; tick: number; player: number; shot: number }
  | { type: "vent_start"; tick: number; player: number; seq: number; forced: boolean; end: number; winStart: number; winEnd: number }
  | { type: "vent_perfect"; tick: number; player: number; seq: number }
  | { type: "vent_miss"; tick: number; player: number; seq: number }
  | { type: "vent_end"; tick: number; player: number }
  | { type: "dodge"; tick: number; player: number; seq: number; dx: number; dz: number }
  | { type: "death"; tick: number; player: number; killer: number }
  | { type: "countdown"; tick: number; round: number; endsAt: number }
  | { type: "round_start"; tick: number; round: number }
  | { type: "surge"; tick: number; round: number }
  | { type: "ping"; tick: number; player: number; x: number; z: number }
  | { type: "round_end"; tick: number; round: number; winner: number; reason: "kill" | "time" | "trade"; scores: number[] }
  | { type: "match_end"; tick: number; winner: number; reason: EndReason; scores: number[] };

export type CombatEventType = CombatEvent["type"];

/**
 * A stable identity for an event, the same whether a client predicted it or
 * the server sent it, so presentation plays it once.
 */
export function eventKey(e: CombatEvent): string {
  switch (e.type) {
    case "shot": return `shot:${e.player}:${e.shot}`;
    case "overheat": return `overheat:${e.player}:${e.shot}`;
    case "shield_up":
    case "vent_start":
    case "vent_perfect":
    case "vent_miss":
    case "dodge":
      return `${e.type}:${e.player}:${e.seq}`;
    default:
      return `${e.type}:${e.tick}:${"player" in e ? e.player : ""}:${"bolt" in e ? e.bolt : ""}`;
  }
}
