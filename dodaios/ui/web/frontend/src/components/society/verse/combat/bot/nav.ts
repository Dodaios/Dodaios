/**
 * Route finding for bots: a waypoint graph over the arena's movement grid
 * (a 2 m lattice, the walkways over drops, the cover spots), A* over it, then
 * string-pulling so a route is a few straight legs. Built once per arena.
 */
import { isWalkable, nearestWalkable, walkableSegment, type Arena } from "../arena";

export interface NavGraph {
  xs: Float64Array;
  zs: Float64Array;
  /** Neighbours of node i: adj[i] = [j, cost, j, cost, ...]. */
  adj: number[][];
}

const graphs = new WeakMap<Arena, NavGraph>();
const LINK_RANGE = 6.5;

export function navGraph(arena: Arena): NavGraph {
  const hit = graphs.get(arena);
  if (hit) return hit;
  const pts: { x: number; z: number }[] = [];
  const add = (x: number, z: number) => {
    if (!isWalkable(arena, x, z)) return;
    for (const p of pts) if (Math.abs(p.x - x) < 0.6 && Math.abs(p.z - z) < 0.6) return;
    pts.push({ x, z });
  };
  const b = arena.def.bounds;
  for (let z = b.z0 + 1; z < b.z1; z += 2) for (let x = b.x0 + 1; x < b.x1; x += 2) add(x, z);
  for (const v of arena.def.voids) {
    // Walkways: sample along every bridge, and round the rim.
    for (const br of arena.def.bridges) {
      if (br.kind === "annulus") {
        const r = (br.r0 + br.r1) / 2;
        for (let a = 0; a < 360; a += 15) add(br.x + Math.sin((a * Math.PI) / 180) * r, br.z + Math.cos((a * Math.PI) / 180) * r);
      } else {
        const a = (br.yawDeg * Math.PI) / 180;
        for (let r = br.r0 + 0.4; r <= br.r1 + 1.2; r += 1.5) add(br.x + Math.sin(a) * r, br.z + Math.cos(a) * r);
      }
    }
    for (let a = 0; a < 360; a += 10) {
      const r = v.r + 0.9;
      add(v.x + Math.sin((a * Math.PI) / 180) * r, v.z + Math.cos((a * Math.PI) / 180) * r);
    }
  }
  for (const c of arena.cover) add(c.x, c.z);
  const n = pts.length;
  const xs = new Float64Array(n);
  const zs = new Float64Array(n);
  pts.forEach((p, i) => { xs[i] = p.x; zs[i] = p.z; });
  const adj: number[][] = pts.map(() => []);
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      const d = Math.hypot(xs[i] - xs[j], zs[i] - zs[j]);
      if (d > LINK_RANGE) continue;
      if (!walkableSegment(arena, xs[i], zs[i], xs[j], zs[j])) continue;
      adj[i].push(j, d);
      adj[j].push(i, d);
    }
  }
  const g = { xs, zs, adj };
  graphs.set(arena, g);
  return g;
}

function nearNodes(arena: Arena, g: NavGraph, x: number, z: number, k: number): number[] {
  const cand: { i: number; d: number }[] = [];
  for (let i = 0; i < g.xs.length; i++) {
    const d = Math.hypot(g.xs[i] - x, g.zs[i] - z);
    if (d <= LINK_RANGE) cand.push({ i, d });
  }
  cand.sort((a, b) => a.d - b.d);
  const out: number[] = [];
  for (const c of cand) {
    if (walkableSegment(arena, x, z, g.xs[c.i], g.zs[c.i])) out.push(c.i);
    if (out.length >= k) break;
  }
  return out;
}

export interface Pt { x: number; z: number }

/** A walkable route from `from` to `to` (start, corners, goal), or null. */
export function findRoute(arena: Arena, from: Pt, to: Pt): Pt[] | null {
  const start = nearestWalkable(arena, from.x, from.z, 2);
  const goal = nearestWalkable(arena, to.x, to.z, 4);
  if (!start || !goal) return null;
  if (walkableSegment(arena, start.x, start.z, goal.x, goal.z)) return [start, goal];
  const g = navGraph(arena);
  const n = g.xs.length;
  const S = n;
  const G = n + 1;
  const startLinks = nearNodes(arena, g, start.x, start.z, 6);
  const goalLinks = new Set(nearNodes(arena, g, goal.x, goal.z, 6));
  if (startLinks.length === 0 || goalLinks.size === 0) return null;
  const px = (i: number) => (i === S ? start.x : i === G ? goal.x : g.xs[i]);
  const pz = (i: number) => (i === S ? start.z : i === G ? goal.z : g.zs[i]);
  const h = (i: number) => Math.hypot(px(i) - goal.x, pz(i) - goal.z);
  const gScore = new Float64Array(n + 2).fill(Infinity);
  const from_ = new Int32Array(n + 2).fill(-1);
  const closed = new Uint8Array(n + 2);
  const open: number[] = [S];
  gScore[S] = 0;
  while (open.length) {
    let bi = 0;
    let bf = Infinity;
    for (let k = 0; k < open.length; k++) {
      const f = gScore[open[k]] + h(open[k]);
      if (f < bf) { bf = f; bi = k; }
    }
    const cur = open[bi];
    open[bi] = open[open.length - 1];
    open.pop();
    if (cur === G) break;
    if (closed[cur]) continue;
    closed[cur] = 1;
    const relax = (j: number, cost: number) => {
      const ng = gScore[cur] + cost;
      if (ng < gScore[j]) { gScore[j] = ng; from_[j] = cur; open.push(j); }
    };
    if (cur === S) {
      for (const j of startLinks) relax(j, Math.hypot(g.xs[j] - start.x, g.zs[j] - start.z));
    } else {
      const a = g.adj[cur];
      for (let k = 0; k < a.length; k += 2) if (!closed[a[k]]) relax(a[k], a[k + 1]);
      if (goalLinks.has(cur)) relax(G, Math.hypot(g.xs[cur] - goal.x, g.zs[cur] - goal.z));
    }
  }
  if (from_[G] < 0) return null;
  const chain: Pt[] = [];
  for (let i = G; i !== -1; i = from_[i]) chain.push({ x: px(i), z: pz(i) });
  chain.reverse();
  // String-pull: skip every waypoint a straight walk can cut.
  const out: Pt[] = [chain[0]];
  let anchor = 0;
  while (anchor < chain.length - 1) {
    let next = anchor + 1;
    for (let j = chain.length - 1; j > anchor + 1; j--) {
      if (walkableSegment(arena, chain[anchor].x, chain[anchor].z, chain[j].x, chain[j].z)) { next = j; break; }
    }
    out.push(chain[next]);
    anchor = next;
  }
  return out;
}

export function routeLength(route: readonly Pt[]): number {
  let d = 0;
  for (let i = 1; i < route.length; i++) d += Math.hypot(route[i].x - route[i - 1].x, route[i].z - route[i - 1].z);
  return d;
}
