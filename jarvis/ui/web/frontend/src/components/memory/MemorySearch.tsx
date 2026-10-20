/**
 * Ctrl/Cmd+K over the whole memory: titles match instantly from the index,
 * full text (and, when switched on, meaning) follows from the server, and a
 * title nobody has written yet can become a new page from the same box.
 */
import { useEffect, useMemo, useState } from "react";
import { Command } from "cmdk";
import { useQuery } from "@tanstack/react-query";
import { CornerDownLeft, Plus, Search } from "lucide-react";
import { fill, useT } from "@/i18n";
import { MEMORY_KEYS, searchMemory, type MemoryIndex } from "@/lib/memoryApi";
import { KindIcon } from "./KindIcon";

const ITEM =
  "flex min-h-9 cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-sm text-foreground aria-selected:bg-secondary aria-selected:text-foreground-strong";

export function MemorySearch({
  open,
  onOpenChange,
  index,
  onOpen,
  onCreate,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  index: MemoryIndex | undefined;
  onOpen: (path: string) => void;
  onCreate: (title: string) => void;
}) {
  const t = useT();
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");

  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(query.trim()), 180);
    return () => window.clearTimeout(id);
  }, [query]);

  useEffect(() => {
    if (!open) setQuery("");
  }, [open]);

  const titleHits = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const pages = (index?.pages ?? []).filter((page) => page.group !== "system" || needle);
    if (!needle) {
      return pages.filter((page) => !page.empty).sort((a, b) => b.mtime - a.mtime).slice(0, 8);
    }
    return pages
      .filter((page) => page.title.toLowerCase().includes(needle) || page.slug.toLowerCase().includes(needle))
      .sort(
        (a, b) =>
          Number(b.title.toLowerCase().startsWith(needle)) - Number(a.title.toLowerCase().startsWith(needle)) ||
          Number(a.empty) - Number(b.empty) ||
          b.links_in - a.links_in,
      )
      .slice(0, 8);
  }, [index, query]);

  const textQuery = useQuery({
    queryKey: MEMORY_KEYS.search(debounced),
    queryFn: () => searchMemory(debounced),
    enabled: open && debounced.length >= 2,
    staleTime: 30_000,
  });
  const titlePaths = new Set(titleHits.map((page) => page.path));
  const byPath = new Map((index?.pages ?? []).map((page) => [page.path, page]));
  const textHits = (textQuery.data ?? []).filter((hit) => !titlePaths.has(hit.path));
  const exact = (index?.pages ?? []).some((page) => page.title.toLowerCase() === query.trim().toLowerCase());

  const choose = (path: string) => {
    onOpenChange(false);
    onOpen(path);
  };

  return (
    <Command.Dialog
      open={open}
      onOpenChange={onOpenChange}
      label={t("memory_view.search")}
      shouldFilter={false}
      overlayClassName="fixed inset-0 z-[80] bg-scrim/40"
      contentClassName="fixed left-1/2 top-[14%] z-[90] w-[min(640px,calc(100vw-2rem))] -translate-x-1/2 overflow-hidden rounded-xl border border-border bg-popover text-popover-foreground shadow-float"
      data-testid="memory-search"
    >
      <div className="flex items-center gap-2.5 border-b border-border px-4">
        <Search className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
        <Command.Input
          value={query}
          onValueChange={setQuery}
          placeholder={t("memory_view.search_placeholder")}
          className="h-12 flex-1 bg-transparent text-base text-foreground outline-none placeholder:text-foreground-faint"
        />
      </div>
      <Command.List className="max-h-[min(60vh,480px)] overflow-y-auto p-2">
        <Command.Empty className="px-3 py-8 text-center text-sm text-muted-foreground">
          {textQuery.isFetching ? t("memory_view.searching") : t("memory_view.search_no_results")}
        </Command.Empty>

        {titleHits.length > 0 && (
          <Command.Group
            heading={query.trim() ? t("memory_view.search_titles") : t("memory_view.recently_changed")}
            className="[&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:pt-2 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:text-foreground-faint"
          >
            {titleHits.map((page) => (
              <Command.Item key={page.path} value={`title:${page.path}`} onSelect={() => choose(page.path)} className={ITEM}>
                <KindIcon kind={page.kind} className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="min-w-0 flex-1 truncate">{page.title}</span>
                <span className="max-w-[40%] truncate text-xs text-foreground-faint">
                  {page.empty ? t("memory_view.no_content_yet") : page.folder}
                </span>
              </Command.Item>
            ))}
          </Command.Group>
        )}

        {textHits.length > 0 && (
          <Command.Group
            heading={t("memory_view.search_text")}
            className="[&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:pt-3 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:text-foreground-faint"
          >
            {textHits.map((hit) => {
              const page = byPath.get(hit.path);
              return (
                <Command.Item key={hit.path} value={`text:${hit.path}`} onSelect={() => choose(hit.path)} className={`${ITEM} items-start`}>
                  <KindIcon kind={page?.kind} className="mt-0.5 h-3.5 w-3.5 text-muted-foreground" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate">{page?.title ?? hit.title}</span>
                    {hit.snippet && <span className="line-clamp-2 text-xs text-muted-foreground">{hit.snippet.replace(/\s+/g, " ")}</span>}
                  </span>
                  {hit.by_meaning && <span className="shrink-0 text-xs text-foreground-faint">{t("memory_view.by_meaning")}</span>}
                </Command.Item>
              );
            })}
          </Command.Group>
        )}

        {query.trim() && !exact && index?.writable && (
          <Command.Group className="mt-1 border-t border-border pt-1">
            <Command.Item
              value="create"
              onSelect={() => {
                onOpenChange(false);
                onCreate(query.trim());
              }}
              className={ITEM}
            >
              <Plus className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
              <span className="flex-1 truncate">{fill(t("memory_view.search_create"), { title: query.trim() })}</span>
              <CornerDownLeft className="h-3.5 w-3.5 text-foreground-faint" aria-hidden />
            </Command.Item>
          </Command.Group>
        )}
      </Command.List>
    </Command.Dialog>
  );
}
