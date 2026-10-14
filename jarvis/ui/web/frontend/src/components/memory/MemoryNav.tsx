/**
 * The Memory section's navigation column: search, the areas of the vault with
 * their page counts, and the agents whose notebooks hold something.
 */
import { useMemo } from "react";
import { Bot, Home, Network, Plus, Search, Settings2 } from "lucide-react";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { MemoryIndex } from "@/lib/memoryApi";
import { KNOWLEDGE_AREAS, SYSTEM_AREA, visibleAgents, type MemoryArea } from "@/lib/memoryModel";
import { KindIcon } from "./KindIcon";

export type NavTarget =
  | { view: "home" }
  | { view: "map" }
  | { view: "area"; area: MemoryArea }
  | { view: "agent"; agentId: string };

const ITEM =
  "flex h-8 w-full min-w-0 items-center gap-2.5 rounded-lg px-2 text-left text-base transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

const AREA_KIND = { entities: "entity", projects: "project", concepts: "concept", journal: "session" } as const;

const IS_MAC = typeof navigator !== "undefined" && /Mac|iPhone|iPad/i.test(navigator.platform || navigator.userAgent);

export function MemoryNav({
  index,
  active,
  activeAgentId,
  onNavigate,
  onSearch,
  onNewPage,
}: {
  index: MemoryIndex | undefined;
  active: NavTarget["view"] | MemoryArea | null;
  activeAgentId: string | null;
  onNavigate: (target: NavTarget) => void;
  onSearch: () => void;
  onNewPage: () => void;
}) {
  const t = useT();
  const counts = useMemo(() => {
    const out = new Map<MemoryArea, number>();
    for (const page of index?.pages ?? []) {
      if (page.empty) continue;
      for (const area of [...KNOWLEDGE_AREAS, SYSTEM_AREA]) {
        if (area.matches(page)) out.set(area.id, (out.get(area.id) ?? 0) + 1);
      }
    }
    return out;
  }, [index]);
  // Only live agents get a row here; deleted and unknown ones stay one click
  // away under "All agents", where they can also be tidied up.
  const agents = useMemo(
    () => visibleAgents(index?.agents ?? [], false).filter((agent) => agent.state === "active"),
    [index],
  );
  const areas = KNOWLEDGE_AREAS.filter((area) => area.id !== "journal" || (counts.get("journal") ?? 0) > 0);

  return (
    <aside className="flex w-[248px] shrink-0 flex-col bg-sidebar" data-testid="memory-nav">
      <div className="px-4 pb-3 pt-4">
        <div className="flex items-center justify-between gap-2">
          <h1 className="text-lg font-semibold text-foreground-strong">{t("memory_view.title")}</h1>
          {index?.writable && (
            <button
              type="button"
              onClick={onNewPage}
              aria-label={t("memory_view.new_page")}
              title={t("memory_view.new_page")}
              data-testid="memory-new-page"
              className="grid h-7 w-7 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <Plus className="h-4 w-4" aria-hidden />
            </button>
          )}
        </div>
        <button
          type="button"
          onClick={onSearch}
          data-testid="memory-search-trigger"
          className="mt-3 flex h-8 w-full items-center gap-2 rounded-lg border border-border bg-background px-2.5 text-sm text-muted-foreground transition-colors hover:border-border-strong hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <Search className="h-3.5 w-3.5 shrink-0" aria-hidden />
          <span className="flex-1 truncate text-left">{t("memory_view.search")}</span>
          <kbd className="rounded border border-border px-1 font-sans text-xs leading-4 text-foreground-faint">
            {IS_MAC ? "⌘K" : "Ctrl K"}
          </kbd>
        </button>
      </div>

      <ScrollArea className="min-h-0 flex-1">
        <nav aria-label={t("memory_view.title")} className="flex flex-col gap-0.5 px-2 pb-4">
          <NavItem active={active === "home"} onClick={() => onNavigate({ view: "home" })} icon={<Home aria-hidden />} label={t("memory_view.overview")} />
          <NavItem active={active === "map"} onClick={() => onNavigate({ view: "map" })} icon={<Network aria-hidden />} label={t("memory_view.map")} />

          <GroupHeading label={t("memory_view.group_knowledge")} />
          {areas.map((area) => (
            <NavItem
              key={area.id}
              active={active === area.id}
              onClick={() => onNavigate({ view: "area", area: area.id })}
              icon={<KindIcon kind={AREA_KIND[area.id as keyof typeof AREA_KIND]} />}
              label={t(area.labelKey)}
              count={counts.get(area.id) ?? 0}
              testId={`memory-nav-${area.id}`}
            />
          ))}

          <GroupHeading label={t("memory_view.group_agents")} />
          <NavItem
            active={active === "agents" && !activeAgentId}
            onClick={() => onNavigate({ view: "area", area: "agents" })}
            icon={<Bot aria-hidden />}
            label={t("memory_view.all_agents")}
            count={(index?.agents ?? []).filter((agent) => agent.state === "active").length}
            testId="memory-nav-agents"
          />
          {agents.map((agent) => (
            <button
              key={agent.agent_id}
              type="button"
              onClick={() => onNavigate({ view: "agent", agentId: agent.agent_id })}
              aria-current={activeAgentId === agent.agent_id ? "page" : undefined}
              className={cn(
                ITEM,
                "pl-3 text-sm",
                activeAgentId === agent.agent_id
                  ? "bg-secondary font-medium text-foreground-strong"
                  : "text-muted-foreground hover:bg-secondary hover:text-foreground",
              )}
            >
              <span
                className={cn(
                  "grid h-5 w-5 shrink-0 place-items-center rounded-md text-[10px] font-semibold uppercase",
                  agent.state === "active" ? "bg-surface-raised text-foreground" : "bg-secondary text-foreground-faint",
                )}
                aria-hidden
              >
                {agent.name.slice(0, 1)}
              </span>
              <span className="min-w-0 flex-1 truncate">{agent.name}</span>
              {agent.state !== "active" && (
                <span className="text-xs text-foreground-faint">{t(`memory_view.agent_${agent.state}_short`)}</span>
              )}
            </button>
          ))}

          <GroupHeading label={t("memory_view.group_system")} />
          <NavItem
            active={active === "system"}
            onClick={() => onNavigate({ view: "area", area: "system" })}
            icon={<Settings2 aria-hidden />}
            label={t(SYSTEM_AREA.labelKey)}
            count={counts.get("system") ?? 0}
          />
        </nav>
      </ScrollArea>

      {index && (
        <p className="border-t border-border px-4 py-3 text-xs leading-5 text-foreground-faint" data-testid="memory-nav-stats">
          {fill(t("memory_view.nav_stats"), {
            pages: index.stats.content_pages,
            links: index.stats.links + index.stats.mentions,
          })}
        </p>
      )}
    </aside>
  );
}

function GroupHeading({ label }: { label: string }) {
  return <h2 className="px-2 pb-1 pt-5 text-xs font-medium uppercase tracking-wide text-foreground-faint">{label}</h2>;
}

function NavItem({
  active,
  onClick,
  icon,
  label,
  count,
  testId,
}: {
  active: boolean;
  onClick: () => void;
  icon: JSX.Element;
  label: string;
  count?: number;
  testId?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={active ? "page" : undefined}
      data-testid={testId}
      className={cn(
        ITEM,
        "[&>svg]:h-4 [&>svg]:w-4 [&>svg]:shrink-0",
        active ? "bg-secondary font-medium text-foreground-strong" : "text-muted-foreground hover:bg-secondary hover:text-foreground",
      )}
    >
      {icon}
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {count !== undefined && <span className="text-xs tabular-nums text-foreground-faint">{count}</span>}
    </button>
  );
}
