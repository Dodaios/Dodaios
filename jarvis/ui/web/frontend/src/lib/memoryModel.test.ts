import { describe, expect, it } from "vitest";

import type { MemoryAgent, OutgoingRef } from "@/lib/memoryApi";
import {
  LINK_SCHEME,
  MISSING_SCHEME,
  plainText,
  prepareBody,
  pruneEmptySections,
  relativeAge,
  stripComments,
  stripLeadingTitle,
  visibleAgents,
} from "@/lib/memoryModel";

const OUT: OutgoingRef[] = [
  { path: "projects/magenta-ide.md", title: "Magenta IDE", kind: "project", broken: false, raw: "projects/magenta-ide" },
  { path: null, title: "Nowhere", kind: null, broken: true, raw: "Nowhere" },
];

describe("memoryModel", () => {
  it("routes resolved links to their path and missing ones to the create offer", () => {
    const body = prepareBody("Works on [[projects/magenta-ide|the IDE]] and [[Nowhere]].", "Ruben", OUT);
    expect(body).toBe(
      `Works on [the IDE](${LINK_SCHEME}${encodeURIComponent("projects/magenta-ide.md")}) and ` +
        `[Nowhere](${MISSING_SCHEME}Nowhere).`,
    );
  });

  it("drops entry bookkeeping and a leading title that repeats the page title", () => {
    const body = prepareBody('\n# Ruben\n<!-- memory-entry: {"id": "x"} -->\nPrefers short answers.\n', "Ruben", []);
    expect(body).toBe("Prefers short answers.");
    expect(stripLeadingTitle("# Other\nbody", "Ruben")).toBe("# Other\nbody");
  });

  it("removes headings with nothing under them, parents included", () => {
    const skeleton = "## Summary\nThe owner.\n\n## Preferences\n\n### Food\n- \n\n## Facts\n";
    expect(pruneEmptySections(skeleton).trim()).toBe("## Summary\nThe owner.");
  });

  it("keeps a heading whose only content sits in a sub-section", () => {
    const body = "## Work\n### Projects\n- Magenta\n";
    expect(pruneEmptySections(body)).toBe(body);
  });

  it("removes nested and unclosed comment openers completely", () => {
    expect(stripComments("a <!<!-- x -->-- y --> b")).toBe("a  b");
    expect(stripComments("text <!-- never closed")).toBe("text  never closed");
  });

  it("flattens Markdown for a one-line preview", () => {
    expect(plainText("**Bold** [[entities/ruben|Ruben]] and [a link](https://x.y)")).toBe("Bold Ruben and a link");
  });

  it("lists live agents and those with notes, hides empty leftovers", () => {
    const agents: MemoryAgent[] = [
      { agent_id: "a", name: "Ada", state: "orphan", empty: true, updated: 0, pages: [] },
      { agent_id: "b", name: "Bea", state: "archived", empty: false, updated: 0, pages: [] },
      { agent_id: "c", name: "Cal", state: "active", empty: true, updated: 0, pages: [] },
    ];
    expect(visibleAgents(agents, false).map((agent) => agent.name)).toEqual(["Cal", "Bea"]);
    expect(visibleAgents(agents, true)).toHaveLength(3);
  });

  it("formats a relative age", () => {
    const now = 1_000_000 * 1000;
    expect(relativeAge(1_000_000 - 2 * 86400, "en", now)).toBe("2 days ago");
    expect(relativeAge(0, "en", now)).toBe("");
  });
});
