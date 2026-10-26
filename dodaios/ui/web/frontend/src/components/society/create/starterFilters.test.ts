import { describe, expect, test } from "vitest";
import { areaCounts, defaultTools, filterStarters, starterCopy, translated } from "./starterFilters";
import type { Starter } from "./startersApi";

function starter(over: Partial<Starter>): Starter {
  return {
    id: "researcher", area: "research", icon: "search", name: "Researcher", title: "Researches with sources",
    outcome: "Answers a question with sources.", instructions: "You answer.\n\n- one\n- two", first_message: "Research this: ",
    tools: [], routine: null,
    summary: { instructions_words: 5, instructions_rules: 2, skills: null, routines: 0, tools: 0, asks_before: 0, limited_tools: false },
    ...over,
  };
}

const STARTERS: Starter[] = [
  starter({}),
  starter({ id: "code-reviewer", area: "coding", name: "Code Reviewer", outcome: "Reads a branch before you merge.",
    tools: [{ id: "cli:gh", label: "GitHub CLI", available: true, connected: true }] }),
  starter({ id: "inbox-sorter", area: "inbox", name: "Inbox Sorter", outcome: "Sorts new mail.",
    tools: [
      { id: "plugin:gmail", label: "Gmail", available: true, connected: false },
      { id: "core:search-web", label: "Search", available: true, connected: true },
      { id: "plugin:missing", label: "Missing", available: false, connected: false },
    ] }),
];

const identity = (key: string) => key;
const german: Record<string, string> = {
  "agent_create.starter.code_reviewer.name": "Code-Prüfer", // i18n-allow: translated fixture
  "agent_create.starter.code_reviewer.outcome": "Liest einen Branch vor dem Merge.", // i18n-allow: translated fixture
};
const de = (key: string) => german[key] ?? key;

describe("starter copy", () => {
  test("a missing translation falls back to the catalogue's English", () => {
    expect(translated(identity, "agent_create.nope", "Fallback")).toBe("Fallback");
    expect(starterCopy(identity, STARTERS[1]).name).toBe("Code Reviewer");
    expect(starterCopy(de, STARTERS[1])).toMatchObject({ name: "Code-Prüfer", outcome: "Liest einen Branch vor dem Merge." }); // i18n-allow: translated fixture
  });

  test("the routine title is empty without a routine", () => {
    expect(starterCopy(identity, STARTERS[0]).routineTitle).toBe("");
    const withRoutine = starter({ routine: { title: "Morning", when: "weekday_morning", cron: "0 8 * * 1-5" } });
    expect(starterCopy(identity, withRoutine).routineTitle).toBe("Morning");
  });
});

describe("gallery filtering", () => {
  const copyOf = (s: Starter) => starterCopy(de, s);

  test("by area", () => {
    expect(filterStarters(STARTERS, "all", "", copyOf)).toHaveLength(3);
    expect(filterStarters(STARTERS, "coding", "", copyOf).map((s) => s.id)).toEqual(["code-reviewer"]);
    expect(filterStarters(STARTERS, "writing", "", copyOf)).toEqual([]);
  });

  test("search matches translated and English copy, accents folded, every word", () => {
    expect(filterStarters(STARTERS, "all", "prufer", copyOf).map((s) => s.id)).toEqual(["code-reviewer"]);
    expect(filterStarters(STARTERS, "all", "reviewer", copyOf).map((s) => s.id)).toEqual(["code-reviewer"]);
    expect(filterStarters(STARTERS, "all", "gmail", copyOf).map((s) => s.id)).toEqual(["inbox-sorter"]);
    expect(filterStarters(STARTERS, "all", "mail sorts", copyOf).map((s) => s.id)).toEqual(["inbox-sorter"]);
    expect(filterStarters(STARTERS, "all", "mail zebra", copyOf)).toEqual([]);
    expect(filterStarters(STARTERS, "research", "branch", copyOf)).toEqual([]);
  });

  test("area chips count what the current search would show", () => {
    const counts = areaCounts(STARTERS, ["coding", "research", "inbox", "writing"], "", copyOf);
    expect(counts).toEqual({ all: 3, coding: 1, research: 1, inbox: 1, writing: 0 });
    const searched = areaCounts(STARTERS, ["coding", "research", "inbox"], "question", copyOf);
    expect(searched).toEqual({ all: 1, coding: 0, research: 1, inbox: 0 });
  });
});

describe("tools", () => {
  test("only connected tools start ticked", () => {
    expect(defaultTools(STARTERS[2].tools)).toEqual(["core:search-web"]);
    expect(defaultTools([])).toEqual([]);
  });
});
