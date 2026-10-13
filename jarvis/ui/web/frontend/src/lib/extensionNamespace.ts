/**
 * The namespace a plugin package keeps this app's own data under: the key of
 * its block in plugin.json ("extensions") and the directory of its extension
 * files ("<namespace>/usage-card.md").
 *
 * One namespace is written, every namespace is read. Packages published
 * before the rename carry the earlier one, and those packages never change.
 * The names restate jarvis/core/branding.py; a Python test pins them to it.
 */

/** What a new manifest is written with. */
export const EXTENSION_NAMESPACE = "io.github.dodaios";

/** Earlier names of the namespace, read forever. */
export const LEGACY_EXTENSION_NAMESPACES: readonly string[] = ["io.github.personaljarvis"];

/** Every namespace a package may use, the current one first. */
export const EXTENSION_NAMESPACES: readonly string[] = [EXTENSION_NAMESPACE, ...LEGACY_EXTENSION_NAMESPACES];

const USAGE_CARD_FILE = "usage-card.md";

/** The plugin's own block, under whichever namespace its manifest uses. */
export function extensionOf<T>(manifest: { extensions?: Record<string, T> | null } | null | undefined): T | undefined {
  const extensions = manifest?.extensions;
  if (!extensions || typeof extensions !== "object") return undefined;
  for (const namespace of EXTENSION_NAMESPACES) {
    const block = extensions[namespace];
    if (block && typeof block === "object") return block;
  }
  return undefined;
}

/** Where a package may keep its usage card, the current location first. */
export function usageCardPaths(prefix = ""): string[] {
  return EXTENSION_NAMESPACES.map((namespace) => `${prefix}${namespace}/${USAGE_CARD_FILE}`);
}
