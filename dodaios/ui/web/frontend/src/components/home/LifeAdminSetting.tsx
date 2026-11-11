import { useEffect, useState } from "react";
import { ClipboardList } from "lucide-react";

import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { BrandedSelect } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";

const URL = "/api/agent-chat/lead/life-admin";
const KINDS = ["birthday", "appointment", "renewal", "bill", "shopping", "document", "follow_up"] as const;
const DAYS = ["off", "mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;

type Draft = { kind: string; title?: string; subject?: string; body?: string; lines?: string[]; to?: string; message?: string; hold?: { title: string; date: string | null } };
export type LifeItem = { id: string; kind: string; title: string; due: string | null; status: string; draft: Draft | null };
type Settings = { enabled: boolean; digest_day: string; digest_time: string; in_brief: boolean; categories: Record<string, boolean>; timezone: string };
/** `GET /api/agent-chat/lead/life-admin`: the settings and the open items. */
export type LifeAdmin = { available: boolean; settings: Settings; items: LifeItem[] };

/** What a prepared draft says, in one short line for the list. */
export function draftLine(draft: Draft): string {
  if (draft.kind === "mail") return [draft.subject, draft.body].filter(Boolean).join(" — ");
  if (draft.kind === "gift_ideas" || draft.kind === "list") return (draft.lines ?? []).join("; ");
  return draft.hold ? `${draft.hold.title}${draft.hold.date ? ` · ${draft.hold.date}` : ""}` : "";
}

/**
 * Life admin: the birthdays, renewals, bills and appointments the assistant
 * noticed. Off until switched on; the digest is written, never spoken, and a
 * prepared draft is only a proposal that waits for the owner's yes.
 */
export function LifeAdminSetting() {
  const t = useT();
  const [state, setState] = useState<LifeAdmin | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    void fetch(URL).then((r) => (r.ok ? r.json() : null)).then((s: LifeAdmin | null) => { if (live) setState(s); }, () => undefined);
    return () => { live = false; };
  }, []);
  if (!state || !state.available) return null;
  const { settings } = state;
  const call = (input: string, init: RequestInit, then: (r: Response) => Promise<void>) => {
    setError("");
    void fetch(input, init).then(async (r) => {
      if (!r.ok) { setError(t("home.lifeadmin.failed")); return; }
      await then(r);
    }, () => setError(t("home.lifeadmin.failed")));
  };
  const save = (patch: Partial<Settings>) => {
    const next = { ...settings, ...patch, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone };
    setState({ ...state, settings: next });
    call(URL, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(next) },
      async (r) => setState((await r.json()) as LifeAdmin));
  };
  const act = (item: LifeItem, verb: "prepare" | "dismiss") => {
    call(`${URL}/items/${encodeURIComponent(item.id)}/${verb}`, { method: "POST" }, async (r) => {
      if (verb === "dismiss") {
        setState({ ...state, items: state.items.filter((i) => i.id !== item.id) });
        return;
      }
      const fresh = (await r.json()) as LifeItem;
      setState({ ...state, items: state.items.map((i) => (i.id === item.id ? fresh : i)) });
    });
  };
  const on = settings.enabled;
  return (
    <section className="space-y-1.5" data-testid="lead-life-admin">
      <h3 className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
        <ClipboardList aria-hidden className={cn("h-3.5 w-3.5", on && "text-primary")} />{t("home.lifeadmin.title")}
      </h3>
      <div className="space-y-2 pl-5">
        <div className="flex items-center justify-between gap-2">
          <label htmlFor="lead-life-admin-enabled" className="text-sm text-foreground">{t("home.lifeadmin.enable")}</label>
          <Switch id="lead-life-admin-enabled" checked={on} data-testid="lead-life-admin-enabled"
            onCheckedChange={(enabled) => save({ enabled })} />
        </div>
        {on ? (
          <>
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm text-foreground">{t("home.lifeadmin.digest")}</span>
              <div className="flex items-center gap-1.5">
                <BrandedSelect value={settings.digest_day} ariaLabel={t("home.lifeadmin.digest")} testId="lead-life-admin-day"
                  className="h-7 w-28 text-xs" onValueChange={(digest_day) => save({ digest_day })}
                  options={DAYS.map((day) => ({ value: day, label: t(`home.lifeadmin.day_${day}`) }))} />
                <input type="time" value={settings.digest_time} disabled={settings.digest_day === "off"}
                  aria-label={t("home.lifeadmin.digest_time")} data-testid="lead-life-admin-time"
                  onChange={(e) => e.target.value && save({ digest_time: e.target.value })}
                  className="rounded-md border border-border bg-transparent px-1.5 py-0.5 text-xs disabled:opacity-50" />
              </div>
            </div>
            <div className="flex items-center justify-between gap-2">
              <label htmlFor="lead-life-admin-brief" className="text-sm text-foreground">{t("home.lifeadmin.in_brief")}</label>
              <Switch id="lead-life-admin-brief" checked={settings.in_brief} data-testid="lead-life-admin-brief"
                onCheckedChange={(in_brief) => save({ in_brief })} />
            </div>
            <ul className="space-y-1" aria-label={t("home.lifeadmin.categories")}>
              {KINDS.map((kind) => (
                <li key={kind} className="flex items-center justify-between gap-2">
                  <label htmlFor={`lead-life-admin-kind-${kind}`} className="text-sm text-foreground">{t(`home.lifeadmin.kind_${kind}`)}</label>
                  <Switch id={`lead-life-admin-kind-${kind}`} checked={settings.categories[kind] !== false}
                    data-testid={`lead-life-admin-kind-${kind}`}
                    onCheckedChange={(next) => save({ categories: { ...settings.categories, [kind]: next } })} />
                </li>
              ))}
            </ul>
            {state.items.length === 0 ? (
              <p className="text-xs text-foreground-faint">{t("home.lifeadmin.empty")}</p>
            ) : (
              <ul className="space-y-1.5" aria-label={t("home.lifeadmin.items")} data-testid="lead-life-admin-items">
                {state.items.map((item) => (
                  <li key={item.id} className="rounded-md border border-border px-2 py-1.5" data-testid={`lead-life-admin-item-${item.id}`}>
                    <p className="text-sm text-foreground">{item.title}</p>
                    <p className="text-xs text-foreground-faint">
                      {t(`home.lifeadmin.kind_${item.kind}`)} · {item.due ?? t("home.lifeadmin.no_date")} · {t(`home.lifeadmin.status_${item.status}`)}
                    </p>
                    {item.draft ? (
                      <p className="mt-1 line-clamp-3 text-xs text-muted-foreground" data-testid="lead-life-admin-draft">
                        {t("home.lifeadmin.draft_not_sent")} {draftLine(item.draft)}
                      </p>
                    ) : null}
                    <div className="mt-1 flex gap-1.5">
                      <button type="button" onClick={() => act(item, "prepare")} data-testid="lead-life-admin-prepare"
                        className="rounded-md px-1.5 py-0.5 text-xs text-foreground hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                        {t(item.draft ? "home.lifeadmin.prepare_again" : "home.lifeadmin.prepare")}
                      </button>
                      <button type="button" onClick={() => act(item, "dismiss")} data-testid="lead-life-admin-dismiss"
                        className="rounded-md px-1.5 py-0.5 text-xs text-muted-foreground hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                        {t("home.lifeadmin.dismiss")}
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </>
        ) : null}
        <p className="text-xs text-foreground-faint" data-testid="lead-life-admin-hint">{error || t(on ? "home.lifeadmin.hint_on" : "home.lifeadmin.hint_off")}</p>
      </div>
    </section>
  );
}
