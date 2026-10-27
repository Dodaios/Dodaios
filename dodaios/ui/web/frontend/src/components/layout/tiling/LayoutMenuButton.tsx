import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, ImageUp, LayoutDashboard, Monitor, RotateCcw } from "lucide-react";
import { clsx } from "clsx";

import { resolveNavLabel } from "@/components/layout/navGroups";
import { SectionPicker } from "@/components/layout/tiling/SectionPicker";
import { navItemFor } from "@/components/layout/tiling/tileSection";
import { useT } from "@/i18n";
import { sectionWindow } from "@/lib/sectionWindows";
import { layoutLeaves, leaves, PRESETS, type PresetId } from "@/lib/tilingLayout";
import { useEventStore, type SectionId } from "@/store/events";
import { useTilingStore } from "@/store/tiling";
import { useWallpaperStore } from "@/hooks/useWallpaper";

const PLACEHOLDER: SectionId[] = ["chats", "agents", "memory", "docs"];

/** Which preset the current tree has the shape of, if any. */
function presetOf(tree: ReturnType<typeof useTilingStore.getState>["tree"]): PresetId | null {
  if (!tree) return "single";
  const shape = (node: typeof tree): string =>
    node.kind === "leaf" ? "L" : `${node.dir}(${shape(node.a)},${shape(node.b)})`;
  const own = shape(tree);
  return PRESETS.find((preset) => shape(preset.build(PLACEHOLDER)) === own)?.id ?? null;
}

/**
 * The caption's layout menu: arrange sections side by side, and pick the
 * picture behind them. Replaces the old "open in its own window" button —
 * sections share the main window now instead of spawning more windows.
 */
export function LayoutMenuButton() {
  const t = useT();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const file = useRef<HTMLInputElement>(null);
  const tree = useTilingStore((s) => s.tree);
  const applyPreset = useTilingStore((s) => s.applyPreset);
  const focusedId = useTilingStore((s) => s.focusedId);
  const stageAspect = useTilingStore((s) => s.stageAspect);
  const [picking, setPicking] = useState<string | null>(null);
  const closePicker = useCallback(() => setPicking(null), []);
  const cells = useMemo(() => layoutLeaves(tree), [tree]);
  const shownOwners = cells.map(({ leaf }) => sectionWindow(leaf.section));
  const source = useWallpaperStore((s) => s.source);
  const current = presetOf(tree);
  const tileCount = Math.max(1, leaves(tree).length);
  const thumbs = useMemo(
    () => PRESETS.map((preset) => ({ preset, cells: layoutLeaves(preset.build(PLACEHOLDER)) })),
    [],
  );

  useEffect(() => {
    if (!open) {
      setPicking(null);
      return;
    }
    void useWallpaperStore.getState().refresh();
    const onDown = (event: PointerEvent) => {
      if (!box.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("pointerdown", onDown, true);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("pointerdown", onDown, true);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const toast = (ok: boolean, okKey: string, failKey: string) =>
    useEventStore.getState().pushToast(ok ? "success" : "error", t(ok ? okKey : failKey));

  return (
    <div ref={box} className="relative flex shrink-0 items-center">
      <button
        type="button"
        title={t("tiling.menu_hint")}
        aria-label={t("tiling.menu")}
        aria-haspopup="dialog"
        aria-expanded={open}
        data-testid="layout-menu-button"
        onClick={() => setOpen((value) => !value)}
        className={clsx(
          "inline-flex h-8 shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-md px-2 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          open || tree ? "text-foreground" : "text-muted-foreground",
          "hover:bg-secondary hover:text-foreground",
        )}
      >
        <LayoutDashboard aria-hidden className="h-4 w-4 shrink-0" />
        <span>{t("tiling.menu")}</span>
        {tree && <span className="rounded bg-secondary px-1 text-[10px] tabular-nums">{tileCount}</span>}
      </button>
      {open && (
        <div
          role="dialog"
          aria-label={t("tiling.menu")}
          data-testid="layout-menu"
          className="absolute left-0 top-9 z-[130] w-[320px] rounded-xl border border-border bg-popover p-3 shadow-xl"
        >
          <p className="mb-2 text-meta font-medium text-foreground-strong">{t("tiling.arrange")}</p>
          <div className="grid grid-cols-4 gap-2">
            {thumbs.map(({ preset, cells }) => (
              <button
                key={preset.id}
                type="button"
                title={t(`tiling.preset_${preset.id.replace(/-/g, "_")}`)}
                aria-label={t(`tiling.preset_${preset.id.replace(/-/g, "_")}`)}
                aria-pressed={current === preset.id}
                data-testid={`layout-preset-${preset.id}`}
                onClick={() => {
                  applyPreset(preset.id);
                  setPicking(null);
                  // A single section needs no further choice; a layout stays
                  // open so the user picks what goes where right away.
                  if (preset.slots === 1) setOpen(false);
                }}
                className={clsx(
                  "relative h-12 rounded-md border p-1 transition-colors",
                  current === preset.id ? "border-primary bg-primary/10" : "border-border hover:bg-secondary",
                )}
              >
                <span className="relative block h-full w-full">
                  {cells.map(({ leaf, rect }) => (
                    <span
                      key={leaf.id}
                      className={clsx(
                        "absolute rounded-[3px]",
                        current === preset.id ? "bg-primary/70" : "bg-muted-foreground/45",
                      )}
                      style={{
                        left: `calc(${rect.x * 100}% + 1px)`,
                        top: `calc(${rect.y * 100}% + 1px)`,
                        width: `calc(${rect.w * 100}% - 2px)`,
                        height: `calc(${rect.h * 100}% - 2px)`,
                      }}
                    />
                  ))}
                </span>
              </button>
            ))}
          </div>
          {tree && (
            <div className="mt-3" data-testid="layout-slots">
              <p className="text-meta font-medium text-foreground-strong">{t("tiling.what_where")}</p>
              <p className="mb-2 text-[11px] leading-4 text-muted-foreground">{t("tiling.what_where_hint")}</p>
              <div className="relative">
                <div
                  className="relative w-full overflow-hidden rounded-lg border border-border bg-muted/40"
                  style={{ aspectRatio: String(Math.min(2.2, Math.max(1.2, stageAspect))) }}
                >
                  {cells.map(({ leaf, rect }) => {
                    const item = navItemFor(leaf.section);
                    const Icon = item?.icon;
                    const active = picking === leaf.id;
                    return (
                      <button
                        key={leaf.id}
                        type="button"
                        data-picker-anchor=""
                        data-testid="layout-slot"
                        title={t("tiling.change_section")}
                        onClick={() => setPicking((value) => (value === leaf.id ? null : leaf.id))}
                        className={clsx(
                          "absolute flex flex-col items-center justify-center gap-1 rounded-md border px-1 text-center transition-colors",
                          active
                            ? "border-primary bg-primary/15 text-foreground-strong"
                            : leaf.id === focusedId
                              ? "border-primary/50 bg-card text-foreground hover:bg-secondary"
                              : "border-border bg-card text-foreground hover:bg-secondary",
                        )}
                        style={{
                          left: `calc(${rect.x * 100}% + 3px)`,
                          top: `calc(${rect.y * 100}% + 3px)`,
                          width: `calc(${rect.w * 100}% - 6px)`,
                          height: `calc(${rect.h * 100}% - 6px)`,
                        }}
                      >
                        {Icon && <Icon aria-hidden className="h-4 w-4 shrink-0" />}
                        <span className="flex max-w-full items-center gap-0.5 text-[11px] font-medium leading-tight">
                          <span className="truncate">{item ? resolveNavLabel(t, item) : leaf.section}</span>
                          <ChevronDown aria-hidden className="h-3 w-3 shrink-0 opacity-70" />
                        </span>
                      </button>
                    );
                  })}
                </div>
                {picking && cells.some(({ leaf }) => leaf.id === picking) && (
                  <SectionPicker
                    className="absolute left-1/2 top-full mt-1 -translate-x-1/2"
                    section={cells.find(({ leaf }) => leaf.id === picking)!.leaf.section}
                    shownOwners={shownOwners}
                    onClose={closePicker}
                    onPick={(next) => {
                      useTilingStore.getState().setTileSection(picking, next);
                      setPicking(null);
                    }}
                  />
                )}
              </div>
            </div>
          )}
          <p className="mt-2 text-[11px] leading-4 text-muted-foreground">{t("tiling.shift_click_hint")}</p>

          <div className="my-3 h-px bg-border" />
          <p className="mb-2 text-meta font-medium text-foreground-strong">{t("tiling.background")}</p>
          <div className="flex flex-col gap-1">
            <button
              type="button"
              data-testid="wallpaper-desktop"
              className={clsx(
                "flex h-8 items-center gap-2 rounded-md px-2 text-left text-meta transition-colors hover:bg-secondary",
                source !== "custom" ? "text-foreground-strong" : "text-foreground",
              )}
              onClick={async () => {
                if (source === "custom") toast(await useWallpaperStore.getState().reset(), "tiling.background_reset", "tiling.background_failed");
              }}
            >
              <Monitor aria-hidden className="h-4 w-4 shrink-0" />
              <span className="min-w-0 flex-1">{t("tiling.background_desktop")}</span>
              {source !== "custom" && <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-primary" />}
            </button>
            <button
              type="button"
              data-testid="wallpaper-custom"
              className={clsx(
                "flex h-8 items-center gap-2 rounded-md px-2 text-left text-meta transition-colors hover:bg-secondary",
                source === "custom" ? "text-foreground-strong" : "text-foreground",
              )}
              onClick={() => file.current?.click()}
            >
              <ImageUp aria-hidden className="h-4 w-4 shrink-0" />
              <span className="min-w-0 flex-1">
                {t(source === "custom" ? "tiling.background_change" : "tiling.background_custom")}
              </span>
              {source === "custom" && <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-primary" />}
            </button>
            {source === "custom" && (
              <button
                type="button"
                className="flex h-8 items-center gap-2 rounded-md px-2 text-left text-meta text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
                onClick={async () => toast(await useWallpaperStore.getState().reset(), "tiling.background_reset", "tiling.background_failed")}
              >
                <RotateCcw aria-hidden className="h-4 w-4 shrink-0" />
                <span>{t("tiling.background_use_desktop")}</span>
              </button>
            )}
            {source === "none" && (
              <p className="px-2 text-[11px] leading-4 text-muted-foreground">{t("tiling.background_none")}</p>
            )}
          </div>
          <input
            ref={file}
            type="file"
            accept="image/png,image/jpeg,image/webp,image/gif,image/bmp"
            className="hidden"
            onChange={async (event) => {
              const picked = event.target.files?.[0];
              event.target.value = "";
              if (!picked) return;
              toast(await useWallpaperStore.getState().upload(picked), "tiling.background_saved", "tiling.background_failed");
            }}
          />
        </div>
      )}
    </div>
  );
}
