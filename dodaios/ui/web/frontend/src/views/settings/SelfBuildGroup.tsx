/**
 * Settings → General → Self-building: `[self_build]` (docs/self-build.md).
 *
 * The master switch, how far the loop may go per kind (off / suggest / trial /
 * full), and the hard caps. Every change is one PUT to
 * `/api/self-build/settings`, written to jarvis.toml and applied at once — the
 * running loop reads the new values on its next decision, no restart.
 */
import { useEffect, useState } from "react";
import { Switch } from "@/components/ui/switch";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";
import { useSaveSelfBuildSettings, useSelfBuildSettings } from "@/hooks/useSelfBuild";
import {
  BUILD_KINDS,
  type Autonomy,
  type SelfBuildSettings,
  type SelfBuildSettingsPayload,
} from "@/lib/selfBuildApi";
import {
  SettingsCard,
  SettingsLinkButton,
  SettingsNote,
  SettingsRow,
  SettingsSection,
  SettingsSegmented,
} from "@/views/settings/SettingsLayout";

const LEVELS: readonly Autonomy[] = ["off", "suggest", "trial", "full"];

type NumberKey =
  | "silent_days"
  | "trial_days"
  | "trial_uses"
  | "max_builds_per_day"
  | "max_agents_per_week"
  | "max_open_trials"
  | "max_code_runs_per_day"
  | "max_rejections";

const LIMITS: readonly NumberKey[] = [
  "max_builds_per_day",
  "max_open_trials",
  "max_agents_per_week",
  "max_code_runs_per_day",
  "trial_days",
  "trial_uses",
  "max_rejections",
  "silent_days",
];

export function SelfBuildGroup() {
  const t = useT();
  const query = useSelfBuildSettings();
  const save = useSaveSelfBuildSettings();
  const setActive = useEventStore((s) => s.setActiveSection);
  const [error, setError] = useState<string | null>(null);
  const payload = query.data;

  const apply = (patch: Partial<SelfBuildSettings>) => {
    setError(null);
    save.mutate(patch, {
      onError: (err) => setError(fill(t("settings_view.self_build.save_error"), { detail: err.message })),
    });
  };

  return (
    <SettingsSection
      title={t("settings_view.self_build.title")}
      description={t("settings_view.self_build.description")}
      actions={
        <SettingsLinkButton onClick={() => setActive("self-build")}>
          {t("settings_view.self_build.open_view")}
        </SettingsLinkButton>
      }
    >
      {query.isError ? (
        <SettingsNote tone="error">{t("settings_view.self_build.unavailable")}</SettingsNote>
      ) : !payload ? (
        <SettingsCard><div className="h-24" aria-busy="true" /></SettingsCard>
      ) : (
        <SettingsCard>
          <SettingsRow
            id="settings-self-build-enabled"
            testId="self-build-enabled"
            title={t("settings_view.self_build.enabled_title")}
            description={t("settings_view.self_build.enabled_description")}
            control={
              <Switch
                checked={payload.settings.enabled}
                disabled={save.isPending}
                aria-label={t("settings_view.self_build.enabled_title")}
                onCheckedChange={(next) => apply({ enabled: next })}
              />
            }
          />
          <SettingsRow
            title={t("settings_view.self_build.autonomy_title")}
            description={t("settings_view.self_build.autonomy_description")}
            className={cn(!payload.settings.enabled && "opacity-60")}
          >
            <div className="divide-y divide-border rounded-md border border-border">
              {BUILD_KINDS.map((kind) => (
                <div key={kind} className="flex flex-wrap items-center justify-between gap-3 px-3 py-2" data-testid={`self-build-autonomy-${kind}`}>
                  <span className="text-base text-foreground">{t(`settings_view.self_build.kinds.${kind}`)}</span>
                  <SettingsSegmented<Autonomy>
                    value={payload.settings[kind]}
                    ariaLabel={t(`settings_view.self_build.kinds.${kind}`)}
                    disabled={save.isPending || !payload.settings.enabled}
                    options={LEVELS.map((level) => ({
                      value: level,
                      label: t(`settings_view.self_build.levels.${level}`),
                    }))}
                    onChange={(level) => apply({ [kind]: level })}
                  />
                </div>
              ))}
            </div>
          </SettingsRow>
          <SettingsRow
            title={t("settings_view.self_build.limits_title")}
            description={t("settings_view.self_build.limits_description")}
          >
            <div className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
              {LIMITS.map((key) => (
                <NumberField
                  key={key}
                  name={key}
                  payload={payload}
                  label={t(`settings_view.self_build.limits.${key}`)}
                  disabled={save.isPending}
                  onCommit={(value) => apply({ [key]: value })}
                />
              ))}
            </div>
          </SettingsRow>
        </SettingsCard>
      )}
      {error && <SettingsNote tone="error" className="mt-2">{error}</SettingsNote>}
    </SettingsSection>
  );
}

function NumberField({
  name,
  payload,
  label,
  disabled,
  onCommit,
}: {
  name: NumberKey;
  payload: SelfBuildSettingsPayload;
  label: string;
  disabled: boolean;
  onCommit: (value: number) => void;
}) {
  const current = payload.settings[name];
  const bounds = payload.bounds[name];
  const min = bounds?.min ?? 0;
  const max = bounds?.max ?? 1000;
  const [text, setText] = useState(String(current));
  useEffect(() => setText(String(current)), [current]);
  const commit = () => {
    const value = Math.round(Number(text));
    if (!Number.isFinite(value) || text.trim() === "") {
      setText(String(current));
      return;
    }
    const clamped = Math.min(max, Math.max(min, value));
    setText(String(clamped));
    if (clamped !== current) onCommit(clamped);
  };
  return (
    <label className="flex items-center justify-between gap-3" data-testid={`self-build-limit-${name}`}>
      <span className="min-w-0 text-sm text-foreground">{label}</span>
      <input
        type="number"
        inputMode="numeric"
        min={min}
        max={max}
        value={text}
        disabled={disabled}
        aria-label={label}
        onChange={(event) => setText(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") (event.target as HTMLInputElement).blur();
        }}
        className="h-8 w-20 shrink-0 rounded-md border border-border-strong bg-input px-2 text-right text-sm tabular-nums text-foreground focus-visible:border-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      />
    </label>
  );
}
