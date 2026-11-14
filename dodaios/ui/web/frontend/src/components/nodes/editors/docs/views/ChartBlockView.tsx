/**
 * A fenced `chart` block inside the document: the chart drawn as it will be
 * on the page, and the shared chart editor to change it.
 *
 * The block keeps the chart's JSON as written. It is only rewritten when the
 * person changes the chart, so an untouched chart reaches the page exactly as
 * the assistant wrote it. JSON the chart grammar cannot draw (the page shows
 * it as a code block) is offered as text to fix, rather than silently
 * replaced by a different chart.
 */
import { useMemo, useState, type KeyboardEvent } from "react";
import { NodeViewWrapper, type NodeViewProps } from "@tiptap/react";
import { BarChart3, Pencil, Trash2 } from "lucide-react";

import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { ChartEditor } from "../../charts/ChartEditor";
import { ChartPreview } from "../../charts/ChartPreview";
import { validateChart, type ChartJson } from "../../charts/chartModel";
import { ToolbarButton } from "../../controls";
import { shortcutOf } from "../../useNodeSpecEditor";

/** The chart a block's JSON describes, or null when the page could not draw it. */
export function readChart(source: string): ChartJson | null {
  try {
    return validateChart(JSON.parse(source) as unknown).chart;
  } catch {
    // Not JSON: the page shows such a block as code, and so does this view.
    return null;
  }
}

/** A chart as the block's JSON: one line, as the assistant writes it. */
export function chartSource(chart: ChartJson): string {
  return JSON.stringify(chart);
}

export function ChartBlockView({ node, updateAttributes, deleteNode, selected, editor }: NodeViewProps) {
  const t = useT();
  const source = String(node.attrs.source ?? "");
  const chart = useMemo(() => readChart(source), [source]);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<string | null>(null);
  const title = chart?.title || t("nodes.editor.docs.chart.untitled");

  // In the JSON field, the document's undo applies, not the field's own.
  const historyKeys = (event: KeyboardEvent) => {
    const wanted = shortcutOf(event);
    if (!wanted) return;
    event.preventDefault();
    if (wanted === "undo") editor.commands.undo();
    else editor.commands.redo();
  };

  return (
    <NodeViewWrapper
      as="figure"
      className={cn("doc-chart not-prose", selected && "is-selected")}
      data-testid="docs-chart-block"
      aria-label={t("nodes.editor.docs.chart.label").replace("{0}", title)}
      onDoubleClick={() => chart && setEditing(true)}
    >
      <div className="doc-block-bar" contentEditable={false}>
        <BarChart3 className="h-4 w-4 text-muted-foreground" aria-hidden />
        <span className="min-w-0 flex-1 truncate text-sm text-muted-foreground">{title}</span>
        {chart && (
          <ToolbarButton
            label={t("nodes.editor.chart.edit")}
            icon={<Pencil aria-hidden />}
            onClick={() => setEditing(true)}
            data-testid="docs-chart-edit"
          />
        )}
        <ToolbarButton
          label={t("nodes.editor.docs.chart.remove")}
          icon={<Trash2 aria-hidden />}
          onClick={() => deleteNode()}
        />
      </div>
      <div contentEditable={false}>
        {chart ? (
          <ChartPreview chart={chart} height={260} />
        ) : (
          <div className="space-y-2 p-3">
            <p className="text-sm text-warning" role="status">
              {t("nodes.editor.docs.chart.invalid")}
            </p>
            <textarea
              aria-label={t("nodes.editor.docs.chart.source")}
              className="block min-h-[96px] w-full resize-y rounded-md border border-border-strong bg-input p-2 font-mono text-xs text-foreground focus-visible:border-accent focus-visible:outline-none"
              spellCheck={false}
              value={draft ?? source}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={historyKeys}
              onBlur={() => {
                if (draft !== null && draft !== source) updateAttributes({ source: draft });
                setDraft(null);
              }}
              data-testid="docs-chart-source"
            />
          </div>
        )}
      </div>
      {editing && chart && (
        <ChartEditor
          open
          value={chart}
          onCancel={() => {
            setEditing(false);
            editor.commands.focus();
          }}
          onSave={(next) => {
            setEditing(false);
            updateAttributes({ source: chartSource(next) });
            editor.commands.focus();
          }}
        />
      )}
    </NodeViewWrapper>
  );
}
