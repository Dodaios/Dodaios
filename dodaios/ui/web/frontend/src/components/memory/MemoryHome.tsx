/**
 * The Memory section's front page: what the assistant knows, what changed
 * lately and what is most connected — each line one click from the page.
 */
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, BookOpen, Plus } from "lucide-react";
import { fill, useT } from "@/i18n";
import { countText, relativeAge } from "@/lib/memoryModel";
import { MEMORY_KEYS, fetchMemoryActivity, type MemoryIndex } from "@/lib/memoryApi";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { KindIcon } from "./KindIcon";
import { PageRow } from "./PageList";

export function MemoryHome({
  index,
  language,
  onOpen,
  onNewPage,
  onShowAgents,
}: {
  index: MemoryIndex;
  language: string;
  onOpen: (path: string) => void;
  onNewPage: () => void;
  onShowAgents: () => void;
}) {
  const t = useT();
  const activity = useQuery({
    queryKey: MEMORY_KEYS.activity,
    queryFn: () => fetchMemoryActivity(12),
    staleTime: 10_000,
  });

  const knowledge = useMemo(
    () => index.pages.filter((page) => page.group === "knowledge" && !page.empty),
    [index.pages],
  );
  const recent = useMemo(
    () =>
      index.pages
        .filter((page) => page.group !== "system" && !page.empty)
        .sort((a, b) => b.mtime - a.mtime)
        .slice(0, 7),
    [index.pages],
  );
  const hubs = useMemo(
    () => [...knowledge].sort((a, b) => b.links_in - a.links_in).filter((page) => page.links_in > 0).slice(0, 6),
    [knowledge],
  );
  const activeAgents = index.agents.filter((agent) => agent.state === "active");
  const agentsWithMemory = activeAgents.filter((agent) => !agent.empty).length;

  if (index.stats.content_pages === 0) {
    return (
      <div className="flex flex-1 items-center justify-center p-8">
        <EmptyState
          icon={<BookOpen />}
          title={t("memory_view.vault_empty_title")}
          description={t("memory_view.vault_empty_body")}
          actions={
            index.writable ? (
              <Button size="sm" onClick={onNewPage}>
                <Plus aria-hidden />
                {t("memory_view.new_page")}
              </Button>
            ) : undefined
          }
        />
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-[980px] flex-col px-8 pb-16 pt-8 lg:px-12" data-testid="memory-home">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 className="text-2xl font-semibold tracking-tight text-foreground-strong">{t("memory_view.home_title")}</h2>
          <p className="mt-1 max-w-[600px] text-base text-muted-foreground">{t("memory_view.home_lead")}</p>
        </div>
      </header>

      <div className="mt-7 grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-border bg-border sm:grid-cols-4" data-testid="memory-stats">
        <Stat label={t("memory_view.stat_pages")} value={knowledge.length} />
        <Stat label={t("memory_view.stat_links")} value={index.stats.links} />
        <Stat label={t("memory_view.stat_mentions")} value={index.stats.mentions} />
        <Stat
          label={t("memory_view.stat_agents")}
          value={agentsWithMemory}
          suffix={activeAgents.length > 0 ? fill(t("memory_view.stat_of"), { count: activeAgents.length }) : undefined}
          onClick={onShowAgents}
        />
      </div>

      <div className="mt-10 grid gap-10 lg:grid-cols-[minmax(0,1fr)_300px]">
        <section>
          <SectionHeading title={t("memory_view.recently_changed")} />
          <ul className="mt-2 flex flex-col divide-y divide-border border-y border-border">
            {recent.map((page) => (
              <li key={page.path}>
                <PageRow page={page} language={language} onOpen={onOpen} compact />
              </li>
            ))}
          </ul>
        </section>

        <div className="flex flex-col gap-10">
          {hubs.length > 0 && (
            <section>
              <SectionHeading title={t("memory_view.most_connected")} />
              <ul className="mt-2 flex flex-col gap-0.5">
                {hubs.map((page) => (
                  <li key={page.path}>
                    <button
                      type="button"
                      onClick={() => onOpen(page.path)}
                      className="flex h-9 w-full items-center gap-2.5 rounded-lg px-2 text-left text-sm text-foreground transition-colors hover:bg-secondary"
                    >
                      <KindIcon kind={page.kind} className="h-3.5 w-3.5 text-muted-foreground" />
                      <span className="min-w-0 flex-1 truncate">{page.title}</span>
                      <span className="text-xs tabular-nums text-foreground-faint">
                        {countText(t, "memory_view.backlinks_short", page.links_in)}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section>
            <SectionHeading title={t("memory_view.activity")} />
            {activity.isLoading ? (
              <div className="mt-3 space-y-2" role="status" aria-busy="true">
                {[0, 1, 2].map((key) => (
                  <div key={key} className="h-8 animate-pulse rounded-md bg-secondary" />
                ))}
              </div>
            ) : (activity.data?.items.length ?? 0) === 0 ? (
              <p className="mt-2 text-sm text-muted-foreground">{t("memory_view.activity_empty")}</p>
            ) : (
              <ol className="mt-2 flex flex-col" data-testid="memory-activity">
                {activity.data?.items.slice(0, 8).map((item, i) => (
                  <li key={`${item.ts}-${i}`} className="relative border-l border-border pb-4 pl-4 last:pb-0">
                    <span className="absolute -left-[3.5px] top-1.5 h-[7px] w-[7px] rounded-full border border-border-strong bg-background" aria-hidden />
                    <p className="text-xs text-foreground-faint">
                      {relativeAge(Date.parse(item.ts.replace(" ", "T")) / 1000, language)} · {verbLabel(t, item.verb)}
                    </p>
                    <div className="mt-0.5 flex flex-wrap gap-x-2 gap-y-0.5">
                      {item.pages.slice(0, 3).map((page) => (
                        <button
                          key={page.path}
                          type="button"
                          onClick={() => onOpen(page.path)}
                          className="truncate text-left text-sm text-foreground hover:underline"
                        >
                          {page.title}
                        </button>
                      ))}
                      {item.pages.length > 3 && (
                        <span className="text-sm text-muted-foreground">+{item.pages.length - 3}</span>
                      )}
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

const VERBS = new Set(["ingest", "update", "create", "merge", "rename", "archive", "delete"]);

function verbLabel(t: (key: string) => string, verb: string): string {
  return VERBS.has(verb) ? t(`memory_view.verb_${verb}`) : verb;
}

function SectionHeading({ title, action }: { title: string; action?: { label: string; onClick: () => void } }) {
  return (
    <div className="flex items-center justify-between">
      <h3 className="text-sm font-medium text-foreground">{title}</h3>
      {action && (
        <button type="button" onClick={action.onClick} className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          {action.label}
          <ArrowRight className="h-3.5 w-3.5" aria-hidden />
        </button>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  suffix,
  onClick,
}: {
  label: string;
  value: number;
  suffix?: string;
  onClick?: () => void;
}) {
  const body = (
    <>
      <span className="block text-xs text-muted-foreground">{label}</span>
      <span className="mt-1 flex items-baseline gap-1.5">
        <span className="text-2xl font-semibold tabular-nums text-foreground-strong">{value.toLocaleString()}</span>
        {suffix && <span className="text-xs text-foreground-faint">{suffix}</span>}
      </span>
    </>
  );
  return onClick ? (
    <button type="button" onClick={onClick} className="bg-background px-4 py-3.5 text-left transition-colors hover:bg-secondary/60">
      {body}
    </button>
  ) : (
    <div className="bg-background px-4 py-3.5">{body}</div>
  );
}
