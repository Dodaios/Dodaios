import { useEffect, useRef, useState } from "react";
import { ChevronDown, Columns2, Maximize2, Minimize2, Rows2, X } from "lucide-react";
import { clsx } from "clsx";

import { resolveNavLabel } from "@/components/layout/navGroups";
import { navItemFor, TILEABLE_NAV_ITEMS } from "@/components/layout/tiling/tileSection";
import { useT } from "@/i18n";
import { MAX_TILES, leaves } from "@/lib/tilingLayout";
import { sectionWindow } from "@/lib/sectionWindows";
import type { SectionId } from "@/store/events";
import { useTilingStore } from "@/store/tiling";

/** Drag payload type: a tile's id, dropped on another tile to swap the two. */
export const TILE_DRAG_TYPE = "application/x-dodaios-tile";

const ICON_BUTTON =
  "inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-muted-foreground " +
  "transition-colors hover:bg-secondary hover:text-foreground focus-visible:outline-none " +
  "focus-visible:ring-2 focus-visible:ring-ring";

/**
 * The slim title row of one tile: what it shows (click to change it), and
 * split, maximize and close. Dragging the row onto another tile swaps them.
 */
export function TileHeader({
  leafId,
  section,
  focused,
  maximized,
}: {
  leafId: string;
  section: SectionId;
  focused: boolean;
  maximized: boolean;
}) {
  const t = useT();
  const tree = useTilingStore((s) => s.tree);
  const tileCount = leaves(tree).length;
  const shownOwners = leaves(tree).map((item) => sectionWindow(item.section));
  const { splitTile, closeTile, toggleMaximize, setTileSection } = useTilingStore.getState();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const item = navItemFor(section);
  const Icon = item?.icon;
  const label = item ? resolveNavLabel(t, item) : section;
  const canSplit = tileCount < MAX_TILES;

  useEffect(() => {
    if (!menuOpen) return;
    const onDown = (event: PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setMenuOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
    };
    window.addEventListener("pointerdown", onDown, true);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("pointerdown", onDown, true);
      window.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  return (
    <div
      className={clsx(
        "relative flex h-7 shrink-0 items-center gap-1 border-b border-border/60 px-1.5 select-none",
        focused ? "bg-secondary/70" : "bg-card/60",
      )}
      draggable={!maximized}
      onDragStart={(event) => {
        event.dataTransfer.setData(TILE_DRAG_TYPE, leafId);
        event.dataTransfer.effectAllowed = "move";
      }}
      data-testid="tile-header"
    >
      <div ref={menuRef} className="relative min-w-0">
        <button
          type="button"
          className={clsx(
            "flex h-6 min-w-0 items-center gap-1.5 rounded-md px-1.5 text-meta font-medium transition-colors hover:bg-secondary",
            focused ? "text-foreground" : "text-muted-foreground",
          )}
          onClick={() => setMenuOpen((open) => !open)}
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          title={t("tiling.change_section")}
          data-testid="tile-section-button"
        >
          {Icon && <Icon aria-hidden className="h-3.5 w-3.5 shrink-0" />}
          <span className="truncate">{label}</span>
          <ChevronDown aria-hidden className="h-3 w-3 shrink-0 opacity-60" />
        </button>
        {menuOpen && (
          <div
            role="menu"
            className="absolute left-0 top-7 z-30 max-h-[60vh] w-56 overflow-y-auto rounded-lg border border-border bg-popover p-1 shadow-lg"
          >
            {TILEABLE_NAV_ITEMS.map((entry) => {
              const EntryIcon = entry.icon;
              const current = sectionWindow(entry.id) === sectionWindow(section);
              const elsewhere = !current && shownOwners.includes(sectionWindow(entry.id));
              return (
                <button
                  key={entry.id}
                  type="button"
                  role="menuitem"
                  className={clsx(
                    "flex h-8 w-full items-center gap-2 rounded-md px-2 text-left text-meta transition-colors hover:bg-secondary",
                    current ? "text-foreground-strong" : "text-foreground",
                  )}
                  onClick={() => {
                    setMenuOpen(false);
                    setTileSection(leafId, entry.id);
                  }}
                >
                  <EntryIcon aria-hidden className="h-4 w-4 shrink-0" />
                  <span className="min-w-0 flex-1 truncate">{resolveNavLabel(t, entry)}</span>
                  {elsewhere && <span className="text-[10px] text-muted-foreground">{t("tiling.swap")}</span>}
                </button>
              );
            })}
          </div>
        )}
      </div>
      <div className="min-w-0 flex-1" />
      {canSplit && !maximized && (
        <>
          <button type="button" className={ICON_BUTTON} title={t("tiling.split_right")}
            aria-label={t("tiling.split_right")} onClick={() => splitTile(leafId, "row")}>
            <Columns2 aria-hidden className="h-3.5 w-3.5" />
          </button>
          <button type="button" className={ICON_BUTTON} title={t("tiling.split_down")}
            aria-label={t("tiling.split_down")} onClick={() => splitTile(leafId, "column")}>
            <Rows2 aria-hidden className="h-3.5 w-3.5" />
          </button>
        </>
      )}
      <button type="button" className={ICON_BUTTON}
        title={t(maximized ? "tiling.restore" : "tiling.maximize")}
        aria-label={t(maximized ? "tiling.restore" : "tiling.maximize")}
        onClick={() => toggleMaximize(leafId)} data-testid="tile-maximize">
        {maximized ? <Minimize2 aria-hidden className="h-3.5 w-3.5" /> : <Maximize2 aria-hidden className="h-3.5 w-3.5" />}
      </button>
      <button type="button" className={ICON_BUTTON} title={t("tiling.close")}
        aria-label={t("tiling.close")} onClick={() => closeTile(leafId)} data-testid="tile-close">
        <X aria-hidden className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
