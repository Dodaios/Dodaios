import { useEffect, useState } from "react";
import { Radio } from "lucide-react";

import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { BrandedSelect } from "@/components/ui/select";
import { Input } from "@/components/ui/input";

const ACCEPT = ["off", "observe", "auto"] as const;
const SOURCES = ["mail", "calendar", "github", "automation", "channel"] as const;
const MODES = ["explicit_only", "candidate", "ignore"] as const;

type Policy = { id: string; text: string; sources: string[]; auto: boolean };
type Source = { mode: string; senders: string[]; scopes: string[] };
type Decision = {
  id: string; action: string; policy_id: string; policy_text: string; outcome: string;
  event: { summary: string; source: string };
};
/** `GET /api/agent-chat/lead/triggers`: rules, drop counts and the decision log. */
export type Triggers = {
  settings: { accept: string; sources: Record<string, Source>; policies: Policy[] } & Record<string, unknown>;
  counts: Record<string, number>;
  waiting: number;
  log: Decision[];
};

const URL = "/api/agent-chat/lead/triggers";

export function droppedCount(counts: Record<string, number>): number {
  return Object.entries(counts).reduce((sum, [key, n]) => (key.startsWith("dropped_") ? sum + n : sum), 0);
}

/**
 * Event triggers: how the assistant reacts to mail, invites, code-host and
 * chat events. Observing is the default: the decision list shows what it would
 * have done and why, and one rule at a time can be allowed to act.
 */
export function LeadTriggersSetting() {
  const t = useT();
  const [state, setState] = useState<Triggers | null>(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    void fetch(URL).then((r) => (r.ok ? r.json() : null)).then((s: Triggers | null) => { if (live) setState(s); }, () => undefined);
    return () => { live = false; };
  }, []);
  if (!state || !Array.isArray(state.settings?.policies)) return null;
  const { settings } = state;
  const send = (input: RequestInfo, init: RequestInit, optimistic?: Triggers["settings"]) => {
    setError("");
    if (optimistic) setState({ ...state, settings: optimistic });
    void fetch(input, init).then(async (r) => {
      if (!r.ok) { setError(t("home.triggers.failed")); return; }
      setState((await r.json()) as Triggers);
    }, () => setError(t("home.triggers.failed")));
  };
  const save = (patch: Partial<Triggers["settings"]>) => {
    const next = { ...settings, ...patch };
    send(URL, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(next) }, next);
  };
  const on = settings.accept !== "off";
  return (
    <section className="space-y-1.5" data-testid="lead-triggers">
      <h3 className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
        <Radio aria-hidden className={cn("h-3.5 w-3.5", on && "text-primary")} />{t("home.triggers.title")}
      </h3>
      <div className="space-y-2 pl-5">
        <div className="flex items-center justify-between gap-2">
          <span className="text-sm text-foreground">{t("home.triggers.accept")}</span>
          <BrandedSelect value={settings.accept} ariaLabel={t("home.triggers.accept")} testId="lead-triggers-accept"
            className="h-7 w-36 text-xs" onValueChange={(accept) => save({ accept })}
            options={ACCEPT.map((mode) => ({ value: mode, label: t(`home.triggers.accept_${mode}`) }))} />
        </div>
        {on ? (
          <>
            {SOURCES.map((source) => (
              <div key={source} className="flex items-center justify-between gap-2">
                <span className="text-sm text-foreground">{t(`home.triggers.source_${source}`)}</span>
                <BrandedSelect value={settings.sources[source]?.mode ?? "explicit_only"} testId={`lead-triggers-source-${source}`}
                  ariaLabel={t(`home.triggers.source_${source}`)} className="h-7 w-36 text-xs"
                  onValueChange={(mode) => save({ sources: { ...settings.sources, [source]: { ...settings.sources[source], mode } } })}
                  options={MODES.map((mode) => ({ value: mode, label: t(`home.triggers.mode_${mode}`) }))} />
              </div>
            ))}
            <h4 className="pt-1 text-xs text-muted-foreground">{t("home.triggers.policies")}</h4>
            <ul className="space-y-1" data-testid="lead-triggers-policies">
              {settings.policies.map((policy) => (
                <li key={policy.id} className="space-y-0.5 text-sm text-foreground">
                  <span>{policy.text}</span>
                  <span className="flex gap-3 text-xs">
                    {policy.auto ? <span className="text-primary">{t("home.triggers.acts")}</span> : (
                      <button type="button" className="text-primary hover:underline" data-testid={`lead-triggers-promote-${policy.id}`}
                        onClick={() => send(`${URL}/policies/${policy.id}/promote`, { method: "POST" })}>{t("home.triggers.promote")}</button>
                    )}
                    <button type="button" className="text-muted-foreground hover:underline"
                      onClick={() => save({ policies: settings.policies.filter((p) => p.id !== policy.id) })}>{t("home.triggers.remove")}</button>
                  </span>
                </li>
              ))}
            </ul>
            <form className="flex gap-1.5" onSubmit={(e) => {
              e.preventDefault();
              const text = draft.trim();
              if (!text) return;
              setDraft("");
              save({ policies: [...settings.policies, { id: "", text, sources: [], auto: false }] });
            }}>
              <Input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder={t("home.triggers.policy_placeholder")}
                aria-label={t("home.triggers.policies")} data-testid="lead-triggers-draft" className="h-7 text-xs" />
              <button type="submit" className="shrink-0 text-xs text-primary hover:underline">{t("home.triggers.add")}</button>
            </form>
            <h4 className="pt-1 text-xs text-muted-foreground">{t("home.triggers.log")}</h4>
            <ul className="space-y-1.5" data-testid="lead-triggers-log">
              {state.log.length === 0 ? <li className="text-xs text-foreground-faint">{t("home.triggers.log_empty")}</li> : null}
              {state.log.slice(0, 8).map((entry) => (
                <li key={entry.id} className="text-xs text-foreground">
                  <span className="font-medium">{t(`home.triggers.action_${entry.action}`)}</span>{": "}{entry.event.summary}
                  <span className="block text-foreground-faint">{t("home.triggers.because").replace("{policy}", entry.policy_text)}</span>
                  {entry.outcome === "would_have" ? <span className="block text-foreground-faint">{t("home.triggers.outcome_would_have")}</span> : null}
                </li>
              ))}
            </ul>
            <p className="text-xs text-foreground-faint">
              {t("home.triggers.stats").replace("{dropped}", String(droppedCount(state.counts))).replace("{waiting}", String(state.waiting))}
            </p>
          </>
        ) : null}
        <p className="text-xs text-foreground-faint" data-testid="lead-triggers-hint">{error || t("home.triggers.hint")}</p>
      </div>
    </section>
  );
}
