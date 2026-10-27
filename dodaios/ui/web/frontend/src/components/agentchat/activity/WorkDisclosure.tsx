import { memo, useMemo } from "react";
import { ChevronRight } from "lucide-react";
import { fill, useT } from "@/i18n";
import type { TurnItem } from "../reduce";
import { plural, traceDuration } from "../traceEntries";
import { hasWork, workHeadKey, workSummary } from "./workSummary";
import "./runView.css";

/**
 * "Worked for 2m 05s · 14 steps · 3 files +40 −12": one quiet line under a
 * turn that did any work. The conversation stays clean; this line opens the
 * work inspector, where every thought and call of the turn can be read.
 */
export const WorkDisclosure = memo(function WorkDisclosure({ turn, open, onOpen }: {
  turn: TurnItem;
  /** The inspector shows this turn right now. */
  open: boolean;
  onOpen: () => void;
}) {
  const t = useT();
  const lang = t("trace_report.locale");
  const summary = useMemo(() => workSummary(turn.blocks), [turn.blocks]);
  if (!hasWork(summary)) return null;
  const parts: string[] = [];
  const head = fill(t(workHeadKey(turn)), { duration: traceDuration(turn.durationMs ?? 0) });
  const steps = summary.steps > 0 ? fill(t(`run_view.work.steps_${plural(lang, summary.steps)}`), { count: summary.steps }) : "";
  if (steps) parts.push(steps);
  if (summary.helpers > 0) parts.push(fill(t(`run_view.work.helpers_${plural(lang, summary.helpers)}`), { count: summary.helpers }));
  const files = summary.files > 0 ? fill(t(`run_view.work.files_${plural(lang, summary.files)}`), { count: summary.files }) : "";
  const showDuration = turn.status !== "running" && (turn.durationMs ?? 0) > 0;
  const lead = [showDuration || turn.status === "running" ? head : "", ...parts].filter(Boolean);
  // A turn that only thought, with no measured time, still says what the line does.
  if (!lead.length && !files) lead.push(t("run_view.work.open"));
  const label = [...lead, files].filter(Boolean).join(" · ");
  return <button type="button" className="run-work" onClick={onOpen} aria-expanded={open}
    aria-label={`${label}. ${t("run_view.work.open")}`} title={t("run_view.work.open")}
    data-testid="work-disclosure" data-turn={turn.id}>
    <span className="min-w-0 truncate">
      {lead.map((part, i) => <span key={i}>
        {i > 0 ? <span className="run-work-sep" aria-hidden> · </span> : null}{part}
      </span>)}
      {files ? <span>
        {lead.length ? <span className="run-work-sep" aria-hidden> · </span> : null}{files}
        {summary.added > 0 ? <span className="run-diff-add tabular-nums"> +{summary.added}</span> : null}
        {summary.removed > 0 ? <span className="run-diff-del tabular-nums"> −{summary.removed}</span> : null}
      </span> : null}
    </span>
    <ChevronRight aria-hidden className="run-work-chev h-3 w-3 shrink-0" />
  </button>;
});
