/**
 * Graphics & performance for one game: what this PC is, four one-click
 * presets, resolution tiles from HD to 5K, the FPS limit up to unlimited,
 * and every rendering, detail, ray-tracing and effect setting in cards.
 * The game's own video options (as the game names them) close the page.
 */
import type { ReactNode } from "react";
import {
  Cpu,
  Crown,
  Gauge,
  Info,
  MemoryStick,
  Monitor,
  MonitorPlay,
  Sparkles,
  Sun,
  Wand2,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { GameSettingRow } from "@/components/games/GameControls";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { useGameSystem } from "@/hooks/useGames";
import { useT } from "@/i18n";
import type {
  GameDefinition,
  GamePreset,
  GameProfile,
  GameSetting,
  GameSettingValue,
  ProfilePatch,
  SystemInfo,
} from "@/lib/gamesApi";
import { cn } from "@/lib/utils";

const RESOLUTION_NAMES: Record<string, string> = {
  "1280x720": "HD",
  "1600x900": "HD+",
  "1920x1080": "Full HD",
  "2560x1080": "UW Full HD",
  "2560x1440": "QHD",
  "3440x1440": "UWQHD",
  "3840x1600": "UW4K",
  "3840x2160": "4K UHD",
  "5120x1440": "DQHD",
  "5120x2160": "5K2K",
  "5120x2880": "5K",
};

const PRESET_ICONS: Record<GamePreset["id"], LucideIcon> = {
  competitive: Zap,
  balanced: Gauge,
  quality: Sparkles,
  epic: Crown,
};

/** Settings drawn by hand at the top of the display card, not as rows. */
const CUSTOM_DRAWN = new Set(["perf_resolution", "perf_fps_cap", "perf_refresh_rate"]);

type Values = Record<string, GameSettingValue>;

function primaryMonitor(system: SystemInfo | undefined) {
  return system?.monitors.find((m) => m.primary) ?? system?.monitors[0] ?? null;
}

/**
 * A preset's values for THIS PC: "monitor" becomes the highest FPS option the
 * monitor can show, and the resolution and refresh rate follow the monitor.
 */
export function resolvePreset(
  preset: GamePreset,
  settings: Record<string, GameSetting>,
  system: SystemInfo | undefined,
): Values {
  const monitor = primaryMonitor(system);
  const out: Values = {};
  for (const [key, value] of Object.entries(preset.values)) {
    if (value === "monitor") {
      const hz = monitor?.max_refresh_hz ?? null;
      const options = settings[key]?.options ?? [];
      const fitting = options.filter((o) => Number(o) > 0 && hz !== null && Number(o) <= hz);
      if (fitting.length > 0) out[key] = fitting[fitting.length - 1];
      continue;
    }
    out[key] = value;
  }
  if (monitor) {
    const native = `${monitor.width}x${monitor.height}`;
    if (settings.perf_resolution?.options?.includes(native)) out.perf_resolution = native;
    const hz = `${monitor.max_refresh_hz} Hz`;
    if (settings.perf_refresh_rate?.options?.includes(hz)) out.perf_refresh_rate = hz;
  }
  return out;
}

function matchesPreset(resolved: Values, effective: (key: string) => GameSettingValue | null): boolean {
  return Object.entries(resolved).every(([key, value]) => effective(key) === value);
}

function Card({
  eyebrow,
  title,
  icon: Icon,
  children,
  className,
  testId,
}: {
  eyebrow: string;
  title: string;
  icon: LucideIcon;
  children: ReactNode;
  className?: string;
  testId?: string;
}) {
  return (
    <section
      data-testid={testId}
      className={cn(
        "relative overflow-hidden rounded-xl border border-border bg-card/80 px-5 pb-2 pt-4",
        "before:absolute before:inset-y-0 before:left-0 before:w-[3px] before:bg-[var(--game-accent)]",
        className,
      )}
    >
      <header className="mb-1 flex items-center gap-2.5">
        <Icon className="h-4 w-4 text-[var(--game-accent)]" aria-hidden />
        <div>
          <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">{eyebrow}</p>
          <h3 className="text-sm font-semibold text-foreground-strong">{title}</h3>
        </div>
      </header>
      {children}
    </section>
  );
}

export function PerformancePanel({
  game,
  profile,
  presets,
  onPatch,
}: {
  game: GameDefinition;
  profile: GameProfile;
  presets: GamePreset[];
  onPatch: (patch: ProfilePatch) => void;
}) {
  const t = useT();
  const system = useGameSystem();
  const settings: Record<string, GameSetting> = Object.fromEntries(
    game.sections.flatMap((s) => s.settings).map((s) => [s.key, s]),
  );
  const effective = (key: string): GameSettingValue | null =>
    profile.values[key] ?? settings[key]?.default ?? null;
  const set = (key: string, value: GameSettingValue | null) => onPatch({ values: { [key]: value } });
  const section = (id: string) => game.sections.find((s) => s.id === id)?.settings ?? [];
  const monitor = primaryMonitor(system.data);
  const resolved = presets.map((preset) => ({
    preset,
    values: resolvePreset(preset, settings, system.data),
  }));
  const activePreset = resolved.find((r) => matchesPreset(r.values, effective))?.preset.id ?? null;
  const recommended = system.data?.recommended_preset ?? null;

  const applyPreset = (id: GamePreset["id"]) => {
    const match = resolved.find((r) => r.preset.id === id);
    if (match) onPatch({ values: match.values });
  };

  const rows = (id: string, skip: Set<string> = new Set()) =>
    section(id)
      .filter((s) => !skip.has(s.key))
      .map((s) => (
        <GameSettingRow key={s.key} setting={s} value={profile.values[s.key]} onChange={(v) => set(s.key, v)} />
      ));

  const resolution = String(effective("perf_resolution") ?? "");
  const fps = String(effective("perf_fps_cap") ?? "");
  const refresh = String(effective("perf_refresh_rate") ?? "");
  const native = monitor ? `${monitor.width}x${monitor.height}` : null;

  return (
    <div className="flex flex-col gap-5" data-testid="games-performance">
      <SystemStrip
        system={system.data}
        loading={system.isLoading}
        recommended={recommended}
        onApplyRecommended={() => recommended && applyPreset(recommended)}
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" role="radiogroup" aria-label={t("games.perf.presets")}>
        {resolved.map(({ preset }) => {
          const Icon = PRESET_ICONS[preset.id];
          const active = activePreset === preset.id;
          return (
            <button
              key={preset.id}
              type="button"
              role="radio"
              aria-checked={active}
              data-testid={`games-preset-${preset.id}`}
              onClick={() => applyPreset(preset.id)}
              className={cn(
                "group relative overflow-hidden rounded-xl border p-4 text-left transition-all",
                active
                  ? "border-[var(--game-accent)] bg-[var(--game-accent-soft)] shadow-[0_0_24px_var(--game-accent-glow)]"
                  : "border-border bg-card/70 hover:-translate-y-0.5 hover:border-border-strong",
              )}
            >
              <div
                aria-hidden
                className="pointer-events-none absolute -right-6 -top-6 h-24 w-24 rounded-full bg-[var(--game-accent-glow)] opacity-0 blur-2xl transition-opacity group-hover:opacity-100"
              />
              <div className="flex items-center justify-between">
                <Icon
                  className={cn("h-5 w-5", active ? "text-[var(--game-accent)]" : "text-muted-foreground")}
                  aria-hidden
                />
                {recommended === preset.id && (
                  <span className="rounded-full border border-[var(--game-accent)] px-2 py-0.5 font-mono text-[9px] uppercase tracking-[0.14em] text-[var(--game-accent)]">
                    {t("games.perf.recommended")}
                  </span>
                )}
              </div>
              <p className="mt-3 text-base font-semibold text-foreground-strong">
                {t(`games.perf.preset_${preset.id}`)}
              </p>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                {t(`games.perf.preset_${preset.id}_hint`)}
              </p>
            </button>
          );
        })}
      </div>

      <Card eyebrow={t("games.perf.eyebrow_display")} title={t("games.perf.display")} icon={Monitor} testId="games-perf-display">
        <p className="mb-2 mt-3 text-xs font-medium text-muted-foreground">{t("games.perf.resolution")}</p>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4 2xl:grid-cols-6" role="radiogroup" aria-label={t("games.perf.resolution")}>
          {(settings.perf_resolution?.options ?? []).map((value) => {
            const [w, h] = value.split("x");
            const active = resolution === value;
            const isNative = native === value;
            return (
              <button
                key={value}
                type="button"
                role="radio"
                aria-checked={active}
                data-testid={`games-res-${value}`}
                onClick={() => set("perf_resolution", value)}
                className={cn(
                  "relative rounded-lg border px-3 py-2.5 text-left transition-all",
                  active
                    ? "border-[var(--game-accent)] bg-[var(--game-accent-soft)] shadow-[0_0_16px_var(--game-accent-glow)]"
                    : "border-border bg-background/50 hover:border-border-strong",
                )}
              >
                <span className="block text-sm font-semibold text-foreground-strong">{RESOLUTION_NAMES[value] ?? value}</span>
                <span className="block font-mono text-[11px] tabular-nums text-muted-foreground">
                  {w} × {h}
                </span>
                {isNative && (
                  <span className="absolute right-2 top-2 font-mono text-[9px] uppercase tracking-[0.12em] text-[var(--game-accent)]">
                    {t("games.perf.your_monitor")}
                  </span>
                )}
              </button>
            );
          })}
        </div>

        <div className="mt-5 grid gap-5 lg:grid-cols-2">
          <div>
            <p className="mb-2 text-xs font-medium text-muted-foreground">{t("games.perf.fps_limit")}</p>
            <ChipRow
              label={t("games.perf.fps_limit")}
              options={settings.perf_fps_cap?.options ?? []}
              value={fps}
              highlight={(o) => o === "Unlimited"}
              format={(o) => (o === "Unlimited" ? t("games.perf.unlimited") : o)}
              onChange={(o) => set("perf_fps_cap", o)}
            />
            <p className="mt-2 text-xs text-muted-foreground">{t("games.perf.fps_hint")}</p>
          </div>
          <div>
            <p className="mb-2 text-xs font-medium text-muted-foreground">{t("games.perf.refresh")}</p>
            <ChipRow
              label={t("games.perf.refresh")}
              options={settings.perf_refresh_rate?.options ?? []}
              value={refresh}
              highlight={(o) => monitor !== null && o === `${monitor.max_refresh_hz} Hz`}
              onChange={(o) => set("perf_refresh_rate", o)}
            />
          </div>
        </div>
        <div className="mt-3">{rows("perf_display", CUSTOM_DRAWN)}</div>
      </Card>

      <div className="grid gap-5 2xl:grid-cols-2">
        <Card eyebrow={t("games.perf.eyebrow_rendering")} title={t("games.perf.rendering")} icon={Wand2}>
          {rows("perf_rendering")}
        </Card>
        <Card eyebrow={t("games.perf.eyebrow_raytracing")} title={t("games.perf.raytracing")} icon={Sun}>
          {rows("perf_raytracing")}
        </Card>
      </div>

      <Card eyebrow={t("games.perf.eyebrow_detail")} title={t("games.perf.detail")} icon={Sparkles}>
        {rows("perf_detail")}
      </Card>

      <Card eyebrow={t("games.perf.eyebrow_effects")} title={t("games.perf.effects")} icon={MonitorPlay}>
        <div className="grid gap-x-6 py-2 sm:grid-cols-2 lg:grid-cols-3">
          {section("perf_effects").map((s) => (
            <label key={s.key} className="flex items-center justify-between gap-3 border-b border-border/50 py-2.5">
              <span className="text-sm text-foreground">{s.label}</span>
              <Switch
                checked={effective(s.key) === true}
                aria-label={s.label}
                onCheckedChange={(next) => set(s.key, next)}
              />
            </label>
          ))}
        </div>
      </Card>

      {section("video").length > 0 && (
        <Card
          eyebrow={t("games.perf.eyebrow_ingame")}
          title={t("games.perf.ingame").replace("{0}", game.name)}
          icon={Info}
        >
          <p className="text-xs text-muted-foreground">{t("games.perf.ingame_hint")}</p>
          {rows("video")}
        </Card>
      )}
    </div>
  );
}

function ChipRow({
  label,
  options,
  value,
  onChange,
  highlight,
  format,
}: {
  label: string;
  options: string[];
  value: string;
  onChange: (value: string) => void;
  highlight?: (option: string) => boolean;
  format?: (option: string) => string;
}) {
  return (
    <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label={label}>
      {options.map((option) => {
        const active = option === value;
        return (
          <button
            key={option}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(option)}
            className={cn(
              "rounded-md border px-2.5 py-1.5 font-mono text-xs tabular-nums transition-all",
              active
                ? "border-[var(--game-accent)] bg-[var(--game-accent)] font-semibold text-black shadow-[0_0_14px_var(--game-accent-glow)]"
                : highlight?.(option)
                  ? "border-[var(--game-accent)]/60 text-[var(--game-accent)] hover:bg-[var(--game-accent-soft)]"
                  : "border-border text-muted-foreground hover:border-border-strong hover:text-foreground",
            )}
          >
            {format ? format(option) : option}
          </button>
        );
      })}
    </div>
  );
}

function SystemStrip({
  system,
  loading,
  recommended,
  onApplyRecommended,
}: {
  system: SystemInfo | undefined;
  loading: boolean;
  recommended: GamePreset["id"] | null;
  onApplyRecommended: () => void;
}) {
  const t = useT();
  const monitor = primaryMonitor(system);
  const gpu = system?.gpus[0];
  const items: { icon: LucideIcon; label: string; value: string }[] = [
    {
      icon: MonitorPlay,
      label: t("games.perf.gpu"),
      value: gpu ? `${gpu.name}${gpu.vram_gb ? ` · ${Math.round(gpu.vram_gb)} GB` : ""}` : "—",
    },
    { icon: Cpu, label: t("games.perf.cpu"), value: system?.cpu ?? "—" },
    { icon: MemoryStick, label: t("games.perf.ram"), value: system?.ram_gb ? `${system.ram_gb} GB` : "—" },
    {
      icon: Monitor,
      label: t("games.perf.monitor"),
      value: monitor
        ? `${monitor.width} × ${monitor.height} · ${monitor.refresh_hz} Hz`
        : "—",
    },
  ];
  const lowRefresh = monitor !== null && monitor.max_refresh_hz > monitor.refresh_hz + 5;

  return (
    <section
      data-testid="games-system"
      className="rounded-xl border border-border bg-gradient-to-br from-card to-background p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
          {loading ? t("games.perf.detecting") : t("games.perf.your_pc")}
        </p>
        {recommended && (
          <Button type="button" size="sm" onClick={onApplyRecommended} data-testid="games-apply-recommended">
            <Sparkles aria-hidden />
            {t("games.perf.apply_recommended").replace("{0}", t(`games.perf.preset_${recommended}`))}
          </Button>
        )}
      </div>
      <dl className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {items.map(({ icon: Icon, label, value }) => (
          <div key={label} className="flex min-w-0 items-start gap-2.5">
            <Icon className="mt-0.5 h-4 w-4 shrink-0 text-[var(--game-accent)]" aria-hidden />
            <div className="min-w-0">
              <dt className="text-[11px] text-muted-foreground">{label}</dt>
              <dd className="truncate text-sm font-medium text-foreground-strong" title={value}>
                {value}
              </dd>
            </div>
          </div>
        ))}
      </dl>
      {lowRefresh && monitor && (
        <p
          role="note"
          data-testid="games-refresh-tip"
          className="mt-3 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-foreground"
        >
          {t("games.perf.refresh_tip")
            .replace("{0}", String(monitor.refresh_hz))
            .replace("{1}", String(monitor.max_refresh_hz))}
        </p>
      )}
    </section>
  );
}

