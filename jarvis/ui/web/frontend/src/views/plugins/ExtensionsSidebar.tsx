/**
 * The navigation column of the Plugins, MCPs & Skills section: its three areas
 * and, below them, every plugin the owner connected or added. Clicking one
 * opens its page, so a connection is one click away from any area.
 */
import { useMemo, useState } from "react";
import { Search, X } from "lucide-react";
import { translate, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { ConnectorIcon, PluginIcon, SkillIcon } from "@/components/icons/sectionIcons";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { PluginArea } from "@/views/PluginsDialog";
import { BrandTile, matchesQuery, sortPluginsByName, usePluginCatalog } from "@/views/PluginsView";
import { isInstalled } from "@/views/plugins/sections";

const AREAS = [
  { id: "plugins", labelKey: "nav.plugins", Icon: PluginIcon },
  { id: "mcps", labelKey: "nav.mcps", Icon: ConnectorIcon },
  { id: "skills", labelKey: "nav.skills", Icon: SkillIcon },
] as const;

const ITEM =
  "flex min-w-0 items-center gap-2.5 rounded-lg px-2 text-left text-base transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

export function ExtensionsSidebar({
  area,
  onArea,
  selectedPluginId,
  onOpenPlugin,
}: {
  area: PluginArea;
  onArea: (area: PluginArea) => void;
  selectedPluginId: string | null;
  onOpenPlugin: (id: string) => void;
}) {
  const t = useT();
  const { plugins, isLoading, error, refetch } = usePluginCatalog();
  const [searching, setSearching] = useState(false);
  const [query, setQuery] = useState("");
  const installed = useMemo(
    () => plugins.filter(isInstalled).sort(sortPluginsByName),
    [plugins],
  );
  const shown = query.trim() ? installed.filter((plugin) => matchesQuery(plugin, query)) : installed;
  const closeSearch = () => {
    setSearching(false);
    setQuery("");
  };

  return (
    <aside className="flex shrink-0 flex-col border-b border-border bg-sidebar md:w-[232px] md:border-b-0 md:border-r">
      <h2 className="hidden px-4 pb-2 pt-4 text-base font-semibold text-foreground-strong md:block">
        {t("plugins_view.frame_title")}
      </h2>
      <nav aria-label={t("nav.extensions")} className="flex gap-1 p-2 md:flex-col md:gap-0.5 md:py-0">
        {AREAS.map(({ id, labelKey, Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => onArea(id)}
            aria-current={area === id && !selectedPluginId ? "page" : undefined}
            className={cn(
              ITEM,
              "h-8",
              area === id && !selectedPluginId
                ? "bg-secondary font-medium text-foreground-strong"
                : "text-muted-foreground hover:bg-secondary hover:text-foreground",
            )}
          >
            <Icon className="h-4 w-4 shrink-0" aria-hidden />
            <span className="truncate">{t(labelKey)}</span>
          </button>
        ))}
      </nav>

      <div className="hidden min-h-0 flex-1 flex-col md:flex">
        <div className="flex h-8 items-center justify-between pl-4 pr-2 pt-5">
          <h3 className="text-sm text-muted-foreground">{t("plugins_view.installed_heading")}</h3>
          <button
            type="button"
            onClick={() => (searching ? closeSearch() : setSearching(true))}
            aria-label={t("plugins_view.installed_search")}
            aria-pressed={searching}
            title={t("plugins_view.installed_search")}
            className="grid h-6 w-6 place-items-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {searching ? <X className="h-3.5 w-3.5" aria-hidden /> : <Search className="h-3.5 w-3.5" aria-hidden />}
          </button>
        </div>
        {searching && (
          <div className="px-2 pt-3">
            <input
              type="search"
              autoFocus
              data-escape-local=""
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              // Escape leaves the search, not the whole plugin window.
              onKeyDown={(event) => { if (event.key === "Escape") closeSearch(); }}
              placeholder={t("plugins_view.installed_search")}
              aria-label={t("plugins_view.installed_search")}
              className="h-8 w-full rounded-lg border border-border bg-background px-2.5 text-sm text-foreground outline-none placeholder:text-foreground-faint focus:border-border-strong [&::-webkit-search-cancel-button]:hidden"
            />
          </div>
        )}
        <ScrollArea className="mt-2 min-h-0 flex-1">
          <ul aria-label={t("plugins_view.installed_heading")} className="flex flex-col gap-0.5 px-2 pb-3">
            {shown.map((plugin) => {
              const broken = plugin.status === "needs_reauth" || plugin.status === "error";
              const active = area === "plugins" && selectedPluginId === plugin.id;
              return (
                <li key={plugin.id}>
                  <button
                    type="button"
                    onClick={() => onOpenPlugin(plugin.id)}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      ITEM,
                      "h-8 w-full",
                      active
                        ? "bg-secondary font-medium text-foreground-strong"
                        : "text-foreground hover:bg-secondary",
                    )}
                  >
                    <BrandTile plugin={plugin} size="xs" />
                    <span className="min-w-0 flex-1 truncate">{plugin.name}</span>
                    {broken && (
                      <span role="img" aria-label={translate("plugins_view.status_reauth")} title={translate("plugins_view.status_reauth")}
                        className="h-1.5 w-1.5 shrink-0 rounded-full bg-warning" />
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
          {shown.length === 0 && (
            <div className="px-4 pb-3 text-sm text-muted-foreground">
              {isLoading ? (
                <p role="status">{t("plugins_view.loading")}</p>
              ) : error ? (
                <>
                  <p role="alert">{t("plugins_view.unreachable")}</p>
                  <button type="button" onClick={() => void refetch()} className="mt-2 underline underline-offset-4 hover:text-foreground">
                    {t("common.retry")}
                  </button>
                </>
              ) : (
                <p>{t(query.trim() ? "plugins_view.installed_no_match" : "plugins_view.installed_empty")}</p>
              )}
            </div>
          )}
        </ScrollArea>
      </div>
    </aside>
  );
}
