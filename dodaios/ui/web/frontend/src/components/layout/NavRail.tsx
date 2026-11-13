import { lazy, Suspense, type ReactNode } from "react";
import { Search, type LucideIcon } from "lucide-react";

import { ArtifactsIcon, CaptureIcon, ChatIcon, ExtensionsIcon, SpeechIcon } from "@/components/icons/sectionIcons";
import { QuickTooltip } from "@/components/ui/tooltip";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { useEventStore, type SectionId } from "@/store/events";
import { useQuickSwitcher } from "@/store/quickSwitcher";

import { useRailNotices } from "./railNotices";

// Logos, faces and the reconnect sign-in: fetched when the first notice shows.
const RailNoticeTiles = lazy(() => import("./RailNoticeTiles"));

/** The conversation and the pages reached most from beside it, in the maintainer's order. */
const SHORTCUTS: readonly { id: SectionId; labelKey: string; Icon: LucideIcon; also: readonly SectionId[] }[] = [
  { id: "chats", labelKey: "sidebar.surface_chat", Icon: ChatIcon, also: [] },
  { id: "plugins", labelKey: "nav.plugins", Icon: ExtensionsIcon, also: ["skills", "mcps"] },
  { id: "dictation", labelKey: "nav.dictation", Icon: SpeechIcon, also: ["dictionary", "voice-shortcuts", "voice-language", "voice-api-keys"] },
  { id: "visualization", labelKey: "nav.visualization", Icon: ArtifactsIcon, also: [] },
  { id: "appshots", labelKey: "nav.appshots", Icon: CaptureIcon, also: [] },
];

/** One round button of the rail: the shape every icon on it shares. */
export const RAIL_BUTTON =
  "relative flex h-12 w-12 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors " +
  "hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
export const RAIL_BUTTON_ON = "bg-secondary text-foreground-strong";
export const RAIL_GLYPH = "h-6 w-6 shrink-0";

function Divider() {
  return <span aria-hidden className="my-1.5 h-px w-6 shrink-0 bg-border" />;
}

/** A rail icon says its name in a bubble to the right, never in a native tooltip. */
function Named({ name, children }: { name: string; children: ReactNode }) {
  return <QuickTooltip content={name} side="right" className="flex">{children}</QuickTooltip>;
}

/**
 * What needs the person, as round tiles under the shortcuts: a connection that
 * ended, a provider that stopped working, an agent that asks (`railNotices`).
 * Each tile shows whose notice it is and what is asked; nothing shows while
 * nothing needs the person. The tiles are loaded once there is one to draw.
 */
function RailNotices() {
  const t = useT();
  const notices = useRailNotices();
  if (notices.length === 0) return null;
  return (
    <section aria-label={t("rail_notice.title")} data-testid="rail-notices" className="flex flex-col items-center gap-1.5">
      <Divider />
      <Suspense fallback={null}><RailNoticeTiles notices={notices} /></Suspense>
    </section>
  );
}

/**
 * The column beside the conversation: a rail of round icons. On top the
 * conversation, search and the pages reached most; under them only what needs
 * the person right now. Every icon says its name on hover, so the rail needs
 * no words of its own.
 *
 * The rail lists no artifacts and no running work (both did until 2026-11-13):
 * tiles that change by themselves and ask for nothing read as noise, and the
 * maintainer could not tell what the rail was showing. Artifacts have their
 * page one icon above.
 */
export function NavRail({ searchOn }: {
  /** The quick switcher is on, so search has a place on the rail. */
  searchOn: boolean;
}) {
  const t = useT();
  const active = useEventStore((s) => s.activeSection);
  const setActive = useEventStore((s) => s.setActiveSection);
  const searchLabel = t("quick_switch.sidebar_search");

  return (
    <div data-testid="nav-rail" className="flex flex-col items-center gap-1.5 pb-3 pt-1">
      <nav aria-label={t("sidebar.sections")} data-testid="sidebar-shortcuts">
        <ul className="m-0 flex list-none flex-col items-center gap-1.5 p-0">
          {SHORTCUTS.map((item, index) => {
            const { id, labelKey, Icon, also } = item;
            const here = active === id || also.includes(active);
            const label = t(labelKey);
            return [
              <li key={id}>
                <Named name={label}>
                  <button type="button" data-testid={`sidebar-shortcut-${id}`} data-tour={`nav-${item.id}`} onClick={() => setActive(id)}
                    aria-label={label} aria-current={here ? "page" : undefined}
                    className={cn(RAIL_BUTTON, here && RAIL_BUTTON_ON)}>
                    <Icon aria-hidden strokeWidth={1.6} className={RAIL_GLYPH} />
                  </button>
                </Named>
              </li>,
              // Search stands second, right under the conversation.
              index === 0 && searchOn && (
                <li key="search">
                  <Named name={searchLabel}>
                    <button type="button" data-testid="sidebar-search-row" aria-label={searchLabel}
                      onClick={() => useQuickSwitcher.getState().show()} className={RAIL_BUTTON}>
                      <Search aria-hidden strokeWidth={1.6} className={RAIL_GLYPH} />
                    </button>
                  </Named>
                </li>
              ),
            ];
          })}
        </ul>
      </nav>
      <RailNotices />
    </div>
  );
}
