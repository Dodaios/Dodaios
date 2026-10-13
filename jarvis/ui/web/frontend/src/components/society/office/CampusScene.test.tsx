import { afterEach, describe, expect, it } from "vitest";
import { act, createRoot, extend, type ReconcilerRoot } from "@react-three/fiber";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as THREE from "three";
import { Box3, type InstancedMesh, type Mesh, type Object3D } from "three";
import { AgentsDepartment, AgentsSlab } from "./AgentsFloorLook";
import { AgentsFloorAmbience } from "./AgentsFloorAmbience";
import { BuildingShell, FACADE } from "./BuildingShell";
import { CampusGround } from "./CampusGround";
import { DeskDressing } from "./DeskDressing";
import { DeskInstances } from "./DeskInstances";
import { buildHallLayout } from "./hallFloorLayout";
import { buildOfficeLayout, type OfficeAgentInput, type OfficeLayout, type OfficeTeamInput } from "./officeLayout";
import { FurniturePiece, MeetingChairs } from "./OfficeProps";
import { StaticBatch } from "./StaticBatch";
import { ToyFigure } from "./ToyFigure";
import { loadProfile, playerLook } from "./playerProfile";
import { RoomFloors, RoomSign, RoomWalls } from "./OfficeRooms";

/** Just enough of a WebGLRenderer for R3F to mount a scene graph without a GPU. */
function fakeRenderer(canvas: HTMLCanvasElement) {
  const noop = () => undefined;
  return {
    domElement: canvas,
    render: noop, setSize: noop, setPixelRatio: noop, setAnimationLoop: noop, dispose: noop,
    getPixelRatio: () => 1,
    shadowMap: { enabled: false, type: 0, needsUpdate: false },
    xr: { enabled: false, isPresenting: false, addEventListener: noop, removeEventListener: noop, setAnimationLoop: noop },
    outputColorSpace: "srgb", toneMapping: 0, toneMappingExposure: 1,
    info: { render: {}, memory: {} },
  };
}

// <Canvas> registers the three namespace; a bare root must do it itself.
extend(THREE);

let root: ReconcilerRoot<HTMLCanvasElement> | null = null;

async function mount(element: JSX.Element): Promise<Object3D> {
  const canvas = document.createElement("canvas");
  const current = createRoot(canvas);
  root = current;
  current.configure({
    // Test double: R3F only needs the renderer's shape here, nothing is drawn.
    gl: fakeRenderer(canvas) as unknown as NonNullable<Parameters<typeof current.configure>[0]>["gl"],
    frameloop: "never",
    size: { width: 100, height: 100, top: 0, left: 0 },
  });
  let captured: Object3D | null = null;
  await act(async () => {
    current.render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <group ref={(g) => { captured = g; }}>{element}</group>
      </QueryClientProvider>,
    );
  });
  if (!captured) throw new Error("the element did not mount");
  return captured;
}

afterEach(() => {
  root?.unmount();
  root = null;
});

const staff = (count: number): OfficeAgentInput[] => Array.from({ length: count }, (_, i) => ({
  agentId: `a${i + 1}`, name: `Agent ${i + 1}`, tier: i === 0 ? "lead" : "specialist", providerLabel: "Codex", state: "idle", createdMs: i,
}));
const teamsOf = (count: number, size: number): OfficeTeamInput[] => Array.from({ length: count }, (_, t) => ({
  id: `team-${t}`, name: `Team ${t}`, createdMs: t, members: Array.from({ length: size }, (_, i) => `a${2 + t * size + i}`),
}));

/**
 * What a frame costs: every visible mesh is a draw call (however many instances it holds), every one that casts a
 * shadow a second one in the shadow pass, and its triangles are drawn in each.
 */
function cost(node: Object3D): { meshes: number; casters: number; calls: number; triangles: number } {
  let meshes = 0, casters = 0, triangles = 0;
  node.traverseVisible((child) => {
    const mesh = child as Mesh;
    if (!mesh.isMesh) return;
    const own = (mesh.geometry.index ? mesh.geometry.index.count : mesh.geometry.getAttribute("position").count) / 3
      * ((mesh as unknown as InstancedMesh).isInstancedMesh ? (mesh as unknown as InstancedMesh).count : 1);
    meshes += 1;
    triangles += own;
    if (mesh.castShadow) { casters += 1; triangles += own; }
  });
  return { meshes, casters, calls: meshes + casters, triangles: Math.round(triangles) };
}

const noClick = () => undefined;
const STATION_KINDS = new Set(["spawnTerminal", "spawnPad", "receptionDesk", "teamBoard", "dressingMirror", "coffeeBar", "elevator", "studioBoard", "teamStand"]);

/** The floor's static dressing, mounted the way the scene mounts it; the agents floor's furniture goes through the batch. */
function Dressing({ layout, batch = layout.variant === "agents" }: { layout: OfficeLayout; batch?: boolean }) {
  const desks = layout.departments.flatMap((d) => d.desks);
  const table = layout.furniture.find((f) => f.kind === "meetingTable");
  const signs = layout.rooms.map((room) => <RoomSign key={room.id} room={room} label={room.kind} />);
  const studios = layout.departments.map((dept) => <AgentsDepartment key={dept.id} dept={dept} />);
  return (
    <>
      <AgentsSlab layout={layout} onFloorClick={noClick} />
      <BuildingShell layout={layout} />
      <AgentsFloorAmbience layout={layout} />
      <CampusGround layout={layout} />
      <RoomFloors rooms={layout.rooms} campus />
      <RoomWalls walls={layout.walls} />
      {desks.length > 0 && <DeskInstances desks={desks} agents={new Map()} zones={new Map(layout.departments.flatMap((d) => d.desks.map((desk) => [desk.id, d.tint] as const)))} />}
      {desks.length > 0 && <DeskDressing desks={desks} departments={layout.departments} floor="agents" />}
      {batch
        ? <>
          <StaticBatch signature={layout.furniture.map((f) => f.id).join()}>
            {signs}{studios}
            {layout.furniture.filter((f) => !STATION_KINDS.has(f.kind)).map((item) => <FurniturePiece key={item.id} item={item} />)}
            {table && <MeetingChairs table={table} />}
          </StaticBatch>
          {layout.furniture.filter((f) => STATION_KINDS.has(f.kind)).map((item) => <FurniturePiece key={item.id} item={item} merged />)}
        </>
        : <>
          {signs}{studios}
          {layout.furniture.map((item) => <FurniturePiece key={item.id} item={item} />)}
          {table && <MeetingChairs table={table} />}
        </>}
    </>
  );
}

describe("campus scene", () => {
  it("mounts the agents floor's dressing for 5, 15 and 40 people, and the Level Hall's, within its budget", async () => {
    const floors: [string, OfficeLayout][] = [
      ["5", buildOfficeLayout(staff(5))],
      ["15", buildOfficeLayout(staff(15), { teams: teamsOf(3, 4) })],
      ["40", buildOfficeLayout(staff(40), { teams: teamsOf(8, 4) })],
      ["hall", buildHallLayout()],
    ];
    const costs: Record<string, ReturnType<typeof cost>> = {};
    for (const [name, layout] of floors) {
      const group = await mount(<Dressing layout={layout} />);
      costs[name] = cost(group);
      root?.unmount();
      root = null;
    }
    // The whole static floor — slab, building, planting, fittings, rooms, studios, desks — in a few hundred draw
    // calls, shadow pass included. (Without a GPU no texture exists; in a browser each textured material adds
    // a merged mesh of its own, a few dozen on this floor.)
    expect(costs["5"].calls).toBeLessThan(520);
    expect(costs["15"].calls).toBeLessThan(540);
    expect(costs["40"].calls).toBeLessThan(600);
    // Studios, desks, fittings and trees are merged or instanced: eight teams cost little more than none.
    expect(costs["40"].meshes - costs["5"].meshes).toBeLessThan(60);
    // Triangles, both passes: what grows with the roster is the desks and their chairs.
    expect(costs["5"].triangles).toBeLessThan(560_000);
    expect(costs["15"].triangles).toBeLessThan(700_000);
    expect(costs["40"].triangles).toBeLessThan(1_050_000);
    expect(costs.hall.calls).toBeLessThan(costs["5"].calls);
  });

  it("draws the furniture in a fraction of the calls it takes piece by piece", async () => {
    const layout = buildOfficeLayout(staff(15), { teams: teamsOf(3, 4) });
    const loose = cost(await mount(<Dressing layout={layout} batch={false} />));
    root?.unmount();
    const merged = cost(await mount(<Dressing layout={layout} />));
    expect(merged.calls).toBeLessThan(loose.calls / 3);
    // The same shapes: merging changes how they are drawn, not what is drawn.
    expect(merged.triangles).toBeLessThanOrEqual(loose.triangles);
    expect(merged.triangles).toBeGreaterThan(loose.triangles * 0.6);
  });

  it("keeps the ground flat and inside the slab, and a studio's wall inside its studio", async () => {
    const layout = buildOfficeLayout(staff(12), { teams: teamsOf(2, 3) });
    const ground = await mount(<CampusGround layout={layout} />);
    ground.updateMatrixWorld(true);
    const box = new Box3().setFromObject(ground);
    // Everything is either flat on the floor or the atrium's ring of light (band, lamp and rods) above every head.
    let overhead = 0;
    ground.traverse((child) => {
      if (!(child as Mesh).isMesh) return;
      const own = new Box3().setFromObject(child);
      if (own.min.y > 2.6) { overhead += 1; expect(own.max.y).toBeLessThanOrEqual(3.4 + 1e-6); return; }
      expect(own.min.y).toBeGreaterThan(0.001);
      expect(own.max.y).toBeLessThan(0.02);
    });
    expect(overhead).toBe(3);
    expect(box.min.x).toBeGreaterThanOrEqual(layout.bounds.minX);
    expect(box.max.x).toBeLessThanOrEqual(layout.bounds.maxX);
    expect(box.min.z).toBeGreaterThanOrEqual(layout.bounds.minZ);
    expect(box.max.z).toBeLessThanOrEqual(layout.bounds.maxZ);
    root?.unmount();
    for (const dept of layout.departments) {
      const studio = await mount(<AgentsDepartment dept={dept} />);
      studio.updateMatrixWorld(true);
      const own = new Box3().setFromObject(studio);
      expect(own.min.x, dept.id).toBeGreaterThanOrEqual(dept.minX - 0.01);
      expect(own.max.x, dept.id).toBeLessThanOrEqual(dept.maxX + 0.01);
      expect(own.min.z, dept.id).toBeGreaterThanOrEqual(dept.minZ - 0.01);
      expect(own.max.z, dept.id).toBeLessThanOrEqual(dept.maxZ + 0.01);
      root?.unmount();
    }
    root = null;
  });

  it("builds the building's edges on the slab's edge: a window wall and a balustrade per side, the far sides' walls shown", async () => {
    const layout = buildOfficeLayout(staff(5));
    const shell = await mount(<BuildingShell layout={layout} />);
    shell.updateMatrixWorld(true);
    const { minX, maxX, minZ, maxZ } = layout.bounds;
    // Everything the person could bump into stays out of the walkable floor: nothing of a wall or a rail lies inside it below head height.
    const inside = (child: Object3D) => {
      const box = new Box3().setFromObject(child);
      return box.min.x > layout.floor.minX && box.max.x < layout.floor.maxX && box.min.z > layout.floor.minZ && box.max.z < layout.floor.maxZ && box.min.y < 2;
    };
    const visible: number[] = [];
    let walls = 0;
    shell.traverse((child) => {
      const box = new Box3().setFromObject(child);
      // A window wall's group: as tall as the façade, on the slab, as long as one of its sides.
      if (child.type !== "Group" || child.children.length !== 5) return;
      if (Math.abs(box.max.y - (FACADE.h + 0.1)) > 0.01) return;
      walls += 1;
      expect(inside(child)).toBe(false);
      expect(box.min.x).toBeGreaterThanOrEqual(minX - 0.01);
      expect(box.max.x).toBeLessThanOrEqual(maxX + 0.01);
      expect(box.min.z).toBeGreaterThanOrEqual(minZ - 0.01);
      expect(box.max.z).toBeLessThanOrEqual(maxZ + 0.01);
      if (child.parent?.visible) visible.push(Math.round((box.min.x + box.max.x) / 2) + Math.round((box.min.z + box.max.z) / 2) * 1000);
    });
    expect(walls).toBe(4);
    // The home view looks from the south-east: the north and the west wall stand, the other two sides show the balustrade.
    expect(visible).toHaveLength(2);
  });

  it("tags every room wall run for the camera's cutaway", async () => {
    const layout = buildOfficeLayout(staff(5));
    const group = await mount(<RoomWalls walls={layout.walls} />);
    const tagged: unknown[] = [];
    group.traverse((child) => { if (child.userData.officeWall) tagged.push(child.userData.officeWall); });
    expect(tagged).toHaveLength(layout.walls.length);
    expect(new Set(tagged).size).toBe(layout.walls.length);
  });
});

describe("a figure", () => {
  const still = { current: { mode: "idle" as const, speed: 0 } };

  it("is a few dozen draw calls: its rigid head, torso and arm halves are merged, only the legs are parts of their own", async () => {
    const figure = cost(await mount(<ToyFigure look={playerLook(loadProfile())} drive={still} paused />));
    expect(figure.meshes).toBeLessThanOrEqual(22);
    // What still casts: head, torso, pelvis, each half of an arm and each segment of a leg.
    expect(figure.casters).toBeLessThanOrEqual(14);
    // Both passes together.
    expect(figure.triangles).toBeLessThan(40_000);
  });

  it("keeps its shape when it is merged: the same triangles in the same place, for a bare arm, a sleeve and a held thing", async () => {
    const base = playerLook(loadProfile());
    const looks = [base, { ...base, outfit: "tee" as const }, { ...base, outfit: "suit" as const }];
    for (const look of looks) {
      const group = await mount(<ToyFigure look={look} drive={still} paused holding={<mesh><boxGeometry args={[0.05, 0.05, 0.05]} /></mesh>} />);
      group.updateMatrixWorld(true);
      const merged = { triangles: 0, box: new Box3() }, parts = { triangles: 0, box: new Box3() };
      let loose = 0;
      group.traverse((child) => {
        const mesh = child as Mesh;
        if (!mesh.isMesh) return;
        if (!mesh.userData.staticBatched) { loose += 1; return; }
        const into = mesh.visible ? merged : parts;
        into.triangles += (mesh.geometry.index ? mesh.geometry.index.count : mesh.geometry.getAttribute("position").count) / 3;
        // Measured vertex by vertex: a turned part's own box would overstate it.
        into.box.union(new Box3().setFromObject(mesh, true));
      });
      expect(merged.triangles, look.outfit).toBe(parts.triangles);
      for (const axis of ["x", "y", "z"] as const) {
        expect(merged.box.min[axis], look.outfit).toBeCloseTo(parts.box.min[axis], 5);
        expect(merged.box.max[axis], look.outfit).toBeCloseTo(parts.box.max[axis], 5);
      }
      // Outside every batch: the pelvis, three segments of each leg with a sole, and what the hand holds.
      expect(loose, look.outfit).toBeLessThanOrEqual(12);
      root?.unmount();
      root = null;
    }
  });
});
