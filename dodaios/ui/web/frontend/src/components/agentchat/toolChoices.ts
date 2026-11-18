import { translate } from "@/i18n";
import { isPluginOwnedSkill } from "@/lib/pluginFamilies";

/** Mirrors the composer catalog's Pydantic model; selections send IDs only. */
export type ToolCategory =
  "plugins" | "skills" | "mcp" | "memory" | "web" | "files" | "automation" | "system" | "cli";
export const TOOL_CATEGORIES: ToolCategory[] = [
  "plugins",
  "skills",
  "mcp",
  "memory",
  "web",
  "files",
  "automation",
  "system",
  "cli",
];

export interface ToolChoice {
  id: string;
  label: string;
  description: string;
  category: ToolCategory;
  group: string;
  brand: string;
  available: boolean;
  tool_names: string[];
  skill: string;
  /** A plugin the owner added (custom connector or upload). */
  user_added?: boolean;
}

/** The row a plugin's or CLI's logo is drawn from when only its id is known. */
export function serviceIconRow(kind: "plugin" | "cli", id: string, label: string): ToolChoice {
  return {
    id: `${kind}:${id}`,
    label,
    description: "",
    category: kind === "plugin" ? "plugins" : "cli",
    group: "",
    brand: id,
    available: false,
    tool_names: [],
    skill: "",
  };
}

export interface ToolSearchResult {
  items: ToolChoice[];
  mode: "browse" | "semantic" | "text";
  total: number;
}

export async function searchTools(
  params: Record<string, string>,
  signal: AbortSignal,
): Promise<ToolSearchResult> {
  const res = await fetch(`/api/agent-chat/tools?${new URLSearchParams(params)}`, { signal });
  if (!res.ok) throw new Error(`tool-search:${res.status}`);
  return res.json();
}

/**
 * The assistant's own tools a person may name on purpose, with the words they
 * read in the list (`chat_tools.curated.<key>`). Every other `tool:` row is
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
  if (isPluginOwnedSkill(row.skill || row.label || row.id)) return false;
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
  const out: ToolChoice[] = [];
  for (const row of items) {
    if (row.id.startsWith("tool:")) {
      const key = CURATED_TOOLS[row.id];
      if (!key) continue;
      out.push({
        ...row,
        label: translate(`chat_tools.curated.${key}.label`),
        description: translate(`chat_tools.curated.${key}.hint`),
      });
      continue;
    }
    if (row.category === "plugins" && !row.available && !searching && !row.user_added) continue;
    if (row.category === "skills" && !personSkill(row)) continue;
    out.push(row);
  }
  return out;
}

/** Old events have no selections. Discard malformed receipts. */
export function readToolChoices(value: unknown): ToolChoice[] {
  if (!Array.isArray(value)) return [];
  return value.filter((row): row is ToolChoice =>
    Boolean(
      row &&
      typeof row.id === "string" &&
      typeof row.label === "string" &&
      TOOL_CATEGORIES.includes(row.category) &&
      typeof row.brand === "string",
    ),
  );
}
