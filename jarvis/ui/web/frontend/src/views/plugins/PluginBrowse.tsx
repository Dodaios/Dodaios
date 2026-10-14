/**
 * The plugin directory: a header with search and the add menu, two scopes
 * (what ships with the app, what the owner added), and sections of rows whose
 * headings open the full list.
 *
 * Connection state and every connect flow stay with `PluginsView`; this file
 * only decides what is listed and how a row reads. Colours are theme tokens, so
 * the page reads the same in light and dark mode.
 */
import { type ReactNode, useEffect, useId } from "react";
import {
  Check,
  ChevronRight,
  ExternalLink,
  FolderUp,
  Link2,
  Loader2,
  MoreHorizontal,
  PanelsTopLeft,
  Plus,
  RefreshCw,
  RotateCw,
  Search,
  Settings2,
  Store,
  Trash2,
  Unplug,
  X,
} from "lucide-react";
import { fill, translate } from "@/i18n";
import { cn } from "@/lib/utils";
import { MarketplaceBadge } from "@/components/MarketplaceBadge";
import {
  ActionMenu,
  IconButton,
  MenuPill,
  type MenuAction,
} from "@/components/extensions/primitives";
import type { AddPluginMode } from "@/views/AddConnectorDialog";
import {
  BrandTile,
  categoryLabel,
  GrantExpiry,
  type Plugin,
  pluginStatusLabel,
  ReauthExplanation,
  searchPlugins,
  sortPluginsByName,
  unavailableReasonText,
  useConnectLock,
} from "@/views/PluginsView";
import {
  allSections,
  type BrowseSection,
  catalogSections,
  COMMUNITY_SECTION,
  homeRows,
  isInstalled,
  isOwnerAdded,
  ownSections,
  type PluginScope,
  POPULAR_SECTION,
  sectionCategory,
  UPLOADED_SECTION,
} from "@/views/plugins/sections";

const isBroken = (plugin: Plugin): boolean =>
  plugin.status === "needs_reauth" || plugin.status === "error";

/** The catalog grid: one column on a narrow pane, two once both fit. */
const GRID = "grid grid-cols-[repeat(auto-fill,minmax(min(100%,340px),1fr))] gap-x-6 gap-y-0.5";

export interface PluginRowHandlers {
  onOpen: (id: string) => void;
  onConnect: (plugin: Plugin) => void | Promise<void>;
  onDisconnect: (id: string) => void;
  onRemove: (plugin: Plugin) => void;
}

/** Display title of a section id, in the current UI language. */
export function sectionTitle(sectionId: string): string {
  if (sectionId === POPULAR_SECTION) return translate("plugins_view.section_popular");
  if (sectionId === UPLOADED_SECTION) return translate("plugins_view.section_uploaded");
  if (sectionId === COMMUNITY_SECTION) return translate("plugins_view.section_community");
  return categoryLabel(sectionCategory(sectionId) ?? sectionId);
}

// ---------------------------------------------------------------------------
// Breadcrumbs — the only way back from a section or a plugin page
// ---------------------------------------------------------------------------

export interface Crumb {
  label: string;
  onClick?: () => void;
}

export function Breadcrumbs({ crumbs }: { crumbs: Crumb[] }) {
  return (
    <nav aria-label={translate("plugins_view.breadcrumb")} className="flex min-w-0 items-center gap-1.5 text-base">
      {crumbs.map((crumb, index) => (
        <span key={`${index}-${crumb.label}`} className="flex min-w-0 items-center gap-1">
          {index > 0 && <ChevronRight className="h-4 w-4 shrink-0 text-foreground-faint" aria-hidden />}
          {crumb.onClick ? (
            <button
              type="button"
              onClick={crumb.onClick}
              className="truncate rounded-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {crumb.label}
            </button>
          ) : (
            <span aria-current="page" className="truncate text-foreground">{crumb.label}</span>
          )}
        </span>
      ))}
    </nav>
  );
}

// ---------------------------------------------------------------------------
// Row
// ---------------------------------------------------------------------------

/** Where an owner-added plugin came from, in the same marks the rest of the
 *  app uses for it. A plugin the app ships carries none. */
function OriginMark({ plugin }: { plugin: Plugin }) {
  if (plugin.selfUploaded) {
    return (
      <span
        className="shrink-0 rounded-full bg-surface-raised px-1.5 text-micro font-medium text-foreground"
        title={translate("plugin_upload.unreviewed")}
      >
        {translate("plugin_upload.self_badge")}
      </span>
    );
  }
  return plugin.fromMarketplace ? <MarketplaceBadge publisher={plugin.publisher} /> : null;
}

const ACTION_BUTTON =
  "grid h-9 w-9 shrink-0 place-items-center rounded-lg text-muted-foreground transition-colors hover:bg-surface-raised hover:text-foreground-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-60";

/** The trailing control of a row. One state at a time, first match wins:
 *  connecting, connected (menu), broken (reconnect + menu), otherwise the "+"
 *  that starts the connection — disabled where the plugin cannot run on this
 *  device. Connection words throughout: an untouched plugin offers Connect,
 *  never Add. */
function RowAction({
  plugin,
  busy,
  run,
  onOpen,
  onDisconnect,
  onRemove,
}: { plugin: Plugin; busy: boolean; run: () => Promise<void> } & Omit<PluginRowHandlers, "onConnect">) {
  const connected = plugin.status === "connected";
  const broken = isBroken(plugin);

  if (busy) {
    return (
      <button type="button" disabled aria-busy className={ACTION_BUTTON}
        aria-label={fill(translate("plugins_view.connecting_plugin"), { plugin: plugin.name })}>
        <Loader2 className="h-[18px] w-[18px] animate-spin" aria-hidden />
      </button>
    );
  }

  if (!connected && !broken) {
    return (
      <button type="button" onClick={() => void run()} className={ACTION_BUTTON}
        disabled={Boolean(plugin.unavailableReason)}
        aria-label={fill(translate("plugins_view.connect_named"), { plugin: plugin.name })}
        title={unavailableReasonText(plugin) ?? translate("plugins_view.connect")}>
        <Plus className="h-[18px] w-[18px]" aria-hidden />
      </button>
    );
  }

  const actions: MenuAction[] = [
    {
      id: "open",
      label: translate("plugins_view.open_details"),
      icon: <PanelsTopLeft className="h-3.5 w-3.5" />,
      onSelect: () => onOpen(plugin.id),
    },
    ...(connected
      ? [{
          id: "reconnect",
          label: translate("plugins_view.reconnect"),
          icon: <RotateCw className="h-3.5 w-3.5" />,
          onSelect: () => void run(),
        }]
      : []),
    {
      id: "disconnect",
      label: translate("plugins_view.disconnect"),
      icon: <Unplug className="h-3.5 w-3.5" />,
      destructive: true,
      separatorAbove: true,
      onSelect: () => onDisconnect(plugin.id),
    },
    ...(isOwnerAdded(plugin)
      ? [{
          id: "remove",
          label: translate("custom_connector.remove"),
          icon: <Trash2 className="h-3.5 w-3.5" />,
          destructive: true,
          onSelect: () => onRemove(plugin),
        }]
      : []),
  ];

  return (
    <span className="flex shrink-0 items-center gap-0.5">
      {connected ? (
        <span role="img" aria-label={translate("plugins_view.status_connected")} title={pluginStatusLabel(plugin)}
          className="grid h-9 w-7 place-items-center text-success">
          <Check className="h-[18px] w-[18px]" aria-hidden />
        </span>
      ) : (
        <button type="button" onClick={() => void run()} className={cn(ACTION_BUTTON, "text-warning hover:text-warning")}
          aria-label={fill(translate("plugins_view.reconnect_named"), { plugin: plugin.name })}
          title={translate("plugins_view.reconnect")}>
          <RotateCw className="h-[18px] w-[18px]" aria-hidden />
        </button>
      )}
      <ActionMenu
        label={translate("plugins_view.more_actions")}
        actions={actions}
        trigger={({ open, toggle }) => (
          <button type="button" onClick={toggle} aria-haspopup="menu" aria-expanded={open}
            aria-label={fill(translate("plugins_view.more_actions_named"), { plugin: plugin.name })}
            title={translate("plugins_view.more_actions")}
            className={cn(ACTION_BUTTON, open && "bg-surface-raised text-foreground-strong")}>
            <MoreHorizontal className="h-[18px] w-[18px]" aria-hidden />
          </button>
        )}
      />
    </span>
  );
}

export function PluginRow({
  plugin,
  showStatus = false,
  onOpen,
  onConnect,
  onDisconnect,
  onRemove,
}: { plugin: Plugin; showStatus?: boolean } & PluginRowHandlers) {
  // One lock per row: the "+" and a menu "Reconnect" can never race into two
  // sign-in flows for the same plugin.
  const { busy, run } = useConnectLock(() => onConnect(plugin));
  const detailsId = useId();
  return (
    <li className="flex min-h-[72px] items-center gap-1 rounded-2xl pr-2 transition-colors hover:bg-secondary focus-within:bg-secondary">
      <button
        type="button"
        onClick={() => onOpen(plugin.id)}
        aria-label={plugin.name}
        aria-describedby={detailsId}
        className="flex min-w-0 flex-1 items-center gap-4 rounded-2xl px-3 py-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <BrandTile plugin={plugin} size="row" />
        <span className="min-w-0 flex-1">
          <span className="flex min-w-0 items-center gap-1.5">
            <span className="truncate text-lg font-medium text-foreground-strong">{plugin.name}</span>
            <OriginMark plugin={plugin} />
          </span>
          <span id={detailsId} className="block">
            <span className="block truncate text-base text-muted-foreground" title={plugin.description}>
              {plugin.description}
            </span>
            {plugin.unavailableReason && (
              <span className="block truncate text-xs text-muted-foreground" title={unavailableReasonText(plugin)}>
                {translate("plugins_view.unsupported_device")}
              </span>
            )}
            {plugin.status === "needs_reauth" && (
              <span className="block truncate text-xs text-warning"><ReauthExplanation plugin={plugin} inline /></span>
            )}
            <GrantExpiry plugin={plugin} />
          </span>
        </span>
        {showStatus && (
          <span className="hidden shrink-0 text-base text-muted-foreground sm:block">{pluginStatusLabel(plugin)}</span>
        )}
      </button>
      <RowAction plugin={plugin} busy={busy} run={run} onOpen={onOpen} onDisconnect={onDisconnect} onRemove={onRemove} />
    </li>
  );
}

function PluginGrid({ plugins, label, single = false, showStatus = false, handlers }: {
  plugins: Plugin[];
  /** Left out where a surrounding region already names the list. */
  label?: string;
  single?: boolean;
  showStatus?: boolean;
  handlers: PluginRowHandlers;
}) {
  return (
    <ul aria-label={label} className={single ? "flex flex-col gap-0.5" : GRID}>
      {plugins.map((plugin) => (
        <PluginRow key={plugin.id} plugin={plugin} showStatus={showStatus} {...handlers} />
      ))}
    </ul>
  );
}

/** Six placeholder rows in the catalog grid while the first load is running. */
function BrowseSkeleton() {
  const widths = ["w-20", "w-16", "w-24", "w-16", "w-20", "w-16"];
  return (
    <div role="status" className="flex flex-col gap-4">
      <span className="sr-only">{translate("plugins_view.loading")}</span>
      <span className="h-3 w-20 rounded bg-secondary motion-safe:animate-pulse" aria-hidden />
      <div className={GRID} aria-hidden>
        {widths.map((width, index) => (
          <div key={index} className="flex min-h-[72px] items-center gap-4 px-3 py-3 motion-safe:animate-pulse">
            <span className="h-12 w-12 shrink-0 rounded-xl bg-secondary" />
            <span className="flex min-w-0 flex-1 flex-col gap-2">
              <span className={cn("h-3 rounded bg-secondary", width)} />
              <span className="h-3 w-3/5 rounded bg-secondary" />
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/** One home-page section: the rows it was given, under a heading that opens
 *  the section's full list. */
function SectionBlock({ section, onOpenSection, handlers }: {
  section: BrowseSection;
  onOpenSection: (id: string) => void;
  handlers: PluginRowHandlers;
}) {
  const title = sectionTitle(section.id);
  return (
    <section aria-label={title} className="flex flex-col gap-4">
      <h3 className="px-3">
        <button
          type="button"
          onClick={() => onOpenSection(section.id)}
          aria-label={fill(translate("plugins_view.open_section"), { section: title })}
          className="group/heading inline-flex items-center gap-1.5 rounded-sm text-xl font-semibold text-foreground-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {title}
          <ChevronRight className="h-5 w-5 text-foreground-faint transition-transform group-hover/heading:text-muted-foreground motion-safe:group-hover/heading:translate-x-0.5" aria-hidden />
        </button>
      </h3>
      <PluginGrid plugins={section.plugins} handlers={handlers} />
    </section>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export interface PluginBrowseProps extends PluginRowHandlers {
  plugins: Plugin[];
  categoryOrder: string[];
  loading: boolean;
  error: string | null;
  refreshing: boolean;
  onRefresh: () => void;
  scope: PluginScope;
  onScope: (scope: PluginScope) => void;
  /** The section whose full list is open, or null on the home page. */
  sectionId: string | null;
  onSection: (sectionId: string | null) => void;
  query: string;
  onQuery: (query: string) => void;
  /** The installed list with its connection states, instead of the directory. */
  managing: boolean;
  onManage: (managing: boolean) => void;
  onAdd: (mode: AddPluginMode) => void;
  onCommunity: () => void;
  onMarketplace: () => void;
  onCustomApis: () => void;
  /** Shown above the sections of the home page (the reconnect notice). */
  banner?: ReactNode;
}

export function PluginBrowse({
  plugins, categoryOrder, loading, error, refreshing, onRefresh,
  scope, onScope, sectionId, onSection, query, onQuery, managing, onManage,
  onAdd, onCommunity, onMarketplace, onCustomApis, banner,
  onOpen, onConnect, onDisconnect, onRemove,
}: PluginBrowseProps) {
  const handlers: PluginRowHandlers = { onOpen, onConnect, onDisconnect, onRemove };
  const sections = scope === "catalog" ? catalogSections(plugins, categoryOrder) : ownSections(plugins);
  const openSection = sectionId
    ? allSections(plugins, categoryOrder).find((section) => section.id === sectionId) ?? null
    : null;
  // A section that empties while open (its last plugin removed) closes, so
  // a later plugin of the same kind does not reopen it unasked.
  const sectionGone = Boolean(sectionId) && !loading && !openSection;
  useEffect(() => {
    if (sectionGone) onSection(null);
  }, [sectionGone, onSection]);
  // What needs a reconnect leads the installed list; the rest follows A-Z.
  const installed = plugins.filter(isInstalled).sort((a, b) =>
    Number(isBroken(b)) - Number(isBroken(a)) || sortPluginsByName(a, b));
  const searching = query.trim() !== "";
  // A search stays inside whatever is open: one section, the installed list,
  // or — on the home page — every plugin of both scopes.
  const pool = managing ? installed : openSection ? openSection.plugins : plugins;
  const results = searching ? searchPlugins(pool, query) : pool;
  const home = !managing && !openSection && !searching;

  const title = managing
    ? translate("plugins_view.manage_title")
    : openSection ? sectionTitle(openSection.id) : translate("plugins_view.title");
  const subtitle = managing
    ? translate("plugins_view.manage_subtitle")
    : openSection ? null : translate("plugins_view.subtitle");

  const leave = () => {
    onManage(false);
    onSection(null);
    onQuery("");
  };

  const addActions: MenuAction[] = [
    {
      id: "connector",
      label: translate("custom_connector.menu_connector"),
      icon: <Link2 className="h-3.5 w-3.5" />,
      onSelect: () => onAdd("connector"),
    },
    {
      id: "upload",
      label: translate("custom_connector.menu_folder"),
      icon: <FolderUp className="h-3.5 w-3.5" />,
      onSelect: () => onAdd("folder"),
    },
    {
      id: "custom-apis",
      label: translate("custom_apis.title"),
      icon: <PanelsTopLeft className="h-3.5 w-3.5" />,
      onSelect: onCustomApis,
    },
    {
      id: "community",
      label: translate("plugins_view.add_community"),
      icon: <Store className="h-3.5 w-3.5" />,
      separatorAbove: true,
      onSelect: onCommunity,
    },
    {
      id: "marketplace",
      label: translate("plugins_view.add_marketplace"),
      icon: <ExternalLink className="h-3.5 w-3.5" />,
      onSelect: onMarketplace,
    },
  ];

  return (
    <div className="flex flex-col gap-8">
      {(managing || openSection) && (
        <Breadcrumbs crumbs={[{ label: translate("plugins_view.title"), onClick: leave }, { label: title }]} />
      )}

      <header className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
        <div className="min-w-0">
          <h2 className="text-2xl font-semibold text-foreground-strong">{title}</h2>
          {subtitle && <p className="mt-1.5 text-lg text-muted-foreground">{subtitle}</p>}
        </div>
        {/* A basis instead of a bare flex-1: on a narrow pane the controls
            wrap under the title rather than squeezing the search shut. */}
        <div className="flex min-w-0 flex-[1_1_22rem] items-center justify-end gap-1.5">
          <label className="flex h-10 min-w-0 max-w-72 flex-1 items-center gap-2.5 rounded-full border border-border bg-background px-3 text-muted-foreground focus-within:border-border-strong">
            <Search className="h-4 w-4 shrink-0" aria-hidden />
            <input
              type="search"
              value={query}
              onChange={(event) => onQuery(event.target.value)}
              // Escape clears a search before it may close the window.
              data-escape-local={searching ? "" : undefined}
              onKeyDown={(event) => { if (event.key === "Escape" && searching) onQuery(""); }}
              placeholder={translate("plugins_view.search_placeholder")}
              aria-label={translate("plugins_view.search_placeholder")}
              className="min-w-0 flex-1 bg-transparent text-base text-foreground outline-none placeholder:text-foreground-faint [&::-webkit-search-cancel-button]:hidden"
            />
            {searching && (
              <button type="button" onClick={() => onQuery("")} aria-label={translate("plugins_view.clear_filters")}
                className="grid h-5 w-5 shrink-0 place-items-center rounded-full hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                <X className="h-3.5 w-3.5" aria-hidden />
              </button>
            )}
          </label>
          <IconButton label={translate("plugins_view.refresh")} onClick={onRefresh} busy={refreshing} className="h-10 w-10">
            <RefreshCw className="h-[18px] w-[18px]" />
          </IconButton>
          {!managing && (
            <IconButton label={translate("plugins_view.manage")} onClick={() => { onSection(null); onQuery(""); onManage(true); }} className="h-10 w-10">
              <Settings2 className="h-[18px] w-[18px]" />
            </IconButton>
          )}
          <ActionMenu
            label={translate("plugins_view.add")}
            actions={addActions}
            trigger={({ open, toggle }) => (
              <MenuPill open={open} toggle={toggle} primary>
                {translate("plugins_view.add")}
              </MenuPill>
            )}
          />
        </div>
      </header>

      {home && (
        <div role="tablist" aria-label={translate("plugins_view.scope_label")} className="flex gap-1">
          {(["catalog", "yours"] as const).map((id) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={scope === id}
              onClick={() => onScope(id)}
              className={cn(
                "rounded-full px-4 py-2 text-base font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                scope === id
                  ? "bg-secondary text-foreground-strong"
                  : "text-muted-foreground hover:bg-secondary hover:text-foreground",
              )}
            >
              {translate(id === "catalog" ? "plugins_view.scope_catalog" : "plugins_view.scope_yours")}
            </button>
          ))}
        </div>
      )}

      {error && (
        <div role="alert" className="flex flex-wrap items-center gap-3 rounded-xl bg-secondary px-4 py-3 text-sm text-destructive">
          <span className="min-w-0 flex-1">{error}</span>
          <button type="button" onClick={onRefresh}
            className="rounded-md border border-border px-2.5 py-1 text-xs font-medium text-foreground hover:bg-surface-raised">
            {translate("common.retry")}
          </button>
        </div>
      )}

      {loading && <BrowseSkeleton />}

      {!loading && !error && home && (
        <>
          {banner}
          {homeRows(sections).map((section) => (
            <SectionBlock key={section.id} section={section} onOpenSection={onSection} handlers={handlers} />
          ))}
          {sections.length === 0 && (
            <div className="rounded-xl border border-border bg-card px-5 py-8 text-center">
              <p className="text-lg font-medium text-foreground-strong">{translate("plugins_view.yours_empty_title")}</p>
              <p className="mx-auto mt-1.5 max-w-md text-base text-muted-foreground">{translate("plugins_view.yours_empty_body")}</p>
              <div className="mt-4 flex flex-wrap justify-center gap-2">
                <button type="button" onClick={() => onAdd("connector")}
                  className="inline-flex h-8 items-center gap-1.5 rounded-md bg-secondary px-3 text-sm font-medium text-foreground hover:bg-surface-raised">
                  <Link2 className="h-3.5 w-3.5" aria-hidden />{translate("custom_connector.menu_connector")}
                </button>
                <button type="button" onClick={onCommunity}
                  className="inline-flex h-8 items-center gap-1.5 rounded-md bg-secondary px-3 text-sm font-medium text-foreground hover:bg-surface-raised">
                  <Store className="h-3.5 w-3.5" aria-hidden />{translate("plugins_view.add_community")}
                </button>
              </div>
            </div>
          )}
        </>
      )}

      {!loading && !error && !home && (
        <>
          {searching && (
            <p className="px-3 text-base text-muted-foreground" aria-live="polite">
              {fill(translate("plugins_view.matches"), { n: results.length })}
            </p>
          )}
          <PluginGrid plugins={results} label={title} single={managing} showStatus={managing} handlers={handlers} />
          {results.length === 0 && (
            <div className="py-12 text-center text-base text-muted-foreground">
              <p>{translate(managing && !searching ? "plugins_view.installed_empty" : "plugins_view.no_hits")}</p>
              {searching && (
                <button type="button" onClick={leave} className="mt-3 underline underline-offset-4 hover:text-foreground">
                  {translate("plugins_view.show_all")}
                </button>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
