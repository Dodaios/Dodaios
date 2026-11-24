import { useEffect } from "react";
import { themeFor, type TerminalAppearance } from "../terminalThemes";
import { clearTerminalTextureAtlas } from "../terminalRenderer";
import { alignTerminalCells, terminalFontWeights } from "@/lib/terminalFont";
import type { PanePorts } from "./connect/paneRuntime";

export function usePaneLiveRestyle({ appearance, fontSize, terminalEpoch, termRef, resizeRef, claimResizeRef }: {
  appearance: TerminalAppearance;
  fontSize: number;
  terminalEpoch: number;
  termRef: PanePorts["termRef"];
  resizeRef: PanePorts["resizeRef"];
  claimResizeRef: PanePorts["claimResizeRef"];
}) {
  /*
   * Live restyle — no reconnect, so the running agent is untouched. The canvas
   * renderer caches rendered glyphs per colour in a texture atlas, so a theme
   * change has to invalidate it or the old palette keeps being painted.
   *
   * `terminalEpoch` is in here, and in the size effect below, for a reason the
   * appearance prop alone cannot cover: the terminal can be replaced without
   * either prop changing. Check the replacement's actual options, but leave a
   * correctly initialized terminal alone. Clearing its shared atlas on mount
   * makes every existing WebGL pane rebuild its glyphs too.
   */
  useEffect(() => {
    const term = termRef.current;
    if (!term) return;
    const theme = themeFor(appearance);
    const weights = terminalFontWeights(appearance);
    const transparent = appearance !== "light";
    if (
      term.options.theme === theme &&
      term.options.fontWeight === weights.body &&
      term.options.fontWeightBold === weights.bold &&
      term.options.allowTransparency === transparent
    ) {
      return;
    }
    term.options.theme = theme;
    // Opaque on paper for subpixel-smoothed glyphs — see the constructor.
    term.options.allowTransparency = transparent;
    // A light pane draws one cut heavier (TERMINAL_FONT_WEIGHT_LIGHT). Every
    // cut has the same advance, so the grid stays put and only glyphs change.
    term.options.fontWeight = weights.body;
    term.options.fontWeightBold = weights.bold;
    clearTerminalTextureAtlas(term);
  }, [appearance, terminalEpoch]);

  useEffect(() => {
    const term = termRef.current;
    if (!term || term.options.fontSize === fontSize) return;
    // The setter itself skips unchanged values; the alignment, atlas clear and
    // resize below must also run only for an actual size change.
    term.options.fontSize = fontSize;
    // A new size is a new glyph advance, and so a new fraction of a pixel for
    // the canvas renderer to floor away. Re-align before the fit below, or the
    // pane spends this size with its glyphs overhanging their cells.
    alignTerminalCells(term);
    clearTerminalTextureAtlas(term);
    // Changing the font size changes the COLUMN COUNT. Fitting locally without
    // telling the terminal process leaves the agent formatting for the old
    // width — it keeps wrapping at 100 columns in a pane that now holds 80, and
    // every line breaks in the wrong place. The two must move together, so this
    // goes through the same resize path the observer uses — claiming, because
    // a text size is chosen in THIS window (see `claimResize`).
    (claimResizeRef.current ?? resizeRef.current)?.();
  }, [fontSize, terminalEpoch]);
}
