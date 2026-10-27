import { useEffect, useMemo, useRef, useState } from "react";
import { Check, Search } from "lucide-react";
import { clsx } from "clsx";

import { resolveNavLabel } from "@/components/layout/navGroups";
import { TILEABLE_NAV_GROUPS } from "@/components/layout/tiling/tileSection";
import { useT } from "@/i18n";
import { sectionWindow } from "@/lib/sectionWindows";
import type { SectionId } from "@/store/events";

/**
 * The list of sections one tile can show: searchable, grouped like the
 * sidebar. A section already shown in another tile is marked — picking it
 * swaps the two tiles instead of showing it twice. Its opener carries
 * `data-picker-anchor`, so a click on it toggles instead of reopening.
 */
export function SectionPicker({
  section,
  shownOwners,
  onPick,
  onClose,
  className,
}: {
  section: SectionId;
  shownOwners: readonly string[];
  onPick: (section: SectionId) => void;
  onClose: () => void;
  className?: string;
}) {
  const t = useT();
  const [query, setQuery] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    input.current?.focus();
    const onDown = (event: PointerEvent) => {
      const target = event.target as Element | null;
      // The button that opened the picker toggles it itself.
      if (box.current?.contains(target) || target?.closest?.("[data-picker-anchor]")) return;
      onClose();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("pointerdown", onDown, true);
    window.addEventListener("keydown", onKey, true);
    return () => {
      window.removeEventListener("pointerdown", onDown, true);
      window.removeEventListener("keydown", onKey, true);
    };
  }, [onClose]);

  const groups = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return TILEABLE_NAV_GROUPS.map((group) =>
      group
        .map((item) => ({ item, label: resolveNavLabel(t, item) }))
        .filter(({ label, item }) => !needle || label.toLowerCase().includes(needle) || item.id.includes(needle)),
    ).filter((group) => group.length > 0);
  }, [query, t]);
  const first = groups[0]?.[0]?.item;
  const ownOwner = sectionWindow(section);

  return (
    <div
      ref={box}
      role="menu"
      data-testid="section-picker"
      className={clsx(
        "z-[140] flex max-h-[min(60vh,440px)] w-60 flex-col overflow-hidden rounded-lg border border-border bg-popover shadow-xl",
        className,
      )}
    >
      <p className="px-3 pt-2.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        {t("tiling.pick_section")}
      </p>
      <label className="mx-2 mt-1.5 flex h-8 items-center gap-2 rounded-md border border-border bg-background px-2">
        <Search aria-hidden className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        <input
          ref={input}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && first) onPick(first.id);
          }}
          placeholder={t("tiling.search_section")}
          aria-label={t("tiling.search_section")}
          className="min-w-0 flex-1 bg-transparent text-meta text-foreground outline-none placeholder:text-muted-foreground"
        />
      </label>
      <div className="mt-1.5 min-h-0 flex-1 overflow-y-auto px-1 pb-1">
        {groups.length === 0 && (
          <p className="px-2 py-3 text-meta text-muted-foreground">{t("tiling.no_section_match")}</p>
        )}
        {groups.map((group, index) => (
          <div key={group[0].item.id} className={clsx(index > 0 && "mt-1 border-t border-border/60 pt-1")}>
            {group.map(({ item, label }) => {
              const Icon = item.icon;
              const owner = sectionWindow(item.id);
              const current = owner === ownOwner;
              const elsewhere = !current && shownOwners.includes(owner);
              return (
                <button
                  key={item.id}
                  type="button"
                  role="menuitem"
                  data-testid={`section-pick-${item.id}`}
                  className={clsx(
                    "flex h-8 w-full items-center gap-2 rounded-md px-2 text-left text-meta transition-colors hover:bg-secondary",
                    current ? "bg-secondary/60 text-foreground-strong" : "text-foreground",
                  )}
                  onClick={() => onPick(item.id)}
                >
                  <Icon aria-hidden className="h-4 w-4 shrink-0" />
                  <span className="min-w-0 flex-1 truncate">{label}</span>
                  {current && <Check aria-hidden className="h-3.5 w-3.5 shrink-0 text-primary" />}
                  {elsewhere && (
                    <span className="shrink-0 rounded bg-secondary px-1 text-[10px] text-muted-foreground">
                      {t("tiling.swap")}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
