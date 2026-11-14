import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Check, Loader2, Palette, Pencil, RotateCcw, Sparkles, Trash2, X } from "lucide-react";

import { DesignPreview } from "@/components/designs/DesignPreview";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { useThemeValue } from "@/hooks/useTheme";
import { useT } from "@/i18n";
import { fetchLeadSession, sendAgentChatMessage } from "@/lib/agentChatApi";
import { STANDARD_DESIGN_ID, type Design } from "@/lib/designs/designsApi";
import { cn } from "@/lib/utils";
import { useDesignsStore } from "@/store/designs";
import { useEventStore } from "@/store/events";

/**
 * Settings -> Designs (docs/designs.md).
 *
 * Top to bottom: a field to tell Dodaios how the app should look (the
 * sentence goes into the lead conversation as the person's own message, and
 * the design it makes switches on and appears here by itself); the person's
 * own designs with "Standard" first, each one click to switch, rename or
 * delete; then the designs Dodaios ships as examples. "Back to standard" in
 * the header switches every design off; the designs stay in the list.
 */

/** How long the page shows "Dodaios is making it" before it stops waiting. */
const PENDING_MS = 3 * 60_000;
const EXAMPLE_KEYS = ["designs.ask.example_1", "designs.ask.example_2", "designs.ask.example_3"] as const;

export function DesignsView() {
  const t = useT();
  const pushToast = useEventStore((s) => s.pushToast);
  const theme = useThemeValue();
  const { loaded, active, designs, load, activate, reset, remove, rename } = useDesignsStore();

  const [prompt, setPrompt] = useState("");
  const [sending, setSending] = useState(false);
  const [pendingSince, setPendingSince] = useState<number | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const knownIds = useRef<Set<string>>(new Set());

  useEffect(() => {
    void load();
  }, [load]);

  // A new design of the person's own arriving ends the wait.
  useEffect(() => {
    const ids = new Set(designs.map((d) => d.id));
    if (pendingSince !== null && designs.some((d) => !d.builtin && !knownIds.current.has(d.id))) {
      setPendingSince(null);
    }
    if (pendingSince === null) knownIds.current = ids;
  }, [designs, pendingSince]);

  useEffect(() => {
    if (pendingSince === null) return;
    const timer = window.setTimeout(() => setPendingSince(null), PENDING_MS);
    return () => window.clearTimeout(timer);
  }, [pendingSince]);

  const own = designs.filter((d) => !d.builtin);
  const builtin = designs.filter((d) => d.builtin);
  const isStandard = active === STANDARD_DESIGN_ID;

  const fail = (error: unknown) =>
    pushToast("error", t("designs.error").replace("{0}", () => (error as Error).message));

  async function run(id: string, action: () => Promise<void>) {
    setBusyId(id);
    try {
      await action();
    } catch (error) {
      fail(error);
    } finally {
      setBusyId(null);
    }
  }

  async function ask(event?: FormEvent) {
    event?.preventDefault();
    const text = prompt.trim();
    if (!text || sending) return;
    setSending(true);
    try {
      const session = await fetchLeadSession();
      await sendAgentChatMessage(session.session_id, t("designs.ask.request").replace("{0}", () => text));
      knownIds.current = new Set(designs.map((d) => d.id));
      setPendingSince(Date.now());
      setPrompt("");
      pushToast("success", t("designs.ask.sent"));
    } catch (error) {
      fail(error);
    } finally {
      setSending(false);
    }
  }

  return (
    <div
      data-testid="designs-view"
      className="flex h-full flex-col overflow-y-auto bg-background px-8 pb-10 scrollbar-jarvis"
    >
      <div className="w-full max-w-[1400px]">
        <PageHeader
          icon={<Palette />}
          title={t("designs.title")}
          description={t("designs.subtitle")}
          actions={
            <Button
              type="button"
              variant="outline"
              size="sm"
              data-testid="designs-reset"
              disabled={isStandard || busyId !== null}
              onClick={() =>
                void run(STANDARD_DESIGN_ID, async () => {
                  await reset();
                  pushToast("success", t("designs.reset_done"));
                })
              }
            >
              <RotateCcw aria-hidden />
              {t("designs.reset")}
            </Button>
          }
        />

        <form
          onSubmit={(e) => void ask(e)}
          className="mb-8 rounded-xl border border-border bg-card p-5"
          data-testid="designs-ask"
        >
          <label htmlFor="designs-ask-input" className="flex items-center gap-2 text-base font-medium text-foreground">
            <Sparkles className="h-4 w-4 text-accent" aria-hidden />
            {t("designs.ask.title")}
          </label>
          <p className="mt-1 text-sm text-muted-foreground">{t("designs.ask.body")}</p>
          <div className="mt-3 flex flex-wrap items-start gap-2">
            <textarea
              id="designs-ask-input"
              data-testid="designs-ask-input"
              value={prompt}
              rows={2}
              maxLength={600}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={(e: KeyboardEvent<HTMLTextAreaElement>) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  void ask();
                }
              }}
              placeholder={t("designs.ask.placeholder")}
              className="min-h-[44px] min-w-[240px] flex-1 resize-y rounded-lg border border-border-strong bg-input px-3 py-2 text-base text-foreground placeholder:text-faint-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
            <Button type="submit" disabled={!prompt.trim() || sending} data-testid="designs-ask-send">
              {sending ? <Loader2 className="animate-spin" aria-hidden /> : <Sparkles aria-hidden />}
              {t("designs.ask.send")}
            </Button>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {EXAMPLE_KEYS.map((key) => (
              <button
                key={key}
                type="button"
                onClick={() => setPrompt(t(key))}
                className="rounded-full border border-border bg-secondary px-3 py-1 text-sm text-foreground-secondary transition-colors hover:border-border-strong hover:text-foreground"
              >
                {t(key)}
              </button>
            ))}
          </div>
          {pendingSince !== null && (
            <p className="mt-3 flex items-center gap-2 text-sm text-muted-foreground" role="status" data-testid="designs-pending">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              {t("designs.ask.pending")}
            </p>
          )}
        </form>

        <h2 className="mb-3 text-lg font-semibold text-foreground-strong">{t("designs.own_title")}</h2>
        <div className="mb-8 grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-4" data-testid="designs-own">
          <DesignTile
            design={null}
            active={isStandard}
            busy={busyId === STANDARD_DESIGN_ID}
            appearance={theme}
            onPick={() => void run(STANDARD_DESIGN_ID, reset)}
          />
          {own.map((design) => (
            <DesignTile
              key={design.id}
              design={design}
              active={active === design.id}
              busy={busyId === design.id}
              appearance={theme}
              onPick={() => void run(design.id, () => activate(design.id))}
              onRename={(name) => void run(design.id, () => rename(design.id, name))}
              onDelete={() =>
                void run(design.id, async () => {
                  await remove(design.id);
                  pushToast("success", t("designs.deleted").replace("{0}", () => design.name));
                })
              }
            />
          ))}
          {loaded && own.length === 0 && (
            <p className="col-span-full -mt-1 text-sm text-muted-foreground sm:col-span-1 sm:self-center" data-testid="designs-own-empty">
              {t("designs.own_empty")}
            </p>
          )}
        </div>

        <h2 className="mb-1 text-lg font-semibold text-foreground-strong">{t("designs.examples_title")}</h2>
        <p className="mb-3 text-sm text-muted-foreground">{t("designs.examples_body")}</p>
        <div className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-4" data-testid="designs-examples">
          {builtin.map((design) => (
            <DesignTile
              key={design.id}
              design={design}
              active={active === design.id}
              busy={busyId === design.id}
              appearance={theme}
              onPick={() => void run(design.id, () => activate(design.id))}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

interface TileProps {
  design: Design | null;
  active: boolean;
  busy: boolean;
  appearance: "dark" | "light";
  onPick: () => void;
  onRename?: (name: string) => void;
  onDelete?: () => void;
}

function DesignTile({ design, active, busy, appearance, onPick, onRename, onDelete }: TileProps) {
  const t = useT();
  const [hover, setHover] = useState(false);
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [draft, setDraft] = useState(design?.name ?? "");

  const name = design ? builtinText(t, design, "name") : t("designs.standard_name");
  const description = design ? builtinText(t, design, "description") : t("designs.standard_description");
  const missingSide = design && !design[appearance];
  const id = design?.id ?? STANDARD_DESIGN_ID;

  function saveName() {
    const next = draft.trim();
    setEditing(false);
    if (design && next && next !== design.name) onRename?.(next);
  }

  return (
    <div
      data-testid={`design-tile-${id}`}
      data-active={active ? "true" : undefined}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      className={cn(
        "group flex flex-col gap-2 rounded-xl border bg-card p-2.5 transition-colors",
        active ? "border-accent" : "border-border hover:border-border-strong",
      )}
    >
      <button
        type="button"
        onClick={onPick}
        disabled={busy}
        aria-pressed={active}
        aria-label={t("designs.use").replace("{0}", () => name)}
        className="relative block w-full rounded-lg focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <DesignPreview design={design} appearance={appearance} animate={hover || active} />
        {busy && (
          <span className="absolute inset-0 flex items-center justify-center rounded-lg bg-scrim/30">
            <Loader2 className="h-5 w-5 animate-spin text-white" aria-hidden />
          </span>
        )}
      </button>
      <div className="flex min-h-[40px] items-start gap-1 px-0.5">
        <div className="min-w-0 flex-1">
          {editing ? (
            <input
              autoFocus
              value={draft}
              maxLength={40}
              aria-label={t("designs.rename")}
              onChange={(e) => setDraft(e.target.value)}
              onBlur={saveName}
              onKeyDown={(e) => {
                if (e.key === "Enter") saveName();
                if (e.key === "Escape") setEditing(false);
              }}
              className="w-full rounded-md border border-border-strong bg-input px-2 py-0.5 text-base text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          ) : (
            <p className="flex items-center gap-2 text-base font-medium text-foreground">
              <span className="truncate">{name}</span>
              {active && (
                <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-accent px-2 py-0.5 text-xs font-medium text-accent-foreground">
                  <Check className="h-3 w-3" aria-hidden />
                  {t("designs.active")}
                </span>
              )}
            </p>
          )}
          <p className="line-clamp-2 text-sm text-muted-foreground">
            {missingSide ? t(appearance === "dark" ? "designs.only_light" : "designs.only_dark") : description}
          </p>
        </div>
        {design && !design.builtin && !editing && (
          <div className="flex shrink-0 items-center gap-0.5">
            {confirming ? (
              <>
                <Button
                  type="button"
                  size="sm"
                  variant="destructive"
                  data-testid={`design-delete-confirm-${id}`}
                  onClick={() => {
                    setConfirming(false);
                    onDelete?.();
                  }}
                >
                  {t("designs.delete_confirm")}
                </Button>
                <Button type="button" size="icon" variant="ghost" aria-label={t("designs.cancel")} onClick={() => setConfirming(false)}>
                  <X aria-hidden />
                </Button>
              </>
            ) : (
              <>
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  aria-label={t("designs.rename")}
                  onClick={() => {
                    setDraft(design.name);
                    setEditing(true);
                  }}
                >
                  <Pencil aria-hidden />
                </Button>
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  aria-label={t("designs.delete")}
                  data-testid={`design-delete-${id}`}
                  onClick={() => setConfirming(true)}
                >
                  <Trash2 aria-hidden />
                </Button>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/** A built-in design's name or description in the person's language; own designs keep their words. */
function builtinText(t: (key: string) => string, design: Design, field: "name" | "description"): string {
  if (!design.builtin) return design[field];
  const key = `designs.builtin.${design.id.replace(/-/g, "_")}.${field}`;
  const localized = t(key);
  return localized !== key ? localized : design[field];
}
