import { useCallback, useEffect, useState } from "react";
import { Cloud, Laptop, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { fill, useT } from "@/i18n";
import { fetchPrivacyOverview, setLearning, setScreenContext, type PrivacyOverview as Overview } from "@/lib/trustApi";
import { useEventStore } from "@/store/events";

function Section({ title, intro, children, testId }: { title: string; intro?: string; children: React.ReactNode; testId: string }) {
  return (
    <section data-testid={testId}>
      <h2 className="m-0 text-base font-semibold text-foreground">{title}</h2>
      {intro && <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{intro}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

function SwitchRow({ id, label, checked, onChange, disabled }: {
  id: string; label: string; checked: boolean; onChange: (next: boolean) => void; disabled?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-lg border border-border px-4 py-3">
      <label htmlFor={id} className="text-sm text-foreground">{label}</label>
      <Switch id={id} checked={checked} onCheckedChange={onChange} disabled={disabled} />
    </div>
  );
}

export function PrivacyOverview() {
  const t = useT();
  const setActive = useEventStore((s) => s.setActiveSection);
  const pushToast = useEventStore((s) => s.pushToast);
  const [data, setData] = useState<Overview | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await fetchPrivacyOverview());
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const flip = async (run: () => Promise<unknown>) => {
    if (busy) return;
    setBusy(true);
    try {
      await run();
      await load();
    } catch {
      pushToast("error", t("privacy.switch_failed"));
    } finally {
      setBusy(false);
    }
  };

  if (failed) return <p className="py-6 text-sm text-destructive">{t("trust.page.load_failed")}</p>;
  if (!data) {
    return (
      <p className="flex items-center gap-2 py-6 text-sm text-muted-foreground" data-testid="privacy-loading">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("trust.page.loading")}
      </p>
    );
  }

  const cloud = data.providers.filter((p) => !p.local);
  return (
    <div className="flex flex-col gap-10 pt-6" data-testid="privacy-overview">
      <h2 className="m-0 text-lg font-semibold text-foreground-strong">{t("privacy.title")}</h2>

      <Section title={t("privacy.accounts_title")} testId="privacy-accounts">
        {data.accounts.length === 0 ? (
          <p className="text-sm text-foreground-secondary">{t("privacy.accounts_empty")}</p>
        ) : (
          <ul className="divide-y divide-border rounded-lg border border-border">
            {data.accounts.map((account) => (
              <li key={account.id} className="flex items-center gap-3 px-4 py-2.5 text-sm">
                <span className="min-w-0 flex-1 truncate text-foreground">{account.label}</span>
                <span className={account.status === "connected" ? "text-xs text-muted-foreground" : "text-xs text-warning"}>
                  {t(`privacy.status_${account.status}`)}
                </span>
              </li>
            ))}
          </ul>
        )}
        <Button variant="link" size="sm" className="mt-2 px-0" onClick={() => setActive("plugins")}>
          {t("privacy.manage_accounts")}
        </Button>
      </Section>

      <Section title={t("privacy.learned_title")} intro={t("privacy.learned_intro")} testId="privacy-learned">
        <div className="flex flex-col gap-3">
          <p className="m-0 text-sm text-foreground">
            {data.memory.available ? fill(t("privacy.learned_count"), { count: data.memory.count }) : t("privacy.learned_off")}
          </p>
          <SwitchRow
            id="privacy-learning"
            label={t("privacy.learning_switch")}
            checked={data.memory.available && !data.memory.learning_paused}
            disabled={busy || !data.memory.available}
            onChange={(next) => void flip(() => setLearning(next))}
          />
          {data.memory.learning_paused && data.memory.paused_until && data.memory.paused_until !== "forever" && (
            <p className="m-0 text-xs text-muted-foreground">{fill(t("privacy.learning_paused_until"), { until: data.memory.paused_until })}</p>
          )}
          <Button variant="link" size="sm" className="self-start px-0" onClick={() => setActive("memory")}>
            {t("privacy.open_memory")}
          </Button>
        </div>
      </Section>

      <Section title={t("privacy.leaves_title")} intro={t("privacy.leaves_intro")} testId="privacy-leaves">
        {data.providers.length === 0 ? (
          <p className="text-sm text-foreground-secondary">{t("privacy.all_local")}</p>
        ) : (
          <ul className="divide-y divide-border rounded-lg border border-border">
            {data.providers.map((row) => (
              <li key={row.role} className="flex items-center gap-3 px-4 py-2.5 text-sm" data-testid={`privacy-provider-${row.role}`}>
                <span className="w-28 shrink-0 text-muted-foreground">{t(`privacy.role_${row.role}`)}</span>
                <span className="min-w-0 flex-1 truncate text-foreground">{row.label}</span>
                <span className="flex items-center gap-1 text-xs text-muted-foreground">
                  {row.local ? <Laptop className="h-3.5 w-3.5" aria-hidden /> : <Cloud className="h-3.5 w-3.5" aria-hidden />}
                  {t(row.local ? "privacy.local" : "privacy.cloud")}
                </span>
              </li>
            ))}
          </ul>
        )}
        {data.providers.length > 0 && cloud.length === 0 && (
          <p className="mt-2 text-sm text-foreground-secondary">{t("privacy.all_local")}</p>
        )}
        <Button variant="link" size="sm" className="mt-2 px-0" onClick={() => setActive("apikeys")}>
          {t("privacy.manage_providers")}
        </Button>
      </Section>

      <Section title={t("privacy.channels_title")} intro={t("privacy.channels_intro")} testId="privacy-channels">
        {data.channels.length === 0 ? (
          <p className="text-sm text-foreground-secondary">{t("privacy.channels_none")}</p>
        ) : (
          <ul className="flex flex-wrap gap-2">
            {data.channels.map((name) => (
              <li key={name} className="rounded-full border border-border px-3 py-1 text-sm capitalize text-foreground">{name}</li>
            ))}
          </ul>
        )}
      </Section>

      <Section title={t("privacy.screen_title")} intro={t("privacy.screen_intro")} testId="privacy-screen">
        <SwitchRow
          id="privacy-screen"
          label={t("privacy.screen_switch")}
          checked={data.screen_context}
          disabled={busy}
          onChange={(next) => void flip(() => setScreenContext(next))}
        />
      </Section>

      <p className="m-0 text-xs text-muted-foreground">{fill(t("privacy.recipients_line"), { count: data.known_recipients })}</p>
    </div>
  );
}
