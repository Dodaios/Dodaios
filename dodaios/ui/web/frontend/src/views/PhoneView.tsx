/**
 * Phone — the companion app on the person's phone. A tab of the Settings hub
 * (System group), on the Computers page's surface.
 *
 * Three groups: pair a phone (a QR code that carries a one-time code and the
 * LAN link, with the honest notes about reachability and HTTPS), the paired
 * phones (one row each, remove), and messaging apps (the owner-only WhatsApp
 * channel behind its switch, with what is still missing said plainly).
 */
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { QRCodeSVG } from "qrcode.react";
import { Loader2, RefreshCw, Smartphone } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Switch } from "@/components/ui/switch";
import { useT, useUiLanguage } from "@/i18n";
import { OFFICIAL_REPO_URL } from "@/lib/branding";
import { mobileApi, type PairingCode } from "@/lib/mobileApi";
import { Row, Section, StatusDot } from "@/views/computers/surface";

export const phoneKeys = {
  status: ["mobile", "status"] as const,
};

const GUIDE_URL = `${OFFICIAL_REPO_URL}/blob/main/docs/mobile-companion.md`;

function fill(template: string, values: Record<string, string | number>): string {
  return Object.entries(values).reduce(
    (text, [key, value]) => text.split(`{${key}}`).join(String(value)),
    template,
  );
}

function formatDate(seconds: number, language: string): string {
  if (!seconds) return "";
  return new Date(seconds * 1000).toLocaleString(language, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Seconds left on a shown code, ticking once a second; null once it ran out. */
function useCountdown(code: PairingCode | null): number | null {
  const [left, setLeft] = useState<number | null>(null);
  useEffect(() => {
    if (!code) {
      setLeft(null);
      return;
    }
    const until = Date.now() + code.expires_in * 1000;
    const tick = () => setLeft(Math.max(0, Math.round((until - Date.now()) / 1000)));
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [code]);
  return left;
}

function PairCard({ reachable }: { reachable: boolean }) {
  const t = useT();
  const [code, setCode] = useState<PairingCode | null>(null);
  const left = useCountdown(code);
  const mint = useMutation({
    mutationFn: mobileApi.pairCode,
    onSuccess: (next) => setCode(next),
  });
  const expired = left === 0;
  const link = code?.urls[0] ?? "";
  const typeHint = useMemo(() => {
    if (!code) return "";
    const base = link ? link.split("#")[0] : "";
    return base ? fill(t("mobile.settings.pair_type_hint"), { url: base }) : "";
  }, [code, link, t]);

  return (
    <Row
      title={t("mobile.settings.pair_title")}
      description={t("mobile.settings.pair_body")}
      control={
        <Button
          variant={code ? "outline" : "default"}
          size="sm"
          onClick={() => mint.mutate()}
          disabled={mint.isPending || !reachable}
          data-testid="phone-pair-button"
        >
          {mint.isPending ? <Loader2 className="animate-spin" /> : <RefreshCw />}
          {code ? t("mobile.settings.pair_new_code") : t("mobile.settings.pair_button")}
        </Button>
      }
    >
      {mint.isError && (
        <p role="alert" className="text-sm text-destructive">{(mint.error as Error).message}</p>
      )}
      {code && (
        <div className="flex flex-col gap-4 pb-2 pt-1 sm:flex-row sm:items-start" data-testid="phone-pair-code">
          <div className="shrink-0 rounded-lg bg-white p-3" aria-hidden={expired}>
            <QRCodeSVG value={link || code.code} size={168} level="M" marginSize={0} />
          </div>
          <div className="min-w-0 space-y-1.5 text-sm">
            <p className="text-muted-foreground">{t("mobile.settings.code_label")}</p>
            <p className="font-mono text-lg tracking-[0.2em] text-foreground-strong" data-testid="phone-pair-code-text">
              {code.code.slice(0, 5)} {code.code.slice(5)}
            </p>
            <p className="text-xs text-foreground-faint">
              {expired
                ? t("mobile.settings.expired")
                : fill(t("mobile.settings.expires_in"), { seconds: left ?? code.expires_in })}
            </p>
            {typeHint && <p className="text-xs text-muted-foreground">{typeHint}</p>}
          </div>
        </div>
      )}
    </Row>
  );
}

export function PhoneView() {
  const t = useT();
  const language = useUiLanguage();
  const queryClient = useQueryClient();
  const status = useQuery({ queryKey: phoneKeys.status, queryFn: mobileApi.status, retry: false });
  const revoke = useMutation({
    mutationFn: mobileApi.revoke,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: phoneKeys.status }),
  });
  const whatsapp = useMutation({
    mutationFn: mobileApi.whatsapp,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: phoneKeys.status }),
  });

  const data = status.data;
  const reachable = Boolean(data && !data.listening.loopback_only);
  const wa = data?.whatsapp;
  const waTone = !wa?.enabled ? "off" : wa.running && wa.linked ? "ok" : "busy";
  const waLabel = !wa?.enabled
    ? t("mobile.settings.whatsapp_off")
    : wa.running && wa.linked
      ? t("mobile.settings.whatsapp_running")
      : t("mobile.settings.whatsapp_waiting");

  return (
    <div className="flex h-full min-h-0 w-full flex-col" data-testid="phone-view">
      <ScrollArea className="min-h-0 flex-1">
        <div className="mx-auto flex w-full max-w-4xl flex-col gap-8 px-6 pb-20 pt-10 sm:px-10">
          <header className="space-y-1 px-3 sm:px-4">
            <h1 className="flex items-center gap-2 text-xl font-semibold text-foreground-strong">
              <Smartphone className="h-5 w-5 text-muted-foreground" aria-hidden />
              {t("mobile.settings.title")}
            </h1>
            <p className="max-w-2xl text-sm text-muted-foreground">{t("mobile.settings.subtitle")}</p>
          </header>

          {status.isError && (
            <p role="alert" className="px-3 text-sm text-destructive sm:px-4">
              {t("mobile.settings.load_failed")}
            </p>
          )}

          <Section title={t("mobile.settings.pair_title")} testId="phone-pair-section">
            {data && data.listening.loopback_only && (
              <Row
                title={t("mobile.settings.not_reachable_title")}
                description={t("mobile.settings.not_reachable_body")}
                control={
                  <a className="text-sm text-accent underline-offset-4 hover:underline" href={GUIDE_URL} target="_blank" rel="noreferrer">
                    {t("mobile.settings.guide")}
                  </a>
                }
                testId="phone-not-reachable"
              />
            )}
            <PairCard reachable={reachable} />
            {data && !data.listening.https && (
              <Row description={t("mobile.settings.https_note")} title={<span className="sr-only">HTTPS</span>} testId="phone-https-note" />
            )}
          </Section>

          <Section title={t("mobile.settings.devices_title")} testId="phone-devices-section">
            {data && data.devices.length === 0 && (
              <Row title={t("mobile.settings.devices_empty")} />
            )}
            {data?.devices.map((device) => (
              <Row
                key={device.id}
                testId={`phone-device-${device.id}`}
                title={
                  <span className="flex items-center gap-2">
                    <StatusDot tone={device.push ? "ok" : "off"} />
                    {device.name}
                  </span>
                }
                description={[
                  fill(t("mobile.settings.device_paired_on"), { date: formatDate(device.created_at, language) }),
                  device.last_seen_at
                    ? fill(t("mobile.settings.device_last_seen"), { date: formatDate(device.last_seen_at, language) })
                    : null,
                  t(device.push ? "mobile.settings.device_push_on" : "mobile.settings.device_push_off"),
                ]
                  .filter(Boolean)
                  .join(" · ")}
                control={
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => revoke.mutate(device.id)}
                    disabled={revoke.isPending}
                    data-testid={`phone-remove-${device.id}`}
                  >
                    {t("mobile.settings.device_remove")}
                  </Button>
                }
              />
            ))}
          </Section>

          <Section title={t("mobile.settings.messaging_title")} testId="phone-messaging-section">
            <Row
              title={
                <span className="flex items-center gap-2">
                  <StatusDot tone={waTone} label={waLabel} />
                  {t("mobile.settings.whatsapp_title")}
                </span>
              }
              description={t("mobile.settings.whatsapp_body")}
              status={
                <span>
                  {waLabel}
                  {" · "}
                  {t("mobile.settings.whatsapp_missing")}{" "}
                  <a className="text-accent underline-offset-4 hover:underline" href={GUIDE_URL} target="_blank" rel="noreferrer">
                    {t("mobile.settings.guide")}
                  </a>
                  {wa?.enabled && !wa.running ? ` · ${t("mobile.settings.whatsapp_restart_note")}` : ""}
                  {wa?.start_error ? ` · ${wa.start_error}` : ""}
                </span>
              }
              control={
                <Switch
                  checked={Boolean(wa?.enabled)}
                  disabled={!data || whatsapp.isPending}
                  onCheckedChange={(checked) => whatsapp.mutate(checked)}
                  aria-label={t("mobile.settings.whatsapp_title")}
                  data-testid="phone-whatsapp-switch"
                />
              }
            />
          </Section>
        </div>
      </ScrollArea>
    </div>
  );
}
