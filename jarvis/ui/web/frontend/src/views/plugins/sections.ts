/**
 * How the plugin directory is cut into sections.
 *
 * The home page never lists the whole catalog: it shows a handful of sections,
 * each capped at `SECTION_LIMIT` rows and none repeating a plugin, and a
 * section's heading opens its full list. Kept free of React so the grouping rules can be tested on their own.
 */
import type { Plugin } from "@/views/PluginsView";

/** Rows a home section shows before its heading leads to the full list. */
export const SECTION_LIMIT = 6;

export const POPULAR_SECTION = "popular";
export const UPLOADED_SECTION = "uploaded";
export const COMMUNITY_SECTION = "community";
const CATEGORY_PREFIX = "category:";

/** "catalog" is what the app ships with; "yours" is everything the owner added. */
export type PluginScope = "catalog" | "yours";

export interface BrowseSection {
  id: string;
  plugins: Plugin[];
}

/** A plugin the owner brought in: by URL, as a folder, or from the community. */
export const isOwnerAdded = (plugin: Plugin): boolean =>
  plugin.fromMarketplace || plugin.selfUploaded;

/** A plugin that belongs in the "Installed" list: connected once, or added by
 *  the owner. A revoked or errored one stays listed so it can be reconnected. */
export const isInstalled = (plugin: Plugin): boolean =>
  plugin.status === "connected" ||
  plugin.status === "needs_reauth" ||
  plugin.status === "error" ||
  isOwnerAdded(plugin);

export const categorySectionId = (category: string): string => `${CATEGORY_PREFIX}${category}`;

/** The catalog category behind a section id, or null for a curated section. */
export const sectionCategory = (sectionId: string): string | null =>
  sectionId.startsWith(CATEGORY_PREFIX) ? sectionId.slice(CATEGORY_PREFIX.length) : null;

/** The section a plugin is listed under, whatever page it was opened from. */
export function homeSectionId(plugin: Plugin): string {
  if (plugin.selfUploaded) return UPLOADED_SECTION;
  if (plugin.fromMarketplace) return COMMUNITY_SECTION;
  return categorySectionId(plugin.category);
}

const byName = (a: Plugin, b: Plugin): number =>
  a.name.localeCompare(b.name, undefined, { sensitivity: "base" });

/** Sections of the shipped catalog: the featured picks first, then one section
 *  per category in `categoryOrder`. Empty sections are dropped. */
export function catalogSections(plugins: Plugin[], categoryOrder: string[]): BrowseSection[] {
  const shipped = plugins.filter((plugin) => !isOwnerAdded(plugin));
  const sections: BrowseSection[] = [];
  const popular = shipped.filter((plugin) => plugin.featured);
  if (popular.length > 0) sections.push({ id: POPULAR_SECTION, plugins: popular });
  for (const category of categoryOrder) {
    const members = shipped.filter((plugin) => plugin.category === category).sort(byName);
    if (members.length > 0) sections.push({ id: categorySectionId(category), plugins: members });
  }
  return sections;
}

/** Sections of what the owner added: own connectors and folders, then
 *  community installs. */
export function ownSections(plugins: Plugin[]): BrowseSection[] {
  const sections: BrowseSection[] = [];
  const uploaded = plugins.filter((plugin) => plugin.selfUploaded).sort(byName);
  if (uploaded.length > 0) sections.push({ id: UPLOADED_SECTION, plugins: uploaded });
  const community = plugins
    .filter((plugin) => plugin.fromMarketplace && !plugin.selfUploaded)
    .sort(byName);
  if (community.length > 0) sections.push({ id: COMMUNITY_SECTION, plugins: community });
  return sections;
}

/** What each section shows on the home page: at most `SECTION_LIMIT` rows, and
 *  a plugin a section above already shows is not repeated below — every plugin
 *  is on the page once. A section left with nothing to show is dropped; its
 *  own page still lists all of it. */
export function homeRows(sections: BrowseSection[]): BrowseSection[] {
  const shown = new Set<string>();
  const rows: BrowseSection[] = [];
  for (const section of sections) {
    const plugins = section.plugins
      .filter((plugin) => !shown.has(plugin.id))
      .slice(0, SECTION_LIMIT);
    for (const plugin of plugins) shown.add(plugin.id);
    if (plugins.length > 0) rows.push({ id: section.id, plugins });
  }
  return rows;
}

/** Every section of both scopes, for resolving an open section by its id. */
export function allSections(plugins: Plugin[], categoryOrder: string[]): BrowseSection[] {
  return [...catalogSections(plugins, categoryOrder), ...ownSections(plugins)];
}
