/**
 * A small synthetic deck for unit tests: a 48 × 24 m hall split by a wall with
 * a gap, a sunken pit reached by a stair, a console row, a team table, a mess,
 * bunks, viewport stands, a lift and a patrol route. Shaped like a cooked deck
 * so the code under test never knows.
 */
import type { Deck, NavGrid, PlateImages, PlateLevel, Socket, SocketKind } from "../content/deck";

export const SYNTH_W = 48;
export const SYNTH_D = 24;
/** The pit: x 12–20, z −11…−7, 1.4 m down; a stair at x 15–17 climbs out toward +z. */
export const PIT = { x0: 12, x1: 20, z0: -11, z1: -7, depth: -1.4 } as const;

function navGrid(): NavGrid {
  const cell = 0.2;
  const cols = SYNTH_W / cell;
  const rows = SYNTH_D / cell;
  const walkable = new Uint8Array(cols * rows).fill(1);
  const heights = new Float32Array(cols * rows);
  const x0 = -SYNTH_W / 2;
  const z0 = -SYNTH_D / 2;
  for (let r = 0; r < rows; r++) {
    const z = z0 + (r + 0.5) * cell;
    for (let c = 0; c < cols; c++) {
      const x = x0 + (c + 0.5) * cell;
      const i = r * cols + c;
      // A wall at x = 0 from the back (z = -12) to z = 4; the gap is at the front.
      if (z <= 4 && Math.abs(x) < 0.4) walkable[i] = 0;
      if (x > PIT.x0 && x < PIT.x1 && z > PIT.z0 && z < PIT.z1) heights[i] = PIT.depth;
      // The stair: 2 m long, rising toward +z from the pit's front edge.
      if (x > 15 && x < 17 && z >= PIT.z1 && z < PIT.z1 + 2) heights[i] = PIT.depth * (1 - (z - PIT.z1) / 2);
    }
  }
  return { cell, x0, z0, cols, rows, walkable, heights, maxStep: 0.3 };
}

function socket(kind: SocketKind, id: string, x: number, z: number, extra: Partial<Socket> = {}): Socket {
  const m = /^(.*?)_?(\d+)$/.exec(id);
  return {
    id, kind, x, y: 0, z, yaw: 0, room: null, group: m ? m[1] : id, order: m ? Number(m[2]) : 0,
    station: null, corners: null, size: null, props: {}, ...extra,
  };
}

/**
 * The synthetic hall's plate at `pxPerMetre`: an older deck (overview at 1/4,
 * L0 only) or, with `mips`, the close-up layout (M2 and M4 tile levels, the
 * overview at 1/8). Tiles are 2048 px.
 */
export function syntheticPlate(pxPerMetre: number, mips: boolean): PlateImages {
  const tileSize = 2048;
  const width = Math.round(SYNTH_W * pxPerMetre);
  const height = Math.round(24.8 * pxPerMetre);
  const level = (divisor: number, prefix: string): PlateLevel => {
    const w = Math.round(width / divisor);
    const h = Math.round(height / divisor);
    return {
      divisor, width: w, height: h, tileSize, cols: Math.ceil(w / tileSize), rows: Math.ceil(h / tileSize),
      tileUrl: (c, r) => `/synthetic/${prefix}_${c}_${r}.avif`,
    };
  };
  const l0 = level(1, "L0");
  const overviewDivisor = mips ? 8 : 4;
  return {
    width, height,
    overview: { url: "/synthetic/L1.avif", width: Math.round(width / overviewDivisor), height: Math.round(height / overviewDivisor) },
    tileSize, cols: l0.cols, rows: l0.rows, tileUrl: l0.tileUrl,
    levels: mips ? [l0, level(2, "M2"), level(4, "M4")] : [l0],
  };
}

export function syntheticDeck(): Deck {
  const sockets: Socket[] = [];
  for (let i = 0; i < 6; i++) {
    const x = -20 + i * 2.4;
    sockets.push(socket("seat", `pit_p_${i}`, x, -4, { yaw: Math.PI, room: "bridge" }));
    const s = socket("screen", `pit_p_${i}`, x, -4.7, { room: "bridge", size: [0.6, 0.36], y: 1.1 });
    sockets.push({ ...s, corners: [[x - 0.3, 1.28, -4.7], [x + 0.3, 1.28, -4.7], [x + 0.3, 0.92, -4.7], [x - 0.3, 0.92, -4.7]] });
  }
  sockets.push(socket("holo", "briefing", 8, -2, { room: "briefing", size: [1.6, 0.8], y: 1.0, station: "brief" }));
  for (let i = 0; i < 6; i++) {
    const a = (i / 6) * Math.PI * 2;
    sockets.push(socket("seat", `brief_${i}`, 8 + Math.cos(a) * 1.6, -2 + Math.sin(a) * 1.6, { room: "briefing", station: "brief" }));
  }
  for (let i = 0; i < 4; i++) sockets.push(socket("seat", `mess_${i}`, 14 + i * 1.2, 6, { room: "mess" }));
  for (let i = 0; i < 3; i++) sockets.push(socket("bunk", `${i}`, 20, -2 + i * 2, { room: "quarters" }));
  for (let i = 0; i < 3; i++) sockets.push(socket("stand", `viewport_${i}`, -22, 6 + i));
  for (let i = 0; i < 4; i++) sockets.push(socket("waypoint", `patrol_a_${i}`, -10 + (i % 2) * 20, i < 2 ? 8 : 10));
  sockets.push(socket("lift", "main", -23, 0));
  sockets.push(socket("spawn", "arrival", -20, 10));
  sockets.push(socket("light", "hall_0", 0, 0, { y: 3.2 }));
  sockets.push(socket("station", "brief", 8, 0.2, { station: null }));
  sockets.push(socket("station", "command", -16, 0));
  sockets.push(socket("station", "lift", -22.5, 0.5));
  return {
    id: "bridge",
    contentId: "synthetic",
    name: "Synthetic",
    camera: { center: [0, 0, 0], pitchDeg: 60, frameW: SYNTH_W, frameH: 24.8, pxPerMetre: 96 },
    plate: syntheticPlate(96, false),
    occludersUrl: null,
    envUrl: null,
    exposure: 0,
    nav: navGrid(),
    sockets,
    stations: [
      { id: "command", kind: "agents_list", room: null, x: -16, y: 0, z: 0, sockets: {} },
      { id: "brief", kind: "team", room: "briefing", x: 8, y: 0, z: 0.2, sockets: { seat: sockets.filter((s) => s.station === "brief" && s.kind === "seat").map((s) => s.id), holo: ["briefing"] } },
      { id: "lift", kind: "lift", room: null, x: -22.5, y: 0, z: 0.5, sockets: {} },
    ],
    rooms: [],
    probes: [],
  };
}
