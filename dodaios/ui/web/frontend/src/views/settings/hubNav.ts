/**
 * The Settings hub's left navigation: six groups a person can name without
 * reading them — You, Voice, Connections, Assistant, Tools, Advanced.
 *
 * The app's sidebar holds only the conversation and the Agentic IDE, so this
 * is where every other page is reached from. An entry is one of three kinds:
 *
 *   tab   a section id the hub renders itself (Profile, API Keys, Spend …).
 *         The section id IS the state, so deep links keep landing on it.
 *   page  a slice of the General settings page (e.g. "Voice & wake word" is
 *         its voice and wake-word groups). The section stays "settings"; the
 *         slice is the hub's own view state. Every group belongs to exactly
 *         one slice, so no entry shows the whole page: a bare "settings"
 *         deep link opens the first slice, and a search hit, a jump from
 *         outside or the first-run guide opens the slice holding its group
 *         (`pageForTarget`).
 *   link  a section that has its own page outside the hub (Memory, Dictation,
 *         Plugins, Artifacts, the tools). Picking it leaves Settings for that
 *         page.
 */
import type { LucideIcon } from "lucide-react";
import { AudioLines, Languages, SlidersHorizontal } from "lucide-react";
import {
  NodesIcon,
  BoardIcon,
  BuiltIcon,
  DocsIcon,
  ExtensionsIcon,
  MarketplaceIcon,
  MicrophoneIcon,
  SpeechIcon,
  TerminalIcon,
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
 * entry. Every group appears in exactly one page (hubNav.test checks it), so
 * each setting has one place in the navigation.
 */
export const HUB_PAGES: Record<HubPageKey, readonly string[]> = {
  language: ["languages", "app", "overlay-taskbar", "music"],
  voice: ["voice", "wake-word"],
  behavior: ["system-prompt", "approvals", "self-build"],
};

/** The slice a bare "settings" link opens. */
export const DEFAULT_HUB_PAGE: HubPageKey = "language";

/**
 * Rows that carry their own `settings-<id>` anchor inside a group, by the
 * group that renders them. A search hit or a jump may name the row.
 */
const ROW_GROUPS: Record<string, string> = {
  volume: "voice",
  "audio-devices": "voice",
  more: "app",
};

/** The slice that shows a group or row anchor; the first slice when unknown. */
export function pageForTarget(target: string): HubPageKey {
  const group = ROW_GROUPS[target] ?? target;
  const found = (Object.keys(HUB_PAGES) as HubPageKey[]).find((key) => HUB_PAGES[key].includes(group));
  return found ?? DEFAULT_HUB_PAGE;
}

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
    ],
  },
  // What used to be the sidebar's own rows. Each keeps its page; only the
  // way in moved here.
  {
    id: "tools",
    labelKey: "nav.group_tools",
    entries: [
      { kind: "link", id: "visualization", labelKey: "nav.visualization", icon: NodesIcon },
      { kind: "link", id: "marketplace", labelKey: "nav.marketplace", icon: MarketplaceIcon },
      { kind: "link", id: "clis", labelKey: "nav.clis_hub", icon: TerminalIcon },
      { kind: "link", id: "sessions", labelKey: "nav.sessions", icon: MicrophoneIcon },
      { kind: "link", id: "board", labelKey: "nav.board", icon: BoardIcon },
      { kind: "link", id: "docs", labelKey: "nav.docs", icon: DocsIcon },
      { kind: "link", id: "self-build", labelKey: "nav.self_build", icon: BuiltIcon },
    ],
  },
  {
    id: "advanced",
    labelKey: "design.settings.group_advanced",
    entries: [
      { kind: "tab", id: "costs" },
      { kind: "tab", id: "appshots" },
      { kind: "tab", id: "pets" },
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
 * back to the first slice of the General page. "languages" and "taskbar" open
 * the slice their groups live in, "voice-shortcuts" (the former Voice tab for
 * the dictation keys) opens Keyboard shortcuts. "socials" keeps its tab for
 * old links, but no entry lists it.
 */
export function resolveHubTab(
  active: string,
  pickedPage: HubPageKey | null,
): { content: HubContent; highlight: string; page: HubPageKey | null } {
  // `page` is null for every tab but the General page, which always shows one slice.
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
    case "voice-shortcuts":
      return { content: "shortcuts", highlight: "shortcuts", page: null };
    case "telephony":
      return { content: "apikeys", highlight: "apikeys", page: null };
    case "telephony-setup":
      return { content: "telephony-setup", highlight: "apikeys", page: null };
    case "languages":
    case "taskbar":
      return { content: "settings", highlight: "page:language", page: "language" };
    case "settings":
    default: {
      const page = active === "settings" && pickedPage ? pickedPage : DEFAULT_HUB_PAGE;
      return { content: "settings", highlight: `page:${page}`, page };
    }
  }
}
