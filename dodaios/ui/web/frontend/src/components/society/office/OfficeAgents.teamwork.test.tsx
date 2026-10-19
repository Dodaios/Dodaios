import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, createRoot, extend, type ReconcilerRoot, type RootState } from "@react-three/fiber";
import * as THREE from "three";
import { OfficeAgents, type WalkerContext } from "./OfficeAgents";
import type { AgentRunState, SocietyAgent } from "../data";
import { allDesks, seatOf, type OfficeLayout } from "./officeLayout";
import { buildNavGrid, isWalkable } from "./officeNav";
import { PERSON_CROWD_M, PERSON_SPACE_M, SpotBook } from "./officeBehavior";
import { huddlePlaces, studioOfTeam } from "./officeTeams";
import { player, useOfficeStore } from "./officeStore";
import { emptyRound, useTeamwork, type Handoff } from "./teamwork";
import { agentPositions, seatedAtDesk, walkerDebug } from "./walkerRegistry";
import { campusOf, type Campus } from "./officeFixtures";

vi.mock("@react-three/drei", async (original) => ({
  ...await original<typeof import("@react-three/drei")>(),
  // The walkers' choreography is under test, not their models or their DOM labels.
  useGLTF: () => ({ scene: new THREE.Group() }),
  Html: () => null,
}));

// The little symbol pets behind the agents need their shipped models; they are not what is tested here.
vi.mock("../companion/AgentFollower", () => ({ AgentFollower: () => null }));
// The store is driven by hand here; the hook that feeds it from the network has its own tests.
vi.mock("./useTeamRounds", () => ({ useTeamRounds: () => undefined }));

extend(THREE);
let root: ReconcilerRoot<HTMLCanvasElement> | null = null;
const originalPlayer = { ...player };

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(1_000_000);
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
  vi.spyOn(console, "warn").mockImplementation(() => undefined);
  // The person stands far away from everything that happens.
  Object.assign(player, { x: 500, z: 500, heading: 0, path: [], moving: false });
  useOfficeStore.setState({ summons: {} });
  useTeamwork.getState().reset();
});

afterEach(async () => {
  await act(async () => root?.unmount());
  root = null;
  Object.assign(player, originalPlayer);
  useTeamwork.getState().reset();
  agentPositions.clear();
  seatedAtDesk.clear();
  walkerDebug.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

/** R3F scene graph test double; no browser, GPU or network. */
function fakeRenderer(canvas: HTMLCanvasElement) {
  const noop = () => undefined;
  return {
    domElement: canvas, render: noop, setSize: noop, setPixelRatio: noop, setAnimationLoop: noop, dispose: noop,
    getPixelRatio: () => 1, shadowMap: { enabled: false, type: 0, needsUpdate: false },
    xr: { enabled: false, isPresenting: false, addEventListener: noop, removeEventListener: noop, setAnimationLoop: noop },
    outputColorSpace: "srgb", toneMapping: 0, toneMappingExposure: 1,
    info: { render: {}, memory: {} },
  };
}

function societyAgents(campus: Campus, states: Record<string, AgentRunState> = {}): Map<string, SocietyAgent> {
  return new Map(campus.roster.map((a) => [a.agentId, {
    agentId: a.agentId, name: a.name, tier: "specialist", state: states[a.agentId] ?? "idle", figure: null,
    palette: { primary: "#f2a65a" }, provider: "", chatSessionId: null, checkpoint: "desk",
  } as unknown as SocietyAgent]));
}

async function mount(campus: Campus) {
  const canvas = document.createElement("canvas");
  const current = createRoot(canvas);
  root = current;
  let state!: RootState;
  current.configure({
    gl: fakeRenderer(canvas) as unknown as NonNullable<Parameters<typeof current.configure>[0]>["gl"],
    frameloop: "never", size: { width: 100, height: 100, top: 0, left: 0 },
    onCreated: (value) => { state = value; },
  });
  const book = new SpotBook();
  let agents = societyAgents(campus);
  let layout: OfficeLayout = campus.layout;
  let grid = campus.grid;
  const context = (): WalkerContext => {
    const desks = allDesks(layout);
    return {
      layout, grid, book, spawn: layout.arrival,
      colleagues: () => desks.filter((d) => d.agentId && agents.get(d.agentId)?.state === "working").map((d) => ({ agentId: d.agentId as string, desk: d })),
    };
  };
  let ctx = context();
  const render = async () => {
    await act(async () => {
      current.render(
        <OfficeAgents agents={agents} desks={allDesks(layout)} ctx={ctx} newcomers={new Set()} awake reduced={false} selectedId={null} onSelect={() => undefined} />,
      );
    });
  };
  await render();
  let time = 0;
  let closest = Infinity;
  /** Run the office for `seconds`, 30 frames each; keeps the smallest gap between any two figures on the move. */
  const run = async (seconds: number) => {
    await act(async () => {
      for (let i = 0; i < seconds * 30; i += 1) {
        time += 1000 / 30;
        vi.setSystemTime(1_000_000 + time);
        // R3F takes the frame time in seconds.
        state.advance(time / 1000);
        for (const a of walkerDebug.values()) {
          if (a.phase !== "travel") continue;
          for (const b of walkerDebug.values()) {
            if (a.id !== b.id) closest = Math.min(closest, Math.hypot(a.at.x - b.at.x, a.at.z - b.at.z));
          }
        }
      }
    });
  };
  return {
    run, book,
    closest: () => closest,
    walker: (id: string) => walkerDebug.get(id)!,
    setStates: async (states: Record<string, AgentRunState>) => { agents = societyAgents(campus, states); await render(); },
    swapFloor: async (next: Campus) => { layout = next.layout; grid = buildNavGrid(next.layout); book.retain(new Set(layout.spots.map((s) => s.id))); ctx = context(); await render(); },
    grid: () => grid,
  };
}

const TEAM = "team-0";

describe("teamwork on the floor", () => {
  it("gathers a team's free members at their studio board while its round runs, and sends them back when it ends", async () => {
    const campus = campusOf(12, [5]);
    const office = await mount(campus);
    const studio = studioOfTeam(campus.layout, TEAM)!;
    const members = studio.members;
    const places = huddlePlaces(campus.layout, campus.grid, studio);
    await office.run(1);
    for (const id of members) expect(office.walker(id)).toMatchObject({ team: TEAM, role: "none" });
    expect(members.every((id) => office.walker(id).plan !== "huddle" || office.walker(id).phase === "dwell")).toBe(true);

    // A round opens; one member is working on something else.
    await office.setStates({ [members[4]]: "working" });
    act(() => useTeamwork.getState().setRound({ ...emptyRound(TEAM), running: true, members: [...members], loaded: true }));
    await office.run(40);
    const free = members.slice(0, 4);
    for (const id of free) {
      const w = office.walker(id);
      expect(w, id).toMatchObject({ plan: "huddle", phase: "dwell", role: "gather" });
      const place = places.find((p) => p.id === w.spot)!;
      expect(Math.hypot(w.at.x - place.x, w.at.z - place.z), id).toBeLessThan(1e-6);
    }
    expect(new Set(free.map((id) => office.walker(id).spot)).size).toBe(4);
    // The busy member never left its screen.
    const seat = seatOf(allDesks(campus.layout).find((d) => d.agentId === members[4])!);
    expect(office.walker(members[4])).toMatchObject({ plan: "work", role: "busy", at: { x: seat.x, z: seat.z } });

    // The member contributing now reads "working" and stays at the board, as the speaker.
    act(() => useTeamwork.getState().setRound({ ...useTeamwork.getState().rounds[TEAM], speakerId: members[1] }));
    await office.setStates({ [members[4]]: "working", [members[1]]: "working" });
    await office.run(12);
    expect(office.walker(members[1])).toMatchObject({ plan: "huddle", phase: "dwell", role: "speaker" });

    // The round settles: everyone goes back to their own desk first.
    act(() => useTeamwork.getState().setRound({ ...useTeamwork.getState().rounds[TEAM], running: false, speakerId: null }));
    await office.setStates({ [members[4]]: "working" });
    await office.run(1);
    for (const id of free) expect(office.walker(id), id).toMatchObject({ plan: "desk", role: "none" });
    await office.run(30);
    for (const id of free) {
      const own = seatOf(allDesks(campus.layout).find((d) => d.agentId === id)!);
      const w = office.walker(id);
      if (w.plan === "desk") expect([w.at.x, w.at.z], id).toEqual([own.x, own.z]);
    }
    // On the way there and back nobody walked through anybody, and nobody had to be placed.
    expect(office.closest()).toBeGreaterThan(0.5);
    expect(members.reduce((n, id) => n + office.walker(id).rescues, 0)).toBe(0);
  });

  it("makes room when the person walks into the group at the board, and takes no place on the person's toes", async () => {
    const campus = campusOf(12, [5]);
    const office = await mount(campus);
    const studio = studioOfTeam(campus.layout, TEAM)!;
    const places = huddlePlaces(campus.layout, campus.grid, studio);
    // The person already stands on the best place when the round opens.
    Object.assign(player, { x: places[0].x, z: places[0].z });
    act(() => useTeamwork.getState().setRound({ ...emptyRound(TEAM), running: true, members: [...studio.members], loaded: true }));
    await office.run(40);
    const gap = (id: string) => Math.hypot(office.walker(id).at.x - player.x, office.walker(id).at.z - player.z);
    for (const id of studio.members) {
      expect(office.walker(id), id).toMatchObject({ plan: "huddle", phase: "dwell" });
      expect(gap(id), id).toBeGreaterThanOrEqual(PERSON_SPACE_M - 0.01);
    }
    // Now the person steps right up to one of them.
    const neighbour = studio.members[2];
    const was = office.walker(neighbour).spot;
    Object.assign(player, { x: office.walker(neighbour).at.x + 0.7, z: office.walker(neighbour).at.z });
    expect(gap(neighbour)).toBeLessThan(PERSON_CROWD_M);
    await office.run(12);
    expect(office.walker(neighbour)).toMatchObject({ plan: "huddle", phase: "dwell" });
    expect(office.walker(neighbour).spot).not.toBe(was);
    expect(gap(neighbour)).toBeGreaterThanOrEqual(PERSON_SPACE_M - 0.01);
    // Everybody still has a place of their own, more than a metre from the next.
    const at = studio.members.map((id) => office.walker(id).at);
    for (const [i, p] of at.entries()) for (const q of at.slice(i + 1)) expect(Math.hypot(p.x - q.x, p.z - q.z)).toBeGreaterThan(1);
  });

  it("hurries a working agent back to its screen, at the pace the walker reports", async () => {
    const campus = campusOf(12, [5]);
    const office = await mount(campus);
    // Idle life spreads the floor out; then an agent away from its desk gets work.
    await office.run(40);
    const desks = allDesks(campus.layout);
    const away = campus.roster.map((a) => a.agentId).filter((id) => {
      const seat = seatOf(desks.find((d) => d.agentId === id)!);
      return Math.hypot(office.walker(id).at.x - seat.x, office.walker(id).at.z - seat.z) > 8;
    });
    expect(away.length).toBeGreaterThan(0);
    const id = away[0];
    const seat = seatOf(desks.find((d) => d.agentId === id)!);
    await office.setStates({ [id]: "working" });
    await office.run(2);
    const start = office.walker(id);
    expect(start).toMatchObject({ plan: "work", phase: "travel" });
    const metres = start.remainingM + start.walkS * start.speed;
    // By its own clock it walks briskly: well above the stroll, never above the brisk pace.
    expect(start.speed).toBeGreaterThan(1.5);
    expect(start.speed).toBeLessThanOrEqual(2.1 + 1e-6);
    // And it is seated within the time that pace gives, plus the turns.
    await office.run(Math.ceil(metres / 1.6) + 2);
    expect(office.walker(id)).toMatchObject({ plan: "work", phase: "dwell", at: { x: seat.x, z: seat.z }, speed: 0, walkS: 0 });
  });

  it("walks a message from its sender to the receiver, and delivers it once", async () => {
    const campus = campusOf(12, [5]);
    const office = await mount(campus);
    const studio = studioOfTeam(campus.layout, TEAM)!;
    const receiver = studio.members[0];
    const sender = campus.roster.find((a) => !studio.members.includes(a.agentId))!.agentId;
    await office.setStates({ [receiver]: "working" });
    await office.run(1);
    const handoff: Handoff = {
      id: "ev-1", from: sender, to: receiver, toName: "Agent 0", text: "Here are the numbers you asked for.", msgType: "ANSWER",
      atMs: Date.now(), phase: "queued", untilMs: Date.now() + 90_000,
    };
    act(() => useTeamwork.getState().addHandoff(handoff));
    await office.run(1);
    expect(office.walker(sender)).toMatchObject({ plan: "handoff", with: receiver });
    // It arrives beside the receiver's chair and stays a moment.
    let delivered = false;
    for (let i = 0; i < 60 && !delivered; i += 1) {
      await office.run(1);
      delivered = useTeamwork.getState().handoffs[0]?.phase === "delivering";
    }
    expect(delivered).toBe(true);
    const seat = seatOf(allDesks(campus.layout).find((d) => d.agentId === receiver)!);
    const at = office.walker(sender).at;
    // Beside the chair, or a step away when both places beside it are taken.
    expect(Math.hypot(at.x - seat.x, at.z - seat.z)).toBeLessThan(1.7);
    expect(Math.hypot(at.x - seat.x, at.z - seat.z)).toBeGreaterThan(0.6);
    // The receiver kept working at its screen throughout.
    expect(office.walker(receiver)).toMatchObject({ plan: "work", at: { x: seat.x, z: seat.z } });
    await office.run(10);
    expect(useTeamwork.getState().handoffs).toEqual([]);
    expect(office.walker(sender).plan).not.toBe("handoff");
  });

  it("keeps a working sender at its screen: the message is not walked over", async () => {
    const campus = campusOf(12, [5]);
    const office = await mount(campus);
    const [a, b] = studioOfTeam(campus.layout, TEAM)!.members;
    await office.setStates({ [a]: "working" });
    await office.run(1);
    act(() => useTeamwork.getState().addHandoff({ id: "ev-2", from: a, to: b, toName: "Agent 1", text: "Take this over", msgType: "ASSIGN", atMs: Date.now(), phase: "queued", untilMs: Date.now() + 90_000 }));
    await office.run(5);
    expect(office.walker(a).plan).toBe("work");
    expect(useTeamwork.getState().handoffs[0].phase).toBe("queued");
  });

  it("keeps everyone on their feet when the floor plan is rebuilt under them", async () => {
    const before = campusOf(14, [5]);
    const office = await mount(before);
    // Let the idle floor spread out, then build a second team's studio mid-walk.
    await office.run(25);
    const after = campusOf(14, [5, 5]);
    await office.swapFloor(after);
    await office.run(60);
    const grid = office.grid();
    for (const agent of after.roster) {
      const w = office.walker(agent.agentId);
      expect(w.plan, agent.agentId).not.toBeNull();
      // Standing people stand on the floor; seated ones on a seat that exists on the new plan.
      const seated = w.phase === "dwell" && ["desk", "couch", "beanbag", "meeting", "work", "nap"].includes(w.plan!);
      if (w.phase === "dwell" && !seated) expect(isWalkable(grid, w.at), `${agent.agentId} ${w.plan}`).toBe(true);
      if (w.plan === "desk" && w.phase === "dwell") {
        const own = seatOf(allDesks(after.layout).find((d) => d.agentId === agent.agentId)!);
        expect([w.at.x, w.at.z], agent.agentId).toEqual([own.x, own.z]);
      }
      expect(w.team, agent.agentId).toBe(after.teams.find((t) => t.members.includes(agent.agentId))?.id ?? null);
    }
  });
});
