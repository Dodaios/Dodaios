/**
 * What the Add menu and the Dodaios chat's `@` list show of the composer's
 * tool catalog. Its own module, apart from `toolChoices`: the rail's notices
 * import that one, so anything there loads with the first screen. Callers
 * load the `chat_tools` locale chunk first (`loadLocaleChunk`).
 */
import { isLocaleChunkLoaded, translate } from "@/i18n";
import { isPluginOwnedSkill } from "@/lib/pluginFamilies";
import type { ToolChoice } from "./toolChoices";

/**
 * The assistant's own tools a person may name on purpose, with the words they
 * read in the list (`chat_tools.curated.<key>`, the lazy `chat_tools` locale chunk: the
 * locale files of the first screen stay as small as they were). Every other `tool:` row is
 * plumbing the assistant reaches for by itself (the IDE's terminals, jobs,
 * settings, the file tools of a coding folder): listing those buried the few
 * things worth tagging under a hundred internal names (maintainer,
 * 2026-11-18: "so much junk"). Node tools are not here either: the menu's
 * own "Nodes" section tags a node type instead.
 */
const CURATED_TOOLS: Readonly<Record<string, string>> = {
  "tool:society_browser": "browser",
  "tool:search_web": "web_search",
  "tool:computer_use": "computer_use",
  "tool:memory-search": "memory",
  "tool:reminders": "reminders",
  "tool:create_artifact": "artifact",
  "tool:screenshot": "screenshot",
  "tool:call-contact": "phone_call",
  "tool:contact-lookup": "contacts",
};

/**
 * Skills the app ships for its own agents (how to brief a coding agent, how
 * to drive the Control API, how to write the repository's docs). They run
 * when the assistant needs them; a person never tags them.
 */
const AGENT_SKILLS: ReadonlySet<string> = new Set(["agent-brief", "control-api", "dodaios-doc-author"]);

function skillSlug(row: ToolChoice): string {
  return (row.skill || row.id.replace(/^skill:/, "") || row.label).trim().toLowerCase();
}

/** A skill row a person would tag: not a plugin's or CLI's companion, not retired, not the app's own. */
function personSkill(row: ToolChoice): boolean {
  const slug = skillSlug(row);
  // A plugin's companion skill is named after the plugin ("gmail",
  // "google-calendar"); a skill of the person's own that merely mentions one
  // ("t-gliche-github-triage") is theirs and stays.
  if (slug.split(/[-_]/).length <= 2 && isPluginOwnedSkill(row.skill || row.label || row.id)) return false;
  if (slug.startsWith("plugin-") || slug.startsWith("cli-")) return false;
  if (AGENT_SKILLS.has(slug)) return false;
  return !/^\s*deprecated\b/i.test(row.description);
}

/**
 * What the Add menu and the chat's `@` list show: connectors, the person's
 * own skills, connected CLIs and MCP servers, and the handful of the
 * assistant's tools worth naming (in plain words). Disconnected plugins stay
 * hidden until someone searches for them, except the ones the owner added,
 * which show with a Connect action.
 */
export function browseToolRows(items: ToolChoice[], query = ""): ToolChoice[] {
  const searching = Boolean(query.trim());
  // Until the chunk is in, a tool keeps the catalog's own name and line.
  const worded = isLocaleChunkLoaded("chat_tools");
  const out: ToolChoice[] = [];
  for (const row of items) {
    if (row.id.startsWith("tool:")) {
      const key = CURATED_TOOLS[row.id];
      if (!key) continue;
      out.push(
        worded
          ? {
              ...row,
              label: translate(`chat_tools.curated.${key}.label`),
              description: translate(`chat_tools.curated.${key}.hint`),
            }
          : row,
      );
      continue;
    }
    if (row.category === "plugins" && !row.available && !searching && !row.user_added) continue;
    if (row.category === "skills" && !personSkill(row)) continue;
    out.push(row);
  }
  return out;
}
