import { describe, expect, it } from "vitest";
import {
  BODY_SPACING, BRISK_SPEED, STUCK, WALK_SPEED, applySeparation, clearOfBodies, clickPaceFor, hurryPaceFor, newStuckWatch, paceFor, segmentWalkable, separation, stepClearOfBodies, stepMover,
  stepMoverAvoiding, stepWalker, turnToward, watchProgress, type Mover, wrapAngle,
} from "./officeMotion";

describe("office motion", () => {
  it("turns the short way and clamps the step", () => {
    expect(turnToward(0, 1, 0.5)).toBeCloseTo(0.5);
    expect(turnToward(0, 1, 2)).toBeCloseTo(1);
    // From just below +π to just above -π is a tiny step across the seam.
    expect(turnToward(3.1, -3.1, 0.2)).toBeCloseTo(wrapAngle(-3.1));
    expect(turnToward(3.0, -3.0, 0.1)).toBeCloseTo(3.1);
  });

  it("walks a path to its end at the given speed and faces the travel direction", () => {
    const m: Mover = { x: 0, z: 0, heading: 0, path: [{ x: 2, z: 0 }, { x: 2, z: 3 }] };
    let total = 0;
    let arrived = false;
    let ticks = 0;
    let headingOnFirstLeg = NaN;
    while (!arrived && ticks < 1000) {
      const res = stepMover(m, WALK_SPEED, 1 / 60);
      total += res.moved;
      arrived = res.arrived;
      ticks += 1;
      if (m.x > 1 && m.x < 1.9 && m.z === 0) headingOnFirstLeg = m.heading;
    }
    expect(arrived).toBe(true);
    expect(m.x).toBeCloseTo(2);
    expect(m.z).toBeCloseTo(3);
    expect(total).toBeCloseTo(5);
    expect(ticks).toBeCloseTo(Math.ceil(5 / WALK_SPEED * 60), -1);
    // East = +x = heading π/2; south = +z = heading 0.
    expect(headingOnFirstLeg).toBeCloseTo(Math.PI / 2);
    expect(m.heading).toBeCloseTo(0);
    expect(m.path).toHaveLength(0);
  });

  it("does nothing without a path", () => {
    const m: Mover = { x: 1, z: 1, heading: 0.3, path: [] };
    expect(stepMover(m, WALK_SPEED, 0.1)).toEqual({ moved: 0, arrived: true });
    expect(m).toEqual({ x: 1, z: 1, heading: 0.3, path: [] });
  });

  it("consumes several waypoints in one large step", () => {
    const m: Mover = { x: 0, z: 0, heading: 0, path: [{ x: 0, z: 1 }, { x: 0, z: 2 }, { x: 0, z: 3 }] };
    const res = stepMover(m, 1, 2.5);
    expect(res.moved).toBeCloseTo(2.5);
    expect(res.arrived).toBe(false);
    expect(m.path).toHaveLength(1);
    expect(m.z).toBeCloseTo(2.5);
  });
});

describe("separation", () => {
  it("is zero when nobody is near and pushes away from a close body", () => {
    expect(separation({ x: 0, z: 0 }, 0, [{ x: 5, z: 5 }])).toEqual({ x: 0, z: 0 });
    const push = separation({ x: 0, z: 0 }, Math.PI / 2, [{ x: 0.3, z: 0 }]);
    expect(push.x).toBeLessThan(0);
  });
  it("adds a sidestep when someone stands straight ahead", () => {
    // Walking towards +z, someone 0.5 m ahead: the push has a sideways component.
    const push = separation({ x: 0, z: 0 }, 0, [{ x: 0, z: 0.5 }]);
    expect(Math.abs(push.x)).toBeGreaterThan(0.1);
  });
  it("only nudges onto walkable ground and reports spacing", () => {
    const m = { x: 0, z: 0, heading: 0, path: [] };
    applySeparation(m, { x: 1, z: 0 }, 0.1, () => false);
    expect(m.x).toBe(0);
    applySeparation(m, { x: 1, z: 0 }, 0.1, () => true);
    expect(m.x).toBeGreaterThan(0);
    expect(clearOfBodies({ x: 0, z: 0 }, [{ x: BODY_SPACING / 2, z: 0 }])).toBe(false);
    expect(clearOfBodies({ x: 0, z: 0 }, [{ x: BODY_SPACING * 2, z: 0 }])).toBe(true);
  });
  it("lets a figure pinned against someone step away even when others stand far off in that direction", () => {
    // Touching a colleague to the west; the rest of the office lies south-east, beyond the step.
    const from = { x: 0, z: 0 };
    const others = [{ x: -0.4, z: 0 }, { x: 5, z: 5 }, { x: 8, z: -2 }];
    expect(stepClearOfBodies({ x: 0.03, z: 0 }, from, others)).toBe(true);
    expect(stepClearOfBodies({ x: 0, z: 0.03 }, from, others)).toBe(true);
    // Never deeper into the one already touched, never into someone new.
    expect(stepClearOfBodies({ x: -0.03, z: 0 }, from, others)).toBe(false);
    expect(stepClearOfBodies({ x: 0.03, z: 0 }, from, [{ x: 0.5, z: 0 }])).toBe(false);
  });
  it("keeps two walkers crossing head-on apart", () => {
    const a = { x: 0, z: -3, heading: 0, path: [{ x: 0, z: 3 }] };
    const b = { x: 0.02, z: 3, heading: Math.PI, path: [{ x: 0.02, z: -3 }] };
    let closest = Infinity;
    for (let i = 0; i < 600; i += 1) {
      stepMoverAvoiding(a, 1.35, 1 / 60, [b], () => true);
      stepMoverAvoiding(b, 1.35, 1 / 60, [a], () => true);
      closest = Math.min(closest, Math.hypot(a.x - b.x, a.z - b.z));
    }
    expect(closest).toBeGreaterThan(0.45);
    // Both still reach their goals.
    expect(a.path).toHaveLength(0);
    expect(b.path).toHaveLength(0);
  });
});

const open = () => true;
const DT = 1 / 60;

describe("stepWalker", () => {
  it("lands exactly on the last waypoint and faces the way it walked", () => {
    for (const dt of [1 / 144, 1 / 60, 1 / 30, 0.1]) {
      const m: Mover = { x: 0, z: 0, heading: Math.PI / 2, path: [{ x: 3, z: 0 }, { x: 3, z: 2.37 }] };
      let ticks = 0;
      while (!stepWalker(m, WALK_SPEED, dt, [], open).arrived && ticks < 5000) ticks += 1;
      expect([m.x, m.z], `dt ${dt}`).toEqual([3, 2.37]);
      expect(m.heading, `dt ${dt}`).toBeCloseTo(0);
    }
  });

  it("turns before it walks instead of gliding sideways round a corner", () => {
    // Facing east, the route goes west: a U-turn.
    const m: Mover = { x: 0, z: 0, heading: Math.PI / 2, path: [{ x: -5, z: 0 }] };
    let sideways = 0;
    for (let i = 0; i < 120; i += 1) {
      const before = m.x;
      const { moved } = stepWalker(m, WALK_SPEED, DT, [], open);
      // Moving west while still facing away from west by more than 60°.
      if (Math.abs(wrapAngle(-Math.PI / 2 - m.heading)) > 1.05) sideways += Math.abs(m.x - before);
      expect(moved).toBeLessThanOrEqual(WALK_SPEED * DT + 1e-9);
    }
    expect(sideways).toBeLessThan(0.03);
    expect(m.heading).toBeCloseTo(-Math.PI / 2);
    expect(m.x).toBeLessThan(-2);
  });

  it("never steps onto blocked ground: it slides along a wall it is pushed against, or waits", () => {
    // A wall along z < 0; someone beside the walker pushes it towards the wall.
    const floor = (p: { x: number; z: number }) => p.z >= 0;
    const m: Mover = { x: 0, z: 0.05, heading: Math.PI / 2, path: [{ x: 6, z: 0.05 }] };
    const pusher = { x: 1.2, z: 0.75 };
    for (let i = 0; i < 400 && m.path.length > 0; i += 1) {
      stepWalker(m, WALK_SPEED, DT, [pusher], floor);
      expect(m.z).toBeGreaterThanOrEqual(0);
      expect(Math.hypot(m.x - pusher.x, m.z - pusher.z)).toBeGreaterThan(BODY_SPACING - 0.02);
    }
    expect([m.x, m.z]).toEqual([6, 0.05]);
  });

  it("never steps into anybody: with no way round it waits and says so", () => {
    // A corridor one body wide, someone standing in it.
    const corridor = (p: { x: number; z: number }) => Math.abs(p.z) <= 0.3;
    const m: Mover = { x: 0, z: 0, heading: Math.PI / 2, path: [{ x: 6, z: 0 }] };
    const body = { x: 3, z: 0 };
    let blocked = false;
    for (let i = 0; i < 600; i += 1) {
      const step = stepWalker(m, WALK_SPEED, DT, [body], corridor);
      blocked = step.blocked;
      expect(Math.hypot(m.x - body.x, m.z - body.z)).toBeGreaterThan(BODY_SPACING - 0.01);
    }
    expect(blocked).toBe(true);
    expect(m.x).toBeLessThan(3);
    expect(m.path).toHaveLength(1);
  });

  it("walks out of a seat and onto one although both lie inside a footprint", () => {
    // The chair's footprint covers x in [-0.5, 0.5]; a neighbour sits within arm's reach of the target seat.
    const floor = (p: { x: number; z: number }) => Math.abs(p.x) > 0.5 && Math.abs(p.x - 6) > 0.5;
    const m: Mover = { x: 0, z: 0, heading: 0, path: [{ x: 0.7, z: 0 }, { x: 5.3, z: 0 }, { x: 6, z: 0 }] };
    let ticks = 0;
    while (!stepWalker(m, WALK_SPEED, DT, [{ x: 6, z: 0.55 }], floor).arrived && ticks < 2000) ticks += 1;
    expect([m.x, m.z]).toEqual([6, 0]);
  });

  it("reports when steering carried it off its route", () => {
    // The straight line to the waypoint crosses a pillar the route went round.
    const pillar = (p: { x: number; z: number }) => !(p.x > 0.9 && p.x < 2 && Math.abs(p.z) < 0.3);
    const m: Mover = { x: 0.9, z: 0, heading: Math.PI / 2, path: [{ x: 3, z: 0 }] };
    const step = stepWalker(m, WALK_SPEED, DT, [], pillar);
    expect(step.offPath).toBe(true);
    expect(pillar(m)).toBe(true);
  });

  it("goes for the next waypoint once it is in plain view, never back to one it was pushed past", () => {
    const m: Mover = { x: 1.8, z: 0.4, heading: Math.PI / 2, path: [{ x: 2, z: 0 }, { x: 6, z: 0 }] };
    stepWalker(m, WALK_SPEED, DT, [{ x: 1.4, z: -0.3 }], open);
    expect(m.path).toEqual([{ x: 6, z: 0 }]);
  });
});

describe("segmentWalkable", () => {
  it("samples the first stretch of a line", () => {
    const wall = (p: { x: number; z: number }) => p.x < 1 || p.x > 1.2;
    expect(segmentWalkable({ x: 0, z: 0 }, { x: 0.9, z: 0 }, wall)).toBe(true);
    expect(segmentWalkable({ x: 0, z: 0 }, { x: 3, z: 0 }, wall)).toBe(false);
    // Only the first metres count: a wall far down the line is the route's business.
    expect(segmentWalkable({ x: -5, z: 0 }, { x: 3, z: 0 }, wall)).toBe(true);
  });
});

describe("paceFor", () => {
  it("strolls on short legs and walks briskly across the campus", () => {
    expect(paceFor(0)).toBe(WALK_SPEED);
    expect(paceFor(8)).toBe(WALK_SPEED);
    expect(paceFor(60)).toBe(BRISK_SPEED);
    expect(paceFor(17)).toBeGreaterThan(WALK_SPEED);
    expect(paceFor(17)).toBeLessThan(BRISK_SPEED);
    expect(paceFor(20)).toBeGreaterThan(paceFor(15));
  });
});

describe("hurryPaceFor", () => {
  it("is brisk on anything but the last steps, and never slower than the ordinary pace", () => {
    expect(hurryPaceFor(1)).toBe(WALK_SPEED);
    expect(hurryPaceFor(8)).toBe(BRISK_SPEED);
    expect(hurryPaceFor(40)).toBe(BRISK_SPEED);
    for (let m = 0; m < 40; m += 1) expect(hurryPaceFor(m)).toBeGreaterThanOrEqual(paceFor(m));
  });
});

describe("clickPaceFor", () => {
  it("jogs a long click-to-move route and settles to a walk before it arrives", () => {
    expect(clickPaceFor(60, 2, 4.4)).toBe(4.4);
    expect(clickPaceFor(22, 2, 4.4)).toBe(4.4);
    expect(clickPaceFor(7, 2, 4.4)).toBe(2);
    expect(clickPaceFor(0, 2, 4.4)).toBe(2);
    expect(clickPaceFor(14, 2, 4.4)).toBeGreaterThan(2);
    expect(clickPaceFor(14, 2, 4.4)).toBeLessThan(4.4);
    // Never a jump in pace: the change is spread over the metres in between.
    for (let m = 0; m < 30; m += 0.5) expect(Math.abs(clickPaceFor(m + 0.5, 2, 4.4) - clickPaceFor(m, 2, 4.4))).toBeLessThan(0.1);
  });

  it("crosses a campus in well under half the time a plain walk takes", () => {
    const time = (pace: (left: number) => number) => {
      const m: Mover = { x: 0, z: 0, heading: Math.PI / 2, path: [{ x: 70, z: 0 }] };
      let seconds = 0;
      while (seconds < 120 && !stepWalker(m, pace(70 - m.x), DT, [], open).arrived) seconds += DT;
      return seconds;
    };
    const walked = time(() => 2);
    const clicked = time((left) => clickPaceFor(left, 2, 4.4));
    expect(walked).toBeCloseTo(35, 0);
    expect(clicked).toBeLessThan(20);
    expect(clicked).toBeGreaterThan(70 / 4.4);
  });
});

describe("the stuck watch", () => {
  it("stays quiet while a figure makes progress, however slowly it queues", () => {
    const watch = newStuckWatch({ x: 0, z: 0 });
    let x = 0;
    for (let i = 0; i < 60 * 30; i += 1) {
      x += 0.34 * DT;
      expect(watchProgress(watch, { x, z: 0 }, DT)).toBe("ok");
    }
  });

  it("asks for a re-plan after 1.5 s without progress, twice, then for a rescue", () => {
    const watch = newStuckWatch({ x: 0, z: 0 });
    const verdicts: string[] = [];
    for (let i = 0; i < 60 * 6.2; i += 1) {
      // Shuffling on the spot is not progress.
      const verdict = watchProgress(watch, { x: Math.sin(i / 5) * 0.15, z: 0 }, DT);
      if (verdict !== "ok") verdicts.push(`${verdict}@${((i + 1) * DT).toFixed(1)}`);
    }
    // (Sixty frames of 1/60 s fall a hair short of a second, so each verdict comes a frame late.)
    expect(verdicts).toEqual(["replan@1.5", "replan@3.0", "rescue@4.5", "replan@6.1"]);
    expect(STUCK.maxReplans).toBe(2);
  });

  it("starts over with every unit of progress", () => {
    const watch = newStuckWatch({ x: 0, z: 0 });
    for (let i = 0; i < 80; i += 1) watchProgress(watch, { x: 0, z: 0 }, DT);
    expect(watchProgress(watch, { x: 0, z: 0 }, 1)).toBe("replan");
    expect(watch.replans).toBe(1);
    expect(watchProgress(watch, { x: STUCK.progressM, z: 0 }, DT)).toBe("ok");
    expect(watch).toMatchObject({ idleS: 0, replans: 0, x: STUCK.progressM });
  });
});
