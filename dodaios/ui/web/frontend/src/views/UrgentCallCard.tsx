import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { useT } from "@/i18n";
import {
  URGENT_EVENTS,
  type NotifySettingsPatch,
  type UrgentCallSettings,
  type UrgentEvent,
} from "@/lib/remindersApi";
import { cn } from "@/lib/utils";

const EVENT_LABEL: Record<UrgentEvent, string> = {
  approval: "notify.urgent_event_approval",
  question: "notify.urgent_event_question",
  watchdog: "notify.urgent_event_watchdog",
};

const PHONE_RE = /^\+[1-9]\d{6,14}$/;

type NumberKey = "deadline_min" | "max_per_day" | "escalate_after_min";

/**
 * Settings → Notifications → "Call me for urgent decisions". Off by default.
 * Every field saves on its own (numbers and text when the field is left), the
 * backend clamps what it cannot take (`dodaios/notify/settings.py`).
 */
export function UrgentCallCard({
  value,
  saving,
  onSave,
}: {
  value: UrgentCallSettings;
  saving: boolean;
  onSave: (patch: NotifySettingsPatch) => Promise<void> | void;
}) {
  const t = useT();
  const [words, setWords] = useState(value.keywords.join(", "));
  const [phone, setPhone] = useState(value.phone_number);
  const [numbers, setNumbers] = useState<Record<NumberKey, string>>({
    deadline_min: String(value.deadline_min),
    max_per_day: String(value.max_per_day),
    escalate_after_min: String(value.escalate_after_min),
  });

  // What the server kept (clamped, trimmed) replaces what was typed.
  useEffect(() => {
    setWords(value.keywords.join(", "));
    setPhone(value.phone_number);
    setNumbers({
      deadline_min: String(value.deadline_min),
      max_per_day: String(value.max_per_day),
      escalate_after_min: String(value.escalate_after_min),
    });
  }, [value]);

  const save = (urgent: NonNullable<NotifySettingsPatch["urgent_call"]>) => void onSave({ urgent_call: urgent });
  const cleanPhone = phone.replace(/\s+/g, "");
  const phoneBad = cleanPhone !== "" && !PHONE_RE.test(cleanPhone);
  const idle = !value.enabled;

  const numberField = (key: NumberKey, label: string, hint?: string) => (
    <label className="flex items-center justify-between gap-6 text-sm">
      <span className="min-w-0">
        <span className="block text-foreground">{label}</span>
        {hint ? <span className="block text-muted-foreground">{hint}</span> : null}
      </span>
      <Input
        type="number"
        min={0}
        inputMode="numeric"
        value={numbers[key]}
        disabled={saving || idle}
        data-testid={`notify-urgent-${key}`}
        className="w-24 shrink-0"
        onChange={(event) => setNumbers({ ...numbers, [key]: event.target.value })}
        onBlur={() => {
          const n = Number.parseInt(numbers[key], 10);
          if (Number.isFinite(n) && n !== value[key]) save({ [key]: n });
          else setNumbers({ ...numbers, [key]: String(value[key]) });
        }}
      />
    </label>
  );

  return (
    <div data-testid="notify-urgent-card" className="divide-y divide-border self-start rounded-xl border border-border bg-card">
      <div className="px-5 py-4">
        <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
          <div className="min-w-[min(100%,14rem)] flex-1">
            <p className="text-base font-medium text-foreground">{t("notify.urgent_title")}</p>
            <p className="mt-0.5 text-sm text-muted-foreground">{t("notify.urgent_hint")}</p>
          </div>
          <Switch
            checked={value.enabled}
            disabled={saving}
            aria-label={t("notify.urgent_title")}
            data-testid="notify-urgent-enabled"
            onCheckedChange={(enabled) => save({ enabled })}
          />
        </div>
      </div>
      <div className={cn("space-y-4 px-5 py-4", idle && "opacity-60")}>
        <div>
          <p className="text-sm font-medium text-foreground">{t("notify.urgent_events_title")}</p>
          <ul className="mt-2 space-y-2">
            {URGENT_EVENTS.map((kind) => (
              <li key={kind} className="flex items-center justify-between gap-6">
                <span className="text-sm text-foreground">{t(EVENT_LABEL[kind])}</span>
                <Switch
                  checked={value.events[kind] !== false}
                  disabled={saving || idle}
                  aria-label={t(EVENT_LABEL[kind])}
                  data-testid={`notify-urgent-event-${kind}`}
                  onCheckedChange={(on) => save({ events: { [kind]: on } })}
                />
              </li>
            ))}
          </ul>
        </div>
        <label className="block text-sm">
          <span className="block text-foreground">{t("notify.urgent_keywords")}</span>
          <span className="mb-1.5 block text-muted-foreground">{t("notify.urgent_keywords_hint")}</span>
          <Input
            value={words}
            disabled={saving || idle}
            data-testid="notify-urgent-keywords"
            onChange={(event) => setWords(event.target.value)}
            onBlur={() => {
              const next = words.split(",").map((w) => w.trim()).filter(Boolean);
              if (next.join("|").toLowerCase() !== value.keywords.join("|")) save({ keywords: next });
            }}
          />
        </label>
        {numberField("deadline_min", t("notify.urgent_deadline"), t("notify.urgent_deadline_hint"))}
        {numberField("escalate_after_min", t("notify.urgent_escalate"), t("notify.urgent_escalate_hint"))}
        {numberField("max_per_day", t("notify.urgent_max_per_day"))}
        <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
          <span className="text-foreground">{t("notify.urgent_route")}</span>
          <div role="group" aria-label={t("notify.urgent_route")} className="flex gap-2">
            {(["desktop", "phone"] as const).map((route) => (
              <Button
                key={route}
                type="button"
                size="sm"
                variant={value.route === route ? "default" : "outline"}
                aria-pressed={value.route === route}
                disabled={saving || idle}
                data-testid={`notify-urgent-route-${route}`}
                onClick={() => save({ route })}
              >
                {t(route === "desktop" ? "notify.urgent_route_desktop" : "notify.urgent_route_phone")}
              </Button>
            ))}
          </div>
        </div>
        {value.route === "phone" ? (
          <label className="block text-sm">
            <span className="block text-foreground">{t("notify.urgent_phone")}</span>
            <span className="mb-1.5 block text-muted-foreground">{t("notify.urgent_phone_hint")}</span>
            <Input
              type="tel"
              value={phone}
              placeholder="+4915112345678"
              aria-invalid={phoneBad}
              disabled={saving || idle}
              data-testid="notify-urgent-phone"
              onChange={(event) => setPhone(event.target.value)}
              onBlur={() => {
                if (!phoneBad && cleanPhone !== value.phone_number) save({ phone_number: cleanPhone });
              }}
            />
            {phoneBad ? <span role="alert" className="mt-1 block text-destructive">{t("notify.urgent_phone_invalid")}</span> : null}
          </label>
        ) : null}
      </div>
    </div>
  );
}
