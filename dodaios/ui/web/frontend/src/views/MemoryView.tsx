/**
 * The Memory section: the personal memory vault (ADR-0044).
 *
 *   ┌──────────────────────────────────────────────┬──────────────────┐
 *   │ Memory · what the assistant knows about you  │ Always in mind   │
 *   │ [ tell me something to remember …    ][Save] │ (the prompt      │
 *   │ search · kind chips · history                │  block, verbatim)│
 *   │ About you ──────────────────────────────     │ Recent changes   │
 *   │  sentence                    pin edit end ✕  │ Take it with you │
 *   │ People ─────────────────────────────────     │  export · import │
 *   └──────────────────────────────────────────────┴──────────────────┘
 *
 * Every row is one atomic memory. An edit is a new version (the old one
 * stays in the history), "no longer true" closes it with a date, and
 * forgetting erases every version.
 */
import { useCallback, useMemo, useRef, useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  Brain,
  Check,
  CircleOff,
  Download,
  History,
  Loader2,
  Pencil,
  Pin,
  PinOff,
  Search,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { fill, useLocaleChunk, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { BrandedSelect } from "@/components/ui/select";
import { ConfirmDialog } from "@/components/memory/MemoryDialogs";
import {
  MEMORY_KINDS,
  VAULT_KEYS,
  addMemory,
  editMemory,
  endMemory,
  exportUrl,
  forgetMemory,
  importBundle,
  pinMemory,
  useVaultActivity,
  useVaultHistory,
  useVaultItems,
  useVaultOverview,
  type MemoryKind,
  type VaultMemory,
} from "@/lib/personalMemoryApi";

type Filter = MemoryKind | "all";

function day(stamp: string | null | undefined): string {
  if (!stamp) return "";
  const date = new Date(stamp);
  if (Number.isNaN(date.getTime())) return stamp.slice(0, 10);
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function MemoryView(): JSX.Element {
  const t = useT();
  useLocaleChunk("memory");
  const name = useEventStore((s) => s.assistantName) || "Dodaios";
  const queryClient = useQueryClient();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [showHistory, setShowHistory] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [forgetting, setForgetting] = useState<VaultMemory | null>(null);

  const overview = useVaultOverview();
  const items = useVaultItems(query, showHistory);

  const refresh = useCallback(
    () => queryClient.invalidateQueries({ queryKey: VAULT_KEYS.all }),
    [queryClient],
  );
  const notify = useCallback((message: string) => {
    setToast(message);
    window.setTimeout(() => setToast((current) => (current === message ? null : current)), 3200);
  }, []);
  const run = useCallback(
    async (work: () => Promise<unknown>, done?: string) => {
      try {
        await work();
        await refresh();
        if (done) notify(done);
      } catch (error) {
        notify(error instanceof Error ? error.message : String(error));
      }
    },
    [notify, refresh],
  );

  const rows = useMemo(() => {
    const all = items.data?.items ?? [];
    return filter === "all" ? all : all.filter((m) => m.kind === filter);
  }, [items.data, filter]);

  const grouped = useMemo(() => {
    if (query.trim()) return [{ kind: null as MemoryKind | null, rows }];
    return MEMORY_KINDS.map((kind) => ({ kind, rows: rows.filter((m) => m.kind === kind) })).filter(
      (group) => group.rows.length > 0,
    );
  }, [rows, query]);

  if (overview.isError) {
    return (
      <div className="flex h-full items-center justify-center p-8">
        <EmptyState
          icon={<Brain />}
          title={t("vault.offline_title")}
          description={t("vault.offline_body")}
        />
      </div>
    );
  }

  const stats = overview.data?.stats;
  const byKind = stats?.by_kind ?? {};

  return (
    <div data-testid="memory-vault-view" className="flex h-full min-h-0 flex-col overflow-hidden">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto grid w-full max-w-[1180px] gap-8 px-6 pb-16 pt-8 lg:grid-cols-[minmax(0,1fr)_320px]">
          <main className="min-w-0">
            <header>
              <h1 className="text-2xl font-semibold tracking-tight text-foreground-strong">
                {t("vault.title")}
              </h1>
              <p className="mt-1 text-sm text-muted-foreground">
                {stats
                  ? fill(t("vault.subtitle"), { name, count: stats.current })
                  : t("vault.loading")}
              </p>
            </header>

            <Composer
              onSave={(text, kind) =>
                run(() => addMemory(text, kind), t("vault.saved"))
              }
            />

            <div className="mt-6 flex flex-wrap items-center gap-2">
              <label className="relative flex min-w-[220px] flex-1 items-center">
                <Search className="pointer-events-none absolute left-3 h-4 w-4 text-muted-foreground" />
                <input
                  data-testid="vault-search"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder={t("vault.search_placeholder")}
                  aria-label={t("vault.search_placeholder")}
                  className="h-9 w-full rounded-md border border-border bg-card pl-9 pr-3 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                />
              </label>
              <Button
                variant={showHistory ? "secondary" : "ghost"}
                size="sm"
                aria-pressed={showHistory}
                data-testid="vault-history-toggle"
                onClick={() => setShowHistory((value) => !value)}
              >
                <History /> {t("vault.show_history")}
              </Button>
            </div>

            <div className="mt-3 flex flex-wrap gap-1.5" role="tablist" aria-label={t("vault.kinds_label")}>
              <Chip active={filter === "all"} onClick={() => setFilter("all")}>
                {t("vault.kind_all")}
                <span className="tabular-nums text-muted-foreground">{stats?.current ?? 0}</span>
              </Chip>
              {MEMORY_KINDS.filter((kind) => (byKind[kind] ?? 0) > 0 || filter === kind).map((kind) => (
                <Chip key={kind} active={filter === kind} onClick={() => setFilter(kind)}>
                  {t(`vault.kind_${kind}`)}
                  <span className="tabular-nums text-muted-foreground">{byKind[kind] ?? 0}</span>
                </Chip>
              ))}
            </div>

            {items.isLoading ? (
              <p className="mt-10 flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" /> {t("vault.loading")}
              </p>
            ) : rows.length === 0 ? (
              <EmptyState
                className="mt-6"
                icon={<Brain />}
                title={query.trim() ? t("vault.no_results") : t("vault.empty_title")}
                description={query.trim() ? undefined : fill(t("vault.empty_body"), { name })}
              />
            ) : (
              grouped.map((group) => (
                <section key={group.kind ?? "results"} className="mt-8" data-testid={`vault-group-${group.kind ?? "results"}`}>
                  <h2 className="mb-2.5 flex items-baseline gap-2 px-1 text-sm font-medium text-foreground">
                    {group.kind ? t(`vault.kind_${group.kind}`) : t("vault.results")}
                    <span className="tabular-nums text-muted-foreground">{group.rows.length}</span>
                  </h2>
                  <ul className="divide-y divide-border overflow-hidden rounded-xl border border-border bg-card">
                    {group.rows.map((memory) => (
                      <MemoryRow
                        key={memory.id}
                        memory={memory}
                        onPin={() => run(() => pinMemory(memory.id, !memory.pinned))}
                        onEdit={(text) => run(() => editMemory(memory.id, text), t("vault.updated"))}
                        onEnd={() => run(() => endMemory(memory.id), t("vault.ended"))}
                        onForget={() => setForgetting(memory)}
                      />
                    ))}
                  </ul>
                </section>
              ))
            )}
          </main>

          <aside className="flex min-w-0 flex-col gap-5 lg:sticky lg:top-8 lg:self-start">
            <AlwaysInMind block={overview.data?.prompt_block ?? ""} name={name} />
            <RecentChanges />
            <Portability onImported={(message) => run(async () => undefined, message)} onError={notify} />
          </aside>
        </div>
      </div>

      <ConfirmDialog
        open={forgetting !== null}
        title={t("vault.forget_title")}
        description={fill(t("vault.forget_body"), { name })}
        confirmLabel={t("vault.forget")}
        items={forgetting ? [forgetting.text] : undefined}
        onClose={() => setForgetting(null)}
        onConfirm={async () => {
          const target = forgetting;
          if (!target) return;
          await forgetMemory(target.id);
          setForgetting(null);
          await refresh();
          notify(t("vault.forgotten"));
        }}
      />

      {toast && (
        <div
          role="status"
          className="pointer-events-none fixed bottom-6 left-1/2 z-[70] -translate-x-1/2 rounded-lg border border-border bg-popover px-4 py-2 text-sm text-popover-foreground shadow-float"
        >
          {toast}
        </div>
      )}
    </div>
  );
}

function Chip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={cn(
        "inline-flex h-7 items-center gap-1.5 rounded-full border px-3 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        active
          ? "border-accent/60 bg-accent/10 text-foreground-strong"
          : "border-border bg-transparent text-muted-foreground hover:bg-secondary hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

function Composer({ onSave }: { onSave: (text: string, kind: MemoryKind | "") => Promise<void> }) {
  const t = useT();
  const [text, setText] = useState("");
  const [kind, setKind] = useState<MemoryKind | "">("");
  const [busy, setBusy] = useState(false);
  const options = useMemo(
    () => [
      { value: "", label: t("vault.kind_auto") },
      ...MEMORY_KINDS.filter((k) => k !== "ephemeral").map((k) => ({ value: k, label: t(`vault.kind_${k}`) })),
    ],
    [t],
  );
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const value = text.trim();
    if (!value || busy) return;
    setBusy(true);
    try {
      await onSave(value, kind);
      setText("");
    } finally {
      setBusy(false);
    }
  };
  return (
    <form
      onSubmit={submit}
      data-testid="vault-composer"
      className="mt-6 flex flex-wrap items-center gap-2 rounded-xl border border-border bg-card p-2 focus-within:border-accent/50"
    >
      <input
        value={text}
        onChange={(event) => setText(event.target.value)}
        placeholder={t("vault.composer_placeholder")}
        aria-label={t("vault.composer_placeholder")}
        maxLength={2000}
        className="h-9 min-w-[200px] flex-1 bg-transparent px-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none"
      />
      <BrandedSelect
        value={kind}
        options={options}
        onValueChange={(value) => setKind(value as MemoryKind | "")}
        ariaLabel={t("vault.kind_label")}
        className="w-[170px]"
        testId="vault-composer-kind"
      />
      <Button type="submit" size="sm" disabled={!text.trim() || busy}>
        {busy ? <Loader2 className="animate-spin" /> : <Check />}
        {t("vault.remember")}
      </Button>
    </form>
  );
}

function MemoryRow({
  memory,
  onPin,
  onEdit,
  onEnd,
  onForget,
}: {
  memory: VaultMemory;
  onPin: () => void;
  onEdit: (text: string) => Promise<void>;
  onEnd: () => void;
  onForget: () => void;
}) {
  const t = useT();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(memory.text);
  const [historyOpen, setHistoryOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const meta = [
    t(`vault.origin_${memory.origin}`),
    // An imported memory's start date is the import, not when it became true.
    memory.valid_from && memory.origin !== "imported" ? fill(t("vault.since"), { date: day(memory.valid_from) }) : "",
    memory.valid_to ? fill(t("vault.until"), { date: day(memory.valid_to) }) : "",
    memory.entities.length ? memory.entities.join(", ") : "",
  ].filter(Boolean);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    const value = draft.trim();
    if (!value || value === memory.text) {
      setEditing(false);
      return;
    }
    await onEdit(value);
    setEditing(false);
  };

  return (
    <li
      data-testid="vault-row"
      data-current={memory.current || undefined}
      className={cn("group px-4 py-3", !memory.current && "opacity-60")}
    >
      {editing ? (
        <form onSubmit={save} className="flex items-center gap-2">
          <input
            ref={inputRef}
            autoFocus
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => event.key === "Escape" && setEditing(false)}
            aria-label={t("vault.edit")}
            className="h-8 flex-1 rounded-md border border-border-strong bg-background px-2 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
          <Button type="submit" size="sm">
            <Check /> {t("vault.save")}
          </Button>
          <Button type="button" size="sm" variant="ghost" onClick={() => setEditing(false)}>
            <X />
          </Button>
        </form>
      ) : (
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <p className={cn("text-sm leading-relaxed text-foreground", !memory.current && "line-through decoration-muted-foreground/50")}>
              {memory.pinned && <Pin className="mr-1.5 inline h-3.5 w-3.5 -translate-y-px text-accent" aria-label={t("vault.pinned")} />}
              {memory.text}
            </p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {meta.join(" · ")}
              {memory.sensitivity === "sensitive" && (
                <span className="ml-1.5 rounded border border-border px-1 py-px text-[10px] uppercase tracking-wide">
                  {t("vault.sensitive")}
                </span>
              )}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
            {memory.supersedes_id && (
              <IconButton label={t("vault.history")} onClick={() => setHistoryOpen((v) => !v)}>
                <History />
              </IconButton>
            )}
            {memory.current && (
              <>
                <IconButton label={memory.pinned ? t("vault.unpin") : t("vault.pin")} onClick={onPin}>
                  {memory.pinned ? <PinOff /> : <Pin />}
                </IconButton>
                <IconButton
                  label={t("vault.edit")}
                  onClick={() => {
                    setDraft(memory.text);
                    setEditing(true);
                  }}
                >
                  <Pencil />
                </IconButton>
                <IconButton label={t("vault.end")} onClick={onEnd}>
                  <CircleOff />
                </IconButton>
              </>
            )}
            <IconButton label={t("vault.forget")} onClick={onForget} danger>
              <Trash2 />
            </IconButton>
          </div>
        </div>
      )}
      {historyOpen && <Versions id={memory.id} />}
    </li>
  );
}

function IconButton({
  label,
  onClick,
  danger = false,
  children,
}: {
  label: string;
  onClick: () => void;
  danger?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      onClick={onClick}
      className={cn(
        "inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&>svg]:h-3.5 [&>svg]:w-3.5",
        danger ? "hover:text-destructive" : "hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

function Versions({ id }: { id: string }) {
  const t = useT();
  const history = useVaultHistory(id);
  const versions = history.data?.versions ?? [];
  return (
    <ol className="mt-3 space-y-1.5 border-l border-border pl-3" data-testid="vault-versions">
      {versions.map((version) => (
        <li key={version.id} className="text-xs">
          <span className="text-muted-foreground">{day(version.valid_from)} · </span>
          <span className={version.current ? "text-foreground" : "text-muted-foreground line-through"}>
            {version.text}
          </span>
          {version.current && <span className="ml-1.5 text-accent">{t("vault.now")}</span>}
        </li>
      ))}
    </ol>
  );
}

function Panel({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-border bg-card p-4">
      <h2 className="text-sm font-medium text-foreground">{title}</h2>
      {hint && <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{hint}</p>}
      <div className="mt-3">{children}</div>
    </section>
  );
}

function AlwaysInMind({ block, name }: { block: string; name: string }) {
  const t = useT();
  const body = block.split("\n").slice(2).join("\n").trim();
  return (
    <Panel title={t("vault.always_title")} hint={fill(t("vault.always_hint"), { name })}>
      {body ? (
        <pre
          data-testid="vault-prompt-block"
          className="max-h-[320px] overflow-y-auto whitespace-pre-wrap break-words rounded-md bg-background/60 p-3 font-mono text-[11px] leading-relaxed text-muted-foreground"
        >
          {body}
        </pre>
      ) : (
        <p className="text-xs text-muted-foreground">{t("vault.always_empty")}</p>
      )}
    </Panel>
  );
}

function RecentChanges() {
  const t = useT();
  const activity = useVaultActivity();
  const entries = (activity.data?.entries ?? []).filter((e) => e.action !== "pin" && e.action !== "unpin");
  return (
    <Panel title={t("vault.recent_title")}>
      {entries.length === 0 ? (
        <p className="text-xs text-muted-foreground">{t("vault.recent_empty")}</p>
      ) : (
        <ul className="space-y-2" data-testid="vault-activity">
          {entries.slice(0, 8).map((entry) => (
            <li key={entry.seq} className="text-xs leading-snug">
              <span className="font-medium text-foreground">{t(`vault.action_${entry.action}`)}</span>
              <span className="text-muted-foreground"> · {day(entry.at)}</span>
              {entry.text && <p className="mt-0.5 line-clamp-2 text-muted-foreground">{entry.text}</p>}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function Portability({ onImported, onError }: { onImported: (message: string) => void; onError: (message: string) => void }) {
  const t = useT();
  const fileRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const pick = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    try {
      const report = await importBundle(file);
      onImported(fill(t("vault.import_done"), { added: report.added, skipped: report.skipped }));
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };
  return (
    <Panel title={t("vault.portable_title")} hint={t("vault.portable_hint")}>
      <div className="flex flex-col gap-2">
        <Button asChild variant="secondary" size="sm" className="justify-start">
          <a href={exportUrl("bundle")} download data-testid="vault-export-bundle">
            <Download /> {t("vault.export_bundle")}
          </a>
        </Button>
        <Button asChild variant="ghost" size="sm" className="justify-start">
          <a href={exportUrl("markdown")} download data-testid="vault-export-markdown">
            <Download /> {t("vault.export_markdown")}
          </a>
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className="justify-start"
          disabled={busy}
          onClick={() => fileRef.current?.click()}
          data-testid="vault-import"
        >
          {busy ? <Loader2 className="animate-spin" /> : <Upload />} {t("vault.import")}
        </Button>
        <input
          ref={fileRef}
          type="file"
          accept=".zip,application/zip"
          className="hidden"
          onChange={(event) => void pick(event.target.files?.[0])}
        />
      </div>
    </Panel>
  );
}
