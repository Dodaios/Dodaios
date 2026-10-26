// @vitest-environment node
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { inflateSync } from "node:zlib";
import { describe, expect, it } from "vitest";
import { buildArena, hasFloor, isWalkable, lineOfSight, raycastWorld, walkableSegment, COVER_HEIGHT } from "./arena";
import { REACTOR_ARENA } from "./arenaReactor";
import { DEFAULT_TUNING } from "./tuning";

const arena = buildArena(REACTOR_ARENA, DEFAULT_TUNING.body.radius);
const SHAFT = REACTOR_ARENA.centre;

describe("reactor arena", () => {
  it("spawns on opposite sides of the shaft, out of each other's sight", () => {
    const [a, b] = REACTOR_ARENA.spawns;
    expect(isWalkable(arena, a.x, a.z)).toBe(true);
    expect(isWalkable(arena, b.x, b.z)).toBe(true);
    expect(Math.hypot(a.x - b.x, a.z - b.z)).toBeGreaterThan(25);
    // The core blocks the straight line at standing height.
    expect(lineOfSight(arena, a.x, 1.6, a.z, b.x, 1.6, b.z)).toBe(false);
    // Mirrored about the shaft axis.
    expect(a.x + b.x).toBeCloseTo(2 * SHAFT.x, 6);
    expect(a.z).toBe(b.z);
  });

  it("walks the catwalks and the ring but not into the drop", () => {
    expect(walkableSegment(arena, 38.8, 22, 48.6, 22)).toBe(true); // west catwalk to the ring
    expect(walkableSegment(arena, 54, 8.0, 54, 15.6)).toBe(true); // north catwalk
    for (let a = 0; a < 360; a += 10) {
      const r = 5.75;
      expect(isWalkable(arena, SHAFT.x + Math.sin((a * Math.PI) / 180) * r, SHAFT.z + Math.cos((a * Math.PI) / 180) * r)).toBe(true);
    }
    expect(isWalkable(arena, 46, 17)).toBe(false); // over the shaft
    expect(walkableSegment(arena, 40, 14, 50, 14)).toBe(false);
    expect(isWalkable(arena, 54, 22)).toBe(false); // the core
  });

  it("has the east floor's cover and the far wall's stacks as solids", () => {
    expect(isWalkable(arena, 78.6, 22)).toBe(false);
    expect(isWalkable(arena, 73, 12)).toBe(false);
    expect(isWalkable(arena, 72.6, 3.4)).toBe(false);
    expect(isWalkable(arena, 76.5, 22)).toBe(true);
  });

  it("lets bolts fly over the drop, stops them at the core, walls and cover, and lets them out through doorways", () => {
    // Across the shaft north of the core: nothing in the way.
    expect(raycastWorld(arena, 41, 1.4, 14, 67, 1.4, 14)).toBeNull();
    // Diving into the shaft: no floor there.
    expect(raycastWorld(arena, 46, 1.4, 24.5, 46, -2, 24.5)).toBeNull();
    // ...but there is floor on the rim.
    expect(raycastWorld(arena, 36, 1.4, 22, 36, -1, 22)?.surface).toBe("floor");
    const core = raycastWorld(arena, 40, 1.4, 22, 68, 1.4, 22);
    expect(core?.surface).toBe("prop");
    expect(core?.collider).toBe("core");
    // Over the core's cap.
    expect(raycastWorld(arena, 46, 2.4, 22.2, 62, 2.4, 22.2)).toBeNull();
    const conduit = raycastWorld(arena, 70, 1.4, 22, 81, 1.4, 22);
    expect(conduit?.collider).toBe("conduit_1");
    expect(raycastWorld(arena, 60, 1.4, 30, 60, 1.4, 45)?.surface).toBe("wall");
    expect(raycastWorld(arena, 54, 1.4, 36, 54, 1.4, 45)?.surface).toBe("exit");
    // Waist-high coolant runs stop low bolts only.
    expect(raycastWorld(arena, 70, 0.6, 12, 77, 0.6, 12)?.collider).toBe("coolant_0");
    expect(raycastWorld(arena, 70, 1.4, 12, 77, 1.4, 12)).toBeNull();
  });

  it("finds cover spots next to tall solids, all on walkable floor", () => {
    expect(arena.cover.length).toBeGreaterThan(40);
    for (const c of arena.cover) {
      expect(isWalkable(arena, c.x, c.z)).toBe(true);
      const solid = REACTOR_ARENA.colliders.find((k) => k.id === c.collider);
      expect(solid && solid.y1).toBeGreaterThanOrEqual(COVER_HEIGHT);
    }
    // Some cover sits on the ring, behind the core.
    expect(arena.cover.some((c) => c.collider === "core")).toBe(true);
  });

  it("has floor exactly where the deck has it", () => {
    expect(hasFloor(REACTOR_ARENA, 54, 12)).toBe(true); // north catwalk
    expect(hasFloor(REACTOR_ARENA, 50, 12)).toBe(false); // drop
    expect(hasFloor(REACTOR_ARENA, 30, 22)).toBe(false); // outside the hall
  });
});

// ---------------------------------------------------------------- against the cooked deck

const deckDir = resolve(process.cwd(), "public/verse/decks/engineering");

function decodeGreyPng(buf: Buffer): { w: number; h: number; px: Uint8Array } {
  let p = 8;
  let w = 0;
  let h = 0;
  const idat: Buffer[] = [];
  while (p < buf.length) {
    const len = buf.readUInt32BE(p);
    const type = buf.toString("ascii", p + 4, p + 8);
    const data = buf.subarray(p + 8, p + 8 + len);
    if (type === "IHDR") { w = data.readUInt32BE(0); h = data.readUInt32BE(4); if (data[8] !== 8 || data[9] !== 0) throw new Error("not 8-bit grey"); }
    if (type === "IDAT") idat.push(data);
    p += 12 + len;
  }
  const raw = inflateSync(Buffer.concat(idat));
  const px = new Uint8Array(w * h);
  let prev = new Uint8Array(w);
  for (let y = 0; y < h; y++) {
    const f = raw[y * (w + 1)];
    const cur = new Uint8Array(w);
    for (let x = 0; x < w; x++) {
      const a = x > 0 ? cur[x - 1] : 0;
      const b = prev[x];
      const c = x > 0 ? prev[x - 1] : 0;
      let v = raw[y * (w + 1) + 1 + x];
      if (f === 1) v += a;
      else if (f === 2) v += b;
      else if (f === 3) v += (a + b) >> 1;
      else if (f === 4) { const pp = a + b - c; const pa = Math.abs(pp - a); const pb = Math.abs(pp - b); const pc = Math.abs(pp - c); v += pa <= pb && pa <= pc ? a : pb <= pc ? b : c; }
      cur[x] = v & 255;
    }
    px.set(cur, y * w);
    prev = cur;
  }
  return { w, h, px };
}

const cooked = existsSync(resolve(deckDir, "manifest.json")) && existsSync(resolve(deckDir, "nav.png"));

describe.skipIf(!cooked)("reactor arena against the cooked engineering deck", () => {
  const manifest = cooked ? JSON.parse(readFileSync(resolve(deckDir, "manifest.json"), "utf8")) : null;

  it("matches the reactor room's outline and its ring consoles", () => {
    const room = manifest.rooms.find((r: { id: string }) => r.id === REACTOR_ARENA.room);
    expect(room).toBeTruthy();
    const xs = room.polygon.map((p: number[]) => p[0]);
    const zs = room.polygon.map((p: number[]) => p[1]);
    const b = REACTOR_ARENA.bounds;
    expect(Math.abs(Math.min(...xs) - b.x0)).toBeLessThan(0.6);
    expect(Math.abs(Math.max(...xs) - b.x1)).toBeLessThan(0.6);
    expect(Math.abs(Math.min(...zs) - b.z0)).toBeLessThan(0.6);
    expect(Math.abs(Math.max(...zs) - b.z1)).toBeLessThan(0.6);
    for (const t of REACTOR_ARENA.terminals) {
      const s = manifest.sockets.find((k: { id: string; kind: string }) => k.id === t.id && k.kind === "stand");
      expect(s, t.id).toBeTruthy();
      expect(Math.hypot(s.position[0] - t.x, s.position[2] - t.z)).toBeLessThan(0.2);
    }
  });

  it("agrees with the nav grid away from the rim band it deliberately opens", () => {
    const nav = manifest.nav;
    const { w, h, px } = decodeGreyPng(readFileSync(resolve(deckDir, "nav.png")));
    expect([w, h]).toEqual([nav.w, nav.h]);
    const b = REACTOR_ARENA.bounds;
    let navWalk = 0, navAndMine = 0, mineWalk = 0, mineAndNav = 0;
    for (let r = 0; r < h; r++) {
      for (let c = 0; c < w; c++) {
        const x = nav.origin_x + (c + 0.5) * nav.cell;
        const z = nav.origin_z + (r + 0.5) * nav.cell;
        // Inside the hall, away from its walls (the clearances differ) and outside the rim band.
        if (x < b.x0 + 0.6 || x > b.x1 - 0.6 || z < b.z0 + 0.6 || z > b.z1 - 0.6) continue;
        const d = Math.hypot(x - SHAFT.x, z - SHAFT.z);
        if (d > 12.6 && d < 16.0) continue;
        const theirs = px[r * w + c] !== 0;
        const mine = isWalkable(arena, x, z);
        if (theirs) { navWalk++; if (mine) navAndMine++; }
        if (mine) { mineWalk++; if (theirs) mineAndNav++; }
      }
    }
    expect(navWalk).toBeGreaterThan(20000);
    expect(navAndMine / navWalk).toBeGreaterThan(0.95);
    expect(mineAndNav / mineWalk).toBeGreaterThan(0.95);
  });
});
