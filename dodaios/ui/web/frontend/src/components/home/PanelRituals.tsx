import { useState } from "react";
import { AudioLines, CircleAlert, LoaderCircle, Plus } from "lucide-react";

import { FOCUS, PANEL_ICON, PANEL_ROW, PANEL_ROW_BUTTON, PanelEmpty, PanelSection, ShowMore } from "@/components/home/panelParts";
import { Switch } from "@/components/ui/switch";
import { fill, useT } from "@/i18n";
import { clockOf, useRituals, useUpdateRitual, type ListedRitual } from "@/lib/ritualsApi";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";

/** How many rituals show before the rest folds away. */
export const RITUALS_SHOWN = 4;

/** Where a ritual stands today; "window" and "" say nothing about today. */
export type RitualState = "gathering" | "failed" | "ran" | "ready" | "window" | "";

/**
 * The one thing worth saying about a ritual today, the most pressing first:
 * it is gathering right now, the gathering failed, it already ran, or what
 * it wants ready is there. A ritual that ran and was gathered for again
 * afterwards is ready once more. With nothing to say about today, its time
 * window stands in.
 */
export function ritualState(ritual: ListedRitual): RitualState {
  const today = ritual.today;
  if (today?.prep_state === "running") return "gathering";
  if (today?.prep_state === "failed") return "failed";
  const ready = today?.prep_state === "ready";
  if (today && today.fired_ms !== null) {
    const gatheredSince = ready && today.prepared_ms !== null && today.prepared_ms > today.fired_ms;
    if (!gatheredSince) return "ran";
  }
  if (ready) return "ready";
  return ritual.window_from && ritual.window_to ? "window" : "";
}

/** A ritual's second line: the phrase that starts it, then where it stands today. */
export function ritualLine(ritual: ListedRitual, t: (key: string) => string): string {
  const state = ritualState(ritual);
  const fired = ritual.today?.fired_ms ?? null;
  const words =
    state === "gathering" ? t("rituals.state_gathering")
    : state === "failed" ? t("rituals.state_failed")
    : state === "ran" && fired !== null ? fill(t("rituals.state_ran"), { time: clockOf(fired) })
    : state === "ready" ? t("rituals.state_ready")
    : state === "window" ? `${ritual.window_from}–${ritual.window_to}`
    : "";
  const phrase = ritual.phrases[0] ? fill(t("rituals.phrase_quoted"), { phrase: ritual.phrases[0] }) : "";
  return [phrase, words].filter(Boolean).join(" · ");
}

/**
 * The person's rituals in the assistant's Library tab: the first four, the
 * rest one click away. A row names the ritual, the phrase that starts it and
 * where it stands today, and has a switch that turns it on or off; the row
 * itself opens the ritual in a dialog over the conversation. The last row
 * starts a new one.
 */
export function PanelRituals({ onOpen, onNew }: { onOpen: (ritualId: string) => void; onNew: () => void }) {
  const t = useT();
  const rituals = useRituals();
  const update = useUpdateRitual();
  const [open, setOpen] = useState(false);
  const rows = rituals.data?.rituals ?? [];
  const shown = open ? rows : rows.slice(0, RITUALS_SHOWN);
  const full = rituals.data ? rows.length >= rituals.data.limits.max_rituals : false;

  const toggle = (ritual: ListedRitual, enabled: boolean) => {
    // Each click answers for itself: a refusal is said even when another switch was flipped meanwhile.
    update.mutateAsync({ id: ritual.id, patch: { enabled } }).catch((error: unknown) => {
      useEventStore.getState().pushToast("error", error instanceof Error ? error.message : String(error));
    });
  };

  return (
    <PanelSection id="rituals" title={t("rituals.title")}>
      {shown.map((ritual) => {
        const state = ritualState(ritual);
        const line = ritualLine(ritual, t);
        return (
          <div key={ritual.id} className={PANEL_ROW}>
            <button type="button" data-testid={`assistant-ritual-${ritual.id}`} data-state={state}
              onClick={() => onOpen(ritual.id)} title={line ? `${ritual.name} · ${line}` : ritual.name}
              className={cn("flex min-w-0 flex-1 items-center gap-2.5 rounded-md text-left", FOCUS)}>
              <AudioLines aria-hidden strokeWidth={1.75} className={PANEL_ICON} />
              <span className="min-w-0 flex-1">
                <span className={cn("block truncate text-sm", ritual.enabled ? "text-foreground" : "text-muted-foreground")}>{ritual.name}</span>
                {line && <span className="block truncate text-sm text-muted-foreground">{line}</span>}
              </span>
              {state === "gathering" && (
                <LoaderCircle aria-hidden strokeWidth={1.75} className="h-3.5 w-3.5 shrink-0 text-success motion-safe:animate-spin" />
              )}
              {state === "failed" && <CircleAlert aria-hidden strokeWidth={1.75} className="h-3.5 w-3.5 shrink-0 text-destructive" />}
            </button>
            {/* The switch rests until the list has the answer, so it never shows a state the server does not have. */}
            <Switch aria-label={ritual.name} data-testid={`assistant-ritual-switch-${ritual.id}`}
              checked={ritual.enabled} disabled={update.isPending && update.variables?.id === ritual.id}
              onCheckedChange={(enabled) => toggle(ritual, enabled)} />
          </div>
        );
      })}
      {rows.length === 0 && (
        <PanelEmpty testId="assistant-rituals-empty">
          {rituals.isLoading ? t("common.loading") : t("rituals.empty")}
        </PanelEmpty>
      )}
      {rows.length > RITUALS_SHOWN && (
        <ShowMore testId="assistant-rituals-more" open={open} onToggle={() => setOpen((value) => !value)} />
      )}
      {!rituals.isLoading && !full && (
        <button type="button" data-testid="assistant-ritual-new" onClick={onNew} className={PANEL_ROW_BUTTON}>
          <Plus aria-hidden strokeWidth={1.75} className={PANEL_ICON} />
          <span className="min-w-0 flex-1 truncate text-sm text-muted-foreground">{t("rituals.new")}</span>
        </button>
      )}
    </PanelSection>
  );
}
