/**
 * Settings → Game settings: the player's own setup for each game — graphics
 * and performance (presets, resolution up to 5K, FPS up to unlimited),
 * mouse, keybinds with combinations, audio, gameplay — plus a converter that
 * carries a hip-fire sensitivity to every other game at the same cm/360
 * (docs/game-settings.md).
 *
 * Which settings a game has comes from the backend catalog
 * (`dodaios/games/catalog.json` plus `dodaios/games/performance.py`), so
 * adding a game never touches this view. Each game wears its own hue
 * (`lib/gameVisuals`), passed down as CSS variables.
 */
import { useCallback, useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Check,
  Copy,
  Crosshair,
  FileCog,
  Gamepad2,
  Keyboard,
  Loader2,
  MonitorCog,
  Repeat,
  Search,
  SlidersHorizontal,
  Trash2,
  Volume2,
  type LucideIcon,
} from "lucide-react";
import { GameSettingRow } from "@/components/games/GameControls";
import { KeybindPanel } from "@/components/games/KeybindPanel";
import { PerformancePanel } from "@/components/games/PerformancePanel";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  useGameDetail,
  useGamesIndex,
  useResetGameProfile,
  useSaveDefaultDpi,
  useSaveGameProfile,
} from "@/hooks/useGames";
import { useT } from "@/i18n";
import { robustCopy } from "@/lib/clipboard";
import {
  cmPer360,
  convertSensitivity,
  type GameDefinition,
  type GamePreset,
  type GameProfile,
  type GameSettingValue,
  type ProfilePatch,
} from "@/lib/gamesApi";
import { gameAccent, gameMonogram } from "@/lib/gameVisuals";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";

type TabId = "performance" | "mouse" | "keybinds" | "audio" | "gameplay" | "converter";
const TABS: readonly { id: TabId; icon: LucideIcon }[] = [
  { id: "performance", icon: MonitorCog },
  { id: "mouse", icon: Crosshair },
  { id: "keybinds", icon: Keyboard },
  { id: "audio", icon: Volume2 },
  { id: "gameplay", icon: SlidersHorizontal },
  { id: "converter", icon: Repeat },
];
const LAST_GAME_KEY = "dodaios.games.last";

function readLastGame(): string | null {
  try {
    return window.localStorage.getItem(LAST_GAME_KEY);
  } catch {
    return null;
  }
}

function writeLastGame(id: string) {
  try {
    window.localStorage.setItem(LAST_GAME_KEY, id);
  } catch {
    // Remembering the last game is a convenience only.
  }
}

function formatNumber(value: number, digits = 2): string {
  return value.toLocaleString(undefined, { maximumFractionDigits: digits });
}

/** The CSS variables that colour one game's page. */
function accentVars(id: string): CSSProperties {
  return {
    "--game-accent": gameAccent(id),
    "--game-accent-soft": gameAccent(id, 0.12),
    "--game-accent-glow": gameAccent(id, 0.35),
  } as CSSProperties;
}

function Monogram({ id, name, size = "sm" }: { id: string; name: string; size?: "sm" | "lg" }) {
  return (
    <span
      aria-hidden
      style={{
        background: `linear-gradient(135deg, ${gameAccent(id, 0.95)}, ${gameAccent(id, 0.45)})`,
        boxShadow: `0 0 ${size === "lg" ? 28 : 12}px ${gameAccent(id, 0.35)}`,
      }}
      className={cn(
        "flex shrink-0 items-center justify-center rounded-lg font-mono font-bold text-black/85",
        size === "lg" ? "h-16 w-16 text-xl" : "h-9 w-9 text-xs",
      )}
    >
      {gameMonogram(name)}
    </span>
  );
}

export function GamesView() {
  const t = useT();
  const pushToast = useEventStore((s) => s.pushToast);
  const index = useGamesIndex();
  const saveDpi = useSaveDefaultDpi();
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(() => readLastGame());
  const [tab, setTab] = useState<TabId>("performance");

  const games = index.data?.games ?? [];
  useEffect(() => {
    if (games.length === 0) return;
    if (!selected || !games.some((game) => game.id === selected)) setSelected(games[0].id);
  }, [games, selected]);

  const needle = query.trim().toLowerCase();
  const visible = games.filter(
    (game) =>
      needle === "" ||
      game.name.toLowerCase().includes(needle) ||
      game.publisher.toLowerCase().includes(needle),
  );

  const choose = (id: string) => {
    setSelected(id);
    writeLastGame(id);
  };

  return (
    <div
      data-testid="games-view"
      className="flex h-full flex-col overflow-y-auto bg-background px-4 pb-10 scrollbar-jarvis sm:px-8"
    >
      <div className="w-full max-w-[1500px]">
        <PageHeader
          icon={<Gamepad2 />}
          title={t("games.title")}
          description={t("games.subtitle")}
          actions={
            index.data && (
              <DpiField
                label={t("games.default_dpi")}
                value={index.data.dpi}
                onCommit={(dpi) =>
                  dpi !== null &&
                  saveDpi.mutate(dpi, {
                    onError: (error) =>
                      pushToast("error", t("games.save_error").replace("{0}", (error as Error).message)),
                  })
                }
              />
            )
          }
        />

        {index.isError && (
          <p role="alert" className="text-sm text-destructive">
            {t("games.load_error").replace("{0}", (index.error as Error).message)}
          </p>
        )}
        {index.isLoading && <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-hidden />}

        {index.data && (
          <div className="flex flex-col gap-6 lg:flex-row">
            <aside className="lg:w-60 lg:shrink-0">
              <div className="relative mb-3">
                <Search
                  className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
                  aria-hidden
                />
                <Input
                  value={query}
                  onChange={(event) => setQuery(event.currentTarget.value)}
                  placeholder={t("games.search")}
                  aria-label={t("games.search")}
                  className="h-8 pl-8"
                />
              </div>
              <ul
                className="flex gap-1.5 overflow-x-auto pb-1 lg:flex-col lg:overflow-visible lg:pb-0"
                data-testid="games-list"
              >
                {visible.map((game) => {
                  const active = game.id === selected;
                  return (
                    <li key={game.id} className="shrink-0">
                      <button
                        type="button"
                        data-testid={`games-pick-${game.id}`}
                        aria-current={active ? "true" : undefined}
                        onClick={() => choose(game.id)}
                        style={active ? accentVars(game.id) : undefined}
                        className={cn(
                          "flex w-full items-center gap-3 rounded-lg border px-2.5 py-2 text-left transition-all",
                          active
                            ? "border-[var(--game-accent)] bg-[var(--game-accent-soft)]"
                            : "border-transparent text-foreground hover:bg-secondary/60",
                        )}
                      >
                        <Monogram id={game.id} name={game.name} />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-medium text-foreground-strong">
                            {game.name}
                          </span>
                          <span className="block truncate text-[11px] text-muted-foreground">
                            {game.publisher}
                          </span>
                        </span>
                        {game.has_profile && (
                          <span
                            className="h-1.5 w-1.5 shrink-0 rounded-full bg-accent"
                            title={t("games.saved_badge")}
                            aria-label={t("games.saved_badge")}
                          />
                        )}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </aside>

            <section className="min-w-0 flex-1">
              {selected && (
                <GamePanel
                  key={selected}
                  gameId={selected}
                  defaultDpi={index.data.dpi}
                  presets={index.data.presets ?? []}
                  tab={tab}
                  onTab={setTab}
                />
              )}
            </section>
          </div>
        )}
      </div>
    </div>
  );
}

function DpiField({
  label,
  value,
  placeholder,
  allowEmpty = false,
  onCommit,
}: {
  label: string;
  value: number | null;
  placeholder?: string;
  /** A blank field means "follow the default"; otherwise blank just reverts. */
  allowEmpty?: boolean;
  onCommit: (dpi: number | null) => void;
}) {
  const [draft, setDraft] = useState(value === null ? "" : String(value));
  useEffect(() => setDraft(value === null ? "" : String(value)), [value]);
  const commit = () => {
    const trimmed = draft.trim();
    if (trimmed === "") {
      if (!allowEmpty) setDraft(value === null ? "" : String(value));
      else if (value !== null) onCommit(null);
      return;
    }
    const next = Math.round(Number(trimmed));
    if (!Number.isFinite(next) || next < 50 || next > 64000) {
      setDraft(value === null ? "" : String(value));
      return;
    }
    if (next !== value) onCommit(next);
  };
  return (
    <label className="flex items-center gap-2.5 rounded-lg border border-border bg-card px-3 py-1.5">
      <span className="text-sm font-medium text-foreground">{label}</span>
      <Input
        inputMode="numeric"
        value={draft}
        placeholder={placeholder}
        onChange={(event) => setDraft(event.currentTarget.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") (event.currentTarget as HTMLInputElement).blur();
        }}
        className="h-7 w-20 font-mono tabular-nums"
      />
    </label>
  );
}

function HeroStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">{label}</p>
      <p className="truncate font-mono text-lg font-semibold tabular-nums text-foreground-strong">{value}</p>
    </div>
  );
}

function GamePanel({
  gameId,
  defaultDpi,
  presets,
  tab,
  onTab,
}: {
  gameId: string;
  defaultDpi: number;
  presets: GamePreset[];
  tab: TabId;
  onTab: (tab: TabId) => void;
}) {
  const t = useT();
  const pushToast = useEventStore((s) => s.pushToast);
  const detail = useGameDetail(gameId);
  const save = useSaveGameProfile();
  const reset = useResetGameProfile();
  const [confirmReset, setConfirmReset] = useState(false);

  const patch = useCallback(
    (change: ProfilePatch) =>
      save.mutate(
        { gameId, patch: change },
        {
          onError: (error) =>
            pushToast("error", t("games.save_error").replace("{0}", (error as Error).message)),
        },
      ),
    [gameId, save, pushToast, t],
  );

  if (detail.isLoading || !detail.data) {
    return detail.isError ? (
      <p role="alert" className="text-sm text-destructive">
        {t("games.load_error").replace("{0}", (detail.error as Error).message)}
      </p>
    ) : (
      <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-hidden />
    );
  }

  const { game, profile: raw } = detail.data;
  const profile: GameProfile = {
    ...raw,
    alt_keybinds: raw.alt_keybinds ?? {},
    bind_modes: raw.bind_modes ?? {},
    custom_binds: raw.custom_binds ?? [],
  };
  const dpi = profile.dpi ?? defaultDpi;
  const hasProfile = profile.updated_at !== null;
  const allSettings = game.sections.flatMap((s) => s.settings);
  const effective = (key: string) =>
    profile.values[key] ?? allSettings.find((s) => s.key === key)?.default ?? null;
  const sensRaw = game.sens_key ? effective(game.sens_key) : null;
  const sens = typeof sensRaw === "number" ? sensRaw : null;
  const cm = game.yaw && sens ? cmPer360(game.yaw, sens, dpi) : null;
  const res = String(effective("perf_resolution") ?? "—").replace("x", " × ");
  const fps = String(effective("perf_fps_cap") ?? "—");

  const copySummary = async () => {
    const ok = await robustCopy(profileSummary(game, profile, dpi));
    pushToast(ok ? "success" : "error", ok ? t("games.copied") : t("games.copy_failed"));
  };

  const sectionRows = (id: string) => {
    const settings = game.sections.find((s) => s.id === id)?.settings ?? [];
    if (settings.length === 0) {
      return <p className="py-6 text-sm text-muted-foreground">{t("games.section_empty")}</p>;
    }
    return settings.map((setting) => (
      <GameSettingRow
        key={setting.key}
        setting={setting}
        value={profile.values[setting.key]}
        onChange={(value) => patch({ values: { [setting.key]: value } })}
      />
    ));
  };

  return (
    <div data-testid={`game-panel-${game.id}`} style={accentVars(game.id)}>
      <header
        className="relative overflow-hidden rounded-2xl border border-border px-5 py-5 sm:px-6"
        style={{
          background: `radial-gradient(120% 140% at 0% 0%, ${gameAccent(game.id, 0.28)}, transparent 55%), radial-gradient(80% 120% at 100% 100%, ${gameAccent(game.id, 0.12)}, transparent 60%), hsl(var(--card))`,
        }}
      >
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 opacity-[0.07] [background-image:linear-gradient(hsl(var(--foreground))_1px,transparent_1px),linear-gradient(90deg,hsl(var(--foreground))_1px,transparent_1px)] [background-size:28px_28px]"
        />
        <div className="relative flex flex-wrap items-start justify-between gap-4">
          <div className="flex min-w-0 items-center gap-4">
            <Monogram id={game.id} name={game.name} size="lg" />
            <div className="min-w-0">
              <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-[var(--game-accent)]">
                {game.publisher}
              </p>
              <h2 className="truncate text-2xl font-bold tracking-tight text-foreground-strong sm:text-3xl">
                {game.name}
              </h2>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button type="button" variant="outline" size="sm" onClick={() => void copySummary()}>
              <Copy aria-hidden />
              {t("games.copy")}
            </Button>
            <Button
              type="button"
              variant={confirmReset ? "destructive" : "outline"}
              size="sm"
              disabled={!hasProfile || reset.isPending}
              onBlur={() => setConfirmReset(false)}
              onClick={() => {
                if (!confirmReset) return setConfirmReset(true);
                setConfirmReset(false);
                reset.mutate(game.id, {
                  onSuccess: () => pushToast("success", t("games.reset_done").replace("{0}", game.name)),
                  onError: (error) =>
                    pushToast("error", t("games.save_error").replace("{0}", (error as Error).message)),
                });
              }}
            >
              <Trash2 aria-hidden />
              {confirmReset ? t("games.reset_confirm") : t("games.reset_profile")}
            </Button>
          </div>
        </div>
        <div className="relative mt-5 grid grid-cols-2 gap-4 sm:grid-cols-4" data-testid="games-hero-stats">
          <HeroStat label={t("games.perf.resolution")} value={res} />
          <HeroStat
            label={t("games.perf.fps_limit")}
            value={fps === "Unlimited" ? t("games.perf.unlimited") : fps}
          />
          <HeroStat label={t("games.cm360")} value={cm ? `${formatNumber(cm, 1)} cm` : "—"} />
          <HeroStat label={t("games.edpi")} value={sens ? formatNumber(sens * dpi, 0) : "—"} />
        </div>
      </header>

      <nav
        className="sticky top-0 z-10 -mx-1 mt-4 flex gap-1 overflow-x-auto rounded-xl border border-border bg-background/85 p-1 backdrop-blur"
        aria-label={game.name}
      >
        {TABS.map(({ id, icon: Icon }) => {
          const active = tab === id;
          return (
            <button
              key={id}
              type="button"
              aria-current={active ? "page" : undefined}
              onClick={() => onTab(id)}
              className={cn(
                "flex shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-all",
                active
                  ? "bg-[var(--game-accent-soft)] text-foreground-strong shadow-[inset_0_-2px_0_var(--game-accent)]"
                  : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
              )}
            >
              <Icon className={cn("h-4 w-4", active && "text-[var(--game-accent)]")} aria-hidden />
              {t(`games.tabs.${id}`)}
              {id === "keybinds" && (
                <span className="font-mono text-[11px] text-muted-foreground">{game.keybinds.length}</span>
              )}
            </button>
          );
        })}
      </nav>

      <div className="mt-4">
        {tab === "performance" && (
          <PerformancePanel game={game} profile={profile} presets={presets} onPatch={patch} />
        )}
        {tab === "mouse" && (
          <Panel>
            <MouseSummary game={game} profile={profile} defaultDpi={defaultDpi} onPatch={patch} />
            {sectionRows("mouse")}
          </Panel>
        )}
        {tab === "keybinds" && <KeybindPanel game={game} profile={profile} onPatch={patch} />}
        {tab === "audio" && <Panel>{sectionRows("audio")}</Panel>}
        {tab === "gameplay" && <Panel>{sectionRows("gameplay")}</Panel>}
        {tab === "converter" && (
          <Panel>
            <Converter game={game} profile={profile} dpi={dpi} />
          </Panel>
        )}
      </div>

      <div className="mt-6 grid gap-4 md:grid-cols-2">
        <NotesField value={profile.notes} onCommit={(notes) => patch({ notes })} />
        <div className="rounded-xl border border-border bg-card/80 p-4">
          <div className="flex items-center gap-2 text-sm font-medium text-foreground">
            <FileCog className="h-4 w-4 text-[var(--game-accent)]" aria-hidden />
            {t("games.config_file")}
          </div>
          <p className="mt-2 break-words font-mono text-xs text-muted-foreground">{game.config_file}</p>
        </div>
      </div>
    </div>
  );
}

function Panel({ children }: { children: ReactNode }) {
  return (
    <div className="relative overflow-hidden rounded-xl border border-border bg-card/80 px-5 before:absolute before:inset-y-0 before:left-0 before:w-[3px] before:bg-[var(--game-accent)]">
      {children}
    </div>
  );
}

function MouseSummary({
  game,
  profile,
  defaultDpi,
  onPatch,
}: {
  game: GameDefinition;
  profile: GameProfile;
  defaultDpi: number;
  onPatch: (patch: ProfilePatch) => void;
}) {
  const t = useT();
  const dpi = profile.dpi ?? defaultDpi;
  const sensSetting = game.sens_key
    ? game.sections.flatMap((s) => s.settings).find((s) => s.key === game.sens_key)
    : undefined;
  const raw = game.sens_key ? (profile.values[game.sens_key] ?? sensSetting?.default) : undefined;
  const sens = typeof raw === "number" ? raw : null;
  const cm = game.yaw && sens ? cmPer360(game.yaw, sens, dpi) : null;

  return (
    <div className="grid gap-3 border-b border-border/60 py-4 sm:grid-cols-3" data-testid="games-mouse-summary">
      <div>
        <p className="text-xs text-muted-foreground">{t("games.game_dpi")}</p>
        <div className="mt-1">
          <DpiField
            label="DPI"
            value={profile.dpi}
            placeholder={String(defaultDpi)}
            allowEmpty
            onCommit={(next) => onPatch(next === null ? { reset_dpi: true } : { dpi: next })}
          />
        </div>
        {profile.dpi === null && (
          <p className="mt-1 text-xs text-muted-foreground">
            {t("games.follow_default").replace("{0}", String(defaultDpi))}
          </p>
        )}
      </div>
      <Stat label={t("games.cm360")} value={cm ? `${formatNumber(cm, 1)} cm` : "—"} hint={t("games.cm360_hint")} />
      <Stat
        label={t("games.edpi")}
        value={sens ? formatNumber(sens * dpi, 0) : "—"}
        hint={game.yaw ? undefined : t("games.not_convertible")}
      />
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 font-mono text-xl tabular-nums text-foreground-strong">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

function Converter({ game, profile, dpi }: { game: GameDefinition; profile: GameProfile; dpi: number }) {
  const t = useT();
  const pushToast = useEventStore((s) => s.pushToast);
  const save = useSaveGameProfile();
  const sensKey = game.sens_key;
  const saved = sensKey ? profile.values[sensKey] : undefined;
  const [sensDraft, setSensDraft] = useState(typeof saved === "number" ? String(saved) : "");
  const [toDpiDraft, setToDpiDraft] = useState("");
  const [applied, setApplied] = useState<string | null>(null);
  const sens = Number(sensDraft.replace(",", "."));
  const toDpi = Number(toDpiDraft);
  const validSens = Number.isFinite(sens) && sens > 0;
  const validToDpi = toDpiDraft.trim() === "" || (Number.isFinite(toDpi) && toDpi >= 50 && toDpi <= 64000);

  const result = useQuery({
    queryKey: ["games", "convert", game.id, sens, dpi, toDpiDraft],
    queryFn: () =>
      convertSensitivity({
        game_id: game.id,
        sens,
        dpi,
        to_dpi: toDpiDraft.trim() === "" ? undefined : Math.round(toDpi),
      }),
    enabled: Boolean(game.yaw && sensKey && validSens && validToDpi),
    staleTime: Infinity,
  });

  if (!game.yaw || !sensKey) {
    return (
      <p className="py-6 text-sm text-muted-foreground" data-testid="games-converter-unavailable">
        {t("games.converter_unavailable").replace("{0}", game.name)}
      </p>
    );
  }

  const apply = (targetId: string, targetName: string, targetKey: string, value: number) => {
    const rounded = Math.round(value * 1000) / 1000;
    save.mutate(
      { gameId: targetId, patch: { values: { [targetKey]: rounded } } },
      {
        onSuccess: () => {
          setApplied(targetId);
          pushToast("success", t("games.converter_applied").replace("{0}", String(rounded)).replace("{1}", targetName));
        },
        onError: (error) =>
          pushToast("error", t("games.save_error").replace("{0}", (error as Error).message)),
      },
    );
  };

  return (
    <div className="py-4" data-testid="games-converter">
      <p className="text-xs text-muted-foreground">{t("games.converter_hint")}</p>
      <div className="mt-3 flex flex-wrap items-end gap-4">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">
            {t("games.converter_from").replace("{0}", game.name)}
          </span>
          <Input
            inputMode="decimal"
            value={sensDraft}
            onChange={(event) => setSensDraft(event.currentTarget.value)}
            className="h-8 w-32 font-mono tabular-nums"
            data-testid="games-converter-sens"
          />
        </label>
        <div className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">DPI</span>
          <span className="flex h-8 items-center font-mono text-sm tabular-nums">{dpi}</span>
        </div>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">{t("games.converter_target_dpi")}</span>
          <Input
            inputMode="numeric"
            value={toDpiDraft}
            placeholder={String(dpi)}
            onChange={(event) => setToDpiDraft(event.currentTarget.value)}
            className="h-8 w-28 font-mono tabular-nums"
          />
        </label>
        {result.data && (
          <div className="ml-auto text-right">
            <p className="text-xs text-muted-foreground">{t("games.cm360")}</p>
            <p className="font-mono text-2xl font-semibold tabular-nums text-[var(--game-accent)]" data-testid="games-converter-cm">
              {formatNumber(result.data.cm_per_360, 1)} cm
            </p>
          </div>
        )}
      </div>

      {result.isError && (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {(result.error as Error).message}
        </p>
      )}

      {result.data && (
        <table className="mt-4 w-full text-sm" data-testid="games-converter-results">
          <thead>
            <tr className="text-left font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
              <th className="py-2 font-normal">{t("games.converter_game")}</th>
              <th className="py-2 text-right font-normal">{t("games.converter_sens")}</th>
              <th className="hidden py-2 text-right font-normal sm:table-cell">{t("games.edpi")}</th>
              <th className="py-2" />
            </tr>
          </thead>
          <tbody>
            {result.data.results.map((row) => (
              <tr key={row.id} className="border-t border-border/60">
                <td className="py-2">
                  <span className="flex items-center gap-2.5 text-foreground">
                    <Monogram id={row.id} name={row.name} />
                    {row.name}
                  </span>
                </td>
                <td className="py-2 text-right font-mono tabular-nums text-foreground-strong">
                  {formatNumber(row.sens, 3)}
                </td>
                <td className="hidden py-2 text-right font-mono tabular-nums text-muted-foreground sm:table-cell">
                  {formatNumber(row.edpi, 0)}
                </td>
                <td className="py-2 pl-3 text-right">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="text-xs"
                    disabled={save.isPending}
                    onClick={() => apply(row.id, row.name, row.sens_key, row.sens)}
                  >
                    {applied === row.id && <Check aria-hidden />}
                    {t("games.converter_apply")}
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function NotesField({ value, onCommit }: { value: string; onCommit: (notes: string) => void }) {
  const t = useT();
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  return (
    <label className="flex flex-col gap-2 rounded-xl border border-border bg-card/80 p-4">
      <span className="text-sm font-medium text-foreground">{t("games.notes")}</span>
      <Textarea
        value={draft}
        maxLength={4000}
        placeholder={t("games.notes_placeholder")}
        onChange={(event) => setDraft(event.currentTarget.value)}
        onBlur={() => draft !== value && onCommit(draft)}
        className="min-h-[5rem] text-sm"
      />
    </label>
  );
}

function valueText(value: GameSettingValue): string {
  return typeof value === "boolean" ? (value ? "On" : "Off") : String(value);
}

/** Plain-text summary of a profile, for pasting into chat or a note. */
export function profileSummary(game: GameDefinition, profile: GameProfile, dpi: number): string {
  const lines = [`${game.name} — DPI ${dpi}`];
  for (const section of game.sections) {
    const set = section.settings.filter((s) => profile.values[s.key] !== undefined);
    if (set.length === 0) continue;
    lines.push("", `[${section.id}]`);
    for (const s of set) lines.push(`${s.label}: ${valueText(profile.values[s.key])}`);
  }
  const binds = game.keybinds.filter(
    (b) => b.id in profile.keybinds || b.id in (profile.alt_keybinds ?? {}),
  );
  if (binds.length > 0) {
    lines.push("", "[keybinds]");
    for (const b of binds) {
      const primary = profile.keybinds[b.id] ?? b.default;
      const alt = profile.alt_keybinds?.[b.id];
      const mode = profile.bind_modes?.[b.id];
      lines.push(`${b.action}: ${primary || "—"}${alt ? ` / ${alt}` : ""}${mode ? ` (${mode})` : ""}`);
    }
  }
  const custom = (profile.custom_binds ?? []).filter((c) => c.action || c.key);
  if (custom.length > 0) {
    lines.push("", "[custom]");
    for (const c of custom) lines.push(`${c.action || "—"}: ${c.key || "—"}${c.alt ? ` / ${c.alt}` : ""}`);
  }
  if (profile.notes.trim()) lines.push("", profile.notes.trim());
  return lines.join("\n");
}
