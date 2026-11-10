/**
 * The store's front: one centred column with the search on top and every
 * published entry as a row beneath it.
 *
 * Rows, not cards: a row reads the same with three entries and with three
 * hundred, and it never leaves a half-empty grid. Nothing installs from a row;
 * pressing one opens the entry's page, where what it reaches and what is
 * inside it are on screen before the button is.
 */
import { useRef, type ReactNode, type RefObject } from "react";
import {
  AlertTriangle,
  Check,
  ChevronRight,
  FileInput,
  Loader2,
  Plus,
  Search,
  X,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { fill } from "@/i18n";
import { cn } from "@/lib/utils";
import { EntryMark } from "./EntryMark";
import { categoryLabel, entryKey, KINDS, type Entry, type Kind, type StoreFilter } from "./model";

type Translate = (key: string) => string;

const FOCUS_RING =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background";

export interface StoreHomeProps {
  t: Translate;
  /** The index is still on its way, or the section's strings are. */
  loading: boolean;
  /** The index request itself failed. */
  loadError: string | null;
  /** `stale` and `unavailable` are said out loud; `disabled` replaces the page. */
  status: string | undefined;
  /** Every entry the search leaves, best match first. */
  searched: Entry[];
  /** `searched`, narrowed by the active filter. */
  visible: Entry[];
  counts: Record<StoreFilter, number>;
  /** True while the index holds nothing at all. */
  empty: boolean;
  query: string;
  onQuery: (value: string) => void;
  filter: StoreFilter;
  onFilter: (filter: StoreFilter) => void;
  signedIn: boolean;
  publishEnabled: boolean;
  searchRef: RefObject<HTMLInputElement>;
  onOpen: (entry: Entry) => void;
  onPublish: () => void;
  onImport: (file: File) => void;
  importing: boolean;
  importError: string | null;
  onBrowseBuiltIn: () => void;
  onRetry: () => void;
  retrying: boolean;
  refreshError: string | null;
}

export function StoreHome(props: StoreHomeProps) {
  const { t, loading, loadError, status, visible, empty, query, filter } = props;
  const needle = query.trim();
  const indexDown = empty && (status === "disabled" || status === "unavailable");
  const frontPage = filter === "all" && !needle;
  const ready = !loading && !loadError;

  return (
    <ScrollArea className="min-h-0 flex-1">
      <div className="mx-auto w-full max-w-[860px] px-6 pb-24">
        <header className="pb-8 pt-4 text-center">
          <h1 className="font-display text-2xl font-semibold text-foreground-strong">
            {t("marketplace.title")}
          </h1>
          {!loading && (
            <p
              className="mx-auto mt-2 max-w-[52ch] text-lg text-muted-foreground"
              data-testid="marketplace-lead"
            >
              {status === "disabled" ? t("marketplace.status_disabled") : t("marketplace.home_lead")}
            </p>
          )}
          {!indexDown && (
            <>
              <SearchField
                inputRef={props.searchRef}
                value={query}
                onChange={props.onQuery}
                placeholder={t("marketplace.search_placeholder")}
                clearLabel={t("marketplace.empty_clear")}
              />
              {ready && (
                <FilterTabs
                  active={filter}
                  onChange={props.onFilter}
                  counts={props.counts}
                  showInstalled={props.counts.installed > 0 || filter === "installed"}
                  showMine={props.signedIn}
                  t={t}
                />
              )}
            </>
          )}
        </header>

        {ready && (status === "stale" || props.refreshError) && (
          <Notice
            text={props.refreshError ?? t("marketplace.status_stale")}
            action={t("marketplace.retry")}
            onAction={props.onRetry}
            busy={props.retrying}
          />
        )}

        {loading && <RowSkeleton />}

        {loadError && !loading && (
          <Message
            title={t("marketplace.error_title")}
            body={loadError}
            actions={
              <Button size="sm" onClick={props.onRetry} disabled={props.retrying}>
                {props.retrying && <Loader2 className="animate-spin" />}
                {t("marketplace.retry")}
              </Button>
            }
          />
        )}

        {ready && indexDown && status === "unavailable" && (
          <Message
            title={t("marketplace.error_title")}
            body={t("marketplace.status_unavailable")}
            actions={
              <Button size="sm" onClick={props.onRetry} disabled={props.retrying}>
                {props.retrying && <Loader2 className="animate-spin" />}
                {t("marketplace.retry")}
              </Button>
            }
          />
        )}

        {ready && !indexDown && visible.length === 0 && <NoResults {...props} needle={needle} />}

        {ready && visible.length > 0 && frontPage && <FrontPage entries={visible} onOpen={props.onOpen} onShowKind={props.onFilter} t={t} />}

        {ready && visible.length > 0 && !frontPage && (
          <RowList
            entries={visible}
            onOpen={props.onOpen}
            showKind={filter === "all" || filter === "installed" || filter === "mine"}
            t={t}
          />
        )}

        {ready && !indexDown && visible.length > 0 && frontPage && <OwnRows {...props} />}
      </div>
    </ScrollArea>
  );
}

// ---------------------------------------------------------------------------
// Search and filter
// ---------------------------------------------------------------------------

function SearchField({
  inputRef,
  value,
  onChange,
  placeholder,
  clearLabel,
}: {
  inputRef: RefObject<HTMLInputElement>;
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  clearLabel: string;
}) {
  return (
    <div className="relative mx-auto mt-6 w-full max-w-[560px]">
      <Search className="pointer-events-none absolute left-4 top-1/2 h-[18px] w-[18px] -translate-y-1/2 text-muted-foreground" />
      <input
        ref={inputRef}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Escape" && value) {
            event.stopPropagation();
            onChange("");
          }
        }}
        placeholder={placeholder}
        aria-label={placeholder}
        className={cn(
          "h-12 w-full rounded-full border border-transparent bg-secondary pl-11 pr-12 text-lg text-foreground",
          "placeholder:text-foreground-faint transition-colors",
          "hover:bg-surface-raised focus:border-border-strong focus:bg-secondary focus:outline-none",
        )}
      />
      <div className="absolute right-3 top-1/2 flex -translate-y-1/2 items-center">
        {value ? (
          <button
            type="button"
            onClick={() => {
              onChange("");
              inputRef.current?.focus();
            }}
            aria-label={clearLabel}
            title={clearLabel}
            className={cn(
              "grid h-7 w-7 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-surface-raised hover:text-foreground",
              FOCUS_RING,
            )}
          >
            <X className="h-4 w-4" />
          </button>
        ) : (
          <kbd
            aria-hidden
            className="grid h-6 min-w-6 place-items-center rounded-md border border-border-strong px-1.5 font-mono text-xs text-muted-foreground"
          >
            /
          </kbd>
        )}
      </div>
    </div>
  );
}

/** The kind switch. One quiet ground marks the active one; counts follow the search. */
function FilterTabs({
  active,
  onChange,
  counts,
  showInstalled,
  showMine,
  t,
}: {
  active: StoreFilter;
  onChange: (filter: StoreFilter) => void;
  counts: Record<StoreFilter, number>;
  showInstalled: boolean;
  showMine: boolean;
  t: Translate;
}) {
  const ids: StoreFilter[] = ["all", ...KINDS];
  if (showInstalled) ids.push("installed");
  if (showMine) ids.push("mine");
  const label: Record<StoreFilter, string> = {
    all: t("marketplace.filter_all"),
    plugin: t("marketplace.filter_plugins"),
    skill: t("marketplace.filter_skills"),
    agent: t("marketplace.filter_agents"),
    look: t("marketplace.filter_looks"),
    installed: t("marketplace.installed"),
    mine: t("marketplace.filter_mine"),
  };
  return (
    <div role="tablist" aria-label={t("marketplace.title")} className="mt-5 flex flex-wrap justify-center gap-1">
      {ids.map((id) => (
        <button
          key={id}
          type="button"
          role="tab"
          aria-selected={active === id}
          onClick={() => onChange(id)}
          className={cn(
            "inline-flex h-8 items-center gap-1.5 rounded-full px-3 text-base font-medium transition-colors",
            active === id
              ? "bg-secondary text-foreground-strong"
              : "text-muted-foreground hover:text-foreground",
            FOCUS_RING,
          )}
        >
          {label[id]}
          <span className="tabular-nums text-foreground-faint">{counts[id]}</span>
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Rows
// ---------------------------------------------------------------------------

const KIND_TITLE: Record<Kind, string> = {
  plugin: "marketplace.shelf_plugins",
  skill: "marketplace.shelf_skills",
  agent: "marketplace.shelf_agents",
  look: "marketplace.shelf_looks",
};
const KIND_HINT: Record<Kind, string> = {
  plugin: "marketplace.shelf_plugins_hint",
  skill: "marketplace.shelf_skills_hint",
  agent: "marketplace.shelf_agents_hint",
  look: "marketplace.shelf_looks_hint",
};

/** A store this small is one short list; a lead entry would only repeat it. */
const SPOTLIGHT_MIN_ENTRIES = 6;
/** Rows a kind shows on the front page before "Show all" takes over. */
const GROUP_ROWS = 5;

/**
 * The unfiltered store: what leads the page, then one group per kind.
 *
 * The lead is the registry's own picks, or the newest arrival when it made
 * none. An entry is listed once: what leads is not repeated under its kind.
 */
function FrontPage({
  entries,
  onOpen,
  onShowKind,
  t,
}: {
  entries: Entry[];
  onOpen: (entry: Entry) => void;
  onShowKind: (kind: Kind) => void;
  t: Translate;
}) {
  const readable = entries.filter((entry) => !entry.broken);
  const picks = readable.filter((entry) => entry.featured);
  const newest =
    picks.length === 0 && readable.length >= SPOTLIGHT_MIN_ENTRIES
      ? [...readable].sort((x, y) => Date.parse(y.publishedAt ?? "") - Date.parse(x.publishedAt ?? ""))[0]
      : undefined;
  const lead = picks.length > 0 ? picks.slice(0, 2) : newest?.publishedAt ? [newest] : [];
  const label = t(picks.length > 0 ? "marketplace.shelf_featured" : "marketplace.shelf_new");
  const rest = entries.filter((entry) => !lead.includes(entry));
  return (
    <div className="space-y-10">
      {lead.length > 0 && (
        <section aria-label={label} className="grid gap-3 sm:grid-cols-[repeat(auto-fit,minmax(320px,1fr))]">
          {lead.map((entry) => (
            <Spotlight key={entryKey(entry)} entry={entry} label={label} onOpen={onOpen} t={t} />
          ))}
        </section>
      )}
      {KINDS.map((kind) => {
        // An entry this client cannot read goes last: it is a fact about the
        // store, not something to open the group with.
        const rows = rest
          .filter((entry) => entry.kind === kind)
          .sort((x, y) => Number(Boolean(x.broken)) - Number(Boolean(y.broken)));
        if (rows.length === 0) return null;
        const more = rows.length > GROUP_ROWS;
        return (
          <Group key={kind} title={t(KIND_TITLE[kind])} hint={t(KIND_HINT[kind])}>
            <RowList entries={more ? rows.slice(0, GROUP_ROWS) : rows} onOpen={onOpen} t={t} />
            {more && (
              <button
                type="button"
                onClick={() => onShowKind(kind)}
                data-testid={`marketplace-show-all-${kind}`}
                className={cn(
                  "ml-3 mt-2 inline-flex items-center gap-1 rounded-sm text-base font-medium text-muted-foreground transition-colors hover:text-foreground",
                  FOCUS_RING,
                )}
              >
                {fill(t("marketplace.show_all_count"), { count: rows.length })}
                <ChevronRight className="h-4 w-4" />
              </button>
            )}
          </Group>
        );
      })}
    </div>
  );
}

/** The one entry the page opens with: larger, with room for its whole pitch. */
function Spotlight({
  entry,
  label,
  onOpen,
  t,
}: {
  entry: Entry;
  label: string;
  onOpen: (entry: Entry) => void;
  t: Translate;
}) {
  return (
    <button
      type="button"
      onClick={() => onOpen(entry)}
      data-testid={`marketplace-spotlight-${entry.name}`}
      data-entry-key={entryKey(entry)}
      className={cn(
        "group flex items-center gap-5 rounded-2xl border border-border bg-card p-5 text-left transition-colors hover:border-border-strong hover:bg-secondary",
        FOCUS_RING,
      )}
    >
      <EntryMark entry={entry} size="lead" />
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-medium text-accent">{label}</span>
        <span className="mt-0.5 block truncate text-xl font-semibold text-foreground-strong">
          {entry.title}
        </span>
        <span className="mt-1 line-clamp-2 text-base text-foreground-secondary">
          {entry.description ?? t("marketplace.description_missing")}
        </span>
        <span className="mt-2 block truncate text-sm text-muted-foreground">{bylineOf(entry, true, t)}</span>
      </span>
      <RowState entry={entry} t={t} />
    </button>
  );
}

/** "Skill · @publisher · Writing": what a row says about itself in one line. */
function bylineOf(entry: Entry, showKind: boolean, t: Translate): string {
  return [
    showKind ? t(`marketplace.kind_${entry.kind}`) : null,
    entry.publisher ? `@${entry.publisher}` : null,
    entry.categories[0] ? categoryLabel(entry.categories[0]) : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

function Group({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section>
      <div className="mb-1 flex flex-wrap items-baseline gap-x-3 px-3">
        <h2 className="text-lg font-semibold text-foreground-strong">{title}</h2>
        {hint && <p className="text-base text-muted-foreground">{hint}</p>}
      </div>
      {children}
    </section>
  );
}

function RowList({
  entries,
  onOpen,
  showKind = false,
  t,
}: {
  entries: Entry[];
  onOpen: (entry: Entry) => void;
  showKind?: boolean;
  t: Translate;
}) {
  return (
    <ul>
      {entries.map((entry) => (
        <li key={entryKey(entry)}>
          <EntryRow entry={entry} onOpen={onOpen} showKind={showKind} t={t} />
        </li>
      ))}
    </ul>
  );
}

const ROW = cn(
  "group flex w-full items-center gap-4 rounded-xl px-3 py-3 text-left transition-colors hover:bg-secondary",
  FOCUS_RING,
);

function EntryRow({
  entry,
  onOpen,
  showKind = false,
  t,
}: {
  entry: Entry;
  onOpen: (entry: Entry) => void;
  showKind?: boolean;
  t: Translate;
}) {
  const description = entry.broken
    ? (entry.problem ?? t("marketplace.entry_unreadable"))
    : (entry.description ?? t("marketplace.description_missing"));
  const byline = bylineOf(entry, showKind, t);
  return (
    <button
      type="button"
      onClick={() => onOpen(entry)}
      data-testid={`marketplace-row-${entry.name}`}
      data-entry-key={entryKey(entry)}
      className={ROW}
    >
      <EntryMark entry={entry} />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-lg font-medium text-foreground-strong">{entry.title}</span>
        <span
          className={cn(
            "line-clamp-2 text-base",
            entry.description || entry.broken ? "text-foreground-secondary" : "text-foreground-faint",
          )}
        >
          {description}
        </span>
        {byline && <span className="mt-1 block truncate text-sm text-muted-foreground">{byline}</span>}
      </span>
      <RowState entry={entry} t={t} />
    </button>
  );
}

/** What pressing the row leads to, in one word — or just the way in. */
function RowState({ entry, t }: { entry: Entry; t: Translate }) {
  if (entry.pending) {
    const failed = entry.pending === "failed";
    return (
      <span
        data-testid="store-row-pending"
        className={cn(
          "inline-flex shrink-0 items-center justify-end gap-1.5 whitespace-nowrap text-base",
          failed ? "text-destructive" : "text-muted-foreground",
        )}
      >
        {failed ? (
          <AlertTriangle className="h-4 w-4" />
        ) : (
          <Loader2 className="h-4 w-4 animate-spin" />
        )}
        {t(failed ? "marketplace.pending_failed" : "marketplace.pending_checking")}
      </span>
    );
  }
  if (entry.updateAvailable) {
    return (
      <span className="w-[92px] shrink-0 text-right text-base font-medium text-accent">
        {t("marketplace.update_available")}
      </span>
    );
  }
  if (entry.installed) {
    return (
      <span className="inline-flex w-[92px] shrink-0 items-center justify-end gap-1.5 text-base text-muted-foreground">
        <Check className="h-4 w-4 text-success" />
        {t("marketplace.installed")}
      </span>
    );
  }
  return (
    <span className="flex w-[92px] shrink-0 justify-end">
      <ChevronRight className="h-4 w-4 text-foreground-faint transition-colors group-hover:text-foreground" />
    </span>
  );
}

/** The two things a person can add themselves, as rows of the same list. */
function OwnRows({
  t,
  publishEnabled,
  onPublish,
  onImport,
  importing,
  importError,
}: StoreHomeProps) {
  const fileInput = useRef<HTMLInputElement | null>(null);
  return (
    <div className="mt-10">
      <Group title={t("marketplace.shelf_own")}>
        <ul>
          {publishEnabled && (
            <li>
              <button type="button" onClick={onPublish} className={ROW} data-testid="marketplace-publish-row">
                <OwnMark>
                  <Plus className="h-5 w-5" />
                </OwnMark>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-lg font-medium text-foreground-strong">
                    {t("marketplace.publish_cta")}
                  </span>
                  <span className="block truncate text-base text-foreground-secondary">
                    {t("marketplace.publish_card_body")}
                  </span>
                </span>
                <ChevronRight className="h-4 w-4 shrink-0 text-foreground-faint transition-colors group-hover:text-foreground" />
              </button>
            </li>
          )}
          <li>
            <input
              ref={fileInput}
              type="file"
              accept=".json,application/json"
              className="hidden"
              data-testid="marketplace-import-agent-input"
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = "";
                if (file) onImport(file);
              }}
            />
            <button
              type="button"
              onClick={() => fileInput.current?.click()}
              disabled={importing}
              className={ROW}
              data-testid="marketplace-import-agent"
            >
              <OwnMark>
                {importing ? <Loader2 className="h-5 w-5 animate-spin" /> : <FileInput className="h-5 w-5" />}
              </OwnMark>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-lg font-medium text-foreground-strong">
                  {t("marketplace.import_agent")}
                </span>
                <span className="block truncate text-base text-foreground-secondary">
                  {t("marketplace.import_agent_body")}
                </span>
              </span>
              <ChevronRight className="h-4 w-4 shrink-0 text-foreground-faint transition-colors group-hover:text-foreground" />
            </button>
            {importError && (
              <p role="alert" className="flex items-start gap-2 px-3 pt-1 text-base text-destructive">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                {importError}
              </p>
            )}
          </li>
        </ul>
      </Group>
    </div>
  );
}

function OwnMark({ children }: { children: ReactNode }) {
  return (
    <span className="grid h-12 w-12 shrink-0 place-items-center rounded-xl bg-secondary text-muted-foreground transition-colors group-hover:bg-surface-raised group-hover:text-foreground">
      {children}
    </span>
  );
}

// ---------------------------------------------------------------------------
// States
// ---------------------------------------------------------------------------

function RowSkeleton() {
  return (
    <div role="status" aria-busy="true" data-testid="marketplace-skeleton" className="space-y-1">
      {Array.from({ length: 5 }, (_, index) => (
        <div key={index} className="flex items-center gap-4 px-3 py-2.5">
          <div className="h-12 w-12 rounded-xl bg-secondary" />
          <div className="flex-1 space-y-2">
            <div className="h-3.5 w-1/4 rounded bg-secondary" />
            <div className="h-3 w-3/5 rounded bg-secondary" />
          </div>
        </div>
      ))}
    </div>
  );
}

/** One line under the search that says what is wrong, and the way out. */
function Notice({
  text,
  action,
  onAction,
  busy,
}: {
  text: string;
  action: string;
  onAction: () => void;
  busy: boolean;
}) {
  return (
    <p role="alert" className="mb-6 flex items-start gap-2.5 px-3 text-base text-foreground">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
      <span className="min-w-0 flex-1">{text}</span>
      <button
        type="button"
        onClick={onAction}
        disabled={busy}
        className={cn("shrink-0 rounded-sm font-medium text-accent hover:underline disabled:opacity-50", FOCUS_RING)}
      >
        {action}
      </button>
    </p>
  );
}

function Message({ title, body, actions }: { title: string; body?: string; actions?: ReactNode }) {
  return (
    <div className="px-3 py-10 text-center">
      <p className="text-lg font-medium text-foreground-strong">{title}</p>
      {body && <p className="mx-auto mt-1 max-w-[52ch] text-base text-muted-foreground">{body}</p>}
      {actions && <div className="mt-4 flex flex-wrap justify-center gap-2">{actions}</div>}
    </div>
  );
}

function NoResults({
  t,
  needle,
  filter,
  onQuery,
  onFilter,
  onPublish,
  publishEnabled,
  onBrowseBuiltIn,
}: StoreHomeProps & { needle: string }) {
  const showAll = () => {
    onQuery("");
    onFilter("all");
  };
  if (filter === "mine" && !needle) {
    return (
      <div data-testid="marketplace-empty-mine">
        <Message
          title={t("marketplace.empty_mine")}
          actions={
            publishEnabled && (
              <Button size="sm" onClick={onPublish}>
                {t("marketplace.publish_cta")}
              </Button>
            )
          }
        />
      </div>
    );
  }
  if (needle) {
    return (
      <Message
        title={fill(t("marketplace.empty_search"), { query: needle })}
        body={t("marketplace.empty_search_builtin")}
        actions={
          <>
            <Button size="sm" onClick={onBrowseBuiltIn}>
              {t("marketplace.browse_builtin")}
            </Button>
            <Button size="sm" variant="outline" onClick={showAll}>
              {t("marketplace.empty_clear")}
            </Button>
          </>
        }
      />
    );
  }
  return (
    <Message
      title={t("marketplace.empty")}
      actions={
        filter !== "all" ? (
          <Button size="sm" variant="outline" onClick={showAll}>
            {t("marketplace.show_all")}
          </Button>
        ) : publishEnabled ? (
          <Button size="sm" onClick={onPublish}>
            {t("marketplace.publish_cta")}
          </Button>
        ) : undefined
      }
    />
  );
}
