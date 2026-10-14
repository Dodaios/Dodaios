/**
 * The Core: the coding floor's landmark, hanging above the spawn terminal in
 * the middle of the concourse. A plasma heart inside three gyroscope rings,
 * held between two crowns of fins, with motes orbiting it and a column of
 * light that runs from the terminal up into the nebula — visible from every
 * corner of the deck.
 *
 * It reads the floor's real state and nothing else: the rings turn faster and
 * the heart burns brighter the more panes are working, an idle floor lets it
 * slow to a drift, and every packet of output that reaches it along a rail
 * makes it flare (`coreSignal`). Reduced motion holds it still. When the
 * camera comes down close underneath it, the hanging parts step aside so they
 * never fill the view.
 */
import { useEffect, useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import {
  AdditiveBlending, Color, CylinderGeometry, DoubleSide, Group, IcosahedronGeometry, InstancedMesh, Matrix4, MeshBasicMaterial,
  RepeatWrapping, TorusGeometry, Vector3,
} from "three";
import { cachedCanvasTexture } from "./canvasMaterials";
import type { Point } from "./officeLayout";
import { FOUNDRY } from "./foundryPalette";
import { GEO, matte } from "./OfficeFurniture";

/** What the rails tell the Core: each arriving packet adds to `flash`, which decays every frame. */
export const coreSignal = { flash: 0 };

const HEART_Y = 5.2;
const COLUMN_H = 60;
const MOTES = 28;

/** A soft radial glow (white; tinted by the material). */
function drawHalo(ctx: CanvasRenderingContext2D, w: number, h: number): void {
  const g = ctx.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, w / 2);
  g.addColorStop(0, "rgba(255,255,255,0.95)");
  g.addColorStop(0.18, "rgba(255,255,255,0.45)");
  g.addColorStop(0.5, "rgba(255,255,255,0.12)");
  g.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, w, h);
}

/** Soft bands of light that rise up the column: the energy flowing into the sky (white; tinted). */
function drawFlow(ctx: CanvasRenderingContext2D, w: number, h: number): void {
  ctx.clearRect(0, 0, w, h);
  for (const [y, size, alpha] of [[0.12, 0.05, 0.9], [0.4, 0.03, 0.6], [0.63, 0.07, 0.75], [0.86, 0.025, 0.5]] as const) {
    const g = ctx.createLinearGradient(0, (y - size) * h, 0, (y + size) * h);
    g.addColorStop(0, "rgba(255,255,255,0)");
    g.addColorStop(0.5, `rgba(255,255,255,${alpha})`);
    g.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = g;
    ctx.fillRect(0, (y - size) * h, w, size * 2 * h);
  }
}

/** A column that is bright at its foot and fades out upwards, with fine vertical streaks (white; tinted). */
function drawColumn(ctx: CanvasRenderingContext2D, w: number, h: number): void {
  const g = ctx.createLinearGradient(0, h, 0, 0);
  g.addColorStop(0, "rgba(255,255,255,0.9)");
  g.addColorStop(0.15, "rgba(255,255,255,0.45)");
  g.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, w, h);
  ctx.globalCompositeOperation = "destination-out";
  for (let x = 0; x < w; x += 4) {
    ctx.fillStyle = `rgba(0,0,0,${0.15 + ((x * 37) % 11) / 30})`;
    ctx.fillRect(x, 0, 2, h);
  }
  ctx.globalCompositeOperation = "source-over";
}

const GEOM = {
  heart: new IcosahedronGeometry(0.55, 3),
  shell: new IcosahedronGeometry(0.78, 1),
  ringA: new TorusGeometry(1.3, 0.075, 12, 96),
  ringB: new TorusGeometry(1.65, 0.05, 10, 112),
  ringC: new TorusGeometry(2.05, 0.03, 8, 128),
  crown: new TorusGeometry(1.9, 0.1, 10, 64),
  crownLow: new TorusGeometry(1.7, 0.09, 10, 64),
  crownBand: new TorusGeometry(1.9, 0.045, 8, 64),
  column: new CylinderGeometry(0.42, 0.42, COLUMN_H, 24, 1, true),
  columnWide: new CylinderGeometry(1.0, 1.0, COLUMN_H, 24, 1, true),
  mote: new IcosahedronGeometry(0.045, 0),
};

const MAT = {
  gold: matte(FOUNDRY.gold, { roughness: 0.25, metalness: 0.9 }),
  steel: matte(FOUNDRY.steel, { roughness: 0.4, metalness: 0.7 }),
  heart: new MeshBasicMaterial({ color: new Color(FOUNDRY.plasma.heart).multiplyScalar(1.25), toneMapped: false }),
  shell: new MeshBasicMaterial({
    color: new Color(FOUNDRY.plasma.inner).multiplyScalar(1.2), wireframe: true, transparent: true, opacity: 0.55,
    blending: AdditiveBlending, depthWrite: false, toneMapped: false,
  }),
  ringGlow: new MeshBasicMaterial({ color: new Color(FOUNDRY.code).multiplyScalar(2), toneMapped: false }),
  fin: matte(FOUNDRY.steelDark, { roughness: 0.4, metalness: 0.7 }),
  finLight: new MeshBasicMaterial({ color: new Color(FOUNDRY.code).multiplyScalar(1.6), toneMapped: false }),
  mote: new MeshBasicMaterial({ color: new Color(FOUNDRY.plasma.inner).multiplyScalar(2.4), toneMapped: false }),
};

/** Unit vectors of the fins round a crown. */
const FINS = Array.from({ length: 10 }, (_, i) => (i / 10) * Math.PI * 2);

export function FoundryCore({ at, working, animate }: { at: Point; working: number; animate: boolean }) {
  const materials = useMemo(() => {
    const halo = cachedCanvasTexture("foundry:halo", 128, 128, drawHalo);
    const column = cachedCanvasTexture("foundry:column", 64, 256, drawColumn);
    const flowBase = cachedCanvasTexture("foundry:flow", 16, 256, drawFlow);
    const flow = flowBase?.clone() ?? null;
    if (flow) { flow.wrapS = flow.wrapT = RepeatWrapping; flow.repeat.set(1, 8); flow.needsUpdate = true; }
    return {
      flow: new MeshBasicMaterial({
        map: flow, color: new Color(FOUNDRY.plasma.inner).multiplyScalar(0.4), transparent: true, depthWrite: false,
        blending: AdditiveBlending, toneMapped: false, side: DoubleSide,
      }),
      halo: new MeshBasicMaterial({
        map: halo, color: new Color(FOUNDRY.plasma.inner).multiplyScalar(0.5), transparent: true, depthWrite: false,
        blending: AdditiveBlending, toneMapped: false,
      }),
      column: new MeshBasicMaterial({
        map: column, color: new Color(FOUNDRY.plasma.inner).multiplyScalar(0.28), transparent: true, depthWrite: false,
        blending: AdditiveBlending, toneMapped: false, side: DoubleSide,
      }),
      columnWide: new MeshBasicMaterial({
        map: column, color: new Color(FOUNDRY.plasma.outer).multiplyScalar(0.12), transparent: true, depthWrite: false,
        blending: AdditiveBlending, toneMapped: false, side: DoubleSide,
      }),
    };
  }, []);
  useEffect(() => () => {
    materials.halo.dispose(); materials.column.dispose(); materials.columnWide.dispose(); materials.flow.map?.dispose(); materials.flow.dispose();
  }, [materials]);

  const hanging = useRef<Group>(null);
  const ringA = useRef<Group>(null);
  const ringB = useRef<Group>(null);
  const ringC = useRef<Group>(null);
  const motes = useRef<InstancedMesh>(null);
  const heart = useRef<Group>(null);
  const halo = useRef<Group>(null);
  const spin = useRef({ speed: 0.3, angle: 0 });
  const moteSeeds = useMemo(() => Array.from({ length: MOTES }, (_, i) => ({
    radius: 0.95 + ((i * 7) % 9) * 0.07, tilt: ((i * 13) % 17) / 17 * Math.PI, phase: (i / MOTES) * Math.PI * 2, rate: 0.6 + ((i * 5) % 7) * 0.12,
  })), []);
  const tmp = useMemo(() => ({ m: new Matrix4(), v: new Vector3() }), []);

  useFrame(({ camera, clock }, delta) => {
    const step = Math.min(delta, 0.1);
    // Busy floor, fast core: the target pace follows the panes at work, eased so a change never jerks.
    const target = animate ? 0.18 + Math.min(working, 10) * 0.16 : 0;
    spin.current.speed += (target - spin.current.speed) * Math.min(1, step * 1.5);
    spin.current.angle += spin.current.speed * step;
    const a = spin.current.angle;
    // The bands rise with the core's pace.
    if (materials.flow.map) materials.flow.map.offset.y = (materials.flow.map.offset.y - spin.current.speed * step * 0.6) % 1;
    coreSignal.flash = Math.max(0, coreSignal.flash - step * 2.4);
    const flash = animate ? Math.min(1.5, coreSignal.flash) : 0;
    if (ringA.current) ringA.current.rotation.set(a * 1.1, a * 0.4, 0);
    if (ringB.current) ringB.current.rotation.set(0.6, a * -0.8, a * 0.9);
    if (ringC.current) ringC.current.rotation.set(Math.PI / 2 + Math.sin(a * 0.3) * 0.25, 0, a * 0.5);
    const breath = animate ? Math.sin(clock.elapsedTime * (1.2 + working * 0.15)) * 0.06 : 0;
    const glow = 0.8 + Math.min(working, 10) * 0.05 + flash * 0.5;
    if (heart.current) heart.current.scale.setScalar(glow + breath);
    if (halo.current) {
      halo.current.quaternion.copy(camera.quaternion);
      halo.current.scale.setScalar(2.8 * (glow + breath * 2));
    }
    if (motes.current) {
      moteSeeds.forEach((s, i) => {
        const angle = s.phase + a * s.rate * 2;
        tmp.v.set(Math.cos(angle) * s.radius, Math.sin(angle) * s.radius * Math.cos(s.tilt), Math.sin(angle) * s.radius * Math.sin(s.tilt));
        tmp.m.makeTranslation(tmp.v.x, tmp.v.y, tmp.v.z);
        motes.current!.setMatrixAt(i, tmp.m);
      });
      motes.current.instanceMatrix.needsUpdate = true;
    }
    // Step aside when the camera is under the hanging parts.
    if (hanging.current) {
      const close = Math.hypot(camera.position.x - at.x, camera.position.z - at.z) < 4.5 && camera.position.y < HEART_Y + 2.5;
      hanging.current.visible = !close;
    }
  });

  return (
    <group position={[at.x, 0, at.z]}>
      {/* The column of light, from the terminal up into the sky. */}
      <mesh geometry={GEOM.column} material={materials.column} position={[0, COLUMN_H / 2 + 2.2, 0]} renderOrder={3} />
      <mesh geometry={GEOM.columnWide} material={materials.columnWide} position={[0, COLUMN_H / 2 + 2.2, 0]} renderOrder={3} />
      <mesh geometry={GEOM.column} material={materials.flow} position={[0, COLUMN_H / 2 + 2.2, 0]} scale={[1.08, 1, 1.08]} renderOrder={3} />
      <group ref={hanging}>
        {/* Lower crown, fins pointing up. */}
        <group position={[0, 3.25, 0]}>
          <mesh geometry={GEOM.crownLow} material={MAT.steel} rotation={[Math.PI / 2, 0, 0]} castShadow />
          {FINS.map((angle) => (
            <group key={angle} rotation={[0, angle, 0]}>
              <mesh geometry={GEO.box} material={MAT.fin} position={[1.7, 0.35, 0]} scale={[0.08, 0.7, 0.32]} rotation={[0, 0, 0.35]} castShadow />
              <mesh geometry={GEO.box} material={MAT.finLight} position={[1.6, 0.45, 0]} scale={[0.012, 0.5, 0.04]} rotation={[0, 0, 0.35]} />
            </group>
          ))}
        </group>
        {/* Upper crown, fins pointing down, with a gold band. */}
        <group position={[0, 7.4, 0]}>
          <mesh geometry={GEOM.crown} material={MAT.steel} rotation={[Math.PI / 2, 0, 0]} castShadow />
          <mesh geometry={GEOM.crownBand} material={MAT.gold} rotation={[Math.PI / 2, 0, 0]} position={[0, 0.14, 0]} />
          {FINS.map((angle) => (
            <group key={angle} rotation={[0, angle + Math.PI / 10, 0]}>
              <mesh geometry={GEO.box} material={MAT.fin} position={[1.82, -0.42, 0]} scale={[0.08, 0.8, 0.3]} rotation={[0, 0, -0.3]} castShadow />
              <mesh geometry={GEO.box} material={MAT.finLight} position={[1.73, -0.47, 0]} scale={[0.012, 0.55, 0.04]} rotation={[0, 0, -0.3]} />
            </group>
          ))}
        </group>
        <group position={[0, HEART_Y, 0]}>
          <group ref={ringA}><mesh geometry={GEOM.ringA} material={MAT.gold} castShadow /></group>
          <group ref={ringB}><mesh geometry={GEOM.ringB} material={MAT.steel} castShadow /></group>
          <group ref={ringC}><mesh geometry={GEOM.ringC} material={MAT.ringGlow} /></group>
          <group ref={heart}>
            <mesh geometry={GEOM.heart} material={MAT.heart} />
            <mesh geometry={GEOM.shell} material={MAT.shell} />
          </group>
          <instancedMesh ref={motes} args={[GEOM.mote, MAT.mote, MOTES]} frustumCulled={false} />
          <group ref={halo}>
            <mesh material={materials.halo} renderOrder={4}>
              <planeGeometry args={[1, 1]} />
            </mesh>
          </group>
        </group>
      </group>
    </group>
  );
}
