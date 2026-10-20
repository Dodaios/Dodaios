/**
 * What a console or terminal screen shows, drawn into a small canvas: a
 * monochrome ship display (green for live work, amber when the crew member
 * needs the commander, red on a fault, dim blue on standby), a header strip
 * with the station and the status, the tail of the agent's chat or the pane's
 * terminal in a small pixel font, and faint scanlines. Restrained enough to
 * sit inside the photograph. Pure drawing; the caller owns canvas and texture.
 */

export type ScreenTone = "live" | "attention" | "fault" | "standby";

export interface ScreenFace {
  tone: ScreenTone;
  /** Header left: the station or the agent's name. */
  title: string;
  /** Header right: the status word. */
  status: string;
  /** Body lines, oldest first; the newest that fit are shown. */
  lines: readonly string[];
  /** A blinking block cursor after the last line. */
  cursor: boolean;
}

const PALETTE: Readonly<Record<ScreenTone, { ground: string; ink: string; dim: string; bar: string }>> = {
  live: { ground: "#030a07", ink: "#7ed29b", dim: "#3b6b4c", bar: "#0b1f15" },
  attention: { ground: "#0b0803", ink: "#e0b064", dim: "#7a5b2a", bar: "#21180a" },
  fault: { ground: "#0c0404", ink: "#e07062", dim: "#7a332c", bar: "#240c0a" },
  standby: { ground: "#03060b", ink: "#6f93b8", dim: "#2f4258", bar: "#0a121c" },
};

/** Canvas pixels per metre of screen width; tall enough for the text to read when zoomed in. */
export const SCREEN_PX_PER_M = 320;
const FONT = "\"JetBrains Mono\", ui-monospace, Consolas, monospace";

/** Canvas size for a screen of the given metres, power-of-two friendly and bounded. */
export function screenCanvasSize(widthM: number, heightM: number): { width: number; height: number } {
  const width = Math.max(96, Math.min(768, Math.round(widthM * SCREEN_PX_PER_M)));
  const height = Math.max(48, Math.min(512, Math.round(heightM * SCREEN_PX_PER_M)));
  return { width, height };
}

/** Lines wrapped to `cols` characters, newest kept. Pure. */
export function wrapTail(lines: readonly string[], cols: number, rows: number): string[] {
  const out: string[] = [];
  for (const line of lines) {
    const flat = line.replace(/\s+/g, " ").trimEnd();
    if (!flat) { out.push(""); continue; }
    for (let i = 0; i < flat.length; i += cols) out.push(flat.slice(i, i + cols));
  }
  return out.slice(-rows);
}

export function paintScreen(ctx: CanvasRenderingContext2D, face: ScreenFace, blinkOn: boolean): void {
  const { width: w, height: h } = ctx.canvas;
  const c = PALETTE[face.tone];
  ctx.fillStyle = c.ground;
  ctx.fillRect(0, 0, w, h);
  const fontPx = Math.max(7, Math.round(h / 11));
  const lineH = Math.round(fontPx * 1.25);
  const pad = Math.max(4, Math.round(fontPx * 0.6));
  const headH = lineH + pad;
  ctx.fillStyle = c.bar;
  ctx.fillRect(0, 0, w, headH);
  ctx.fillStyle = c.dim;
  ctx.fillRect(0, headH, w, 1);
  ctx.textBaseline = "top";
  ctx.font = `600 ${fontPx}px ${FONT}`;
  const charW = ctx.measureText("M").width || fontPx * 0.6;
  const cols = Math.max(8, Math.floor((w - pad * 2) / charW));
  const status = face.status.toUpperCase();
  ctx.fillStyle = c.ink;
  ctx.textAlign = "right";
  ctx.fillText(status, w - pad, Math.round(pad / 2) + 1);
  ctx.textAlign = "left";
  ctx.fillStyle = c.dim;
  const titleCols = Math.max(0, cols - status.length - 2);
  ctx.fillText(face.title.toUpperCase().slice(0, titleCols), pad, Math.round(pad / 2) + 1);
  ctx.font = `${fontPx}px ${FONT}`;
  const rows = Math.max(1, Math.floor((h - headH - pad) / lineH));
  const body = wrapTail(face.lines, cols, rows);
  body.forEach((line, i) => {
    // Older lines fade a little, so the newest work reads first.
    ctx.globalAlpha = 0.55 + 0.45 * ((i + 1) / body.length);
    ctx.fillStyle = c.ink;
    ctx.fillText(line, pad, headH + pad / 2 + i * lineH);
  });
  ctx.globalAlpha = 1;
  if (face.cursor && blinkOn) {
    const last = body[body.length - 1] ?? "";
    const row = Math.max(0, body.length - (last.length >= cols ? 0 : 1));
    const col = last.length >= cols ? 0 : last.length;
    ctx.fillStyle = c.ink;
    ctx.fillRect(pad + col * charW, headH + pad / 2 + row * lineH + 1, Math.max(2, charW * 0.8), fontPx);
  }
  // Scanlines: a faint darkening every other pixel row.
  ctx.fillStyle = "rgba(0,0,0,0.18)";
  for (let y = 0; y < h; y += 2) ctx.fillRect(0, y, w, 1);
}
