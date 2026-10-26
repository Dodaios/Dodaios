import type { SectionId } from "@/store/events";
import { SETTINGS_HUB_IDS } from "@/components/layout/navGroups";

/**
 * The family a section belongs to: tabs of one hub (Settings, Plugins, the
 * coding workspace, CLIs) share one identity — one tile in the tiling layout,
 * one native window for the editor tool windows.
 */
export function sectionWindow(section: SectionId): SectionId {
  if (SETTINGS_HUB_IDS.includes(section)) return "settings";
  if (["agentic-ide", "agentic-ide-classic", "chat-workspace"].includes(section)) return "agentic-ide";
  if (["plugins", "mcps", "skills"].includes(section)) return "plugins";
  if (section === "cli-test-hub") return "clis";
  return section;
}

/** The URL keeps this identity when a tool window reloads. */
export function windowIdentity(search: string, fallback: SectionId): string {
  const params = new URLSearchParams(search);
  return params.get("window") || params.get("view") || sectionWindow(fallback);
}
