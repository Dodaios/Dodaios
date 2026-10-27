/**
 * The building blocks of Settings → Game settings: one row per game setting
 * (slider, number, choice, switch or text) and the keybind capture button.
 *
 * Rows keep a local draft while the user drags or types and hand the value
 * up only when it is settled (pointer up, blur, Enter), so a slider drag is
 * one save, not fifty.
 */
import { useEffect, useRef, useState, type ReactNode } from "react";
import { RotateCcw } from "lucide-react";
import { Input } from "@/components/ui/input";
import { BrandedSelect } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useT } from "@/i18n";
import { keyNameFromCode, mouseButtonName, wheelName } from "@/lib/gameKeys";
import type { GameSetting, GameSettingValue } from "@/lib/gamesApi";
import { cn } from "@/lib/utils";

function formatDefault(setting: GameSetting, t: (key: string) => string): string | null {
  const value = setting.default;
  if (value === null || value === undefined || value === "") return null;
  if (typeof value === "boolean") return value ? t("games.on") : t("games.off");
  return String(value);
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
      className="flex flex-col gap-2 border-b border-border/60 py-3 last:border-b-0 sm:flex-row sm:items-center sm:gap-6"
    >
      <div className="min-w-0 sm:w-[42%]">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-foreground">{setting.label}</span>
          {saved && (
            <span aria-hidden className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
          )}
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

function NumberField({
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
    return (
      <SettingShell setting={setting} saved={saved} onReset={reset}>
        <BrandedSelect
          value={typeof effective === "string" ? effective : ""}
          options={(setting.options ?? []).map((option) => ({ value: option, label: option }))}
          onValueChange={(next) => onChange(next)}
          ariaLabel={setting.label}
          placeholder={t("games.unset")}
          className="h-8 w-full max-w-xs"
        />
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
        <NumberField setting={setting} value={saved ? numeric : null} onCommit={onChange} className="max-w-[10rem]" />
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
  const dirty = useRef(false);
  useEffect(() => setDraft(value ?? min), [value, min]);
  const commit = () => {
    if (!dirty.current) return;
    dirty.current = false;
    onCommit(draft);
  };
  return (
    <div className="flex items-center gap-3">
      <input
        type="range"
        min={min}
        max={max}
        step={setting.step ?? "any"}
        value={draft}
        aria-label={setting.label}
        onChange={(event) => {
          dirty.current = true;
          setDraft(Number(event.currentTarget.value));
        }}
        onPointerUp={commit}
        onKeyUp={commit}
        onBlur={commit}
        className={cn("h-1 min-w-0 flex-1 cursor-pointer accent-primary", !saved && value === null && "opacity-50")}
      />
      <NumberField
        setting={setting}
        value={saved ? value : null}
        onCommit={onCommit}
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

/**
 * A button that shows the bound key; click it, then press a key, click a
 * mouse button or turn the wheel to bind. Escape cancels. While listening,
 * the press is swallowed so app shortcuts do not fire.
 */
export function KeyCaptureButton({
  value,
  label,
  onCapture,
}: {
  value: string;
  label: string;
  onCapture: (key: string) => void;
}) {
  const t = useT();
  const [listening, setListening] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!listening) return;
    const finish = (key: string | null) => {
      setListening(false);
      if (key) onCapture(key);
    };
    const onKey = (event: KeyboardEvent) => {
      event.preventDefault();
      event.stopPropagation();
      if (event.code === "Escape") return finish(null);
      finish(keyNameFromCode(event.code));
    };
    const onMouse = (event: MouseEvent) => {
      event.preventDefault();
      event.stopPropagation();
      finish(mouseButtonName(event.button));
    };
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      event.stopPropagation();
      if (event.deltaY !== 0) finish(wheelName(event.deltaY));
    };
    const block = (event: Event) => {
      event.preventDefault();
      event.stopPropagation();
    };
    // Registered on the next tick so the click that started listening is not
    // itself taken as the binding.
    const timer = window.setTimeout(() => {
      window.addEventListener("keydown", onKey, true);
      window.addEventListener("mousedown", onMouse, true);
      window.addEventListener("wheel", onWheel, { capture: true, passive: false });
      window.addEventListener("contextmenu", block, true);
    }, 0);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("keydown", onKey, true);
      window.removeEventListener("mousedown", onMouse, true);
      window.removeEventListener("wheel", onWheel, true);
      window.removeEventListener("contextmenu", block, true);
    };
  }, [listening, onCapture]);

  return (
    <button
      ref={buttonRef}
      type="button"
      aria-label={`${label}: ${value || t("games.keybind_unbound")}`}
      aria-pressed={listening}
      onClick={() => setListening(true)}
      className={cn(
        "flex h-8 min-w-[7.5rem] items-center justify-center rounded-md border px-3 font-mono text-xs transition-colors",
        listening
          ? "border-primary bg-primary/10 text-foreground"
          : "border-border bg-muted text-foreground hover:border-border-strong",
        !value && !listening && "text-muted-foreground",
      )}
    >
      {listening ? t("games.keybind_press") : value || t("games.keybind_unbound")}
    </button>
  );
}
