/**
 * The inspector beside the grid: the active column's settings (label, type
 * and number format, unit, decimals, total, formula, width, alignment, bold,
 * colour) and the sheet's own (frozen columns, the note under the title).
 *
 * Texts are taken when the field is left or Enter is pressed, never per
 * keystroke: `normalize` trims a label, and trimming while the person types
 * would swallow the space before the next word. A formula is checked as it
 * is typed (the same grammar the server applies) and only taken when it is
 * valid, so a half-typed formula never holds up the saving of everything else.
 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { AlignCenter, AlignLeft, AlignRight, Bold, X } from "lucide-react";

import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { InspectorField, NumberField, Select, ToolbarButton } from "../controls";
import { formulaPlan } from "./formula";
import {
  COLOR_TOKENS,
  COLUMN_COLORS,
  COLUMN_TYPES,
  MAX_DECIMALS,
  MAX_FORMULA_CHARS,
  MAX_LABEL_CHARS,
  MAX_NOTE_CHARS,
  MAX_UNIT_CHARS,
  MAX_WIDTH,
  MIN_WIDTH,
  TOTALS,
  type ColumnColor,
  type ColumnType,
  type ColumnView,
  type Sheet,
  type TotalKind,
} from "./model";
import { normalFormula, type ColumnPatch } from "./ops";

export interface ColumnPanelProps {
  sheet: Sheet;
  col: number;
  view: ColumnView | undefined;
  note: string;
  onPatch: (patch: ColumnPatch, label: string) => void;
  onFreeze: (count: number) => void;
  onNote: (note: string) => void;
  onClose: () => void;
  /** Bump to put focus on the label field (a double-click on a column head). */
  focusToken: number;
}

/** A text field that hands its value over when left or on Enter; Escape restores it. */
function CommitField({
  id,
  value,
  onCommit,
  maxLength,
  placeholder,
  invalid,
  inputRef,
  onDraft,
  testId,
  mono,
}: {
  id: string;
  value: string;
  onCommit: (text: string) => void;
  maxLength: number;
  placeholder?: string;
  invalid?: boolean;
  inputRef?: React.Ref<HTMLInputElement>;
  onDraft?: (text: string) => void;
  testId?: string;
  mono?: boolean;
}) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  return (
    <input
      id={id}
      ref={inputRef}
      value={draft}
      maxLength={maxLength}
      placeholder={placeholder}
      aria-invalid={invalid || undefined}
      data-own-undo=""
      data-testid={testId}
      onChange={(event) => {
        setDraft(event.target.value);
        onDraft?.(event.target.value);
      }}
      onBlur={() => {
        if (draft !== value) onCommit(draft);
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          if (draft !== value) onCommit(draft);
        } else if (event.key === "Escape") {
          event.stopPropagation();
          setDraft(value);
          onDraft?.(value);
        }
      }}
      className={cn(
        "h-8 w-full rounded-md border border-border-strong bg-input px-2 text-sm text-foreground focus:border-accent focus:outline-none focus:ring-2 focus:ring-ring",
        invalid && "border-destructive",
        mono && "font-mono",
      )}
    />
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h3>
      {children}
    </section>
  );
}

export function ColumnPanel({ sheet, col, view, note, onPatch, onFreeze, onNote, onClose, focusToken }: ColumnPanelProps) {
  const t = useT();
  const column = sheet.columns[col];
  const labelRef = useRef<HTMLInputElement | null>(null);
  const [formulaDraft, setFormulaDraft] = useState(column?.formula ?? "");
  useEffect(() => setFormulaDraft(column?.formula ?? ""), [column?.key, column?.formula]);
  useEffect(() => {
    if (focusToken > 0) window.requestAnimationFrame(() => labelRef.current?.focus());
  }, [focusToken]);

  const formulaError = useMemo(() => {
    if (!column) return "";
    const text = normalFormula(formulaDraft);
    if (!text) return "";
    const columns = sheet.columns.map((c, i) => (i === col ? { ...c, formula: text } : c));
    const problem = formulaPlan(columns).problems.find((p) => p.key === column.key);
    if (!problem) return "";
    if (problem.reason === "unknown") return t("nodes.editor.sheets.formula.unknown").replace("{0}", problem.name ?? "");
    if (problem.reason === "cycle") return t("nodes.editor.sheets.formula.cycle");
    return t("nodes.editor.sheets.formula.grammar");
  }, [formulaDraft, sheet.columns, col, column, t]);

  if (!column || !view) return null;
  const step = (name: string) => t(`nodes.editor.sheets.step.${name}`);
  const numeric = view.numeric;
  const typeOptions = COLUMN_TYPES.map((type) => ({ value: type, label: t(`nodes.editor.sheets.types.${type}`) }));
  const totalOptions = [
    { value: "", label: t("nodes.editor.sheets.total.none") },
    ...TOTALS.filter((total) => total === "count" || numeric || view.kind === "check").map((total) => ({
      value: total,
      label: t(`nodes.editor.sheets.total.${total}`),
    })),
  ];
  const otherKeys = sheet.columns.filter((c) => c.key !== column.key).map((c) => c.key);

  return (
    <div className="flex flex-col gap-6" data-testid="sheet-column-panel">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">{t("nodes.editor.sheets.panel.title")}</h2>
        <ToolbarButton label={t("nodes.editor.sheets.panel.close")} icon={<X aria-hidden />} onClick={onClose} />
      </div>
      <Section title={t("nodes.editor.sheets.panel.column")}>
        <InspectorField label={t("nodes.editor.sheets.panel.label")}>
          {(id) => (
            <CommitField
              id={id}
              inputRef={labelRef}
              value={column.label}
              maxLength={MAX_LABEL_CHARS}
              onCommit={(text) => text.trim() && onPatch({ label: text }, step("rename_column"))}
              testId="sheet-column-label"
            />
          )}
        </InspectorField>
        <p className="-mt-2 text-xs text-muted-foreground">
          {t("nodes.editor.sheets.panel.key")}: <code className="font-mono">{column.key}</code>
        </p>
        <Select
          label={t("nodes.editor.sheets.panel.type")}
          showLabel
          value={column.formula ? view.kind : (column.type ?? view.kind)}
          options={column.formula ? typeOptions.filter((o) => ["number", "currency", "percent"].includes(o.value)) : typeOptions}
          onChange={(value) => onPatch({ type: value as ColumnType }, step("column_type"))}
          testId="sheet-column-type"
        />
        {numeric && (
          <div className="grid grid-cols-2 gap-3">
            <InspectorField
              label={view.kind === "currency" ? t("nodes.editor.sheets.panel.currency") : t("nodes.editor.sheets.panel.unit")}
            >
              {(id) => (
                <CommitField
                  id={id}
                  value={column.unit ?? ""}
                  maxLength={MAX_UNIT_CHARS}
                  placeholder={view.kind === "currency" ? "EUR" : ""}
                  onCommit={(text) => onPatch({ unit: text.trim() }, step("number_format"))}
                />
              )}
            </InspectorField>
            <NumberField
              label={t("nodes.editor.sheets.panel.decimals")}
              showLabel
              value={column.decimals ?? null}
              allowEmpty
              min={0}
              max={MAX_DECIMALS}
              onChange={(value) => onPatch({ decimals: value === null ? undefined : value }, step("number_format"))}
            />
          </div>
        )}
        <Select
          label={t("nodes.editor.sheets.panel.total")}
          showLabel
          value={column.total ?? ""}
          options={totalOptions}
          onChange={(value) => onPatch({ total: (value || undefined) as TotalKind | undefined }, step("total"))}
          testId="sheet-column-total"
        />
        <InspectorField label={t("nodes.editor.sheets.panel.formula")} hint={formulaError || t("nodes.editor.sheets.formula.hint")}>
          {(id) => (
            <>
              <CommitField
                id={id}
                value={column.formula ?? ""}
                maxLength={MAX_FORMULA_CHARS}
                placeholder="qty * price"
                invalid={Boolean(formulaError)}
                onDraft={setFormulaDraft}
                mono
                onCommit={(text) => {
                  if (formulaError) return;
                  onPatch({ formula: normalFormula(text) || undefined }, step("formula"));
                }}
                testId="sheet-column-formula"
              />
              {otherKeys.length > 0 && (
                <div className="flex flex-wrap gap-1" aria-label={t("nodes.editor.sheets.formula.keys")}>
                  {otherKeys.map((key) => (
                    <code key={key} className="rounded bg-secondary px-1.5 py-0.5 font-mono text-xs text-muted-foreground">
                      {key}
                    </code>
                  ))}
                </div>
              )}
            </>
          )}
        </InspectorField>
      </Section>
      <Section title={t("nodes.editor.sheets.panel.look")}>
        <NumberField
          label={t("nodes.editor.sheets.panel.width")}
          showLabel
          value={column.width ?? null}
          allowEmpty
          min={MIN_WIDTH}
          max={MAX_WIDTH}
          step={8}
          suffix="px"
          onChange={(value) => onPatch({ width: value === null ? undefined : value }, step("resize_column"))}
        />
        <div role="group" aria-label={t("nodes.editor.sheets.panel.align")} className="flex items-center gap-1">
          {(
            [
              ["left", AlignLeft],
              ["center", AlignCenter],
              ["right", AlignRight],
            ] as const
          ).map(([align, Icon]) => (
            <ToolbarButton
              key={align}
              label={t(`nodes.editor.sheets.align.${align}`)}
              icon={<Icon aria-hidden />}
              active={column.align === align}
              onClick={() => onPatch({ align: column.align === align ? undefined : align }, step("align"))}
            />
          ))}
          <span className="mx-1 h-5 w-px bg-border" />
          <ToolbarButton
            label={t("nodes.editor.sheets.toolbar.bold")}
            icon={<Bold aria-hidden />}
            active={Boolean(column.bold)}
            onClick={() => onPatch({ bold: !column.bold || undefined }, step("bold"))}
          />
        </div>
        <ColorSwatches value={column.color} onChange={(color) => onPatch({ color }, step("color"))} />
      </Section>
      <Section title={t("nodes.editor.sheets.panel.sheet")}>
        <Select
          label={t("nodes.editor.sheets.panel.freeze")}
          showLabel
          value={String(sheet.freeze ?? 1)}
          options={[0, 1, 2, 3].map((n) => ({ value: String(n), label: t(`nodes.editor.sheets.freeze.${n}`) }))}
          onChange={(value) => onFreeze(Number(value))}
        />
        <InspectorField label={t("nodes.editor.sheets.panel.note")}>
          {(id) => <CommitField id={id} value={note} maxLength={MAX_NOTE_CHARS} onCommit={onNote} />}
        </InspectorField>
      </Section>
    </div>
  );
}

/** The column colours: the theme's named tokens (a spec holds the name, never a value). */
export function ColorSwatches({ value, onChange }: { value?: ColumnColor; onChange: (color: ColumnColor | undefined) => void }) {
  const t = useT();
  return (
    <div role="radiogroup" aria-label={t("nodes.editor.sheets.panel.color")} className="flex flex-wrap items-center gap-1.5">
      <button
        type="button"
        role="radio"
        aria-checked={!value}
        aria-label={t("nodes.editor.sheets.color.none")}
        title={t("nodes.editor.sheets.color.none")}
        onClick={() => onChange(undefined)}
        className={cn(
          "flex h-6 w-6 items-center justify-center rounded-full border border-border-strong text-xs text-muted-foreground",
          !value && "ring-2 ring-ring ring-offset-1 ring-offset-background",
        )}
      >
        A
      </button>
      {COLUMN_COLORS.map((color) => (
        <button
          key={color}
          type="button"
          role="radio"
          aria-checked={value === color}
          aria-label={t(`nodes.editor.sheets.color.${color}`)}
          title={t(`nodes.editor.sheets.color.${color}`)}
          onClick={() => onChange(color)}
          className={cn("h-6 w-6 rounded-full", value === color && "ring-2 ring-ring ring-offset-1 ring-offset-background")}
          style={{ background: COLOR_TOKENS[color] }}
        />
      ))}
    </div>
  );
}
