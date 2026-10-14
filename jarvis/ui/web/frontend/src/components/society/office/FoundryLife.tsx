/**
 * What moves on the Foundry deck besides the figures: rings of light where the
 * person's character steps, and a few maintenance drones circling over the
 * bays with a scanner cone under each. Reduced motion stills both (the drones
 * hover in place, no rings).
 */
import { useEffect, useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import {
  AdditiveBlending, Color, ConeGeometry, DoubleSide, Group, Mesh, MeshBasicMaterial, MeshStandardMaterial, RingGeometry, SphereGeometry,
} from "three";
import { RoundedBoxGeometry } from "three-stdlib";
import { cachedCanvasTexture } from "./canvasMaterials";
import { FOUNDRY, glowColour } from "./foundryPalette";
import { GEO } from "./OfficeFurniture";
import type { OfficeLayout } from "./officeLayout";
import { player } from "./officeStore";

// ---------------------------------------------------------------------------
// Footsteps
// ---------------------------------------------------------------------------

const STEP_S = 0.32;
const RING_LIFE_S = 0.75;
const RINGS = 8;
const STEP_RING = new RingGeometry(0.2, 0.26, 40);

function Footsteps() {
  const meshes = useRef<(Mesh | null)[]>([]);
  const state = useRef({ next: 0, slot: 0, born: new Array<number>(RINGS).fill(-10) });
  const materials = useMemo(() => Array.from({ length: RINGS }, () => new MeshBasicMaterial({
    color: new Color(FOUNDRY.code).multiplyScalar(1.6), transparent: true, opacity: 0, depthWrite: false,
    blending: AdditiveBlending, toneMapped: false,
  })), []);
  useEffect(() => () => materials.forEach((m) => m.dispose()), [materials]);
  useFrame(({ clock }) => {
    const t = clock.elapsedTime, s = state.current;
    if (player.moving && t >= s.next) {
      s.next = t + STEP_S;
      const mesh = meshes.current[s.slot];
      if (mesh) mesh.position.set(player.x, 0.015, player.z);
      s.born[s.slot] = t;
      s.slot = (s.slot + 1) % RINGS;
    }
    for (let i = 0; i < RINGS; i += 1) {
      const mesh = meshes.current[i];
      if (!mesh) continue;
      const p = (t - s.born[i]) / RING_LIFE_S;
      mesh.visible = p >= 0 && p < 1;
      if (!mesh.visible) continue;
      mesh.scale.setScalar(1 + p * 2.2);
      materials[i].opacity = 0.7 * (1 - p) * (1 - p);
    }
  });
  return (
    <group>
      {materials.map((material, i) => (
        <mesh key={i} ref={(m) => { meshes.current[i] = m; }} geometry={STEP_RING} material={material} rotation={[-Math.PI / 2, 0, 0]}
          visible={false} renderOrder={3} />
      ))}
    </group>
  );
}

// ---------------------------------------------------------------------------
// Drones
// ---------------------------------------------------------------------------

const DRONE = {
  body: new RoundedBoxGeometry(0.46, 0.13, 0.46, 2, 0.05),
  rotor: new RingGeometry(0.02, 0.15, 20),
  light: new SphereGeometry(0.03, 8, 6),
  cone: new ConeGeometry(0.9, 2.6, 24, 1, true),
};

/** Fades along the cone from its apex down (white; tinted). */
function drawCone(ctx: CanvasRenderingContext2D, w: number, h: number): void {
  const g = ctx.createLinearGradient(0, 0, 0, h);
  g.addColorStop(0, "rgba(255,255,255,0.55)");
  g.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, w, h);
}

const DMAT = {
  body: new MeshStandardMaterial({ color: "#2a2e36", roughness: 0.35, metalness: 0.7 }),
  trim: new MeshStandardMaterial({ color: FOUNDRY.gold, roughness: 0.3, metalness: 0.85 }),
  rotor: new MeshBasicMaterial({ color: "#c8d6e6", transparent: true, opacity: 0.18, depthWrite: false, side: DoubleSide }),
  red: new MeshBasicMaterial({ color: glowColour("#ff3b4e", 1.4), toneMapped: false }),
  green: new MeshBasicMaterial({ color: glowColour("#5bff8f", 1.4), toneMapped: false }),
  eye: new MeshBasicMaterial({ color: new Color(FOUNDRY.code).multiplyScalar(2.2), toneMapped: false }),
};

interface Route { cx: number; cz: number; rx: number; rz: number; y: number; speed: number; phase: number; wobble: number }

/** Each drone's loop over the deck: ellipses of different sizes round the floor's middle. Pure. */
export function droneRoutes(bounds: OfficeLayout["bounds"], count: number): Route[] {
  const cx = (bounds.minX + bounds.maxX) / 2, cz = (bounds.minZ + bounds.maxZ) / 2;
  const hw = (bounds.maxX - bounds.minX) / 2, hd = (bounds.maxZ - bounds.minZ) / 2;
  return Array.from({ length: count }, (_, i) => ({
    cx: cx + (i % 2 === 0 ? -1 : 1) * hw * 0.12,
    cz: cz + ((i * 0.37) % 1 - 0.5) * hd * 0.3,
    rx: hw * (0.45 + 0.12 * (i % 3)),
    rz: hd * (0.35 + 0.1 * ((i + 1) % 3)),
    y: 4.3 + (i % 3) * 0.35,
    speed: (0.07 + 0.025 * i) * (i % 2 === 0 ? 1 : -1),
    phase: (i / count) * Math.PI * 2,
    wobble: 0.6 + i * 0.27,
  }));
}

function Drone({ route, animate }: { route: Route; animate: boolean }) {
  const ref = useRef<Group>(null);
  const rotors = useRef<Group>(null);
  const cone = useMemo(() => new MeshBasicMaterial({
    map: cachedCanvasTexture("foundry:cone", 32, 128, drawCone), color: new Color(FOUNDRY.code).multiplyScalar(0.5),
    transparent: true, depthWrite: false, blending: AdditiveBlending, toneMapped: false, side: DoubleSide,
  }), []);
  useEffect(() => () => cone.dispose(), [cone]);
  const angle = useRef(route.phase);
  useFrame(({ camera, clock }, delta) => {
    const g = ref.current;
    if (!g) return;
    if (animate) angle.current += route.speed * Math.min(delta, 0.1);
    const a = angle.current, t = clock.elapsedTime;
    const x = route.cx + Math.cos(a) * route.rx, z = route.cz + Math.sin(a) * route.rz;
    const y = route.y + (animate ? Math.sin(t * route.wobble) * 0.12 : 0);
    g.position.set(x, y, z);
    // Face along the loop, tilted a little into the direction of travel.
    const vx = -Math.sin(a) * route.rx * Math.sign(route.speed), vz = Math.cos(a) * route.rz * Math.sign(route.speed);
    g.rotation.set(0, Math.atan2(vx, vz), 0);
    g.rotateX(animate ? 0.12 : 0);
    if (rotors.current && animate) rotors.current.children.forEach((r, i) => { r.rotation.z = t * 40 + i; });
    // Never in the camera's face.
    g.visible = camera.position.distanceTo(g.position) > 2.2;
  });
  return (
    <group ref={ref}>
      <mesh geometry={DRONE.body} material={DMAT.body} castShadow />
      <mesh geometry={GEO.box} material={DMAT.trim} position={[0, 0.07, 0]} scale={[0.3, 0.012, 0.3]} />
      <mesh geometry={DRONE.light} material={DMAT.eye} position={[0, -0.03, 0.23]} scale={[1.6, 1, 1]} />
      <group ref={rotors}>
        {[[-0.3, -0.3], [0.3, -0.3], [-0.3, 0.3], [0.3, 0.3]].map(([x, z]) => (
          <mesh key={`${x}${z}`} geometry={DRONE.rotor} material={DMAT.rotor} position={[x, 0.08, z]} rotation={[-Math.PI / 2, 0, 0]} />
        ))}
      </group>
      {[[-0.3, -0.3], [0.3, -0.3], [-0.3, 0.3], [0.3, 0.3]].map(([x, z]) => (
        <mesh key={`arm${x}${z}`} geometry={GEO.box} material={DMAT.body} position={[x / 2, 0.04, z / 2]} rotation={[0, Math.atan2(x, z), 0]}
          scale={[0.04, 0.03, 0.42]} />
      ))}
      <mesh geometry={DRONE.light} material={DMAT.red} position={[-0.3, 0.02, 0.3]} />
      <mesh geometry={DRONE.light} material={DMAT.green} position={[0.3, 0.02, 0.3]} />
      {/* The scanner cone sweeping the deck below. */}
      <mesh geometry={DRONE.cone} material={cone} position={[0, -1.35, 0]} renderOrder={3} />
    </group>
  );
}

export function FoundryLife({ layout, animate }: { layout: OfficeLayout; animate: boolean }) {
  const routes = useMemo(() => droneRoutes(layout.bounds, 4), [layout.bounds]);
  return (
    <group>
      {animate && <Footsteps />}
      {routes.map((route, i) => <Drone key={i} route={route} animate={animate} />)}
    </group>
  );
}
