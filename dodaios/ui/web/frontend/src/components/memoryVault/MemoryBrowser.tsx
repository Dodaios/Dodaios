/**
 * The memories list and the inspector beside it.
 *
 * A row is one sentence with its kind's glyph; a blue compass marks the
 * memories the assistant carries into every conversation. The inspector
 * explains one memory: what it says, where it came from (with the user's own
 * words when it was learned), every earlier version, and what can be done.
 */
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Check, CircleOff, Compass, Pencil, Pin, PinOff, Quote, Search, Trash2, X } from "lucide-react";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/memory/MemoryDialogs";
import {
  editMemory,
  endMemory,
  forgetMemory,
  pinMemory,
  useVaultHistory,
  type MemoryKind,
  type VaultMemory,
} from "@/lib/personalMemoryApi";
import { KIND_STYLE, kindColor } from "./kinds";

export type Shelf = "all" | "in_mind" | "pinned" | "history" | MemoryKind;

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
}) {
  const t = useT();
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

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = rows.find((m) => m.id === selectedId) ?? rows[0] ?? null;
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
    if (!rows.length) return;
    const index = Math.max(0, rows.findIndex((m) => m.id === selected?.id));
    const next = rows[Math.min(rows.length - 1, Math.max(0, index + step))];
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
        className="mx-auto min-h-0 w-full max-w-[860px] overflow-y-auto px-2 py-2 focus-visible:outline-none"
      >
        {rows.map((memory) => (
          <Row
            key={memory.id}
            memory={memory}
            inMind={inMind.has(memory.id)}
            selected={memory.id === selected?.id}
            onSelect={() => setSelectedId(memory.id)}
          />
        ))}
      </ul>
      <div className="hidden min-h-0 border-l border-border lg:block">
        {selected && (
          <Inspector
            key={selected.id}
            memory={selected}
            inMind={inMind.has(selected.id)}
            name={name}
            onChanged={onChanged}
            notify={notify}
          />
        )}
      </div>
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
            />
          </div>
        </div>
      )}
    </div>
  );
}

function Row({
  memory,
  inMind,
  selected,
  onSelect,
}: {
  memory: VaultMemory;
  inMind: boolean;
  selected: boolean;
  onSelect: () => void;
}) {
  const t = useT();
  const style = KIND_STYLE[memory.kind];
  const Icon = style.icon;
  return (
    <li
      id={`vault-row-${memory.id}`}
      role="option"
      aria-selected={selected}
      data-testid="vault-row"
      onClick={onSelect}
      className={cn(
        "group flex cursor-default items-start gap-3 rounded-xl px-3 py-2.5 transition-colors",
        selected ? "bg-accent-soft" : "hover:bg-sheen/[0.04]",
        !memory.current && "opacity-60",
      )}
    >
      <span
        className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg"
        style={{ backgroundColor: kindColor(memory.kind, 0.14), color: kindColor(memory.kind) }}
      >
        <Icon className="h-3.5 w-3.5" />
      </span>
      <div className="min-w-0 flex-1">
        <p className={cn("line-clamp-2 text-[13px] leading-snug text-foreground", !memory.current && "line-through")}>
          {memory.text}
        </p>
        <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
          {t(`vault.kind_${memory.kind}`)}
          {memory.entities.length > 0 && ` · ${memory.entities.join(", ")}`}
        </p>
      </div>
      <span className="mt-1 flex shrink-0 items-center gap-1 text-muted-foreground">
        {memory.pinned && <Pin className="h-3 w-3 text-[hsl(4_86%_58%)]" aria-label={t("vault.pinned")} />}
        {inMind && <Compass className="h-3.5 w-3.5 text-accent" aria-label={t("vault.shelf_in_mind")} />}
      </span>
    </li>
  );
}

function Inspector({
  memory,
  inMind,
  name,
  onChanged,
  notify,
}: {
  memory: VaultMemory;
  inMind: boolean;
  name: string;
  onChanged: () => Promise<unknown>;
  notify: (message: string) => void;
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
      </Section>

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
          await forgetMemory(memory.id);
          setForgetting(false);
          await onChanged();
          notify(t("vault.forgotten"));
        }}
      />
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

