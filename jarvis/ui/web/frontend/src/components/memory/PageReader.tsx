/**
 * One memory page: a document column and a rail of everything it connects to.
 *
 *   ┌──────────────────────────────────────────┬─────────────────┐
 *   │ Area › Title                    actions  │ Linked from     │
 *   │ Title                                    │ Links to        │
 *   │ kind · updated · words                   │ Mentioned in    │
 *   │                                          │ Related         │
 *   │ body / notebook entries / empty state    │ Properties      │
 *   └──────────────────────────────────────────┴─────────────────┘
 *
 * Agent notebooks render as their entries, with the agent's other pages one
 * click away; a page without a sentence of content says so instead of
 * showing an empty sheet.
 */
import { useCallback, useMemo, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  ChevronRight,
  Copy,
  ExternalLink,
  FileQuestion,
  Network,
  PencilLine,
  TextCursorInput,
} from "lucide-react";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { buildObsidianUrl } from "@/lib/obsidian";
import {
  MEMORY_KEYS,
  archiveMemoryPage,
  renameMemoryPage,
  saveMemoryPage,
  useMemoryPage,
  type LinkRef,
  type MemoryIndex,
  type MemoryPage,
  type NotebookEntry,
  type PageRef,
} from "@/lib/memoryApi";
import {
  GROUP_LABEL_KEY,
  HIDDEN_PROPERTIES,
  KIND_LABEL_KEY,
  areaOf,
  formatProperty,
  countText,
  prepareBody,
  relativeAge,
  type MemoryArea,
} from "@/lib/memoryModel";
import { EmptyState } from "@/components/ui/empty-state";
import { Button } from "@/components/ui/button";
import { KindIcon } from "./KindIcon";
import { MarkdownBody } from "./MarkdownBody";
import { PageEditor } from "./PageEditor";
import { ConfirmDialog, RenameDialog } from "./MemoryDialogs";

export function PageReader({
  path,
  index,
  language,
  onOpen,
  onArea,
  onShowOnMap,
  onCreate,
  onArchived,
  notify,
}: {
  path: string;
  index: MemoryIndex | undefined;
  language: string;
  onOpen: (path: string) => void;
  onArea: (area: MemoryArea) => void;
  onShowOnMap: (path: string) => void;
  onCreate: (title: string) => void;
  onArchived: () => void;
  notify: (message: string) => void;
}) {
  const t = useT();
  const queryClient = useQueryClient();
  const pageQuery = useMemoryPage(path);
  const page = pageQuery.data;
  const [editing, setEditing] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [archiving, setArchiving] = useState(false);

  const refresh = useCallback(
    () => queryClient.invalidateQueries({ queryKey: MEMORY_KEYS.all }),
    [queryClient],
  );

  if (pageQuery.isLoading) return <ReaderSkeleton />;
  if (pageQuery.isError || !page) {
    return (
      <div className="flex flex-1 items-center justify-center p-8">
        <EmptyState
          icon={<FileQuestion />}
          title={t("memory_view.page_missing_title")}
          description={pageQuery.error instanceof Error ? pageQuery.error.message : t("memory_view.page_missing_body")}
        />
      </div>
    );
  }

  const area = areaOf(page);
  const agentPages = page.agent_id
    ? (index?.pages ?? []).filter((item) => item.agent_id === page.agent_id)
    : [];

  return (
    <div className="flex min-h-0 flex-1" data-testid="memory-reader" data-path={page.path}>
      <div className="min-w-0 flex-1 overflow-y-auto">
        <article className="mx-auto w-full max-w-[760px] px-8 pb-24 pt-6 lg:px-12">
          <nav aria-label={t("memory_view.breadcrumb")} className="flex min-w-0 items-center gap-1 text-sm text-muted-foreground">
            <button type="button" onClick={() => onArea(area)} className="truncate rounded px-1 py-0.5 hover:bg-secondary hover:text-foreground">
              {area === "agents" ? t("memory_view.area_agents") : t(`memory_view.area_${area}`)}
            </button>
            {page.agent && (
              <>
                <ChevronRight className="h-3.5 w-3.5 shrink-0 text-foreground-faint" aria-hidden />
                <span className="truncate px-1">{page.agent.name}</span>
              </>
            )}
          </nav>

          <header className="mt-5">
            <div className="flex items-start gap-4">
              <h1 className="min-w-0 flex-1 text-[28px] font-semibold leading-tight tracking-tight text-foreground-strong" data-testid="memory-page-title">
                {page.title}
              </h1>
              <PageActions
                page={page}
                vaultRoot={index?.vault_root ?? ""}
                writable={index?.writable ?? false}
                onEdit={() => setEditing(true)}
                onRename={() => setRenaming(true)}
                onArchive={() => setArchiving(true)}
                onShowOnMap={() => onShowOnMap(page.path)}
                notify={notify}
              />
            </div>
            <MetaLine page={page} language={language} />
            {(page.aliases.length > 0 || page.tags.length > 0) && (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {page.aliases.map((alias) => (
                  <span key={`a-${alias}`} className="rounded-md bg-secondary px-2 py-0.5 text-xs text-foreground-secondary">
                    {alias}
                  </span>
                ))}
                {page.tags.map((tag) => (
                  <span key={`t-${tag}`} className="rounded-md border border-border px-2 py-0.5 text-xs text-muted-foreground">
                    #{tag}
                  </span>
                ))}
              </div>
            )}
          </header>

          {agentPages.length > 1 && (
            <AgentTabs current={page.path} pages={agentPages} onOpen={onOpen} />
          )}

          <div className="mt-8">
            {editing ? (
              <PageEditor
                initialBody={page.body_md.replace(/^\s+/, "")}
                pages={index?.pages ?? []}
                onCancel={() => setEditing(false)}
                onSave={async (body) => {
                  await saveMemoryPage(page.path, body, page.mtime);
                  await refresh();
                  setEditing(false);
                  notify(t("memory_view.saved"));
                }}
                renderPreview={(body) => (
                  <MarkdownBody markdown={prepareBody(body, page.title, page.outgoing)} onOpen={onOpen} onCreate={onCreate} />
                )}
              />
            ) : (
              <PageBody page={page} onOpen={onOpen} onCreate={onCreate} onEdit={() => setEditing(true)} writable={Boolean(index?.writable)} />
            )}
          </div>
          {!editing && <ConnectionsRail page={page} onOpen={onOpen} inline />}
        </article>
      </div>

      <ConnectionsRail page={page} onOpen={onOpen} />

      <RenameDialog
        open={renaming}
        currentTitle={page.title}
        onClose={() => setRenaming(false)}
        onRename={async (title) => {
          const result = await renameMemoryPage(page.path, title);
          await refresh();
          setRenaming(false);
          const done =
            result.links_rewritten > 0
              ? fill(t("memory_view.renamed_links"), { count: result.links_rewritten })
              : t("memory_view.renamed");
          notify(
            result.links_unrewritten > 0
              ? `${done} ${fill(t("memory_view.renamed_unrewritten"), { count: result.links_unrewritten })}`
              : done,
          );
          if (result.path !== page.path) onOpen(result.path);
        }}
      />
      <ConfirmDialog
        open={archiving}
        title={fill(t("memory_view.archive_title"), { title: page.title })}
        description={t("memory_view.archive_body")}
        confirmLabel={t("memory_view.archive")}
        onClose={() => setArchiving(false)}
        onConfirm={async () => {
          await archiveMemoryPage(page.path);
          await refresh();
          setArchiving(false);
          notify(t("memory_view.archived"));
          onArchived();
        }}
      />
    </div>
  );
}

function MetaLine({ page, language }: { page: MemoryPage; language: string }) {
  const t = useT();
  const parts: ReactNode[] = [
    <span key="kind" className="inline-flex items-center gap-1.5">
      <KindIcon kind={page.kind} className="h-3.5 w-3.5" />
      {t(KIND_LABEL_KEY[page.kind])}
    </span>,
  ];
  if (page.agent && page.agent.state !== "active") {
    parts.push(
      <span key="state" className="rounded bg-secondary px-1.5 py-px text-xs text-muted-foreground">
        {t(`memory_view.agent_${page.agent.state}`)}
      </span>,
    );
  }
  const age = relativeAge(page.mtime, language);
  if (age) parts.push(<span key="age">{fill(t("memory_view.updated"), { age })}</span>);
  if (page.entries.length > 0) {
    parts.push(<span key="entries">{countText(t, "memory_view.entries_count", page.entries.length)}</span>);
  } else if (page.words > 0) {
    parts.push(<span key="words">{countText(t, "memory_view.words_count", page.words)}</span>);
  }
  return (
    <div className="mt-2 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-sm text-muted-foreground" data-testid="memory-meta">
      {parts.map((part, i) => (
        <span key={i} className="inline-flex items-center gap-2.5">
          {i > 0 && <span className="text-foreground-faint" aria-hidden>·</span>}
          {part}
        </span>
      ))}
    </div>
  );
}

function PageActions({
  page,
  vaultRoot,
  writable,
  onEdit,
  onRename,
  onArchive,
  onShowOnMap,
  notify,
}: {
  page: MemoryPage;
  vaultRoot: string;
  writable: boolean;
  onEdit: () => void;
  onRename: () => void;
  onArchive: () => void;
  onShowOnMap: () => void;
  notify: (message: string) => void;
}) {
  const t = useT();
  return (
    <div className="flex shrink-0 items-center gap-0.5 pt-1">
      {page.editable && writable && (
        <Button variant="secondary" size="sm" onClick={onEdit} data-testid="memory-edit">
          <PencilLine aria-hidden />
          {t("memory_view.edit")}
        </Button>
      )}
      {!page.empty && <IconAction label={t("memory_view.show_on_map")} onClick={onShowOnMap} icon={<Network />} />}
      {vaultRoot && (
        <IconAction
          label={t("memory_view.open_obsidian")}
          icon={<ExternalLink />}
          onClick={() => {
            window.location.href = buildObsidianUrl(vaultRoot, page.path);
          }}
        />
      )}
      <IconAction
        label={t("memory_view.copy_path")}
        icon={<Copy />}
        onClick={() => {
          void navigator.clipboard?.writeText(page.path).then(
            () => notify(t("memory_view.copied")),
            () => notify(page.path),
          );
        }}
      />
      {page.group === "knowledge" && writable && (
        <IconAction label={t("memory_view.rename")} icon={<TextCursorInput />} onClick={onRename} />
      )}
      {page.archivable && writable && <IconAction label={t("memory_view.archive")} icon={<Archive />} onClick={onArchive} />}
    </div>
  );
}

function IconAction({ label, icon, onClick }: { label: string; icon: JSX.Element; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className="grid h-8 w-8 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&>svg]:h-4 [&>svg]:w-4"
    >
      {icon}
    </button>
  );
}

function AgentTabs({
  current,
  pages,
  onOpen,
}: {
  current: string;
  pages: { path: string; title: string; kind: string; empty: boolean; mtime: number }[];
  onOpen: (path: string) => void;
}) {
  const t = useT();
  const order = (kind: string) => (kind === "memory" ? 0 : kind === "profile" ? 1 : 2);
  const sorted = [...pages].sort((a, b) => order(a.kind) - order(b.kind) || b.mtime - a.mtime);
  return (
    <div className="mt-6 flex gap-1 overflow-x-auto border-b border-border [scrollbar-width:none]" role="tablist" aria-label={t("memory_view.agent_pages")}>
      {sorted.map((item) => {
        const active = item.path === current;
        const label =
          item.kind === "memory" ? t("memory_view.kind_memory") : item.kind === "profile" ? t("memory_view.kind_profile") : item.title;
        return (
          <button
            key={item.path}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onOpen(item.path)}
            className={cn(
              "-mb-px max-w-[220px] shrink-0 truncate border-b-2 px-3 pb-2 pt-1 text-sm transition-colors",
              active ? "border-accent font-medium text-foreground-strong" : "border-transparent text-muted-foreground hover:text-foreground",
              item.empty && !active && "text-foreground-faint",
            )}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}

function PageBody({
  page,
  onOpen,
  onCreate,
  onEdit,
  writable,
}: {
  page: MemoryPage;
  onOpen: (path: string) => void;
  onCreate: (title: string) => void;
  onEdit: () => void;
  writable: boolean;
}) {
  const t = useT();
  const markdown = useMemo(() => prepareBody(page.body_md, page.title, page.outgoing), [page]);

  if (page.kind === "memory" || page.kind === "profile") {
    if (page.entries.length === 0) {
      return (
        <EmptyState
          icon={<KindIcon kind={page.kind} />}
          title={t(page.kind === "memory" ? "memory_view.notebook_empty_memory" : "memory_view.notebook_empty_profile")}
          description={fill(t("memory_view.notebook_empty_body"), { agent: page.agent?.name ?? page.title })}
        />
      );
    }
    return <EntryList entries={page.entries} outgoing={page} onOpen={onOpen} onCreate={onCreate} />;
  }

  if (page.empty || !markdown) {
    return (
      <EmptyState
        icon={<KindIcon kind={page.kind} />}
        title={t("memory_view.page_empty_title")}
        description={t(page.editable ? "memory_view.page_empty_editable" : "memory_view.page_empty_body")}
        actions={
          page.editable && writable ? (
            <Button size="sm" onClick={onEdit}>
              <PencilLine aria-hidden />
              {t("memory_view.write_page")}
            </Button>
          ) : undefined
        }
      />
    );
  }

  return <MarkdownBody markdown={markdown} onOpen={onOpen} onCreate={onCreate} />;
}

const KNOWN_ORIGINS = new Set(["agent", "tool", "user", "review"]);

function EntryList({
  entries,
  outgoing,
  onOpen,
  onCreate,
}: {
  entries: NotebookEntry[];
  outgoing: MemoryPage;
  onOpen: (path: string) => void;
  onCreate: (title: string) => void;
}) {
  const t = useT();
  const sorted = [...entries].sort((a, b) => b.importance - a.importance);
  return (
    <ol className="flex flex-col divide-y divide-border rounded-xl border border-border" data-testid="memory-entries">
      {sorted.map((entry) => (
        <li key={entry.id} className="px-5 py-4">
          <div className="mb-1.5 flex items-center gap-2 text-xs text-foreground-faint">
            {entry.importance >= 8 && (
              <span className="rounded bg-accent-soft px-1.5 py-px font-medium text-accent">{t("memory_view.important")}</span>
            )}
            <span>{KNOWN_ORIGINS.has(entry.origin) ? t(`memory_view.origin_${entry.origin}`) : entry.origin}</span>
          </div>
          <div className="[&_p:first-child]:mt-0 [&_p:last-child]:mb-0 [&_p]:my-2 [&_ul]:my-2">
            <MarkdownBody markdown={prepareBody(entry.text, "", outgoing.outgoing)} onOpen={onOpen} onCreate={onCreate} />
          </div>
        </li>
      ))}
    </ol>
  );
}

// ----------------------------------------------------------------- the rail

function ConnectionsRail({
  page,
  onOpen,
  inline = false,
}: {
  page: MemoryPage;
  onOpen: (path: string) => void;
  inline?: boolean;
}) {
  const t = useT();
  const outgoing = dedupe(
    page.outgoing
      .filter((link) => link.path)
      .map((link): PageRef => ({ path: link.path as string, title: link.title, kind: link.kind, group: null, empty: false })),
  );
  const broken = page.outgoing.filter((link) => link.broken);
  const properties = Object.entries(page.properties).filter(
    ([key, value]) => !HIDDEN_PROPERTIES.has(key) && formatProperty(value) !== "",
  );
  const total = page.backlinks.length + outgoing.length + page.mentioned_in.length + page.mentions.length + page.related.length;

  return (
    <aside
      className={cn(
        inline
          ? "mt-12 flex flex-col border-t border-border pt-8 lg:hidden"
          : "hidden w-[296px] shrink-0 flex-col overflow-y-auto border-l border-border bg-sidebar/60 lg:flex",
      )}
      aria-label={t("memory_view.connections")}
      data-testid={inline ? "memory-rail-inline" : "memory-rail"}
    >
      <div className={cn("flex flex-col gap-6", !inline && "px-4 pb-10 pt-6")}>
        {total === 0 && (
          <p className="text-sm leading-relaxed text-muted-foreground">{t("memory_view.no_connections")}</p>
        )}
        <RailSection title={t("memory_view.linked_from")} items={page.backlinks} onOpen={onOpen} testId="rail-backlinks" />
        <RailSection title={t("memory_view.links_to")} items={outgoing} onOpen={onOpen} testId="rail-outgoing" />
        <RailSection
          title={t("memory_view.mentioned_in")}
          hint={t("memory_view.mentioned_in_hint")}
          items={page.mentioned_in}
          onOpen={onOpen}
          testId="rail-mentioned-in"
        />
        <RailSection title={t("memory_view.mentions")} items={page.mentions} onOpen={onOpen} testId="rail-mentions" />
        <RailSection
          title={t("memory_view.related")}
          hint={t("memory_view.related_hint")}
          items={page.related.map((item) => ({
            ...item,
            context: item.via ? fill(t("memory_view.related_via"), { title: item.via.title }) : "",
          }))}
          onOpen={onOpen}
          testId="rail-related"
        />
        {broken.length > 0 && (
          <section>
            <RailHeading title={t("memory_view.unresolved_links")} count={broken.length} />
            <ul className="mt-2 flex flex-wrap gap-1.5">
              {broken.map((link) => (
                <li key={link.raw} className="rounded-md border border-dashed border-border px-2 py-0.5 text-xs text-muted-foreground">
                  {link.title}
                </li>
              ))}
            </ul>
          </section>
        )}
        {properties.length > 0 && (
          <section>
            <RailHeading title={t("memory_view.properties")} />
            <dl className="mt-2 flex flex-col gap-2 text-sm">
              {properties.map(([key, value]) => (
                <div key={key} className="grid grid-cols-[96px_1fr] gap-2">
                  <dt className="truncate text-muted-foreground" title={key}>
                    {key}
                  </dt>
                  <dd className="min-w-0 break-words text-foreground">{formatProperty(value)}</dd>
                </div>
              ))}
            </dl>
          </section>
        )}
        <section>
          <RailHeading title={t("memory_view.file")} />
          <p className="mt-2 break-all font-mono text-xs leading-5 text-muted-foreground">{page.path}</p>
          <p className="mt-1 text-xs text-foreground-faint">{t(GROUP_LABEL_KEY[page.group])}</p>
        </section>
      </div>
    </aside>
  );
}

function dedupe<T extends { path: string }>(items: T[]): T[] {
  const seen = new Set<string>();
  return items.filter((item) => (seen.has(item.path) ? false : (seen.add(item.path), true)));
}

function RailHeading({ title, count }: { title: string; count?: number }) {
  return (
    <h3 className="flex items-center justify-between text-xs font-medium uppercase tracking-wide text-muted-foreground">
      <span>{title}</span>
      {count !== undefined && <span className="tabular-nums text-foreground-faint">{count}</span>}
    </h3>
  );
}

const RAIL_LIMIT = 8;

function RailSection({
  title,
  hint,
  items,
  onOpen,
  testId,
}: {
  title: string;
  hint?: string;
  items: (PageRef & Partial<Pick<LinkRef, "context">>)[];
  onOpen: (path: string) => void;
  testId: string;
}) {
  const t = useT();
  const [expanded, setExpanded] = useState(false);
  if (items.length === 0) return null;
  const shown = expanded ? items : items.slice(0, RAIL_LIMIT);
  return (
    <section data-testid={testId}>
      <RailHeading title={title} count={items.length} />
      {hint && <p className="mt-1 text-xs leading-snug text-foreground-faint">{hint}</p>}
      <ul className="mt-2 flex flex-col gap-0.5">
        {shown.map((item) => (
          <li key={item.path}>
            <button
              type="button"
              onClick={() => onOpen(item.path)}
              className="group flex w-full flex-col gap-0.5 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-secondary"
            >
              <span className="flex min-w-0 items-center gap-2 text-sm text-foreground">
                <KindIcon kind={item.kind} className="h-3.5 w-3.5 text-muted-foreground" />
                <span className={cn("truncate", item.empty && "text-muted-foreground")}>{item.title}</span>
              </span>
              {item.context && (
                <span className="line-clamp-2 pl-[22px] text-xs leading-snug text-muted-foreground">{item.context}</span>
              )}
            </button>
          </li>
        ))}
      </ul>
      {items.length > RAIL_LIMIT && (
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          className="mt-1 px-2 text-xs text-muted-foreground hover:text-foreground"
        >
          {expanded ? t("memory_view.show_less") : fill(t("memory_view.show_all"), { count: items.length })}
        </button>
      )}
    </section>
  );
}

function ReaderSkeleton() {
  return (
    <div className="mx-auto w-full max-w-[760px] space-y-4 px-12 pt-12" role="status" aria-busy="true">
      <div className="h-3 w-32 animate-pulse rounded bg-secondary" />
      <div className="h-8 w-80 animate-pulse rounded-md bg-secondary" />
      <div className="h-3 w-56 animate-pulse rounded bg-secondary" />
      <div className="space-y-3 pt-6">
        <div className="h-3 w-full animate-pulse rounded bg-secondary" />
        <div className="h-3 w-5/6 animate-pulse rounded bg-secondary" />
        <div className="h-3 w-4/6 animate-pulse rounded bg-secondary" />
      </div>
    </div>
  );
}
