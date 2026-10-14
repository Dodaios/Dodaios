/**
 * The coding floor's long shared tables. Each bench of the layout — two rows
 * of desk slots facing each other — is one continuous white-oak table on dark
 * steel A-frames, with a low felt screen in the team's colour down its spine.
 * Every seat keeps what a desk had: a monitor on an arm (the live terminal is
 * drawn on its screen, exactly where it was), a keyboard and a task chair
 * whose seat is upholstered in the team's felt.
 *
 * Every repeated part is one instanced mesh per neighbourhood; the slots and
 * their footprints are the layout's, so seating and navigation are unchanged.
 */
import { useEffect, useLayoutEffect, useMemo, useRef } from "react";
import { BufferGeometry, Euler, InstancedMesh, Matrix4, MeshStandardMaterial, PlaneGeometry, Quaternion, Vector3, type Material } from "three";
import { RoundedBoxGeometry } from "three-stdlib";
import type { SocietyAgent } from "../data";
import { CHAIR_MAT, TASK_CHAIR_PARTS, type ChairFinish } from "./OfficeChairs";
import { GEO, MAT, screenMaterial } from "./OfficeFurniture";
import { DESK_SIZE, type DeskSlot } from "./officeLayout";
import { CODING_SCENE, type TeamColours } from "./officePalette";
import type { ScreenFace } from "./screenTextures";

const TM = {
  top: new MeshStandardMaterial({ color: CODING_SCENE.table.top, roughness: 0.5 }),
  edge: new MeshStandardMaterial({ color: CODING_SCENE.table.edge, roughness: 0.5 }),
  leg: new MeshStandardMaterial({ color: CODING_SCENE.table.leg, roughness: 0.4, metalness: 0.5 }),
  spine: new MeshStandardMaterial({ color: CODING_SCENE.table.spine, roughness: 0.5, metalness: 0.3 }),
  chairFrame: new MeshStandardMaterial({ color: "#2a2c30", roughness: 0.45, metalness: 0.2 }),
};

/** A table: one bench's slots, its centre, length along x and depth across. */
export interface LongTable { key: string; x: number; z: number; length: number; depth: number }

/** One long table per bench of desk slots ("<dept>:<bench>:<facing>:<col>"). Pure. */
export function longTables(desks: readonly DeskSlot[]): LongTable[] {
  const benches = new Map<string, DeskSlot[]>();
  for (const desk of desks) {
    if (desk.size) continue;
    const key = desk.id.split(":").slice(0, -2).join(":");
    benches.set(key, [...(benches.get(key) ?? []), desk]);
  }
  return [...benches.entries()].map(([key, slots]) => {
    const xs = slots.map((s) => s.x), zs = slots.map((s) => s.z);
    const minX = Math.min(...xs) - DESK_SIZE.w / 2, maxX = Math.max(...xs) + DESK_SIZE.w / 2;
    const minZ = Math.min(...zs) - DESK_SIZE.d / 2, maxZ = Math.max(...zs) + DESK_SIZE.d / 2;
    return { key, x: (minX + maxX) / 2, z: (minZ + maxZ) / 2, length: maxX - minX, depth: maxZ - minZ };
  });
}

const _q = new Quaternion(), _e = new Euler(), _p = new Vector3(), _s = new Vector3();
function compose(position: [number, number, number], scale: [number, number, number], rotY = 0): Matrix4 {
  return new Matrix4().compose(_p.set(...position), _q.setFromEuler(_e.set(0, rotY, 0)), _s.set(...scale));
}

function seatMatrix(desk: DeskSlot, local: [number, number, number], scale: [number, number, number] = [1, 1, 1]): Matrix4 {
  const turn = desk.facing === "north" ? 0 : Math.PI;
  return compose([desk.x, 0, desk.z], [1, 1, 1], turn).multiply(compose(local, scale));
}

function InstancedParts({ geometry, material, matrices, cast = true }: {
  geometry: BufferGeometry; material: Material; matrices: readonly Matrix4[]; cast?: boolean;
}) {
  const ref = useRef<InstancedMesh>(null);
  useLayoutEffect(() => {
    const mesh = ref.current;
    if (!mesh) return;
    matrices.forEach((m, i) => mesh.setMatrixAt(i, m));
    mesh.count = matrices.length;
    mesh.instanceMatrix.needsUpdate = true;
    mesh.computeBoundingSphere();
  }, [matrices]);
  if (matrices.length === 0) return null;
  // Remount when the count changes: an instanced mesh cannot grow in place.
  return <instancedMesh key={matrices.length} ref={ref} args={[geometry, material, matrices.length]} castShadow={cast} receiveShadow frustumCulled={false} />;
}

const TOP = new RoundedBoxGeometry(1, 1, 1, 1, 0.02);
const MONITOR = new RoundedBoxGeometry(0.72, 0.43, 0.022, 1, 0.012);
const SCREEN = new PlaneGeometry(0.66, 0.38);
const FACES: ScreenFace[] = ["working", "idle", "waiting", "paused", "empty"];
const CHAIR_FINISH: Record<ChairFinish, "frame" | "seat" | "metal" | "mesh"> = { frame: "frame", fabric: "seat", metal: "metal", mesh: "mesh" };

/** The long tables of one neighbourhood and everything at their seats. */
export function CodingTables({ desks, agents, team }: {
  desks: readonly DeskSlot[]; agents: ReadonlyMap<string, SocietyAgent>; team: TeamColours;
}) {
  const felt = useMemo(() => new MeshStandardMaterial({ color: team.felt, roughness: 0.95 }), [team.felt]);
  useEffect(() => () => felt.dispose(), [felt]);
  const tables = useMemo(() => longTables(desks), [desks]);
  const parts = useMemo(() => {
    const top: Matrix4[] = [], edge: Matrix4[] = [], legs: Matrix4[] = [], spine: Matrix4[] = [], screen: Matrix4[] = [];
    for (const t of tables) {
      top.push(compose([t.x, 0.755, t.z], [t.length, 0.035, t.depth]));
      edge.push(compose([t.x, 0.728, t.z], [t.length - 0.04, 0.022, t.depth - 0.04]));
      // A-frames at both ends and, on a long table, in the middle.
      const frames = t.length > 4 ? [-t.length / 2 + 0.28, 0, t.length / 2 - 0.28] : [-t.length / 2 + 0.28, t.length / 2 - 0.28];
      for (const fx of frames) {
        legs.push(compose([t.x + fx, 0.36, t.z - t.depth / 2 + 0.22], [0.06, 0.72, 0.06]));
        legs.push(compose([t.x + fx, 0.36, t.z + t.depth / 2 - 0.22], [0.06, 0.72, 0.06]));
        legs.push(compose([t.x + fx, 0.03, t.z], [0.06, 0.04, t.depth - 0.4]));
      }
      // The spine: a cable rail and a low felt screen in the team's colour.
      spine.push(compose([t.x, 0.79, t.z], [t.length - 0.3, 0.04, 0.1]));
      screen.push(compose([t.x, 0.98, t.z], [t.length - 0.4, 0.34, 0.03]));
    }
    const seats = desks.filter((desk) => !desk.size);
    const arm = seats.flatMap((d) => [
      seatMatrix(d, [0, 0.8, -0.3], [0.08, 0.05, 0.06]),
      seatMatrix(d, [0, 0.95, -0.3], [0.018, 0.3, 0.018]),
      seatMatrix(d, [0, 1.1, -0.26], [0.04, 0.03, 0.08]),
    ]);
    const monitor = seats.map((d) => seatMatrix(d, [0, 1.18, -0.224]));
    const keys = seats.flatMap((d) => [
      seatMatrix(d, [0, 0.784, 0.2], [0.46, 0.014, 0.14]),
      seatMatrix(d, [0.34, 0.786, 0.2], [0.05, 0.02, 0.08]),
    ]);
    const chair = seats.map((d) => seatMatrix(d, [0, 0, 0.62]));
    const faces = new Map<ScreenFace, Matrix4[]>(FACES.map((f) => [f, []]));
    for (const d of seats) {
      const agent = d.agentId ? agents.get(d.agentId) : undefined;
      faces.get(agent ? agent.state : "empty")!.push(seatMatrix(d, [0, 1.18, -0.212]));
    }
    return { top, edge, legs, spine, screen, arm, monitor, keys, chair, faces };
  }, [tables, desks, agents]);
  const chairMaterial: Record<"frame" | "seat" | "metal" | "mesh", Material> = {
    frame: TM.chairFrame, seat: felt, metal: CHAIR_MAT.aluminium, mesh: CHAIR_MAT.mesh,
  };
  return (
    <group>
      <InstancedParts geometry={TOP} material={TM.top} matrices={parts.top} />
      <InstancedParts geometry={GEO.box} material={TM.edge} matrices={parts.edge} cast={false} />
      <InstancedParts geometry={GEO.box} material={TM.leg} matrices={parts.legs} />
      <InstancedParts geometry={GEO.box} material={TM.spine} matrices={parts.spine} cast={false} />
      <InstancedParts geometry={GEO.box} material={felt} matrices={parts.screen} />
      <InstancedParts geometry={GEO.box} material={MAT.monitorArm} matrices={parts.arm} cast={false} />
      <InstancedParts geometry={MONITOR} material={MAT.monitor} matrices={parts.monitor} />
      <InstancedParts geometry={GEO.box} material={MAT.keyboard} matrices={parts.keys} cast={false} />
      {TASK_CHAIR_PARTS.map((part, i) => (
        <InstancedParts key={i} geometry={part.geometry} material={chairMaterial[CHAIR_FINISH[part.finish]]} matrices={parts.chair} cast={part.cast} />
      ))}
      {FACES.map((face) => <InstancedParts key={face} geometry={SCREEN} material={screenMaterial(face)} matrices={parts.faces.get(face)!} cast={false} />)}
    </group>
  );
}
