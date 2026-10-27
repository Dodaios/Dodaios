/**
 * The building blocks of Settings → Game settings: one row per setting
 * (segmented choice, filled slider, number, switch, text) and the keybind
 * capture button that records combinations ("Shift + Mouse 4").
 *
 * Rows keep a local draft while the user drags or types and hand the value
 * up only when it is settled (pointer up, blur, Enter), so a slider drag is
 * one save, not fifty.
 */
import { useEffect, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import { RotateCcw } from "lucide-react";
import { Input } from "@/components/ui/input";
import { BrandedSelect } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useT } from "@/i18n";
import {
  MODIFIER_CODES,
  comboName,
  comboParts,
  keyNameFromCode,
  mouseButtonName,
  wheelName,
  type HeldModifiers,
} from "@/lib/gameKeys";
import type { GameSetting, GameSettingValue } from "@/lib/gamesApi";
import { cn } from "@/lib/utils";

function formatDefault(setting: GameSetting, t: (key: string) => string): string | null {
  const value = setting.default;
  if (value === null || value === undefined || value === "") return null;
  if (typeof value === "boolean") return value ? t("games.on") : t("games.off");
  return String(value);
}

/** A choice short enough to show every option at once instead of a dropdown. */
export function fitsSegmented(options: readonly string[]): boolean {
  return options.length >= 2 && options.length <= 7 && options.join("").length <= 64;
}

export function Segmented({
  options,
  value,
  onChange,
  label,
  className,
}: {
  options: readonly { value: string; label: string }[];
  value: string | null;
  onChange: (value: string) => void;
  label: string;
  className?: string;
}) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={cn(
        "inline-flex max-w-full flex-wrap gap-0.5 rounded-lg border border-border bg-background/60 p-0.5",
        className,
      )}
    >
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(option.value)}
            className={cn(
              "rounded-md px-2.5 py-1 text-xs font-medium transition-all",
              // Inside a game's page the active segment wears the game's hue;
              // anywhere else it falls back to the app's signal colour.
              active
                ? "bg-[var(--game-accent,hsl(var(--accent)))] font-semibold text-black shadow-[0_0_12px_var(--game-accent-glow,hsl(var(--accent)/0.45))]"
                : "text-muted-foreground hover:bg-secondary hover:text-foreground",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

function SettingShell({
  setting,
  saved,
  onReset,
  children,
}: {
  setting: GameSetting;
  saved: boolean;
  onReset: () => void;
  children: ReactNode;
}) {
  const t = useT();
  const fallback = formatDefault(setting, t);
  return (
    <div
      data-testid={`game-setting-${setting.key}`}
      className="group flex flex-col gap-2 border-b border-border/50 py-3 last:border-b-0 md:flex-row md:items-center md:gap-6"
    >
      <div className="min-w-0 md:w-[38%]">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-foreground">{setting.label}</span>
          {saved && <span aria-hidden className="h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />}
        </div>
        {(setting.note || fallback) && (
          <p className="mt-0.5 text-xs text-muted-foreground">
            {fallback && t("games.default_value").replace("{0}", fallback)}
            {fallback && setting.note && " · "}
            {setting.note}
          </p>
        )}
      </div>
      <div className="flex min-w-0 flex-1 items-center gap-2">
        <div className="min-w-0 flex-1">{children}</div>
        <button
          type="button"
          onClick={onReset}
          disabled={!saved}
          title={t("games.reset_field")}
          aria-label={`${t("games.reset_field")}: ${setting.label}`}
          className={cn(
            "flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground",
            !saved && "invisible",
          )}
        >
          <RotateCcw className="h-3.5 w-3.5" aria-hidden />
        </button>
      </div>
    </div>
  );
}

function toNumber(raw: string): number | null {
  if (raw.trim() === "") return null;
  const value = Number(raw.replace(",", "."));
  return Number.isFinite(value) ? value : null;
}

export function NumberField({
  value,
  setting,
  onCommit,
  className,
}: {
  value: number | null;
  setting: GameSetting;
  onCommit: (value: number | null) => void;
  className?: string;
}) {
  const [draft, setDraft] = useState(value === null ? "" : String(value));
  useEffect(() => setDraft(value === null ? "" : String(value)), [value]);
  const commit = () => {
    const next = toNumber(draft);
    if (next === value) return;
    if (draft.trim() !== "" && next === null) {
      setDraft(value === null ? "" : String(value));
      return;
    }
    onCommit(next);
  };
  return (
    <Input
      inputMode="decimal"
      value={draft}
      placeholder={setting.default !== null ? String(setting.default) : "—"}
      aria-label={setting.label}
      onChange={(event) => setDraft(event.currentTarget.value)}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === "Enter") (event.currentTarget as HTMLInputElement).blur();
      }}
      className={cn("h-8 font-mono tabular-nums", className)}
    />
  );
}

/** How long after the last change a slider value is saved on its own. */
const SETTLE_MS = 500;

/**
 * A range input whose track fills up to the thumb in the signal colour. The
 * fill is a background gradient driven by one CSS variable.
 *
 * A drag ends wherever the mouse is let go, not only on the slider: the
 * release is caught on the window, so a drag that drifts up off the track
 * still saves when the mouse is let go. While
 * dragging, text selection is blocked so the page does not start selecting
 * and shift. A change that never sees a release (keyboard, a lost pointer)
 * saves itself once it has been still for a moment.
 */
export function FilledRange({
  min,
  max,
  step,
  value,
  label,
  dim,
  onDraft,
  onCommit,
}: {
  min: number;
  max: number;
  step?: number;
  value: number;
  label: string;
  dim?: boolean;
  onDraft: (value: number) => void;
  onCommit: () => void;
}) {
  const commitRef = useRef(onCommit);
  commitRef.current = onCommit;
  const settleTimer = useRef<number | null>(null);
  const endDrag = useRef<(() => void) | null>(null);

  const clearSettle = () => {
    if (settleTimer.current !== null) window.clearTimeout(settleTimer.current);
    settleTimer.current = null;
  };
  const commit = () => {
    clearSettle();
    commitRef.current();
  };

  useEffect(
    () => () => {
      endDrag.current?.();
      // Leaving with an unsaved change (tab switch mid-drag) still saves it.
      if (settleTimer.current !== null) commit();
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- unmount only
    [],
  );

  const startDrag = (_event: ReactPointerEvent<HTMLInputElement>) => {
    endDrag.current?.();
    const noSelect = (e: Event) => e.preventDefault();
    const finish = () => {
      window.removeEventListener("pointerup", finish, true);
      window.removeEventListener("pointercancel", finish, true);
      document.removeEventListener("selectstart", noSelect, true);
      endDrag.current = null;
      commit();
    };
    window.addEventListener("pointerup", finish, true);
    window.addEventListener("pointercancel", finish, true);
    document.addEventListener("selectstart", noSelect, true);
    endDrag.current = () => {
      window.removeEventListener("pointerup", finish, true);
      window.removeEventListener("pointercancel", finish, true);
      document.removeEventListener("selectstart", noSelect, true);
      endDrag.current = null;
    };
  };

  const pct = max > min ? ((value - min) / (max - min)) * 100 : 0;
  return (
    <input
      type="range"
      min={min}
      max={max}
      step={step ?? "any"}
      value={value}
      aria-label={label}
      onPointerDown={startDrag}
      onChange={(event) => {
        onDraft(Number(event.currentTarget.value));
        clearSettle();
        // During a drag the release saves; otherwise settle after a pause.
        if (endDrag.current === null) settleTimer.current = window.setTimeout(commit, SETTLE_MS);
      }}
      onKeyUp={commit}
      onBlur={() => {
        if (endDrag.current === null) commit();
      }}
      style={{ "--fill": `${pct}%` } as CSSProperties}
      className={cn(
        "h-1.5 min-w-0 flex-1 cursor-pointer touch-none select-none appearance-none rounded-full",
        "bg-[linear-gradient(to_right,hsl(var(--accent))_var(--fill),hsl(var(--border))_var(--fill))]",
        "[&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-accent [&::-webkit-slider-thumb]:bg-background [&::-webkit-slider-thumb]:shadow-[0_0_10px_hsl(var(--accent)/0.6)]",
        "[&::-moz-range-thumb]:h-4 [&::-moz-range-thumb]:w-4 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border-2 [&::-moz-range-thumb]:border-accent [&::-moz-range-thumb]:bg-background",
        dim && "opacity-50",
      )}
    />
  );
}

export function GameSettingRow({
  setting,
  value,
  onChange,
}: {
  setting: GameSetting;
  /** The saved value, or undefined when the game default applies. */
  value: GameSettingValue | undefined;
  onChange: (value: GameSettingValue | null) => void;
}) {
  const t = useT();
  const saved = value !== undefined;
  const effective = saved ? value : setting.default;
  const reset = () => onChange(null);

  if (setting.type === "toggle") {
    return (
      <SettingShell setting={setting} saved={saved} onReset={reset}>
        <Switch
          checked={effective === true}
          aria-label={setting.label}
          onCheckedChange={(next) => onChange(next)}
        />
      </SettingShell>
    );
  }

  if (setting.type === "select") {
    const options = setting.options ?? [];
    const current = typeof effective === "string" ? effective : null;
    return (
      <SettingShell setting={setting} saved={saved} onReset={reset}>
        {fitsSegmented(options) ? (
          <Segmented
            label={setting.label}
            value={current}
            options={options.map((option) => ({ value: option, label: option }))}
            onChange={(next) => onChange(next)}
          />
        ) : (
          <BrandedSelect
            value={current ?? ""}
            options={options.map((option) => ({ value: option, label: option }))}
            onValueChange={(next) => onChange(next)}
            ariaLabel={setting.label}
            placeholder={t("games.unset")}
            className="h-8 w-full max-w-xs"
          />
        )}
      </SettingShell>
    );
  }

  if (setting.type === "text") {
    return (
      <SettingShell setting={setting} saved={saved} onReset={reset}>
        <TextField
          value={typeof value === "string" ? value : ""}
          label={setting.label}
          onCommit={(next) => onChange(next === "" ? null : next)}
        />
      </SettingShell>
    );
  }

  const numeric = typeof effective === "number" ? effective : null;
  return (
    <SettingShell setting={setting} saved={saved} onReset={reset}>
      {setting.type === "slider" ? (
        <SliderField setting={setting} value={numeric} saved={saved} onCommit={onChange} />
      ) : (
        <NumberField
          setting={setting}
          value={saved ? numeric : null}
          onCommit={onChange}
          className="max-w-[10rem]"
        />
      )}
    </SettingShell>
  );
}

function SliderField({
  setting,
  value,
  saved,
  onCommit,
}: {
  setting: GameSetting;
  value: number | null;
  saved: boolean;
  onCommit: (value: number | null) => void;
}) {
  const min = setting.min ?? 0;
  const max = setting.max ?? 100;
  const [draft, setDraft] = useState<number>(value ?? min);
  const [touched, setTouched] = useState(false);
  // The commit can run from a window listener registered when the drag
  // began, so it reads the latest draft from a ref, never a stale closure.
  const draftRef = useRef(draft);
  const dirty = useRef(false);
  useEffect(() => {
    if (dirty.current) return;
    setDraft(value ?? min);
    draftRef.current = value ?? min;
  }, [value, min]);
  return (
    <div className="flex items-center gap-3">
      <FilledRange
        min={min}
        max={max}
        step={setting.step}
        value={draft}
        label={setting.label}
        dim={!saved && !touched && value === null}
        onDraft={(next) => {
          dirty.current = true;
          draftRef.current = next;
          setTouched(true);
          setDraft(next);
        }}
        onCommit={() => {
          if (!dirty.current) return;
          dirty.current = false;
          onCommit(draftRef.current);
        }}
      />
      {/* The number follows the thumb while dragging, not only after release. */}
      <NumberField
        setting={setting}
        value={saved || touched ? draft : null}
        onCommit={(next) => {
          if (next !== null) {
            setTouched(true);
            setDraft(next);
            draftRef.current = next;
          }
          onCommit(next);
        }}
        className="w-24 shrink-0"
      />
    </div>
  );
}

function TextField({
  value,
  label,
  onCommit,
}: {
  value: string;
  label: string;
  onCommit: (value: string) => void;
}) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  return (
    <Input
      value={draft}
      aria-label={label}
      maxLength={200}
      onChange={(event) => setDraft(event.currentTarget.value)}
      onBlur={() => draft.trim() !== value && onCommit(draft.trim())}
      onKeyDown={(event) => {
        if (event.key === "Enter") (event.currentTarget as HTMLInputElement).blur();
      }}
      className="h-8 font-mono"
    />
  );
}

/** A bind drawn as keycaps: "Shift + Mouse 4" → [Shift] + [Mouse 4]. */
export function Keycaps({ combo, empty }: { combo: string; empty: string }) {
  const parts = comboParts(combo);
  if (parts.length === 0) return <span className="text-muted-foreground">{empty}</span>;
  return (
    <span className="inline-flex items-center gap-1">
      {parts.map((part, index) => (
        <span key={`${part}-${index}`} className="inline-flex items-center gap-1">
          {index > 0 && <span className="text-muted-foreground/60">+</span>}
          <kbd className="rounded border border-border-strong bg-background px-1.5 py-0.5 font-mono text-[11px] text-foreground shadow-[inset_0_-2px_0_hsl(var(--border))]">
            {part}
          </kbd>
        </span>
      ))}
    </span>
  );
}

/**
 * A button that shows the bound key; click it, then press a key, a mouse
 * button or turn the wheel — while holding Ctrl / Shift / Alt for a
 * combination. A modifier pressed and released alone binds itself ("Left
 * Shift" for sprint). Escape cancels. While listening, presses are swallowed
 * so app shortcuts do not fire.
 */
export function KeyCaptureButton({
  value,
  label,
  onCapture,
  compact,
}: {
  value: string;
  label: string;
  onCapture: (key: string) => void;
  compact?: boolean;
}) {
  const t = useT();
  const [listening, setListening] = useState(false);
  const [held, setHeld] = useState<HeldModifiers>({ ctrl: false, shift: false, alt: false });
  const captureRef = useRef(onCapture);
  captureRef.current = onCapture;

  useEffect(() => {
    if (!listening) return;
    let mods: HeldModifiers = { ctrl: false, shift: false, alt: false };
    let lastModifier: string | null = null;
    const finish = (key: string | null) => {
      setListening(false);
      setHeld({ ctrl: false, shift: false, alt: false });
      if (key) captureRef.current(key);
    };
    const swallow = (event: Event) => {
      event.preventDefault();
      event.stopPropagation();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      swallow(event);
      if (event.code === "Escape") return finish(null);
      if (MODIFIER_CODES.has(event.code)) {
        mods = { ctrl: event.ctrlKey, shift: event.shiftKey, alt: event.altKey };
        lastModifier = keyNameFromCode(event.code);
        setHeld(mods);
        return;
      }
      const name = keyNameFromCode(event.code);
      if (name) finish(comboName({ ctrl: event.ctrlKey, shift: event.shiftKey, alt: event.altKey }, name));
    };
    const onKeyUp = (event: KeyboardEvent) => {
      swallow(event);
      // A modifier pressed and let go on its own binds the modifier itself.
      if (MODIFIER_CODES.has(event.code) && lastModifier === keyNameFromCode(event.code)) {
        const others = { ...mods };
        if (/Ctrl$/.test(lastModifier ?? "")) others.ctrl = false;
        if (/Shift$/.test(lastModifier ?? "")) others.shift = false;
        if (/Alt$/.test(lastModifier ?? "")) others.alt = false;
        finish(comboName(others, lastModifier as string));
      }
    };
    const onMouse = (event: MouseEvent) => {
      swallow(event);
      const name = mouseButtonName(event.button);
      if (name) finish(comboName({ ctrl: event.ctrlKey, shift: event.shiftKey, alt: event.altKey }, name));
    };
    const onWheel = (event: WheelEvent) => {
      swallow(event);
      if (event.deltaY !== 0) {
        finish(comboName({ ctrl: event.ctrlKey, shift: event.shiftKey, alt: event.altKey }, wheelName(event.deltaY)));
      }
    };
    // Registered on the next tick so the click that started listening is not
    // itself taken as the binding.
    const timer = window.setTimeout(() => {
      window.addEventListener("keydown", onKeyDown, true);
      window.addEventListener("keyup", onKeyUp, true);
      window.addEventListener("mousedown", onMouse, true);
      window.addEventListener("wheel", onWheel, { capture: true, passive: false });
      window.addEventListener("contextmenu", swallow, true);
    }, 0);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("keydown", onKeyDown, true);
      window.removeEventListener("keyup", onKeyUp, true);
      window.removeEventListener("mousedown", onMouse, true);
      window.removeEventListener("wheel", onWheel, true);
      window.removeEventListener("contextmenu", swallow, true);
    };
  }, [listening]);

  const heldText = comboParts(comboName(held, "")).join(" + ");
  return (
    <button
      type="button"
      aria-label={`${label}: ${value || t("games.keybind_unbound")}`}
      aria-pressed={listening}
      onClick={() => setListening(true)}
      className={cn(
        "flex h-9 items-center justify-center rounded-md border px-2.5 text-xs transition-all",
        compact ? "min-w-[6.5rem]" : "min-w-[9rem]",
        listening
          ? "animate-pulse border-accent bg-accent/10 text-foreground shadow-[0_0_14px_hsl(var(--accent)/0.5)]"
          : "border-border bg-muted/60 hover:border-border-strong hover:bg-muted",
      )}
    >
      {listening ? (
        <span className="font-mono">{heldText ? `${heldText} + …` : t("games.keybind_press")}</span>
      ) : (
        <Keycaps combo={value} empty={t("games.keybind_unbound")} />
      )}
    </button>
  );
}
