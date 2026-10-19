/**
 * The captain's companion: the pet from My Pets (Gigi when none is chosen),
 * who is the user's assistant in the Verse. It keeps a little behind the
 * captain's shoulder; flyers hover at head height, pets that walk stay on
 * free floor and turn the way they move. A soft glow marks a flyer.
 */
import { Component, Suspense, useMemo, useRef, type ReactNode } from "react";
import { useFrame } from "@react-three/fiber";
import { Color, type Group } from "three";
import { CompanionModel } from "../../companion/AgentFollower";
import { defaultCompanion } from "../../companion/appearance";
import { useCompanionPet } from "../../companion/companionPetStore";
import { companionFlies, type CompanionPet } from "../../companion/petCompanions";
import { PetModel, VoxelPet, type PetDrive } from "../../companion/PetModel";
import { isFree, type NavGrid } from "../nav/shipNav";
import { captain } from "../shipStore";
import { turnTowards } from "./motion";

/** A missing or broken model hides the body, never the ship. */
class Boundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error: Error) { console.warn("Companion model unavailable", error.name); }
  render() { return this.state.failed ? null : this.props.children; }
}

const GIGI_SIZE_M = 0.5;
const FOLLOW_BACK = 1.05;
const FOLLOW_SIDE = 0.75;
/** Every this many metres walked together pays the companion a little XP (metered on the server). */
export const WALK_REPORT_M = 50;

function Body({ pet, drive, reduced }: { pet: CompanionPet; drive: { current: PetDrive }; reduced: boolean }) {
  const gigi = useMemo(() => ({ ...defaultCompanion("jarvis"), sizeM: GIGI_SIZE_M }), []);
  if (pet.kind === "model") return <PetModel pet={pet} drive={drive} reduced={reduced} paused={false} />;
  if (pet.kind === "voxel") return <VoxelPet pet={pet} reduced={reduced} paused={false} />;
  return <CompanionModel appearance={gigi} lead />;
}

export function ShipPet({ grid, reduced, onWalked }: { grid: NavGrid; reduced: boolean; onWalked?: () => void }) {
  const pet = useCompanionPet((s) => s.pet);
  const flies = companionFlies(pet);
  const root = useRef<Group>(null);
  const body = useRef({ x: captain.x + FOLLOW_SIDE, z: captain.z + FOLLOW_BACK, yaw: captain.yaw, t: 0 });
  const drive = useRef<PetDrive>({ speed: 0, mood: "idle" });
  const walked = useRef({ x: captain.x, z: captain.z, metres: 0 });
  const glow = useMemo(() => new Color("#ffd98a").multiplyScalar(1.6), []);
  useFrame((_, rawDt) => {
    const dt = Math.min(0.1, rawDt);
    const b = body.current;
    b.t += dt;
    const w = walked.current;
    const step = Math.hypot(captain.x - w.x, captain.z - w.z);
    // A jump (a deck change, a placement) is not a walk.
    if (step < 3) w.metres += step;
    w.x = captain.x; w.z = captain.z;
    if (w.metres >= WALK_REPORT_M) { w.metres -= WALK_REPORT_M; onWalked?.(); }
    // Behind the captain's right shoulder, in the captain's own frame.
    const s = Math.sin(captain.yaw), c = Math.cos(captain.yaw);
    let tx = captain.x - s * FOLLOW_BACK - c * FOLLOW_SIDE;
    let tz = captain.z - c * FOLLOW_BACK + s * FOLLOW_SIDE;
    if (!flies && !isFree(grid, { x: tx, z: tz })) { tx = captain.x - s * FOLLOW_BACK; tz = captain.z - c * FOLLOW_BACK; }
    const dx = tx - b.x, dz = tz - b.z;
    const dist = Math.hypot(dx, dz);
    const k = 1 - Math.exp(-dt * (dist > 4 ? 5 : 2.6));
    const nx = b.x + dx * k, nz = b.z + dz * k;
    if (flies || isFree(grid, { x: nx, z: nz })) { b.x = nx; b.z = nz; }
    const speed = (dist * k) / Math.max(dt, 1e-3);
    drive.current.speed = speed;
    drive.current.mood = "idle";
    b.yaw = speed > 0.15 ? turnTowards(b.yaw, Math.atan2(dx, dz), dt, 6) : turnTowards(b.yaw, captain.yaw, dt, 2);
    const g = root.current;
    if (g) {
      const bob = flies && !reduced ? Math.sin(b.t * 2.1) * 0.06 : 0;
      g.position.set(b.x, flies ? 1.45 + bob : 0, b.z);
      g.rotation.y = b.yaw;
    }
  });
  return (
    <group ref={root}>
      <Boundary>
        <Suspense fallback={null}>
          <group position={[0, flies && pet.kind === "gigi" ? -0.26 : flies ? -pet.heightM / 2 : 0, 0]}>
            <Body pet={pet} drive={drive} reduced={reduced} />
          </group>
        </Suspense>
      </Boundary>
      {flies && (
        <mesh position={[0, -0.35, 0]} rotation={[-Math.PI / 2, 0, 0]} raycast={() => undefined}>
          <circleGeometry args={[0.18, 24]} />
          <meshBasicMaterial color={glow} transparent opacity={0.35} toneMapped={false} depthWrite={false} />
        </mesh>
      )}
    </group>
  );
}
