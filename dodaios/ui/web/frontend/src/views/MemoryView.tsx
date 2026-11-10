/**
 * The Memory section: the personal memory vault (ADR-0044).
 *
 *   ┌──────────────┬──────────────────────────────────────────────────┐
 *   │ ● ● ●        │  [ Memories | Files | How it works ]   ⌕   +     │
 *   │ Library      ├───────────────────────────┬──────────────────────┤
 *   │  All         │ list of memories           │ inspector:           │
 *   │  In mind     │  (one sentence each)       │  the memory, where   │
 *   │  Pinned      │                            │  it came from, its   │
 *   │ Kinds        │                            │  versions, actions   │
 *   │  About you … │                            │                      │
 *   │ ─────        │                            │                      │
 *   │ export/import│                            │                      │
 *   └──────────────┴───────────────────────────┴──────────────────────┘
 *
 * "Files" shows the same memory as the Markdown files an export writes, with
 * a large preview; "How it works" draws what reaches the model and when.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Brain, FileText, History, Pin, Plus, Search, X } from "lucide-react";
import { fill, useLocaleChunk, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";
import { EmptyState } from "@/components/ui/empty-state";
import {
  MEMORY_KINDS,
  VAULT_KEYS,
  useVaultItems,
  useVaultOverview,
} from "@/lib/personalMemoryApi";
import { IN_MIND_STYLE, KIND_STYLE } from "@/components/memoryVault/kinds";
import { MemoryBrowser, type Shelf } from "@/components/memoryVault/MemoryBrowser";
import { MemoryFiles } from "@/components/memoryVault/MemoryFiles";
import { HowItWorks } from "@/components/memoryVault/HowItWorks";
import { NewMemorySheet } from "@/components/memoryVault/NewMemorySheet";
import { Portability } from "@/components/memoryVault/Portability";
import { LearningPause } from "@/components/memoryVault/LearningPause";

type Mode = "memories" | "files" | "how";

export function MemoryView(): JSX.Element {
  const t = useT();
  useLocaleChunk("memory");
  const name = useEventStore((s) => s.assistantName) || "Dodaios";
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<Mode>("memories");
  const [shelf, setShelf] = useState<Shelf>("all");
  const [query, setQuery] = useState("");
  const [adding, setAdding] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const overview = useVaultOverview();
  const items = useVaultItems(query, shelf === "history");

  const refresh = useCallback(() => queryClient.invalidateQueries({ queryKey: VAULT_KEYS.all }), [queryClient]);
  const notify = useCallback((message: string) => {
    setToast(message);
    window.setTimeout(() => setToast((current) => (current === message ? null : current)), 3200);
  }, []);

  // Cmd/Ctrl+N adds a memory, Cmd/Ctrl+F searches.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey)) return;
      const key = event.key.toLowerCase();
      if (key === "n") {
        event.preventDefault();
        setAdding(true);
      } else if (key === "f") {
        event.preventDefault();
        setMode("memories");
        document.getElementById("vault-search")?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const inMind = useMemo(() => new Set(overview.data?.in_mind_ids ?? []), [overview.data]);
  const stats = overview.data?.stats;
  const byKind = stats?.by_kind ?? {};
  const all = items.data?.items ?? [];
  const pinnedCount = all.filter((m) => m.pinned && m.current).length;

  if (overview.isError) {
    return (
      <div className="flex h-full items-center justify-center p-8">
        <EmptyState icon={<Brain />} title={t("vault.offline_title")} description={t("vault.offline_body")} />
      </div>
    );
  }

  const shelfTitle =
    shelf === "all"
      ? t("vault.shelf_all")
      : shelf === "in_mind"
        ? t("vault.shelf_in_mind")
        : shelf === "pinned"
          ? t("vault.shelf_pinned")
          : shelf === "history"
            ? t("vault.shelf_history")
            : t(`vault.kind_${shelf}`);

  return (
    <div data-testid="memory-vault-view" className="flex h-full min-h-0 flex-col p-3 sm:p-5">
      <div className="mx-auto flex min-h-0 w-full max-w-[1480px] flex-1 overflow-hidden rounded-2xl border border-border bg-card shadow-float">
        {/* Sidebar */}
        <aside className="hidden w-[232px] shrink-0 flex-col border-r border-border bg-sheen/[0.025] md:flex">
          <div className="flex items-center gap-2 px-4 pb-3 pt-4">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent/15 text-accent">
              <Brain className="h-4 w-4" />
            </span>
            <div className="min-w-0">
              <p className="truncate text-[13px] font-semibold text-foreground-strong">{t("vault.title")}</p>
              <p className="truncate text-[11px] text-muted-foreground">
                {stats ? fill(t("vault.count"), { count: stats.current }) : t("vault.loading")}
              </p>
            </div>
          </div>
          <nav className="min-h-0 flex-1 overflow-y-auto px-2 pb-3" aria-label={t("vault.title")}>
            <SidebarLabel>{t("vault.library")}</SidebarLabel>
            <SidebarItem
              active={mode === "memories" && shelf === "all"}
              icon={<Brain />}
              hue="220 9% 56%"
              label={t("vault.shelf_all")}
              count={stats?.current}
              onClick={() => {
                setMode("memories");
                setShelf("all");
              }}
            />
            <SidebarItem
              active={mode === "memories" && shelf === "in_mind"}
              icon={<IN_MIND_STYLE.icon />}
              hue={IN_MIND_STYLE.hue}
              label={t("vault.shelf_in_mind")}
              count={inMind.size}
              onClick={() => {
                setMode("memories");
                setShelf("in_mind");
              }}
            />
            <SidebarItem
              active={mode === "memories" && shelf === "pinned"}
              icon={<Pin />}
              hue="4 86% 58%"
              label={t("vault.shelf_pinned")}
              count={pinnedCount}
              onClick={() => {
                setMode("memories");
                setShelf("pinned");
              }}
            />
            <SidebarItem
              active={mode === "memories" && shelf === "history"}
              icon={<History />}
              hue="220 9% 56%"
              label={t("vault.shelf_history")}
              onClick={() => {
                setMode("memories");
                setShelf("history");
              }}
            />
            <SidebarItem
              active={mode === "files"}
              icon={<FileText />}
              hue="220 9% 56%"
              label={t("vault.shelf_files")}
              onClick={() => setMode("files")}
            />
            <SidebarLabel>{t("vault.kinds_label")}</SidebarLabel>
            {MEMORY_KINDS.filter((kind) => (byKind[kind] ?? 0) > 0 || shelf === kind).map((kind) => {
              const Icon = KIND_STYLE[kind].icon;
              return (
                <SidebarItem
                  key={kind}
                  active={mode === "memories" && shelf === kind}
                  icon={<Icon />}
                  hue={KIND_STYLE[kind].hue}
                  label={t(`vault.kind_${kind}`)}
                  count={byKind[kind] ?? 0}
                  onClick={() => {
                    setMode("memories");
                    setShelf(kind);
                  }}
                />
              );
            })}
          </nav>
          <LearningPause onError={notify} />
          <Portability onDone={(message) => void refresh().then(() => notify(message))} onError={notify} />
        </aside>

        {/* Main */}
        <section className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-14 shrink-0 items-center gap-3 border-b border-border px-4">
            <h1 className="hidden min-w-0 truncate text-[15px] font-semibold text-foreground-strong lg:block lg:w-[180px]">
              {mode === "memories" ? shelfTitle : mode === "files" ? t("vault.mode_files") : fill(t("vault.mode_how"), { name })}
            </h1>
            <Segmented
              value={mode}
              onChange={setMode}
              options={[
                { value: "memories", label: t("vault.mode_memories") },
                { value: "how", label: t("vault.mode_how_short") },
              ]}
            />
            <div className="ml-auto flex items-center gap-2">
              {mode === "memories" && (
                <label className="relative hidden items-center sm:flex">
                  <Search className="pointer-events-none absolute left-2.5 h-3.5 w-3.5 text-muted-foreground" />
                  <input
                    id="vault-search"
                    data-testid="vault-search"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder={t("vault.search_placeholder")}
                    aria-label={t("vault.search_placeholder")}
                    className="h-8 w-[200px] rounded-lg border border-border bg-sheen/[0.04] pl-8 pr-7 text-[13px] text-foreground placeholder:text-faint-foreground focus-visible:w-[260px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-safe:transition-[width]"
                  />
                  {query && (
                    <button
                      type="button"
                      aria-label={t("vault.clear_search")}
                      onClick={() => setQuery("")}
                      className="absolute right-2 text-muted-foreground hover:text-foreground"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  )}
                </label>
              )}
              <button
                type="button"
                data-testid="vault-add"
                onClick={() => setAdding(true)}
                title={t("vault.add_title")}
                aria-label={t("vault.add_title")}
                className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-accent px-3 text-[13px] font-medium text-accent-foreground shadow-sm hover:bg-accent/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <Plus className="h-4 w-4" />
                <span className="hidden sm:inline">{t("vault.add")}</span>
              </button>
            </div>
          </header>

          <div className="min-h-0 flex-1">
            {mode === "memories" && (
              <MemoryBrowser
                shelf={shelf}
                query={query}
                items={all}
                loading={items.isLoading}
                inMind={inMind}
                name={name}
                onChanged={refresh}
                notify={notify}
                onAdd={() => setAdding(true)}
              />
            )}
            {mode === "files" && <MemoryFiles />}
            {mode === "how" && overview.data && (
              <HowItWorks
                name={name}
                overview={overview.data}
                onShowInMind={() => {
                  setMode("memories");
                  setShelf("in_mind");
                }}
              />
            )}
          </div>
        </section>
      </div>

      <NewMemorySheet
        open={adding}
        name={name}
        onClose={() => setAdding(false)}
        onSaved={async (message) => {
          setAdding(false);
          await refresh();
          notify(message);
        }}
        onError={notify}
      />

      {toast && (
        <div
          role="status"
          className="pointer-events-none fixed bottom-8 left-1/2 z-[70] -translate-x-1/2 rounded-full border border-border bg-popover/95 px-4 py-2 text-[13px] text-popover-foreground shadow-float backdrop-blur"
        >
          {toast}
        </div>
      )}
    </div>
  );
}

function SidebarLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="px-2.5 pb-1 pt-4 text-[11px] font-semibold uppercase tracking-wide text-faint-foreground">{children}</p>
  );
}

function SidebarItem({
  active,
  icon,
  hue,
  label,
  count,
  onClick,
}: {
  active: boolean;
  icon: React.ReactNode;
  hue: string;
  label: string;
  count?: number;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex h-8 w-full items-center gap-2.5 rounded-lg px-2.5 text-left text-[13px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        active ? "bg-accent-soft text-foreground-strong" : "text-foreground hover:bg-sheen/[0.05]",
      )}
    >
      <span
        className="flex h-5 w-5 shrink-0 items-center justify-center rounded-md [&>svg]:h-3 [&>svg]:w-3"
        style={{ backgroundColor: `hsl(${hue} / 0.16)`, color: `hsl(${hue})` }}
      >
        {icon}
      </span>
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {count !== undefined && <span className="text-[11px] tabular-nums text-muted-foreground">{count}</span>}
    </button>
  );
}

function Segmented<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T;
  onChange: (value: T) => void;
  options: Array<{ value: T; label: string }>;
}) {
  return (
    <div role="tablist" className="flex h-8 items-center rounded-lg bg-sheen/[0.06] p-0.5">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="tab"
          aria-selected={value === option.value}
          data-testid={`vault-mode-${option.value}`}
          onClick={() => onChange(option.value)}
          className={cn(
            "h-7 whitespace-nowrap rounded-md px-3 text-[12px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            value === option.value
              ? "bg-surface-raised text-foreground-strong shadow-sm"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

