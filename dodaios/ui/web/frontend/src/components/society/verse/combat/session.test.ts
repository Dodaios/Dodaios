// @vitest-environment node
import { describe, expect, it } from "vitest";
import { cameraPose, cameraRigFor, crosshairRadiusPx, resolveAim } from "./camera";
import { idleControl } from "./input";
import { createLocalDuel } from "./session";
import { step } from "./sim";
import { liveMatch, place } from "./testing";
import { DEFAULT_TUNING, withTuning } from "./tuning";
import { buildView } from "./view";
import { makeInput } from "./input";
import type { CombatEvent } from "./types";

describe("local duel session", () => {
  it("plays a whole match against the bot and reports it", () => {
    const duel = createLocalDuel({ difficulty: "normal", seed: 3 });
    const events: CombatEvent[] = [];
    let frames = 0;
    let sawHud = false;
    while (!duel.finished && frames < 60 * 60 * 6) {
      const { view, events: ev } = duel.frame(16.7, idleControl());
      events.push(...ev);
      frames++;
      if (view?.hud) {
        sawHud = true;
        expect(view.hud.heat).toBeGreaterThanOrEqual(0);
        expect(view.hud.heat).toBeLessThanOrEqual(1);
        expect(view.hud.shieldEnergy).toBeLessThanOrEqual(1);
        expect(view.players).toHaveLength(2);
      }
    }
    expect(sawHud).toBe(true);
    expect(duel.finished).toBe(true);
    // Standing still does not win duels.
    expect(duel.result?.outcome).toBe("lost");
    expect(duel.result?.rounds).toEqual([0, 2]);
    const types = new Set(events.map((e) => e.type));
    for (const t of ["countdown", "round_start", "shot", "hit", "death", "round_end", "match_end"] as const) expect(types.has(t), t).toBe(true);
    duel.dispose();
  });

  it("can be left at any time", () => {
    const duel = createLocalDuel({ difficulty: "elite", seed: 4 });
    for (let i = 0; i < 60; i++) duel.frame(16.7, idleControl());
    duel.forfeit();
    for (let i = 0; i < 10 && !duel.finished; i++) duel.frame(16.7, idleControl());
    expect(duel.finished).toBe(true);
    expect(duel.result?.outcome).toBe("lost");
    expect(duel.result?.reason).toBe("forfeit");
  });

  it("runs over a laggy link too", () => {
    const duel = createLocalDuel({ difficulty: "hard", seed: 5, latencyMs: 60, jitterMs: 20, loss: 0.05 });
    let frames = 0;
    while (!duel.finished && frames < 60 * 60 * 6) { duel.frame(16.7, idleControl()); frames++; }
    expect(duel.finished).toBe(true);
    expect(duel.result?.reason).toBe("rounds");
  });
});

describe("camera hooks", () => {
  it("converges the blaster on what the crosshair covers", () => {
    const exact = withTuning(DEFAULT_TUNING, { blaster: { hipSpreadDeg: 0, moveSpreadHipDeg: 0 } });
    const { ctx, state } = liveMatch({ tuning: exact });
    const s = place(state, { x: 38.8, z: 10 }, { x: 40.5, z: 27 });
    const view = buildView(ctx, s, s, 1, 0, [], "playing");
    const me = view.players[0];
    const target = view.players[1];
    const rig = cameraRigFor(me);
    // Look from the shoulder camera at the target's chest.
    const pose = cameraPose({ ...me, yaw: Math.atan2(target.x - me.x, target.z - me.z), pitch: 0 }, rig);
    const dir = { x: target.x - pose.position.x, y: 1.2 - pose.position.y, z: target.z - pose.position.z };
    const aim = resolveAim(ctx, view, pose.position, dir);
    expect(aim.target).toBe("player");
    // Fire along the solution: it hits.
    let st = s;
    let hit = false;
    for (let i = 0; i < 40 && !hit; i++) {
      const res = step(st, [makeInput(i, { ...idleControl(aim.yaw, aim.pitch), fire: i === 0 }), null], ctx);
      st = res.state;
      hit = res.events.some((e) => e.type === "hit" && e.target === 1);
    }
    expect(hit).toBe(true);
  });

  it("sizes the crosshair from the spread and the field of view", () => {
    expect(crosshairRadiusPx(1.6, 70, 1000)).toBeGreaterThan(crosshairRadiusPx(0.3, 70, 1000));
    expect(crosshairRadiusPx(1, 50, 1000)).toBeGreaterThan(crosshairRadiusPx(1, 70, 1000));
  });
});
