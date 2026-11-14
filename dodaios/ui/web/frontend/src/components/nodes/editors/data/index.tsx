/**
 * The Analytics (``data``) editor: the dashboard laid out as the page lays
 * it out, every piece editable where it stands.
 *
 * Head: the summary and the named sources (as chips, the way the page shows
 * them under the title). A kept-current dashboard's status line (when it was
 * refreshed, how often, pause) is the stage's upkeep bar right above the
 * editor (`NodeEditorHost`), so it is not drawn a second time here; the
 * inspector says what a refresh does to values typed by hand. Then the sections, each with its title and text,
 * its row of metric tiles, its charts (two per row, wide ones across) and
 * its tables. Each piece can be selected (its inspector holds what has no
 * place on the page), moved earlier or later (buttons, the arrow keys on its
 * handle, or a drag), duplicated and deleted; charts are made and changed
 * in the shared chart editor. "Page" shows the real page the server draws
 * from the unsaved spec.
 *
 * Two rules come from `data.py` and are kept here so a save never fails
 * under the person's hands: the dashboard keeps at least one metric, chart
 * or table (the last one cannot be deleted), and a tile needs a label and a
 * value (an empty one holds the save, with the reason, until it is filled).
 */
import { useCallback, useMemo, useState, type DragEvent, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { BarChart3, Database, Eye, LayoutDashboard, Plus, Rows3, SquarePen, Table2 } from "lucide-react";

import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { ChartEditor } from "../charts/ChartEditor";
import type { ChartJson } from "../charts/chartModel";
import { starterChart } from "../charts/chartModel";
import { ToolbarButton, ToolbarGroup, ToolbarSeparator } from "../controls";
import { EditorShell } from "../EditorShell";
import { PreviewFrame, useNodePreview } from "../PreviewFrame";
import type { NodeEditorProps } from "../types";
import { hasOwnUndo, shortcutOf, useNodeSpecEditor } from "../useNodeSpecEditor";
import {
  ChartBody,
  Floating,
  Grip,
  InlineText,
  ItemActions,
  MetricFields,
  Piece,
  TableGrid,
  type Act,
} from "./DashboardParts";
import { DataInspector } from "./DataInspector";
import {
  LIMITS,
  PARTS,
  addItem,
  addSection,
  canAdd,
  chartRowSpans,
  duplicateItem,
  duplicateSection,
  findProblems,
  metricsPerRow,
  moveInList,
  newMetric,
  newTable,
  readDashSpec,
  removeItem,
  removeSection,
  wouldEmpty,
  type DashChart,
  type DashSelection,
  type DashSpec,
  type Part,
} from "./dashboardModel";

const same = (a: DashSelection | null, b: DashSelection | null): boolean =>
  !!a && !!b && a.kind === b.kind && a.section === b.section && (a.kind === "section" || a.index === (b as { index: number }).index);

/** What is being dragged: one piece of one list. */
interface Dragging {
  part: Part | "section";
  section: number;
  index: number;
}

export default function DataEditor({ node, initial, onDone }: NodeEditorProps) {
  const t = useT();
  const nodeId = node.id ?? "";
  const start = useMemo(() => ({ ...initial, spec: readDashSpec(initial.spec) }), [initial]);
  const prepare = useCallback(
    (spec: DashSpec) => (findProblems(spec).length ? { error: t("nodes.editor.data.held") } : spec),
    [t],
  );
  const editor = useNodeSpecEditor<DashSpec>(nodeId, start, { prepare });
  const { spec, apply } = editor;
  const [selection, setSelection] = useState<DashSelection | null>(null);
  const [view, setView] = useState<"edit" | "page">("edit");
  const [chartDialog, setChartDialog] = useState<{ section: number; index: number | null } | null>(null);
  const [dragging, setDragging] = useState<Dragging | null>(null);
  const [dropAt, setDropAt] = useState<string>("");
  const problems = useMemo(() => findProblems(spec), [spec]);

  const act: Act = useCallback((label, change, coalesce) => apply((draft) => void change(draft), { label, coalesce }), [apply]);

  // An undo can take the selected piece away: then nothing is selected.
  const selectionAlive =
    selection === null ||
    (selection.kind === "section"
      ? !!spec.sections[selection.section]
      : !!spec.sections[selection.section]?.[selection.kind][selection.index]);
  const current = selectionAlive ? selection : null;

  /** The section new pieces go into: the selected one, else the last. */
  const target = current ? current.section : spec.sections.length - 1;

  /* ---------------------------------------------------------- actions */

  const addPart = (part: Part, section = target) => {
    if (part === "charts") {
      setChartDialog({ section, index: null });
      return;
    }
    let index = -1;
    act(t(`nodes.editor.data.history.add_${part}`), (draft) => {
      const item =
        part === "metrics"
          ? newMetric(t("nodes.editor.data.metric.new_label"))
          : newTable(t("nodes.editor.data.table.new_title"), [t("nodes.editor.data.table.new_item"), t("nodes.editor.data.table.new_value")]);
      index = addItem(draft, section, part, item);
    });
    if (index >= 0) setSelection({ kind: part, section, index });
  };

  const saveChart = (chart: ChartJson) => {
    const dialog = chartDialog;
    setChartDialog(null);
    if (!dialog) return;
    let index = dialog.index ?? -1;
    act(t(dialog.index === null ? "nodes.editor.data.history.add_charts" : "nodes.editor.data.history.chart"), (draft) => {
      const holder = draft.sections[dialog.section];
      if (!holder) return;
      if (dialog.index === null) {
        index = addItem(draft, dialog.section, "charts", chart as unknown as DashChart);
      } else {
        // The chart editor knows the chart grammar; the width in the row is the dashboard's.
        const wide = holder.charts[dialog.index]?.wide;
        holder.charts[dialog.index] = { ...(chart as unknown as DashChart), ...(wide ? { wide: true } : {}) };
      }
    });
    if (index >= 0) setSelection({ kind: "charts", section: dialog.section, index });
  };

  const moveItem = (part: Part, section: number, index: number, to: number) => {
    let landed = index;
    act(t("nodes.editor.data.history.move"), (draft) => {
      landed = moveInList(draft.sections[section]![part] as unknown[], index, to);
    });
    setSelection({ kind: part, section, index: landed });
  };

  const moveSection = (index: number, to: number) => {
    let landed = index;
    act(t("nodes.editor.data.history.move"), (draft) => {
      landed = moveInList(draft.sections, index, to);
    });
    setSelection({ kind: "section", section: landed });
  };

  const duplicate = (selected: DashSelection) => {
    let index = -1;
    act(t("nodes.editor.data.history.duplicate"), (draft) => {
      index =
        selected.kind === "section"
          ? duplicateSection(draft, selected.section)
          : duplicateItem(draft, selected.section, selected.kind, selected.index);
    });
    if (index < 0) return;
    setSelection(selected.kind === "section" ? { kind: "section", section: index } : { ...selected, index });
  };

  const remove = (selected: DashSelection) => {
    let gone = false;
    act(t("nodes.editor.data.history.delete"), (draft) => {
      gone =
        selected.kind === "section"
          ? removeSection(draft, selected.section)
          : removeItem(draft, selected.section, selected.kind, selected.index);
    });
    if (gone) setSelection(selected.kind === "section" ? null : { kind: "section", section: selected.section });
  };

  const canRemove = (selected: DashSelection): boolean => {
    if (selected.kind !== "section") return !wouldEmpty(spec, 1);
    const section = spec.sections[selected.section];
    if (!section || spec.sections.length === 1) return false;
    return !wouldEmpty(spec, PARTS.reduce((n, part) => n + section[part].length, 0));
  };

  const addSectionAfter = (after: number) => {
    let at = -1;
    act(t("nodes.editor.data.history.add_section"), (draft) => {
      at = addSection(draft, after, t("nodes.editor.data.section.new_title"));
    });
    if (at >= 0) setSelection({ kind: "section", section: at });
  };

  /* ------------------------------------------------------------- keys */

  const onBodyKey = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (!current || event.defaultPrevented || hasOwnUndo(event.target) || shortcutOf(event)) return;
    const mod = event.metaKey || event.ctrlKey;
    let handled = true;
    if (mod && event.key.toLowerCase() === "d") duplicate(current);
    else if ((event.key === "Delete" || event.key === "Backspace") && canRemove(current)) remove(current);
    else if (event.key === "Escape") setSelection(current.kind === "section" ? null : { kind: "section", section: current.section });
    else handled = false;
    if (handled) {
      event.preventDefault();
      event.stopPropagation();
    }
  };

  /* ------------------------------------------------------------- drag */

  const dragStart = (drag: Dragging) => (event: DragEvent<HTMLElement>) => {
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", `${drag.part}:${drag.section}:${drag.index}`);
    setDragging(drag);
  };
  const dragOver = (part: Part | "section", section: number, index: number) => (event: DragEvent<HTMLElement>) => {
    if (!dragging || dragging.part !== part || (part !== "section" && dragging.section !== section)) return;
    event.preventDefault();
    setDropAt(`${part}:${section}:${index}`);
  };
  const drop = (part: Part | "section", section: number, index: number) => (event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    const from = dragging;
    setDragging(null);
    setDropAt("");
    if (!from || from.part !== part || from.index === index) return;
    if (part === "section") moveSection(from.index, index);
    else if (from.section === section) moveItem(part, section, from.index, index);
  };
  const isDropTarget = (part: Part | "section", section: number, index: number) =>
    dragging !== null && dropAt === `${part}:${section}:${index}` && !(dragging.section === section && dragging.index === index && dragging.part === part);

  /* ---------------------------------------------------------- preview */

  const preview = useNodePreview(nodeId, spec, { enabled: view === "page", delayMs: 300 });

  /* ---------------------------------------------------------- toolbar */

  const toolbar = (
    <>
      <ToolbarGroup label={t("nodes.editor.data.add_group")}>
        <ToolbarButton
          label={t("nodes.editor.data.add.metrics")}
          icon={<SquarePen aria-hidden />}
          showLabel
          disabled={view !== "edit" || !canAdd(spec, target, "metrics")}
          onClick={() => addPart("metrics")}
          data-testid="data-add-metric"
        />
        <ToolbarButton
          label={t("nodes.editor.data.add.charts")}
          icon={<BarChart3 aria-hidden />}
          showLabel
          disabled={view !== "edit" || !canAdd(spec, target, "charts")}
          onClick={() => addPart("charts")}
          data-testid="data-add-chart"
        />
        <ToolbarButton
          label={t("nodes.editor.data.add.tables")}
          icon={<Table2 aria-hidden />}
          showLabel
          disabled={view !== "edit" || !canAdd(spec, target, "tables")}
          onClick={() => addPart("tables")}
          data-testid="data-add-table"
        />
        <ToolbarButton
          label={t("nodes.editor.data.add.section")}
          icon={<Rows3 aria-hidden />}
          showLabel
          disabled={view !== "edit" || spec.sections.length >= LIMITS.sections}
          onClick={() => addSectionAfter(target)}
          data-testid="data-add-section"
        />
      </ToolbarGroup>
      <ToolbarSeparator />
      <ToolbarGroup label={t("nodes.editor.data.view.label")}>
        <ToolbarButton
          label={t("nodes.editor.data.view.edit")}
          icon={<LayoutDashboard aria-hidden />}
          active={view === "edit"}
          onClick={() => setView("edit")}
        />
        <ToolbarButton
          label={t("nodes.editor.data.view.page")}
          icon={<Eye aria-hidden />}
          active={view === "page"}
          onClick={() => setView("page")}
          data-testid="data-view-page"
        />
      </ToolbarGroup>
    </>
  );

  /* ------------------------------------------------------------- head */

  const sources = spec.sources ?? [];
  const head = (
    <header className="flex flex-col gap-3">
      <h1 className="px-1.5 text-3xl font-semibold tracking-tight">{node.title}</h1>
      <InlineText
        value={spec.summary}
        onChange={(value) => act(t("nodes.editor.data.history.summary"), (draft) => void (draft.summary = value), "summary")}
        label={t("nodes.editor.data.summary")}
        placeholder={t("nodes.editor.data.summary_placeholder")}
        maxLength={LIMITS.summary}
        multiline
        className="max-w-[700px] text-base text-muted-foreground"
        testId="data-summary"
      />
      <ul aria-label={t("nodes.editor.data.sources.label")} className="flex flex-wrap items-center gap-1.5 px-1.5 text-sm text-muted-foreground">
        <li aria-hidden className="flex text-muted-foreground/80">
          <Database className="h-3.5 w-3.5" />
        </li>
        {sources.map((name, index) => (
          <li key={`${index}:${name}`}>
            <span className="inline-flex items-center rounded-full border border-border px-2.5 py-0.5">{name}</span>
          </li>
        ))}
        <li>
          <button
            type="button"
            onClick={() => {
              // The sources are edited in the dashboard's inspector: open it there.
              setSelection(null);
              window.requestAnimationFrame(() => document.querySelector<HTMLElement>('[data-testid="data-source-input"]')?.focus());
            }}
            className="inline-flex items-center gap-1 rounded-full border border-dashed border-border px-2.5 py-0.5 hover:border-border-strong hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {sources.length ? t("nodes.editor.data.sources.edit") : t("nodes.editor.data.sources.none")}
          </button>
        </li>
      </ul>
    </header>
  );

  /* --------------------------------------------------------- sections */

  const problemAt = (section: number, part: Part, index: number, field: string) =>
    problems.some((p) => p.section === section && p.part === part && p.index === index && p.field === field);

  const sections = spec.sections.map((section, s) => {
    const sectionSelected = same(current, { kind: "section", section: s });
    const name = section.title.trim() || t("nodes.editor.data.section.numbered").replace("{0}", String(s + 1));
    const perRow = metricsPerRow(section.metrics.length);
    const spans = chartRowSpans(section.charts);
    const sectionSel: DashSelection = { kind: "section", section: s };
    return (
      <Piece
        key={s}
        label={name}
        selected={sectionSelected}
        onSelect={() => setSelection((now) => (now && now.section === s && now.kind !== "section" ? now : sectionSel))}
        className="p-3"
        testId="data-section"
        dropTarget={isDropTarget("section", s, s)}
        onDragOver={dragOver("section", s, s)}
        onDrop={drop("section", s, s)}
      >
        <Floating selected={sectionSelected}>
          <ItemActions
            vertical
            name={name}
            canEarlier={s > 0}
            canLater={s < spec.sections.length - 1}
            canDuplicate={spec.sections.length < LIMITS.sections}
            canRemove={canRemove(sectionSel)}
            onMove={(step) => moveSection(s, s + step)}
            onDuplicate={() => duplicate(sectionSel)}
            onRemove={() => remove(sectionSel)}
          />
        </Floating>
        <div className="flex items-start gap-1">
          <Grip vertical name={name} onMove={(step) => moveSection(s, s + step)} onDragStart={dragStart({ part: "section", section: s, index: s })} />
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <InlineText
              value={section.title}
              onChange={(value) => act(t("nodes.editor.data.history.section"), (draft) => void (draft.sections[s]!.title = value), `s${s}.title`)}
              label={t("nodes.editor.data.section.title")}
              placeholder={t("nodes.editor.data.section.title_placeholder")}
              maxLength={LIMITS.title}
              className="text-xl font-semibold"
              testId="data-section-title"
            />
            <InlineText
              value={section.text}
              onChange={(value) => act(t("nodes.editor.data.history.section"), (draft) => void (draft.sections[s]!.text = value), `s${s}.text`)}
              label={t("nodes.editor.data.section.text")}
              placeholder={t("nodes.editor.data.section.text_placeholder")}
              maxLength={LIMITS.text}
              multiline
              className="max-w-[700px] text-sm text-muted-foreground"
            />
          </div>
        </div>

        {section.metrics.length > 0 && (
          <div className="mt-4 grid gap-3" style={{ gridTemplateColumns: `repeat(${perRow}, minmax(0, 1fr))` }} data-testid="data-metrics">
            {section.metrics.map((metric, i) => {
              const sel: DashSelection = { kind: "metrics", section: s, index: i };
              const selected = same(current, sel);
              const label = metric.label || t("nodes.editor.data.metric.untitled");
              return (
                <Piece
                  key={i}
                  label={label}
                  selected={selected}
                  onSelect={() => setSelection(sel)}
                  className="border border-border bg-card"
                  testId="data-metric"
                  dropTarget={isDropTarget("metrics", s, i)}
                  onDragOver={dragOver("metrics", s, i)}
                  onDrop={drop("metrics", s, i)}
                >
                  <Floating selected={selected}>
                    <ItemActions
                      name={label}
                      canEarlier={i > 0}
                      canLater={i < section.metrics.length - 1}
                      canDuplicate={section.metrics.length < LIMITS.metrics}
                      canRemove={canRemove(sel)}
                      onMove={(step) => moveItem("metrics", s, i, i + step)}
                      onDuplicate={() => duplicate(sel)}
                      onRemove={() => remove(sel)}
                    />
                  </Floating>
                  <div className="absolute left-1 top-2">
                    <Grip name={label} onMove={(step) => moveItem("metrics", s, i, i + step)} onDragStart={dragStart({ part: "metrics", section: s, index: i })} />
                  </div>
                  <div className="pl-4">
                    <MetricFields
                      metric={metric}
                      where={`s${s}.m${i}`}
                      act={act}
                      set={(change) => (draft) => change(draft.sections[s]!.metrics[i]!)}
                      invalidLabel={problemAt(s, "metrics", i, "label")}
                      invalidValue={problemAt(s, "metrics", i, "value")}
                    />
                  </div>
                </Piece>
              );
            })}
          </div>
        )}

        {section.charts.length > 0 && (
          <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2" data-testid="data-charts">
            {section.charts.map((chart, i) => {
              const sel: DashSelection = { kind: "charts", section: s, index: i };
              const selected = same(current, sel);
              const label = chart.title || t("nodes.editor.data.chart.untitled");
              return (
                <Piece
                  key={i}
                  label={label}
                  selected={selected}
                  onSelect={() => setSelection(sel)}
                  className={cn(spans[i] && "xl:col-span-2")}
                  testId="data-chart"
                  dropTarget={isDropTarget("charts", s, i)}
                  onDragOver={dragOver("charts", s, i)}
                  onDrop={drop("charts", s, i)}
                >
                  <Floating selected={selected}>
                    <ItemActions
                      name={label}
                      canEarlier={i > 0}
                      canLater={i < section.charts.length - 1}
                      canDuplicate={section.charts.length < LIMITS.charts}
                      canRemove={canRemove(sel)}
                      onMove={(step) => moveItem("charts", s, i, i + step)}
                      onDuplicate={() => duplicate(sel)}
                      onRemove={() => remove(sel)}
                    >
                      <Grip name={label} onMove={(step) => moveItem("charts", s, i, i + step)} onDragStart={dragStart({ part: "charts", section: s, index: i })} />
                    </ItemActions>
                  </Floating>
                  <ChartBody
                    chart={chart}
                    wide={spans[i] === true}
                    onEdit={() => setChartDialog({ section: s, index: i })}
                    onToggleWide={() =>
                      act(t("nodes.editor.data.chart.wide"), (draft) => {
                        const target = draft.sections[s]!.charts[i]!;
                        if (target.wide) delete target.wide;
                        else target.wide = true;
                      })
                    }
                  />
                </Piece>
              );
            })}
          </div>
        )}

        {section.tables.map((table, i) => {
          const sel: DashSelection = { kind: "tables", section: s, index: i };
          const selected = same(current, sel);
          const label = table.title || t("nodes.editor.data.table.untitled");
          return (
            <Piece
              key={i}
              label={label}
              selected={selected}
              onSelect={() => setSelection(sel)}
              className="mt-4 p-1"
              testId="data-table"
              dropTarget={isDropTarget("tables", s, i)}
              onDragOver={dragOver("tables", s, i)}
              onDrop={drop("tables", s, i)}
            >
              <Floating selected={selected}>
                <ItemActions
                  vertical
                  name={label}
                  canEarlier={i > 0}
                  canLater={i < section.tables.length - 1}
                  canDuplicate={section.tables.length < LIMITS.tables}
                  canRemove={canRemove(sel)}
                  onMove={(step) => moveItem("tables", s, i, i + step)}
                  onDuplicate={() => duplicate(sel)}
                  onRemove={() => remove(sel)}
                />
              </Floating>
              <div className="mb-2 flex items-center gap-1">
                <Grip vertical name={label} onMove={(step) => moveItem("tables", s, i, i + step)} onDragStart={dragStart({ part: "tables", section: s, index: i })} />
                <InlineText
                  value={table.title}
                  onChange={(value) => act(t("nodes.editor.data.history.table"), (draft) => void (draft.sections[s]!.tables[i]!.title = value), `s${s}.t${i}.title`)}
                  label={t("nodes.editor.data.table.title")}
                  placeholder={t("nodes.editor.data.table.title_placeholder")}
                  maxLength={LIMITS.title}
                  className="text-base font-medium"
                />
              </div>
              <TableGrid
                table={table}
                where={`s${s}.t${i}`}
                act={act}
                setTable={(change) => (draft) => change(draft.sections[s]!.tables[i]!)}
                invalidColumns={problemAt(s, "tables", i, "columns")}
              />
            </Piece>
          );
        })}

        <div className="mt-3 flex flex-wrap gap-1 opacity-70 focus-within:opacity-100 hover:opacity-100">
          {PARTS.map((part) => (
            <ToolbarButton
              key={part}
              showLabel
              label={t(`nodes.editor.data.add.${part}`)}
              icon={<Plus aria-hidden />}
              disabled={!canAdd(spec, s, part)}
              onClick={() => addPart(part, s)}
              className="text-muted-foreground"
            />
          ))}
        </div>
      </Piece>
    );
  });

  const editing = chartDialog?.index !== null && chartDialog ? spec.sections[chartDialog.section]?.charts[chartDialog.index] : undefined;

  return (
    <EditorShell
      editor={editor}
      title={node.title}
      onDone={onDone}
      toolbar={toolbar}
      side={
        view === "edit" ? (
          <DataInspector
            spec={spec}
            selection={current}
            act={act}
            onSelect={setSelection}
            onEditChart={(section, index) => setChartDialog({ section, index })}
            node={node}
          />
        ) : undefined
      }
      bodyClassName={view === "page" ? "overflow-hidden" : undefined}
    >
      {view === "page" ? (
        <div className="relative h-full">
          <PreviewFrame html={preview.html} title={t("nodes.editor.data.view.page_title").replace("{0}", node.title)} className="h-full w-full border-0" />
          {preview.error && (
            <p role="status" className="absolute inset-x-0 bottom-3 mx-auto w-fit max-w-xl rounded-md bg-destructive/90 px-3 py-1.5 text-sm text-destructive-foreground shadow">
              {preview.error}
            </p>
          )}
        </div>
      ) : (
        <div
          className="mx-auto flex max-w-[1216px] flex-col gap-6 px-6 py-8"
          onKeyDown={onBodyKey}
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setSelection(null);
          }}
          data-testid="data-canvas"
        >
          {head}
          {sections}
          <button
            type="button"
            disabled={spec.sections.length >= LIMITS.sections}
            onClick={() => addSectionAfter(spec.sections.length - 1)}
            className="flex h-10 items-center justify-center gap-2 rounded-lg border border-dashed border-border text-sm text-muted-foreground hover:border-border-strong hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-40"
          >
            <Plus aria-hidden className="h-4 w-4" />
            {t("nodes.editor.data.add.section")}
          </button>
        </div>
      )}
      <ChartEditor
        open={chartDialog !== null}
        value={editing ? (editing as unknown as ChartJson) : chartDialog?.index === null ? newChart(t) : null}
        onSave={(chart) => saveChart(chart)}
        onCancel={() => setChartDialog(null)}
      />
    </EditorShell>
  );
}

/** The chart a new dashboard figure starts from: a few columns to replace. */
function newChart(t: (key: string) => string): ChartJson {
  return { ...starterChart("column"), title: t("nodes.editor.data.chart.new_title") };
}
