/**
 * The store's rules, without a DOM: what a search finds and in which order,
 * what each filter counts, and how an entry without artwork gets its mark.
 */
import { describe, expect, it } from "vitest";

import { splitFrontmatter } from "@/components/extensions/FileCard";
import type { CommunityResponse } from "@/views/PluginsCommunity";
import {
  entriesOf,
  filterCounts,
  monogram,
  nameHue,
  readableText,
  searchEntries,
  type Entry,
} from "./model";

function entry(over: Partial<Entry>): Entry {
  return {
    kind: "skill",
    name: "x",
    title: "X",
    description: null,
    categories: [],
    installed: false,
    ...over,
  };
}

const INDEX: CommunityResponse = {
  status: "fresh",
  plugins: [
    {
      name: "sentry",
      valid: true,
      id: "sentry",
      display_name: "Sentry",
      description: "Errors from your projects",
      publisher: "octocat",
      publisher_id: 583231,
      published_at: "2026-08-12T15:01:23Z",
      installed: true,
      installed_version: "0.9.0",
      version: "1.0.0",
    },
  ],
  skills: [
    {
      name: "humanizer",
      title: "Humanizer",
      description: "|",
      publisher: "octocat",
      categories: [],
      published_at: "2026-08-23T07:16:10Z",
      installed: false,
      featured: true,
    },
    {
      name: "brief",
      title: "Brief",
      description: "Three bullets about any topic",
      publisher: "stranger",
      categories: ["writing"],
      published_at: "2026-09-01T00:00:00Z",
      installed: true,
    },
  ],
};

describe("entriesOf", () => {
  it("puts the registry's pick first, then the newest", () => {
    expect(entriesOf(INDEX).map((e) => e.name)).toEqual(["humanizer", "brief", "sentry"]);
  });

  it("treats a leaked YAML marker as no description", () => {
    expect(entriesOf(INDEX).find((e) => e.name === "humanizer")?.description).toBeNull();
    expect(readableText(" > ")).toBeNull();
    expect(readableText(" ok ")).toBe("ok");
  });

  it("knows an update from an install, and keeps the publisher's account id", () => {
    const sentry = entriesOf(INDEX).find((e) => e.name === "sentry");
    expect(sentry?.updateAvailable).toBe(true);
    expect(sentry?.publisherId).toBe(583231);
  });

  it("is empty before the index arrived", () => {
    expect(entriesOf(undefined)).toEqual([]);
  });
});

describe("searchEntries", () => {
  const entries = [
    entry({ name: "notes", title: "Meeting Notes", description: "Linear issues from a transcript" }),
    entry({ name: "linear-sync", title: "Linear", description: "Create and triage issues" }),
    entry({ name: "brief", title: "Brief", description: "Three bullets", publisher: "linus" }),
  ];

  it("ranks a title that starts with the query above a mention", () => {
    expect(searchEntries(entries, "lin").map((e) => e.name)).toEqual(["linear-sync", "notes", "brief"]);
  });

  it("needs every word to appear somewhere", () => {
    expect(searchEntries(entries, "linear transcript").map((e) => e.name)).toEqual(["notes"]);
    expect(searchEntries(entries, "linear nothing")).toEqual([]);
  });

  it("returns the list untouched for a blank query", () => {
    expect(searchEntries(entries, "   ")).toBe(entries);
  });
});

describe("filterCounts", () => {
  it("counts each filter, and Mine only for a signed-in account", () => {
    const entries = entriesOf(INDEX);
    expect(filterCounts(entries, "octocat")).toEqual({
      all: 3,
      plugin: 1,
      skill: 2,
      agent: 0,
      installed: 2,
      mine: 2,
    });
    expect(filterCounts(entries, null).mine).toBe(0);
  });
});

describe("marks", () => {
  it("draws two letters from a title", () => {
    expect(monogram("Three Bullet Brief")).toBe("TB");
    expect(monogram("humanizer")).toBe("H");
    expect(monogram("sql-reviewer")).toBe("SR");
    expect(monogram("  ")).toBe("?");
  });

  it("gives a name the same hue every time, from a small palette", () => {
    expect(nameHue("humanizer")).toBe(nameHue("humanizer"));
    expect(nameHue("humanizer") % 30).toBe(0);
    expect(nameHue("humanizer")).toBeLessThanOrEqual(360);
  });
});

describe("splitFrontmatter", () => {
  it("takes the YAML block off the top of a SKILL.md", () => {
    const { frontmatter, body } = splitFrontmatter("---\nname: brief\n---\n\n# Brief\n");
    expect(frontmatter).toBe("name: brief");
    expect(body).toBe("\n# Brief\n");
  });

  it("leaves a document without frontmatter alone", () => {
    const text = "# Title\n\n---\n\nA rule is not frontmatter.";
    expect(splitFrontmatter(text)).toEqual({ frontmatter: null, body: text });
  });

  it("reads Windows line endings", () => {
    expect(splitFrontmatter("---\r\nname: a\r\n---\r\nBody").frontmatter).toBe("name: a");
  });
});
