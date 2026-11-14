import { describe, expect, it } from "vitest";

import { NAV_GROUPS, SETTINGS_HUB_IDS } from "@/components/layout/navGroups";
import { HUB_GROUPS, HUB_PAGES, PAGE_ENTRIES, entryKey, pageForTarget, resolveHubTab } from "@/views/settings/hubNav";

/**
 * The tabs the hub lists. Two former entries are gone on purpose
 * (2026-11-13): "settings" (the whole General page repeated the three slices
 * beside it) and "socials" (a list of links, not a setting).
 */
const LISTED_TABS = [
  "shortcuts", "appshots", "pets", "designs", "profile",
  "agent-instructions", "computers", "apikeys", "costs", "feedback",
  "notifications", "trust", "phone",
];

/** Hub ids that answer a deep link but have no entry of their own. */
const UNLISTED_IDS = ["socials"];

/** The General page's groups (SettingsView SECTIONS). */
const GENERAL_SECTIONS = [
  "languages", "app", "voice", "wake-word", "system-prompt", "approvals",
  "self-build", "music", "overlay-taskbar",
];

const entries = HUB_GROUPS.flatMap((group) => group.entries);

describe("the Settings hub's six groups", () => {
  it("are You, Voice, Connections, Assistant, Tools, Advanced — in that order", () => {
    expect(HUB_GROUPS.map((group) => group.id)).toEqual(["you", "voice", "connections", "agents", "tools", "advanced"]);
  });

  it("list every tab exactly once, and the whole General page not at all", () => {
    const tabs = entries.flatMap((entry) => (entry.kind === "tab" ? [entry.id] : []));
    expect([...tabs].sort()).toEqual([...LISTED_TABS].sort());
  });

  it("give every entry a unique key", () => {
    const keys = entries.map(entryKey);
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("put every General group in exactly one page, so no setting is listed twice", () => {
    const named = Object.values(HUB_PAGES).flat();
    expect([...named].sort()).toEqual([...GENERAL_SECTIONS].sort());
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
  it.each(SETTINGS_HUB_IDS.filter((id) => !UNLISTED_IDS.includes(id)).map((id) => [id]))("%s resolves to a tab", (id) => {
    const { content, highlight } = resolveHubTab(id, null);
    expect(content).toBeTruthy();
    expect(entries.map(entryKey)).toContain(highlight);
  });

  it("lands the merged-in ids where their content lives", () => {
    expect(resolveHubTab("telephony", null)).toMatchObject({ content: "apikeys", highlight: "apikeys" });
    expect(resolveHubTab("telephony-setup", null)).toMatchObject({ content: "telephony-setup", highlight: "apikeys" });
    expect(resolveHubTab("taskbar", null)).toMatchObject({ content: "settings", page: "language", highlight: "page:language" });
    expect(resolveHubTab("socials", null)).toMatchObject({ content: "socials", page: null });
    // The former Voice tab for the dictation keys.
    expect(resolveHubTab("voice-shortcuts", null)).toMatchObject({ content: "shortcuts", highlight: "shortcuts" });
    expect(resolveHubTab("languages", null)).toMatchObject({ content: "settings", page: "language", highlight: "page:language" });
  });

  it("shows the first slice for a bare settings link, the picked one after that", () => {
    expect(resolveHubTab("settings", null)).toMatchObject({ content: "settings", highlight: "page:language", page: "language" });
    expect(resolveHubTab("settings", "voice")).toMatchObject({ content: "settings", highlight: "page:voice", page: "voice" });
  });

  it("ignores a picked slice once another tab is active", () => {
    expect(resolveHubTab("costs", "voice")).toMatchObject({ content: "costs", page: null });
  });

  it("falls back to the first slice for an unknown id", () => {
    expect(resolveHubTab("chats", null)).toMatchObject({ content: "settings", highlight: "page:language" });
    expect(resolveHubTab("chats", "voice")).toMatchObject({ page: "language" });
  });
});

describe("pageForTarget finds the slice that shows a search hit", () => {
  it.each([
    ["languages", "language"],
    ["app", "language"],
    ["more", "language"],
    ["music", "language"],
    ["overlay-taskbar", "language"],
    ["voice", "voice"],
    ["volume", "voice"],
    ["audio-devices", "voice"],
    ["wake-word", "voice"],
    ["system-prompt", "behavior"],
    ["approvals", "behavior"],
    ["self-build", "behavior"],
  ])("%s is on the %s page", (target, page) => {
    expect(pageForTarget(target)).toBe(page);
  });

  it("opens the first slice for a group that no longer exists", () => {
    expect(pageForTarget("realtime-voice")).toBe("language");
  });
});
