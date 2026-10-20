/**
 * The sky pad's structure (skyPad.ts has its plan): the bridge that carries
 * the boulevard out through the east windows, the round landing deck with its
 * markings, a ring of light round its rim, four light masts, glass rails, and
 * the steel that holds it all out from the tower. The deck and the bridge take
 * clicks like the floor, so the person can walk out by pointing.
 */
import { useEffect, useMemo, useRef } from "react";
import { useFrame, type ThreeEvent } from "@react-three/fiber";
import { CylinderGeometry, MeshBasicMaterial, MeshStandardMaterial, RingGeometry, type Mesh } from "three";
import { cachedCanvasTexture } from "./canvasMaterials";
import { Box, GEO, matte, Railing } from "./OfficeFurniture";
import type { Rect } from "./officeLayout";
import { SKY_PAD, type SkyPad } from "./skyPad";

const PAD_PAINT = {
  deck: "#1d2129",
  seam: "#2b313b",
  ring: "#d4a94e",
  mark: "#e8ecf2",
  glow: "#5fe3ff",
} as const;

let deckTop: MeshStandardMaterial | null = null;
/** The deck's face: graphite plates, the gold landing circle, the chevrons that lead in and the touchdown cross. */
function deckMaterial(): MeshStandardMaterial {
  if (deckTop) return deckTop;
  const map = cachedCanvasTexture("skypad:deck", 1024, 1024, (ctx, w, h) => {
    const c = w / 2;
    ctx.fillStyle = PAD_PAINT.deck;
    ctx.fillRect(0, 0, w, h);
    // Plates: a radial and ring pattern of thin seams.
    ctx.strokeStyle = PAD_PAINT.seam;
    ctx.lineWidth = 3;
    for (let r = 90; r < c; r += 90) { ctx.beginPath(); ctx.arc(c, c, r, 0, Math.PI * 2); ctx.stroke(); }
    for (let i = 0; i < 24; i += 1) {
      const a = (i / 24) * Math.PI * 2;
      ctx.beginPath(); ctx.moveTo(c + Math.cos(a) * 90, c + Math.sin(a) * 90); ctx.lineTo(c + Math.cos(a) * c, c + Math.sin(a) * c); ctx.stroke();
    }
    // The landing circle and an inner ring, in gold.
    ctx.strokeStyle = PAD_PAINT.ring;
    ctx.lineWidth = 16;
    ctx.beginPath(); ctx.arc(c, c, c * 0.78, 0, Math.PI * 2); ctx.stroke();
    ctx.lineWidth = 6;
    ctx.beginPath(); ctx.arc(c, c, c * 0.7, 0, Math.PI * 2); ctx.stroke();
    // Chevrons on four sides, pointing in.
    ctx.fillStyle = PAD_PAINT.mark;
    for (let i = 0; i < 4; i += 1) {
      ctx.save();
      ctx.translate(c, c);
      ctx.rotate((i * Math.PI) / 2);
      for (let k = 0; k < 3; k += 1) {
        const y = c * 0.86 + k * 26;
        ctx.beginPath(); ctx.moveTo(-34, y + 14); ctx.lineTo(0, y - 6); ctx.lineTo(34, y + 14); ctx.lineTo(34, y + 24); ctx.lineTo(0, y + 4); ctx.lineTo(-34, y + 24); ctx.closePath(); ctx.fill();
      }
      ctx.restore();
    }
    // The touchdown mark: a thin cross with a ring.
    ctx.strokeStyle = PAD_PAINT.mark;
    ctx.lineWidth = 8;
    ctx.beginPath(); ctx.moveTo(c - 70, c); ctx.lineTo(c + 70, c); ctx.moveTo(c, c - 70); ctx.lineTo(c, c + 70); ctx.stroke();
    ctx.lineWidth = 5;
    ctx.beginPath(); ctx.arc(c, c, 46, 0, Math.PI * 2); ctx.stroke();
  });
  deckTop = new MeshStandardMaterial({ color: map ? "#ffffff" : PAD_PAINT.deck, map, roughness: 0.55, metalness: 0.35 });
  return deckTop;
}

const STEEL = matte("#2a2e35", { roughness: 0.4, metalness: 0.6 });
const GOLD = matte("#c39a4a", { roughness: 0.3, metalness: 0.85 });
const BRIDGE_DECK = matte("#262b33", { roughness: 0.6, metalness: 0.3 });
const GLOW = new MeshBasicMaterial({ color: PAD_PAINT.glow, toneMapped: false });
const LAMP = new MeshBasicMaterial({ color: "#fff3d6", toneMapped: false });

const SEGMENTS = 64;

/** The rim's glass rail as straight runs round the disc, open where the bridge arrives. */
function rimRuns(pad: SkyPad): [[number, number], [number, number]][] {
  const { x, z, r } = pad.pad;
  const rr = r - 0.25, half = SKY_PAD.bridgeWidth / 2 + 0.3;
  const runs: [[number, number], [number, number]][] = [];
  const count = 28;
  for (let i = 0; i < count; i += 1) {
    const a0 = (i / count) * Math.PI * 2, a1 = ((i + 1) / count) * Math.PI * 2;
    const p0: [number, number] = [x + Math.cos(a0) * rr, z + Math.sin(a0) * rr], p1: [number, number] = [x + Math.cos(a1) * rr, z + Math.sin(a1) * rr];
    // The bridge comes in from the west (the building's side).
    const westOfRim = (p: [number, number]) => p[0] < x && Math.abs(p[1] - z) < half + 0.6;
    if (westOfRim(p0) || westOfRim(p1)) continue;
    runs.push([p0, p1]);
  }
  return runs;
}

export function SkyPadStructure({ pad, bounds, reduced, onFloorClick }: {
  pad: SkyPad; bounds: Rect; reduced: boolean; onFloorClick: (event: ThreeEvent<MouseEvent>) => void;
}) {
  const { x, z, r } = pad.pad;
  const deckGeometry = useMemo(() => new CylinderGeometry(r, r * 0.94, SKY_PAD.thickness, SEGMENTS), [r]);
  const glowGeometry = useMemo(() => new RingGeometry(r - 0.12, r + 0.05, SEGMENTS * 2).rotateX(-Math.PI / 2), [r]);
  const runs = useMemo(() => rimRuns(pad), [pad]);
  const glow = useRef<Mesh>(null);
  useFrame(({ clock }) => {
    // The rim's light breathes slowly; with reduced motion it simply stays on.
    if (glow.current && !reduced) (glow.current.material as MeshBasicMaterial).opacity = 0.75 + 0.25 * Math.sin(clock.elapsedTime * 1.4);
  });
  const glowMaterial = useMemo(() => {
    const m = GLOW.clone();
    m.transparent = true;
    return m;
  }, []);
  useEffect(() => () => { deckGeometry.dispose(); glowGeometry.dispose(); glowMaterial.dispose(); }, [deckGeometry, glowGeometry, glowMaterial]);
  const bridgeX0 = bounds.maxX, bridgeX1 = x - r + 0.6;
  const bridgeLength = bridgeX1 - bridgeX0, bridgeMid = (bridgeX0 + bridgeX1) / 2;
  const masts = [Math.PI / 4, (3 * Math.PI) / 4, (5 * Math.PI) / 4, (7 * Math.PI) / 4].map((a) => [x + Math.cos(a) * (r - 0.9), z + Math.sin(a) * (r - 0.9)] as const);
  return (
    <group>
      {/* The bridge: deck, gold kerbs, glass rails and the girder under it. */}
      <mesh geometry={GEO.box} material={BRIDGE_DECK} position={[bridgeMid, -0.25, z]} scale={[bridgeLength, 0.5, SKY_PAD.bridgeWidth]} receiveShadow onClick={onFloorClick} />
      {[-1, 1].map((side) => (
        <group key={side}>
          <Box size={[bridgeLength, 0.08, 0.16]} position={[bridgeMid, 0.04, z + side * (SKY_PAD.bridgeWidth / 2 - 0.08)]} material={GOLD} cast={false} />
          <Railing from={[bridgeX0 + 0.1, z + side * (SKY_PAD.bridgeWidth / 2 - 0.2)]} to={[bridgeX1, z + side * (SKY_PAD.bridgeWidth / 2 - 0.2)]} />
        </group>
      ))}
      <Box size={[bridgeLength, 1.4, 1.2]} position={[bridgeMid, -1.2, z]} material={STEEL} cast={false} />

      {/* The deck: its painted face on top, steel round its edge, a gold band at its lip. */}
      <mesh geometry={deckGeometry} material={STEEL} position={[x, -SKY_PAD.thickness / 2, z]} receiveShadow />
      <mesh position={[x, 0.004, z]} rotation={[-Math.PI / 2, 0, 0]} receiveShadow onClick={onFloorClick} material={deckMaterial()}>
        <circleGeometry args={[r - 0.05, SEGMENTS]} />
      </mesh>
      <mesh ref={glow} geometry={glowGeometry} material={glowMaterial} position={[x, 0.012, z]} />
      {runs.map(([from, to], i) => <Railing key={i} from={from} to={to} height={0.9} />)}

      {/* Four light masts round the rim: glowing lamps, no light sources (a light per mast would cost every lit
          material of the floor a recompile on arrival and a share of every pixel). */}
      {masts.map(([mx, mz], i) => (
        <group key={i} position={[mx, 0, mz]}>
          <mesh geometry={GEO.cyl} material={STEEL} position={[0, 1.6, 0]} scale={[0.09, 3.2, 0.09]} />
          <mesh geometry={GEO.box} material={LAMP} position={[0, 3.25, 0]} scale={[0.36, 0.14, 0.36]} />
        </group>
      ))}

      {/* The cantilever: two raking struts from under the deck back into the tower, and a ring beam under the rim. */}
      {[-1, 1].map((side) => {
        const fromX = x - r * 0.3, fromZ = z + side * r * 0.45, toX = bounds.maxX - 0.15, toZ = z + side * 5, drop = 22;
        const dx = toX - fromX, dz = toZ - fromZ, length = Math.hypot(dx, drop, dz);
        return (
          <mesh key={side} geometry={GEO.box} material={STEEL} position={[(fromX + toX) / 2, -SKY_PAD.thickness - drop / 2, (fromZ + toZ) / 2]}
            rotation={[0, -Math.atan2(dz, dx), Math.atan2(-drop, Math.hypot(dx, dz))]} scale={[length, 0.9, 0.9]} />
        );
      })}
      <mesh geometry={GEO.cyl} material={STEEL} position={[x, -SKY_PAD.thickness - 1.2, z]} scale={[r * 0.55, 2.4, r * 0.55]} />
    </group>
  );
}
