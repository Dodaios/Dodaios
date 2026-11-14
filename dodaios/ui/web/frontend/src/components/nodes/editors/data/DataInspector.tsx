/**
 * The Analytics editor's inspector: what the selected piece holds beyond the
 * words typed on the canvas.
 *
 * A metric's direction ("lower is better" flips its delta's colour), a
 * chart's width in its row, which section a piece belongs to, and for the
 * dashboard as a whole its summary and named sources, with a word on what a
 * kept-current dashboard's refresh does to hand edits.
 */
import { useState } from "react";
import { Pencil, Plus, X } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { cadence } from "@/components/visualization/livingPage";
import { localeForUiLanguage } from "@/components/runs/format";
import { useT, useUiLanguage } from "@/i18n";
import type { NodeCard } from "../../nodeModel";
import { ChartPreview } from "../charts/ChartPreview";
import type { ChartJson } from "../charts/chartModel";
import { InspectorField, Select, ToolbarButton } from "../controls";
import type { Act } from "./DashboardParts";
import {
  LIMITS,
  moveItemToSection,
  type DashSelection,
  type DashSpec,
} from "./dashboardModel";

function sectionName(spec: DashSpec, index: number, t: (key: string) => string): string {
  const title = spec.sections[index]?.title.trim();
  return title || t("nodes.editor.data.section.numbered").replace("{0}", String(index + 1));
}

export function DataInspector({
  spec,
  selection,
  act,
  onSelect,
  onEditChart,
  node,
}: {
  spec: DashSpec;
  selection: DashSelection | null;
  act: Act;
  onSelect: (selection: DashSelection | null) => void;
  onEditChart: (section: number, index: number) => void;
  node: NodeCard;
}) {
  const t = useT();
  const section = selection ? spec.sections[selection.section] : undefined;

  const moveTo = (target: string) => {
    if (!selection || selection.kind === "section") return;
    const to = Number(target);
    let landed = -1;
    act(t("nodes.editor.data.history.move"), (draft) => {
      landed = moveItemToSection(draft, selection.section, selection.kind, selection.index, to);
    });
    if (landed >= 0) onSelect({ kind: selection.kind, section: to, index: landed });
  };
  const sectionChoice =
    selection && selection.kind !== "section" && spec.sections.length > 1 ? (
      <Select
        label={t("nodes.editor.data.inspector.section")}
        showLabel
        value={String(selection.section)}
        options={spec.sections.map((_, index) => ({
          value: String(index),
          label: sectionName(spec, index, t),
          disabled:
            index !== selection.section && spec.sections[index]![selection.kind].length >= LIMITS[selection.kind],
        }))}
        onChange={moveTo}
        testId="data-move-section"
      />
    ) : null;

  if (!selection || !section) return <DashboardPanel spec={spec} act={act} node={node} />;

  if (selection.kind === "section") {
    const s = selection.section;
    return (
      <div className="flex flex-col gap-4" data-testid="data-inspector-section">
        <h3 className="text-sm font-medium">{sectionName(spec, s, t)}</h3>
        <InspectorField label={t("nodes.editor.data.section.title")}>
          {(id) => (
            <Input
              id={id}
              value={section.title}
              maxLength={LIMITS.title}
              onChange={(event) =>
                act(t("nodes.editor.data.history.section"), (draft) => void (draft.sections[s]!.title = event.target.value), `s${s}.title`)
              }
            />
          )}
        </InspectorField>
        <InspectorField label={t("nodes.editor.data.section.text")} hint={t("nodes.editor.data.section.text_hint")}>
          {(id) => (
            <Textarea
              id={id}
              value={section.text}
              maxLength={LIMITS.text}
              rows={4}
              onChange={(event) =>
                act(
                  t("nodes.editor.data.history.section"),
                  (draft) => void (draft.sections[s]!.text = event.target.value.replace(/\n/g, " ")),
                  `s${s}.text`,
                )
              }
            />
          )}
        </InspectorField>
        <p className="text-xs text-muted-foreground">
          {t("nodes.editor.data.section.counts")
            .replace("{0}", String(section.metrics.length))
            .replace("{1}", String(section.charts.length))
            .replace("{2}", String(section.tables.length))}
        </p>
      </div>
    );
  }

  if (selection.kind === "metrics") {
    const metric = section.metrics[selection.index];
    if (!metric) return null;
    const { section: s, index: i } = selection;
    return (
      <div className="flex flex-col gap-4" data-testid="data-inspector-metric">
        <h3 className="text-sm font-medium">{metric.label || t("nodes.editor.data.metric.untitled")}</h3>
        <label className="flex items-start justify-between gap-3 text-sm">
          <span className="flex flex-col gap-0.5">
            <span>{t("nodes.editor.data.metric.lower")}</span>
            <span className="text-xs text-muted-foreground">{t("nodes.editor.data.metric.lower_hint")}</span>
          </span>
          <Switch
            checked={metric.better === "lower"}
            disabled={!metric.delta}
            onCheckedChange={(checked) =>
              act(t("nodes.editor.data.metric.lower"), (draft) => {
                const target = draft.sections[s]!.metrics[i]!;
                if (checked) target.better = "lower";
                else delete target.better;
              })
            }
            aria-label={t("nodes.editor.data.metric.lower")}
            data-testid="data-metric-lower"
          />
        </label>
        {sectionChoice}
      </div>
    );
  }

  if (selection.kind === "charts") {
    const chart = section.charts[selection.index];
    if (!chart) return null;
    const { section: s, index: i } = selection;
    return (
      <div className="flex flex-col gap-4" data-testid="data-inspector-chart">
        <h3 className="text-sm font-medium">{chart.title || t("nodes.editor.data.chart.untitled")}</h3>
        <div className="rounded-md border border-border bg-card p-2">
          <ChartPreview chart={chart as unknown as ChartJson} height={140} />
        </div>
        <ToolbarButton
          showLabel
          label={t("nodes.editor.data.chart.edit")}
          icon={<Pencil aria-hidden />}
          onClick={() => onEditChart(s, i)}
          className="self-start"
        />
        <label className="flex items-start justify-between gap-3 text-sm">
          <span className="flex flex-col gap-0.5">
            <span>{t("nodes.editor.data.chart.wide")}</span>
            <span className="text-xs text-muted-foreground">{t("nodes.editor.data.chart.wide_hint")}</span>
          </span>
          <Switch
            checked={chart.wide === true}
            onCheckedChange={(checked) =>
              act(t("nodes.editor.data.chart.wide"), (draft) => {
                const target = draft.sections[s]!.charts[i]!;
                if (checked) target.wide = true;
                else delete target.wide;
              })
            }
            aria-label={t("nodes.editor.data.chart.wide")}
            data-testid="data-chart-wide"
          />
        </label>
        {sectionChoice}
      </div>
    );
  }

  const table = section.tables[selection.index];
  if (!table) return null;
  return (
    <div className="flex flex-col gap-4" data-testid="data-inspector-table">
      <h3 className="text-sm font-medium">{table.title || t("nodes.editor.data.table.untitled")}</h3>
      <p className="text-xs text-muted-foreground">
        {t("nodes.editor.data.table.size")
          .replace("{0}", String(table.rows.length))
          .replace("{1}", String(table.columns.length))}
      </p>
      <p className="text-xs text-muted-foreground">{t("nodes.editor.data.table.paste_hint")}</p>
      {sectionChoice}
    </div>
  );
}

/** With nothing selected: the dashboard's summary, its sources, its upkeep. */
function DashboardPanel({ spec, act, node }: { spec: DashSpec; act: Act; node: NodeCard }) {
  const t = useT();
  const locale = localeForUiLanguage(useUiLanguage());
  const [draft, setDraft] = useState("");
  const sources = spec.sources ?? [];
  const addSource = () => {
    const name = draft.trim().slice(0, LIMITS.source);
    if (!name || sources.some((known) => known.toLowerCase() === name.toLowerCase())) return;
    act(t("nodes.editor.data.history.source"), (d) => void (d.sources = [...(d.sources ?? []), name]));
    setDraft("");
  };
  return (
    <div className="flex flex-col gap-4" data-testid="data-inspector-dashboard">
      <h3 className="text-sm font-medium">{t("nodes.editor.data.inspector.dashboard")}</h3>
      <InspectorField label={t("nodes.editor.data.summary")} hint={t("nodes.editor.data.summary_hint")}>
        {(id) => (
          <Textarea
            id={id}
            value={spec.summary}
            maxLength={LIMITS.summary}
            rows={4}
            onChange={(event) =>
              act(t("nodes.editor.data.history.summary"), (d) => void (d.summary = event.target.value.replace(/\n/g, " ")), "summary")
            }
          />
        )}
      </InspectorField>
      <div className="flex flex-col gap-2">
        <span className="text-xs text-muted-foreground">{t("nodes.editor.data.sources.label")}</span>
        {sources.length > 0 && (
          <ul className="flex flex-col gap-1">
            {sources.map((name, index) => (
              <li key={`${index}:${name}`} className="flex items-center gap-1">
                <Input
                  value={name}
                  maxLength={LIMITS.source}
                  aria-label={t("nodes.editor.data.sources.item").replace("{0}", String(index + 1))}
                  onChange={(event) =>
                    act(
                      t("nodes.editor.data.history.source"),
                      (d) => void ((d.sources ?? [])[index] = event.target.value),
                      `source${index}`,
                    )
                  }
                  className="h-8"
                />
                <ToolbarButton
                  label={t("nodes.editor.data.sources.remove").replace("{0}", name)}
                  icon={<X aria-hidden />}
                  onClick={() =>
                    act(t("nodes.editor.data.history.source"), (d) => {
                      const next = (d.sources ?? []).filter((_, at) => at !== index);
                      if (next.length) d.sources = next;
                      else delete d.sources;
                    })
                  }
                />
              </li>
            ))}
          </ul>
        )}
        {sources.length < LIMITS.sources && (
          <div className="flex items-center gap-1">
            <Input
              value={draft}
              maxLength={LIMITS.source}
              placeholder={t("nodes.editor.data.sources.placeholder")}
              aria-label={t("nodes.editor.data.sources.add")}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  addSource();
                }
              }}
              className="h-8"
              data-testid="data-source-input"
            />
            <ToolbarButton label={t("nodes.editor.data.sources.add")} icon={<Plus aria-hidden />} onClick={addSource} disabled={!draft.trim()} />
          </div>
        )}
      </div>
      {node.kept_current && (
        <p className="rounded-md border border-border bg-secondary/50 p-2.5 text-xs text-muted-foreground" data-testid="data-upkeep-note">
          {t("nodes.editor.data.upkeep_note").replace(
            "{0}",
            () => (node.every_minutes > 0 ? cadence(node.every_minutes, locale) : "—"),
          )}
        </p>
      )}
    </div>
  );
}
