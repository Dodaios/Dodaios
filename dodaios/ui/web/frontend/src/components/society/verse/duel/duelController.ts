/**
 * The duel as the stage runs it: one object per stage that starts a match
 * against the bot (`combat/createLocalDuel`), feeds it the person's keys and
 * mouse every frame, keeps the shoulder camera on them, collects the frame's
 * events for the effects, the HUD and the sounds, and ends it (forfeit,
 * leave, the match's end) handing control back to the deck.
 *
 * Phases:
 *
 *   off --start()--> running <--pause()/resume()--> paused
 *                      |  the match ends               |  leave()
 *                      v                               v
 *                    result --rematch()--> running    off
 *                      | leave()
 *                      v
 *                     off
 *
 * Paused freezes the match (the duel's clock only advances with the frames
 * it is given), so a released pointer or an opened menu never costs a
 * round. React-free; the stage subscribes for phase changes.
 */
import { resolveAim } from "../combat/camera";
import { idleControl, type ControlState } from "../combat/input";
import type { BotTier } from "../combat/bot/tiers";
import { createLocalDuel, type DuelResult, type LocalDuel, type LocalDuelOptions } from "../combat/session";
import type { CombatEvent } from "../combat/types";
import type { ViewState } from "../combat/view";
import type { SegmentTest } from "../engine/realtime/shoulderRig";
import { DuelCamera, type DuelCameraPose } from "./duelCamera";
import { buildHudModel, DuelHudFeed, type HudModel } from "./duelHud";
import { DuelInput } from "./duelInput";
import { DuelSound } from "./duelSound";

export type DuelPhase = "off" | "running" | "paused" | "result";
export type DuelDifficulty = BotTier;
export const DUEL_DIFFICULTIES: readonly DuelDifficulty[] = ["normal", "hard", "elite"];

/** Where the person stood when the duel ended: the deck takes them back there. */
export interface DuelExit { x: number; z: number; yaw: number }

export interface DuelControllerOptions {
  /** Makes the match (tests pass a seeded or scripted one). */
  create?: (o: LocalDuelOptions) => LocalDuel;
  sound?: DuelSound | null;
  now?: () => number;
}

export class DuelController {
  phase: DuelPhase = "off";
  difficulty: DuelDifficulty = "hard";
  readonly input = new DuelInput();
  readonly camera = new DuelCamera();
  readonly feed = new DuelHudFeed();
  /** The latest frame of the match (null before the first). */
  view: ViewState | null = null;
  /** The finished match's result while the result screen shows. */
  result: DuelResult | null = null;
  /** Deck floor height under the arena, metres (the arena's y 0). */
  floorY = 0;
  /** Effects drain this every frame (the 3D layer); events stay here for one frame. */
  readonly visualEvents: CombatEvent[] = [];
  /** Called when the duel hands control back to the deck. */
  onExit: ((at: DuelExit | null) => void) | null = null;
  /** The pointer was locked to the stage during this match (losing the lock then pauses it). */
  hadLock = false;
  /** What the crosshair covers (the opponent turns it red). */
  aimTarget: "player" | "world" | "none" = "none";
  /** QA: held controls forced on top of the person's (`window.__verseDuel.hold`). */
  forced: Partial<ControlState> = {};
  /** Shots the person has fired this match, and whether the last one was in the sights (the viewmodel kicks on each). */
  ownShots = 0;
  lastShotAds = false;
  private duel: LocalDuel | null = null;
  private readonly control: ControlState = idleControl();
  private readonly listeners = new Set<() => void>();
  private readonly create: (o: LocalDuelOptions) => LocalDuel;
  private readonly sound: DuelSound | null;
  private readonly now: () => number;
  private lastCount = -1;
  private pausedAt = 0;
  private forcedPress: { dodge?: boolean; vent?: boolean } = {};

  constructor(o: DuelControllerOptions = {}) {
    this.create = o.create ?? createLocalDuel;
    this.sound = o.sound === undefined ? new DuelSound() : o.sound;
    this.now = o.now ?? (() => performance.now());
  }

  get active(): boolean {
    return this.phase !== "off";
  }

  /** The match takes the person's input right now. */
  get live(): boolean {
    return this.phase === "running";
  }

  subscribe = (fn: () => void): (() => void) => {
    this.listeners.add(fn);
    return () => { this.listeners.delete(fn); };
  };

  getPhase = (): DuelPhase => this.phase;

  private setPhase(next: DuelPhase): void {
    if (this.phase === next) return;
    this.phase = next;
    if (next === "paused") this.pausedAt = this.now();
    for (const fn of [...this.listeners]) fn();
  }

  /** A new match against the bot at `difficulty`. Any match in progress is dropped. */
  start(difficulty: DuelDifficulty = this.difficulty, seed: number = (Math.random() * 0x7fffffff) >>> 0): void {
    this.duel?.dispose();
    this.difficulty = difficulty;
    this.duel = this.create({ difficulty, seed, playerName: "Commander" });
    this.view = null;
    this.result = null;
    this.feed.reset();
    this.input.clear();
    this.visualEvents.length = 0;
    this.lastCount = -1;
    this.forced = {};
    this.forcedPress = {};
    this.hadLock = false;
    this.ownShots = 0;
    const spawn = this.duel.arena.def.spawns;
    // The camera faces the first spawn's way until the first frame says which side the person has.
    this.camera.face(spawn[0].yaw);
    this.sound?.resume();
    this.setPhase("running");
    // The first frame (no time passes) places the players.
    this.step(0, null);
  }

  /** Freeze the match (the pointer was released, Escape). */
  pause(): void {
    if (this.phase !== "running") return;
    this.input.clear();
    this.sound?.silence();
    this.setPhase("paused");
  }

  resume(): void {
    if (this.phase !== "paused") return;
    this.sound?.resume();
    this.setPhase("running");
  }

  /** Escape: pause a running match; a second Escape (not the browser's echo of the first) leaves it. */
  escape(): void {
    if (this.phase === "running") { this.pause(); return; }
    if (this.phase === "paused" && this.now() - this.pausedAt > 250) { this.leave(); return; }
    if (this.phase === "result") this.leave();
  }

  /** Forfeit if a match is on, then hand control back to the deck. */
  leave(): void {
    if (this.phase === "off") return;
    const at = this.exitPoint();
    if (this.duel && !this.duel.finished) this.duel.forfeit();
    this.duel?.dispose();
    this.duel = null;
    this.input.clear();
    this.sound?.silence();
    this.visualEvents.length = 0;
    this.setPhase("off");
    this.onExit?.(at);
  }

  /** The same difficulty again, from the result screen. */
  rematch(): void {
    this.start(this.difficulty);
  }

  dispose(): void {
    this.duel?.dispose();
    this.duel = null;
    this.sound?.dispose();
    this.listeners.clear();
    this.phase = "off";
  }

  private exitPoint(): DuelExit | null {
    const me = this.view?.players[this.view.slot];
    return me ? { x: me.x, z: me.z, yaw: me.yaw } : null;
  }

  /** QA hooks: hold controls (fire, shield, ads, moveX...) or press one (dodge, vent) on the next frame. */
  hold(c: Partial<ControlState>): void {
    this.forced = { ...this.forced, ...c };
  }

  press(name: "dodge" | "vent"): void {
    this.forcedPress[name] = true;
  }

  /** The camera pose of the last frame (world coordinates), for the renderer. */
  get pose(): DuelCameraPose {
    return this.camera.pose;
  }

  /**
   * One rendered frame: advance the match by `dtMs` (none while paused or
   * over), move the camera, solve the crosshair for the next input. `test`
   * is the deck's collision (world).
   */
  frame(dtMs: number, test: SegmentTest | null = null): void {
    if (this.phase === "off") return;
    this.step(this.phase === "running" ? dtMs : 0, test);
  }

  private step(dtMs: number, test: SegmentTest | null): void {
    const duel = this.duel;
    if (!duel) return;
    // The aim solved last frame goes out with this frame's keys.
    const control = this.control;
    if (this.phase === "running") {
      this.input.control(control.yaw, control.pitch, control);
      Object.assign(control, this.forced);
      if (this.forcedPress.dodge) control.dodge = true;
      if (this.forcedPress.vent) control.vent = true;
      this.forcedPress = {};
    } else {
      const { yaw, pitch } = control;
      Object.assign(control, idleControl(yaw, pitch));
    }
    const { view, events } = duel.frame(dtMs, control);
    const now = this.now();
    if (view) {
      const first = !this.view;
      this.view = view;
      const me = view.players[view.slot];
      // Each round (sides swap) starts facing the way the spawn faces.
      if (me && (first || events.some((e) => e.type === "countdown"))) {
        const spawn = duel.arena.def.spawns[me.side];
        this.camera.face(spawn?.yaw ?? me.yaw);
      }
      if (me) {
        const pose = this.camera.update(dtMs / 1000, me, this.floorY, test);
        // The crosshair converges the blaster on what it covers (arena coordinates: floor at y 0).
        const aim = resolveAim(duel.ctx, view, { x: pose.position.x, y: pose.position.y - this.floorY, z: pose.position.z }, pose.aimDir);
        control.yaw = aim.yaw;
        control.pitch = aim.pitch;
        this.aimTarget = aim.target;
        for (const e of events) {
          if (e.type === "shot" && e.player === view.slot) {
            this.camera.kick(e.ads ? 0.35 : 0.6);
            this.ownShots++;
            this.lastShotAds = !!e.ads;
          }
          if (e.type === "hit" && e.target === view.slot) this.camera.kick(1.1);
          if (e.type === "parry" && e.player === view.slot) this.camera.kick(0.8);
        }
      }
      this.feed.ingest(events, view.slot, now);
      const count = view.match.phase === "countdown" ? Math.ceil(view.match.countdown) : -1;
      if (count !== this.lastCount && count > 0) this.sound?.tick(count === 1);
      this.lastCount = count;
      const cam = this.camera.pose.position;
      this.sound?.play(events, view.slot, { x: cam.x, z: cam.z, yaw: this.camera.yaw }, view.players);
    }
    for (const e of events) this.visualEvents.push(e);
    // A burst the renderer never drained (a hidden stage) is not kept forever.
    if (this.visualEvents.length > 400) this.visualEvents.splice(0, this.visualEvents.length - 400);
    if (duel.finished && this.phase !== "result") {
      this.result = duel.result;
      this.setPhase("result");
    }
  }

  /** The HUD for this moment, or null when no match is on screen. */
  hud(): HudModel | null {
    if (!this.view || this.phase === "off") return null;
    return buildHudModel(this.view, this.feed, this.now(), this.camera.yaw);
  }
}

