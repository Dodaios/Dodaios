import { describe, expect, it } from "vitest";

import { NAV_GROUPS, SETTINGS_HUB_IDS } from "@/components/layout/navGroups";
import { HUB_GROUPS, HUB_PAGES, PAGE_ENTRIES, entryKey, resolveHubTab } from "@/views/settings/hubNav";

/** Every tab the hub showed before the regrouping (2026-11-10). */
const FORMER_TABS = [
  "settings", "shortcuts", "appshots", "pets", "games", "profile",
  "agent-instructions", "socials", "computers", "apikeys", "costs", "feedback",
];

/** The General page's groups (SettingsView SECTIONS). */
const GENERAL_SECTIONS = [
  "languages", "app", "voice", "wake-word", "system-prompt", "approvals",
  "self-build", "music", "overlay-taskbar", "verse",
];

const entries = HUB_GROUPS.flatMap((group) => group.entries);

describe("the Settings hub's five groups", () => {
  it("are You, Voice, Connections, Agents, Advanced — in that order", () => {
    expect(HUB_GROUPS.map((group) => group.id)).toEqual(["you", "voice", "connections", "agents", "advanced"]);
  });

  it("drop no tab: every former entry is still listed, exactly once", () => {
    const tabs = entries.flatMap((entry) => (entry.kind === "tab" ? [entry.id] : []));
    expect([...tabs].sort()).toEqual([...FORMER_TABS].sort());
  });

  it("give every entry a unique key", () => {
    const keys = entries.map(entryKey);
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("only name General groups that exist, each in one page at most", () => {
    const named = Object.values(HUB_PAGES).flat();
    for (const id of named) expect(GENERAL_SECTIONS).toContain(id);
    expect(new Set(named).size).toBe(named.length);
    expect(Object.keys(PAGE_ENTRIES).sort()).toEqual(Object.keys(HUB_PAGES).sort());
  });

  it("link only to sections outside the hub that the sidebar knows", () => {
    const sidebarIds = NAV_GROUPS.flat().flatMap((item) => [item.id, ...(item.matchIds ?? [])]);
    for (const entry of entries) {
      if (entry.kind !== "link") continue;
      expect(SETTINGS_HUB_IDS).not.toContain(entry.id);
      expect(sidebarIds).toContain(entry.id);
    }
  });
});

describe("resolveHubTab keeps every deep link working", () => {
  it.each(SETTINGS_HUB_IDS.map((id) => [id]))("%s resolves to a tab", (id) => {
    const { content, highlight } = resolveHubTab(id, null);
    expect(content).toBeTruthy();
    expect(entries.map(entryKey)).toContain(highlight);
  });

  it("lands the merged-in ids where their content lives", () => {
    expect(resolveHubTab("telephony", null)).toMatchObject({ content: "apikeys", highlight: "apikeys" });
    expect(resolveHubTab("telephony-setup", null)).toMatchObject({ content: "telephony-setup", highlight: "apikeys" });
    expect(resolveHubTab("taskbar", null)).toMatchObject({ content: "settings", highlight: "settings", page: null });
    expect(resolveHubTab("languages", null)).toMatchObject({ content: "settings", page: "language", highlight: "page:language" });
  });

  it("shows the whole General page for a bare settings link, a slice once picked", () => {
    expect(resolveHubTab("settings", null)).toMatchObject({ content: "settings", highlight: "settings", page: null });
    expect(resolveHubTab("settings", "voice")).toMatchObject({ content: "settings", highlight: "page:voice", page: "voice" });
  });

  it("ignores a picked slice once another tab is active", () => {
    expect(resolveHubTab("costs", "voice")).toMatchObject({ content: "costs", page: null });
  });

  it("falls back to the General page for an unknown id", () => {
    expect(resolveHubTab("chats", null)).toMatchObject({ content: "settings", highlight: "settings" });
  });
});
