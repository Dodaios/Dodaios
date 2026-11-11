/**
 * The Settings hub's left navigation: five groups a person can name without
 * reading them — You, Voice, Connections, Agents, Advanced.
 *
 * Nothing was removed to get there; every page and every option is still
 * reachable, only regrouped. An entry is one of three kinds:
 *
 *   tab   a section id the hub renders itself (Profile, API Keys, Spend …).
 *         The section id IS the state, so deep links keep landing on it.
 *   page  a slice of the General settings page (e.g. "Voice & wake word" is
 *         its voice and wake-word groups). The section stays "settings"; the
 *         slice is the hub's own view state. "All settings" under Advanced
 *         is the whole page, which is also where a bare "settings" deep link,
 *         a search hit and the first-run guide land.
 *   link  a section that has its own page outside the hub (Memory, Dictation,
 *         Plugins, Agents). Picking it leaves Settings for that page.
 */
import type { LucideIcon } from "lucide-react";
import { AudioLines, Languages, SlidersHorizontal } from "lucide-react";
import {
  AgentsIcon,
  ExtensionsIcon,
  SpeechIcon,
  WikiIcon,
} from "@/components/icons/sectionIcons";
import type { SectionId } from "@/store/events";

/** Section ids the hub renders as its own tabs. */
export type HubTabId =
  | "settings"
  | "shortcuts"
  | "appshots"
  | "pets"
  | "notifications"
  | "trust"
  | "phone"
  | "profile"
  | "agent-instructions"
  | "socials"
  | "apikeys"
  | "computers"
  | "costs"
  | "feedback";

export type HubEntry =
  | { kind: "tab"; id: HubTabId }
  | { kind: "page"; key: HubPageKey; labelKey: string; icon: LucideIcon; sections: readonly string[] }
  | { kind: "link"; id: SectionId; labelKey: string; icon: LucideIcon };

export type HubPageKey = "language" | "voice" | "behavior";

/**
 * The General page's groups (SettingsView `SECTIONS` ids) behind each page
 * entry. A group may appear in exactly one page; groups no page names stay
 * under "All settings" only (music, overlay & taskbar).
 */
export const HUB_PAGES: Record<HubPageKey, readonly string[]> = {
  language: ["languages", "app"],
  voice: ["voice", "wake-word"],
  behavior: ["system-prompt", "approvals", "self-build"],
};

const page = (key: HubPageKey, labelKey: string, icon: LucideIcon): HubEntry => ({
  kind: "page",
  key,
  labelKey,
  icon,
  sections: HUB_PAGES[key],
});

export const HUB_GROUPS: readonly { id: string; labelKey: string; entries: readonly HubEntry[] }[] = [
  {
    id: "you",
    labelKey: "design.settings.group_you",
    entries: [
      { kind: "tab", id: "profile" },
      page("language", "design.settings.language_app", Languages),
      { kind: "tab", id: "notifications" },
      { kind: "link", id: "memory", labelKey: "design.settings.memory", icon: WikiIcon },
    ],
  },
  {
    id: "voice",
    labelKey: "design.settings.group_voice",
    entries: [
      page("voice", "design.settings.voice_wake", AudioLines),
      { kind: "link", id: "dictation", labelKey: "design.settings.dictation", icon: SpeechIcon },
      { kind: "tab", id: "shortcuts" },
    ],
  },
  {
    id: "connections",
    labelKey: "design.settings.group_connections",
    entries: [
      { kind: "tab", id: "apikeys" },
      { kind: "link", id: "plugins", labelKey: "design.settings.plugins", icon: ExtensionsIcon },
      { kind: "tab", id: "computers" },
      { kind: "tab", id: "phone" },
    ],
  },
  {
    id: "agents",
    labelKey: "design.settings.group_agents",
    entries: [
      { kind: "tab", id: "agent-instructions" },
      page("behavior", "design.settings.behavior", SlidersHorizontal),
      { kind: "tab", id: "trust" },
      { kind: "link", id: "agents", labelKey: "design.settings.agents", icon: AgentsIcon },
    ],
  },
  {
    id: "advanced",
    labelKey: "design.settings.group_advanced",
    entries: [
      { kind: "tab", id: "settings" },
      { kind: "tab", id: "costs" },
      { kind: "tab", id: "appshots" },
      { kind: "tab", id: "pets" },
      { kind: "tab", id: "socials" },
      { kind: "tab", id: "feedback" },
    ],
  },
];

/** Each page slice's own nav entry, for its label as the page title. */
export const PAGE_ENTRIES = Object.fromEntries(
  HUB_GROUPS.flatMap((group) => group.entries)
    .filter((entry): entry is Extract<HubEntry, { kind: "page" }> => entry.kind === "page")
    .map((entry) => [entry.key, entry]),
) as Record<HubPageKey, Extract<HubEntry, { kind: "page" }>>;

/** A stable key per entry, for React and for the highlight. */
export function entryKey(entry: HubEntry): string {
  return entry.kind === "page" ? `page:${entry.key}` : entry.id;
}

/** The test id each entry renders with. Tabs keep the ids they always had. */
export function entryTestId(entry: HubEntry): string {
  if (entry.kind === "tab") return `settings-hub-nav-${entry.id}`;
  if (entry.kind === "page") return `settings-hub-nav-page-${entry.key}`;
  return `settings-hub-nav-link-${entry.id}`;
}

export type HubContent = HubTabId | "telephony-setup";

/**
 * Which tab content and which entry is highlighted for an active section id
 * and the page slice the person picked. Plain ids name their own tab; the
 * merged-in ids resolve to the tab hosting their content; anything else falls
 * back to the General page. "languages" opens the language slice directly.
 */
export function resolveHubTab(
  active: string,
  pickedPage: HubPageKey | null,
): { content: HubContent; highlight: string; page: HubPageKey | null } {
  switch (active) {
    case "profile":
    case "agent-instructions":
    case "socials":
    case "computers":
    case "appshots":
    case "shortcuts":
    case "pets":
    case "notifications":
    case "trust":
    case "phone":
    case "costs":
    case "feedback":
    case "apikeys":
      return { content: active, highlight: active, page: null };
    case "telephony":
      return { content: "apikeys", highlight: "apikeys", page: null };
    case "telephony-setup":
      return { content: "telephony-setup", highlight: "apikeys", page: null };
    case "languages":
      return { content: "settings", highlight: "page:language", page: "language" };
    case "settings":
      return pickedPage
        ? { content: "settings", highlight: `page:${pickedPage}`, page: pickedPage }
        : { content: "settings", highlight: "settings", page: null };
    case "taskbar":
    default:
      return { content: "settings", highlight: "settings", page: null };
  }
}
