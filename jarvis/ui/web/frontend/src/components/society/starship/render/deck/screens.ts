/**
 * Every console screen of a deck in one atlas texture. A screen shows its
 * owner's real work: the tail of its chat (the captain's lines in gold, its
 * own replies in white, running tools in cyan) or a live terminal on
 * engineering; an idle console a calm standby page, an empty one "vacant".
 * Cells are redrawn only when their content changes; a cursor blinks on the
 * working ones.
 */
import { CanvasTexture, SRGBColorSpace } from "three";
import type { ChatLine } from "../../../crewFeeds/deskChat";

export const SCREEN_COLS = 8;
export const SCREEN_ROWS = 8;
export const SCREEN_W = 256;
export const SCREEN_H = 140;

export type ScreenState = "working" | "waiting" | "idle" | "paused" | "vacant" | "error";

export interface ScreenContent {
  title: string;
  state: ScreenState;
  accent: string;
  /** Chat lines (agents deck) or terminal rows (engineering). */
  lines?: readonly ChatLine[];
  rows?: readonly string[];
  /** Words for the state chip, already translated. */
  stateLabel: string;
  /** Shown on a console without live content. */
  standby: string;
}

const STATE_COLOUR: Record<ScreenState, string> = {
  working: "#3fd27f", waiting: "#ffb020", idle: "#8aa4c8", paused: "#8a7fc8", vacant: "#4a5566", error: "#ff4d5e",
};

const LINE_COLOUR: Record<ChatLine["kind"], string> = {
  user: "#f2c46b", agent: "#e8eef6", tool: "#6fd8ff", notice: "#9aa6b8", error: "#ff7a85",
};

interface Cell { index: number; key: string; content: ScreenContent }

export class ScreenAtlas {
  readonly canvas: HTMLCanvasElement;
  readonly texture: CanvasTexture;
  private readonly ctx: CanvasRenderingContext2D;
  private readonly cells = new Map<string, Cell>();
  private readonly free: number[] = [];
  private dirty = false;
  private blink = false;

  constructor() {
    this.canvas = document.createElement("canvas");
    this.canvas.width = SCREEN_COLS * SCREEN_W;
    this.canvas.height = SCREEN_ROWS * SCREEN_H;
    const ctx = this.canvas.getContext("2d");
    if (!ctx) throw new Error("2d canvas unavailable");
    this.ctx = ctx;
    for (let i = SCREEN_COLS * SCREEN_ROWS - 1; i >= 0; i -= 1) this.free.push(i);
    this.texture = new CanvasTexture(this.canvas);
    this.texture.colorSpace = SRGBColorSpace;
    this.texture.anisotropy = 4;
  }

  uv(id: string): [number, number, number, number] {
    let cell = this.cells.get(id);
    if (!cell) {
      const index = this.free.pop() ?? 0;
      cell = { index, key: "", content: { title: "", state: "vacant", accent: "#5fd4ff", stateLabel: "", standby: "" } };
      this.cells.set(id, cell);
    }
    const c = cell.index % SCREEN_COLS, r = Math.floor(cell.index / SCREEN_COLS);
    const e = 0.5 / this.canvas.width;
    return [c / SCREEN_COLS + e, 1 - (r + 1) / SCREEN_ROWS + e, (c + 1) / SCREEN_COLS - e, 1 - r / SCREEN_ROWS - e];
  }

  release(id: string): void {
    const cell = this.cells.get(id);
    if (!cell) return;
    this.cells.delete(id);
    this.free.push(cell.index);
  }

  set(id: string, content: ScreenContent): void {
    const cell = this.cells.get(id);
    if (!cell) return;
    cell.content = content;
  }

  /** Redraw changed cells; the cursor of working screens blinks twice a second. */
  tick(nowMs: number): void {
    const blink = Math.floor(nowMs / 500) % 2 === 0;
    const blinkChanged = blink !== this.blink;
    this.blink = blink;
    for (const cell of this.cells.values()) {
      const c = cell.content;
      const lines = c.lines ? c.lines.map((l) => `${l.kind}:${l.text}`).join("\n") : c.rows?.join("\n") ?? "";
      const live = c.state === "working";
      const key = `${c.title}|${c.state}|${c.accent}|${c.stateLabel}|${lines}|${live && blink ? 1 : 0}`;
      if (key === cell.key && !(live && blinkChanged)) continue;
      cell.key = key;
      this.draw(cell);
      this.dirty = true;
    }
    if (this.dirty) { this.texture.needsUpdate = true; this.dirty = false; }
  }

  private draw(cell: Cell): void {
    const { ctx } = this;
    const x = (cell.index % SCREEN_COLS) * SCREEN_W, y = Math.floor(cell.index / SCREEN_COLS) * SCREEN_H;
    const c = cell.content;
    ctx.save();
    ctx.beginPath(); ctx.rect(x, y, SCREEN_W, SCREEN_H); ctx.clip();
    const bg = ctx.createLinearGradient(x, y, x, y + SCREEN_H);
    bg.addColorStop(0, c.state === "vacant" ? "#05080c" : "#07121c"); bg.addColorStop(1, "#02050a");
    ctx.fillStyle = bg; ctx.fillRect(x, y, SCREEN_W, SCREEN_H);
    // Header: a thin accent rule, the title and the state chip.
    ctx.fillStyle = c.accent; ctx.globalAlpha = 0.9; ctx.fillRect(x, y, SCREEN_W, 3); ctx.globalAlpha = 1;
    ctx.font = "600 13px 'Space Grotesk', 'Inter Variable', sans-serif";
    ctx.textBaseline = "middle";
    ctx.fillStyle = "#e8eef6";
    ctx.fillText(clip(ctx, c.title.toUpperCase(), SCREEN_W - 96), x + 10, y + 16);
    const chip = STATE_COLOUR[c.state];
    ctx.font = "600 10px 'JetBrains Mono', monospace";
    const label = c.stateLabel.toUpperCase();
    const lw = ctx.measureText(label).width + 16;
    ctx.fillStyle = chip; ctx.globalAlpha = 0.18;
    ctx.fillRect(x + SCREEN_W - lw - 8, y + 8, lw, 16); ctx.globalAlpha = 1;
    ctx.fillStyle = chip;
    ctx.beginPath(); ctx.arc(x + SCREEN_W - lw - 1, y + 16, 3, 0, Math.PI * 2); ctx.fill();
    ctx.fillText(label, x + SCREEN_W - lw + 6, y + 16.5);
    ctx.fillStyle = "rgba(255,255,255,0.08)"; ctx.fillRect(x + 8, y + 29, SCREEN_W - 16, 1);
    const body = c.lines?.length ? c.lines.map((l) => ({ text: l.text, colour: LINE_COLOUR[l.kind], mono: l.kind === "tool" }))
      : c.rows?.length ? c.rows.map((r) => ({ text: r, colour: "#cfe6d8", mono: true })) : null;
    if (body) {
      const rowH = 13;
      const fit = Math.floor((SCREEN_H - 40) / rowH);
      const shown = body.slice(-fit);
      shown.forEach((line, i) => {
        ctx.font = line.mono ? "10px 'JetBrains Mono', monospace" : "11px 'Inter Variable', sans-serif";
        ctx.fillStyle = line.colour;
        ctx.globalAlpha = 0.55 + 0.45 * ((i + 1) / shown.length);
        ctx.fillText(clip(ctx, line.text.replace(/\s+/g, " "), SCREEN_W - 22), x + 10, y + 40 + i * rowH);
      });
      ctx.globalAlpha = 1;
      if (c.state === "working" && this.blink) {
        ctx.fillStyle = c.accent;
        ctx.fillRect(x + 10, y + 40 + Math.min(shown.length, fit - 1) * rowH - 5, 7, 10);
      }
    } else {
      // Standby: the division's ring and one quiet word.
      ctx.strokeStyle = c.accent; ctx.globalAlpha = c.state === "vacant" ? 0.25 : 0.6; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(x + SCREEN_W / 2, y + 82, 26, 0, Math.PI * 2); ctx.stroke();
      ctx.beginPath(); ctx.arc(x + SCREEN_W / 2, y + 82, 16, -0.4, Math.PI * 1.3); ctx.stroke();
      ctx.globalAlpha = 1;
      ctx.font = "600 10px 'JetBrains Mono', monospace";
      ctx.fillStyle = "#8aa0b8";
      ctx.textAlign = "center";
      ctx.fillText(c.standby.toUpperCase(), x + SCREEN_W / 2, y + 126);
      ctx.textAlign = "left";
    }
    // Scan lines over everything.
    ctx.fillStyle = "rgba(0,0,0,0.18)";
    for (let k = 0; k < SCREEN_H; k += 3) ctx.fillRect(x, y + k, SCREEN_W, 1);
    ctx.restore();
  }
}

function clip(ctx: CanvasRenderingContext2D, text: string, width: number): string {
  if (ctx.measureText(text).width <= width) return text;
  let lo = 0, hi = text.length;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (ctx.measureText(text.slice(0, mid) + "…").width <= width) lo = mid; else hi = mid - 1;
  }
  return text.slice(0, lo) + "…";
}
