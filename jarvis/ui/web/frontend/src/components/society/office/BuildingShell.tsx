/**
 * What makes the agents floor (and the Level Hall above it) a floor of a
 * building instead of a plate in space: the tower's body under the slab, a
 * window wall with steel mullions and a ceiling edge on the far sides, the
 * glass balustrade on the sides the camera looks in through, and a city at
 * night far below.
 *
 * The floor is shown like a cut-open model: a side's window wall stands only
 * while the camera is on the opposite side of the floor, so it is always the
 * backdrop and never in the way; the other sides keep the low balustrade.
 *
 * The city is a backdrop and stays one: a few dozen unlit towers a shade
 * lighter than the deep navy night, a long way off and far below the floor,
 * the near ones lowest. One window in twenty is lit, dimly; every tower sinks
 * into the sky's own colour towards its foot and with its distance from the
 * building, and the faintest glow lies over the streets where detail would
 * be. The scene's sun never reaches them. Apart from the sparse windows
 * nothing out there is brighter than a dark navy (#1a2233): the office is
 * always the brightest and most detailed thing on screen.
 *
 * Purely visual and out of reach: everything stands on or beyond the slab's
 * edge, outside the walkable floor. The city is four draw calls (three tower
 * classes and the haze), the shell about two dozen, at any floor size.
 * Nothing casts a shadow.
 */
import { useEffect, useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { AdditiveBlending, BufferGeometry, Float32BufferAttribute, Group, MeshBasicMaterial, MeshStandardMaterial, RepeatWrapping, RingGeometry } from "three";
import { cachedCanvasTexture } from "./canvasMaterials";
import { Instances, type Placement } from "./CodingFloorAmbience";
import { Box, GEO, matte, Railing } from "./OfficeFurniture";
import type { OfficeLayout, Rect } from "./officeLayout";

/** The window wall: its height, the mullion pitch, and how far the ceiling edge reaches into the floor. */
export const FACADE = { h: 3.4, pitch: 2.9, soffit: 1.1 } as const;
/** Metres of façade one repeat of the window texture covers (four windows across, four storeys up). */
const WINDOW_TILE_M = 12;
/** A side's window wall changes only once the camera is this far past the floor's middle, so it never flickers. */
const SIDE_DEAD_BAND_M = 4;

const SHELL = {
  steel: matte("#23262b", { roughness: 0.45, metalness: 0.4 }),
  soffit: matte("#f1ede6", { roughness: 0.9 }),
  glass: new MeshStandardMaterial({ color: "#cfe6f7", transparent: true, opacity: 0.16, roughness: 0.08, metalness: 0.1, depthWrite: false }),
  roof: matte("#0f1420", { roughness: 0.95 }),
};

function lcg(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 0x1_0000_0000;
  };
}

/** A tower's cladding at night: a shade lighter than the sky (#0d1320), so a near tower reads against it. */
const CLADDING = "#141b2b";

let windows: MeshBasicMaterial | null = null;
/**
 * A tower's face at night, unlit so the scene's sun never touches it: cladding a shade off the sky and rows of
 * windows of which about one in twenty is lit, dimly and mostly warm. One 128 px tile for the whole city; a
 * tower's own colour (towards the sky's with distance) and its vertex colours (towards the foot) multiply it.
 */
function windowMaterial(): MeshBasicMaterial {
  if (!windows) {
    const map = cachedCanvasTexture("shell:windows:night", 128, 128, (ctx, w, h) => {
      const rand = lcg(0xc17e);
      ctx.fillStyle = CLADDING;
      ctx.fillRect(0, 0, w, h);
      const cols = 8, rows = 8, cw = w / cols, rh = h / rows;
      for (let r = 0; r < rows; r += 1) {
        for (let c = 0; c < cols; c += 1) {
          const roll = rand();
          ctx.fillStyle = roll < 0.04 ? "#6f5b3c" : roll < 0.055 ? "#3c475c" : "#101726";
          ctx.fillRect(c * cw + 4, r * rh + 5, cw - 8, rh - 11);
        }
      }
    });
    if (map) { map.wrapS = map.wrapT = RepeatWrapping; map.anisotropy = 4; }
    windows = new MeshBasicMaterial({ color: map ? "#ffffff" : CLADDING, map, vertexColors: true });
  }
  return windows;
}

/** How dark a tower's foot is against its roof line (in linear light): at the foot the cladding is about the sky's colour. */
const FOOT_SHADE = 0.72;

/**
 * A tower w × h × d, its roof at y = 0: four faces with texture coordinates
 * in metres of façade (every tower shows windows of the same size) and the
 * roof, which takes the cladding's colour from the tile's margin. The vertex
 * colours darken the faces towards the foot.
 */
function towerGeometry(w: number, h: number, d: number): BufferGeometry {
  const positions: number[] = [], normals: number[] = [], uvs: number[] = [], colours: number[] = [], index: number[] = [];
  const face = (ax: number, az: number, bx: number, bz: number, nx: number, nz: number) => {
    const at = positions.length / 3, run = Math.hypot(bx - ax, bz - az) / WINDOW_TILE_M, rise = h / WINDOW_TILE_M;
    positions.push(ax, -h, az, bx, -h, bz, bx, 0, bz, ax, 0, az);
    for (let i = 0; i < 4; i += 1) normals.push(nx, 0, nz);
    uvs.push(0, 0, run, 0, run, rise, 0, rise);
    colours.push(FOOT_SHADE, FOOT_SHADE, FOOT_SHADE, FOOT_SHADE, FOOT_SHADE, FOOT_SHADE, 1, 1, 1, 1, 1, 1);
    index.push(at, at + 1, at + 2, at, at + 2, at + 3);
  };
  const x = w / 2, z = d / 2;
  face(-x, z, x, z, 0, 1);
  face(x, z, x, -z, 1, 0);
  face(x, -z, -x, -z, 0, -1);
  face(-x, -z, -x, z, -1, 0);
  // The roof: every corner samples the tile's margin, which is plain cladding.
  const at = positions.length / 3;
  positions.push(-x, 0, z, x, 0, z, x, 0, -z, -x, 0, -z);
  for (let i = 0; i < 4; i += 1) { normals.push(0, 1, 0); uvs.push(0.008, 0.008); colours.push(1, 1, 1); }
  index.push(at, at + 1, at + 2, at, at + 2, at + 3);
  const geometry = new BufferGeometry();
  geometry.setAttribute("position", new Float32BufferAttribute(positions, 3));
  geometry.setAttribute("normal", new Float32BufferAttribute(normals, 3));
  geometry.setAttribute("uv", new Float32BufferAttribute(uvs, 2));
  geometry.setAttribute("color", new Float32BufferAttribute(colours, 3));
  geometry.setIndex(index);
  return geometry;
}

/** Tower sizes of the city: every tower of a class shares one geometry, so each class is one draw call. */
const TOWER_CLASSES = [{ w: 14, d: 14, h: 110 }, { w: 22, d: 16, h: 110 }, { w: 30, d: 20, h: 110 }] as const;
/**
 * The city's reserve. `clear`: empty air round the building before the first tower. `reach`: how far the city
 * goes on from there. `roofTop`: the highest any roof comes, metres below the floor; the towers nearest the
 * building lie `nearDrop` lower still, and each a random share of `roofDrop` below that. `near`/`far`: a
 * tower's tint beside the clear air and at the city's far end, where the cladding comes out at the sky's colour.
 */
const CITY = { clear: 62, reach: 170, towers: 60, roofTop: -24, nearDrop: 22, roofDrop: 56, near: 1, far: 0.8, haze: -64 } as const;

const grey = (v: number): string => {
  const c = Math.round(Math.min(1, Math.max(0, v)) * 255).toString(16).padStart(2, "0");
  return `#${c}${c}${c}`;
};

/** How bright the haze is at each of its rings, from the building outwards: nothing, rising, full, fading, nothing. */
const HAZE_RINGS = [0, 0.55, 1, 0.45, 0] as const;
/**
 * The glow of streets too far down to see, added over the night. In LINEAR light, where the sky itself is about
 * (0.004, 0.007, 0.014): at its brightest the haze lifts the navy to about #181b27 and no further.
 */
const HAZE_TONE = [0.005, 0.0045, 0.006] as const;
const HAZE_MATERIAL = new MeshBasicMaterial({
  vertexColors: true, transparent: true, blending: AdditiveBlending, depthWrite: false, fog: false, toneMapped: false,
});

/** A flat ring of haze from `inner` to `outer` metres, brightest a third of the way out. */
function hazeGeometry(inner: number, outer: number): BufferGeometry {
  const rings = HAZE_RINGS.length - 1, segments = 48;
  const geometry = new RingGeometry(inner, outer, segments, rings).rotateX(-Math.PI / 2);
  const colours: number[] = [];
  for (let ring = 0; ring <= rings; ring += 1) {
    for (let s = 0; s <= segments; s += 1) colours.push(HAZE_TONE[0] * HAZE_RINGS[ring], HAZE_TONE[1] * HAZE_RINGS[ring], HAZE_TONE[2] * HAZE_RINGS[ring]);
  }
  geometry.setAttribute("color", new Float32BufferAttribute(colours, 3));
  return geometry;
}

/**
 * The city: a thin field of towers whose roofs all lie far below the floor,
 * the nearest lowest, so none ever rises into the view or stands in front of
 * the office, and a ring of haze over their feet.
 */
function Skyline({ bounds }: { bounds: Rect }) {
  const cx = (bounds.minX + bounds.maxX) / 2, cz = (bounds.minZ + bounds.maxZ) / 2;
  const halfW = (bounds.maxX - bounds.minX) / 2, halfD = (bounds.maxZ - bounds.minZ) / 2;
  const geometries = useMemo(() => TOWER_CLASSES.map((c) => towerGeometry(c.w, c.h, c.d)), []);
  useEffect(() => () => { for (const g of geometries) g.dispose(); }, [geometries]);
  const haze = useMemo(() => hazeGeometry(Math.hypot(halfW, halfD) + 6, Math.hypot(halfW, halfD) + CITY.clear + CITY.reach + 80), [halfW, halfD]);
  useEffect(() => () => haze.dispose(), [haze]);
  const towers = useMemo(() => {
    const rand = lcg(0x51a7e);
    const towers: Placement[][] = TOWER_CLASSES.map(() => []);
    const taken: { x: number; z: number; r: number }[] = [];
    for (let i = 0; i < CITY.towers; i += 1) {
      const angle = rand() * Math.PI * 2, far = rand(), reach = CITY.clear + far * CITY.reach;
      const x = cx + Math.cos(angle) * (halfW + reach), z = cz + Math.sin(angle) * (halfD + reach);
      const kind = Math.floor(rand() * TOWER_CLASSES.length);
      const top = CITY.roofTop - (1 - far) * CITY.nearDrop - rand() * rand() * CITY.roofDrop;
      // Wide gaps: the city is a few silhouettes, never a wall.
      const size = TOWER_CLASSES[kind], r = Math.hypot(size.w, size.d) / 2 + 9;
      if (taken.some((t) => Math.hypot(t.x - x, t.z - z) < t.r + r)) continue;
      taken.push({ x, z, r });
      towers[kind].push({ position: [x, top, z], scale: [1, 1, 1], color: grey(CITY.near + (CITY.far - CITY.near) * far) });
    }
    return towers;
  }, [cx, cz, halfW, halfD]);
  return (
    <group>
      {geometries.map((geometry, i) => <Instances key={i} geometry={geometry} material={windowMaterial()} items={towers[i]} cast={false} />)}
      <mesh geometry={haze} material={HAZE_MATERIAL} position={[cx, CITY.haze, cz]} renderOrder={1} />
    </group>
  );
}

/** The building's own body under the slab: the tower this floor belongs to, dark and plain so the floor above it carries. */
function TowerBody({ bounds }: { bounds: Rect }) {
  const w = bounds.maxX - bounds.minX - 1.2, d = bounds.maxZ - bounds.minZ - 1.2;
  const geometry = useMemo(() => towerGeometry(w, 140, d), [w, d]);
  useEffect(() => () => geometry.dispose(), [geometry]);
  return <mesh geometry={geometry} material={SHELL.roof} position={[(bounds.minX + bounds.maxX) / 2, -0.6, (bounds.minZ + bounds.maxZ) / 2]} />;
}

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

export function BuildingShell({ layout }: { layout: OfficeLayout }) {
  return (
    <group>
      <Skyline bounds={layout.bounds} />
      <TowerBody bounds={layout.bounds} />
      <Edges bounds={layout.bounds} />
    </group>
  );
}
