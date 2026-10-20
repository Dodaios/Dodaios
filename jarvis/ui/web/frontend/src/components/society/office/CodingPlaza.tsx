/**
 * The coding floor's town square: where the concourse meets the cross aisle
 * round the spawn terminal, a round terrazzo medallion with brass rings and a
 * compass of fine brass lines is set into the oak, under a soft pool of warm
 * light — the floor's centre, readable from every desk.
 *
 * Purely visual and flat, so navigation is unchanged.
 */
import { useEffect, useMemo } from "react";
import { AdditiveBlending, MeshBasicMaterial, MeshStandardMaterial } from "three";
import { cachedCanvasTexture } from "./canvasMaterials";
import type { Point } from "./officeLayout";
import { CODING_SCENE } from "./officePalette";

/** The medallion's radius (m). */
export const PLAZA_RADIUS = 2.7;

/** Terrazzo with brass rings and a compass rose of fine brass lines, on a transparent ground. */
function drawMedallion(ctx: CanvasRenderingContext2D, w: number, h: number): void {
  ctx.clearRect(0, 0, w, h);
  const c = w / 2, r = w / 2 - 2;
  let seed = 0x7e44a20;
  const rand = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 0x1_0000_0000; };
  // The terrazzo field: a warm pale ground with small chips.
  ctx.save();
  ctx.beginPath();
  ctx.arc(c, c, r, 0, Math.PI * 2);
  ctx.clip();
  ctx.fillStyle = CODING_SCENE.plaza.terrazzo;
  ctx.fillRect(0, 0, w, h);
  for (let i = 0; i < 2600; i += 1) {
    ctx.fillStyle = CODING_SCENE.plaza.chips[Math.floor(rand() * CODING_SCENE.plaza.chips.length)];
    const s = 1.5 + rand() * 3.5;
    ctx.fillRect(rand() * w, rand() * h, s, s * (0.6 + rand() * 0.6));
  }
  ctx.restore();
  // Brass: an outer band, two inner rings and the compass lines between them.
  ctx.strokeStyle = CODING_SCENE.brass;
  ctx.lineWidth = w * 0.018;
  ctx.beginPath(); ctx.arc(c, c, r - ctx.lineWidth / 2, 0, Math.PI * 2); ctx.stroke();
  ctx.lineWidth = w * 0.006;
  ctx.beginPath(); ctx.arc(c, c, r * 0.86, 0, Math.PI * 2); ctx.stroke();
  ctx.beginPath(); ctx.arc(c, c, r * 0.5, 0, Math.PI * 2); ctx.stroke();
  ctx.lineWidth = w * 0.004;
  for (let i = 0; i < 16; i += 1) {
    const a = (i / 16) * Math.PI * 2, inner = i % 4 === 0 ? 0.5 : 0.62;
    ctx.beginPath();
    ctx.moveTo(c + Math.cos(a) * r * inner, c + Math.sin(a) * r * inner);
    ctx.lineTo(c + Math.cos(a) * r * 0.86, c + Math.sin(a) * r * 0.86);
    ctx.stroke();
  }
}

/** A soft round pool of warm light on the floor (white centre fading out; the material tints it). */
function drawPool(ctx: CanvasRenderingContext2D, w: number, h: number): void {
  const g = ctx.createRadialGradient(w / 2, h / 2, w * 0.2, w / 2, h / 2, w / 2);
  g.addColorStop(0, "rgba(255,255,255,0.55)");
  g.addColorStop(0.6, "rgba(255,255,255,0.3)");
  g.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, w, h);
}

export function CodingPlaza({ at }: { at: Point }) {
  const surfaces = useMemo(() => ({
    medallion: new MeshStandardMaterial({
      map: cachedCanvasTexture("coding:medallion", 1024, 1024, drawMedallion), transparent: true, roughness: 0.4, metalness: 0.1,
      polygonOffset: true, polygonOffsetFactor: -2,
    }),
    pool: new MeshBasicMaterial({
      map: cachedCanvasTexture("coding:plaza-pool", 128, 128, drawPool), color: CODING_SCENE.pendant.pool, transparent: true,
      opacity: 0.3, blending: AdditiveBlending, depthWrite: false,
    }),
  }), []);
  useEffect(() => () => { surfaces.medallion.dispose(); surfaces.pool.dispose(); }, [surfaces]);
  return (
    <group position={[at.x, 0, at.z]}>
      <mesh position={[0, 0.006, 0]} rotation={[-Math.PI / 2, 0, 0]} material={surfaces.medallion} receiveShadow>
        <circleGeometry args={[PLAZA_RADIUS, 96]} />
      </mesh>
      <mesh position={[0, 0.009, 0]} rotation={[-Math.PI / 2, 0, 0]} material={surfaces.pool}>
        <planeGeometry args={[PLAZA_RADIUS * 2.4, PLAZA_RADIUS * 2.4]} />
      </mesh>
    </group>
  );
}
