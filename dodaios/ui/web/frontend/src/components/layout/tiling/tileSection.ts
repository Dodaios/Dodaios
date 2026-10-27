import { createContext, useContext } from "react";

import { NAV_FOOTER_ITEMS, NAV_GROUPS, type NavItem } from "@/components/layout/navGroups";
import { isTileable } from "@/lib/tilingLayout";
import { sectionWindow } from "@/lib/sectionWindows";
import { useEventStore, type SectionId } from "@/store/events";

/**
 * The section a tile shows. A view that keeps its tab in the section id (the
 * CLIs and Voice hubs) reads its own tile's section here instead of the
 * active one, which belongs to whichever tile has focus.
 */
export const TileSectionContext = createContext<SectionId | null>(null);

export function useStageSection(): SectionId {
  const own = useContext(TileSectionContext);
  const active = useEventStore((s) => s.activeSection);
  return own ?? active;
}

/** Every sidebar row whose section can sit in a tile, in sidebar order. */
export const TILEABLE_NAV_ITEMS: readonly NavItem[] = [...NAV_GROUPS.flat(), ...NAV_FOOTER_ITEMS]
  .filter((item) => isTileable(item.id));

/** The sidebar row that fronts `section` (a hub's tabs share their hub's row). */
export function navItemFor(section: SectionId): NavItem | undefined {
  const owner = sectionWindow(section);
  return TILEABLE_NAV_ITEMS.find(
    (item) => item.id === section || item.matchIds?.includes(section) || sectionWindow(item.id) === owner,
  );
}

/** The tileable rows grouped the way the sidebar groups them. */
export const TILEABLE_NAV_GROUPS: readonly (readonly NavItem[])[] = [...NAV_GROUPS, NAV_FOOTER_ITEMS]
  .map((group) => group.filter((item) => isTileable(item.id)))
  .filter((group) => group.length > 0);
