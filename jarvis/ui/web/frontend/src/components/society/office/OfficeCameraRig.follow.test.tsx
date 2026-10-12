import { useEffect, useImperativeHandle } from "react";
import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { PerspectiveCamera, Vector3 } from "three";
import { CanvasActivity } from "@/hooks/useCanvasAwake";
import { FOLLOW_DISTANCE, OfficeCameraRig } from "./OfficeCameraRig";
import { cameraLimitsFor } from "./officeCamera";
import { officeSession, player, useOfficeStore } from "./officeStore";
import { campusOf } from "./officeFixtures";

const state = vi.hoisted(() => ({
  frames: new Set<(frame: unknown, dt: number) => void>(),
  renderer: null as unknown as { camera: PerspectiveCamera; size: { width: number; height: number }; gl: { domElement: HTMLCanvasElement }; scene: object; events: { connected: undefined } },
  controls: null as unknown as { target: Vector3; enabled: boolean; update: () => void; mouseButtons: { LEFT: number }; zoomSpeed: number; maxDistance: number },
}));

vi.mock("@react-three/fiber", () => ({
  useThree: (select: (value: typeof state.renderer) => unknown) => select(state.renderer),
  useFrame: (frame: (frame: unknown, dt: number) => void) => {
    useEffect(() => { state.frames.add(frame); return () => { state.frames.delete(frame); }; }, [frame]);
  },
}));
vi.mock("@react-three/drei", async () => {
  const { forwardRef } = await import("react");
  return {
    OrbitControls: forwardRef(({ enabled, maxDistance }: { enabled: boolean; maxDistance: number }, ref) => {
      state.controls.enabled = enabled;
      state.controls.maxDistance = maxDistance;
      useImperativeHandle(ref, () => state.controls);
      return null;
    }),
  };
});

const campus = campusOf(40, [8, 7, 6, 5]);
const originalPlayer = { ...player };

beforeEach(() => {
  state.renderer = {
    camera: new PerspectiveCamera(35, 1.6, 0.2, 800), size: { width: 1280, height: 800 },
    gl: { domElement: document.createElement("canvas") }, scene: {}, events: { connected: undefined },
  };
  state.controls = { target: new Vector3(), enabled: true, update: () => undefined, mouseButtons: { LEFT: 0 }, zoomSpeed: 1, maxDistance: 0 };
  officeSession.camera = null;
  Object.assign(player, { x: campus.layout.spawn.x, z: campus.layout.spawn.z, heading: 0, path: [], moving: false });
  useOfficeStore.setState({ zoom: null, focus: null, follow: true });
});

afterEach(() => {
  cleanup();
  state.frames.clear();
  Object.assign(player, originalPlayer);
  officeSession.camera = null;
});

const tree = (overview: number) => (
  <CanvasActivity.Provider value><OfficeCameraRig layout={campus.layout} overview={overview} /></CanvasActivity.Provider>
);
const frames = (count: number) => act(() => { for (let i = 0; i < count; i += 1) for (const step of state.frames) step(null, 1 / 30); });
const orbit = () => state.renderer.camera.position.distanceTo(state.controls.target);
const offTarget = () => Math.hypot(state.controls.target.x - player.x, state.controls.target.z - player.z);

it("comes back to the walking view when following resumes after the overview", () => {
  const view = render(tree(0));
  frames(5);
  expect(orbit()).toBeCloseTo(FOLLOW_DISTANCE, 1);
  const angle = () => { const c = state.renderer.camera.position, t = state.controls.target; return Math.atan2(c.x - t.x, c.z - t.z); };

  view.rerender(tree(1));
  frames(5);
  // The overview stands a campus away and looks at the middle of the floor.
  expect(orbit()).toBeGreaterThan(60);
  expect(useOfficeStore.getState().follow).toBe(false);
  const from = orbit();
  const yaw = angle();

  act(() => useOfficeStore.getState().setFollow(true));
  frames(3);
  // A glide, not a cut: on its way after a tenth of a second.
  expect(orbit()).toBeLessThan(from);
  expect(orbit()).toBeGreaterThan(FOLLOW_DISTANCE + 5);
  frames(40);
  expect(orbit()).toBeCloseTo(FOLLOW_DISTANCE, 1);
  expect(offTarget()).toBeLessThan(0.05);
  // Only the distance changed: the direction the person looks from stays.
  expect(angle()).toBeCloseTo(yaw, 2);
});

it("keeps a distance the person zoomed to by hand in the overview", () => {
  const view = render(tree(0));
  frames(5);
  view.rerender(tree(1));
  frames(5);
  const chosen = orbit();
  act(() => { state.renderer.gl.domElement.dispatchEvent(new WheelEvent("wheel", { deltaY: 100 })); });
  // Far out a notch zooms further than up close.
  expect(state.controls.zoomSpeed).toBeGreaterThan(4);
  act(() => useOfficeStore.getState().setFollow(true));
  frames(40);
  expect(orbit()).toBeCloseTo(chosen, 1);
  expect(offTarget()).toBeLessThan(0.05);
});

it("lets the wheel reach the overview of this floor", () => {
  render(tree(0));
  expect(state.controls.maxDistance).toBe(cameraLimitsFor(campus.layout.bounds, 1280 / 800).maxDistance);
  expect(state.controls.maxDistance).toBeGreaterThan(100);
});

it("does not restore a remembered view of a place the floor no longer has", () => {
  officeSession.camera = { position: [900, 20, 900], target: [880, 0.8, 880] };
  officeSession.follow = false;
  render(tree(0));
  frames(2);
  // The view starts from the character instead.
  expect(offTarget()).toBeLessThan(0.05);
  expect(orbit()).toBeCloseTo(FOLLOW_DISTANCE, 1);
  expect(useOfficeStore.getState().follow).toBe(true);
});

it("leaves the view where it is when the floor plan is rebuilt (a team was created)", () => {
  // A view remembered from an earlier visit; restoring it again now would be a jump.
  officeSession.camera = { position: [30, 25, 30], target: [10, 0.8, 10] };
  officeSession.follow = false;
  const view = render(tree(0));
  frames(3);
  // The person turns and pans to a view of their own.
  act(() => {
    state.renderer.camera.position.set(-12, 18, 4);
    state.controls.target.set(-20, 0.8, -6);
    useOfficeStore.getState().setFollow(false);
  });
  frames(2);
  const position = state.renderer.camera.position.toArray();
  const target = state.controls.target.toArray();
  // Same floor, new plan: one more team, so a fresh layout object with a fresh `spawn`.
  const rebuilt = campusOf(40, [8, 7, 6, 5, 4]);
  view.rerender(<CanvasActivity.Provider value><OfficeCameraRig layout={rebuilt.layout} overview={0} /></CanvasActivity.Provider>);
  frames(5);
  expect(state.renderer.camera.position.toArray()).toEqual(position);
  expect(state.controls.target.toArray()).toEqual(target);
  expect(useOfficeStore.getState().follow).toBe(false);
});
