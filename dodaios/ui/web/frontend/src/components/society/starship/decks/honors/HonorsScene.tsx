/**
 * The Hall of Honour on screen, beyond the shared kit: the runner, the rank
 * wall's sixteen plaques (enlisted and warrant at the foot, officers above,
 * the flag ranks at the top; ranks held lit, the captain's own framed in
 * gold, ranks ahead dim) under a slow sweep of light, and the display cases,
 * whose insignia are lit once their rank is held. Reduced motion holds it
 * all still.
 */
import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo } from "react";
import {
  AdditiveBlending, BoxGeometry, CanvasTexture, Color, CylinderGeometry, DoubleSide, Group, Matrix4, Mesh, MeshBasicMaterial,
  PlaneGeometry, RepeatWrapping, SRGBColorSpace, BufferAttribute, type BufferGeometry,
} from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import { useProgression } from "../../../progression/progressionStore";
import { PERSON_SUBJECT } from "../../../progression/progressionApi";
import { RANKS, rankFor, type Rank } from "../../levels/ranks";
import type { DeckSceneProps } from "../registry";
import type { DeckPlan, Prop } from "../../plan/types";
import { GeoBatch, type CutLine } from "../../render/kit/geo";
import { castsShadow, finishMaterial, receivesShadow } from "../../render/kit/materials";
import { withCutaway } from "../../render/kit/cutaway";
import { SHIP } from "../../render/kit/palette";
import { wallCutFor } from "../../render/deck/props";
import { DAIS, HALL_D, RUNNER_W } from "./honorsPlan";
import { buildRunner, HALL, PLAQUE_FACE, VITRINE } from "./honorsProps";
import { drawInsignia, GOLD, GOLD_DEEP, SILVER_DEEP } from "./insignia";

export function HonorsScene({ plan, reduced, actions }: DeckSceneProps) {
  const level = useProgression((s) => s.subjects[PERSON_SUBJECT]?.level ?? 1);
  const t = actions.t;
  // One string for everything the plaques say, so a redraw happens only when a word changes.
  const words = [t("ship.honors.wall_title"), t("ship.level"), ...RANKS.map((r) => t(`ship.rank.${r.id}`))].join("\u0001");
  return (
    <>
      <HallFittings plan={plan} />
      <RankWallFace plan={plan} level={level} words={words} reduced={reduced} />
      <CaseLights plan={plan} level={level} reduced={reduced} />
    </>
  );
}

function HallFittings({ plan }: { plan: DeckPlan }) {
  const meshes = useMemo(() => {
    const batch = new GeoBatch();
    buildRunner(batch.frame(new Matrix4()), DAIS.z + DAIS.d / 2 + 0.05, HALL_D + 0.3, RUNNER_W);
    return batch.merged().map(({ finish, geometry }) => {
      const mesh = new Mesh(geometry, finishMaterial(finish));
      mesh.castShadow = castsShadow(finish);
      mesh.receiveShadow = receivesShadow(finish);
      mesh.raycast = () => undefined;
      return mesh;
    });
  }, [plan]);
  useEffect(() => () => { for (const m of meshes) m.geometry.dispose(); }, [meshes]);
  return <>{meshes.map((m, i) => <primitive key={i} object={m} />)}</>;
}

// ── the rank wall ─────────────────────────────────────────────────────

/** A plaque's place on the wall's face, as fractions of the face (u across, v down). */
export interface PlaqueCell { rank: Rank; u0: number; v0: number; u1: number; v1: number }

const TITLE_V = 0.13;
const COLUMNS = 6;

/**
 * The ladder as a pyramid that climbs: enlisted and warrant ranks on the
 * bottom row, the officers above them, the flag ranks on top, each row left
 * to right in order.
 */
export function plaqueLayout(ranks: readonly Rank[] = RANKS): PlaqueCell[] {
  const rows: Rank[][] = [
    ranks.filter((r) => r.tier === "flag"),
    ranks.filter((r) => r.tier === "officer"),
    ranks.filter((r) => r.tier === "enlisted" || r.tier === "warrant"),
  ];
  const rowH = (1 - TITLE_V) / rows.length;
  const cells: PlaqueCell[] = [];
  rows.forEach((row, r) => {
    const cols = Math.max(COLUMNS, row.length);
    const offset = (cols - row.length) / 2;
    row.forEach((rank, c) => {
      const u0 = (offset + c) / cols, v0 = TITLE_V + r * rowH;
      cells.push({ rank, u0: u0 + 0.006, v0: v0 + 0.02, u1: u0 + 1 / cols - 0.006, v1: v0 + rowH - 0.02 });
    });
  });
  return cells;
}

type PlaqueState = "held" | "current" | "ahead";

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number): void {
  ctx.beginPath();
  ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
}

const FACE_PX = { w: 2048, h: 564 } as const;

function drawWall(ctx: CanvasRenderingContext2D, cells: readonly PlaqueCell[], level: number, words: string): void {
  const [title, levelFmt, ...names] = words.split("\u0001");
  const { w: W, h: H } = FACE_PX;
  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = HALL.stone; ctx.fillRect(0, 0, W, H);
  // The title, engraved in gold between two rules.
  ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.font = "600 40px 'Space Grotesk', 'Inter Variable', sans-serif";
  ctx.fillStyle = GOLD;
  const label = (title ?? "").toUpperCase();
  ctx.fillText(label, W / 2, (TITLE_V * H) / 2 + 2);
  const half = Math.min(W / 2 - 40, ctx.measureText(label).width / 2 + 40);
  ctx.fillStyle = GOLD_DEEP;
  ctx.fillRect(60, (TITLE_V * H) / 2, W / 2 - half - 60, 2);
  ctx.fillRect(W / 2 + half, (TITLE_V * H) / 2, W / 2 - half - 60, 2);
  const current = rankFor(level).id;
  for (const cell of cells) {
    const x = cell.u0 * W, y = cell.v0 * H, w = (cell.u1 - cell.u0) * W, h = (cell.v1 - cell.v0) * H;
    const state: PlaqueState = cell.rank.id === current ? "current" : level >= cell.rank.level ? "held" : "ahead";
    const metal = cell.rank.tier === "enlisted" ? SILVER_DEEP : GOLD_DEEP;
    const bg = ctx.createLinearGradient(0, y, 0, y + h);
    if (state === "current") { bg.addColorStop(0, "#33280f"); bg.addColorStop(1, "#191309"); }
    else if (state === "held") { bg.addColorStop(0, "#1c222c"); bg.addColorStop(1, "#11151b"); }
    else { bg.addColorStop(0, "#0e1014"); bg.addColorStop(1, "#0a0b0e"); }
    roundRect(ctx, x, y, w, h, 12);
    ctx.fillStyle = bg; ctx.fill();
    ctx.lineWidth = state === "current" ? 5 : 2.5;
    ctx.strokeStyle = state === "current" ? GOLD : state === "held" ? metal : "#23272e";
    ctx.stroke();
    drawInsignia(ctx, cell.rank, x + w / 2, y + h * 0.33, h * 0.62, state === "ahead");
    const index = RANKS.findIndex((r) => r.id === cell.rank.id);
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.font = "600 25px 'Space Grotesk', 'Inter Variable', sans-serif";
    ctx.fillStyle = state === "current" ? GOLD : state === "held" ? "#e8eef6" : "#4b5159";
    ctx.fillText(names[index] ?? cell.rank.id, x + w / 2, y + h * 0.7, w - 20);
    ctx.font = "500 18px 'Inter Variable', sans-serif";
    ctx.fillStyle = state === "ahead" ? "#363b43" : "#8f9db0";
    ctx.fillText((levelFmt ?? "{n}").replace("{n}", String(cell.rank.level)), x + w / 2, y + h * 0.87, w - 20);
  }
}

/** Give a world-space geometry the cut-away line of the wall it hangs on. */
function cutWith(geometry: BufferGeometry, cut: CutLine | undefined): BufferGeometry {
  const n = geometry.attributes.position.count;
  const ab = new Float32Array(n * 4), kind = new Float32Array(n);
  if (cut) for (let i = 0; i < n; i += 1) { ab.set([cut.ax, cut.az, cut.bx, cut.bz], i * 4); kind[i] = cut.kind; }
  geometry.setAttribute("cutAB", new BufferAttribute(ab, 4));
  geometry.setAttribute("cutKind", new BufferAttribute(kind, 1));
  return geometry;
}

/** The face of the rank wall in world space: centre, size and the matrix of its plane. */
function wallFace(wall: Prop, lift: number) {
  const w = wall.w - 2 * PLAQUE_FACE.inset, h = PLAQUE_FACE.y1 - PLAQUE_FACE.y0;
  const at = new Matrix4().makeRotationY(wall.yaw).setPosition(wall.x, 0, wall.z)
    .multiply(new Matrix4().makeTranslation(0, (PLAQUE_FACE.y0 + PLAQUE_FACE.y1) / 2, wall.d / 2 + PLAQUE_FACE.z + lift));
  return { w, h, at };
}

function bandTexture(): CanvasTexture {
  const c = document.createElement("canvas");
  c.width = 512; c.height = 128;
  const ctx = c.getContext("2d") as CanvasRenderingContext2D;
  // A soft, slanted band of light in the middle of the strip.
  for (let y = 0; y < 128; y += 1) {
    const cx = 256 + (64 - y) * 0.5;
    const g = ctx.createLinearGradient(cx - 46, 0, cx + 46, 0);
    g.addColorStop(0, "rgba(255,236,200,0)"); g.addColorStop(0.5, "rgba(255,236,200,1)"); g.addColorStop(1, "rgba(255,236,200,0)");
    ctx.fillStyle = g; ctx.fillRect(cx - 46, y, 92, 1);
  }
  const t = new CanvasTexture(c);
  t.wrapS = RepeatWrapping;
  t.colorSpace = SRGBColorSpace;
  return t;
}

function RankWallFace({ plan, level, words, reduced }: { plan: DeckPlan; level: number; words: string; reduced: boolean }) {
  const wall = plan.props.find((p) => p.kind === "rankWall");
  const cells = useMemo(() => plaqueLayout(), []);
  const parts = useMemo(() => {
    if (!wall) return null;
    const cut = wallCutFor(plan, wall);
    const face = wallFace(wall, 0);
    const canvas = document.createElement("canvas");
    canvas.width = FACE_PX.w; canvas.height = FACE_PX.h;
    const texture = new CanvasTexture(canvas);
    texture.colorSpace = SRGBColorSpace;
    texture.anisotropy = 8;
    const plaques = new Mesh(cutWith(new PlaneGeometry(face.w, face.h).applyMatrix4(face.at), cut),
      withCutaway(new MeshBasicMaterial({ map: texture, toneMapped: false, color: new Color(1.12, 1.12, 1.12) }), 0, 0.6));
    const sweepMap = bandTexture();
    const sweep = new Mesh(cutWith(new PlaneGeometry(face.w, face.h).applyMatrix4(wallFace(wall, 0.004).at), cut),
      withCutaway(new MeshBasicMaterial({ map: sweepMap, transparent: true, opacity: 0.16, blending: AdditiveBlending, depthWrite: false, toneMapped: false }), 0, 0.6));
    // The frame round the captain's plaque: four bars, rebuilt when the rank changes.
    const frameMat = withCutaway(new MeshBasicMaterial({ color: new Color(SHIP.gold).multiplyScalar(2.4), toneMapped: false }), 0, 0.6);
    const frame = new Mesh<BufferGeometry, MeshBasicMaterial>(new BoxGeometry(0.01, 0.01, 0.01), frameMat);
    for (const m of [plaques, sweep, frame]) m.raycast = () => undefined;
    sweep.renderOrder = 2;
    return { canvas, texture, plaques, sweep, sweepMap, frame, frameMat, cut, face };
  }, [plan, wall]);

  useEffect(() => {
    if (!parts) return;
    const ctx = parts.canvas.getContext("2d");
    if (ctx) drawWall(ctx, cells, level, words);
    parts.texture.needsUpdate = true;
    // Frame the current plaque.
    const cell = cells.find((c) => c.rank.id === rankFor(level).id);
    if (!cell) return;
    const { w, h, at } = parts.face;
    const x0 = -w / 2 + cell.u0 * w, x1 = -w / 2 + cell.u1 * w, y0 = h / 2 - cell.v1 * h, y1 = h / 2 - cell.v0 * h;
    const bar = 0.025, pad = 0.02;
    const bars = [
      [x0 - pad, y1 + pad, x1 + pad, y1 + pad - bar], [x0 - pad, y0 - pad + bar, x1 + pad, y0 - pad],
      [x0 - pad, y1 + pad, x0 - pad + bar, y0 - pad], [x1 + pad - bar, y1 + pad, x1 + pad, y0 - pad],
    ].map(([ax, ay, bx, by]) => new BoxGeometry(Math.abs(bx - ax), Math.abs(by - ay), 0.02).translate((ax + bx) / 2, (ay + by) / 2, 0.012));
    const merged = mergeGeometries(bars, false) as BufferGeometry;
    for (const g of bars) g.dispose();
    merged.applyMatrix4(at);
    parts.frame.geometry.dispose();
    parts.frame.geometry = cutWith(merged, parts.cut);
  }, [parts, cells, level, words]);

  useEffect(() => () => {
    if (!parts) return;
    for (const m of [parts.plaques, parts.sweep, parts.frame]) { m.geometry.dispose(); (m.material as MeshBasicMaterial).dispose(); }
    parts.texture.dispose(); parts.sweepMap.dispose();
  }, [parts]);

  const base = useMemo(() => new Color(SHIP.gold), []);
  useFrame(({ clock }) => {
    if (!parts) return;
    const t = clock.elapsedTime;
    parts.sweep.visible = !reduced;
    parts.sweepMap.offset.x = reduced ? 0 : -((t / 14) % 1);
    parts.frameMat.color.copy(base).multiplyScalar(reduced ? 2.4 : 2.1 + Math.sin(t * 1.6) * 0.4);
  });
  if (!parts) return null;
  return <><primitive object={parts.plaques} /><primitive object={parts.sweep} /><primitive object={parts.frame} /></>;
}

// ── the display cases ─────────────────────────────────────────────────

function insigniaTexture(rank: Rank, dim: boolean): CanvasTexture {
  const c = document.createElement("canvas");
  c.width = 256; c.height = 256;
  const ctx = c.getContext("2d") as CanvasRenderingContext2D;
  // A dark enamel medallion with the mark on it.
  ctx.beginPath(); ctx.arc(128, 128, 112, 0, Math.PI * 2);
  ctx.fillStyle = dim ? "rgba(14,16,20,0.95)" : "rgba(24,28,36,0.96)"; ctx.fill();
  ctx.lineWidth = 7; ctx.strokeStyle = dim ? "#3a3d43" : GOLD; ctx.stroke();
  drawInsignia(ctx, rank, 128, 128, 170, dim);
  const t = new CanvasTexture(c);
  t.colorSpace = SRGBColorSpace;
  return t;
}

interface CaseView { rank: Rank; group: Group; medal: Mesh; lamp: MeshBasicMaterial; beam: Mesh; lit: CanvasTexture; dim: CanvasTexture; medalMat: MeshBasicMaterial; seed: number }

function CaseLights({ plan, level, reduced }: { plan: DeckPlan; level: number; reduced: boolean }) {
  const shared = useMemo(() => ({
    medal: new PlaneGeometry(0.36, 0.36),
    lamp: new BoxGeometry(0.78, 0.012, 0.58),
    beam: new CylinderGeometry(0.28, 0.36, VITRINE.y1 - VITRINE.y0 - 0.04, 20, 1, true),
    beamMat: new MeshBasicMaterial({ color: new Color(SHIP.lightWarm).multiplyScalar(0.22), transparent: true, blending: AdditiveBlending, depthWrite: false, side: DoubleSide, toneMapped: false }),
  }), []);
  const cases = useMemo(() => plan.props.filter((p) => p.kind === "honorCase" && p.ref).map((p, i): CaseView | null => {
    const rank = RANKS.find((r) => r.id === p.ref);
    if (!rank) return null;
    const group = new Group();
    group.position.set(p.x, 0, p.z);
    group.rotation.y = p.yaw;
    const lit = insigniaTexture(rank, false), dim = insigniaTexture(rank, true);
    const medalMat = new MeshBasicMaterial({ map: dim, transparent: true, alphaTest: 0.05, side: DoubleSide, toneMapped: false });
    const medal = new Mesh(shared.medal, medalMat);
    medal.position.y = (VITRINE.y0 + 0.08 + VITRINE.y1) / 2;
    const lamp = new MeshBasicMaterial({ color: new Color("#2a2d33"), toneMapped: false });
    const lampMesh = new Mesh(shared.lamp, lamp);
    lampMesh.position.y = VITRINE.y1 - 0.012;
    const beam = new Mesh(shared.beam, shared.beamMat);
    beam.position.y = (VITRINE.y0 + VITRINE.y1) / 2;
    beam.renderOrder = 3;
    for (const m of [medal, lampMesh, beam]) { m.raycast = () => undefined; group.add(m); }
    return { rank, group, medal, lamp, beam, lit, dim, medalMat, seed: i * 0.9 };
  }).filter((c): c is CaseView => c !== null), [plan, shared]);

  useEffect(() => {
    const current = rankFor(level).id;
    for (const c of cases) {
      const held = level >= c.rank.level;
      c.medalMat.map = held ? c.lit : c.dim;
      c.medalMat.color.setScalar(held ? 1.25 : 0.7);
      c.medalMat.needsUpdate = true;
      c.lamp.color.set(held ? (c.rank.id === current ? SHIP.gold : SHIP.lightWarm) : "#24272c").multiplyScalar(held ? 2.3 : 1);
      c.beam.visible = held;
    }
  }, [cases, level]);
  useEffect(() => () => {
    for (const c of cases) { c.lit.dispose(); c.dim.dispose(); c.medalMat.dispose(); c.lamp.dispose(); }
  }, [cases]);
  useEffect(() => () => { shared.medal.dispose(); shared.lamp.dispose(); shared.beam.dispose(); shared.beamMat.dispose(); }, [shared]);

  useFrame(({ clock }) => {
    const t = clock.elapsedTime;
    for (const c of cases) {
      const held = level >= c.rank.level;
      c.medal.rotation.y = reduced || !held ? 0 : Math.sin(t * 0.5 + c.seed) * 0.5;
    }
  });
  return <>{cases.map((c) => <primitive key={c.rank.id} object={c.group} />)}</>;
}
