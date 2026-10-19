/**
 * A busy light on every occupied desk of the coding floor: a small frosted
 * lamp on a brass foot at the desk's back corner, lit in the pane's state —
 * green while it works, amber blinking while it waits for the person, red
 * when it failed, a dim grey when idle. It stays on the desk while its agent
 * walks off to the coffee bar, so a glance along a bench tells who needs you.
 *
 * Two instanced meshes for the whole floor; the lamp colours are rewritten a
 * few times a second, not every frame.
 */
import { useLayoutEffect, useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Color, CylinderGeometry, InstancedMesh, Matrix4, MeshBasicMaterial, MeshStandardMaterial, Quaternion, Vector3 } from "three";
import type { AgentDotKind } from "@/components/agentic/sidePanel/agentStatus";
import type { PaneOccupant } from "./codingFloor";
import type { DeskSlot } from "./officeLayout";
import { CODING_SCENE } from "./officePalette";

/** Where the lamp stands in the desk's own frame (the agent sits at +z): the back corner beside the monitor. */
const LAMP_LOCAL = new Vector3(-0.6, 0.815, -0.28);
const FOOT = new CylinderGeometry(0.03, 0.034, 0.018, 16);
const LAMP = new CylinderGeometry(0.026, 0.03, 0.07, 16);
/** A moment at which the blinking waiting light is on: the still frame under reduced motion. */
const REST_T = 0.1;

const COLOURS: Record<AgentDotKind, Color> = {
  working: new Color(CODING_SCENE.busy.working),
  waiting: new Color(CODING_SCENE.busy.waiting),
  error: new Color(CODING_SCENE.busy.error),
  idle: new Color(CODING_SCENE.busy.idle),
};

/** A desk lamp's colour at time `t` (s): waiting blinks, failed breathes, the others hold. Pure. */
export function busyColour(state: AgentDotKind, t: number, out: Color): Color {
  out.copy(COLOURS[state]);
  if (state === "waiting") return out.multiplyScalar(Math.sin(t * 6) > 0 ? 1 : 0.2);
  if (state === "error") return out.multiplyScalar(0.65 + 0.35 * (0.5 + 0.5 * Math.sin(t * 3)));
  return out;
}

const FOOT_MAT = new MeshStandardMaterial({ color: CODING_SCENE.brass, roughness: 0.3, metalness: 0.6 });
/** Unlit, so the lamp reads as light in any scene lighting; each instance's colour is its state. */
const LAMP_MAT = new MeshBasicMaterial({ color: "#ffffff" });

const _m = new Matrix4(), _q = new Quaternion(), _p = new Vector3(), _one = new Vector3(1, 1, 1);
function lampMatrix(desk: DeskSlot, lift: number): Matrix4 {
  const turn = desk.facing === "north" ? 0 : Math.PI;
  const x = LAMP_LOCAL.x * Math.cos(turn) + LAMP_LOCAL.z * Math.sin(turn);
  const z = -LAMP_LOCAL.x * Math.sin(turn) + LAMP_LOCAL.z * Math.cos(turn);
  return _m.compose(_p.set(desk.x + x, LAMP_LOCAL.y + lift, desk.z + z), _q.identity(), _one);
}

export function DeskBusyLights({ desks, occupants, animate }: {
  desks: readonly DeskSlot[]; occupants: ReadonlyMap<string, PaneOccupant>; animate: boolean;
}) {
  const lit = useMemo(() => desks.flatMap((desk) => {
    const occupant = desk.agentId ? occupants.get(desk.agentId) : undefined;
    return occupant ? [{ desk, state: occupant.dot }] : [];
  }), [desks, occupants]);
  const foot = useRef<InstancedMesh>(null);
  const lamp = useRef<InstancedMesh>(null);
  const colour = useMemo(() => new Color(), []);
  useLayoutEffect(() => {
    lit.forEach(({ desk, state }, i) => {
      foot.current?.setMatrixAt(i, lampMatrix(desk, 0));
      lamp.current?.setMatrixAt(i, lampMatrix(desk, 0.044));
      lamp.current?.setColorAt(i, busyColour(state, REST_T, colour));
    });
    for (const mesh of [foot.current, lamp.current]) {
      if (!mesh) continue;
      mesh.count = lit.length;
      mesh.instanceMatrix.needsUpdate = true;
      if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    }
  }, [lit, colour]);
  const next = useRef(0);
  useFrame(({ clock }) => {
    const mesh = lamp.current;
    if (!animate || !mesh || clock.elapsedTime < next.current) return;
    next.current = clock.elapsedTime + 0.1;
    let changed = false;
    lit.forEach(({ state }, i) => {
      if (state !== "waiting" && state !== "error") return;
      mesh.setColorAt(i, busyColour(state, clock.elapsedTime, colour));
      changed = true;
    });
    if (changed && mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  });
  if (lit.length === 0) return null;
  // Remount when the count changes: an instanced mesh cannot grow in place.
  return (
    <group>
      <instancedMesh key={`foot${lit.length}`} ref={foot} args={[FOOT, FOOT_MAT, lit.length]} castShadow frustumCulled={false} />
      <instancedMesh key={`lamp${lit.length}`} ref={lamp} args={[LAMP, LAMP_MAT, lit.length]} frustumCulled={false} />
    </group>
  );
}
