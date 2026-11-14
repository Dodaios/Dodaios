/**
 * The inspector: every field of the selected slide's layout, in the order
 * the slide shows them, plus its layout, its picture or its chart.
 *
 * The canvas is where most writing happens; the inspector is where the rest
 * is: fields the slide does not show yet (a kicker, a caption), the lists
 * (add, remove and reorder points, figures, steps, columns, table rows and
 * columns), the picture and how it fills its box, and the chart. Text typed
 * here and on the canvas is the same edit: one undo step per typing run in
 * a field. `data-spec-undo` hands Cmd/Ctrl+Z in these fields to the deck's
 * history, so undo never splits between the browser's field undo and the
 * editor's.
 */
import { useRef, useState, type ChangeEvent, type DragEvent, type ReactNode } from "react";
import { ArrowDown, ArrowUp, BarChart3, ImagePlus, Plus, X } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";

import { ToolbarButton, InspectorField, Popover } from "../controls";
import { validateChart } from "../charts/chartModel";
import {
  LAYOUT_FIELDS,
  LIMITS,
  LINE_LIMITS,
  type Column,
  type Layout,
  type Slide,
  type Stat,
  type Step,
} from "./deckModel";
import { LayoutGlyph, LayoutPicker } from "./LayoutPicker";
import type { FieldPath } from "./SlideView";

export interface SlideInspectorProps {
  slide: Slide;
  index: number;
  /** Text typed into the field at `path` (one undo step per typing run). */
  onText: (path: FieldPath, value: string) => void;
  /** A structural change of the slide, one labelled undo step. */
  onChange: (label: string, change: (slide: Slide) => void) => void;
  onLayout: (layout: Layout) => void;
  onEditChart: () => void;
  onPickImage: () => void;
  onDropImage: (file: File) => void;
  /** A message about the picture (too large, wrong type), or "". */
  imageError: string;
  /** The field the person is in on the canvas, to show its row here. */
  activeField: string | null;
}

function Section({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return (
    <section className="flex flex-col gap-2 border-t border-border pt-3 first:border-t-0 first:pt-0">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{title}</h3>
        {action}
      </div>
      {children}
    </section>
  );
}

/** A text field with the server's limit; the count shows once the text nears it. */
function TextField({
  id,
  value,
  limit,
  multiline,
  placeholder,
  onValue,
  active,
  ariaLabel,
  testId,
}: {
  id?: string;
  value: string;
  limit: number;
  multiline?: boolean;
  placeholder?: string;
  onValue: (value: string) => void;
  active?: boolean;
  ariaLabel?: string;
  testId?: string;
}) {
  const near = value.length >= limit * 0.8;
  const common = {
    id,
    value,
    maxLength: limit,
    placeholder,
    "aria-label": ariaLabel,
    "data-testid": testId,
    className: cn("text-sm", active && "border-accent"),
  };
  return (
    <div className="relative">
      {multiline ? (
        <Textarea
          {...common}
          rows={2}
          className={cn(common.className, "min-h-[56px] resize-y py-1.5")}
          onChange={(event: ChangeEvent<HTMLTextAreaElement>) => onValue(event.target.value.replace(/[\r\n]+/g, " "))}
        />
      ) : (
        <Input {...common} className={cn(common.className, "h-8 px-2")} onChange={(event) => onValue(event.target.value)} />
      )}
      {near && (
        <span aria-hidden className="pointer-events-none absolute bottom-1 right-2 text-[10px] tabular-nums text-muted-foreground">
          {value.length}/{limit}
        </span>
      )}
    </div>
  );
}

/** The buttons of one row of a list: up, down, remove. */
function RowTools({
  index,
  count,
  min,
  name: kind,
  onMove,
  onRemove,
}: {
  index: number;
  count: number;
  min: number;
  name: string;
  onMove: (to: number) => void;
  onRemove: () => void;
}) {
  const t = useT();
  // "Point 2", so each row's buttons have a name of their own.
  const name = fill(t("nodes.editor.slides.item.numbered"), { item: kind, n: index + 1 });
  return (
    <div className="flex shrink-0 items-center">
      <ToolbarButton
        label={fill(t("nodes.editor.slides.list.up"), { item: name })}
        icon={<ArrowUp aria-hidden />}
        disabled={index === 0}
        onClick={() => onMove(index - 1)}
        className="h-7 w-7"
      />
      <ToolbarButton
        label={fill(t("nodes.editor.slides.list.down"), { item: name })}
        icon={<ArrowDown aria-hidden />}
        disabled={index === count - 1}
        onClick={() => onMove(index + 1)}
        className="h-7 w-7"
      />
      <ToolbarButton
        label={fill(t("nodes.editor.slides.list.remove"), { item: name })}
        icon={<X aria-hidden />}
        disabled={count <= min}
        onClick={onRemove}
        className="h-7 w-7"
      />
    </div>
  );
}

function AddButton({ label, disabled, onClick, testId }: { label: string; disabled?: boolean; onClick: () => void; testId?: string }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      data-testid={testId}
      className="flex h-7 items-center gap-1 self-start rounded-md px-2 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-40"
    >
      <Plus className="h-3.5 w-3.5" aria-hidden />
      {label}
    </button>
  );
}

function moveItem<T>(list: T[], from: number, to: number): void {
  if (to < 0 || to >= list.length) return;
  const [item] = list.splice(from, 1);
  list.splice(to, 0, item);
}

export function SlideInspector({
  slide,
  index,
  onText,
  onChange,
  onLayout,
  onEditChart,
  onPickImage,
  onDropImage,
  imageError,
  activeField,
}: SlideInspectorProps) {
  const t = useT();
  const L = (key: string) => t(`nodes.editor.slides.${key}`);
  const fields = LAYOUT_FIELDS[slide.layout];
  const [dragOver, setDragOver] = useState(false);
  const fileDrop = useRef(0);

  const lineField = (key: keyof typeof LINE_LIMITS, multiline = false) =>
    fields.includes(key) && (
      <InspectorField key={key} label={L(`field.${key}`)}>
        {(id) => (
          <TextField
            id={id}
            value={(slide[key] as string | undefined) ?? ""}
            limit={LINE_LIMITS[key]}
            multiline={multiline}
            onValue={(value) => onText([key], value)}
            active={activeField === key}
            testId={`slides-field-${key}`}
          />
        )}
      </InspectorField>
    );

  // --- points (bullets, a closing slide's points) ------------------------------------
  const bulletMax = slide.layout === "closing" ? LIMITS.closingBullets : LIMITS.bullets;
  const bulletChars = slide.layout === "closing" ? LIMITS.closingBulletChars : LIMITS.bulletChars;
  const bullets = slide.bullets ?? [];
  const pointName = L("item.point");

  const bulletsSection = fields.includes("bullets") && (
    <Section title={L("section.points")}>
      <ol className="flex flex-col gap-1.5" aria-label={L("section.points")}>
        {bullets.map((bullet, i) => (
          <li key={i} className="flex items-center gap-1">
            <TextField
              value={bullet}
              limit={bulletChars}
              ariaLabel={fill(L("item.numbered"), { item: pointName, n: i + 1 })}
              onValue={(value) => onText(["bullets", i], value)}
              active={activeField === `bullets/${i}`}
              testId={`slides-bullet-${i}`}
            />
            <RowTools
              index={i}
              count={bullets.length}
              min={0}
              name={pointName}
              onMove={(to) => onChange(L("step.move_point"), (s) => moveItem(s.bullets!, i, to))}
              onRemove={() =>
                onChange(L("step.remove_point"), (s) => {
                  s.bullets!.splice(i, 1);
                  if (!s.bullets!.length) delete s.bullets;
                })
              }
            />
          </li>
        ))}
      </ol>
      <AddButton
        label={L("list.add_point")}
        disabled={bullets.length >= bulletMax}
        testId="slides-add-bullet"
        onClick={() =>
          onChange(L("step.add_point"), (s) => {
            s.bullets = [...(s.bullets ?? []), fill(t("nodes.editor.slides.sample.point"), { n: bullets.length + 1 })];
          })
        }
      />
    </Section>
  );

  // --- columns ---------------------------------------------------------------------
  const columns = slide.columns ?? [];
  const columnName = L("item.column");
  const columnsSection = fields.includes("columns") && (
    <Section title={L("section.columns")}>
      {columns.map((column: Column, c) => (
        <div key={c} className="flex flex-col gap-1.5 rounded-md border border-border p-2">
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">{fill(L("item.numbered"), { item: columnName, n: c + 1 })}</span>
            <RowTools
              index={c}
              count={columns.length}
              min={LIMITS.columnsMin}
              name={columnName}
              onMove={(to) => onChange(L("step.move_column"), (s) => moveItem(s.columns!, c, to))}
              onRemove={() => onChange(L("step.remove_column"), (s) => void s.columns!.splice(c, 1))}
            />
          </div>
          <TextField
            value={column.title ?? ""}
            limit={LIMITS.columnTitleChars}
            placeholder={L("field.title")}
            ariaLabel={`${fill(L("item.numbered"), { item: columnName, n: c + 1 })}: ${L("field.title")}`}
            onValue={(value) => onText(["columns", c, "title"], value)}
          />
          <TextField
            value={column.text ?? ""}
            limit={LIMITS.columnTextChars}
            multiline
            placeholder={L("field.text")}
            ariaLabel={`${fill(L("item.numbered"), { item: columnName, n: c + 1 })}: ${L("field.text")}`}
            onValue={(value) => onText(["columns", c, "text"], value)}
          />
          {(column.bullets ?? []).map((bullet, b) => (
            <div key={b} className="flex items-center gap-1">
              <TextField
                value={bullet}
                limit={LIMITS.columnBulletChars}
                ariaLabel={fill(L("item.numbered"), { item: pointName, n: b + 1 })}
                onValue={(value) => onText(["columns", c, "bullets", b], value)}
              />
              <RowTools
                index={b}
                count={column.bullets!.length}
                min={0}
                name={pointName}
                onMove={(to) => onChange(L("step.move_point"), (s) => moveItem(s.columns![c].bullets!, b, to))}
                onRemove={() =>
                  onChange(L("step.remove_point"), (s) => {
                    const col = s.columns![c];
                    col.bullets!.splice(b, 1);
                    if (!col.bullets!.length) delete col.bullets;
                  })
                }
              />
            </div>
          ))}
          <AddButton
            label={L("list.add_point")}
            disabled={(column.bullets?.length ?? 0) >= LIMITS.columnBullets}
            onClick={() =>
              onChange(L("step.add_point"), (s) => {
                const col = s.columns![c];
                col.bullets = [...(col.bullets ?? []), fill(t("nodes.editor.slides.sample.point"), { n: (col.bullets?.length ?? 0) + 1 })];
              })
            }
          />
        </div>
      ))}
      <AddButton
        label={L("list.add_column")}
        disabled={columns.length >= LIMITS.columns}
        testId="slides-add-column"
        onClick={() =>
          onChange(L("step.add_column"), (s) => {
            s.columns = [
              ...(s.columns ?? []),
              {
                title: fill(t("nodes.editor.slides.sample.column"), { n: columns.length + 1 }),
                text: t("nodes.editor.slides.sample.column_text"),
              },
            ];
          })
        }
      />
    </Section>
  );

  // --- figures (stats) ------------------------------------------------------------------
  const stats = slide.stats ?? [];
  const statName = L("item.stat");
  const statsSection = fields.includes("stats") && (
    <Section title={L("section.stats")}>
      {stats.map((stat: Stat, i) => (
        <div key={i} className="flex flex-col gap-1.5 rounded-md border border-border p-2">
          <div className="flex items-center gap-1">
            <TextField
              value={stat.value}
              limit={LIMITS.statValueChars}
              placeholder={L("field.value")}
              ariaLabel={`${fill(L("item.numbered"), { item: statName, n: i + 1 })}: ${L("field.value")}`}
              onValue={(value) => onText(["stats", i, "value"], value)}
              active={activeField === `stats/${i}/value`}
              testId={`slides-stat-value-${i}`}
            />
            <RowTools
              index={i}
              count={stats.length}
              min={1}
              name={statName}
              onMove={(to) => onChange(L("step.move_stat"), (s) => moveItem(s.stats!, i, to))}
              onRemove={() => onChange(L("step.remove_stat"), (s) => void s.stats!.splice(i, 1))}
            />
          </div>
          <TextField
            value={stat.label ?? ""}
            limit={LIMITS.statLabelChars}
            placeholder={L("field.label")}
            ariaLabel={`${fill(L("item.numbered"), { item: statName, n: i + 1 })}: ${L("field.label")}`}
            onValue={(value) => onText(["stats", i, "label"], value)}
          />
          <TextField
            value={stat.detail ?? ""}
            limit={LIMITS.statDetailChars}
            placeholder={L("field.detail")}
            ariaLabel={`${fill(L("item.numbered"), { item: statName, n: i + 1 })}: ${L("field.detail")}`}
            onValue={(value) => onText(["stats", i, "detail"], value)}
          />
        </div>
      ))}
      {stats.some((stat) => !stat.value.trim()) && <p className="text-xs text-warning">{L("hint.stat_value")}</p>}
      <AddButton
        label={L("list.add_stat")}
        disabled={stats.length >= LIMITS.stats}
        testId="slides-add-stat"
        onClick={() =>
          onChange(L("step.add_stat"), (s) => {
            s.stats = [...(s.stats ?? []), { value: "0", label: fill(t("nodes.editor.slides.sample.stat_label"), { n: stats.length + 1 }) }];
          })
        }
      />
    </Section>
  );

  // --- steps -------------------------------------------------------------------------------
  const steps = slide.steps ?? [];
  const stepName = L("item.step");
  const stepsSection = fields.includes("steps") && (
    <Section title={L("section.steps")}>
      {steps.map((step: Step, i) => (
        <div key={i} className="flex flex-col gap-1.5 rounded-md border border-border p-2">
          <div className="flex items-center gap-1">
            <TextField
              value={step.title ?? ""}
              limit={LIMITS.stepTitleChars}
              placeholder={L("field.title")}
              ariaLabel={`${fill(L("item.numbered"), { item: stepName, n: i + 1 })}: ${L("field.title")}`}
              onValue={(value) => onText(["steps", i, "title"], value)}
            />
            <RowTools
              index={i}
              count={steps.length}
              min={1}
              name={stepName}
              onMove={(to) => onChange(L("step.move_step"), (s) => moveItem(s.steps!, i, to))}
              onRemove={() => onChange(L("step.remove_step"), (s) => void s.steps!.splice(i, 1))}
            />
          </div>
          <TextField
            value={step.text ?? ""}
            limit={LIMITS.stepTextChars}
            multiline
            placeholder={L("field.text")}
            ariaLabel={`${fill(L("item.numbered"), { item: stepName, n: i + 1 })}: ${L("field.text")}`}
            onValue={(value) => onText(["steps", i, "text"], value)}
          />
        </div>
      ))}
      <AddButton
        label={L("list.add_step")}
        disabled={steps.length >= LIMITS.steps}
        testId="slides-add-step"
        onClick={() =>
          onChange(L("step.add_step"), (s) => {
            s.steps = [...(s.steps ?? []), { title: fill(t("nodes.editor.slides.sample.step"), { n: steps.length + 1 }) }];
          })
        }
      />
    </Section>
  );

  // --- table ----------------------------------------------------------------------------------
  const table = slide.table ?? { columns: [], rows: [] };
  const tableSection = fields.includes("table") && (
    <Section title={L("section.table")}>
      <div className="overflow-x-auto">
        <table className="border-separate border-spacing-1 text-xs" aria-label={L("section.table")}>
          <thead>
            <tr>
              {table.columns.map((name, c) => (
                <th key={c} scope="col" className="min-w-[88px] p-0 align-bottom font-normal">
                  <div className="flex items-center gap-0.5">
                    <Input
                      value={name}
                      maxLength={LIMITS.tableHeadChars}
                      aria-label={fill(L("table.column_name"), { n: c + 1 })}
                      className="h-7 px-1.5 text-xs font-medium"
                      onChange={(event) => onText(["table", "columns", c], event.target.value)}
                    />
                    <ToolbarButton
                      label={fill(L("table.remove_column"), { n: c + 1 })}
                      icon={<X aria-hidden />}
                      disabled={table.columns.length <= 1}
                      className="h-6 w-6"
                      onClick={() =>
                        onChange(L("step.remove_table_column"), (s) => {
                          s.table!.columns.splice(c, 1);
                          s.table!.rows.forEach((row) => row.splice(c, 1));
                        })
                      }
                    />
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row, r) => (
              <tr key={r}>
                {row.map((cell, c) => (
                  <td key={c} className="p-0">
                    <Input
                      value={cell}
                      maxLength={LIMITS.cellChars}
                      aria-label={fill(L("table.cell"), { row: r + 1, column: c + 1 })}
                      className="h-7 px-1.5 text-xs"
                      onChange={(event) => onText(["table", "rows", r, c], event.target.value)}
                      data-testid={`slides-cell-${r}-${c}`}
                    />
                  </td>
                ))}
                <td className="p-0">
                  <ToolbarButton
                    label={fill(L("table.remove_row"), { n: r + 1 })}
                    icon={<X aria-hidden />}
                    disabled={table.rows.length <= 1}
                    className="h-6 w-6"
                    onClick={() => onChange(L("step.remove_table_row"), (s) => void s.table!.rows.splice(r, 1))}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex gap-1">
        <AddButton
          label={L("table.add_row")}
          disabled={table.rows.length >= LIMITS.tableRows}
          testId="slides-add-row"
          onClick={() =>
            onChange(L("step.add_table_row"), (s) => {
              s.table!.rows.push(s.table!.columns.map(() => ""));
            })
          }
        />
        <AddButton
          label={L("table.add_column")}
          disabled={table.columns.length >= LIMITS.tableColumns}
          testId="slides-add-table-column"
          onClick={() =>
            onChange(L("step.add_table_column"), (s) => {
              s.table!.columns.push(fill(t("nodes.editor.slides.sample.table_new_col"), { n: s.table!.columns.length + 1 }));
              s.table!.rows.forEach((row) => row.push(""));
            })
          }
        />
      </div>
      <p className="text-xs text-muted-foreground">{L("hint.table")}</p>
    </Section>
  );

  // --- chart ---------------------------------------------------------------------------------
  const chartCheck = slide.chart ? validateChart(slide.chart) : null;
  const chartSection = fields.includes("chart") && (
    <Section title={L("section.chart")}>
      <div className="flex items-center gap-2 rounded-md border border-border p-2 text-xs text-muted-foreground">
        <BarChart3 className="h-4 w-4 shrink-0" aria-hidden />
        <span className="min-w-0 flex-1 truncate">
          {chartCheck?.chart
            ? fill(L("chart.summary"), {
                kind: t(`nodes.editor.slides.chart.kind.${chartCheck.chart.type}`),
                labels: chartCheck.chart.x.length,
                series: chartCheck.chart.series.length,
              })
            : L("chart.none")}
        </span>
      </div>
      <button
        type="button"
        onClick={onEditChart}
        data-testid="slides-edit-chart"
        className="flex h-8 items-center justify-center gap-1.5 rounded-md border border-border-strong text-sm hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <BarChart3 className="h-4 w-4" aria-hidden />
        {L("chart.edit")}
      </button>
      {chartCheck?.chart?.type === "bar" && chartCheck.chart.x.length > 10 && (
        <p className="text-xs text-warning">{L("hint.bar_rows")}</p>
      )}
    </Section>
  );

  // --- picture -----------------------------------------------------------------------------
  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    fileDrop.current = 0;
    setDragOver(false);
    const file = Array.from(event.dataTransfer.files).find((f) => f.type.startsWith("image/"));
    if (file) onDropImage(file);
  };
  const imageSection = fields.includes("image") && (
    <Section title={L("section.image")}>
      <div
        onDragEnter={(event) => {
          event.preventDefault();
          fileDrop.current += 1;
          setDragOver(true);
        }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={() => {
          fileDrop.current -= 1;
          if (fileDrop.current <= 0) setDragOver(false);
        }}
        onDrop={onDrop}
        className={cn(
          "relative grid aspect-video place-items-center overflow-hidden rounded-md border border-dashed border-border-strong bg-secondary/40",
          dragOver && "border-accent bg-accent/10",
        )}
      >
        {slide.image ? (
          <img src={slide.image} alt="" className={cn("h-full w-full", slide.fit === "contain" ? "object-contain" : "object-cover")} />
        ) : (
          <span className="px-3 text-center text-xs text-muted-foreground">{L("image.drop")}</span>
        )}
      </div>
      <button
        type="button"
        onClick={onPickImage}
        data-testid="slides-pick-image"
        className="flex h-8 items-center justify-center gap-1.5 rounded-md border border-border-strong text-sm hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <ImagePlus className="h-4 w-4" aria-hidden />
        {slide.image ? L("image.replace") : L("image.choose")}
      </button>
      {imageError && (
        <p role="alert" className="text-xs text-destructive">
          {imageError}
        </p>
      )}
      <div role="radiogroup" aria-label={L("image.fit")} className="grid grid-cols-2 gap-1 rounded-md bg-secondary/60 p-0.5">
        {(["cover", "contain"] as const).map((fit) => {
          const on = (slide.fit ?? "cover") === fit;
          return (
            <button
              key={fit}
              type="button"
              role="radio"
              aria-checked={on}
              onClick={() =>
                onChange(L("step.image_fit"), (s) => {
                  if (fit === "contain") s.fit = "contain";
                  else delete s.fit;
                })
              }
              className={cn(
                "h-7 rounded text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                on ? "bg-background font-medium text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {L(`image.fit_${fit}`)}
            </button>
          );
        })}
      </div>
      {!slide.title && <p className="text-xs text-muted-foreground">{L("hint.image_bleed")}</p>}
    </Section>
  );

  return (
    <div className="flex flex-col gap-4" data-spec-undo="" data-testid="slides-inspector">
      <Section title={fill(L("inspector.slide"), { n: index + 1 })}>
        <Popover
          label={L("layout.change")}
          trigger={
            <button
              type="button"
              data-testid="slides-layout-button"
              className="flex h-10 w-full items-center gap-2 rounded-md border border-border-strong px-2 text-sm hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <LayoutGlyph layout={slide.layout} className="h-[22px] w-10 shrink-0 border border-border" />
              <span className="min-w-0 flex-1 truncate text-left">{L(`layout.${slide.layout}`)}</span>
              <span className="text-xs text-muted-foreground">{L("layout.change_short")}</span>
            </button>
          }
        >
          {(close) => (
            <div className="w-72 p-1">
              <LayoutPicker
                current={slide.layout}
                onPick={(layout) => {
                  close();
                  onLayout(layout);
                }}
              />
            </div>
          )}
        </Popover>
      </Section>
      <Section title={L("section.text")}>
        {lineField("kicker")}
        {lineField("title", true)}
        {lineField("subtitle", true)}
        {lineField("quote", true)}
        {lineField("by")}
        {lineField("text", true)}
        {lineField("caption", true)}
      </Section>
      {bulletsSection}
      {columnsSection}
      {statsSection}
      {stepsSection}
      {tableSection}
      {chartSection}
      {imageSection}
    </div>
  );
}
