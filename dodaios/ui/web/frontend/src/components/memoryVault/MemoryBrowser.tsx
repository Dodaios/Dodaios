/**
 * The memories list and the inspector beside it.
 *
 * The list is grouped by kind, each group with a plain heading and one line
 * that says what belongs there. A row shows what the memory is about in bold
 * ("Lukas") and what it says beside it; a blue dot marks the memories the
 * assistant carries into every conversation. The inspector explains one
 * memory: what it says, where it came from (with the user's own words when it
 * was learned), every earlier version, and what can be done.
 */
import { useEffect, useMemo, useState, type FormEvent } from "react";
import {
  Check,
  CheckSquare,
  CircleOff,
  Compass,
  MessageSquareQuote,
  MousePointerClick,
  Pencil,
  Pin,
  PinOff,
  Quote,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { anchorOf, jumpToMessage } from "@/lib/memorySource";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "./ConfirmDialog";
import {
  editMemory,
  endMemory,
  forgetMany,
  forgetMemory,
  pinMemory,
  setMemoryScope,
  useVaultHistory,
  MEMORY_KINDS,
  MEMORY_SCOPES,
  type MemoryKind,
  type MemoryScope,
  type VaultMemory,
} from "@/lib/personalMemoryApi";
import { KIND_STYLE, kindColor } from "./kinds";

/** How the list is ordered: grouped by kind, or one flat list, newest first. */
export type ListSort = "kind" | "newest";

export type Shelf = "all" | "in_mind" | "pinned" | "history" | MemoryKind;

/** "Lukas: Born 1922" -> subject "Lukas", body "Born 1922". */
export function splitSubject(raw: string): { subject: string | null; body: string } {
  // A trailing "Source: ..." note is bookkeeping; the inspector shows the origin.
  const text = raw.trim().replace(/\s+Source:\s[^\n]*$/, "");
  const match = /^([^:\n]{1,48}):\s+([\s\S]+)$/.exec(text);
  if (!match) return { subject: null, body: text };
  const body = match[2].charAt(0).toUpperCase() + match[2].slice(1);
  return { subject: match[1].trim(), body };
}

function sortKey(memory: VaultMemory): string {
  return (splitSubject(memory.text).subject ?? memory.text).toLocaleLowerCase();
}

export function formatDay(stamp: string | null | undefined): string {
  if (!stamp) return "";
  const date = new Date(stamp);
  if (Number.isNaN(date.getTime())) return stamp.slice(0, 10);
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function MemoryBrowser({
  shelf,
  query,
  items,
  loading,
  inMind,
  name,
  onChanged,
  notify,
  onAdd,
  sort = "kind",
  selecting = false,
  onSelectingChange = () => undefined,
  onUndoable = () => undefined,
  total,
  hasMore = false,
  onMore = () => undefined,
}: {
  shelf: Shelf;
  query: string;
  items: VaultMemory[];
  loading: boolean;
  inMind: Set<string>;
  name: string;
  onChanged: () => Promise<unknown>;
  notify: (message: string) => void;
  onAdd: () => void;
  sort?: ListSort;
  selecting?: boolean;
  onSelectingChange?: (on: boolean) => void;
  /** A forget that can be taken back: the message and the undo token. */
  onUndoable?: (message: string, token: string | null | undefined) => void;
  total?: number;
  hasMore?: boolean;
  onMore?: () => void;
}) {
  const t = useT();
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [forgettingMany, setForgettingMany] = useState(false);
  useEffect(() => {
    if (!selecting) setPicked(new Set());
  }, [selecting]);
  const rows = useMemo(() => {
    switch (shelf) {
      case "all":
        return items;
      case "in_mind":
        return items.filter((m) => inMind.has(m.id));
      case "pinned":
        return items.filter((m) => m.pinned && m.current);
      case "history":
        return items.filter((m) => !m.current);
      default:
        return items.filter((m) => m.kind === shelf);
    }
  }, [items, shelf, inMind]);

  // One group per kind, in the fixed kind order. Without a search the rows of
  // a group are sorted by what they are about, so "Lukas: ..." facts sit
  // together; a search keeps the ranking it came with.
  const groups = useMemo(() => {
    if (sort === "newest") {
      const flat = [...rows].sort((a, b) => b.recorded_at.localeCompare(a.recorded_at));
      return flat.length ? [{ kind: null as MemoryKind | null, members: flat }] : [];
    }
    return MEMORY_KINDS.map((kind) => {
      const members = rows.filter((m) => m.kind === kind);
      if (!query) members.sort((a, b) => sortKey(a).localeCompare(sortKey(b)));
      return { kind: kind as MemoryKind | null, members };
    }).filter((group) => group.members.length > 0);
  }, [rows, query, sort]);
  const ordered = useMemo(() => groups.flatMap((group) => group.members), [groups]);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = ordered.find((m) => m.id === selectedId) ?? null;
  useEffect(() => {
    if (selectedId && !rows.some((m) => m.id === selectedId)) setSelectedId(null);
  }, [rows, selectedId]);
  // Escape closes the slide-over inspector of a narrow window.
  useEffect(() => {
    if (!selectedId) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && window.matchMedia("(max-width: 1023px)").matches) setSelectedId(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectedId]);

  const move = (step: number) => {
    if (!ordered.length) return;
    const at = ordered.findIndex((m) => m.id === selected?.id);
    const index = at < 0 ? (step > 0 ? -1 : ordered.length) : at;
    const next = ordered[Math.min(ordered.length - 1, Math.max(0, index + step))];
    setSelectedId(next.id);
    document.getElementById(`vault-row-${next.id}`)?.scrollIntoView({ block: "nearest" });
  };

  if (!loading && rows.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 px-8 text-center">
        <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-sheen/[0.06] text-muted-foreground">
          {query ? <Search className="h-5 w-5" /> : <Compass className="h-5 w-5" />}
        </span>
        <p className="text-[15px] font-medium text-foreground-strong">
          {query ? t("vault.no_results") : shelf === "history" ? t("vault.history_empty") : t("vault.empty_title")}
        </p>
        {!query && shelf !== "history" && (
          <>
            <p className="max-w-[360px] text-[13px] leading-relaxed text-muted-foreground">
              {fill(t("vault.empty_body"), { name })}
            </p>
            <Button size="sm" onClick={onAdd}>
              {t("vault.add")}
            </Button>
          </>
        )}
      </div>
    );
  }

  return (
    <div className="grid h-full min-h-0 grid-cols-1 lg:grid-cols-[minmax(0,1fr)_minmax(320px,400px)]">
      <ul
        role="listbox"
        aria-label={t("vault.mode_memories")}
        tabIndex={0}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            move(1);
          } else if (event.key === "ArrowUp") {
            event.preventDefault();
            move(-1);
          }
        }}
        className="mx-auto min-h-0 w-full max-w-[860px] overflow-y-auto px-3 pb-6 pt-2 focus-visible:outline-none"
      >
        <li
          role="presentation"
          data-testid="vault-toolbar"
          className="sticky top-0 z-[2] flex flex-wrap items-center gap-2 bg-card/95 px-3 py-2 backdrop-blur"
        >
          {selecting ? (
            <>
              <span className="text-[12px] tabular-nums text-foreground-secondary" data-testid="vault-picked-count">
                {fill(t("vault.selected_count"), { count: picked.size })}
              </span>
              <button
                type="button"
                data-testid="vault-select-all"
                onClick={() => setPicked(new Set(ordered.map((m) => m.id)))}
                className="rounded-md px-2 py-1 text-[12px] text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {t("vault.select_all")}
              </button>
              <span className="ml-auto flex items-center gap-1.5">
                <Button
                  size="sm"
                  variant="ghost"
                  data-testid="vault-forget-selected"
                  disabled={picked.size === 0}
                  className="text-destructive hover:bg-destructive/10"
                  onClick={() => setForgettingMany(true)}
                >
                  <Trash2 /> {t("vault.forget_selected")}
                </Button>
                <Button size="sm" variant="ghost" data-testid="vault-select-done" onClick={() => onSelectingChange(false)}>
                  {t("vault.select_done")}
                </Button>
              </span>
            </>
          ) : (
            <button
              type="button"
              data-testid="vault-select"
              onClick={() => onSelectingChange(true)}
              className="ml-auto inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[12px] text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <CheckSquare className="h-3.5 w-3.5" /> {t("vault.select")}
            </button>
          )}
        </li>
        {shelf === "all" && !query && (
          <li role="presentation" data-testid="vault-summary" className="px-3 pb-2 pt-3">
            <p className="text-[13px] leading-relaxed text-foreground-secondary">
              {fill(t("vault.summary"), {
                name,
                count: rows.filter((m) => m.current).length,
                inMind: inMind.size,
              })}
            </p>
            <p className="mt-1.5 flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <span className="h-1.5 w-1.5 rounded-full bg-accent" aria-hidden />
              {t("vault.shelf_in_mind")}
            </p>
          </li>
        )}
        {groups.map((group) => (
          <li key={group.kind} role="presentation" data-testid="vault-group">
            {group.kind && <GroupHeading kind={group.kind} count={group.members.length} />}
            <ul role="group" aria-label={group.kind ? t(`vault.kind_${group.kind}`) : t("vault.sort_newest")}>
              {group.members.map((memory) => (
                <Row
                  key={memory.id}
                  memory={memory}
                  inMind={inMind.has(memory.id)}
                  selected={memory.id === selected?.id}
                  checked={selecting ? picked.has(memory.id) : undefined}
                  showDate={sort === "newest"}
                  onSelect={() => {
                    if (!selecting) return setSelectedId(memory.id);
                    setPicked((current) => {
                      const next = new Set(current);
                      if (!next.delete(memory.id)) next.add(memory.id);
                      return next;
                    });
                  }}
                />
              ))}
            </ul>
          </li>
        ))}
        {hasMore && (
          <li role="presentation" className="px-3 py-4 text-center">
            <Button size="sm" variant="ghost" data-testid="vault-more" onClick={onMore}>
              {fill(t("vault.show_more"), { shown: rows.length, total: total ?? rows.length })}
            </Button>
          </li>
        )}
      </ul>
      <div className="hidden min-h-0 border-l border-border lg:block">
        {!selected && (
          <div className="flex h-full flex-col items-center justify-center gap-2 px-10 text-center">
            <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-sheen/[0.06] text-muted-foreground">
              <MousePointerClick className="h-5 w-5" />
            </span>
            <p className="text-[14px] font-medium text-foreground-strong">{t("vault.pick_title")}</p>
            <p className="max-w-[280px] text-[12px] leading-relaxed text-muted-foreground">{t("vault.pick_body")}</p>
          </div>
        )}
        {selected && (
          <Inspector
            key={selected.id}
            memory={selected}
            inMind={inMind.has(selected.id)}
            name={name}
            onChanged={onChanged}
            notify={notify}
            onUndoable={onUndoable}
          />
        )}
      </div>
      <ConfirmDialog
        open={forgettingMany}
        title={t("vault.forget_many_title")}
        description={fill(t("vault.forget_many_body"), { name, count: picked.size })}
        confirmLabel={t("vault.forget")}
        items={ordered.filter((m) => picked.has(m.id)).map((m) => m.text)}
        onClose={() => setForgettingMany(false)}
        onConfirm={async () => {
          const result = await forgetMany([...picked]);
          setForgettingMany(false);
          setPicked(new Set());
          onSelectingChange(false);
          await onChanged();
          onUndoable(fill(t("vault.forgotten_many"), { count: result.forgotten }), result.undo_token);
        }}
      />
      {/* Narrow windows: the inspector slides in over the list. */}
      {selectedId && selected && (
        <div className="fixed inset-0 z-[60] flex justify-end bg-scrim/30 lg:hidden" onClick={() => setSelectedId(null)}>
          <div
            className="relative h-full w-[min(420px,92vw)] border-l border-border bg-card shadow-float motion-safe:animate-in motion-safe:slide-in-from-right-4"
            onClick={(event) => event.stopPropagation()}
          >
            <button
              type="button"
              aria-label={t("vault.close")}
              onClick={() => setSelectedId(null)}
              className="absolute right-3 top-3 z-10 flex h-7 w-7 items-center justify-center rounded-full text-muted-foreground hover:bg-sheen/[0.08] hover:text-foreground"
            >
              <X className="h-4 w-4" />
            </button>
            <Inspector
              key={selected.id}
              memory={selected}
              inMind={inMind.has(selected.id)}
              name={name}
              onChanged={onChanged}
              notify={notify}
              onUndoable={onUndoable}
            />
          </div>
        </div>
      )}
    </div>
  );
}

function GroupHeading({ kind, count }: { kind: MemoryKind; count: number }) {
  const t = useT();
  const Icon = KIND_STYLE[kind].icon;
  return (
    <div className="sticky top-0 z-[1] flex items-center gap-2.5 bg-card/95 px-3 pb-2 pt-5 backdrop-blur">
      <span
        className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md"
        style={{ backgroundColor: kindColor(kind, 0.14), color: kindColor(kind) }}
      >
        <Icon className="h-3.5 w-3.5" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-[13px] font-semibold text-foreground-strong">
          {t(`vault.kind_${kind}`)}
          <span className="ml-1.5 font-normal tabular-nums text-muted-foreground">{count}</span>
        </p>
        <p className="truncate text-[11px] text-muted-foreground">{t(`vault.kind_desc_${kind}`)}</p>
      </div>
    </div>
  );
}

function Row({
  memory,
  inMind,
  selected,
  checked,
  showDate = false,
  onSelect,
}: {
  memory: VaultMemory;
  inMind: boolean;
  selected: boolean;
  /** Set while picking several: the row shows a checkbox. */
  checked?: boolean;
  showDate?: boolean;
  onSelect: () => void;
}) {
  const t = useT();
  const { subject, body } = splitSubject(memory.text);
  return (
    <li
      id={`vault-row-${memory.id}`}
      role="option"
      aria-selected={checked ?? selected}
      data-testid="vault-row"
      onClick={onSelect}
      className={cn(
        "group ml-[30px] flex cursor-default items-baseline gap-2 rounded-lg px-2.5 py-1.5 transition-colors",
        (checked ?? selected) ? "bg-accent-soft" : "hover:bg-sheen/[0.04]",
        !memory.current && "opacity-60",
      )}
    >
      {checked !== undefined && (
        <input
          type="checkbox"
          readOnly
          checked={checked}
          tabIndex={-1}
          aria-label={memory.text}
          className="h-3.5 w-3.5 shrink-0 self-center"
        />
      )}
      <span
        className={cn("h-1.5 w-1.5 shrink-0 -translate-y-px rounded-full", inMind ? "bg-accent" : "bg-transparent")}
        title={inMind ? t("vault.shelf_in_mind") : undefined}
        aria-label={inMind ? t("vault.shelf_in_mind") : undefined}
      />
      <p className={cn("min-w-0 flex-1 text-[13px] leading-snug text-foreground", !memory.current && "line-through")}>
        {subject && <span className="font-semibold text-foreground-strong">{subject} </span>}
        <span className={subject ? "text-foreground-secondary" : undefined}>{body}</span>
      </p>
      {scopeOf(memory) !== "global" && (
        <span data-testid="vault-row-scope" className="shrink-0 rounded-full border border-border px-1.5 text-[10px] text-muted-foreground">
          {t(`memory_trust.scope_${scopeOf(memory)}`)}
        </span>
      )}
      {showDate && (
        <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">{formatDay(memory.recorded_at)}</span>
      )}
      {memory.pinned && <Pin className="h-3 w-3 shrink-0 text-[hsl(4_86%_58%)]" aria-label={t("vault.pinned")} />}
    </li>
  );
}

function Inspector({
  memory,
  inMind,
  name,
  onChanged,
  notify,
  onUndoable,
}: {
  memory: VaultMemory;
  inMind: boolean;
  name: string;
  onChanged: () => Promise<unknown>;
  notify: (message: string) => void;
  onUndoable: (message: string, token: string | null | undefined) => void;
}) {
  const t = useT();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(memory.text);
  const [forgetting, setForgetting] = useState(false);
  const history = useVaultHistory(memory.id);
  const versions = history.data?.versions ?? [];
  const Icon = KIND_STYLE[memory.kind].icon;
  const evidence = typeof memory.source?.evidence === "string" ? memory.source.evidence.trim() : "";
  const sourceFile = typeof memory.source?.file === "string" ? memory.source.file : "";
  const anchor = anchorOf(memory.source);

  const act = async (work: () => Promise<unknown>, done: string) => {
    try {
      await work();
      await onChanged();
      notify(done);
    } catch (error) {
      notify(error instanceof Error ? error.message : String(error));
    }
  };

  const save = async (event: FormEvent) => {
    event.preventDefault();
    const value = draft.trim();
    setEditing(false);
    if (value && value !== memory.text) await act(() => editMemory(memory.id, value), t("vault.updated"));
  };

  return (
    <div data-testid="vault-inspector" className="flex h-full min-h-0 flex-col overflow-y-auto px-6 py-6">
      <div className="flex items-center gap-2">
        <span
          className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium"
          style={{ backgroundColor: kindColor(memory.kind, 0.14), color: kindColor(memory.kind) }}
        >
          <Icon className="h-3 w-3" />
          {t(`vault.kind_${memory.kind}`)}
        </span>
        {memory.sensitivity === "sensitive" && (
          <span className="rounded-full border border-border px-2 py-0.5 text-[11px] text-muted-foreground">
            {t("vault.sensitive")}
          </span>
        )}
      </div>

      {editing ? (
        <form onSubmit={save} className="mt-4">
          <textarea
            autoFocus
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape") setEditing(false);
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void save(event);
              }
            }}
            rows={3}
            aria-label={t("vault.edit")}
            className="w-full resize-none rounded-xl border border-border-strong bg-background p-3 text-[17px] leading-snug text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
          <div className="mt-2 flex gap-2">
            <Button type="submit" size="sm">
              <Check /> {t("vault.save")}
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => setEditing(false)}>
              {t("vault.cancel")}
            </Button>
          </div>
        </form>
      ) : (
        <p
          className={cn(
            "mt-4 text-[20px] font-medium leading-snug tracking-tight text-foreground-strong",
            !memory.current && "text-muted-foreground line-through",
          )}
        >
          {memory.text}
        </p>
      )}

      {/* Where it lives in the model's head */}
      <div
        className={cn(
          "mt-5 flex items-start gap-3 rounded-xl border p-3",
          inMind ? "border-accent/30 bg-accent/[0.06]" : "border-border bg-sheen/[0.02]",
        )}
      >
        {inMind ? (
          <Compass className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
        ) : (
          <Search className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
        )}
        <div>
          <p className="text-[13px] font-medium text-foreground">
            {memory.current ? (inMind ? t("vault.status_in_mind") : t("vault.status_lookup")) : t("vault.status_closed")}
          </p>
          <p className="mt-0.5 text-[12px] leading-relaxed text-muted-foreground">
            {fill(
              memory.current ? (inMind ? t("vault.status_in_mind_hint") : t("vault.status_lookup_hint")) : t("vault.status_closed_hint"),
              { name },
            )}
          </p>
        </div>
      </div>

      {/* Origin */}
      <Section title={t("vault.origin_title")}>
        <p className="text-[13px] text-foreground">
          {t(`vault.origin_long_${memory.origin}`)}
          <span className="text-muted-foreground"> · {formatDay(memory.recorded_at)}</span>
        </p>
        {evidence && (
          <blockquote className="mt-2 flex gap-2 rounded-lg bg-sheen/[0.04] p-2.5 text-[12px] italic leading-relaxed text-foreground-secondary">
            <Quote className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground" />
            {evidence}
          </blockquote>
        )}
        {sourceFile && <p className="mt-1.5 font-mono text-[11px] text-muted-foreground">{sourceFile}</p>}
        {anchor && (
          <button
            type="button"
            data-testid="vault-source-link"
            onClick={() => {
              void jumpToMessage(anchor, { navigate: true }).then((found) => {
                if (!found) notify(t("memory_trust.source_not_loaded"));
              });
            }}
            className="mt-2 inline-flex items-center gap-1.5 rounded-md text-[12px] font-medium text-foreground underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <MessageSquareQuote className="h-3.5 w-3.5 text-muted-foreground" />
            {t("memory_trust.source_open")}
          </button>
        )}
      </Section>

      {memory.current && (
        <Section title={t("memory_trust.scope_title")}>
          <ScopeChoice
            value={scopeOf(memory)}
            onChange={(scope) => act(() => setMemoryScope(memory.id, scope), t("memory_trust.scope_saved"))}
          />
          <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">{fill(t("memory_trust.scope_hint"), { name })}</p>
        </Section>
      )}

      {memory.entities.length > 0 && (
        <Section title={t("vault.entities_title")}>
          <div className="flex flex-wrap gap-1.5">
            {memory.entities.map((entity) => (
              <span key={entity} className="rounded-full bg-sheen/[0.06] px-2.5 py-1 text-[12px] text-foreground">
                {entity}
              </span>
            ))}
          </div>
        </Section>
      )}

      {/* Timeline */}
      {versions.length > 1 && (
        <Section title={t("vault.timeline_title")}>
          <ol className="relative ml-1.5 border-l border-border" data-testid="vault-versions">
            {versions.map((version) => (
              <li key={version.id} className="relative pb-3 pl-4 last:pb-0">
                <span
                  className={cn(
                    "absolute -left-[5px] top-1.5 h-2.5 w-2.5 rounded-full border-2 border-card",
                    version.current ? "bg-accent" : "bg-muted-foreground/50",
                  )}
                />
                <p className="text-[11px] text-muted-foreground">
                  {formatDay(version.valid_from)}
                  {version.valid_to && ` – ${formatDay(version.valid_to)}`}
                  {version.current && <span className="ml-1.5 font-medium text-accent">{t("vault.now")}</span>}
                </p>
                <p className={cn("text-[13px]", version.current ? "text-foreground" : "text-muted-foreground")}>
                  {version.text}
                </p>
              </li>
            ))}
          </ol>
        </Section>
      )}

      {/* Actions */}
      <div className="mt-auto flex flex-wrap gap-1.5 pt-6">
        {memory.current && (
          <>
            <Action
              icon={memory.pinned ? <PinOff /> : <Pin />}
              label={memory.pinned ? t("vault.unpin") : t("vault.pin")}
              onClick={() => act(() => pinMemory(memory.id, !memory.pinned), memory.pinned ? t("vault.unpinned") : t("vault.pinned_done"))}
            />
            <Action
              icon={<Pencil />}
              label={t("vault.edit")}
              onClick={() => {
                setDraft(memory.text);
                setEditing(true);
              }}
            />
            <Action icon={<CircleOff />} label={t("vault.end")} onClick={() => act(() => endMemory(memory.id), t("vault.ended"))} />
          </>
        )}
        <Action icon={<Trash2 />} label={t("vault.forget")} danger onClick={() => setForgetting(true)} />
      </div>

      <ConfirmDialog
        open={forgetting}
        title={t("vault.forget_title")}
        description={fill(t("vault.forget_body"), { name })}
        confirmLabel={t("vault.forget")}
        items={[memory.text]}
        onClose={() => setForgetting(false)}
        onConfirm={async () => {
          const result = await forgetMemory(memory.id);
          setForgetting(false);
          await onChanged();
          onUndoable(t("vault.forgotten"), result.undo_token);
        }}
      />
    </div>
  );
}

/** A memory's scope, with anything unknown read as unmarked. */
export function scopeOf(memory: Pick<VaultMemory, "scope">): MemoryScope {
  return (MEMORY_SCOPES as readonly string[]).includes(memory.scope) ? (memory.scope as MemoryScope) : "global";
}

/** One control: where this memory belongs (unmarked, work, private). */
function ScopeChoice({ value, onChange }: { value: MemoryScope; onChange: (scope: MemoryScope) => void }) {
  const t = useT();
  return (
    <div role="radiogroup" aria-label={t("memory_trust.scope_title")} className="inline-flex h-8 items-center rounded-lg bg-sheen/[0.06] p-0.5">
      {MEMORY_SCOPES.map((scope) => (
        <button
          key={scope}
          type="button"
          role="radio"
          aria-checked={value === scope}
          data-testid={`vault-scope-${scope}`}
          onClick={() => value !== scope && onChange(scope)}
          className={cn(
            "h-7 whitespace-nowrap rounded-md px-3 text-[12px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            value === scope ? "bg-surface-raised text-foreground-strong shadow-sm" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {t(`memory_trust.scope_${scope}`)}
        </button>
      ))}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-6">
      <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-faint-foreground">{title}</h3>
      {children}
    </section>
  );
}

function Action({
  icon,
  label,
  onClick,
  danger = false,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex h-8 items-center gap-1.5 rounded-lg border border-border px-3 text-[12px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&>svg]:h-3.5 [&>svg]:w-3.5",
        danger
          ? "text-destructive hover:border-destructive/40 hover:bg-destructive/10"
          : "text-foreground hover:bg-sheen/[0.05]",
      )}
    >
      {icon}
      {label}
    </button>
  );
}

