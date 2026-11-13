import { Mic, MoreHorizontal } from "lucide-react";
import { SETTINGS_HUB_IDS } from "@/components/layout/navGroups";
import { useEventStore } from "@/store/events";
import { useSectionPrefetch } from "@/hooks/useSectionPrefetch";
import { useVoiceIndicator } from "@/hooks/useVoiceIndicator";
import { useSectionHealth } from "@/hooks/useProviders";
import { usePluginAttention } from "@/hooks/usePluginAttention";
import { cn } from "@/lib/utils";
import { lazy, Suspense, useMemo } from "react";
import { useT } from "@/i18n";
import { LazyIdeProjectTree } from "@/components/agentic/LazyIdeProjectTree";
import { IDE_SECTIONS } from "@/lib/ideSections";
import { useIdeProjectsStore } from "@/store/ideProjects";
import { useIdeThreadsStore } from "@/store/ideThreads";
import { SidebarSearchBar } from "@/components/layout/SidebarSearchBar";
import { IdeLayoutSwitch } from "@/components/agentic/threads/IdeLayoutSwitch";
import { useQuickSwitchSettings } from "@/store/quickSwitchSettings";
import { useAppInstance } from "@/hooks/useAppInstance";
import { usePublishIdentity } from "@/hooks/usePublishIdentity";
import { MarketplaceIcon } from "@/components/icons/sectionIcons";
import { NavRail, RAIL_BUTTON, RAIL_BUTTON_ON, RAIL_GLYPH } from "@/components/layout/NavRail";
import { QuickTooltip } from "@/components/ui/tooltip";
import { useUserName } from "@/hooks/useUserName";
import { apiKeysHealthError } from "@/lib/apiKeysTab";

// The update button renders nothing on most launches; loaded on its own so
// the title-strip module it lives in stays out of the sidebar's chunk.
const UpdateButton = lazy(() =>
  import("@/components/layout/TopBar").then((m) => ({ default: m.UpdateButton })),
);

export interface SidebarProps {
  /**
   * Rendered width in px. Owned by the app shell, because the seam that changes
   * it lives BETWEEN the sidebar and the main area — see `PaneResizer`. Left
   * optional so the sidebar still renders standalone (tests, storybook-style
   * one-offs) at its designed width.
   */
  width?: number;
  /**
   * Is the sidebar deliberately collapsed to its icon rail?
   *
   * Separate from `width` because the two answer different questions. The width
   * is a drag preference and survives a collapse — expanding restores the
   * column the user sized, not the designed default. Collapsing is a STATE, and
   * the app opens in it: the sidebar is navigation, and navigation is not what
   * the window is for. Left optional so the sidebar still renders standalone.
   */
  collapsed?: boolean;
}

/** Width the sidebar was designed at, and the one a double-click restores.
 *  240 since 2026-09-02 (v4 redesign): the Cursor / Grok column. The
 *  navigation is a single 14 px list now, so it fits; the Agentic IDE's
 *  chat list, which drove the older 400, is still one drag away and the
 *  dragged width is remembered. */
export const SIDEBAR_DEFAULT_WIDTH = 240;

/**
 * localStorage key the dragged width is remembered under.
 *
 * `v2` since 2026-08-27. The seam used to stop at 200 px, and a column dragged
 * to that floor back then stayed there through every default since — on the
 * maintainer's desktop the Agentic IDE's session list was still 200 px wide
 * when its rows were redesigned around a two-line title that holds a whole
 * 48-character recap at the designed 320 (`WorkspaceChats`). At 200 the same
 * row holds twelve characters a line, so nothing about the redesign reached
 * the one box it was asked for. A new key seeds every column at the designed
 * width once; a dragged width is remembered again from there.
 *
 * `v3` with the 400 px default (same day): the wider column is the point of
 * the change, so every existing column is re-seeded at it once more.
 *
 * `v4` with the 240 px default (2026-09-02): the redesign's column.
 */
export const SIDEBAR_WIDTH_STORAGE_KEY = "jarvis.sidebar.width.v4";

/**
 * Narrowest the sidebar goes: the nav icons, and nothing else.
 *
 * The seam used to stop at 200 px, which is wide enough to still read every
 * label — so in the Agentic IDE, where a workspace of a dozen terminals wants
 * every pixel, a fifth of the window stayed spent on a list nobody was reading.
 * The rail keeps navigation one click away (the icons are still there, each
 * with its label on hover) while giving that space back to the panes.
 *
 * Beside the conversation the rail is the only face the column has
 * (2026-11-11, `NavRail`): round 48 px icons, so the width leaves 14 px of
 * air on either side of them.
 */
export const SIDEBAR_RAIL_WIDTH = 76;

/**
 * Below this dragged width the sidebar SNAPS to the rail rather than clipping.
 *
 * Between the two there is no useful layout: a 120 px sidebar shows half a word
 * per row, which reads as a broken column rather than a deliberate one. So the
 * band is skipped — pull past it and you get icons, pull back and you get text.
 */
export const SIDEBAR_RAIL_AT_WIDTH = 168;

export function Sidebar({
  width = SIDEBAR_DEFAULT_WIDTH,
  collapsed = false,
}: SidebarProps = {}) {
  const t = useT();
  const profilePrefetch = useSectionPrefetch("profile");
  const marketplacePrefetch = useSectionPrefetch("marketplace");
  const active = useEventStore((s) => s.activeSection);
  const setActive = useEventStore((s) => s.setActiveSection);
  const activeIdeWorkspaceId = useIdeProjectsStore((s) => s.activeWorkspaceId);
  const openIdeWorkspaceOptions = useIdeProjectsStore((s) => s.openWorkspaceOptions);
  const toggleIdeVoice = useIdeProjectsStore((s) => s.toggleVoice);
  const assistantName = useEventStore((s) => s.assistantName);
  // The search bar takes the identity row's place while the quick
  // switcher is on; switched off, the row comes back as it was.
  const searchBarOn = useQuickSwitchSettings((s) => s.enabled);
  // The dev instance (a second, restartable app beside the live one — see
  // dodaios.core.instance) shows a small tag so the two windows are never
  // confused; the default app shows nothing here.
  const appInstance = useAppInstance();
  const devTag = appInstance?.isDev ? appInstance.name.toUpperCase() : null;
  // The IDE leads its column with its own chat / grid switch; which of the
  // app's two places is on screen is picked in the window caption above.
  const onIdeSection = IDE_SECTIONS.includes(active);
  // The IDE's thread list carries search as one of its own start rows
  // (ThreadTree), so there the field atop the column steps aside.
  const threadLayout = useIdeThreadsStore((s) => s.layout) === "threads" && onIdeSection;
  // Beside the conversation, search is one of the rail's icons instead.
  const headerSearch = searchBarOn && onIdeSection && !threadLayout;
  const identity = usePublishIdentity();
  const userName = useUserName();
  // The person by first name once the Profile knows it, else their
  // marketplace login, else the plain word — never an invented name.
  const footerName =
    userName?.split(/\s+/)[0] ||
    (identity.data?.signed_in && identity.data.login) ||
    t("nav.profile");

  // Per-section provider health (same source as the API-Keys tab dots). The
  // sidebar surfaces only a hard "error" — a provider that is set up but failing
  // — so a broken key is visible from anywhere without opening the page. The
  // amber "needs setup" state is intentionally NOT shown here: on a fresh install
  // every unconfigured section would light up and the bar would never be calm.
  const { health: sectionHealth } = useSectionHealth();
  const apikeysHasError = useMemo(() => apiKeysHealthError(sectionHealth), [sectionHealth]);
  // The footer card IS the button that opens API Keys, so its dot carries that
  // page's verdict rather than a decorative grey mark. Three honest states:
  // something is failing, something has answered, or nothing has reported yet
  // — a fresh install must not claim green before a single provider replied.
  // A connected marketplace plugin whose token was revoked/expired (needs_reauth)
  // — surfaced as an amber dot on the row that fronts Plugins ("Skills & Tools"),
  // so a dead connection is visible app-wide, not only on the Plugins page. The
  // names let the tooltip say WHICH plugin, not just "something is off".
  const pluginAttention = usePluginAttention();
  const pluginsNeedReconnect = pluginAttention.count > 0;
  // The Local models health monitor (D7) writes a `local_models` record; a
  // failing or half-configured local setup marks the profile button, the
  // hub's entry point — badge only, never a toast.
  const localModelsHealth = sectionHealth.local_models;
  const localModelsNeedAttention =
    localModelsHealth?.status === "error" || localModelsHealth?.status === "needs_setup";
  // Name the culprit(s) in the hover text so the dot stops being cryptic; the
  // full plain-language banner + jump button live in the Plugins view itself.
  const pluginWarnTitle = pluginAttention.names.length
    ? `${t("sidebar.plugins_reconnect_alert")}: ${pluginAttention.names.join(", ")}`
    : t("sidebar.plugins_reconnect_alert");
  // The voice path's state: the caption's Dodaios switch draws its dot, and
  // the header here spells it out only when it is news.
  const voice = useVoiceIndicator();

  // Dragged past the snap point the sidebar becomes a rail of icons. Everything
  // that only makes sense with a label beside it steps aside; the
  // navigation itself never does, because losing it would make the rail a dead
  // end rather than a narrow sidebar.
  // Two independent ways into the rail in the IDE: the explicit toggle, and
  // dragging the seam past the snap point. Either one alone is enough — a user
  // who dragged the column narrow gets icons without having to also find the
  // button. Beside the conversation the column is always the rail: it lists
  // nothing that needs a line of text, so the width belongs to the conversation.
  const railed = !onIdeSection || collapsed || width < SIDEBAR_RAIL_AT_WIDTH;

  // Lit while any hub section is on screen — the profile button IS the hub's
  // entry point now, so it carries the "you are here" state for all of them.
  const hubActive = (SETTINGS_HUB_IDS as readonly string[]).includes(active);
  const rowClass = "flex min-h-8 w-full items-center gap-3 rounded-lg px-3 text-base text-foreground transition-colors hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

  return (
    // No right border: the draggable seam beside it draws that line now, and
    // two 1px lines three pixels apart read as a rendering fault.
    // z-20: above the stage column, which carries no z-index of its own so
    // that the overlays inside it are not trapped below this one (App.tsx).
    // That same open stage means a section's own z-20 layer (the IDE's pane
    // chat, say) ties with this column and wins on DOM order — so the rail's
    // hover label, which flies out past the sidebar's edge, does NOT rely on
    // this z-index: `DockRail` portals it to <body> at the tooltip level. The
    // app-wide layers (toasts, docks, dialogs) all sit at z-40 and above and
    // really do cover this column.
    <aside
      style={{ width: railed ? SIDEBAR_RAIL_WIDTH : width }}
      data-testid="sidebar"
      data-railed={railed ? "true" : "false"}
      className="jarvis-nav-surface relative isolate z-20 flex h-full shrink-0 flex-col pt-8"
    >
      {/* The app's two places (Dodaios, IDE) are picked in the window
          caption. On the IDE the column opens with how it reads: chat or
          grid. Everything else is a Settings page, behind the profile button
          at the foot. */}
      <div className={cn("flex flex-col gap-1.5", !railed ? "px-2 pb-1 pt-1" : onIdeSection ? "items-center px-3 py-2.5" : "items-center px-2 pt-1")}>
        {onIdeSection && <IdeLayoutSwitch railed={railed} />}
        {/* On the rail the dev instance still says so: two windows that look alike are the trap. */}
        {railed && devTag && (
          <span data-testid="sidebar-instance-tag" title={t("sidebar.instance_dev_hint")}
            className="max-w-full truncate rounded-sm bg-primary px-1 py-0.5 text-xs font-medium leading-none text-primary-foreground">
            {devTag}
          </span>
        )}
        {/* The state is spelled out only when it is news: starting, offline,
            listening. At rest the dot says "fine" on its own. */}
        {!railed && (voice.news || devTag) && (
          <div className="flex min-w-0 items-center gap-2 px-1">
            {/* The dev instance says so on a line of its own; in the switch it squeezed the name out. */}
            {devTag && (
              <span data-testid="sidebar-instance-tag" title={t("sidebar.instance_dev_hint")}
                className="shrink-0 rounded-sm bg-primary px-1 py-0.5 text-xs font-medium leading-none text-primary-foreground">
                {devTag}
              </span>
            )}
            {voice.news && <p data-testid="sidebar-voice-label" className="truncate text-xs text-muted-foreground">{voice.label}</p>}
          </div>
        )}
        {!railed && headerSearch && <SidebarSearchBar assistantName={assistantName} />}
      </div>

      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto scrollbar-jarvis">
        {/* The IDE lists its folders here, or keeps two controls on its rail.
            Beside the conversation the column is a rail of round icons: the
            conversation, search, the pages reached most, and under them what
            needs the person (`NavRail`). The assistant's
            own panel stands to the right of the conversation. */}
        {!onIdeSection ? <NavRail searchOn={searchBarOn} />
          : railed ? <nav aria-label={t("sidebar.ide_navigation")} className="px-2 pt-2">
          <div className="flex flex-col items-center gap-1">
            <button type="button" aria-label={t("sidebar.workspace_options")} title={t("sidebar.workspace_options")}
              disabled={!activeIdeWorkspaceId}
              onClick={() => { if (activeIdeWorkspaceId) openIdeWorkspaceOptions(activeIdeWorkspaceId); }}
              className="flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-35">
              <MoreHorizontal aria-hidden className="h-4 w-4" />
            </button>
            <button type="button" aria-label="Dodaios Live" title="Dodaios Live" onClick={toggleIdeVoice}
              className="flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              <Mic aria-hidden className="h-4 w-4" />
            </button>
          </div>
        </nav> : <LazyIdeProjectTree />}
      </div>

      {/* The footer is one button now, not a popup: it opens the Settings hub
          on the Profile tab. The hub carries every former popup entry
          (Profile, {name}.md, Contacts, Spend, Socials, API Keys, Local
          models, Settings, Feedback) in its own left navigation.
          The attention dot stays — a failing provider, or a local setup that
          needs care, must be visible without opening anything. */}
      <div className={cn("shrink-0", railed ? "px-2 pb-3 pt-1.5" : "border-t border-border px-2 py-1.5")}>
        {/* On the rail the foot reads bottom-up: the person, the marketplace, a waiting update. */}
        <div className={cn("flex items-center", railed ? "flex-col-reverse gap-1.5" : "gap-0.5")}>
          <QuickTooltip content={railed ? footerName : ""} side="right" className={railed ? "flex" : "flex min-w-0 flex-1"}>
          <button type="button" {...profilePrefetch} onClick={() => setActive("profile")} aria-label={t("nav.profile")}
            title={railed ? undefined : t("nav.profile")}
            data-testid="sidebar-profile-toggle"
            data-tour="settings"
            className={railed
              ? cn(RAIL_BUTTON, hubActive && cn("jarvis-nav-active", RAIL_BUTTON_ON))
              : cn(rowClass, "min-w-0 flex-1", hubActive && "jarvis-nav-active bg-secondary text-foreground")}>
            <span className="relative shrink-0">
              <span aria-hidden data-testid="sidebar-profile-initial"
                className={cn("flex items-center justify-center rounded-full bg-secondary font-medium uppercase text-muted-foreground",
                  railed ? "h-9 w-9 text-sm ring-1 ring-inset ring-border" : "h-6 w-6 text-xs")}>
                {footerName.trim().charAt(0) || "?"}
              </span>
              {(apikeysHasError || localModelsNeedAttention || pluginsNeedReconnect) && <span data-testid="sidebar-profile-attention"
                role="status" title={pluginsNeedReconnect ? pluginWarnTitle : undefined}
                aria-label={apikeysHasError || localModelsNeedAttention ? t("sidebar.apikeys_alert") : pluginWarnTitle}
                className={cn("absolute -bottom-0.5 -right-0.5 h-2 w-2 rounded-full ring-2 ring-sidebar", apikeysHasError ? "bg-destructive" : "bg-warning")} />}
            </span>
            {!railed && <span data-testid="sidebar-profile-name" className="min-w-0 flex-1 truncate text-left">{footerName}</span>}
          </button>
          </QuickTooltip>
          {/* The update lives here now, where Claude keeps its download icon:
              in sight on every screen, not among the window buttons. */}
          <Suspense fallback={null}><UpdateButton placement="sidebar" /></Suspense>
          <QuickTooltip content={railed ? t("nav.marketplace") : ""} side="right" className="flex">
          <button type="button" {...marketplacePrefetch} onClick={() => setActive("marketplace")}
            title={railed ? undefined : t("nav.marketplace")}
            aria-label={t("nav.marketplace")} data-testid="nav-row-marketplace"
            aria-current={active === "marketplace" ? "page" : undefined}
            className={railed
              ? cn(RAIL_BUTTON, active === "marketplace" && RAIL_BUTTON_ON)
              : "flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"}>
            <MarketplaceIcon aria-hidden strokeWidth={railed ? 1.6 : 1.75} className={railed ? RAIL_GLYPH : "h-4 w-4"} />
          </button>
          </QuickTooltip>
        </div>
      </div>
    </aside>
  );
}
