/**
 * Keybinds for one game: a keyboard and a mouse that light up where an
 * action is bound (amber where two actions collide), then every action with
 * a primary and a secondary bind — single keys or combinations like
 * "Shift + Mouse 4" — hold or toggle for actions where games offer both, and
 * the player's own extra actions.
 */
import { useState } from "react";
import { Keyboard, Mouse, Plus, Search, Trash2, X } from "lucide-react";
import { KeyCaptureButton, Segmented } from "@/components/games/GameControls";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useT } from "@/i18n";
import { bindUsesKey, keyConflicts } from "@/lib/gameKeys";
import type { BindMode, CustomBind, GameDefinition, GameProfile, ProfilePatch } from "@/lib/gamesApi";
import { cn } from "@/lib/utils";

/** [key name, width in key units, short label]. */
type KeyCap = [string, number, string?];

const KEYBOARD: KeyCap[][] = [
  [["Escape", 1, "Esc"], ["F1", 1], ["F2", 1], ["F3", 1], ["F4", 1], ["F5", 1], ["F6", 1], ["F7", 1], ["F8", 1], ["F9", 1], ["F10", 1], ["F11", 1], ["F12", 1]],
  [["`", 1], ["1", 1], ["2", 1], ["3", 1], ["4", 1], ["5", 1], ["6", 1], ["7", 1], ["8", 1], ["9", 1], ["0", 1], ["-", 1], ["=", 1], ["Backspace", 2, "Bksp"]],
  [["Tab", 1.5], ["Q", 1], ["W", 1], ["E", 1], ["R", 1], ["T", 1], ["Y", 1], ["U", 1], ["I", 1], ["O", 1], ["P", 1], ["[", 1], ["]", 1], ["\\", 1.5]],
  [["Caps Lock", 1.75, "Caps"], ["A", 1], ["S", 1], ["D", 1], ["F", 1], ["G", 1], ["H", 1], ["J", 1], ["K", 1], ["L", 1], [";", 1], ["'", 1], ["Enter", 2.25]],
  [["Left Shift", 2.25, "Shift"], ["Z", 1], ["X", 1], ["C", 1], ["V", 1], ["B", 1], ["N", 1], ["M", 1], [",", 1], [".", 1], ["/", 1], ["Right Shift", 2.75, "Shift"]],
  [["Left Ctrl", 1.5, "Ctrl"], ["Left Win", 1.25, "Win"], ["Left Alt", 1.25, "Alt"], ["Space", 6.5], ["Right Alt", 1.25, "Alt"], ["Right Ctrl", 1.5, "Ctrl"]],
];

const MOUSE_INPUTS = ["Left Mouse", "Right Mouse", "Middle Mouse", "Mouse 4", "Mouse 5", "Mouse Wheel Up", "Mouse Wheel Down"];

/** Actions games commonly let you hold or toggle. */
const MODE_ACTIONS = /sprint|crouch|aim|ads|walk|lean|prone|scope|zoom|slide|run|boost|crawl/i;

interface Bound {
  id: string;
  action: string;
  key: string;
}

function newId(): string {
  return `c${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}

export function KeybindPanel({
  game,
  profile,
  onPatch,
}: {
  game: GameDefinition;
  profile: GameProfile;
  onPatch: (patch: ProfilePatch) => void;
}) {
  const t = useT();
  const [filter, setFilter] = useState("");
  const [focusKey, setFocusKey] = useState<string | null>(null);
  const custom = profile.custom_binds ?? [];

  const rows = game.keybinds.map((bind) => ({
    ...bind,
    primary: profile.keybinds[bind.id] ?? bind.default,
    alt: profile.alt_keybinds?.[bind.id] ?? "",
    mode: profile.bind_modes?.[bind.id] ?? null,
    saved:
      bind.id in profile.keybinds ||
      bind.id in (profile.alt_keybinds ?? {}) ||
      bind.id in (profile.bind_modes ?? {}),
  }));

  // Every bind on one list, so a clash between a game action and the
  // player's own action is caught too.
  const bound: Bound[] = [
    ...rows.flatMap((r) => [
      { id: `${r.id}:p`, action: r.action, key: r.primary },
      { id: `${r.id}:a`, action: r.action, key: r.alt },
    ]),
    ...custom.flatMap((c) => [
      { id: `${c.id}:p`, action: c.action || t("games.keys.custom_unnamed"), key: c.key },
      { id: `${c.id}:a`, action: c.action || t("games.keys.custom_unnamed"), key: c.alt },
    ]),
  ];
  const conflicts = keyConflicts(bound);
  const actionsOn = (keyName: string) =>
    bound.filter((b) => b.key && bindUsesKey(b.key, keyName)).map((b) => b.action);
  const clashOn = (keyName: string) =>
    bound.some((b) => b.key && bindUsesKey(b.key, keyName) && conflicts.has(b.id));

  const needle = filter.trim().toLowerCase();
  const visible = rows.filter((r) => {
    if (focusKey && !bindUsesKey(r.primary, focusKey) && !bindUsesKey(r.alt, focusKey)) return false;
    return needle === "" || r.action.toLowerCase().includes(needle) || r.primary.toLowerCase().includes(needle);
  });

  const setCustom = (next: CustomBind[]) => onPatch({ custom_binds: next });
  const boundCount = bound.filter((b) => b.key).length;

  return (
    <div className="flex flex-col gap-5" data-testid="games-keybinds">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,5fr)_minmax(0,2fr)]">
        <section className="rounded-xl border border-border bg-card/80 p-4">
          <header className="mb-3 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Keyboard className="h-4 w-4 text-[var(--game-accent)]" aria-hidden />
              <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
                {t("games.keys.keyboard")}
              </p>
            </div>
            <p className="font-mono text-[11px] text-muted-foreground">
              {t("games.keys.bound_count").replace("{0}", String(boundCount))}
            </p>
          </header>
          <div className="overflow-x-auto pb-1">
            <div className="flex min-w-[640px] flex-col gap-1" data-testid="games-keyboard">
              {KEYBOARD.map((row, index) => (
                <div key={index} className={cn("flex gap-1", index === 0 && "mb-1.5")}>
                  {row.map(([name, width, short]) => {
                    const actions = actionsOn(name);
                    const clash = clashOn(name);
                    const focused = focusKey === name;
                    return (
                      <button
                        key={name}
                        type="button"
                        title={actions.length ? `${name}: ${actions.join(", ")}` : name}
                        data-testid={`games-key-${name}`}
                        data-bound={actions.length > 0}
                        onClick={() => setFocusKey(focused ? null : name)}
                        style={{ flex: `${width} 1 0` }}
                        className={cn(
                          "relative h-9 min-w-0 truncate rounded-md border px-1 font-mono text-[10px] transition-all",
                          clash
                            ? "border-warning bg-warning/20 text-foreground-strong"
                            : actions.length
                              ? "border-[var(--game-accent)] bg-[var(--game-accent-soft)] text-foreground-strong shadow-[0_0_10px_var(--game-accent-glow)]"
                              : "border-border bg-background/60 text-muted-foreground hover:border-border-strong",
                          focused && "ring-2 ring-[var(--game-accent)] ring-offset-1 ring-offset-background",
                        )}
                      >
                        {short ?? name}
                        {actions.length > 1 && (
                          <span className="absolute right-0.5 top-0 text-[8px] text-[var(--game-accent)]">
                            {actions.length}
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="rounded-xl border border-border bg-card/80 p-4" data-testid="games-mouse">
          <header className="mb-3 flex items-center gap-2">
            <Mouse className="h-4 w-4 text-[var(--game-accent)]" aria-hidden />
            <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
              {t("games.keys.mouse")}
            </p>
          </header>
          <ul className="flex flex-col gap-1">
            {MOUSE_INPUTS.map((name) => {
              const actions = actionsOn(name);
              const focused = focusKey === name;
              return (
                <li key={name}>
                  <button
                    type="button"
                    onClick={() => setFocusKey(focused ? null : name)}
                    className={cn(
                      "flex w-full items-center justify-between gap-3 rounded-md border px-2.5 py-1.5 text-left transition-colors",
                      clashOn(name)
                        ? "border-warning bg-warning/15"
                        : actions.length
                          ? "border-[var(--game-accent)]/50 bg-[var(--game-accent-soft)]"
                          : "border-transparent hover:bg-secondary/60",
                      focused && "ring-2 ring-[var(--game-accent)]",
                    )}
                  >
                    <span className="font-mono text-[11px] text-muted-foreground">{name}</span>
                    <span className="truncate text-xs text-foreground-strong">{actions.join(", ") || "—"}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      </div>

      <section className="rounded-xl border border-border bg-card/80 px-4 pb-2 pt-4">
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative min-w-[12rem] flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <Input
              value={filter}
              onChange={(event) => setFilter(event.currentTarget.value)}
              placeholder={t("games.keys.search")}
              aria-label={t("games.keys.search")}
              className="h-8 pl-8"
            />
          </div>
          {focusKey && (
            <Button type="button" variant="outline" size="sm" onClick={() => setFocusKey(null)}>
              <X aria-hidden />
              {t("games.keys.showing_key").replace("{0}", focusKey)}
            </Button>
          )}
        </div>
        <p className="mt-2 text-xs text-muted-foreground">{t("games.keybind_hint")}</p>

        <div className="mt-2 hidden grid-cols-[minmax(0,1fr)_auto_auto_7.5rem_4.5rem] gap-3 border-b border-border/60 pb-2 font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground md:grid">
          <span>{t("games.keys.action")}</span>
          <span className="w-[9rem]">{t("games.keys.primary")}</span>
          <span className="w-[9rem]">{t("games.keys.secondary")}</span>
          <span>{t("games.keys.mode")}</span>
          <span />
        </div>
        {visible.map((row) => {
          const clashP = row.primary ? conflicts.get(`${row.id}:p`) : undefined;
          const clashA = row.alt ? conflicts.get(`${row.id}:a`) : undefined;
          const clash = [...(clashP ?? []), ...(clashA ?? [])];
          return (
            <div
              key={row.id}
              data-testid={`game-keybind-${row.id}`}
              className="grid grid-cols-1 items-center gap-2 border-b border-border/50 py-2 last:border-b-0 md:grid-cols-[minmax(0,1fr)_auto_auto_7.5rem_4.5rem] md:gap-3"
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm text-foreground">{row.action}</span>
                  {row.saved && <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-accent" />}
                </div>
                {clash.length > 0 ? (
                  <p className="text-xs text-warning">
                    {t("games.keybind_conflict").replace("{0}", [...new Set(clash)].join(", "))}
                  </p>
                ) : (
                  row.note && <p className="text-xs text-muted-foreground">{row.note}</p>
                )}
              </div>
              <div className="flex items-center gap-1">
                <KeyCaptureButton
                  value={row.primary}
                  label={row.action}
                  onCapture={(key) => onPatch({ keybinds: { [row.id]: key } })}
                />
                {row.primary && (
                  <button
                    type="button"
                    aria-label={`${t("games.keybind_clear")}: ${row.action}`}
                    title={t("games.keybind_clear")}
                    onClick={() => onPatch({ keybinds: { [row.id]: "" } })}
                    className="rounded p-1 text-muted-foreground hover:bg-secondary hover:text-foreground"
                  >
                    <X className="h-3.5 w-3.5" aria-hidden />
                  </button>
                )}
              </div>
              <div className="flex items-center gap-1">
                <KeyCaptureButton
                  value={row.alt}
                  label={`${row.action} (${t("games.keys.secondary")})`}
                  onCapture={(key) => onPatch({ alt_keybinds: { [row.id]: key } })}
                />
                {row.alt && (
                  <button
                    type="button"
                    aria-label={`${t("games.keybind_clear")}: ${row.action}`}
                    onClick={() => onPatch({ alt_keybinds: { [row.id]: null } })}
                    className="rounded p-1 text-muted-foreground hover:bg-secondary hover:text-foreground"
                  >
                    <X className="h-3.5 w-3.5" aria-hidden />
                  </button>
                )}
              </div>
              <div>
                {MODE_ACTIONS.test(row.action) ? (
                  <Segmented
                    label={`${row.action}: ${t("games.keys.mode")}`}
                    value={row.mode ?? "hold"}
                    options={[
                      { value: "hold", label: t("games.keys.hold") },
                      { value: "toggle", label: t("games.keys.toggle") },
                    ]}
                    onChange={(mode) => onPatch({ bind_modes: { [row.id]: mode as BindMode } })}
                  />
                ) : (
                  <span className="text-xs text-muted-foreground/50">—</span>
                )}
              </div>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className={cn("text-xs", !row.saved && "invisible")}
                onClick={() =>
                  onPatch({
                    keybinds: { [row.id]: null },
                    alt_keybinds: { [row.id]: null },
                    bind_modes: { [row.id]: null },
                  })
                }
                title={row.default ? t("games.default_value").replace("{0}", row.default) : undefined}
              >
                {t("games.keybind_reset")}
              </Button>
            </div>
          );
        })}
        {visible.length === 0 && (
          <p className="py-6 text-center text-sm text-muted-foreground">{t("games.keys.nothing_found")}</p>
        )}
      </section>

      <section className="rounded-xl border border-border bg-card/80 px-4 pb-3 pt-4" data-testid="games-custom-binds">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
              {t("games.keys.custom_eyebrow")}
            </p>
            <h3 className="text-sm font-semibold text-foreground-strong">{t("games.keys.custom_title")}</h3>
            <p className="mt-0.5 text-xs text-muted-foreground">{t("games.keys.custom_hint")}</p>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            data-testid="games-add-custom"
            disabled={custom.length >= 60}
            onClick={() => setCustom([...custom, { id: newId(), action: "", key: "", alt: "" }])}
          >
            <Plus aria-hidden />
            {t("games.keys.custom_add")}
          </Button>
        </div>
        {custom.map((row, index) => (
          <CustomRow
            key={row.id}
            row={row}
            onChange={(next) => setCustom(custom.map((c, i) => (i === index ? next : c)))}
            onRemove={() => setCustom(custom.filter((_, i) => i !== index))}
          />
        ))}
      </section>
    </div>
  );
}

function CustomRow({
  row,
  onChange,
  onRemove,
}: {
  row: CustomBind;
  onChange: (row: CustomBind) => void;
  onRemove: () => void;
}) {
  const t = useT();
  const [name, setName] = useState(row.action);
  return (
    <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-border/50 pt-2">
      <Input
        value={name}
        maxLength={60}
        placeholder={t("games.keys.custom_name")}
        aria-label={t("games.keys.custom_name")}
        onChange={(event) => setName(event.currentTarget.value)}
        onBlur={() => name.trim() !== row.action && onChange({ ...row, action: name.trim() })}
        className="h-9 min-w-[10rem] flex-1"
      />
      <KeyCaptureButton
        value={row.key}
        label={name || t("games.keys.custom_unnamed")}
        onCapture={(key) => onChange({ ...row, key })}
      />
      <KeyCaptureButton
        value={row.alt}
        label={`${name || t("games.keys.custom_unnamed")} (${t("games.keys.secondary")})`}
        onCapture={(alt) => onChange({ ...row, alt })}
      />
      <button
        type="button"
        aria-label={`${t("games.keys.custom_remove")}: ${name}`}
        onClick={onRemove}
        className="rounded-md p-2 text-muted-foreground hover:bg-destructive/15 hover:text-destructive"
      >
        <Trash2 className="h-4 w-4" aria-hidden />
      </button>
    </div>
  );
}
