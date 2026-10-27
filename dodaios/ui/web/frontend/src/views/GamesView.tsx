/**
 * Settings → Game settings: the player's own settings for each game —
 * sensitivity, keybinds, audio, video, gameplay — in one place, plus a
 * converter that carries a hip-fire sensitivity from one game to the others
 * at the same cm/360 (docs/game-settings.md).
 *
 * Which settings a game has comes from the backend catalog
 * (`dodaios/games/catalog.json`), so adding a game never touches this view.
 */
import { useCallback, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, Copy, FileCog, Gamepad2, Loader2, Search, Trash2 } from "lucide-react";
import { GameSettingRow, KeyCaptureButton } from "@/components/games/GameControls";
import { PageHeader } from "@/components/layout/PageHeader";
import { TabBar } from "@/components/layout/SectionTabBar";
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
import { keyConflicts } from "@/lib/gameKeys";
import {
  cmPer360,
  convertSensitivity,
  type GameDefinition,
  type GameProfile,
  type GameSettingValue,
  type ProfilePatch,
} from "@/lib/gamesApi";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";

type TabId = "mouse" | "keybinds" | "audio" | "video" | "gameplay" | "converter";
const TABS: readonly TabId[] = ["mouse", "keybinds", "audio", "video", "gameplay", "converter"];
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

export function GamesView() {
  const t = useT();
  const pushToast = useEventStore((s) => s.pushToast);
  const index = useGamesIndex();
  const saveDpi = useSaveDefaultDpi();
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(() => readLastGame());
  const [tab, setTab] = useState<TabId>("mouse");

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
      <div className="w-full max-w-[1400px]">
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
            <aside className="lg:w-64 lg:shrink-0">
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
              <ul className="flex gap-1 overflow-x-auto pb-1 lg:flex-col lg:overflow-visible lg:pb-0" data-testid="games-list">
                {visible.map((game) => (
                  <li key={game.id} className="shrink-0">
                    <button
                      type="button"
                      data-testid={`games-pick-${game.id}`}
                      aria-current={game.id === selected ? "true" : undefined}
                      onClick={() => choose(game.id)}
                      className={cn(
                        "flex w-full items-center gap-2 rounded-md px-3 py-2 text-left transition-colors",
                        game.id === selected
                          ? "bg-secondary text-foreground-strong"
                          : "text-foreground hover:bg-secondary/60",
                      )}
                    >
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium">{game.name}</span>
                        <span className="block truncate text-xs text-muted-foreground">{game.publisher}</span>
                      </span>
                      {game.has_profile && (
                        <span
                          className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary"
                          title={t("games.saved_badge")}
                          aria-label={t("games.saved_badge")}
                        />
                      )}
                    </button>
                  </li>
                ))}
              </ul>
            </aside>

            <section className="min-w-0 flex-1">
              {selected && (
                <GamePanel
                  key={selected}
                  gameId={selected}
                  defaultDpi={index.data.dpi}
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

function GamePanel({
  gameId,
  defaultDpi,
  tab,
  onTab,
}: {
  gameId: string;
  defaultDpi: number;
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

  const { game, profile } = detail.data;
  const dpi = profile.dpi ?? defaultDpi;
  const section = game.sections.find((s) => s.id === tab);
  const hasProfile = profile.updated_at !== null;

  const copySummary = async () => {
    const ok = await robustCopy(profileSummary(game, profile, dpi));
    pushToast(ok ? "success" : "error", ok ? t("games.copied") : t("games.copy_failed"));
  };

  return (
    <div data-testid={`game-panel-${game.id}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-foreground-strong">{game.name}</h2>
          <p className="text-xs text-muted-foreground">{game.publisher}</p>
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

      <TabBar
        className="mt-4"
        tabs={TABS.map((id) => ({
          id,
          label: t(`games.tabs.${id}`),
          count: id === "keybinds" ? game.keybinds.length : undefined,
        }))}
        active={tab}
        onChange={(id) => onTab(id as TabId)}
      />

      <div className="mt-4 rounded-lg border border-border bg-card px-4">
        {tab === "mouse" && (
          <MouseSummary game={game} profile={profile} defaultDpi={defaultDpi} onPatch={patch} />
        )}
        {section &&
          (section.settings.length === 0 ? (
            <p className="py-6 text-sm text-muted-foreground">{t("games.section_empty")}</p>
          ) : (
            section.settings.map((setting) => (
              <GameSettingRow
                key={setting.key}
                setting={setting}
                value={profile.values[setting.key]}
                onChange={(value) => patch({ values: { [setting.key]: value } })}
              />
            ))
          ))}
        {tab === "keybinds" && <KeybindList game={game} profile={profile} onPatch={patch} />}
        {tab === "converter" && <Converter game={game} profile={profile} dpi={dpi} />}
      </div>

      <div className="mt-6 grid gap-4 md:grid-cols-2">
        <NotesField value={profile.notes} onCommit={(notes) => patch({ notes })} />
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="flex items-center gap-2 text-sm font-medium text-foreground">
            <FileCog className="h-4 w-4 text-muted-foreground" aria-hidden />
            {t("games.config_file")}
          </div>
          <p className="mt-2 break-words font-mono text-xs text-muted-foreground">{game.config_file}</p>
        </div>
      </div>
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

function KeybindList({
  game,
  profile,
  onPatch,
}: {
  game: GameDefinition;
  profile: GameProfile;
  onPatch: (patch: ProfilePatch) => void;
}) {
  const t = useT();
  const rows = game.keybinds.map((bind) => ({
    ...bind,
    key: profile.keybinds[bind.id] ?? bind.default,
    saved: bind.id in profile.keybinds,
  }));
  const conflicts = keyConflicts(rows);

  return (
    <div data-testid="games-keybinds">
      <p className="border-b border-border/60 py-3 text-xs text-muted-foreground">{t("games.keybind_hint")}</p>
      {rows.map((row) => {
        const clash = conflicts.get(row.id);
        return (
          <div
            key={row.id}
            data-testid={`game-keybind-${row.id}`}
            className="flex flex-wrap items-center gap-3 border-b border-border/60 py-2 last:border-b-0"
          >
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="text-sm text-foreground">{row.action}</span>
                {row.saved && <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-primary" />}
              </div>
              {clash && (
                <p className="text-xs text-amber-500">
                  {t("games.keybind_conflict").replace("{0}", clash.join(", "))}
                </p>
              )}
              {!clash && row.note && <p className="text-xs text-muted-foreground">{row.note}</p>}
            </div>
            <KeyCaptureButton
              value={row.key}
              label={row.action}
              onCapture={(key) => onPatch({ keybinds: { [row.id]: key } })}
            />
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="text-xs"
              onClick={() => onPatch({ keybinds: { [row.id]: "" } })}
              disabled={row.key === ""}
            >
              {t("games.keybind_clear")}
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className={cn("text-xs", !row.saved && "invisible")}
              onClick={() => onPatch({ keybinds: { [row.id]: null } })}
              title={row.default ? t("games.default_value").replace("{0}", row.default) : undefined}
            >
              {t("games.keybind_reset")}
            </Button>
          </div>
        );
      })}
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
            <p className="font-mono text-xl tabular-nums text-foreground-strong" data-testid="games-converter-cm">
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
            <tr className="text-left text-xs text-muted-foreground">
              <th className="py-2 font-normal">{t("games.converter_game")}</th>
              <th className="py-2 text-right font-normal">{t("games.converter_sens")}</th>
              <th className="hidden py-2 text-right font-normal sm:table-cell">{t("games.edpi")}</th>
              <th className="py-2" />
            </tr>
          </thead>
          <tbody>
            {result.data.results.map((row) => (
              <tr key={row.id} className="border-t border-border/60">
                <td className="py-2 text-foreground">{row.name}</td>
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
    <label className="flex flex-col gap-2 rounded-lg border border-border bg-card p-4">
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

/** Plain-text summary of a profile, for pasting into chat or a note. */
export function profileSummary(game: GameDefinition, profile: GameProfile, dpi: number): string {
  const lines = [`${game.name} — DPI ${dpi}`];
  for (const section of game.sections) {
    const set = section.settings.filter((s) => profile.values[s.key] !== undefined);
    if (set.length === 0) continue;
    lines.push("", `[${section.id}]`);
    for (const s of set) {
      const value: GameSettingValue = profile.values[s.key];
      lines.push(`${s.label}: ${typeof value === "boolean" ? (value ? "On" : "Off") : value}`);
    }
  }
  const binds = game.keybinds.filter((b) => b.id in profile.keybinds);
  if (binds.length > 0) {
    lines.push("", "[keybinds]");
    for (const b of binds) lines.push(`${b.action}: ${profile.keybinds[b.id] || "—"}`);
  }
  if (profile.notes.trim()) lines.push("", profile.notes.trim());
  return lines.join("\n");
}
