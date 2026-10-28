/**
 * Every effect of the duel in one object, React-free: the bolts and their
 * moving lights, muzzle flashes with a light pop and a wisp of smoke, heat
 * haze over a hot barrel and steam when venting, impacts that differ by
 * what was struck (walls and floor: sparks, chips, dust, a hot scorch;
 * bodies: a flare of the energy shell, red sparks; shields: a hex ripple
 * and blue sparks), the perfect parry's gold flash and shock ring, the
 * shield shattering into shards, and the knockout's burst.
 *
 * `DuelLayer` owns one, feeds it each frame's view (`frame`) and events
 * (`play`), and adds `group` to the scene. Everything is pooled; the light
 * pool's size never changes while it lives (no shader recompiles).
 */
import { Color, Group, Vector3 } from "three";
import type { CombatEvent } from "../combat/types";
import type { PlayerView, ViewState } from "../combat/view";
import { BOLT_COLOURS } from "./blaster";
import { BoltPool, Flashes, Scorches, Sparks } from "./effects";
import { BodyFlash, Debris, HeatHaze, Puffs, Shards } from "./impacts";
import { DuelLights } from "./lights";
import { ShieldMesh } from "./shield";

/** The bloom the duel asks the eye view for: stronger, wider, above a threshold only bolts, flashes and sparks reach. */
export const DUEL_BLOOM = { strength: 0.16, radius: 0.4, threshold: 6 } as const;

const WHITE = new Color(1, 1, 1);
const SPARK_HOT = new Color(1, 0.62, 0.25);
const SHIELD_SPARK = new Color(0.45, 0.8, 1);
const SHIELD_LIGHT = new Color(0.4, 0.75, 1);
const HIT_SPARK = new Color(1, 0.35, 0.15);
const BREAK_RED = new Color(1, 0.22, 0.12);
const STEAM = new Color(0.8, 0.82, 0.84);
const DUST = new Color(0.36, 0.33, 0.3);

export interface FxFrame {
  view: ViewState;
  floorY: number;
  /** The person's own body is hidden (first person: the viewmodel draws their blaster and flashes). */
  ownHidden: boolean;
  /** Camera position and view direction, world. */
  cam: { x: number; y: number; z: number };
  camDir: { x: number; y: number; z: number };
  /** Where a duellist's muzzle is (world), or null when their body is not loaded. */
  muzzle: (slot: number, out: Vector3) => Vector3 | null;
}

export class DuelFx {
  readonly group = new Group();
  readonly bolts = new BoltPool();
  readonly sparks = new Sparks();
  readonly flashes = new Flashes();
  readonly scorches = new Scorches();
  readonly steam = new Puffs(220, STEAM, 0.55, 0.9, 1.4);
  readonly dust = new Puffs(160, DUST, 0.7, 0.25, 2.4);
  readonly debris = new Debris();
  readonly shards = new Shards();
  readonly lights = new DuelLights();
  /** By role: [person, opponent]. */
  readonly shields: [ShieldMesh, ShieldMesh];
  readonly bodies = [new BodyFlash(), new BodyFlash()] as const;
  readonly hazes = [new HeatHaze(), new HeatHaze()] as const;
  private readonly v = new Vector3();
  private readonly c = new Color();
  private readonly steamAcc = [0, 0];
  private readonly hazeAt = [new Vector3(), new Vector3()];

  constructor(ownAccent: Color, foeAccent: Color) {
    this.group.name = "DuelFx";
    this.shields = [new ShieldMesh(ownAccent), new ShieldMesh(foeAccent)];
    this.group.add(
      this.bolts.group, this.sparks.points, this.sparks.streaks, this.flashes.group, this.scorches.group,
      this.steam.points, this.dust.points, this.debris.mesh, this.shards.mesh, this.lights.group,
      ...this.shields.map((s) => s.mesh), ...this.bodies.map((b) => b.mesh), ...this.hazes.map((h) => h.mesh),
    );
  }

  /** The drawing buffer's height in pixels (the puffs size themselves by it). */
  setViewportHeight(px: number): void {
    this.steam.setViewportHeight(px);
    this.dust.setViewportHeight(px);
  }

  /** Per frame, before the events: bodies' shields, shells, haze and steam; the bolts and their lights. */
  frame(step: number, f: FxFrame): void {
    const { view, floorY } = f;
    const mySlot = view.slot;
    this.lights.begin(step);
    for (const p of view.players) {
      const k = p.slot === mySlot ? 0 : 1;
      this.shields[k].update(step, p, floorY);
      this.bodies[k].update(step, p.x, floorY, p.z, p.alive);
      const own = k === 0;
      const at = own && f.ownHidden ? null : f.muzzle(p.slot, this.hazeAt[k]);
      this.hazes[k].update(step, at, p.alive ? p.heat : 0, p.alive && (p.venting || p.overheated));
      // A venting or very hot blaster steams.
      if (at && p.alive && (p.venting || p.heat > 0.85)) {
        this.steamAcc[k] += step * (p.overheated ? 34 : p.venting ? 22 : 6);
        const n = Math.floor(this.steamAcc[k]);
        if (n > 0) {
          this.steamAcc[k] -= n;
          this.steam.emit(at.x, at.y + 0.02, at.z, n, 0, 0.5, 0, 0.35, 0.06, 0.55, 1.1, p.overheated ? 0.5 : 0.38);
        }
      }
    }
    this.bolts.update(view.bolts, mySlot, floorY, (x, y, z, c, g) => this.lights.bolt(x, y, z, c, g));
  }

  /** After the events: move every particle and give the lights to the brightest requests near the camera. */
  settle(step: number, f: FxFrame): void {
    this.sparks.update(step, f.floorY);
    this.flashes.update(step);
    this.scorches.update(step);
    this.steam.update(step);
    this.dust.update(step);
    this.debris.update(step, f.floorY);
    this.shards.update(step, f.floorY);
    this.lights.apply(f.cam.x, f.cam.y, f.cam.z);
  }

  play(e: CombatEvent, f: FxFrame): void {
    const mySlot = f.view.slot;
    const y = (v: number) => v + f.floorY;
    const player = (slot: number): PlayerView | undefined => f.view.players.find((p) => p.slot === slot);
    switch (e.type) {
      case "shot": {
        const own = e.player === mySlot;
        const colour = own ? BOLT_COLOURS.own : BOLT_COLOURS.foe;
        if (own && f.ownHidden) {
          // The viewmodel draws the flash; the room still lights up from just in front of the eyes.
          const c = f.cam, d = f.camDir;
          this.lights.flash(c.x + d.x * 0.7, c.y + d.y * 0.7 - 0.2, c.z + d.z * 0.7, colour, 7, 0.07);
          break;
        }
        const at = f.muzzle(e.player, this.v) ?? this.v.set(e.x, y(e.y), e.z);
        this.flashes.spawn(at.x, at.y, at.z, colour, 10, 0.14, 0.5, 0.07, "star");
        this.flashes.spawn(at.x, at.y, at.z, WHITE, 7, 0.06, 0.18, 0.05);
        this.flashes.spawn(at.x + e.dx * 0.12, at.y + e.dy * 0.12, at.z + e.dz * 0.12, colour, 3, 0.1, 0.32, 0.09);
        this.lights.flash(at.x, at.y, at.z, colour, 9, 0.08);
        this.dust.emit(at.x + e.dx * 0.1, at.y, at.z + e.dz * 0.1, 1, e.dx * 0.8, 0.25, e.dz * 0.8, 0.15, 0.05, 0.3, 0.6, 0.18);
        break;
      }
      case "impact": {
        const ix = e.x, iy = y(e.y), iz = e.z;
        const floor = e.surface === "floor";
        this.sparks.burst(ix, iy, iz, e.nx, e.ny, e.nz, floor ? 16 : 22, SPARK_HOT, 5, 0.8, 8);
        this.flashes.spawn(ix + e.nx * 0.05, iy + e.ny * 0.05, iz + e.nz * 0.05, SPARK_HOT, 8, 0.22, 0.7, 0.12);
        this.flashes.spawn(ix + e.nx * 0.03, iy + e.ny * 0.03, iz + e.nz * 0.03, WHITE, 6, 0.06, 0.2, 0.05, "star");
        this.scorches.add(ix, iy, iz, e.nx, e.ny, e.nz);
        this.debris.burst(ix, iy, iz, e.nx, e.ny, e.nz, floor ? 4 : 6);
        this.dust.emit(ix + e.nx * 0.08, iy + e.ny * 0.08, iz + e.nz * 0.08, 3, e.nx * 0.6, e.ny * 0.6 + 0.15, e.nz * 0.6, 0.25, 0.1, 0.55, 0.9, 0.32);
        this.lights.flash(ix + e.nx * 0.3, iy + e.ny * 0.3, iz + e.nz * 0.3, SPARK_HOT, 7, 0.14);
        break;
      }
      case "hit": {
        const hx = e.x, hy = y(e.y), hz = e.z;
        const dx = hx - e.fromX, dz = hz - e.fromZ;
        const l = Math.hypot(dx, dz) || 1;
        const shooterColour = e.owner === mySlot ? BOLT_COLOURS.own : BOLT_COLOURS.foe;
        this.sparks.burst(hx, hy, hz, -dx / l, 0.2, -dz / l, e.headshot ? 30 : 20, HIT_SPARK, 4, 1.0, 9);
        this.sparks.burst(hx, hy, hz, dx / l, 0.1, dz / l, 8, shooterColour, 3, 0.5, 7);
        this.flashes.spawn(hx, hy, hz, e.headshot ? WHITE : HIT_SPARK, e.headshot ? 11 : 7, 0.22, 0.65, 0.13);
        this.dust.emit(hx, hy, hz, 2, -dx / l * 0.4, 0.3, -dz / l * 0.4, 0.2, 0.08, 0.4, 0.7, 0.25);
        // The opponent flares; the person's own hits read from the screen's red edge instead.
        if (e.target !== mySlot) this.bodies[1].hit(e.headshot ? WHITE : shooterColour, e.health <= 0 ? 2.6 : e.headshot ? 2 : 1.4);
        this.lights.flash(hx - (dx / l) * 0.4, hy, hz - (dz / l) * 0.4, HIT_SPARK, 6, 0.12);
        break;
      }
      case "block": case "deflect": {
        const k = e.player === mySlot ? 0 : 1;
        this.shields[k].block(e.x, y(e.y), e.z);
        this.sparks.burst(e.x, y(e.y), e.z, 0, 0.3, 0, e.type === "deflect" ? 20 : 12, SHIELD_SPARK, 3.6, 1.2, 7);
        this.flashes.spawn(e.x, y(e.y), e.z, SHIELD_SPARK, 7, 0.2, 0.6, 0.1);
        this.lights.flash(e.x, y(e.y), e.z, SHIELD_LIGHT, 6, 0.14);
        break;
      }
      case "parry": {
        const k = e.player === mySlot ? 0 : 1;
        const py = y(e.y);
        this.shields[k].parry(e.x, py, e.z);
        this.flashes.spawn(e.x, py, e.z, BOLT_COLOURS.parry, 16, 0.3, 1.6, 0.24, "star");
        this.flashes.spawn(e.x, py, e.z, BOLT_COLOURS.parry, 6, 0.2, 2.6, 0.32, "ring");
        this.flashes.spawn(e.x, py, e.z, WHITE, 10, 0.1, 0.45, 0.08);
        this.sparks.burst(e.x, py, e.z, 0, 0.4, 0, 36, BOLT_COLOURS.parry, 5.5, 1.3, 10);
        this.lights.flash(e.x, py, e.z, BOLT_COLOURS.parry, 16, 0.3);
        break;
      }
      case "shield_break": {
        const k = e.player === mySlot ? 0 : 1;
        this.shields[k].shatter();
        const p = player(e.player);
        if (p) {
          const tint = k === 0 ? SHIELD_SPARK : BREAK_RED;
          this.shards.shatter(p.x, f.floorY, p.z, p.aimYaw, this.c.copy(tint).multiplyScalar(4));
          const fx = p.x + Math.sin(p.aimYaw) * 0.8, fz = p.z + Math.cos(p.aimYaw) * 0.8;
          this.flashes.spawn(fx, f.floorY + 1.1, fz, BREAK_RED, 8, 0.4, 1.8, 0.25);
          this.sparks.burst(fx, f.floorY + 1.1, fz, Math.sin(p.aimYaw), 0.3, Math.cos(p.aimYaw), 26, SHIELD_SPARK, 4, 1.2, 7);
          this.lights.flash(fx, f.floorY + 1.2, fz, BREAK_RED, 10, 0.3);
        }
        break;
      }
      case "overheat": {
        if (e.player === mySlot && f.ownHidden) break;
        const at = f.muzzle(e.player, this.v);
        if (at) {
          this.steam.emit(at.x, at.y, at.z, 26, 0, 0.9, 0, 0.6, 0.08, 0.7, 1.3, 0.55);
          this.flashes.spawn(at.x, at.y, at.z, HIT_SPARK, 6, 0.12, 0.4, 0.2);
          this.sparks.burst(at.x, at.y, at.z, 0, 1, 0, 12, HIT_SPARK, 2.5, 1, 6);
        }
        break;
      }
      case "vent_start": {
        if (e.player === mySlot && f.ownHidden) break;
        const at = f.muzzle(e.player, this.v);
        if (at) this.steam.emit(at.x, at.y, at.z, 12, 0, 0.7, 0, 0.45, 0.06, 0.6, 1.1, 0.45);
        break;
      }
      case "vent_perfect": {
        if (e.player === mySlot && f.ownHidden) break;
        const at = f.muzzle(e.player, this.v);
        if (at) {
          this.steam.emit(at.x, at.y, at.z, 18, 0, 1.4, 0, 0.7, 0.06, 0.8, 0.9, 0.5);
          this.flashes.spawn(at.x, at.y, at.z, BOLT_COLOURS.parry, 6, 0.1, 0.5, 0.18);
        }
        break;
      }
      case "death": {
        const p = player(e.player);
        // The opponent goes down in a burst; the person's own fall reads from the camera and the screen, not a flash in the lens.
        if (p && e.player !== mySlot) {
          const by = f.floorY + 1.0;
          this.flashes.spawn(p.x, by, p.z, HIT_SPARK, 12, 0.4, 2.2, 0.3);
          this.flashes.spawn(p.x, by, p.z, WHITE, 6, 0.3, 3.2, 0.4, "ring");
          this.sparks.burst(p.x, by, p.z, 0, 0.8, 0, 40, HIT_SPARK, 5, 1.4, 9);
          if (e.player !== mySlot) this.dust.emit(p.x, f.floorY + 0.3, p.z, 6, 0, 0.3, 0, 0.6, 0.15, 0.8, 1.4, 0.35);
          this.lights.flash(p.x, by + 0.4, p.z, HIT_SPARK, 14, 0.45);
        }
        break;
      }
      default:
        break;
    }
  }

  clear(): void {
    this.bolts.clear();
    this.sparks.clear();
    this.flashes.clear();
    this.scorches.clear();
    this.steam.clear();
    this.dust.clear();
    this.debris.clear();
    this.shards.clear();
    this.lights.clear();
    for (const b of this.bodies) b.clear();
  }

  dispose(): void {
    this.bolts.dispose();
    this.sparks.dispose();
    this.flashes.dispose();
    this.scorches.dispose();
    this.steam.dispose();
    this.dust.dispose();
    this.debris.dispose();
    this.shards.dispose();
    this.lights.dispose();
    for (const s of this.shields) s.dispose();
    for (const b of this.bodies) b.dispose();
    for (const h of this.hazes) h.dispose();
  }
}
