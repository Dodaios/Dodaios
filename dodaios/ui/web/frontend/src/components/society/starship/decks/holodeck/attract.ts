/**
 * Attract mode for the holographic cabinets: two tiny pixel frames per game,
 * drawn once into one atlas. The screens flip between the frames, which is
 * all an attract loop needs to read as "a game is running" from across the
 * deck. Black is empty: the hologram is additive.
 */
import { CanvasTexture, NearestFilter, SRGBColorSpace } from "three";
import { ARCADE_GAMES, type ArcadeGameInfo } from "../../../arcade/arcadeGames";

export const CELL_W = 64;
export const CELL_H = 48;
const ATLAS_W = CELL_W * 2;
const ATLAS_H = 512;

type Paint = (px: (x: number, y: number, w?: number, h?: number, colour?: string) => void, frame: 0 | 1, look: ArcadeGameInfo["look"]) => void;

const SCENES: Record<string, Paint> = {
  "asteroid-run": (px, f, look) => {
    for (const [x, y] of [[6, 5], [50, 9], [20, 40], [58, 30], [33, 3]]) px(x, y, 1, 1, "#9fb3c8");
    const rocks = f ? [[12, 12], [44, 30], [28, 34]] : [[14, 13], [42, 28], [30, 36]];
    for (const [x, y] of rocks) { px(x, y, 5, 4, look.marqueeText); px(x + 1, y - 1, 3, 1, look.marqueeText); px(x + 1, y + 4, 3, 1, look.marqueeText); }
    const sy = f ? 22 : 24;
    px(30, sy, 1, 1, look.accent); px(29, sy + 1, 3, 2, look.accent); px(28, sy + 3, 5, 1, look.accent);
    if (f) px(30, sy - 6, 1, 3, "#ffffff");
  },
  "neon-snake": (px, f, look) => {
    const body = [[4, 6], [5, 6], [6, 6], [7, 6], [7, 5], [7, 4], [8, 4], [9, 4]];
    const cells = f ? [...body.slice(1), [10, 4]] : body;
    for (const [cx, cy] of cells) px(cx * 4 + 1, cy * 4 + 1, 3, 3, look.accent);
    px(12 * 4 + 1, 4 * 4 + 1, 3, 3, look.marqueeText);
    px(0, 0, 64, 1, look.accent); px(0, 47, 64, 1, look.accent); px(0, 0, 1, 48, look.accent); px(63, 0, 1, 48, look.accent);
  },
  "brick-breaker": (px, f, look) => {
    for (let r = 0; r < 3; r += 1) for (let c = 0; c < 6; c += 1) if (!(r === 2 && c === (f ? 3 : 2))) px(3 + c * 10, 4 + r * 5, 8, 3, r === 0 ? look.marqueeText : look.accent);
    px(f ? 26 : 22, 43, 14, 2, "#ffffff");
    px(f ? 34 : 28, f ? 24 : 32, 2, 2, "#ffffff");
  },
  "paddle-duel": (px, f, look) => {
    for (let y = 2; y < 46; y += 6) px(31, y, 2, 3, look.accent);
    px(4, f ? 14 : 20, 2, 10, look.marqueeText);
    px(58, f ? 24 : 18, 2, 10, look.marqueeText);
    px(f ? 40 : 20, f ? 28 : 22, 2, 2, "#ffffff");
  },
  "block-drop": (px, f, look) => {
    const stack = [[0, 5], [1, 5], [2, 5], [4, 5], [5, 5], [6, 5], [7, 5], [0, 4], [1, 4], [5, 4], [6, 4], [7, 4], [0, 3], [6, 3]];
    for (const [c, r] of stack) px(16 + c * 4, 22 + r * 4, 3, 3, r === 5 ? look.accent : look.marqueeText);
    const top = f ? 14 : 6;
    for (const [c, r] of [[2, 0], [3, 0], [4, 0], [3, 1]]) px(16 + c * 4, top + r * 4, 3, 3, "#ffffff");
    px(15, 2, 1, 44, look.accent); px(48, 2, 1, 44, look.accent);
  },
  "maze-muncher": (px, f, look) => {
    px(2, 2, 60, 1, look.accent); px(2, 45, 60, 1, look.accent); px(2, 2, 1, 44, look.accent); px(61, 2, 1, 44, look.accent);
    px(12, 14, 16, 1, look.accent); px(36, 14, 16, 1, look.accent); px(12, 33, 40, 1, look.accent); px(31, 14, 1, 10, look.accent);
    for (let x = 30; x < 58; x += 5) px(x, 24, 1, 1, "#ffe9b8");
    // The muncher: mouth open, then closed.
    const cx = f ? 22 : 18;
    px(cx - 2, 20, 5, 9, look.marqueeText); px(cx - 4, 22, 9, 5, look.marqueeText); px(cx - 3, 21, 7, 7, look.marqueeText);
    if (!f) { px(cx + 1, 24, 4, 1, "#000000"); px(cx + 2, 23, 3, 3, "#000000"); }
    px(44, 37, 6, 6, "#ff5d7a"); px(45, 36, 4, 1, "#ff5d7a");
  },
  "desert-dash": (px, f, look) => {
    px(0, 40, 64, 1, look.accent);
    for (const x of [8, 27, 50]) px((x + (f ? 60 : 0)) % 64, 42, 2, 1, look.accent);
    const cx = f ? 40 : 46;
    px(cx, 31, 2, 9, "#7ed957"); px(cx - 3, 34, 3, 1, "#7ed957"); px(cx - 3, 31, 1, 3, "#7ed957"); px(cx + 2, 33, 3, 1, "#7ed957"); px(cx + 4, 30, 1, 3, "#7ed957");
    const y = f ? 24 : 31;
    px(12, y, 6, 6, look.marqueeText); px(16, y - 2, 4, 3, look.marqueeText);
    px(f ? 12 : 13, y + 6, 1, 3, look.marqueeText); px(f ? 17 : 16, y + 6, 1, 3, look.marqueeText);
  },
  "pixel-raiders": (px, f, look) => {
    for (let r = 0; r < 2; r += 1) for (let c = 0; c < 5; c += 1) {
      const x = 6 + c * 11 + (f ? 2 : 0), y = 6 + r * 9;
      const colour = r ? look.accent : look.marqueeText;
      px(x + 1, y, 5, 1, colour); px(x, y + 1, 7, 2, colour); px(x + 1, y + 1, 1, 1, "#000000"); px(x + 5, y + 1, 1, 1, "#000000");
      if (f) { px(x, y + 3, 1, 2, colour); px(x + 6, y + 3, 1, 2, colour); } else { px(x + 2, y + 3, 1, 2, colour); px(x + 4, y + 3, 1, 2, colour); }
    }
    px(f ? 34 : 28, 41, 7, 3, "#7cf0ff"); px((f ? 34 : 28) + 3, 39, 1, 2, "#7cf0ff");
    px(f ? 37 : 31, f ? 26 : 32, 1, 4, "#ffffff");
  },
  "road-hopper": (px, f, look) => {
    for (const y of [12, 22, 32]) for (let x = 0; x < 64; x += 8) px(x, y, 4, 1, "#5d6672");
    px(0, 41, 64, 1, look.accent); px(0, 3, 64, 1, look.accent);
    const shift = f ? 6 : 0;
    for (const [x, y, w] of [[6, 14, 10], [40, 14, 8], [20, 24, 12], [52, 24, 8], [10, 34, 9], [44, 34, 11]]) px((x + (y === 24 ? -shift : shift) + 64) % 64, y + 2, w, 4, y === 24 ? look.marqueeText : "#ff7a5a");
    const fy = f ? 27 : 37;
    px(30, fy, 4, 3, look.accent); px(29, fy + 1, 1, 2, look.accent); px(34, fy + 1, 1, 2, look.accent);
  },
  "city-defense": (px, f, look) => {
    for (const [x, h] of [[4, 6], [12, 9], [20, 5], [40, 8], [48, 6], [56, 10]]) px(x, 46 - h, 6, h, look.accent);
    px(29, 40, 6, 6, "#9aa3ae"); px(31, 37, 2, 3, "#9aa3ae");
    const len = f ? 22 : 12;
    for (let k = 0; k < len; k += 1) { px(8 + k, 2 + k, 1, 1, "#ff6a4c"); px(54 - Math.floor(k * 0.6), 2 + k, 1, 1, "#ff6a4c"); }
    if (f) { px(22, 10, 7, 7, look.marqueeText); px(24, 8, 3, 11, look.marqueeText); px(20, 12, 11, 3, look.marqueeText); }
  },
};

/** The atlas of every game's two frames: row = game, column = frame. */
export class AttractAtlas {
  readonly texture: CanvasTexture;
  private readonly rows = new Map<string, number>();

  constructor(games: readonly ArcadeGameInfo[] = ARCADE_GAMES) {
    const canvas = document.createElement("canvas");
    canvas.width = ATLAS_W; canvas.height = ATLAS_H;
    const ctx = canvas.getContext("2d") as CanvasRenderingContext2D;
    ctx.fillStyle = "#000000"; ctx.fillRect(0, 0, ATLAS_W, ATLAS_H);
    games.forEach((game, row) => {
      this.rows.set(game.id, row);
      const paint = SCENES[game.id];
      for (const frame of [0, 1] as const) {
        const ox = frame * CELL_W, oy = row * CELL_H;
        const px = (x: number, y: number, w = 1, h = 1, colour = game.look.accent) => {
          ctx.fillStyle = colour;
          ctx.fillRect(ox + Math.max(0, x), oy + Math.max(0, y), Math.min(w, CELL_W - x), Math.min(h, CELL_H - y));
        };
        if (paint) paint(px, frame, game.look);
        else px(28, 20 + frame * 4, 8, 8);
      }
    });
    this.texture = new CanvasTexture(canvas);
    this.texture.magFilter = NearestFilter;
    this.texture.minFilter = NearestFilter;
    this.texture.generateMipmaps = false;
    this.texture.colorSpace = SRGBColorSpace;
  }

  /** The uv rectangle of a game's first frame: [u0, v0, du, dv]; the second frame sits du to the right. */
  cell(gameId: string): [number, number, number, number] {
    const row = this.rows.get(gameId) ?? 0;
    const dv = CELL_H / ATLAS_H;
    return [0, 1 - (row + 1) * dv, CELL_W / ATLAS_W, dv];
  }

  dispose(): void { this.texture.dispose(); }
}
