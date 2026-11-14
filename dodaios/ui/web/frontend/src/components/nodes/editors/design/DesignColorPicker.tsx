/**
 * A colour control for a design: the theme's tokens first, a free colour
 * beside them.
 *
 * The shared `ColorPicker` offers fixed hex colours, right for a chart. A
 * design is different: its page switches between a light and a dark theme,
 * and a colour taken from the theme's tokens switches with it, so the
 * design stays readable in both. So this control writes token references
 * (`var(--accent)`, or the spec's colour names for the page's ground and
 * accent) by default, and a hex only when the person types or picks one.
 */
import { useEffect, useState } from "react";

import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { Popover, normalizeHex } from "../controls";
import type { ColorChoice } from "./designBlocks";

export interface DesignColorPickerProps {
  /** A token value from `choices`, a hex, any other CSS colour, or "" for none. */
  value: string;
  onChange: (value: string) => void;
  label: string;
  choices: readonly ColorChoice[];
  className?: string;
  testId?: string;
}

/** What the swatch shows for `value`: the token's sample, the colour itself, or nothing. */
export function swatchOf(value: string, choices: readonly ColorChoice[]): string {
  const known = choices.find((choice) => choice.value === value);
  if (known) return known.swatch;
  return /^(#|rgb|hsl)/i.test(value.trim()) ? value.trim() : "";
}

export function DesignColorPicker({ value, onChange, label, choices, className, testId }: DesignColorPickerProps) {
  const t = useT();
  const known = choices.find((choice) => choice.value === value);
  const [draft, setDraft] = useState(known ? "" : value);
  useEffect(() => setDraft(choices.some((choice) => choice.value === value) ? "" : value), [value, choices]);
  const swatch = swatchOf(value, choices);
  const spoken = value ? (known ? known.name : value) : t("nodes.editor.color.default");
  const commitDraft = () => {
    const hex = normalizeHex(draft);
    if (hex) onChange(hex);
    else setDraft(known ? "" : value);
  };
  return (
    <Popover
      label={label}
      trigger={
        <button
          type="button"
          aria-label={`${label}: ${spoken}`}
          data-testid={testId}
          className={cn(
            "inline-flex h-8 min-w-0 items-center gap-2 rounded-md border border-border-strong px-2 text-sm",
            "hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            className,
          )}
        >
          <span
            aria-hidden
            className="h-4 w-4 shrink-0 rounded-sm border border-border"
            style={
              swatch
                ? { background: swatch }
                : { background: "repeating-linear-gradient(45deg, transparent 0 3px, hsl(var(--border)) 3px 4px)" }
            }
          />
          <span className="truncate text-muted-foreground">{spoken}</span>
        </button>
      }
    >
      {(close) => (
        <div className="w-60 p-2">
          <p className="px-0.5 pb-1.5 text-xs text-muted-foreground">{t("nodes.editor.design.color_tokens")}</p>
          <div className="grid grid-cols-6 gap-1.5" role="group" aria-label={label}>
            {choices.map((choice) => (
              <button
                key={choice.value}
                type="button"
                aria-label={choice.name}
                title={choice.name}
                aria-pressed={value === choice.value}
                onClick={() => {
                  onChange(choice.value);
                  close();
                }}
                className={cn(
                  "h-7 rounded-md border border-border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  value === choice.value && "ring-2 ring-accent ring-offset-1 ring-offset-popover",
                )}
                style={{ background: choice.swatch }}
              />
            ))}
          </div>
          <div className="mt-2 flex items-center gap-1.5">
            <input
              type="color"
              aria-label={t("nodes.editor.color.custom")}
              value={normalizeHex(draft) ?? normalizeHex(swatch) ?? "#000000"}
              onChange={(event) => {
                setDraft(event.target.value.toUpperCase());
                onChange(event.target.value.toUpperCase());
              }}
              className="h-8 w-8 shrink-0 cursor-pointer rounded-md border border-border bg-transparent p-0.5"
            />
            <input
              type="text"
              aria-label={t("nodes.editor.color.hex")}
              value={draft}
              placeholder="#2A6FD0"
              onChange={(event) => setDraft(event.target.value)}
              onBlur={commitDraft}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  commitDraft();
                }
              }}
              className="h-8 min-w-0 flex-1 rounded-md border border-border-strong bg-input px-2 font-mono text-sm focus-visible:border-accent focus-visible:outline-none"
            />
          </div>
          <button
            type="button"
            onClick={() => {
              onChange("");
              close();
            }}
            className="mt-2 h-8 w-full rounded-md px-2 text-left text-sm text-muted-foreground hover:bg-secondary focus-visible:bg-secondary focus-visible:outline-none"
          >
            {t("nodes.editor.color.default")}
          </button>
        </div>
      )}
    </Popover>
  );
}
