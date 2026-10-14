/**
 * The agents floor's ground between the studios, and the atrium's crown: the
 * two boulevards paved in the limestone of the window band, the atrium's
 * round inlay under the spawn point with a ring of light over it, the free
 * plot taped out for the next team with its lettering on the floor, and a
 * carpet of its own under every commons (moss in a garden court, slate felt
 * under the focus booths, warm tiles in the café).
 *
 * The ring is a light fitting, not a glow: a steel band the size of the disc
 * whose inner face is the lamp, hung on six rods from the ceiling line, each
 * under its own small canopy.
 *
 * The ground is flat and takes no pointer events, so walking and clicking the
 * floor work through it; the ring hangs above every head. Each surface is
 * one mesh; all of it costs about twenty draw calls at any campus size.
 */
import { useEffect, useMemo } from "react";
import { BackSide, CylinderGeometry, MeshStandardMaterial, RingGeometry, Shape } from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import { useT } from "@/i18n";
import { AGENTS_SCENE, limestone } from "./AgentsFloorLook";
import { FACADE } from "./BuildingShell";
import { cachedCanvasTexture } from "./canvasMaterials";
import { Instances, type Placement } from "./CodingFloorAmbience";
import { GEO, matte } from "./OfficeFurniture";
import type { CampusZone, CampusZoneKind, OfficeLayout, Rect } from "./officeLayout";

/**
 * Heights of the layers. The plank floor lies at 1 mm; whatever overlaps something else is at least a millimetre
 * above it, which is what the depth buffer still tells apart from the far end of the zoom.
 */
const Y = { paving: 0.003, moss: 0.003, field: 0.004, mark: 0.005 } as const;
/** The window band's width (see AgentsSlab): the main boulevard's paving runs out to it. */
const WINDOW_BAND = 1.35;
/** The atrium's disc lies between its two flights of step seating; the ring of light hangs over its rim. */
const ATRIUM_R = 4.2;
/** The ring: its top's height, the band's height and thickness, and how many rods carry it up to the ceiling line. */
const ATRIUM_RING = { y: 2.9, band: 0.11, rods: 6 } as const;
const RING_T = 0.03;
/** The band's steel: its outer face and its top edge. Its origin is the ring's middle at the height of its top. */
const RING_BODY = mergeGeometries([
  new CylinderGeometry(ATRIUM_R, ATRIUM_R, ATRIUM_RING.band, 72, 1, true).translate(0, -ATRIUM_RING.band / 2, 0),
  new RingGeometry(ATRIUM_R - RING_T, ATRIUM_R, 72).rotateX(-Math.PI / 2),
]);
/** The lamp: the band's inner face, seen from inside the ring. */
const RING_LAMP = new CylinderGeometry(ATRIUM_R - RING_T, ATRIUM_R - RING_T, ATRIUM_RING.band - 0.02, 72, 1, true).translate(0, -ATRIUM_RING.band / 2, 0);

/** The rods the ring hangs on, and the canopy at the head of each, round the ring's own middle. */
const RING_RODS: Placement[] = Array.from({ length: ATRIUM_RING.rods }, (_, i) => {
  const a = ((i + 0.5) / ATRIUM_RING.rods) * Math.PI * 2, r = ATRIUM_R - RING_T / 2;
  const x = Math.cos(a) * r, z = Math.sin(a) * r, drop = FACADE.h - ATRIUM_RING.y;
  return [
    { position: [x, ATRIUM_RING.y + drop / 2, z], scale: [0.016, drop, 0.016] },
    { position: [x, FACADE.h - 0.012, z], scale: [0.12, 0.024, 0.12] },
  ] satisfies Placement[];
}).flat();

const GROUND = {
  inlay: matte(AGENTS_SCENE.stone.inlay, { roughness: 0.4, metalness: 0.45 }),
  disc: matte("#f1ece3", { roughness: 0.5 }),
  /** Floor marking tape. */
  tape: matte("#e2bc62", { roughness: 0.75 }),
  steel: matte("#23262b", { roughness: 0.45, metalness: 0.4 }),
  /** Warm and tone-mapped: a lamp behind a diffuser, never a white line. */
  lamp: new MeshStandardMaterial({ color: "#f3cf9c", emissive: "#ffbf78", emissiveIntensity: 0.85, roughness: 0.6, side: BackSide }),
};

/** A commons' carpet: a darker rim round a lighter field. The library lies on its own rug and the plain oak. */
const CARPETS: Partial<Record<CampusZoneKind, { edge: MeshStandardMaterial; field: MeshStandardMaterial }>> = {
  garden: { edge: matte("#a9b795", { roughness: 1 }), field: matte("#c7d1b5", { roughness: 1 }) },
  booths: { edge: matte("#9aa5b1", { roughness: 1 }), field: matte("#c3cbd3", { roughness: 1 }) },
  cafe: { edge: matte("#c9ad8c", { roughness: 0.7 }), field: matte("#eadfcd", { roughness: 0.7 }) },
};

/** A flat rounded rectangle in the XY plane, laid on the floor by its mesh's rotation. */
function roundedRect(w: number, d: number, r: number): Shape {
  const x = -w / 2, y = -d / 2;
  const shape = new Shape();
  shape.moveTo(x + r, y);
  shape.lineTo(x + w - r, y);
  shape.quadraticCurveTo(x + w, y, x + w, y + r);
  shape.lineTo(x + w, y + d - r);
  shape.quadraticCurveTo(x + w, y + d, x + w - r, y + d);
  shape.lineTo(x + r, y + d);
  shape.quadraticCurveTo(x, y + d, x, y + d - r);
  shape.lineTo(x, y + r);
  shape.quadraticCurveTo(x, y, x + r, y);
  return shape;
}

const centre = (r: Rect): [number, number] => [(r.minX + r.maxX) / 2, (r.minZ + r.maxZ) / 2];

/** One paved street: limestone at the stone's own scale, whatever the street's size. */
function Paving({ rect }: { rect: Rect }) {
  const w = rect.maxX - rect.minX, d = rect.maxZ - rect.minZ;
  const material = useMemo(() => limestone(w, d), [w, d]);
  useEffect(() => () => { material.map?.dispose(); material.dispose(); }, [material]);
  const [x, z] = centre(rect);
  return (
    <mesh position={[x, Y.paving, z]} rotation={[-Math.PI / 2, 0, 0]} material={material} receiveShadow>
      <planeGeometry args={[w, d]} />
    </mesh>
  );
}

/** The carpet of a commons: a darker rim round a lighter field. */
function Carpet({ zone, edge, field }: { zone: CampusZone; edge: MeshStandardMaterial; field: MeshStandardMaterial }) {
  const w = zone.maxX - zone.minX - 0.7, d = zone.maxZ - zone.minZ - 0.7;
  const shapes = useMemo(() => ({ edge: roundedRect(w, d, 0.6), field: roundedRect(w - 0.3, d - 0.3, 0.5) }), [w, d]);
  const [x, z] = centre(zone);
  return (
    <group>
      <mesh position={[x, Y.moss, z]} rotation={[-Math.PI / 2, 0, 0]} material={edge} receiveShadow>
        <shapeGeometry args={[shapes.edge, 6]} />
      </mesh>
      <mesh position={[x, Y.field, z]} rotation={[-Math.PI / 2, 0, 0]} material={field} receiveShadow>
        <shapeGeometry args={[shapes.field, 6]} />
      </mesh>
    </group>
  );
}

const PLOT_TEXT = { w: 1024, h: 320 } as const;
const plotTexts = new Map<string, MeshStandardMaterial>();
/** The plot's lettering, painted on the floor: what the place is for, and where a team is started. */
function plotText(title: string, hint: string): MeshStandardMaterial {
  const key = `${title}\n${hint}`;
  let material = plotTexts.get(key);
  if (!material) {
    const map = cachedCanvasTexture(`campus:plot:${key}`, PLOT_TEXT.w, PLOT_TEXT.h, (ctx, w, h) => {
      ctx.clearRect(0, 0, w, h);
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      const fit = (text: string, px: number, weight: number, y: number, fill: string) => {
        let size = px;
        const font = (s: number) => `${weight} ${s}px Inter, system-ui, -apple-system, 'Segoe UI', sans-serif`;
        ctx.font = font(size);
        while (size > px * 0.5 && ctx.measureText(text).width > w - 48) { size -= 2; ctx.font = font(size); }
        ctx.fillStyle = fill;
        ctx.fillText(text, w / 2, y);
      };
      fit(title.toLocaleUpperCase(), 92, 700, 118, "#8a7350");
      fit(hint, 56, 500, 232, "#9a8a70");
    });
    material = new MeshStandardMaterial({ color: "#ffffff", map, transparent: true, alphaTest: 0.25, roughness: 0.9, visible: !!map });
    plotTexts.set(key, material);
  }
  return material;
}

/** Tape on the floor: the length of a dash, the gap to the next, a corner's legs and the tape's width. */
const TAPE = { dash: 0.55, gap: 0.4, corner: 0.9, w: 0.06 } as const;

/** The dashes of a taped outline w × d round the origin: solid corners, dashed runs between them. */
function tapeOutline(w: number, d: number): Placement[] {
  const out: Placement[] = [];
  const piece = (x: number, z: number, along: "x" | "z", length: number) => {
    out.push({ position: [x, Y.mark, z], scale: along === "x" ? [length, 0.003, TAPE.w] : [TAPE.w, 0.003, length] });
  };
  const run = (length: number, place: (offset: number, len: number) => void) => {
    const inner = length - TAPE.corner * 2;
    const count = Math.max(1, Math.floor((inner - TAPE.gap) / (TAPE.dash + TAPE.gap)));
    const dash = (inner - TAPE.gap * (count + 1)) / count;
    place(-length / 2 + TAPE.corner / 2, TAPE.corner);
    place(length / 2 - TAPE.corner / 2, TAPE.corner);
    for (let i = 0; i < count; i += 1) place(-inner / 2 + TAPE.gap + dash / 2 + i * (dash + TAPE.gap), dash);
  };
  for (const z of [-d / 2, d / 2]) run(w, (offset, len) => piece(offset, z, "x", len));
  for (const x of [-w / 2, w / 2]) run(d, (offset, len) => piece(x, offset, "z", len));
  return out;
}

/**
 * The free plot: the bare floor taped out like a site about to be moved into, with its lettering facing the
 * lobby. The stand where a team is started, the crates and the plant are the plan's own pieces.
 */
function Plot({ zone }: { zone: CampusZone }) {
  const t = useT();
  const w = zone.maxX - zone.minX - 0.5, d = zone.maxZ - zone.minZ - 0.5;
  const [x, z] = centre(zone);
  const tape = useMemo(() => tapeOutline(w, d), [w, d]);
  const textW = Math.min(w - 1.2, 5.6), textH = (textW * PLOT_TEXT.h) / PLOT_TEXT.w;
  return (
    <group position={[x, 0, z]}>
      <Instances geometry={GEO.box} material={GROUND.tape} items={tape} cast={false} />
      <mesh position={[0, Y.mark, -0.4]} rotation={[-Math.PI / 2, 0, 0]} material={plotText(t("society.office.plot_free"), t("society.office.plot_hint"))}>
        <planeGeometry args={[textW, textH]} />
      </mesh>
    </group>
  );
}

export function CampusGround({ layout }: { layout: OfficeLayout }) {
  const zones = layout.zones;
  const paved = useMemo(() => {
    const boulevard = zones?.find((z) => z.kind === "boulevard");
    const plaza = zones?.find((z) => z.kind === "plaza");
    if (!boulevard || !plaza) return null;
    return {
      // The boulevard's paving stops at the plaza on both sides: two surfaces never share a plane.
      streets: [{ ...boulevard, maxZ: plaza.minZ }, { ...boulevard, minZ: plaza.maxZ }].filter((r) => r.maxZ - r.minZ > 0.01),
      // The main boulevard's paving meets the stone band along both windows.
      plaza: { ...plaza, minX: layout.bounds.minX + WINDOW_BAND, maxX: layout.bounds.maxX - WINDOW_BAND },
      atrium: centre(plaza),
    };
  }, [zones, layout.bounds]);
  if (!zones || !paved) return null;
  const [ax, az] = paved.atrium;
  return (
    <group>
      {paved.streets.map((rect) => <Paving key={rect.minZ} rect={rect} />)}
      <Paving rect={paved.plaza} />
      {/* The atrium: a pale disc inside a bronze ring, the spawn point in its middle. */}
      <mesh position={[ax, Y.field, az]} rotation={[-Math.PI / 2, 0, 0]} material={GROUND.disc} receiveShadow>
        <circleGeometry args={[ATRIUM_R, 64]} />
      </mesh>
      <mesh position={[ax, Y.mark, az]} rotation={[-Math.PI / 2, 0, 0]} material={GROUND.inlay} receiveShadow>
        <ringGeometry args={[ATRIUM_R - 0.07, ATRIUM_R + 0.07, 64]} />
      </mesh>
      <mesh position={[ax, Y.mark, az]} rotation={[-Math.PI / 2, 0, 0]} material={GROUND.inlay} receiveShadow>
        <ringGeometry args={[2.05, 2.11, 48]} />
      </mesh>
      {/* The atrium's crown: a steel band hung from the ceiling line, its inner face the lamp. */}
      <mesh geometry={RING_BODY} material={GROUND.steel} position={[ax, ATRIUM_RING.y, az]} />
      <mesh geometry={RING_LAMP} material={GROUND.lamp} position={[ax, ATRIUM_RING.y, az]} />
      <group position={[ax, 0, az]}><Instances geometry={GEO.box} material={GROUND.steel} items={RING_RODS} cast={false} /></group>
      {zones.map((zone) => {
        if (zone.kind === "plot") return <Plot key={zone.id} zone={zone} />;
        const carpet = CARPETS[zone.kind];
        return carpet ? <Carpet key={zone.id} zone={zone} edge={carpet.edge} field={carpet.field} /> : null;
      })}
    </group>
  );
}
