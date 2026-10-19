/**
 * One area of the vault as a list: each page with its first sentence, how
 * connected it is and when it last changed. Pages without content are
 * counted but folded away until asked for.
 */
import { useMemo, useState } from "react";
import { Link2, Search } from "lucide-react";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import type { MemoryPageSummary } from "@/lib/memoryApi";
import { matchesQuery, relativeAge, sortPages, type SortKey } from "@/lib/memoryModel";
import { EmptyState } from "@/components/ui/empty-state";
import { KindIcon } from "./KindIcon";

export function PageList({
  title,
  description,
  pages,
  language,
  onOpen,
  emptyIcon,
  emptyTitle,
  emptyBody,
  actions,
}: {
  title: string;
  description: string;
  pages: MemoryPageSummary[];
  language: string;
  onOpen: (path: string) => void;
  emptyIcon: JSX.Element;
  emptyTitle: string;
  emptyBody: string;
  actions?: JSX.Element;
}) {
  const t = useT();
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortKey>("recent");
  const [showEmpty, setShowEmpty] = useState(false);

  const withContent = pages.filter((page) => !page.empty);
  const emptyCount = pages.length - withContent.length;
  const shown = useMemo(
    () => sortPages((showEmpty ? pages : withContent).filter((page) => matchesQuery(page, query)), sort),
    [pages, query, showEmpty, sort, withContent],
  );

  return (
    <div className="mx-auto flex w-full max-w-[980px] flex-col px-8 pb-16 pt-8 lg:px-12" data-testid="memory-page-list">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <h2 className="text-2xl font-semibold tracking-tight text-foreground-strong">{title}</h2>
          <p className="mt-1 max-w-[560px] text-base text-muted-foreground">{description}</p>
        </div>
        {actions}
      </header>

      {pages.length === 0 ? (
        <EmptyState icon={emptyIcon} title={emptyTitle} description={emptyBody} className="mt-10" />
      ) : (
        <>
          <div className="mt-6 flex flex-wrap items-center gap-2">
            <label className="flex h-8 min-w-[220px] flex-1 items-center gap-2 rounded-lg border border-border bg-background px-2.5 focus-within:border-border-strong">
              <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
              <input
                type="search"
                value={query}
                data-escape-local=""
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Escape") setQuery("");
                }}
                placeholder={t("memory_view.filter")}
                aria-label={t("memory_view.filter")}
                className="h-full min-w-0 flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-foreground-faint [&::-webkit-search-cancel-button]:hidden"
              />
            </label>
            <div className="flex items-center rounded-lg border border-border p-0.5" role="group" aria-label={t("memory_view.sort")}>
              {(["recent", "name", "links"] as const).map((key) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setSort(key)}
                  aria-pressed={sort === key}
                  className={cn(
                    "h-7 rounded-md px-2.5 text-sm transition-colors",
                    sort === key ? "bg-secondary font-medium text-foreground-strong" : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {t(`memory_view.sort_${key}`)}
                </button>
              ))}
            </div>
          </div>

          <ul className="mt-4 flex flex-col divide-y divide-border border-y border-border" data-testid="memory-page-rows">
            {shown.map((page) => (
              <li key={page.path}>
                <PageRow page={page} language={language} onOpen={onOpen} />
              </li>
            ))}
          </ul>
          {shown.length === 0 && (
            <p className="py-8 text-center text-sm text-muted-foreground">{t("memory_view.filter_no_match")}</p>
          )}
          {emptyCount > 0 && (
            <button
              type="button"
              onClick={() => setShowEmpty((value) => !value)}
              className="mt-4 self-start rounded-md px-1 text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
              data-testid="memory-toggle-empty"
            >
              {showEmpty
                ? t("memory_view.hide_empty")
                : fill(t("memory_view.show_empty"), { count: emptyCount })}
            </button>
          )}
        </>
      )}
    </div>
  );
}

export function PageRow({
  page,
  language,
  onOpen,
  compact = false,
}: {
  page: MemoryPageSummary;
  language: string;
  onOpen: (path: string) => void;
  compact?: boolean;
}) {
  const t = useT();
  const links = page.links_in + page.links_out;
  return (
    <button
      type="button"
      onClick={() => onOpen(page.path)}
      data-memory-row={page.path}
      className={cn(
        "group flex w-full items-start gap-3 px-2 text-left transition-colors hover:bg-secondary/60 focus-visible:bg-secondary focus-visible:outline-none",
        compact ? "py-2.5" : "py-3.5",
      )}
    >
      <KindIcon kind={page.kind} className="mt-0.5 text-muted-foreground" />
      <span className="min-w-0 flex-1">
        <span className="flex min-w-0 items-baseline gap-3">
          <span className={cn("truncate text-base font-medium", page.empty ? "text-muted-foreground" : "text-foreground-strong")}>
            {page.title}
          </span>
        </span>
        <span className="mt-0.5 line-clamp-1 text-sm text-muted-foreground">
          {page.empty ? t("memory_view.no_content_yet") : page.summary || " "}
        </span>
      </span>
      <span className="flex shrink-0 items-center gap-3 pt-0.5 text-xs tabular-nums text-foreground-faint">
        {links > 0 && (
          <span className="inline-flex items-center gap-1" title={fill(t("memory_view.links_title"), { inbound: page.links_in, outbound: page.links_out })}>
            <Link2 className="h-3 w-3" aria-hidden />
            {links}
          </span>
        )}
        <span className="w-[86px] text-right">{relativeAge(page.mtime, language)}</span>
      </span>
    </button>
  );
}
