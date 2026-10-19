/**
 * The androids' faces. Every crew member's head carries a glass display that
 * shows its own profile face: its pixel creature (painted by the same code
 * as the profile picture) or its shape with eyes, on a dark screen. All faces
 * share one atlas texture, so a deck of figures costs one face material.
 * A face is redrawn only when its frame changes (blinks, glances, the
 * thinking sweep), at most ten times a second.
 */
import { CanvasTexture, SRGBColorSpace } from "three";
import { creatureBody, creaturePose, CREATURE_TICK_MS, STAGE_H, STAGE_W, type CreatureLook, type CreatureState } from "../../companion/creature";
import { paintCreature } from "../../companion/creaturePaint";
import type { SymbolShape } from "../../companion/appearance";

export const ATLAS_COLS = 16;
export const ATLAS_ROWS = 8;
export const CELL_PX = 64;

export type FaceLook =
  | { kind: "creature"; creature: CreatureLook }
  | { kind: "shape"; shape: SymbolShape; color: string };

export type FaceMood = "idle" | "working" | "waiting" | "paused" | "talking";

const MOOD_STATE: Record<FaceMood, CreatureState> = {
  idle: "idle", working: "working", waiting: "asking", paused: "sleeping", talking: "talking",
};

interface Slot { index: number; look: FaceLook; mood: FaceMood; frame: number; key: string }

export class FaceAtlas {
  readonly canvas: HTMLCanvasElement;
  readonly texture: CanvasTexture;
  private readonly ctx: CanvasRenderingContext2D;
  private readonly scratch: HTMLCanvasElement;
  private readonly sctx: CanvasRenderingContext2D;
  private readonly slots = new Map<string, Slot>();
  private readonly free: number[] = [];
  private dirty = false;

  constructor() {
    this.canvas = document.createElement("canvas");
    this.canvas.width = ATLAS_COLS * CELL_PX;
    this.canvas.height = ATLAS_ROWS * CELL_PX;
    const ctx = this.canvas.getContext("2d");
    if (!ctx) throw new Error("2d canvas unavailable");
    this.ctx = ctx;
    this.scratch = document.createElement("canvas");
    this.scratch.width = 52;
    this.scratch.height = Math.round((52 / STAGE_W) * STAGE_H);
    const sctx = this.scratch.getContext("2d");
    if (!sctx) throw new Error("2d canvas unavailable");
    this.sctx = sctx;
    // The last cell stays blank for anyone beyond the atlas.
    for (let i = ATLAS_COLS * ATLAS_ROWS - 2; i >= 0; i -= 1) this.free.push(i);
    this.texture = new CanvasTexture(this.canvas);
    this.texture.colorSpace = SRGBColorSpace;
    this.drawBlank(ATLAS_COLS * ATLAS_ROWS - 1);
  }

  /** The uv rectangle (u0, v0, u1, v1) of `id`'s cell, allocating it on first use. */
  cell(id: string, look: FaceLook): [number, number, number, number] {
    let slot = this.slots.get(id);
    if (!slot) {
      const index = this.free.pop() ?? ATLAS_COLS * ATLAS_ROWS - 1;
      slot = { index, look, mood: "idle", frame: -1, key: "" };
      this.slots.set(id, slot);
    }
    slot.look = look;
    const c = slot.index % ATLAS_COLS, r = Math.floor(slot.index / ATLAS_COLS);
    const inset = 1 / (CELL_PX * ATLAS_COLS);
    return [c / ATLAS_COLS + inset, 1 - (r + 1) / ATLAS_ROWS + inset, (c + 1) / ATLAS_COLS - inset, 1 - r / ATLAS_ROWS - inset];
  }

  release(id: string): void {
    const slot = this.slots.get(id);
    if (!slot) return;
    this.slots.delete(id);
    if (slot.index !== ATLAS_COLS * ATLAS_ROWS - 1) this.free.push(slot.index);
  }

  setMood(id: string, mood: FaceMood): void {
    const slot = this.slots.get(id);
    if (slot && slot.mood !== mood) { slot.mood = mood; slot.frame = -1; }
  }

  /** Redraw the faces whose frame changed; call once per rendered frame. */
  tick(nowMs: number, still: boolean): void {
    const frame = still ? 5 : Math.floor(nowMs / CREATURE_TICK_MS);
    for (const [id, slot] of this.slots) {
      // Each face runs on its own phase, so a row of androids does not blink in step.
      const own = frame + (hashId(id) % 97);
      const key = this.frameKey(slot, own);
      if (key === slot.key) continue;
      slot.key = key;
      this.draw(slot, own);
      this.dirty = true;
    }
    if (this.dirty) { this.texture.needsUpdate = true; this.dirty = false; }
  }

  private frameKey(slot: Slot, frame: number): string {
    const pose = creaturePose(MOOD_STATE[slot.mood], frame);
    const lookKey = slot.look.kind === "creature" ? `${slot.look.creature.seed}|${slot.look.creature.palette}|${slot.look.creature.eyes}` : `${slot.look.shape}|${slot.look.color}`;
    return `${lookKey}|${slot.mood}|${pose.eyes}|${pose.ex}|${pose.ey}|${pose.head}|${pose.sweep}|${pose.mouth}|${pose.bits.length}|${pose.dim}`;
  }

  private cellOrigin(index: number): [number, number] {
    return [(index % ATLAS_COLS) * CELL_PX, Math.floor(index / ATLAS_COLS) * CELL_PX];
  }

  private background(x: number, y: number, mood: FaceMood): void {
    const { ctx } = this;
    const g = ctx.createLinearGradient(x, y, x, y + CELL_PX);
    const tint = mood === "working" ? ["#06221a", "#020a08"] : mood === "waiting" ? ["#2a1c05", "#0b0702"] : mood === "paused" ? ["#0e0c1c", "#040308"] : ["#071824", "#02070c"];
    g.addColorStop(0, tint[0]); g.addColorStop(1, tint[1]);
    ctx.fillStyle = g;
    ctx.fillRect(x, y, CELL_PX, CELL_PX);
    // Scan lines.
    ctx.fillStyle = "rgba(255,255,255,0.035)";
    for (let k = 0; k < CELL_PX; k += 3) ctx.fillRect(x, y + k, CELL_PX, 1);
  }

  private drawBlank(index: number): void {
    const [x, y] = this.cellOrigin(index);
    this.background(x, y, "idle");
  }

  private draw(slot: Slot, frame: number): void {
    const [x, y] = this.cellOrigin(slot.index);
    const { ctx } = this;
    ctx.save();
    ctx.beginPath(); ctx.rect(x, y, CELL_PX, CELL_PX); ctx.clip();
    this.background(x, y, slot.mood);
    if (slot.look.kind === "creature") {
      const body = creatureBody(slot.look.creature);
      paintCreature(this.sctx, this.scratch.width, body, creaturePose(MOOD_STATE[slot.mood], frame), 0);
      const w = this.scratch.width, h = this.scratch.height;
      ctx.globalAlpha = slot.mood === "paused" ? 0.55 : 1;
      ctx.drawImage(this.scratch, x + (CELL_PX - w) / 2, y + (CELL_PX - h) / 2 + 2, w, h);
      ctx.globalAlpha = 1;
    } else {
      drawShapeFace(ctx, x, y, slot.look.shape, slot.look.color, slot.mood, frame);
    }
    ctx.restore();
  }
}

function hashId(id: string): number {
  let h = 0;
  for (let i = 0; i < id.length; i += 1) h = (h * 31 + id.charCodeAt(i)) | 0;
  return Math.abs(h);
}

function shapePath(ctx: CanvasRenderingContext2D, shape: SymbolShape, cx: number, cy: number, r: number): void {
  ctx.beginPath();
  switch (shape) {
    case "triangle": ctx.moveTo(cx, cy - r); ctx.lineTo(cx + r * 0.95, cy + r * 0.75); ctx.lineTo(cx - r * 0.95, cy + r * 0.75); ctx.closePath(); break;
    case "hexagon": for (let k = 0; k < 6; k += 1) { const a = (k / 6) * Math.PI * 2 - Math.PI / 2; ctx[k ? "lineTo" : "moveTo"](cx + Math.cos(a) * r, cy + Math.sin(a) * r); } ctx.closePath(); break;
    case "squircle": ctx.roundRect(cx - r, cy - r, r * 2, r * 2, r * 0.45); break;
    case "pill": ctx.roundRect(cx - r, cy - r * 0.72, r * 2, r * 1.44, r * 0.72); break;
    case "drop": ctx.moveTo(cx, cy - r); ctx.quadraticCurveTo(cx + r, cy, cx + r * 0.8, cy + r * 0.4); ctx.arc(cx, cy + r * 0.3, r * 0.8, 0.2, Math.PI - 0.2); ctx.quadraticCurveTo(cx - r, cy, cx, cy - r); break;
    case "cloud": ctx.arc(cx - r * 0.45, cy + r * 0.15, r * 0.5, 0, Math.PI * 2); ctx.arc(cx + r * 0.45, cy + r * 0.15, r * 0.5, 0, Math.PI * 2); ctx.arc(cx, cy - r * 0.25, r * 0.6, 0, Math.PI * 2); break;
    default: ctx.arc(cx, cy, r, 0, Math.PI * 2);
  }
}

function drawShapeFace(ctx: CanvasRenderingContext2D, x: number, y: number, shape: SymbolShape, color: string, mood: FaceMood, frame: number): void {
  const cx = x + CELL_PX / 2, cy = y + CELL_PX / 2 + 2, r = CELL_PX * 0.32;
  ctx.globalAlpha = mood === "paused" ? 0.5 : 1;
  ctx.fillStyle = color;
  shapePath(ctx, shape, cx, cy, r);
  ctx.fill();
  const blink = frame % 60 < 2 || mood === "paused";
  const look = mood === "working" ? 3 : frame % 60 > 30 && frame % 60 < 36 ? -3 : 0;
  ctx.fillStyle = "#0b0d12";
  for (const s of [-1, 1]) {
    if (blink) ctx.fillRect(cx + s * r * 0.36 - 4 + look, cy - 1, 8, 2);
    else ctx.fillRect(cx + s * r * 0.36 - 2.5 + look, cy - 6 + (mood === "working" ? 2 : 0), 5, 9);
  }
  ctx.globalAlpha = 1;
}
