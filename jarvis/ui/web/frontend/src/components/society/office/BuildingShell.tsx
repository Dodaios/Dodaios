/**
 * What makes the agents floor (and the Level Hall above it) a floor of a
 * building instead of a plate in space: a window wall with steel mullions and
 * a ceiling edge on the far sides, the glass balustrade on the sides the
 * camera looks in through, and outside the city in the singularity
 * (SingularityCity.tsx), the building's own glass tower falling away under
 * the slab into it.
 *
 * The floor is shown like a cut-open model: a side's window wall stands only
 * while the camera is on the opposite side of the floor, so it is always the
 * backdrop and never in the way; the other sides keep the low balustrade.
 *
 * Purely visual and out of reach: everything stands on or beyond the slab's
 * edge, outside the walkable floor. Nothing here casts a shadow.
 */
import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Group, MeshStandardMaterial } from "three";
import { Instances, type Placement } from "./Instances";
import { Box, GEO, matte, Railing } from "./OfficeFurniture";
import type { OfficeLayout, Rect } from "./officeLayout";
import { SingularityCity } from "./SingularityCity";

/** The window wall: its height, the mullion pitch, and how far the ceiling edge reaches into the floor. */
export const FACADE = { h: 3.4, pitch: 2.9, soffit: 1.1 } as const;
/** A side's window wall changes only once the camera is this far past the floor's middle, so it never flickers. */
const SIDE_DEAD_BAND_M = 4;

const SHELL = {
  steel: matte("#23262b", { roughness: 0.45, metalness: 0.4 }),
  soffit: matte("#f1ede6", { roughness: 0.9 }),
  glass: new MeshStandardMaterial({ color: "#cfe6f7", transparent: true, opacity: 0.16, roughness: 0.08, metalness: 0.1, depthWrite: false }),
};

type Side = "north" | "south" | "west" | "east";

/** One side's window wall, in its own frame: it runs along +x, the floor lies towards +z. */
function WindowWall({ length }: { length: number }) {
  const mullions = useMemo<Placement[]>(() => {
    const count = Math.max(2, Math.round(length / FACADE.pitch) + 1);
    return Array.from({ length: count }, (_, i) => ({
      position: [-length / 2 + (length * i) / (count - 1), FACADE.h / 2, 0] as [number, number, number], scale: [0.07, FACADE.h, 0.12] as [number, number, number],
    }));
  }, [length]);
  return (
    <group>
      <Box size={[length, 0.22, 0.14]} position={[0, 0.11, 0]} material={SHELL.steel} cast={false} />
      <Box size={[length, FACADE.h - 0.5, 0.03]} position={[0, 0.22 + (FACADE.h - 0.5) / 2, 0]} material={SHELL.glass} cast={false} />
      <Box size={[length, 0.28, 0.2]} position={[0, FACADE.h - 0.14, 0]} material={SHELL.steel} cast={false} />
      {/* The ceiling's edge: a pale band running into the floor from the head of the wall. */}
      <Box size={[length, 0.1, FACADE.soffit]} position={[0, FACADE.h + 0.05, FACADE.soffit / 2 - 0.1]} material={SHELL.soffit} cast={false} />
      <Instances geometry={GEO.box} material={SHELL.steel} items={mullions} cast={false} />
    </group>
  );
}

/**
 * The floor's four edges. Each has a window wall and a balustrade; the wall
 * shows on the sides the camera looks towards, the balustrade on the others.
 */
function Edges({ bounds }: { bounds: Rect }) {
  const { minX, maxX, minZ, maxZ } = bounds;
  const cx = (minX + maxX) / 2, cz = (minZ + maxZ) / 2, w = maxX - minX, d = maxZ - minZ;
  const walls = useRef<Partial<Record<Side, Group | null>>>({});
  const rails = useRef<Partial<Record<Side, Group | null>>>({});
  // The home view looks from the south-east: north and west are the backdrop.
  const shown = useRef<Record<Side, boolean>>({ north: true, west: true, south: false, east: false });
  useFrame(({ camera }) => {
    const dx = camera.position.x - cx, dz = camera.position.z - cz;
    const next = shown.current;
    if (Math.abs(dz) > SIDE_DEAD_BAND_M) { next.north = dz > 0; next.south = dz < 0; }
    if (Math.abs(dx) > SIDE_DEAD_BAND_M) { next.west = dx > 0; next.east = dx < 0; }
    for (const side of ["north", "south", "west", "east"] as const) {
      const wall = walls.current[side], rail = rails.current[side];
      if (wall) wall.visible = next[side];
      if (rail) rail.visible = !next[side];
    }
  });
  // The walls stand just inside the slab's edge and meet in its corners; the balustrade keeps its own line.
  const inset = 0.12, rail = 0.2;
  // A wall's frame: +x along the edge, +z into the floor.
  const sides: { side: Side; position: [number, number, number]; rotationY: number; length: number; from: [number, number]; to: [number, number] }[] = [
    { side: "north", position: [cx, 0, minZ + inset], rotationY: 0, length: w - inset * 2, from: [minX + rail, minZ + rail], to: [maxX - rail, minZ + rail] },
    { side: "south", position: [cx, 0, maxZ - inset], rotationY: Math.PI, length: w - inset * 2, from: [maxX - rail, maxZ - rail], to: [minX + rail, maxZ - rail] },
    { side: "west", position: [minX + inset, 0, cz], rotationY: Math.PI / 2, length: d - inset * 2, from: [minX + rail, maxZ - rail], to: [minX + rail, minZ + rail] },
    { side: "east", position: [maxX - inset, 0, cz], rotationY: -Math.PI / 2, length: d - inset * 2, from: [maxX - rail, minZ + rail], to: [maxX - rail, maxZ - rail] },
  ];
  return (
    <group>
      {sides.map(({ side, position, rotationY, length, from, to }) => (
        <group key={side}>
          <group ref={(g) => { walls.current[side] = g; }} position={position} rotation={[0, rotationY, 0]} visible={shown.current[side]}>
            <WindowWall length={length} />
          </group>
          <group ref={(g) => { rails.current[side] = g; }} visible={!shown.current[side]}>
            <Railing from={from} to={to} />
          </group>
        </group>
      ))}
    </group>
  );
}

export function BuildingShell({ layout, reduced = false }: { layout: OfficeLayout; reduced?: boolean }) {
  return (
    <group>
      <SingularityCity bounds={layout.bounds} reduced={reduced} />
      <Edges bounds={layout.bounds} />
    </group>
  );
}
