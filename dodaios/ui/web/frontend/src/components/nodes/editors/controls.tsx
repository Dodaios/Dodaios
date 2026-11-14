/**
 * The small controls every node editor's toolbar and inspector are made of.
 *
 * They sit on the app's kit (`components/ui`): the same focus ring, radius,
 * surfaces and type steps as the rest of the app, so six editors written by
 * different hands still read as one product. Each is a real, labelled
 * control: icon-only buttons carry their name for screen readers and in a
 * tooltip, toggles say whether they are on (`aria-pressed`), menus are
 * reachable and closable with the keyboard.
 */
import {
  cloneElement,
  forwardRef,
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactElement,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { Check } from "lucide-react";

import { BrandedSelect } from "@/components/ui/select";
import { QuickTooltip } from "@/components/ui/tooltip";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";

/* ------------------------------------------------------------- buttons */

export interface ToolbarButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children"> {
  /** The control's name: read aloud, and shown in the tooltip (or beside the icon). */
  label: string;
  icon?: ReactNode;
  /** A toggle that is on (bold, a chosen alignment). Leave undefined for a plain action. */
  active?: boolean;
  /** A key hint for the tooltip, e.g. "⌘B". */
  shortcut?: string;
  /** Show the label as text beside the icon. */
  showLabel?: boolean;
  /** Extra content after the label (a chevron). */
  trailing?: ReactNode;
}

export const ToolbarButton = forwardRef<HTMLButtonElement, ToolbarButtonProps>(function ToolbarButton(
  { label, icon, active, shortcut, showLabel = false, trailing, className, type = "button", ...rest },
  ref,
) {
  const button = (
    <button
      ref={ref}
      type={type}
      aria-label={showLabel ? undefined : label}
      aria-pressed={active === undefined ? undefined : active}
      className={cn(
        "inline-flex h-8 shrink-0 items-center justify-center gap-1.5 rounded-md text-sm text-foreground",
        "transition-colors hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        "disabled:pointer-events-none disabled:opacity-40 [&_svg]:h-4 [&_svg]:w-4 [&_svg]:shrink-0",
        showLabel || trailing ? "px-2.5" : "w-8",
        active && "bg-secondary text-foreground ring-1 ring-inset ring-border-strong",
        className,
      )}
      {...rest}
    >
      {icon}
      {showLabel && <span>{label}</span>}
      {trailing}
    </button>
  );
  const tip = shortcut ? `${label}  ${shortcut}` : label;
  return (
    <QuickTooltip content={showLabel && !shortcut ? "" : tip} side="bottom" className="inline-flex">
      {button}
    </QuickTooltip>
  );
});

/** A run of related toolbar controls, named for assistive technology. */
export function ToolbarGroup({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div role="group" aria-label={label} className={cn("flex shrink-0 items-center gap-0.5", className)}>
      {children}
    </div>
  );
}

export function ToolbarSeparator() {
  return <div role="separator" aria-orientation="vertical" className="mx-1 h-5 w-px shrink-0 bg-border" />;
}

/* ------------------------------------------------------------- popover */

export interface PopoverProps {
  /** The element that opens the popover; it gets the click and the ARIA wiring. */
  trigger: ReactElement;
  children: ReactNode | ((close: () => void) => ReactNode);
  /** The popover's accessible name. */
  label: string;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  align?: "start" | "end";
  /** "menu" for a list of actions (arrow keys move), "dialog" for a small form. */
  role?: "menu" | "dialog";
  className?: string;
}

/**
 * A panel anchored under its trigger, drawn in a portal above everything.
 * Closes on Escape, on a click outside and (for a menu) when an item is
 * picked; focus goes into it on open and back to the trigger on close.
 */
export function Popover({
  trigger,
  children,
  label,
  open: openProp,
  onOpenChange,
  align = "start",
  role = "dialog",
  className,
}: PopoverProps) {
  const [openState, setOpenState] = useState(false);
  const open = openProp ?? openState;
  const setOpen = useCallback(
    (next: boolean) => {
      if (openProp === undefined) setOpenState(next);
      onOpenChange?.(next);
    },
    [openProp, onOpenChange],
  );
  const anchor = useRef<HTMLElement | null>(null);
  const panel = useRef<HTMLDivElement | null>(null);
  const [place, setPlace] = useState<{ left: number; top: number } | null>(null);
  const id = useId();
  const close = useCallback(() => {
    setOpen(false);
    anchor.current?.focus();
  }, [setOpen]);

  useLayoutEffect(() => {
    if (!open || !anchor.current) {
      setPlace(null);
      return;
    }
    const measure = () => {
      const box = anchor.current?.getBoundingClientRect();
      if (!box) return;
      const width = panel.current?.offsetWidth ?? 0;
      const height = panel.current?.offsetHeight ?? 0;
      let left = align === "end" ? box.right - width : box.left;
      left = Math.max(8, Math.min(left, window.innerWidth - width - 8));
      let top = box.bottom + 6;
      if (top + height > window.innerHeight - 8 && box.top - height - 6 > 8) top = box.top - height - 6;
      setPlace({ left, top });
    };
    measure();
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [open, align]);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      const target = event.target as Node;
      if (panel.current?.contains(target) || anchor.current?.contains(target)) return;
      setOpen(false);
    };
    window.addEventListener("pointerdown", onPointer, true);
    // Focus the first control inside once it is placed.
    const frame = window.requestAnimationFrame(() => {
      const first = panel.current?.querySelector<HTMLElement>(
        '[role="menuitem"]:not([disabled]), button:not([disabled]), input, [tabindex]:not([tabindex="-1"])',
      );
      first?.focus();
    });
    return () => {
      window.removeEventListener("pointerdown", onPointer, true);
      window.cancelAnimationFrame(frame);
    };
  }, [open, setOpen]);

  const onKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      close();
      return;
    }
    if (role !== "menu" || (event.key !== "ArrowDown" && event.key !== "ArrowUp")) return;
    const items = Array.from(panel.current?.querySelectorAll<HTMLElement>('[role="menuitem"]:not([disabled])') ?? []);
    if (items.length === 0) return;
    event.preventDefault();
    const at = items.indexOf(document.activeElement as HTMLElement);
    const next = event.key === "ArrowDown" ? (at + 1) % items.length : (at - 1 + items.length) % items.length;
    items[next]?.focus();
  };

  const triggerProps = trigger.props as { onClick?: (event: unknown) => void };
  const wired = cloneElement(trigger, {
    ref: (node: HTMLElement | null) => {
      anchor.current = node;
    },
    "aria-haspopup": role,
    "aria-expanded": open,
    "aria-controls": open ? id : undefined,
    onClick: (event: unknown) => {
      triggerProps.onClick?.(event);
      setOpen(!open);
    },
  } as Record<string, unknown>);

  return (
    <>
      {wired}
      {open &&
        createPortal(
          <div
            ref={panel}
            id={id}
            role={role}
            aria-label={label}
            onKeyDown={onKeyDown}
            onClick={(event) => {
              if (role === "menu" && (event.target as HTMLElement).closest('[role="menuitem"]')) close();
            }}
            style={{ left: place?.left ?? -9999, top: place?.top ?? -9999 }}
            className={cn(
              "fixed z-[100] min-w-[10rem] rounded-lg border border-border bg-popover p-1 text-popover-foreground shadow-float",
              className,
            )}
            data-node-editor-popover=""
          >
            {typeof children === "function" ? children(close) : children}
          </div>,
          document.body,
        )}
    </>
  );
}

export interface MenuItemProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children"> {
  label: string;
  icon?: ReactNode;
  /** A key hint on the right. */
  shortcut?: string;
  /** A ticked choice. */
  checked?: boolean;
  destructive?: boolean;
}

export function MenuItem({ label, icon, shortcut, checked, destructive, className, ...rest }: MenuItemProps) {
  return (
    <button
      type="button"
      role={checked === undefined ? "menuitem" : "menuitemcheckbox"}
      aria-checked={checked}
      className={cn(
        "flex h-8 w-full items-center gap-2 rounded-md px-2 text-left text-sm",
        "hover:bg-secondary focus-visible:bg-secondary focus-visible:outline-none disabled:opacity-40",
        "[&_svg]:h-4 [&_svg]:w-4 [&_svg]:shrink-0",
        destructive && "text-destructive",
        className,
      )}
      {...rest}
    >
      <span className="flex w-4 shrink-0 justify-center">{checked ? <Check aria-hidden /> : icon}</span>
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {shortcut && <span className="shrink-0 text-xs text-muted-foreground">{shortcut}</span>}
    </button>
  );
}

/* --------------------------------------------------------------- colour */

/**
 * The kit's series colours (`design_guide.py`, light theme), in slot order,
 * then a few neutrals. A chart or a fill picked from these looks at home on
 * every page the renderers draw.
 */
export const KIT_COLORS: readonly string[] = [
  "#2A6FD0",
  "#D4532E",
  "#158F6B",
  "#A86B00",
  "#5B46C2",
  "#C23F86",
  "#1F2328",
  "#59636E",
  "#D1D9E0",
  "#FFFFFF",
];

const HEX_RE = /^#[0-9a-f]{6}$/i;

/** `value` as "#rrggbb", or null. Accepts "#rgb" and missing "#". */
export function normalizeHex(value: string): string | null {
  let text = value.trim();
  if (!text.startsWith("#")) text = `#${text}`;
  if (/^#[0-9a-f]{3}$/i.test(text)) text = `#${text[1]}${text[1]}${text[2]}${text[2]}${text[3]}${text[3]}`;
  return HEX_RE.test(text) ? text.toUpperCase() : null;
}

export interface ColorPickerProps {
  /** "#rrggbb", or "" for the default (the kit's own colour for that place). */
  value: string;
  onChange: (value: string) => void;
  label: string;
  /** Offer "Default" (value ""). */
  allowDefault?: boolean;
  /** Colours to offer instead of the kit's. */
  palette?: readonly string[];
  className?: string;
}

/** A swatch that opens the kit palette with a custom colour field. */
export function ColorPicker({ value, onChange, label, allowDefault = true, palette = KIT_COLORS, className }: ColorPickerProps) {
  const t = useT();
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const commitDraft = () => {
    const hex = normalizeHex(draft);
    if (hex) onChange(hex);
    else setDraft(value);
  };
  return (
    <Popover
      label={label}
      trigger={
        <button
          type="button"
          aria-label={`${label}: ${value || t("nodes.editor.color.default")}`}
          className={cn(
            "inline-flex h-8 items-center gap-2 rounded-md border border-border-strong px-2 text-sm",
            "hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            className,
          )}
        >
          <span
            aria-hidden
            className="h-4 w-4 rounded-sm border border-border"
            style={
              value
                ? { background: value }
                : { background: "repeating-linear-gradient(45deg, transparent 0 3px, hsl(var(--border)) 3px 4px)" }
            }
          />
        </button>
      }
    >
      {(close) => (
        <div className="w-56 p-2">
          <div className="grid grid-cols-5 gap-1.5" role="group" aria-label={label}>
            {palette.map((colour) => (
              <button
                key={colour}
                type="button"
                aria-label={colour}
                aria-pressed={value.toUpperCase() === colour.toUpperCase()}
                onClick={() => {
                  onChange(colour);
                  close();
                }}
                className={cn(
                  "h-8 rounded-md border border-border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  value.toUpperCase() === colour.toUpperCase() && "ring-2 ring-accent ring-offset-1 ring-offset-popover",
                )}
                style={{ background: colour }}
              />
            ))}
          </div>
          <div className="mt-2 flex items-center gap-1.5">
            <input
              type="color"
              aria-label={t("nodes.editor.color.custom")}
              value={normalizeHex(draft) ?? "#000000"}
              onChange={(event) => {
                setDraft(event.target.value);
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
          {allowDefault && (
            <button
              type="button"
              onClick={() => {
                onChange("");
                close();
              }}
              className="mt-2 h-8 w-full rounded-md text-left text-sm text-muted-foreground hover:bg-secondary focus-visible:bg-secondary focus-visible:outline-none px-2"
            >
              {t("nodes.editor.color.default")}
            </button>
          )}
        </div>
      )}
    </Popover>
  );
}

/* --------------------------------------------------------------- number */

export interface NumberFieldProps {
  value: number | null;
  onChange: (value: number | null) => void;
  label: string;
  /** Show the label above the field instead of only to assistive technology. */
  showLabel?: boolean;
  min?: number;
  max?: number;
  step?: number;
  /** Fixed decimals shown; the value is rounded to them. */
  decimals?: number;
  /** A unit after the number ("px", "s", "%"). */
  suffix?: string;
  /** Empty is a valid value (null). */
  allowEmpty?: boolean;
  disabled?: boolean;
  className?: string;
  id?: string;
}

function clampNumber(value: number, min?: number, max?: number): number {
  let out = value;
  if (min !== undefined) out = Math.max(min, out);
  if (max !== undefined) out = Math.min(max, out);
  return out;
}

/**
 * A number typed freely and taken on Enter or when the field is left (a
 * half-typed "1." is never saved); ArrowUp/ArrowDown step it, with Shift by
 * ten steps. A comma is read as a decimal point.
 */
export function NumberField({
  value,
  onChange,
  label,
  showLabel = false,
  min,
  max,
  step = 1,
  decimals,
  suffix,
  allowEmpty = false,
  disabled,
  className,
  id,
}: NumberFieldProps) {
  const ownId = useId();
  const fieldId = id ?? ownId;
  const shown = (n: number | null) => (n === null ? "" : decimals !== undefined ? n.toFixed(decimals) : String(n));
  const [draft, setDraft] = useState(shown(value));
  const focused = useRef(false);
  useEffect(() => {
    if (!focused.current) setDraft(shown(value));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, decimals]);
  const round = (n: number) => (decimals !== undefined ? Number(n.toFixed(decimals)) : n);
  const take = (text: string) => {
    const clean = text.trim().replace(",", ".");
    if (clean === "") {
      if (allowEmpty) onChange(null);
      setDraft(allowEmpty ? "" : shown(value));
      return;
    }
    const parsed = Number(clean);
    if (!Number.isFinite(parsed)) {
      setDraft(shown(value));
      return;
    }
    const next = round(clampNumber(parsed, min, max));
    setDraft(shown(next));
    if (next !== value) onChange(next);
  };
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      {showLabel && (
        <label htmlFor={fieldId} className="text-xs text-muted-foreground">
          {label}
        </label>
      )}
      <div className="flex h-8 items-center rounded-md border border-border-strong bg-input focus-within:border-accent focus-within:ring-2 focus-within:ring-ring">
        <input
          id={fieldId}
          type="text"
          inputMode="decimal"
          role="spinbutton"
          aria-label={showLabel ? undefined : label}
          aria-valuenow={value ?? undefined}
          aria-valuemin={min}
          aria-valuemax={max}
          disabled={disabled}
          value={draft}
          onFocus={() => {
            focused.current = true;
          }}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={(event) => {
            focused.current = false;
            take(event.target.value);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              take(draft);
            } else if (event.key === "Escape") {
              setDraft(shown(value));
            } else if (event.key === "ArrowUp" || event.key === "ArrowDown") {
              event.preventDefault();
              const base = Number(draft.replace(",", "."));
              const from = Number.isFinite(base) && draft.trim() !== "" ? base : (value ?? min ?? 0);
              const delta = (event.key === "ArrowUp" ? 1 : -1) * step * (event.shiftKey ? 10 : 1);
              const next = round(clampNumber(from + delta, min, max));
              setDraft(shown(next));
              onChange(next);
            }
          }}
          className="h-full min-w-0 flex-1 bg-transparent px-2 text-sm tabular-nums text-foreground focus:outline-none disabled:opacity-50"
        />
        {suffix && <span className="pr-2 text-xs text-muted-foreground">{suffix}</span>}
      </div>
    </div>
  );
}

/* --------------------------------------------------------------- select */

export interface SelectOption {
  value: string;
  label: string;
  hint?: string;
  icon?: ReactNode;
  disabled?: boolean;
}

export interface SelectProps {
  value: string;
  options: readonly SelectOption[];
  onChange: (value: string) => void;
  label: string;
  showLabel?: boolean;
  disabled?: boolean;
  className?: string;
  testId?: string;
}

/** A short choice on the app's own listbox (never the system's popup). */
export function Select({ value, options, onChange, label, showLabel = false, disabled, className, testId }: SelectProps) {
  const id = useId();
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      {showLabel && (
        <label htmlFor={id} className="text-xs text-muted-foreground">
          {label}
        </label>
      )}
      <BrandedSelect
        id={id}
        value={value}
        options={options}
        onValueChange={onChange}
        ariaLabel={label}
        disabled={disabled}
        testId={testId}
        className="h-8 text-sm"
      />
    </div>
  );
}

/* ------------------------------------------------------------ text field */

export interface InspectorFieldProps {
  label: string;
  children: (id: string) => ReactNode;
  hint?: string;
  className?: string;
}

/** A labelled row of an inspector panel: the label, the control, a hint under it. */
export function InspectorField({ label, children, hint, className }: InspectorFieldProps) {
  const id = useId();
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <label htmlFor={id} className="text-xs text-muted-foreground">
        {label}
      </label>
      {children(id)}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}
