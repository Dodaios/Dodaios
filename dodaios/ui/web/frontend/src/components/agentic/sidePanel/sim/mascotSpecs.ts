import antigravitySvg from "@/assets/providers/antigravity.svg?raw";
import deepseekSvg from "@/assets/providers/deepseek.svg?raw";
import claudeCodeSvg from "@/assets/agents/claude-code.svg?raw";
import codexSvg from "@/assets/agents/codex.svg?raw";
import cursorSvg from "@/assets/agents/cursor.svg?raw";
import grokBuildSvg from "@/assets/agents/grok-build.svg?raw";
import kimiSvg from "@/assets/agents/kimi.svg?raw";
import opencodeSvg from "@/assets/agents/opencode.svg?raw";
import zaiSvg from "@/assets/agents/zai.svg?raw";

/**
 * How a coding agent's own mark becomes its figure in the simulation.
 *
 * A figure IS the agent's mark, given depth: the outline of the shipped file
 * (`src/assets/agents/LOGOS.md`, `src/assets/providers/LOGOS.md`) is extruded
 * as drawn. Nothing is redrawn and nothing is recoloured: a full-colour mark
 * keeps the vendor's colours, a single-colour glyph is drawn in the theme's
 * text ink, exactly as `AgentMark` draws it flat.
 */

/**
 * Where a figure's colour comes from.
 *
 * * `ink` — a single-colour glyph: the theme's text ink.
 * * `flat` — each path's own fill colour from the file.
 * * `picture` — the file itself, painted by the browser and laid over the
 *   figure. For marks whose colour is a gradient or a blur no single fill
 *   can state.
 */
export type MascotPaint = "ink" | "flat" | "picture";

/** A rectangle in the file's own units (its 24-unit view box). */
export interface MascotRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface MascotSpec {
  /** The file's text, as shipped. */
  svg: string;
  paint: MascotPaint;
  /** Which paths of the file are the figure's body, by their order in it. */
  body: readonly number[];
  /** Paths that stand out of the body on both faces (a glyph on a tile). */
  relief?: readonly number[];
  /**
   * Openings of the mark that are eyes: each is closed with a dark pane set
   * back into the body, so the eyes read as eyes from every side.
   */
  eyes?: readonly MascotRect[];
}

/** One body path, whole file. */
const WHOLE: readonly number[] = [0];

export const MASCOT_SPECS: Record<string, MascotSpec> = {
  // The mask's outline is the arch; the paths after it are the blurred colour
  // fields the picture supplies.
  antigravity: { svg: antigravitySvg, paint: "picture", body: WHOLE },
  // The mascot. Its two eyes are openings in the one path of the file.
  claude: {
    svg: claudeCodeSvg,
    paint: "flat",
    body: WHOLE,
    eyes: [
      { x: 6, y: 8.102, width: 1.488, height: 2.847 },
      { x: 16.51, y: 8.102, width: 1.49, height: 2.847 },
    ],
  },
  // A white tile with the gradient glyph standing out of it.
  codex: { svg: codexSvg, paint: "picture", body: WHOLE, relief: [1] },
  cursor: { svg: cursorSvg, paint: "ink", body: WHOLE },
  "deepseek-harness": { svg: deepseekSvg, paint: "flat", body: WHOLE },
  glm: { svg: zaiSvg, paint: "ink", body: WHOLE },
  "grok-build": { svg: grokBuildSvg, paint: "ink", body: WHOLE },
  kimi: { svg: kimiSvg, paint: "ink", body: WHOLE },
  opencode: { svg: opencodeSvg, paint: "ink", body: WHOLE },
};

/** The figure for an agent, or null for one without a shipped mark. */
export function mascotSpecFor(agent: string): MascotSpec | null {
  return MASCOT_SPECS[agent] ?? null;
}
