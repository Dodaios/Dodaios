/**
 * A small picture of the app in a design: the rail, a reply, a sent bubble
 * and the composer, painted with the design's own tokens and its background
 * moving over them. The tokens are set as CSS variables on the preview's
 * root, so everything inside paints with the design while the page around it
 * keeps its own colours.
 */
import type { CSSProperties } from "react";
import { DesignBackdrop } from "@/components/designs/DesignBackdrop";
import type { Design, DesignPalette } from "@/lib/designs/designsApi";
import { hexToRgb, luminance, paletteTokens } from "@/lib/designs/tokens";

/** The standard look's three inputs, for the "Standard" tile. */
export const STANDARD_PALETTES: Record<"dark" | "light", DesignPalette> = {
  dark: { background: "#0a0a0a", foreground: "#fafafa", accent: "#3d8bff" },
  light: { background: "#ffffff", foreground: "#171717", accent: "#096cdc" },
};

/** The palette a design shows in `appearance`, falling back to its other side. */
export function paletteFor(design: Design | null, appearance: "dark" | "light"): DesignPalette {
  if (!design) return STANDARD_PALETTES[appearance];
  return design[appearance] ?? design[appearance === "dark" ? "light" : "dark"] ?? STANDARD_PALETTES[appearance];
}

interface Props {
  design: Design | null;
  appearance: "dark" | "light";
  animate: boolean;
}

export function DesignPreview({ design, appearance, animate }: Props) {
  const palette = paletteFor(design, appearance);
  const tokens = paletteTokens(palette) as CSSProperties;
  const dark = luminance(hexToRgb(palette.background)) < luminance(hexToRgb(palette.foreground));
  return (
    <div
      className="relative isolate flex aspect-[16/10] w-full overflow-hidden rounded-lg border border-border bg-background"
      style={tokens}
      aria-hidden
    >
      <div className="flex w-[22%] flex-col gap-1.5 border-r border-border bg-sidebar p-2">
        <span className="h-1.5 w-3/4 rounded-full bg-foreground/70" />
        <span className="h-1.5 w-full rounded-full bg-secondary" />
        <span className="h-1.5 w-2/3 rounded-full bg-muted-foreground/40" />
        <span className="h-1.5 w-4/5 rounded-full bg-muted-foreground/40" />
      </div>
      <div className="flex flex-1 flex-col gap-2 p-2.5">
        <div className="ml-auto h-4 w-2/5 rounded-md" style={{ background: "hsl(var(--chat-bubble-out))" }} />
        <div className="flex flex-col gap-1">
          <span className="h-1.5 w-11/12 rounded-full bg-foreground/80" />
          <span className="h-1.5 w-4/5 rounded-full bg-foreground/60" />
          <span className="h-1.5 w-1/2 rounded-full bg-muted-foreground/60" />
        </div>
        <div className="flex items-center gap-1">
          <span className="h-1.5 w-1.5 rounded-full" style={{ background: "hsl(var(--accent))" }} />
          <span className="h-1.5 w-1/3 rounded-full" style={{ background: "hsl(var(--accent) / 0.7)" }} />
        </div>
        <div className="mt-auto flex h-5 items-center justify-end rounded-md border border-border bg-card px-1">
          <span className="h-3 w-3 rounded-full bg-primary" />
        </div>
      </div>
      {design && <DesignBackdrop background={design.background} dark={dark} contained still={!animate} />}
    </div>
  );
}
