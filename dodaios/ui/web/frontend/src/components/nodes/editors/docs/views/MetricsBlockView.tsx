/**
 * A fenced `metrics` block: the row of key figures the page draws, edited as
 * up to six figures of value, label and an optional detail line.
 *
 * The block's text (`value | label | detail` per line, `render_metrics` in
 * `report_blocks.py`) is written again only when a figure changes.
 */
import { type KeyboardEvent } from "react";
import { NodeViewWrapper, type NodeViewProps } from "@tiptap/react";
import { Gauge, Plus, Trash2, X } from "lucide-react";

import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { ToolbarButton } from "../../controls";
import { shortcutOf } from "../../useNodeSpecEditor";

/** Mirrors `MAX_METRICS` in `report_blocks.py`. */
export const MAX_METRICS = 6;

export interface Metric {
  value: string;
  label: string;
  detail: string;
}

export function readMetrics(source: string): Metric[] {
  return source
    .split("\n")
    .filter((line) => line.trim())
    .map((line) => {
      const fields = line.trim().replace(/^\||\|$/g, "").split("|").map((field) => field.trim());
      return { value: fields[0] ?? "", label: fields[1] ?? "", detail: fields.slice(2).join(" ").trim() };
    });
}

export function writeMetrics(metrics: Metric[]): string {
  // A "|" inside a field would split it on the page.
  const clean = (text: string) => text.replace(/\|/g, "/").replace(/\s+/g, " ").trim();
  return metrics
    .map((metric) => [metric.value, metric.label, metric.detail].map(clean))
    .map(([value, label, detail]) => (detail ? `${value} | ${label} | ${detail}` : `${value} | ${label}`))
    .join("\n");
}

/** Whether the page draws these as a row of figures (else it shows the text). */
export function metricsDrawable(metrics: Metric[]): boolean {
  return metrics.length >= 1 && metrics.length <= MAX_METRICS && metrics.every((metric) => metric.value && metric.label);
}

export function MetricsBlockView({ node, updateAttributes, deleteNode, selected, editor, getPos }: NodeViewProps) {
  const t = useT();
  const metrics = readMetrics(String(node.attrs.source ?? ""));
  // The view may be drawn a moment after the document changed: each edit
  // starts from the block as the document holds it now, so two quick edits
  // never undo each other.
  const live = (): Metric[] => {
    const pos = getPos();
    const current = typeof pos === "number" ? editor.state.doc.nodeAt(pos) : null;
    return current?.type.name === "metricsBlock" ? readMetrics(String(current.attrs.source ?? "")) : metrics;
  };
  const set = (next: Metric[]) => updateAttributes({ source: writeMetrics(next) });
  const change = (index: number, field: keyof Metric, value: string) =>
    set(live().map((metric, at) => (at === index ? { ...metric, [field]: value } : metric)));
  // The figures' fields use the document's undo, so one Cmd+Z works everywhere.
  const historyKeys = (event: KeyboardEvent) => {
    const wanted = shortcutOf(event);
    if (!wanted) return;
    event.preventDefault();
    if (wanted === "undo") editor.commands.undo();
    else editor.commands.redo();
  };
  const field = "h-8 w-full rounded-md border border-border bg-input px-2 text-sm text-foreground focus-visible:border-accent focus-visible:outline-none";

  return (
    <NodeViewWrapper
      className={cn("doc-metrics not-prose", selected && "is-selected")}
      data-testid="docs-metrics-block"
      role="group"
      aria-label={t("nodes.editor.docs.metrics.label")}
    >
      <div className="doc-block-bar" contentEditable={false}>
        <Gauge className="h-4 w-4 text-muted-foreground" aria-hidden />
        <span className="flex-1 text-sm text-muted-foreground">{t("nodes.editor.docs.metrics.label")}</span>
        <ToolbarButton
          label={t("nodes.editor.docs.metrics.add")}
          icon={<Plus aria-hidden />}
          disabled={metrics.length >= MAX_METRICS}
          onClick={() => set([...live(), { value: "", label: "", detail: "" }])}
          data-testid="docs-metrics-add"
        />
        <ToolbarButton label={t("nodes.editor.docs.metrics.remove_block")} icon={<Trash2 aria-hidden />} onClick={() => deleteNode()} />
      </div>
      <div className="grid gap-2 p-3 sm:grid-cols-3" contentEditable={false}>
        {metrics.map((metric, index) => (
          <div key={index} className="relative space-y-1 rounded-lg border border-border bg-card p-2" data-testid="docs-metric">
            <input
              className={cn(field, "pr-7 text-base font-semibold")}
              value={metric.value}
              placeholder={t("nodes.editor.docs.metrics.value")}
              aria-label={t("nodes.editor.docs.metrics.value_of").replace("{0}", String(index + 1))}
              onChange={(event) => change(index, "value", event.target.value)}
              onKeyDown={historyKeys}
            />
            <input
              className={field}
              value={metric.label}
              placeholder={t("nodes.editor.docs.metrics.label_field")}
              aria-label={t("nodes.editor.docs.metrics.label_of").replace("{0}", String(index + 1))}
              onChange={(event) => change(index, "label", event.target.value)}
              onKeyDown={historyKeys}
            />
            <input
              className={cn(field, "text-xs")}
              value={metric.detail}
              placeholder={t("nodes.editor.docs.metrics.detail")}
              aria-label={t("nodes.editor.docs.metrics.detail_of").replace("{0}", String(index + 1))}
              onChange={(event) => change(index, "detail", event.target.value)}
              onKeyDown={historyKeys}
            />
            <button
              type="button"
              className="absolute right-3 top-3.5 flex h-5 w-5 items-center justify-center rounded text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              aria-label={t("nodes.editor.docs.metrics.remove").replace("{0}", String(index + 1))}
              onClick={() => {
                const now = live();
                if (now.length > 1) set(now.filter((_, at) => at !== index));
                else deleteNode();
              }}
            >
              <X className="h-3 w-3" aria-hidden />
            </button>
          </div>
        ))}
      </div>
      {!metricsDrawable(metrics) && (
        <p className="px-3 pb-3 text-xs text-warning" role="status" contentEditable={false}>
          {t("nodes.editor.docs.metrics.incomplete")}
        </p>
      )}
    </NodeViewWrapper>
  );
}
