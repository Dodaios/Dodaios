/**
 * The Memory section: what the assistant and its agents remember, as linked
 * Markdown pages in the Obsidian vault.
 *
 *   ┌────────────┬────────────────────────────────────────────────┐
 *   │ navigation │  toolbar: back · title          health · vault │
 *   │ search     ├────────────────────────────────────────────────┤
 *   │ areas      │  overview | area list | agents | page | map    │
 *   │ agents     │                                                │
 *   └────────────┴────────────────────────────────────────────────┘
 *
 * Pages are addressed by vault path everywhere (`/api/wiki/index`, `/read`,
 * `/map`), so two files that share a name are never confused again.
 */
import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, BookOpen, FileText, FolderKanban, Lightbulb, Settings2, Shapes } from "lucide-react";
import { fill, useLocaleChunk, useT } from "@/i18n";
import { useRunLocale } from "@/components/runs/format";
import { useEventStore } from "@/store/events";
import { useWikiLive } from "@/hooks/useWikiLive";
import {
  MEMORY_KEYS,
  createMemoryPage,
  tidyMemory,
  useMemoryIndex,
  type MemoryPageSummary,
} from "@/lib/memoryApi";
import { KNOWLEDGE_AREAS, SYSTEM_AREA, type MemoryArea } from "@/lib/memoryModel";
import { EmptyState } from "@/components/ui/empty-state";
import { MemoryNav, type NavTarget } from "@/components/memory/MemoryNav";
import { MemoryHome } from "@/components/memory/MemoryHome";
import { PageList } from "@/components/memory/PageList";
import { AgentDirectory } from "@/components/memory/AgentDirectory";
import { PageReader } from "@/components/memory/PageReader";
import { MemorySearch } from "@/components/memory/MemorySearch";
import { MemoryHealth } from "@/components/memory/MemoryHealth";
import { ConfirmDialog, NewPageDialog, type CreatableKind } from "@/components/memory/MemoryDialogs";
import { ObsidianStatus } from "@/components/wiki/ObsidianStatus";
import { ObsidianSetupDialog } from "@/components/wiki/ObsidianSetupDialog";
import type { ObsidianStatus as ObsidianStatusType } from "@/types/setup";

// The force-directed map pulls in its own canvas engine; load it on first use.
const MemoryMap = lazy(() => import("@/components/memory/MemoryMap"));

type Route =
  | { view: "home" }
  | { view: "map"; focus: string | null }
  | { view: "area"; area: MemoryArea }
  | { view: "page"; path: string };

const AREA_ICONS: Record<string, JSX.Element> = {
  entities: <Shapes />,
  projects: <FolderKanban />,
  concepts: <Lightbulb />,
  journal: <FileText />,
  system: <Settings2 />,
};

function sameRoute(a: Route, b: Route): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

export function MemoryView(): JSX.Element {
  const t = useT();
  useLocaleChunk("memory");
  const language = useRunLocale();
  useWikiLive();
  const queryClient = useQueryClient();
  const indexQuery = useMemoryIndex();
  const index = indexQuery.data;

  const [history, setHistory] = useState<Route[]>([{ view: "home" }]);
  const route = history[history.length - 1];
  const [searchOpen, setSearchOpen] = useState(false);
  const [creating, setCreating] = useState<{ title: string; kind: CreatableKind } | null>(null);
  const [tidy, setTidy] = useState<string[] | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [setupHint, setSetupHint] = useState<ObsidianStatusType | null>(null);

  const go = useCallback((next: Route) => {
    setHistory((stack) => (sameRoute(stack[stack.length - 1], next) ? stack : [...stack.slice(-30), next]));
  }, []);
  const back = useCallback(() => setHistory((stack) => (stack.length > 1 ? stack.slice(0, -1) : stack)), []);
  const openPage = useCallback((path: string) => go({ view: "page", path }), [go]);

  const notify = useCallback((message: string) => {
    setToast(message);
    window.setTimeout(() => setToast((current) => (current === message ? null : current)), 3200);
  }, []);

  // Ctrl/Cmd+K opens search while the section is on screen.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setSearchOpen((value) => !value);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Another section asked for a page by name (a contact's wiki link, say).
  const pageRequest = useEventStore((s) => s.wikiPageRequest);
  useEffect(() => {
    if (!pageRequest || !index) return;
    const wanted = pageRequest.slug.replace(/\\/g, "/").replace(/\.md$/i, "").toLowerCase();
    const match =
      index.pages.find((page) => page.path.replace(/\.md$/i, "").toLowerCase() === wanted) ??
      index.pages.find((page) => page.group === "knowledge" && page.slug.toLowerCase() === wanted.split("/").pop()) ??
      index.pages.find((page) => page.slug.toLowerCase() === wanted.split("/").pop());
    if (match) openPage(match.path);
    else notify(t("memory_view.page_missing_title"));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- answer each request once, when the index is there
  }, [pageRequest?.seq, Boolean(index)]);

  // First visit: walk through the Obsidian setup when it still needs a step.
  useEffect(() => {
    const controller = new AbortController();
    (async () => {
      try {
        const [statusResp, stateResp] = await Promise.all([
          fetch("/api/setup/obsidian/status", { signal: controller.signal }),
          fetch("/api/setup/state", { signal: controller.signal }),
        ]);
        if (!statusResp.ok || !stateResp.ok) return;
        const status = (await statusResp.json()) as ObsidianStatusType;
        const state = (await stateResp.json()) as { obsidian_setup_seen: boolean };
        if (state.obsidian_setup_seen === false && status.recommended_action !== "ok") setSetupHint(status);
      } catch (err) {
        if ((err as { name?: string })?.name !== "AbortError") console.debug("[MemoryView] setup probe failed:", err);
      }
    })();
    return () => controller.abort();
  }, []);

  const navigate = useCallback(
    (target: NavTarget) => {
      if (target.view === "home") go({ view: "home" });
      else if (target.view === "map") go({ view: "map", focus: null });
      else if (target.view === "area") go({ view: "area", area: target.area });
      else {
        const agent = index?.agents.find((item) => item.agent_id === target.agentId);
        const pages = (agent?.pages ?? [])
          .map((path) => index?.pages.find((page) => page.path === path))
          .filter((page): page is MemoryPageSummary => Boolean(page));
        const first =
          pages.find((page) => page.kind === "memory" && !page.empty) ??
          pages.find((page) => page.kind === "profile" && !page.empty) ??
          pages.find((page) => !page.empty) ??
          pages[0];
        if (first) openPage(first.path);
      }
    },
    [go, index, openPage],
  );

  const createPage = useCallback(
    async (kind: CreatableKind, title: string) => {
      const result = await createMemoryPage(kind, title);
      await queryClient.invalidateQueries({ queryKey: MEMORY_KEYS.all });
      setCreating(null);
      notify(fill(t("memory_view.created"), { title }));
      openPage(result.path);
    },
    [notify, openPage, queryClient, t],
  );

  const startTidy = useCallback(async () => {
    try {
      const preview = await tidyMemory(true);
      if (preview.count === 0) notify(t("memory_view.tidy_nothing"));
      else setTidy(preview.paths);
    } catch (err) {
      notify(err instanceof Error ? err.message : String(err));
    }
  }, [notify, t]);

  const currentPage = route.view === "page" ? index?.pages.find((page) => page.path === route.path) : undefined;
  const activeNav: NavTarget["view"] | MemoryArea | null =
    route.view === "page"
      ? currentPage?.group === "agents"
        ? "agents"
        : null
      : route.view === "area"
        ? route.area
        : route.view;

  const obsidian = useMemo(
    () => <ObsidianStatus onOpenSetup={(status) => setSetupHint(status)} />,
    [],
  );

  const toolbarTitle =
    route.view === "page"
      ? currentPage?.title ?? ""
      : route.view === "area"
        ? route.area === "agents"
          ? t("memory_view.area_agents")
          : t(`memory_view.area_${route.area}`)
        : route.view === "map"
          ? t("memory_view.map")
          : t("memory_view.overview");

  return (
    <div className="flex h-full min-h-0 bg-sidebar" data-testid="memory-view">
      <MemoryNav
        index={index}
        active={activeNav}
        activeAgentId={currentPage?.agent_id ?? null}
        onNavigate={navigate}
        onSearch={() => setSearchOpen(true)}
        onNewPage={() => setCreating({ title: "", kind: "entity" })}
      />

      <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-tl-xl border-l border-t border-border bg-background">
        <div className="flex h-11 shrink-0 items-center gap-2 border-b border-border px-3">
          <button
            type="button"
            onClick={back}
            disabled={history.length < 2}
            aria-label={t("memory_view.back")}
            title={t("memory_view.back")}
            className="grid h-8 w-8 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground disabled:pointer-events-none disabled:opacity-30"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden />
          </button>
          <span className="min-w-0 truncate text-sm font-medium text-foreground" data-testid="memory-toolbar-title">
            {toolbarTitle}
          </span>
          <div className="ml-auto flex items-center gap-1">
            <MemoryHealth />
            {obsidian}
          </div>
        </div>

        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          {indexQuery.isLoading ? (
            <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground" role="status">
              {t("memory_view.loading")}
            </div>
          ) : indexQuery.isError || !index ? (
            <div className="flex flex-1 items-center justify-center p-8">
              <EmptyState
                icon={<BookOpen />}
                title={t("memory_view.load_error_title")}
                description={indexQuery.error instanceof Error ? indexQuery.error.message : t("memory_view.load_error_body")}
              />
            </div>
          ) : route.view === "page" ? (
            <PageReader
              key={route.path}
              path={route.path}
              index={index}
              language={language}
              onOpen={openPage}
              onArea={(area) => go({ view: "area", area })}
              onShowOnMap={(path) => go({ view: "map", focus: path })}
              onCreate={(title) => setCreating({ title, kind: "entity" })}
              onArchived={back}
              notify={notify}
            />
          ) : route.view === "map" ? (
            <Suspense fallback={<div className="flex-1" />}>
              <MemoryMap focus={route.focus} onOpen={openPage} />
            </Suspense>
          ) : (
            <div className="min-h-0 flex-1 overflow-y-auto">
              {route.view === "home" ? (
                <MemoryHome
                  index={index}
                  language={language}
                  onOpen={openPage}
                  onNewPage={() => setCreating({ title: "", kind: "entity" })}
                  onShowAgents={() => go({ view: "area", area: "agents" })}
                />
              ) : route.area === "agents" ? (
                <AgentDirectory index={index} language={language} onOpen={openPage} onTidy={() => void startTidy()} />
              ) : (
                <AreaList
                  area={route.area}
                  pages={index.pages}
                  language={language}
                  onOpen={openPage}
                  onNew={
                    index.writable && route.area !== "system" && route.area !== "journal"
                      ? () =>
                          setCreating({
                            title: "",
                            kind: route.area === "projects" ? "project" : route.area === "concepts" ? "concept" : "entity",
                          })
                      : undefined
                  }
                />
              )}
            </div>
          )}
        </div>
      </main>

      <MemorySearch
        open={searchOpen}
        onOpenChange={setSearchOpen}
        index={index}
        onOpen={openPage}
        onCreate={(title) => setCreating({ title, kind: "entity" })}
      />
      <NewPageDialog
        open={creating !== null}
        initialTitle={creating?.title ?? ""}
        initialKind={creating?.kind ?? "entity"}
        onClose={() => setCreating(null)}
        onCreate={createPage}
      />
      <ConfirmDialog
        open={tidy !== null}
        title={fill(t("memory_view.tidy_title"), { count: tidy?.length ?? 0 })}
        description={t("memory_view.tidy_body")}
        confirmLabel={t("memory_view.tidy_confirm")}
        items={tidy ?? []}
        onClose={() => setTidy(null)}
        onConfirm={async () => {
          const result = await tidyMemory(false);
          await queryClient.invalidateQueries({ queryKey: MEMORY_KEYS.all });
          setTidy(null);
          notify(fill(t("memory_view.tidy_done"), { count: result.count }));
        }}
      />
      {setupHint && (
        <ObsidianSetupDialog
          open
          onClose={() => setSetupHint(null)}
          initialStatus={setupHint}
          onComplete={async () => {
            try {
              await fetch("/api/setup/state/obsidian-seen", { method: "POST" });
            } catch (err) {
              console.debug("[MemoryView] mark-obsidian-seen failed:", err);
            }
          }}
        />
      )}
      {toast && (
        <div
          role="status"
          data-testid="memory-toast"
          className="pointer-events-none fixed bottom-10 right-6 z-[110] max-w-sm rounded-lg border border-border bg-popover px-4 py-3 text-sm text-foreground shadow-float"
        >
          {toast}
        </div>
      )}
    </div>
  );
}

function AreaList({
  area,
  pages,
  language,
  onOpen,
  onNew,
}: {
  area: MemoryArea;
  pages: MemoryPageSummary[];
  language: string;
  onOpen: (path: string) => void;
  onNew?: () => void;
}) {
  const t = useT();
  const def = [...KNOWLEDGE_AREAS, SYSTEM_AREA].find((item) => item.id === area) ?? KNOWLEDGE_AREAS[0];
  const inArea = pages.filter((page) => def.matches(page));
  return (
    <PageList
      title={t(def.labelKey)}
      description={t(def.descriptionKey)}
      pages={inArea}
      language={language}
      onOpen={onOpen}
      emptyIcon={AREA_ICONS[area] ?? <BookOpen />}
      emptyTitle={t("memory_view.area_empty_title")}
      emptyBody={t(`memory_view.area_${area}_empty`)}
      actions={
        onNew ? (
          <button
            type="button"
            onClick={onNew}
            className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border px-3 text-sm font-medium text-foreground transition-colors hover:bg-secondary"
          >
            {t("memory_view.new_page")}
          </button>
        ) : undefined
      }
    />
  );
}
