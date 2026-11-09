/**
 * The controls of the Verse settings menu, drawn like an in-game menu: a
 * "‹ value ›" stepper with option ticks, a filled bar for ranges and a keycap
 * for key bindings. Every control is keyboard reachable; the row passes
 * Left/Right through to the stepper and the bar.
 */
import { useCallback, useEffect, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { keyFromCode, keyFromMouse, keyLabel } from "@/lib/verseSettingsApi";

export function Stepper({
  options,
  value,
  label,
  onChange,
  disabled,
}: {
  options: string[];
  value: string;
  label: (option: string) => string;
  onChange: (next: string) => void;
  disabled?: boolean;
}) {
  const index = Math.max(0, options.indexOf(value));
  const step = (d: number) => {
    const next = options[(index + d + options.length) % options.length];
    if (next !== value) onChange(next);
  };
  const ticks = options.length <= 14;
  return (
    <div className={cn("vs-stepper", disabled && "opacity-40")} data-testid="vs-stepper">
      <button type="button" tabIndex={-1} aria-label="previous" className="vs-arrow" onClick={() => step(-1)} disabled={disabled}>
        <ChevronLeft className="h-4 w-4" />
      </button>
      <button type="button" tabIndex={-1} className="vs-stepper-value" onClick={() => step(1)} disabled={disabled}>
        <span className="truncate">{label(value)}</span>
        {ticks ? (
          <span className="vs-ticks" aria-hidden>
            {options.map((o, i) => (
              <span key={o} className={cn("vs-tick", i === index && "vs-tick-on")} />
            ))}
          </span>
        ) : null}
      </button>
      <button type="button" tabIndex={-1} aria-label="next" className="vs-arrow" onClick={() => step(1)} disabled={disabled}>
        <ChevronRight className="h-4 w-4" />
      </button>
    </div>
  );
}

export function Bar({
  value,
  min,
  max,
  step,
  text,
  onChange,
  ariaLabel,
}: {
  value: number;
  min: number;
  max: number;
  step: number;
  text: string;
  onChange: (next: number) => void;
  ariaLabel: string;
}) {
  const pct = max > min ? ((Math.min(max, Math.max(min, value)) - min) / (max - min)) * 100 : 0;
  return (
    <div className="vs-bar" data-testid="vs-bar">
      <div className="vs-bar-fill" style={{ width: `${pct}%` }} />
      <span className="vs-bar-text">{text}</span>
      <input
        type="range"
        tabIndex={-1}
        aria-label={ariaLabel}
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(roundTo(Number(e.target.value), step))}
        className="vs-bar-input"
      />
    </div>
  );
}

export function roundTo(value: number, step: number): number {
  const decimals = Math.max(0, (String(step).split(".")[1] ?? "").length);
  return Number((Math.round(value / step) * step).toFixed(decimals));
}

/**
 * A keycap; click it, then press a key or mouse button. Esc cancels. The
 * capture runs on window, so a key the app would otherwise use is caught too.
 */
export function KeyCap({
  value,
  listening,
  onListen,
  onPick,
  onCancel,
  pressText,
}: {
  value: string;
  listening: boolean;
  onListen: () => void;
  onPick: (key: string) => void;
  onCancel: () => void;
  pressText: string;
}) {
  const [armed, setArmed] = useState(false);

  const stop = useCallback((e: Event) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  useEffect(() => {
    if (!listening) {
      setArmed(false);
      return;
    }
    // The click that started listening must not count as Mouse 1.
    const armed = { current: false };
    const timer = window.setTimeout(() => {
      armed.current = true;
      setArmed(true);
    }, 120);
    const onKey = (e: KeyboardEvent) => {
      stop(e);
      if (e.code === "Escape") return onCancel();
      const key = keyFromCode(e.code);
      if (key) onPick(key);
    };
    const onMouse = (e: MouseEvent) => {
      if (!armed.current) return;
      stop(e);
      const key = keyFromMouse(e.button);
      if (key) onPick(key);
    };
    window.addEventListener("keydown", onKey, true);
    window.addEventListener("mousedown", onMouse, true);
    window.addEventListener("contextmenu", stop, true);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("keydown", onKey, true);
      window.removeEventListener("mousedown", onMouse, true);
      window.removeEventListener("contextmenu", stop, true);
    };
  }, [listening, onCancel, onPick, stop]);

  return (
    <button
      type="button"
      tabIndex={-1}
      data-testid="vs-keycap"
      className={cn("vs-keycap", listening && "vs-keycap-listening", listening && armed && "vs-keycap-armed")}
      onClick={() => (listening ? undefined : onListen())}
    >
      {listening ? pressText : keyLabel(value)}
    </button>
  );
}

/** Three bars for the performance cost of a graphics setting. */
export function ImpactMeter({ level }: { level: "low" | "medium" | "high" }) {
  const filled = level === "low" ? 1 : level === "medium" ? 2 : 3;
  return (
    <span className="vs-impact" aria-hidden>
      {[0, 1, 2].map((i) => (
        <span key={i} className={cn("vs-impact-bar", i < filled && `vs-impact-${level}`)} style={{ height: 6 + i * 4 }} />
      ))}
    </span>
  );
}

const CROSSHAIR_COLORS: Record<string, string> = {
  amber: "#f2b441",
  white: "#f4f1ea",
  green: "#5ee07a",
  cyan: "#4fd8e8",
  magenta: "#ee5fd0",
};

/** A live drawing of the crosshair the HUD settings describe. */
export function CrosshairPreview({
  style,
  color,
  size,
  thickness,
  gap,
  outline,
}: {
  style: string;
  color: string;
  size: number;
  thickness: number;
  gap: number;
  outline: boolean;
}) {
  const c = CROSSHAIR_COLORS[color] ?? CROSSHAIR_COLORS.amber;
  const len = 4 + size * 3;
  const g = 2 + gap * 2;
  const t = thickness * 1.5;
  const lines = style === "cross" || style === "cross_dot";
  const dot = style === "dot" || style === "cross_dot";
  const stroke = outline ? { stroke: "rgba(0,0,0,0.85)", strokeWidth: 1.5, paintOrder: "stroke" as const } : {};
  return (
    <svg viewBox="-60 -60 120 120" className="h-full w-full" role="img" aria-label="crosshair">
      {lines
        ? [
            [0, -g - len, t, len],
            [0, g, t, len],
            [-g - len, 0, len, t],
            [g, 0, len, t],
          ].map(([x, y, w, h], i) => (
            <rect
              key={i}
              x={i < 2 ? -w / 2 : x}
              y={i < 2 ? y : -h / 2}
              width={w}
              height={h}
              fill={c}
              {...stroke}
            />
          ))
        : null}
      {dot ? <circle r={Math.max(1.5, t)} fill={c} {...stroke} /> : null}
      {style === "circle" ? <circle r={g + len / 2} fill="none" stroke={c} strokeWidth={t} /> : null}
    </svg>
  );
}
