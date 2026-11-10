/**
 * The face of an entry, in one of three sizes.
 *
 * A plugin wears its service's brand, the same three tiers the built-in Plugins
 * catalog uses (full-colour mark on the app-icon surface, else the brand glyph
 * on the brand colour, else a monogram). An agent wears the look its template
 * carries. A look shows its preview picture. A skill has no artwork, so it gets a two-letter monogram on a tint
 * derived from its name: the same skill is the same colour in the list, on its
 * page and on the website.
 */
import { useState, type CSSProperties } from "react";
import { AlertTriangle } from "lucide-react";

import { CompanionMark } from "@/components/society/companion/CompanionMark";
import { resolveCompanion } from "@/components/society/companion/appearance";
import { bundledPluginLogo } from "@/lib/pluginLogos";
import { cn } from "@/lib/utils";
import { monogram, nameHue, type Entry } from "./model";

export type MarkSize = "row" | "lead" | "page";

const BOX: Record<MarkSize, string> = {
  row: "h-12 w-12 rounded-xl",
  lead: "h-16 w-16 rounded-2xl",
  page: "h-[72px] w-[72px] rounded-2xl",
};
const GLYPH: Record<MarkSize, string> = { row: "h-6 w-6", lead: "h-8 w-8", page: "h-9 w-9" };
const FULL: Record<MarkSize, string> = { row: "h-8 w-8", lead: "h-10 w-10", page: "h-12 w-12" };
const LETTERS: Record<MarkSize, string> = { row: "text-lg", lead: "text-xl", page: "text-xl" };
const PET: Record<MarkSize, number> = { row: 36, lead: 48, page: 54 };

const DEFAULT_BRAND_TILE = "#3F3F46";
/** Bundled marks drawn in white; on the white app-icon surface they invert. */
const INVERTED_MARKS = new Set(["github", "vercel", "notion", "cal_com"]);

/** A glyph colour that stays legible on the tile (a few brands are near-white). */
function glyphColor(tileHex: string): string {
  const hex = tileHex.replace("#", "");
  if (hex.length !== 6) return "ffffff";
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const lin = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  const luminance = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
  return luminance > 0.6 ? "111111" : "ffffff";
}

/** The name's own tint: quiet on both grounds, readable ink on top. */
const TINT =
  "bg-[hsl(var(--mark-hue)_70%_90%)] text-[hsl(var(--mark-hue)_60%_26%)] " +
  "dark:bg-[hsl(var(--mark-hue)_42%_22%)] dark:text-[hsl(var(--mark-hue)_90%_86%)]";

export function EntryMark({ entry, size = "row" }: { entry: Entry; size?: MarkSize }) {
  const [failed, setFailed] = useState(false);
  const box = cn("grid shrink-0 place-items-center overflow-hidden", BOX[size]);

  if (entry.broken) {
    return (
      <div className={cn(box, "bg-secondary")}>
        <AlertTriangle className="h-4 w-4 text-muted-foreground" />
      </div>
    );
  }

  if (entry.kind === "agent") {
    const appearance = resolveCompanion(entry.agent?.name || entry.name, entry.agent?.avatar?.companion);
    return (
      <div className={cn(box, "bg-secondary")}>
        <CompanionMark appearance={appearance} size={PET[size]} />
      </div>
    );
  }

  if (entry.kind === "look" && entry.previewUrl && !failed) {
    return (
      <div className={cn(box, "bg-secondary")}>
        <img
          src={entry.previewUrl}
          alt=""
          referrerPolicy="no-referrer"
          className="h-full w-full object-cover"
          onError={() => setFailed(true)}
        />
      </div>
    );
  }

  if (entry.kind === "skill" || entry.kind === "look") {
    return (
      <div
        className={cn(box, TINT, "font-display font-semibold tracking-tight", LETTERS[size])}
        style={{ "--mark-hue": nameHue(entry.name) } as CSSProperties}
        aria-hidden
      >
        {monogram(entry.title)}
      </div>
    );
  }

  const tile = entry.logoColor ?? DEFAULT_BRAND_TILE;
  const fullColour = bundledPluginLogo(entry.name) ?? entry.logoUrl ?? null;
  const src =
    fullColour ??
    (entry.logoSlug ? `https://cdn.simpleicons.org/${entry.logoSlug}/${glyphColor(tile)}` : null);
  const lettered = failed || !src;
  const onWhite = Boolean(fullColour) && !lettered;

  return (
    <div
      className={cn(box, onWhite && "border border-border bg-[hsl(var(--plugin-icon-surface))]")}
      style={onWhite ? undefined : { backgroundColor: tile }}
    >
      {lettered ? (
        <span
          className={cn("font-display font-semibold", LETTERS[size])}
          style={{ color: `#${glyphColor(tile)}` }}
        >
          {monogram(entry.title)}
        </span>
      ) : (
        <img
          src={src}
          alt=""
          loading="lazy"
          className={cn(
            onWhite && INVERTED_MARKS.has(entry.name.replace(/-/g, "_")) && "invert",
            onWhite ? FULL[size] : GLYPH[size],
          )}
          onError={() => setFailed(true)}
        />
      )}
    </div>
  );
}
