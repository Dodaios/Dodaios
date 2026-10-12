/**
 * The person's own character: walks with WASD/arrows (camera-relative, Shift
 * runs, Space jumps — a sprint jump is faster than a sprint) or by clicking
 * the floor, and interacts with whatever is nearby (E).
 * Zooming out never requires walking — everything stays clickable from afar.
 *
 * A click draws the route on the floor (dots to a ring at the destination).
 * The character walks round people and furniture, never through them, and
 * never comes to rest inside anything solid or beyond the floor's edge.
 */
import { useEffect, useMemo, useRef } from "react";
import { Html } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import { DoubleSide, Object3D, Vector3, type Group, type InstancedMesh, type Mesh, type MeshBasicMaterial } from "three";
import type { FigureDrive } from "../figures/FigureRig";
import { ToyFigure } from "./ToyFigure";
import type { ToyLook } from "./toyFigureModel";
import { isWalkable, nearestWalkable, type NavGrid } from "./officeNav";
import { clickPaceFor, stepClearOfBodies, turnToward } from "./officeMotion";
import { advanceWalk, beginWalk, routeMarks, type Walk } from "./officeWalk";
import { standingPlaceFor } from "./officeTeams";
import { officeSession, player, sameSelection, useOfficeStore, type Selection } from "./officeStore";
import { agentPositions, bodiesExcept, bodiesNear, companions } from "./walkerRegistry";
import { OFFICE_FIGURE_HEIGHT_M } from "./OfficeAgents";
import { seatOf, type OfficeLayout } from "./officeLayout";
import { chairInReach, seatDesks, useLeadSeat } from "./leadSeat";
import { useOfficeDog } from "./dogLife";
import { TreatBone } from "./dogProps";
import { isRunning, useOfficeSettings } from "./officeSettings";
import { nearestInteractable } from "./stations";
import { jumpSquash, newJump, pressJump, stepJump } from "./officeJump";
import { useProgression } from "../progression/progressionStore";
import { PERSON_SUBJECT } from "../progression/progressionApi";
import { LevelChip } from "../progression/LevelHud";
import { useDressedFigure } from "../progression/regalia/dress";

/** The person's pace: a brisk walk, and a sprint on Shift (m/s). */
export const PLAYER_WALK_SPEED = 2.0;
export const PLAYER_SPRINT_SPEED = 4.4;

/** Bodies further than this from the character play no part in a click-to-move walk. */
const BODY_RANGE_M = 7;
/** How far the character may be from free ground before it is put back at the floor's entrance instead. */
const RESCUE_RANGE_M = 8;
/** The route marker: dots on the floor and a ring at the destination, in the character's own gold. */
const MARKER = { dots: 40, colour: "#f5b83d", y: 0.035 } as const;

/** Talk range to an agent, in metres. */
export const AGENT_TALK_RANGE = 1.8;

/** Play range around the spot in front of an arcade screen, in metres. */
export const ARCADE_PLAY_RANGE = 0.9;

const MOVE_KEYS: Record<string, [number, number]> = {
  KeyW: [0, 1], ArrowUp: [0, 1], KeyS: [0, -1], ArrowDown: [0, -1],
  KeyA: [-1, 0], ArrowLeft: [-1, 0], KeyD: [1, 0], ArrowRight: [1, 0],
};

/** Keys typed into a field, a dialog or any other DOM control never walk the character. */
export function ownsKeyboard(target: EventTarget | null): boolean {
  // An open modal owns every key, wherever focus happens to sit.
  if (typeof document !== "undefined" && document.querySelector("[role='dialog'][data-state='open'], [role='alertdialog'][data-state='open']")) return true;
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || !!target.closest("[role='dialog']");
}

/**
 * Held movement keys stop counting the moment a modal (an arcade game, the
 * elevator panel) takes the keyboard: the dialog swallows the keys pressed
 * inside it, and the character must not keep walking behind it on a key that
 * was still held when it opened. Returns true when it forgot something.
 */
export function forgetHeldKeysUnderDialog(pressed: Set<string>): boolean {
  if (pressed.size === 0 || !ownsKeyboard(null)) return false;
  pressed.clear();
  return true;
}

/** Space on a focused button, tab or switch activates that control, never a jump. */
function activatesControl(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && !!target.closest("button, a[href], [role='button'], [role='tab'], [role='switch'], [role='checkbox']");
}

/** Pressed movement keys (and Space for jumping), tracked on the window while the office is awake. */
function useMoveKeys(enabled: boolean, onInteract: () => void, onJump: () => void) {
  const pressed = useRef(new Set<string>());
  const run = useRef(false);
  const jumpHeld = useRef(false);
  useEffect(() => {
    if (!enabled) { pressed.current.clear(); return; }
    const down = (event: KeyboardEvent) => {
      if (ownsKeyboard(event.target) || event.ctrlKey || event.metaKey || event.altKey) return;
      run.current = event.shiftKey;
      if (event.code in MOVE_KEYS) { pressed.current.add(event.code); event.preventDefault(); }
      else if (event.code === "KeyE" && !event.repeat) { onInteract(); event.preventDefault(); }
      else if (event.code === "Space" && !activatesControl(event.target)) {
        event.preventDefault();
        if (!event.repeat) onJump();
        jumpHeld.current = true;
      }
    };
    const up = (event: KeyboardEvent) => {
      pressed.current.delete(event.code);
      if (event.code === "Space") jumpHeld.current = false;
      run.current = event.shiftKey;
    };
    // A key held while the window loses focus never sees its keyup; forget
    // everything then, or the character walks on by itself. (Not on
    // visibilitychange: the desktop WebView reports visible windows as hidden.)
    const release = () => { pressed.current.clear(); jumpHeld.current = false; };
    window.addEventListener("keydown", down);
    // Releases are heard in the capture phase, before any overlay that handles its own keys can swallow them.
    window.addEventListener("keyup", up, true);
    window.addEventListener("blur", release);
    return () => {
      release();
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up, true);
      window.removeEventListener("blur", release);
    };
  }, [enabled, onInteract, onJump]);
  return { pressed, run, jumpHeld };
}

/** What E reaches from where the character stands: a station, an agent or a game cabinet (stations.ts). */
const REACH = { agent: AGENT_TALK_RANGE, arcade: ARCADE_PLAY_RANGE } as const;

export function OfficePlayer({ layout, grid, look, name, awake, reduced }: {
  layout: OfficeLayout; grid: NavGrid; look: ToyLook; name: string; awake: boolean; reduced: boolean;
}) {
  const group = useRef<Group>(null);
  const body = useRef<Group>(null);
  const ring = useRef<Mesh>(null);
  const jump = useMemo(newJump, []);
  const drive = useRef<FigureDrive>({ mode: "idle", speed: 0 });
  const camera = useThree((s) => s.camera);
  const forward = useMemo(() => new Vector3(), []);
  const lastWalk = useRef(0);
  // The click-to-move walk in progress: its route, stuck watch and time budget.
  const walk = useRef<Walk | null>(null);
  const others = useRef<{ x: number; z: number }[]>([]);
  const nearbyRef = useRef<Selection | null>(null);
  const interact = useMemo(() => () => {
    // E on the lead's chair sits down (or stands up again); otherwise it opens what is nearby.
    const seat = useLeadSeat.getState();
    if (seat.seated) { seat.set({ seated: null, standUp: true }); return; }
    if (seat.near) { seat.set({ seated: seat.near, pending: null }); return; }
    // The dog: pet it, or hand over the bone; the treat jar hands one out.
    if (useOfficeDog.getState().interact()) return;
    const nearby = nearbyRef.current;
    if (nearby) useOfficeStore.getState().select(nearby);
  }, []);
  const onJump = useMemo(() => () => pressJump(jump), [jump]);
  const hasBone = useOfficeDog((s) => s.hasBone);
  // Seated at Mission Control the camera is the character's eyes: its own figure would block the view.
  const firstPerson = useLeadSeat((s) => !!layout.command && s.seated === layout.command.id);
  const { pressed, run, jumpHeld } = useMoveKeys(awake, interact, onJump);
  // A level-up of the person's own: the character hops for joy and waves while it stands.
  useEffect(() => useProgression.subscribe((state, prev) => {
    if (state.cheerUntil > prev.cheerUntil && !reduced) pressJump(jump);
  }), [jump, reduced]);
  const level = useProgression((s) => (s.snapshot ? s.subjects[PERSON_SUBJECT]?.level ?? 1 : null));
  const dressed = useDressedFigure("person", PERSON_SUBJECT, look);

  // Arrive by the elevator once per app run; coming back to the map keeps the
  // character where it was, unless a changed floor plan put that spot in a wall.
  useEffect(() => {
    if (!awake) return;
    player.path = []; player.moving = false;
    if (officeSession.playerPlaced && isWalkable(grid, player)) return;
    const start = (officeSession.playerPlaced ? nearestWalkable(grid, player) : null)
      ?? nearestWalkable(grid, layout.spawn) ?? layout.spawn;
    player.x = start.x; player.z = start.z;
    if (!officeSession.playerPlaced) player.heading = Math.PI;
    officeSession.playerPlaced = true;
  }, [grid, layout.spawn, awake]);

  useFrame((_, rawDt) => {
    const dt = Math.min(rawDt, 0.1);
    const store = useOfficeStore.getState();
    // Sitting on the lead's chair: hold the seat until the person moves, walks
    // somewhere else or presses E; then step out to the nearest free spot.
    const seatState = useLeadSeat.getState();
    const seatDesk = seatState.seated ? seatDesks(layout).find((d) => d.id === seatState.seated) : undefined;
    const walkRequested = !!store.walkTo && store.walkTo.seq !== lastWalk.current;
    if (seatState.seated && (!seatDesk || pressed.current.size > 0 || walkRequested)) seatState.set({ seated: null, standUp: true });
    if (useLeadSeat.getState().standUp) {
      const out = nearestWalkable(grid, player);
      if (out) { player.x = out.x; player.z = out.z; }
      player.path = [];
      useLeadSeat.getState().set({ standUp: false });
    }
    if (useLeadSeat.getState().seated && seatDesk) {
      const seat = seatOf(seatDesk);
      player.x = seat.x; player.z = seat.z; player.heading = seat.facing; player.path = []; player.moving = false;
      drive.current.mode = "sit";
      drive.current.speed = 0;
      Object.assign(jump, newJump());
      body.current?.position.setY(0);
      body.current?.scale.set(1, 1, 1);
      group.current?.position.set(player.x, 0, player.z);
      if (group.current) group.current.rotation.y = player.heading;
      if (nearbyRef.current) { nearbyRef.current = null; store.setNearby(null); }
      return;
    }
    // Clicked the chair from afar: sit as soon as the walk there ends beside it.
    if (seatState.pending) {
      const target = seatDesks(layout).find((d) => d.id === seatState.pending);
      if (!target || pressed.current.size > 0) seatState.set({ pending: null });
      else if (player.path.length === 0 && chairInReach([target], player)) seatState.set({ seated: target.id, pending: null });
    }
    // Click-to-move / "walk there" requests.
    if (store.walkTo && store.walkTo.seq !== lastWalk.current) {
      lastWalk.current = store.walkTo.seq;
      // A target inside something solid or on somebody (a desk, a chair, a seated agent, the middle of the holo
      // deck) is reached at a free standing place beside it: the character never comes to rest inside furniture
      // or a figure, and never on a chair that is not its own to sit on.
      const goal = store.walkTo.point;
      const free = standingPlaceFor(layout, grid, goal, bodiesNear(null, goal, 4, null, []));
      walk.current = free ? beginWalk(grid, player, free, bodiesNear(null, player, BODY_RANGE_M, null, others.current)) : null;
      if (!walk.current) player.path = [];
    }
    // Keyboard movement, relative to where the camera looks; nothing while a dialog owns the keys.
    if (forgetHeldKeysUnderDialog(pressed.current)) jumpHeld.current = false;
    let ix = 0, iz = 0;
    for (const code of pressed.current) { ix += MOVE_KEYS[code][0]; iz += MOVE_KEYS[code][1]; }
    const sprinting = isRunning(run.current, useOfficeSettings.getState().alwaysRun);
    const steering = ix !== 0 || iz !== 0 || player.path.length > 0;
    stepJump(jump, dt, jumpHeld.current, sprinting && steering);
    // A sprint jump carries its boost while airborne (eased in and out by stepJump).
    const speed = (sprinting ? PLAYER_SPRINT_SPEED : PLAYER_WALK_SPEED) * jump.speedMul;
    let moved = 0;
    if (ix !== 0 || iz !== 0) {
      // Standing inside something solid (a snapped walk ended in it): step out first, or no move is ever free.
      if (!isWalkable(grid, player)) {
        const out = nearestWalkable(grid, player);
        if (out) { player.x = out.x; player.z = out.z; }
      }
      player.path = [];
      camera.getWorldDirection(forward);
      forward.y = 0;
      if (forward.lengthSq() < 1e-6) forward.set(0, 0, -1);
      forward.normalize();
      // Right = forward × up.
      const rx = -forward.z, rz = forward.x;
      let dx = forward.x * iz + rx * ix, dz = forward.z * iz + rz * ix;
      const len = Math.hypot(dx, dz);
      dx /= len; dz /= len;
      const step = speed * dt;
      const nx = player.x + dx * step, nz = player.z + dz * step;
      // Slide along walls and around people: full move, else each axis alone.
      // Moving away from someone you already touch is always allowed, so nobody gets stuck.
      const free = (p: { x: number; z: number }) => isWalkable(grid, p) && stepClearOfBodies(p, player, bodiesExcept(null, null));
      if (free({ x: nx, z: nz })) { player.x = nx; player.z = nz; moved = step; }
      else if (free({ x: nx, z: player.z })) { player.x = nx; moved = Math.abs(dx * step); }
      else if (free({ x: player.x, z: nz })) { player.z = nz; moved = Math.abs(dz * step); }
      player.heading = turnToward(player.heading, Math.atan2(dx, dz), 12 * dt);
      if (!store.follow) store.setFollow(true);
    } else if (player.path.length > 0 && walk.current) {
      // Round people and furniture, never through them; a walk that cannot go on stops where it is. A long
      // route is jogged and ends in a walk; Shift (or "always run") sprints all the way.
      const pace = sprinting ? speed : clickPaceFor(walk.current.remaining, PLAYER_WALK_SPEED, PLAYER_SPRINT_SPEED) * jump.speedMul;
      const step = advanceWalk(walk.current, player, grid, dt, bodiesNear(null, player, BODY_RANGE_M, null, others.current), { speed: pace, place: false });
      moved = step.moved;
      if (step.arrived || step.event === "lost" || step.event === "blocked") { player.path = []; walk.current = null; }
    } else if (player.path.length > 0) {
      player.path = [];
    }
    // Never inside furniture or beyond the floor: whatever left the standing character in a solid cell (a floor
    // plan rebuilt under it, a seat it was lifted out of) puts it on the nearest free ground.
    if (player.path.length === 0 && !isWalkable(grid, player)) {
      const out = nearestWalkable(grid, player, RESCUE_RANGE_M) ?? nearestWalkable(grid, layout.spawn) ?? layout.spawn;
      player.x = out.x; player.z = out.z;
    }
    player.moving = moved > 0;
    drive.current.mode = moved > 0 ? "walk" : performance.now() < useProgression.getState().cheerUntil ? "wave" : "idle";
    drive.current.speed = moved / Math.max(dt, 1e-3);
    if (group.current) {
      group.current.position.set(player.x, 0, player.z);
      group.current.rotation.y = player.heading;
    }
    // The body rides the hop; the gold ring stays on the floor as its shadow.
    if (body.current) {
      body.current.position.y = jump.y;
      const [sw, sh] = reduced ? [1, 1] : jumpSquash(jump);
      body.current.scale.set(sw, sh, sw);
    }
    if (ring.current) ring.current.scale.setScalar(1 - Math.min(0.35, jump.y * 0.6));
    if (ring.current) (ring.current.material as MeshBasicMaterial).opacity = reduced ? 0.8 : 0.6 + Math.sin(performance.now() / 400) * 0.2;
    // What can the character reach right now? The lead's chair has its own prompt beside it.
    const chair = chairInReach(seatDesks(layout), player);
    if (useLeadSeat.getState().near !== (chair?.id ?? null)) useLeadSeat.getState().set({ near: chair?.id ?? null });
    const nearby = chair ? null : nearestInteractable(layout, player, agentPositions, companions, REACH);
    // Compared with the store too: a floor switch clears the store's reading while the character still stands at the elevator.
    if (!sameSelection(nearby, nearbyRef.current) || !sameSelection(nearby, store.nearby)) { nearbyRef.current = nearby; store.setNearby(nearby); }
  });

  return (
    <>
    <RouteMarker animate={awake && !reduced} />
    <group ref={group} visible={!firstPerson}>
      <mesh ref={ring} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.02, 0]}>
        <ringGeometry args={[0.42, 0.52, 40]} />
        <meshBasicMaterial color="#f5b83d" transparent opacity={0.8} side={DoubleSide} depthWrite={false} />
      </mesh>
      <group ref={body}>
        <ToyFigure look={dressed.look} drive={drive} paused={!awake} heightM={OFFICE_FIGURE_HEIGHT_M} holding={hasBone ? <TreatBone scale={1.15} /> : undefined}
          regalia={dressed.regalia} />
        {!firstPerson && (
          <Html center position={[0, OFFICE_FIGURE_HEIGHT_M + 0.35, 0]} zIndexRange={[25, 0]}>
            <span className="office-plate office-plate-player" data-office-ui>
              <span className="office-plate-badge" style={{ background: "#f5b83d" }} aria-hidden>★</span>
              <span className="office-plate-name">{name}</span>
              {level !== null && <LevelChip kind="person" level={level} />}
            </span>
          </Html>
        )}
      </group>
    </group>
    </>
  );
}

/**
 * Where a click sends the character: dots along the route and a ring at its
 * end, shown while a click-to-move walk is under way. It reads the route the
 * character is following, so it shortens as the walk goes on and vanishes on
 * arrival or when the keyboard takes over. Takes no pointer events.
 */
function RouteMarker({ animate }: { animate: boolean }) {
  const dots = useRef<InstancedMesh>(null);
  const goal = useRef<Group>(null);
  const pulse = useRef<Mesh>(null);
  const dummy = useMemo(() => new Object3D(), []);
  useFrame(({ clock }) => {
    const path = player.path;
    const showing = path.length > 0;
    if (goal.current) goal.current.visible = showing;
    if (dots.current) dots.current.visible = showing;
    if (!showing || !goal.current || !dots.current) return;
    const end = path[path.length - 1];
    goal.current.position.set(end.x, MARKER.y, end.z);
    if (pulse.current) {
      const beat = animate ? (clock.elapsedTime * 1.4) % 1 : 0.35;
      pulse.current.scale.setScalar(0.7 + beat * 0.9);
      (pulse.current.material as MeshBasicMaterial).opacity = animate ? 0.6 * (1 - beat) : 0.4;
    }
    const marks = routeMarks(player, path, 0.9, MARKER.dots);
    marks.forEach((mark, i) => {
      dummy.position.set(mark.x, MARKER.y, mark.z);
      dummy.rotation.set(-Math.PI / 2, 0, 0);
      dummy.updateMatrix();
      dots.current!.setMatrixAt(i, dummy.matrix);
    });
    dots.current.count = marks.length;
    dots.current.instanceMatrix.needsUpdate = true;
  });
  return (
    <>
      <instancedMesh ref={dots} args={[undefined, undefined, MARKER.dots]} visible={false} frustumCulled={false} raycast={() => null}>
        <circleGeometry args={[0.07, 12]} />
        <meshBasicMaterial color={MARKER.colour} transparent opacity={0.7} side={DoubleSide} depthWrite={false} />
      </instancedMesh>
      <group ref={goal} visible={false}>
        <mesh rotation={[-Math.PI / 2, 0, 0]} raycast={() => null}>
          <ringGeometry args={[0.2, 0.27, 32]} />
          <meshBasicMaterial color={MARKER.colour} transparent opacity={0.9} side={DoubleSide} depthWrite={false} />
        </mesh>
        <mesh rotation={[-Math.PI / 2, 0, 0]} raycast={() => null}>
          <circleGeometry args={[0.07, 16]} />
          <meshBasicMaterial color={MARKER.colour} transparent opacity={0.9} side={DoubleSide} depthWrite={false} />
        </mesh>
        <mesh ref={pulse} rotation={[-Math.PI / 2, 0, 0]} raycast={() => null}>
          <ringGeometry args={[0.3, 0.34, 32]} />
          <meshBasicMaterial color={MARKER.colour} transparent opacity={0.4} side={DoubleSide} depthWrite={false} />
        </mesh>
      </group>
    </>
  );
}
