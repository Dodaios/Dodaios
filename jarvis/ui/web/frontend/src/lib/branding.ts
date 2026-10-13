/** Product display name and public links shared by frontend surfaces. */

export const PRODUCT_NAME = "Dodaios";
export const OFFICIAL_REPO_SLUG = "Dodaios/Dodaios";
export const OFFICIAL_REPO_URL = `https://github.com/${OFFICIAL_REPO_SLUG}`;
export const OFFICIAL_REPO_LABEL = `github.com/${OFFICIAL_REPO_SLUG}`;

/**
 * Every name the app's own MCP tools server has been registered under, the
 * current one first (jarvis/core/branding.py). A coding CLI names a tool after
 * its server ("mcp__dodaios__gmail"), and transcripts written under the
 * earlier name are still on disk, so a reader accepts all of them.
 */
export const MCP_TOOLS_SERVER_NAMES: readonly string[] = ["dodaios", "jarvis"];
