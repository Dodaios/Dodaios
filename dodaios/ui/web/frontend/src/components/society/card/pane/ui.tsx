/**
 * The agent pane's small building blocks: a titled section, a counted
 * anatomy row that opens somewhere, a compact segmented control, a chip list
 * with an add field. Styling lives in `agentPane.css` and uses theme tokens only.
 */
import { useRef, useState, type ReactNode } from "react";
import { Plus, X, type LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

export function PaneSection({
  title,
  action,
  children,
  className,
  testId,
}: {
  title?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  testId?: string;
}) {
  return (
    <section className={cn("ap-section", className)} data-testid={testId}>
      {title || action ? (
        <div className="ap-section-head">
          {title ? <h3 className="ap-section-title">{title}</h3> : <span />}
          {action}
        </div>
      ) : null}
      {children}
    </section>
  );
}

export function PaneHint({ children, className }: { children: ReactNode; className?: string }) {
  return <p className={cn("ap-hint", className)}>{children}</p>;
}

/** One text row in a pane card: what it is, one muted line about it, and a count when there is one. */
export function AnatomyRow({
  label,
  detail,
  count,
  attention,
  onOpen,
  testId,
}: {
  label: string;
  detail: string;
  count?: string | number | null;
  /** A small warn-coloured mark: something here waits for the person. */
  attention?: boolean;
  onOpen?: () => void;
  testId?: string;
}) {
  const body = (
    <>
      <span className="min-w-0 flex-1">
        <span className="ap-row-label">{label}</span>
        <span className="ap-row-detail">{detail}</span>
      </span>
      {count !== undefined && count !== null ? (
        <span className="ap-row-count">{count}</span>
      ) : null}
      {attention ? <span className="ap-row-dot" aria-hidden /> : null}
    </>
  );
  return onOpen ? (
    <button type="button" className="ap-row" onClick={onOpen} data-testid={testId}>
      {body}
    </button>
  ) : (
    <div className="ap-row" data-testid={testId}>
      {body}
    </div>
  );
}

export interface SegmentOption<T extends string> {
  value: T;
  label: string;
  title?: string;
  disabled?: boolean;
  icon?: LucideIcon;
}

/** A compact radio group drawn as a segmented control. */
export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
  size = "md",
  disabled = false,
  testId,
}: {
  value: T | null;
  options: SegmentOption<T>[];
  onChange: (value: T) => void;
  label: string;
  size?: "sm" | "md";
  disabled?: boolean;
  testId?: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="ap-seg" data-size={size} data-testid={testId}>
      {options.map((option) => {
        const Icon = option.icon;
        const checked = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={checked}
            aria-label={size === "sm" && Icon ? option.label : undefined}
            title={option.title ?? (size === "sm" ? option.label : undefined)}
            disabled={disabled || option.disabled}
            data-value={option.value}
            className="ap-seg-item"
            onClick={() => {
              if (!checked) onChange(option.value);
            }}
          >
            {Icon ? <Icon className="h-3 w-3" aria-hidden /> : null}
            {size === "sm" && Icon ? null : <span>{option.label}</span>}
          </button>
        );
      })}
    </div>
  );
}

/** Editable chips: each removable, plus a field that adds one (Enter or the + button). */
export function ChipList({
  items,
  onChange,
  placeholder,
  addLabel,
  removeLabel,
  normalize = (raw) => raw.trim(),
  suggestions,
  disabled = false,
  emptyText,
  testId,
}: {
  items: string[];
  onChange: (items: string[]) => void;
  placeholder: string;
  addLabel: string;
  /** "Remove {0}" */
  removeLabel: string;
  normalize?: (raw: string) => string;
  suggestions?: string[];
  disabled?: boolean;
  emptyText?: string;
  testId?: string;
}) {
  const [draft, setDraft] = useState("");
  const value = normalize(draft);
  const needle = draft.trim().toLowerCase();
  // Matches show as themed chips under the field, never as an OS popup.
  const matches = needle
    ? (suggestions ?? []).filter((s) => s.toLowerCase().includes(needle) && !items.includes(s) && s !== value).slice(0, 5)
    : [];
  const addValue = (next: string) => {
    setDraft("");
    if (!next || items.includes(next)) return;
    onChange([...items, next]);
  };
  const add = () => addValue(value);
  return (
    <div className="ap-chips" data-testid={testId}>
      {items.length === 0 && emptyText ? <span className="ap-hint">{emptyText}</span> : null}
      {items.length > 0 ? (
        <ul className="flex flex-wrap gap-1.5">
          {items.map((item) => (
            <li key={item} className="ap-chip">
              <span className="truncate">{item}</span>
              {disabled ? null : (
                <button
                  type="button"
                  className="ap-chip-x"
                  aria-label={removeLabel.replace("{0}", item)}
                  onClick={() => onChange(items.filter((x) => x !== item))}
                >
                  <X className="h-3 w-3" aria-hidden />
                </button>
              )}
            </li>
          ))}
        </ul>
      ) : null}
      {disabled ? null : (
        <div className="ap-chip-add">
          <input
            className="ap-input"
            value={draft}
            placeholder={placeholder}
            aria-label={placeholder}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                add();
              }
            }}
          />
          <button type="button" className="ap-icon-btn" aria-label={addLabel} title={addLabel} disabled={!value} onClick={add}>
            <Plus className="h-3.5 w-3.5" aria-hidden />
          </button>
        </div>
      )}
      {matches.length ? (
        <div className="flex flex-wrap gap-1">
          {matches.map((match) => (
            <button key={match} type="button" className="ap-chip ap-chip-suggest" onClick={() => addValue(match)}>
              <Plus className="h-3 w-3" aria-hidden />
              <span className="truncate">{match}</span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

/** Inline text that turns into a field on click; Enter saves, Escape cancels. */
export function InlineEdit({
  value,
  onSave,
  label,
  placeholder,
  disabled = false,
  className,
  maxLength,
  testId,
}: {
  value: string;
  onSave: (next: string) => Promise<void>;
  label: string;
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  maxLength?: number;
  testId?: string;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // Enter commits and the blur that follows must not commit a second time.
  const committing = useRef(false);
  const commit = async () => {
    if (committing.current) return;
    const next = draft.trim();
    if (next === value.trim()) {
      setEditing(false);
      return;
    }
    committing.current = true;
    setBusy(true);
    setError("");
    try {
      await onSave(next);
      setEditing(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      committing.current = false;
      setBusy(false);
    }
  };
  if (!editing) {
    return (
      <button
        type="button"
        className={cn("ap-inline", className)}
        disabled={disabled}
        aria-label={`${label}: ${value || placeholder || ""}`}
        title={disabled ? undefined : label}
        data-testid={testId}
        onClick={() => {
          setDraft(value);
          setError("");
          setEditing(true);
        }}
      >
        {value ? <span className="truncate">{value}</span> : <span className="ap-inline-empty truncate">{placeholder}</span>}
      </button>
    );
  }
  return (
    <span className="flex min-w-0 flex-col gap-1">
      <input
        autoFocus
        className={cn("ap-input", className)}
        value={draft}
        aria-label={label}
        maxLength={maxLength}
        disabled={busy}
        data-testid={testId ? `${testId}-input` : undefined}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={() => void commit()}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            void commit();
          } else if (event.key === "Escape") {
            event.preventDefault();
            setEditing(false);
          }
        }}
      />
      {error ? (
        <span role="alert" className="text-xs text-destructive">
          {error}
        </span>
      ) : null}
    </span>
  );
}
