// @vitest-environment node
/**
 * The duel as the stage runs it: the input mapping (keys and buttons to the
 * combat core's ControlState), the shoulder camera, the HUD model from the
 * view and the events, and the start / pause / leave / result / rematch flow
 * of the controller against the real local duel.
 */
import { describe, expect, it } from "vitest";
import { createLocalDuel, type LocalDuelOptions } from "../combat/session";
import type { CombatEvent } from "../combat/types";
import type { PlayerView, ViewState } from "../combat/view";
import { SHOULDER } from "../engine/realtime/shoulderRig";
import { DuelCamera, DUEL_CAMERA, duelFov, firstFov } from "./duelCamera";
import { DuelController, type DuelExit } from "./duelController";
import { buildHudModel, DuelHudFeed, HUD_TIMES } from "./duelHud";
import { DuelInput, isDuelKey } from "./duelInput";

describe("duel input mapping", () => {
  it("maps WASD to strafe and forward in the aim frame", () => {
    const input = new DuelInput();
    input.keyDown("KeyW");
    let c = input.control(0.5, 0.1);
    expect([c.moveX, c.moveY]).toEqual([0, 1]);
    expect(c.yaw).toBe(0.5);
    expect(c.pitch).toBe(0.1);
    input.keyDown("KeyD");
    c = input.control(0, 0);
    expect([c.moveX, c.moveY]).toEqual([1, 1]);
    input.keyUp("KeyW");
    input.keyDown("KeyS");
    input.keyDown("KeyA");
    c = input.control(0, 0);
    expect([c.moveX, c.moveY]).toEqual([0, -1]);
    input.keyUp("KeyD");
    c = input.control(0, 0);
    expect([c.moveX, c.moveY]).toEqual([-1, -1]);
  });

  it("moves with the arrow keys too", () => {
    const input = new DuelInput();
    input.keyDown("ArrowUp");
    input.keyDown("ArrowLeft");
    const c = input.control(0, 0);
    expect([c.moveX, c.moveY]).toEqual([-1, 1]);
  });

  it("holds fire, sights and shield; sprints only going forward", () => {
    const input = new DuelInput();
    input.mouseDown(0);
    input.mouseDown(2);
    input.keyDown("KeyQ");
    input.keyDown("ShiftLeft");
    let c = input.control(0, 0);
    expect(c.fire && c.ads && c.shield).toBe(true);
    expect(c.sprint).toBe(false);
    input.keyDown("KeyW");
    c = input.control(0, 0);
    expect(c.sprint).toBe(true);
    input.mouseUp(0);
    input.mouseUp(2);
    input.keyUp("KeyQ");
    c = input.control(0, 0);
    expect(c.fire || c.ads || c.shield).toBe(false);
    expect(c.forfeit).toBe(false);
  });

  it("latches a dodge or vent press for exactly one read, and ignores auto-repeat", () => {
    const input = new DuelInput();
    input.keyDown("Space");
    input.keyUp("Space");
    input.keyDown("KeyR");
    let c = input.control(0, 0);
    expect(c.dodge).toBe(true);
    expect(c.vent).toBe(true);
    c = input.control(0, 0);
    expect(c.dodge).toBe(false);
    expect(c.vent).toBe(false);
    input.keyDown("Space", true);
    expect(input.control(0, 0).dodge).toBe(false);
  });

  it("lets everything go on clear (focus lost, pause)", () => {
    const input = new DuelInput();
    input.keyDown("KeyW");
    input.mouseDown(0);
    input.keyDown("KeyR");
    input.clear();
    const c = input.control(0, 0);
    expect([c.moveX, c.moveY, c.fire, c.vent]).toEqual([0, 0, false, false]);
  });

  it("claims only the keys it uses", () => {
    expect(isDuelKey("KeyW")).toBe(true);
    expect(isDuelKey("KeyQ")).toBe(true);
    expect(isDuelKey("Space")).toBe(true);
    expect(isDuelKey("KeyV")).toBe(false);
    expect(isDuelKey("KeyE")).toBe(false);
    expect(new DuelInput().keyDown("KeyL")).toBe(false);
  });
});

function player(over: Partial<PlayerView> = {}): PlayerView {
  return {
    slot: 0, id: "a", local: true, side: 0, x: 40, z: 20, yaw: 0, pitch: 0, aimYaw: 0, aimPitch: 0, vx: 0, vz: 0, speed: 0,
    alive: true, health: 100, healthMax: 100, shieldUp: false, shieldEnergy: 1, shieldBroken: false, parrying: false, ads: 0,
    sprinting: false, dodging: false, dodgeProgress: 0, venting: false, overheated: false, heat: 0, ...over,
  };
}

describe("duel camera", () => {
  it("turns with the mouse: right turns right, up looks up, pitch is clamped", () => {
    const cam = new DuelCamera();
    cam.look(100, 0);
    // Yaw 0 faces +Z; the right of that is -X, which a smaller yaw turns toward.
    expect(cam.yaw).toBeLessThan(0);
    cam.look(0, -100);
    expect(cam.pitch).toBeGreaterThan(0);
    cam.invertY = true;
    const before = cam.pitch;
    cam.look(0, -50);
    expect(cam.pitch).toBeLessThan(before);
    cam.look(0, -1e6);
    expect(cam.pitch).toBeGreaterThanOrEqual(DUEL_CAMERA.minPitch);
    cam.look(0, 1e6);
    expect(cam.pitch).toBeLessThanOrEqual(DUEL_CAMERA.maxPitch);
  });

  it("sits behind the right shoulder and closes in for the sights", () => {
    const cam = new DuelCamera();
    cam.face(0);
    const hip = cam.update(1 / 60, player(), 0);
    // Facing +Z: behind is -Z, the right shoulder is -X.
    expect(hip.position.z).toBeLessThan(20 - 2);
    expect(hip.position.x).toBeLessThan(40);
    expect(hip.position.y).toBeGreaterThan(1.4);
    const hipBack = 20 - hip.position.z;
    const hipFov = hip.fovDeg;
    let ads = hip;
    for (let i = 0; i < 60; i++) ads = cam.update(1 / 60, player({ ads: 1 }), 0);
    expect(20 - ads.position.z).toBeLessThan(hipBack);
    expect(ads.fovDeg).toBeLessThan(hipFov);
  });

  it("keeps a normal shooter's field of view that follows the person's setting", () => {
    const cam = new DuelCamera();
    cam.face(0);
    const hip = cam.update(1 / 60, player(), 0).fovDeg;
    // About 80 deg across a 16:9 frame: no fish-eye.
    const across = (2 * Math.atan(Math.tan((hip * Math.PI) / 360) * (16 / 9)) * 180) / Math.PI;
    expect(hip).toBeGreaterThan(45);
    expect(hip).toBeLessThan(56);
    expect(across).toBeLessThan(90);
    expect(duelFov(50)).toBeCloseTo(50);
    expect(duelFov(50, 90)).toBeGreaterThan(50);
    expect(duelFov(50, 55)).toBeLessThan(50);
    cam.hfovSetting = 90;
    expect(cam.update(1 / 60, player(), 0).fovDeg).toBeGreaterThan(hip);
  });

  it("is pulled in front of a wall behind the player", () => {
    const cam = new DuelCamera();
    cam.face(0);
    // A wall 1 m behind the player (z = 19): every segment crossing it is cut there.
    const test = (from: { z: number }, to: { z: number }) => {
      if ((from.z - 19) * (to.z - 19) >= 0) return null;
      return (from.z - 19) / (from.z - to.z);
    };
    const pose = cam.update(1 / 60, player(), 0, test);
    expect(pose.position.z).toBeGreaterThan(19);
  });

  it("follows the recoil in the view but not in the aim", () => {
    const cam = new DuelCamera();
    cam.face(0);
    const pose = cam.update(1 / 60, player({ aimPitch: 0.02 }), 0);
    expect(pose.dir.y).toBeGreaterThan(0.015);
    expect(pose.aimDir.y).toBeCloseTo(0, 6);
  });

  it("fights through the eyes in first person, with the first-person field of view", () => {
    const cam = new DuelCamera();
    cam.firstPerson = true;
    cam.face(0);
    const p = player();
    const pose = cam.update(1 / 60, p, 0);
    expect(cam.firstShare).toBe(1);
    // At eye height, a little ahead of the body's axis along the view (+Z), not beside the head.
    expect(pose.position.y).toBeCloseTo(DUEL_CAMERA.eyeHeight, 6);
    expect(pose.position.x).toBeCloseTo(p.x, 6);
    expect(pose.position.z).toBeCloseTo(p.z + DUEL_CAMERA.eyeForward, 6);
    expect(pose.fovDeg).toBeCloseTo(firstFov(50, SHOULDER.firstHfovDeg, 16 / 9), 3);
    // The sights narrow it.
    const hipFov = pose.fovDeg;
    let ads = hipFov;
    for (let i = 0; i < 60; i++) ads = cam.update(1 / 60, player({ ads: 1 }), 0).fovDeg;
    expect(ads).toBeLessThan(hipFov);
    // A wider first-person setting widens it.
    expect(firstFov(50, 100)).toBeGreaterThan(firstFov(50, 85));
  });

  it("blends between the shoulder and the eyes when the person changes mid-match", () => {
    const cam = new DuelCamera();
    cam.face(0);
    const third = cam.update(1 / 60, player(), 0).position.y;
    cam.firstPerson = true;
    cam.update(1 / 60, player(), 0);
    expect(cam.firstShare).toBeGreaterThan(0);
    expect(cam.firstShare).toBeLessThan(1);
    for (let i = 0; i < 60; i++) cam.update(1 / 60, player(), 0);
    expect(cam.firstShare).toBe(1);
    cam.firstPerson = false;
    for (let i = 0; i < 60; i++) cam.update(1 / 60, player(), 0);
    expect(cam.firstShare).toBe(0);
    expect(cam.pose.position.y).toBeCloseTo(third, 3);
  });

  it("dips the eyes through a dodge roll, drops them when knocked out, keeps them off a wall ahead", () => {
    const cam = new DuelCamera();
    cam.firstPerson = true;
    cam.face(0);
    const rolling = cam.update(1 / 60, player({ dodging: true, dodgeProgress: 0.5 }), 0).position.y;
    expect(rolling).toBeLessThan(DUEL_CAMERA.eyeHeight - 0.4);
    let down = 0;
    for (let i = 0; i < 60; i++) down = cam.update(1 / 60, player({ alive: false }), 0).position.y;
    expect(down).toBeLessThan(0.5);
    // A wall 5 cm ahead of the body's axis: the eyes stay behind it.
    const p = player();
    const wall = p.z + 0.05;
    const test = (from: { z: number }, to: { z: number }) => {
      if ((from.z - wall) * (to.z - wall) >= 0) return null;
      return (wall - from.z) / (to.z - from.z);
    };
    const near = new DuelCamera();
    near.firstPerson = true;
    near.face(0);
    expect(near.update(1 / 60, p, 0, test).position.z).toBeLessThanOrEqual(wall);
  });
});

function viewOf(over: { phase?: ViewState["match"]["phase"]; countdown?: number; round?: number; me?: Partial<PlayerView> } = {}): ViewState {
  const me = player(over.me);
  const foe = player({ slot: 1, id: "b", local: false, x: 60, z: 20 });
  return {
    status: "playing", slot: 0,
    match: {
      tick: 100, phase: over.phase ?? "live", round: over.round ?? 1, scores: [1, 0], roundsToWin: 2, winner: null, endReason: null,
      countdown: over.countdown ?? 0, roundTimeLeft: 61.2, surge: false,
    },
    players: [me, foe],
    bolts: [],
    hud: {
      health: me.health, healthMax: 100, heat: 0.4, overheated: false, venting: false, ventProgress: 0, ventWindow: null, ventAttempted: false,
      shieldEnergy: 0.8, shieldUp: false, shieldBroken: false, shieldBrokenLeft: 0, shieldCanRaise: true, parryReady: true, dodgeReady: true,
      dodgeCooldown: 0, spreadDeg: 1.6, ads: 0, sprinting: false, canFire: true, recoilPitchDeg: 0, recoilYawDeg: 0, enemyHealth: 55, enemyHealthMax: 100,
    },
  };
}

const hit = (over: Partial<Extract<CombatEvent, { type: "hit" }>>): CombatEvent => ({
  type: "hit", tick: 1, bolt: 1, owner: 0, target: 1, damage: 15, headshot: false, health: 70, x: 0, y: 1, z: 0, fromX: 0, fromZ: 0, ...over,
});

describe("duel HUD model", () => {
  it("reads health, shield, heat, score and clock off the view", () => {
    const m = buildHudModel(viewOf({ me: { health: 25 } }), new DuelHudFeed(), 0, 0);
    expect(m.health).toBe(25);
    expect(m.healthFrac).toBeCloseTo(0.25);
    expect(m.lowHealth).toBe(true);
    expect(m.myScore).toBe(1);
    expect(m.theirScore).toBe(0);
    expect(m.timeLeft).toBe(62);
    expect(m.enemyHealthFrac).toBeCloseTo(0.55);
    expect(m.shieldFrac).toBeCloseTo(0.8);
    expect(m.heat).toBeCloseTo(0.4);
    expect(buildHudModel(viewOf(), new DuelHudFeed(), 0, 0).lowHealth).toBe(false);
  });

  it("marks hits, headshots and the knockout, and lets them fade", () => {
    const feed = new DuelHudFeed();
    feed.ingest([hit({})], 0, 1000);
    expect(buildHudModel(viewOf(), feed, 1000, 0).hitMarker?.kind).toBe("hit");
    feed.ingest([hit({ headshot: true })], 0, 1100);
    expect(buildHudModel(viewOf(), feed, 1100, 0).hitMarker?.kind).toBe("head");
    feed.ingest([hit({ health: 0 })], 0, 1200);
    feed.ingest([hit({})], 0, 1210);
    expect(buildHudModel(viewOf(), feed, 1210, 0).hitMarker?.kind).toBe("kill");
    expect(buildHudModel(viewOf(), feed, 1200 + HUD_TIMES.killMarker + 1, 0).hitMarker).toBeNull();
    // The opponent's hits on the opponent are not the person's markers.
    const other = new DuelHudFeed();
    other.ingest([hit({ owner: 1, target: 1 })], 0, 0);
    expect(buildHudModel(viewOf(), other, 0, 0).hitMarker).toBeNull();
  });

  it("points the damage arc where the hit came from, relative to the camera", () => {
    const feed = new DuelHudFeed();
    // The person at (40, 20) looks along +Z (camera yaw 0); the shooter straight ahead, then on the right (-X).
    feed.ingest([hit({ owner: 1, target: 0, fromX: 40, fromZ: 40 })], 0, 0);
    let m = buildHudModel(viewOf(), feed, 10, 0);
    expect(m.damageArcs).toHaveLength(1);
    expect(m.damageArcs[0].angleDeg).toBeCloseTo(0, 5);
    expect(m.hurt).toBeGreaterThan(0.9);
    const right = new DuelHudFeed();
    right.ingest([hit({ owner: 1, target: 0, fromX: 20, fromZ: 20 })], 0, 0);
    m = buildHudModel(viewOf(), right, 10, 0);
    expect(m.damageArcs[0].angleDeg).toBeCloseTo(90, 5);
    expect(buildHudModel(viewOf(), right, HUD_TIMES.damageArc + 1, 0).damageArcs).toHaveLength(0);
  });

  it("shows the countdown, the fight call and the round's end", () => {
    const feed = new DuelHudFeed();
    expect(buildHudModel(viewOf({ phase: "countdown", countdown: 2.4 }), feed, 0, 0).banner).toEqual({ kind: "countdown", value: 3 });
    feed.ingest([{ type: "round_start", tick: 1, round: 1 }], 0, 100);
    expect(buildHudModel(viewOf(), feed, 200, 0).banner).toEqual({ kind: "fight" });
    expect(buildHudModel(viewOf(), feed, 100 + HUD_TIMES.fight + 1, 0).banner).toBeNull();
    feed.ingest([{ type: "round_end", tick: 2, round: 1, winner: 1, reason: "kill", scores: [0, 1] }], 0, 3000);
    expect(buildHudModel(viewOf({ phase: "round_end" }), feed, 3000, 0).banner).toEqual({ kind: "round", outcome: "lost", reason: "kill" });
  });

  it("calls out the person's parries and perfect vents", () => {
    const feed = new DuelHudFeed();
    feed.ingest([{ type: "parry", tick: 1, player: 0, bolt: 3, target: 1, x: 0, y: 1, z: 0 }], 0, 0);
    expect(buildHudModel(viewOf(), feed, 0, 0).callout?.key).toBe("parry");
    feed.ingest([{ type: "vent_perfect", tick: 2, player: 0, seq: 5 }], 0, 10);
    expect(buildHudModel(viewOf(), feed, 10, 0).callout?.key).toBe("perfect_vent");
    feed.ingest([{ type: "vent_perfect", tick: 3, player: 1, seq: 9 }], 0, 20);
    expect(buildHudModel(viewOf(), feed, 20, 0).callout?.key).toBe("perfect_vent");
  });
});

/** A controller on its own clock, silent, with a fast match (first to one round). */
function controller(options: Partial<LocalDuelOptions> = {}) {
  const clock = { now: 0 };
  const c = new DuelController({
    sound: null,
    now: () => clock.now,
    create: (o) => createLocalDuel({ ...o, seed: 11, config: { roundsToWin: 1, maxRounds: 1 }, ...options }),
  });
  const frame = (n = 1, ms = 1000 / 60) => { for (let i = 0; i < n; i++) { clock.now += ms; c.frame(ms); } };
  return { c, clock, frame };
}

describe("duel flow", () => {
  it("starts running with both players placed and the HUD up", () => {
    const { c, frame } = controller();
    const phases: string[] = [];
    c.subscribe(() => phases.push(c.phase));
    expect(c.phase).toBe("off");
    c.start("normal");
    expect(c.phase).toBe("running");
    expect(phases).toEqual(["running"]);
    expect(c.view?.players).toHaveLength(2);
    frame(10);
    expect(c.view!.match.phase).toBe("countdown");
    const hud = c.hud();
    expect(hud?.banner?.kind).toBe("countdown");
    expect(c.pose.fovDeg).toBeGreaterThan(40);
  });

  it("aims where the mouse turns the camera", () => {
    const { c, frame } = controller();
    c.start("normal");
    frame(5);
    const before = c.view!.players[c.view!.slot].yaw;
    c.camera.look(-300, 0);
    frame(5);
    const after = c.view!.players[c.view!.slot].yaw;
    expect(Math.abs(Math.atan2(Math.sin(after - before), Math.cos(after - before)))).toBeGreaterThan(0.3);
  });

  it("fires bolts when the fire button is held once the round is live", () => {
    const { c, frame } = controller();
    c.start("normal");
    frame(200);
    expect(c.view!.match.phase).toBe("live");
    c.input.mouseDown(0);
    const seen: string[] = [];
    for (let i = 0; i < 30; i++) { frame(1); seen.push(...c.visualEvents.map((e) => e.type)); c.visualEvents.length = 0; }
    expect(seen).toContain("shot");
  });

  it("freezes the match while paused and goes on after resume", () => {
    const { c, frame } = controller();
    c.start("hard");
    frame(30);
    c.pause();
    expect(c.phase).toBe("paused");
    const tick = c.view!.match.tick;
    frame(60);
    expect(c.view!.match.tick).toBe(tick);
    c.resume();
    frame(30);
    expect(c.view!.match.tick).toBeGreaterThan(tick);
  });

  it("pauses on the first Escape and leaves on a second one, handing the commander back where they stood", () => {
    const { c, clock, frame } = controller();
    const exits: (DuelExit | null)[] = [];
    c.onExit = (at) => exits.push(at);
    c.start("elite");
    frame(20);
    c.escape();
    expect(c.phase).toBe("paused");
    // The browser's own Escape (releasing the mouse) right after does not leave.
    clock.now += 50;
    c.escape();
    expect(c.phase).toBe("paused");
    clock.now += 400;
    c.escape();
    expect(c.phase).toBe("off");
    expect(exits).toHaveLength(1);
    expect(exits[0]).not.toBeNull();
    expect(exits[0]!.x).toBeGreaterThan(30);
    expect(exits[0]!.x).toBeLessThan(85);
  });

  it("can be left at any moment", () => {
    const { c, frame } = controller();
    let left = 0;
    c.onExit = () => left++;
    c.start("hard");
    frame(3);
    c.leave();
    expect(c.phase).toBe("off");
    expect(left).toBe(1);
    expect(c.hud()).toBeNull();
    c.leave();
    expect(left).toBe(1);
  });

  it("shows the result when the match ends, then rematches or leaves", () => {
    const { c, frame } = controller();
    c.start("elite");
    let frames = 0;
    while (c.phase === "running" && frames < 60 * 120) { frame(1); frames++; }
    expect(c.phase).toBe("result");
    expect(c.result?.outcome).toBe("lost");
    expect(c.result?.rounds).toEqual([0, 1]);
    const tick = c.view!.match.tick;
    frame(30);
    expect(c.view!.match.tick).toBe(tick);
    c.rematch();
    expect(c.phase).toBe("running");
    expect(c.result).toBeNull();
    expect(c.difficulty).toBe("elite");
    let exited = false;
    c.onExit = () => { exited = true; };
    c.leave();
    expect(exited).toBe(true);
  });

  it("forced QA controls reach the match", () => {
    const { c, frame } = controller();
    c.start("normal");
    frame(200);
    c.hold({ shield: true });
    frame(5);
    expect(c.view!.players[c.view!.slot].shieldUp).toBe(true);
  });
});
