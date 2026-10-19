/**
 * A team lead's place must be found on screen, not only in the plan. These
 * tests put the mark (chair shell, chair mat, name stand) through the real
 * cameras: the default follow view and the campus overview, in a 1600 x 900
 * window, and check how many pixels each piece covers and that nothing on the
 * floor stands between it and the camera.
 */
import { describe, expect, it } from "vitest";
import { Box3, Matrix4, PerspectiveCamera, Vector3 } from "three";
import { pendantHousings } from "./AgentsFloorAmbience";
import { placementMatrix } from "./DeskDressing";
import { leadMark, type Placement } from "./deskKit";
import { TASK_CHAIR_PARTS } from "./OfficeChairs";
import { campusOverview, CAMERA_FOV, FOLLOW_DISTANCE_M, HOME_PITCH_RAD, HOME_YAW_RAD, type CameraPose } from "./officeCamera";
import { buildOfficeLayout, leadDesks, standOf, type DeskSlot, type OfficeAgentInput, type OfficeLayout, type OfficeTeamInput } from "./officeLayout";

const VIEW = { w: 1600, h: 900 } as const;
/** The height the follow view looks at (OfficeCameraRig's target height). */
const TARGET_HEIGHT = 0.8;

const staff = (count: number): OfficeAgentInput[] => Array.from({ length: count }, (_, i) => ({
  agentId: `a${i + 1}`, name: `Agent ${i + 1}`, tier: "specialist", providerLabel: "Codex", state: "idle", createdMs: i,
}));
const teamsOf = (count: number, size: number): OfficeTeamInput[] => Array.from({ length: count }, (_, t) => ({
  id: `team-${t}`, name: `Team ${t}`, createdMs: t, members: Array.from({ length: size }, (_, i) => `a${1 + t * size + i}`),
  // Not the earliest arrival: the lead had to be seated at the head desk.
  leadId: `a${2 + t * size}`,
}));

/** The view that follows the person standing at `at`, as the camera rig sets it. */
function followPose(at: { x: number; z: number }, distance = FOLLOW_DISTANCE_M): CameraPose {
  const horizontal = Math.cos(HOME_PITCH_RAD) * distance;
  return {
    target: [at.x, TARGET_HEIGHT, at.z],
    position: [at.x + Math.sin(HOME_YAW_RAD) * horizontal, Math.sin(HOME_PITCH_RAD) * distance + TARGET_HEIGHT, at.z + Math.cos(HOME_YAW_RAD) * horizontal],
  };
}

function cameraOf(pose: CameraPose): PerspectiveCamera {
  const camera = new PerspectiveCamera(CAMERA_FOV, VIEW.w / VIEW.h, 0.2, 800);
  camera.position.set(...pose.position);
  camera.lookAt(...pose.target);
  camera.updateMatrixWorld(true);
  camera.updateProjectionMatrix();
  return camera;
}

const pixel = (camera: PerspectiveCamera, point: Vector3): { x: number; y: number } => {
  const ndc = point.clone().project(camera);
  return { x: ((ndc.x + 1) / 2) * VIEW.w, y: ((1 - ndc.y) / 2) * VIEW.h };
};
const apart = (a: { x: number; y: number }, b: { x: number; y: number }) => Math.hypot(a.x - b.x, a.y - b.y);

/** A desk's own space in the world, as DeskDressing and DeskInstances place it. */
const deskWorld = (desk: DeskSlot) => new Matrix4().makeRotationY(desk.facing === "north" ? 0 : Math.PI).setPosition(desk.x, 0, desk.z);
const worldOf = (desk: DeskSlot, part: Placement) => deskWorld(desk).multiply(placementMatrix(part));

/** A point of a part's unit box (each side from -0.5 to 0.5) in the world. */
const corner = (matrix: Matrix4, x: number, y: number, z: number) => new Vector3(x, y, z).applyMatrix4(matrix);

/** On-screen length of a plate's two sides, measured across the middle of the face that looks along its local `normal`. */
function faceSides(camera: PerspectiveCamera, matrix: Matrix4, normal: "y" | "z"): [number, number] {
  const p = (u: number, v: number) => pixel(camera, normal === "z" ? corner(matrix, u, v, 0.5) : corner(matrix, u, 0.5, v));
  return [apart(p(-0.5, 0), p(0.5, 0)), apart(p(0, -0.5), p(0, 0.5))];
}

/** Points spread over a plate's visible face, a little inside its edges. */
function faceSamples(matrix: Matrix4, normal: "y" | "z", n = 5): Vector3[] {
  const out: Vector3[] = [];
  for (let i = 0; i < n; i += 1) {
    for (let j = 0; j < n; j += 1) {
      const u = -0.42 + (0.84 * i) / (n - 1), v = -0.42 + (0.84 * j) / (n - 1);
      out.push(normal === "z" ? corner(matrix, u, v, 0.52) : corner(matrix, u, 0.52, v));
    }
  }
  return out;
}

/** Does the straight line from `from` to `to` pass through `box`? */
function crosses(from: Vector3, to: Vector3, box: Box3): boolean {
  let near = 0, far = 1;
  for (const axis of ["x", "y", "z"] as const) {
    const d = to[axis] - from[axis];
    if (Math.abs(d) < 1e-9) {
      if (from[axis] < box.min[axis] || from[axis] > box.max[axis]) return false;
      continue;
    }
    const a = (box.min[axis] - from[axis]) / d, b = (box.max[axis] - from[axis]) / d;
    near = Math.max(near, Math.min(a, b));
    far = Math.min(far, Math.max(a, b));
    if (near > far) return false;
  }
  return true;
}

const boxAt = (desk: DeskSlot, centre: [number, number, number], size: [number, number, number]): Box3 => {
  const turn = desk.facing === "north" ? 1 : -1;
  return new Box3().setFromCenterAndSize(new Vector3(desk.x + turn * centre[0], centre[1], desk.z + turn * centre[2]), new Vector3(...size));
};

/**
 * What can stand in the way on the floor: every desk's monitor and felt screen, every chair's back and whoever sits
 * on it (as boxes a little larger than the things), and the pendant lights. `own` is the lead's desk, whose own
 * chair back the shell lies on: `withOwnChair` leaves that one out.
 */
function occluders(layout: OfficeLayout, own: DeskSlot, withOwnChair: boolean): Box3[] {
  const out: Box3[] = [];
  for (const desk of layout.departments.flatMap((d) => d.desks)) {
    out.push(boxAt(desk, [0, 1.18, -0.224], [0.74, 0.45, 0.04]));
    out.push(boxAt(desk, [0, 0.95, -0.41], [1.46, 0.36, 0.04]));
    // A seated figure: from the seat to the top of the head.
    out.push(boxAt(desk, [0, 0.98, 0.6], [0.5, 0.96, 0.36]));
    if (desk.id !== own.id || withOwnChair) out.push(boxAt(desk, [0, 0.86, 0.87], [0.5, 0.52, 0.1]));
  }
  for (const p of pendantHousings(layout.departments)) {
    out.push(new Box3().setFromCenterAndSize(new Vector3(p.x, p.y, p.z), new Vector3(p.length, p.h + 0.03, p.w + 0.02)));
  }
  return out;
}

/** The share of `points` the camera sees with nothing in `boxes` in front of them. */
function seen(camera: PerspectiveCamera, points: Vector3[], boxes: Box3[]): number {
  const clear = points.filter((point) => !boxes.some((box) => crosses(point, camera.position, box)));
  return clear.length / points.length;
}

const felt = (parts: Placement[]) => parts.filter((p) => p.part === "felt");

describe("a team lead's place", () => {
  const layout = buildOfficeLayout(staff(15), { teams: teamsOf(3, 4) });
  const leads = leadDesks(layout);
  const mark = leadMark("#8aa391");
  const shell = felt(mark.chair).slice(0, 3), plate = felt(mark.stand)[0], mat = mark.mat[0];

  it("is marked at every team's head desk, which faces north: its chair's back looks at the south-east camera", () => {
    expect(leads).toHaveLength(3);
    for (const { desk } of leads) expect(desk.facing).toBe("north");
  });

  it("hugs the real chair: the shell lies on the backrest, the pad on the seat, the mat under it", () => {
    const back = new Box3(), seat = new Box3();
    TASK_CHAIR_PARTS.forEach((part, i) => {
      part.geometry.computeBoundingBox();
      if (part.finish === "mesh") back.union(part.geometry.boundingBox!);
      if (part.finish === "fabric" && i === 2) seat.union(part.geometry.boundingBox!);
    });
    // DeskInstances stands the chair 0.62 m behind the desk's centre.
    const chairZ = 0.62;
    const shellBox = new Box3();
    for (const part of shell) {
      const m = placementMatrix(part);
      for (const x of [-0.5, 0.5]) for (const y of [-0.5, 0.5]) for (const z of [-0.5, 0.5]) shellBox.expandByPoint(corner(m, x, y, z));
    }
    // Behind the mesh (never in front of it, where the sitter is), by a few centimetres at most; inside its height; as wide as it.
    expect(shellBox.max.z - (back.max.z + chairZ)).toBeGreaterThan(0.015);
    expect(shellBox.max.z - (back.max.z + chairZ)).toBeLessThan(0.07);
    expect(shellBox.min.z).toBeGreaterThan(back.min.z + chairZ);
    expect(shellBox.min.y).toBeGreaterThan(back.min.y);
    expect(shellBox.max.y).toBeLessThan(back.max.y + 0.01);
    expect(Math.abs(shellBox.max.x - back.max.x)).toBeLessThan(0.05);
    expect(Math.abs(shellBox.min.x - back.min.x)).toBeLessThan(0.05);
    const pad = felt(mark.chair)[3];
    // The pad rests in the seat's dish and stands a few millimetres proud of its rim.
    expect(pad.p[1] - pad.s![1] / 2).toBeLessThan(seat.max.y);
    expect(pad.p[1] + pad.s![1] / 2).toBeGreaterThan(seat.max.y + 0.002);
    expect(pad.p[1] + pad.s![1] / 2).toBeLessThan(seat.max.y + 0.012);
    expect(pad.s![0]).toBeLessThan(seat.max.x - seat.min.x);
    // The mat is flat, above the rug's field (7 mm) and under the light pools (12 mm).
    expect(mat.p[1] - mat.s![1] / 2).toBeGreaterThan(0.007);
    expect(mat.p[1] + mat.s![1] / 2).toBeLessThan(0.012);
  });

  it("reads in the default follow view: chair shell and name plate cover more than ten pixels each way, with nothing in front", () => {
    for (const { desk, dept } of leads) {
      const centre = { x: (dept.minX + dept.maxX) / 2, z: (dept.minZ + dept.maxZ) / 2 };
      // Standing beside the lead, in the middle of its studio, and in its doorway.
      for (const person of [standOf(desk), centre, { x: centre.x, z: dept.maxZ - 0.5 }]) {
        const camera = cameraOf(followPose(person));
        const at = `${desk.id} from ${person.x.toFixed(1)},${person.z.toFixed(1)}`;

        // The chair's shell as one shape: its box on screen.
        const pixels = shell.flatMap((part) => {
          const m = worldOf(desk, part);
          return [-0.5, 0.5].flatMap((x) => [-0.5, 0.5].flatMap((y) => [-0.5, 0.5].map((z) => pixel(camera, corner(m, x, y, z)))));
        });
        const w = Math.max(...pixels.map((p) => p.x)) - Math.min(...pixels.map((p) => p.x));
        const h = Math.max(...pixels.map((p) => p.y)) - Math.min(...pixels.map((p) => p.y));
        expect(Math.min(w, h), `shell ${at}`).toBeGreaterThan(24);
        for (const p of pixels) {
          expect(p.x > 0 && p.x < VIEW.w && p.y > 0 && p.y < VIEW.h, `shell on screen ${at}`).toBe(true);
        }
        const blockers = occluders(layout, desk, false);
        // Its rear face looks away from the desk (local +z).
        for (const part of shell) expect(seen(camera, faceSamples(worldOf(desk, part), "z"), blockers), `shell seen ${at}`).toBe(1);

        // The name plate on the desk: both of its sides, and all of its face.
        const plateWorld = worldOf(desk, plate);
        const [pw, ph] = faceSides(camera, plateWorld, "z");
        expect(Math.min(pw, ph), `plate ${at}`).toBeGreaterThanOrEqual(10);
        expect(seen(camera, faceSamples(plateWorld, "z"), occluders(layout, desk, true)), `plate seen ${at}`).toBe(1);
      }
    }
  });

  it("reads from the overview: the chair mat is a patch of the team's colour ten pixels across, most of it in the open", () => {
    const camera = cameraOf(campusOverview(layout.bounds, VIEW.w / VIEW.h));
    for (const { desk } of leads) {
      const matWorld = worldOf(desk, mat);
      const [mw, md] = faceSides(camera, matWorld, "y");
      expect(Math.min(mw, md), desk.id).toBeGreaterThanOrEqual(10);
      // The chair and whoever sits on it stand on the mat; the rest of it lies open.
      expect(seen(camera, faceSamples(matWorld, "y", 7), occluders(layout, desk, true)), desk.id).toBeGreaterThan(0.55);
      // The shell is still there as a second patch above it.
      for (const part of shell) expect(seen(camera, faceSamples(worldOf(desk, part), "z"), occluders(layout, desk, false)), desk.id).toBe(1);
    }
  });

  it("stays inside the desk top and the strip the chair rolls on", () => {
    const TOP = 0.77;
    for (const part of mark.stand) {
      const m = placementMatrix(part);
      for (const x of [-0.5, 0.5]) for (const y of [-0.5, 0.5]) for (const z of [-0.5, 0.5]) {
        const p = corner(m, x, y, z);
        // On the desk top (1.5 m x 0.8 m), right of the keyboard and the mouse, lower than the monitor's lower edge.
        expect(p.x, part.part).toBeGreaterThan(0.4);
        expect(p.x, part.part).toBeLessThan(0.75);
        expect(p.z, part.part).toBeGreaterThan(0.15);
        expect(p.z, part.part).toBeLessThan(0.4);
        expect(p.y, part.part).toBeGreaterThanOrEqual(TOP - 1e-9);
        expect(p.y, part.part).toBeLessThan(0.96);
      }
    }
    // The mat: narrower than the desk pitch (1.7 m), and it ends well inside the bench's own depth (2.1 m from its middle).
    expect(mat.s![0]).toBeLessThan(1.5);
    expect(0.45 + mat.p[2] + mat.s![2] / 2).toBeLessThan(2.1);
  });
});
