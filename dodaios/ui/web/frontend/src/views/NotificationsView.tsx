import { useEffect, useState } from "react";
import { Bell, Loader2 } from "lucide-react";

import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { useT } from "@/i18n";
import {
  NOTIFY_KINDS,
  getNotifySettings,
  getTelegramState,
  putNotifySettings,
  sendTestNotification,
  type NotifyKind,
  type NotifySettings,
  type NotifySettingsPatch,
  type TelegramState,
  PHONE_KINDS,
  type PhoneKind,
} from "@/lib/remindersApi";
import { cn } from "@/lib/utils";

const PHONE_LABEL: Record<PhoneKind, string> = {
  decisions: "notify.phone_decisions",
  results: "notify.phone_results",
  failures: "notify.phone_failures",
  progress: "notify.phone_progress",
  brief: "notify.phone_brief",
};

const KIND_LABEL: Record<NotifyKind, string> = {
  reminder: "notify.kind_reminder",
  needs_you: "notify.kind_needs_you",
  approval: "notify.kind_approval",
  finished: "notify.kind_finished",
};

/**
 * Settings → Notifications: how the assistant reaches the person while the
 * app is in the background (`dodaios/notify`). One switch for desktop
 * notifications, one per kind, quiet hours, approvals in Telegram, and a test
 * button that shows exactly what a notification looks like. Every change
 * saves on the spot; the backend's gate reads the same file.
 */
export function NotificationsView() {
  const t = useT();
  const [settings, setSettings] = useState<NotifySettings | null>(null);
  const [telegram, setTelegram] = useState<TelegramState | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    getNotifySettings().then(
      (body) => { if (live) setSettings(body); },
      () => { if (live) setError(t("notify.load_failed")); },
    );
    getTelegramState().then(
      (body) => { if (live) setTelegram(body); },
      () => undefined,
    );
    return () => { live = false; };
    // The labels are read once; the language switch re-renders the texts anyway.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const save = async (patch: NotifySettingsPatch) => {
    if (!settings) return;
    setSaving(true);
    setError(null);
    try {
      setSettings(await putNotifySettings(patch));
    } catch {
      setError(t("notify.save_failed"));
    } finally {
      setSaving(false);
    }
  };

  const test = async () => {
    setTestResult(null);
    try {
      const verdict = await sendTestNotification();
      if (verdict.shown) setTestResult(t("notify.test_shown"));
      else if (verdict.held) setTestResult(t("notify.test_held").replace("{reason}", verdict.held));
      else setTestResult(t("notify.test_unsupported"));
    } catch {
      setTestResult(t("notify.test_unsupported"));
    }
  };

  const off = !settings || !settings.enabled;

  return (
    <div data-testid="notifications-view" className="flex h-full flex-col overflow-y-auto bg-background px-8 pb-10 scrollbar-jarvis">
      <div className="w-full max-w-[1400px]">
        <PageHeader
          icon={<Bell aria-hidden className="h-5 w-5" />}
          title={t("notify.title")}
          description={t("notify.subtitle")}
          actions={
            <Button variant="outline" size="sm" onClick={() => void test()} data-testid="notify-test">
              {t("notify.test")}
            </Button>
          }
        />
        {testResult ? <p role="status" className="mb-4 text-sm text-muted-foreground" data-testid="notify-test-result">{testResult}</p> : null}
        {error ? <p role="alert" className="mb-4 text-sm text-destructive">{error}</p> : null}

        <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,28rem),1fr))] gap-5">
          <div className="divide-y divide-border self-start rounded-xl border border-border bg-card">
            {!settings ? (
              <div className="flex h-40 items-center justify-center" role="status" aria-busy="true">
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-hidden />
              </div>
            ) : (
              <>
                <Row
                  label={t("notify.enabled")}
                  hint={t("notify.enabled_hint")}
                  control={
                    <Switch
                      checked={settings.enabled}
                      disabled={saving}
                      aria-label={t("notify.enabled")}
                      data-testid="notify-enabled"
                      onCheckedChange={(enabled) => void save({ enabled })}
                    />
                  }
                />
                <div className={cn("px-5 py-4", off && "opacity-60")}>
                  <p className="text-base font-medium text-foreground">{t("notify.kinds_title")}</p>
                  <ul className="mt-2 space-y-2">
                    {NOTIFY_KINDS.map((kind) => (
                      <li key={kind} className="flex items-center justify-between gap-6">
                        <span className="text-sm text-foreground">{t(KIND_LABEL[kind])}</span>
                        <Switch
                          checked={settings.kinds[kind] !== false}
                          disabled={saving || off}
                          aria-label={t(KIND_LABEL[kind])}
                          data-testid={`notify-kind-${kind}`}
                          onCheckedChange={(on) => void save({ kinds: { [kind]: on } })}
                        />
                      </li>
                    ))}
                  </ul>
                </div>
              </>
            )}
          </div>

          {settings ? (
            <div className="divide-y divide-border self-start rounded-xl border border-border bg-card">
              <Row
                label={t("notify.quiet_title")}
                hint={t("notify.quiet_hint")}
                control={
                  <Switch
                    checked={settings.quiet_hours.enabled}
                    disabled={saving || off}
                    aria-label={t("notify.quiet_title")}
                    data-testid="notify-quiet"
                    onCheckedChange={(enabled) => void save({ quiet_hours: { enabled } })}
                  />
                }
              >
                <div className={cn("mt-3 flex flex-wrap items-center gap-4 text-sm", !settings.quiet_hours.enabled && "opacity-60")}>
                  <label className="flex items-center gap-2 text-muted-foreground">
                    {t("notify.quiet_from")}
                    <input
                      type="time"
                      value={settings.quiet_hours.start}
                      disabled={saving || off || !settings.quiet_hours.enabled}
                      data-testid="notify-quiet-start"
                      onChange={(event) => void save({ quiet_hours: { start: event.target.value } })}
                      className="rounded-md border border-border bg-background px-2 py-1 text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    />
                  </label>
                  <label className="flex items-center gap-2 text-muted-foreground">
                    {t("notify.quiet_to")}
                    <input
                      type="time"
                      value={settings.quiet_hours.end}
                      disabled={saving || off || !settings.quiet_hours.enabled}
                      data-testid="notify-quiet-end"
                      onChange={(event) => void save({ quiet_hours: { end: event.target.value } })}
                      className="rounded-md border border-border bg-background px-2 py-1 text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    />
                  </label>
                </div>
              </Row>
              <Row
                label={t("notify.telegram_title")}
                hint={telegram && !telegram.connected ? t("notify.telegram_not_connected") : t("notify.telegram_hint")}
                control={
                  <Switch
                    checked={settings.telegram_approvals}
                    disabled={saving}
                    aria-label={t("notify.telegram_title")}
                    data-testid="notify-telegram"
                    onCheckedChange={(on) => void save({ telegram_approvals: on })}
                  />
                }
              />
              <Row label={t("notify.phone_title")} hint={t("notify.phone_hint")} control={null}>
                <ul className="mt-3 space-y-2">
                  {PHONE_KINDS.map((kind) => (
                    <li key={kind} className="flex items-center justify-between gap-6">
                      <span className="text-sm text-foreground">{t(PHONE_LABEL[kind])}</span>
                      <Switch
                        checked={settings.phone?.[kind] === true}
                        disabled={saving}
                        aria-label={t(PHONE_LABEL[kind])}
                        data-testid={`notify-phone-${kind}`}
                        onCheckedChange={(on) => void save({ phone: { [kind]: on } })}
                      />
                    </li>
                  ))}
                </ul>
              </Row>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function Row({
  label,
  hint,
  control,
  children,
}: {
  label: string;
  hint?: string;
  control: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <div className="px-5 py-4">
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
        <div className="min-w-[min(100%,14rem)] flex-1">
          <p className="text-base font-medium text-foreground">{label}</p>
          {hint && <p className="mt-0.5 text-sm text-muted-foreground">{hint}</p>}
        </div>
        <div className="ml-auto shrink-0">{control}</div>
      </div>
      {children}
    </div>
  );
}

export default NotificationsView;
