import { describe, expect, it } from "vitest";

import { browseToolRows, type ToolChoice } from "./toolChoices";

/**
 * What the Add menu and the chat's `@` list show. The catalog also holds the
 * assistant's plumbing (IDE terminals, jobs, settings, file tools) and the
 * app's own agent skills; a person never tags those, so they stay out.
 */

function row(id: string, category: ToolChoice["category"], extra: Partial<ToolChoice> = {}): ToolChoice {
  return {
    id,
    label: id.replace(/^\w+:/, ""),
    description: "",
    category,
    group: category,
    brand: "",
    available: true,
    tool_names: [],
    skill: category === "skills" ? id.replace(/^skill:/, "") : "",
    ...extra,
  };
}

const CATALOG: ToolChoice[] = [
  row("plugin:gmail", "plugins", { brand: "gmail", label: "Gmail" }),
  row("plugin:notion", "plugins", { brand: "notion", label: "Notion", available: false }),
  row("skill:humanizer", "skills"),
  row("skill:memory-save", "skills", { description: "DEPRECATED since B5 and disabled." }),
  row("skill:plugin-shopify", "skills"),
  row("skill:cli-gcloud", "skills"),
  row("skill:agent-brief", "skills"),
  row("skill:control-api", "skills"),
  row("tool:society_browser", "web", { label: "Chrome / Browser", description: "Use YOUR browser to …" }),
  row("tool:search_web", "web", { label: "search_web" }),
  row("tool:memory-search", "memory"),
  row("tool:agentic-ide-fanout", "system"),
  row("tool:await_jobs", "system"),
  row("tool:handback_event", "system"),
  row("tool:Read", "files"),
  row("tool:node", "system"),
  row("cli:gh", "cli", { label: "GitHub CLI" }),
];

describe("browseToolRows", () => {
  it("keeps connectors, the person's skills and the tools worth naming, in plain words", () => {
    const shown = browseToolRows(CATALOG);
    expect(shown.map((r) => r.id)).toEqual([
      "plugin:gmail",
      "skill:humanizer",
      "tool:society_browser",
      "tool:search_web",
      "tool:memory-search",
      "cli:gh",
    ]);
    const byId = Object.fromEntries(shown.map((r) => [r.id, r]));
    expect(byId["tool:search_web"].label).toBe("Web search");
    expect(byId["tool:memory-search"].label).toBe("Memory");
    expect(byId["tool:society_browser"].label).toBe("Browser");
    expect(byId["tool:society_browser"].description).toBe("Do something on the web in your own browser");
  });

  it("never lists the plumbing, not even for a search", () => {
    const found = browseToolRows(CATALOG, "agentic").map((r) => r.id);
    expect(found).not.toContain("tool:agentic-ide-fanout");
    expect(browseToolRows(CATALOG, "await").map((r) => r.id)).not.toContain("tool:await_jobs");
  });

  it("shows a disconnected plugin once someone searches for it", () => {
    expect(browseToolRows(CATALOG, "notion").map((r) => r.id)).toContain("plugin:notion");
  });
});
