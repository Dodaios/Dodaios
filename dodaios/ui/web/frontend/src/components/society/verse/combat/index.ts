/**
 * Dodaios Verse combat: an optional 1v1 blaster duel in the Reactor Shaft.
 * Renderer-independent and React-free; see docs/verse/combat.md.
 *
 * Integrator entry points:
 * - createLocalDuel()      a duel against the bot, one call per frame
 * - REACTOR_ARENA          where it happens (deck coordinates)
 * - resolveAim, cameraRigFor, cameraPose, CAMERA_RIGS   camera and crosshair
 * - ControlState / idleControl   what the keys and mouse map to
 * - ViewState / CombatEvent      what to draw and which effects to play
 */
export { createLocalDuel, type DuelResult, type FrameResult, type LocalDuel, type LocalDuelOptions } from "./session";
export { REACTOR_ARENA } from "./arenaReactor";
export { buildArena, isWalkable, lineOfSight, raycastWorld, type Arena, type ArenaDef, type ArenaPoint } from "./arena";
export { CAMERA_RIGS, cameraPose, cameraRigFor, crosshairRadiusPx, resolveAim, type AimSolution, type CameraRig } from "./camera";
export { idleControl, makeInput, sanitizeInput, type ControlState } from "./input";
export { buildView, type BoltView, type HudState, type MatchView, type PlayerView, type ViewState } from "./view";
export { eventKey, BTN, type CombatEvent, type CombatEventType, type InputCommand, type MatchState } from "./types";
export { DEFAULT_TUNING, TICK_RATE, TICK_DT, type CombatTuning } from "./tuning";
export { createContext, createMatch, step, muzzleOf, rulesHash, type SimContext } from "./sim";
export { MatchServer, type MatchServerOptions } from "./server";
export { MatchClient, type MatchClientOptions } from "./client";
export { LocalNetwork, socketChannel, type Channel, type LinkOptions, type SocketLike } from "./transport";
export { PROTOCOL_VERSION, type ClientMsg, type ServerMsg } from "./protocol";
export { observe, type Observation, type WorldView } from "./observe";
export { BotBrain } from "./bot/brain";
export { BOT_TIERS, botParams, type BotParams, type BotTier } from "./bot/tiers";
