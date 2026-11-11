/**
 * The card a report leaves in the conversation (`write_report`): the long
 * answer lives on a page in the Artifacts section, and the chat shows only
 * this card next to a short reply. The whole card opens the page.
 */
import { ArrowUpRight, FileText } from "lucide-react";

import { useT } from "@/i18n";
import { useEventStore } from "@/store/events";
import type { NoticeItem } from "./reduce";

export interface ReportCardData {
  title: string;
  summary: string;
  artifact: string;
  sections: number;
}

/** The card's data from a notice payload, or null when it cannot open anything. */
export function reportCardData(item: Pick<NoticeItem, "text" | "data">): ReportCardData | null {
  const data = item.data ?? {};
  const artifact = typeof data.artifact === "string" && data.artifact.includes("::") ? data.artifact : "";
  const title = (item.text || "").trim();
  if (!artifact || !title) return null;
  const sections = typeof data.sections === "number" && Number.isFinite(data.sections) ? Math.max(0, Math.floor(data.sections)) : 0;
  return {
    title,
    summary: typeof data.summary === "string" ? data.summary.trim() : "",
    artifact,
    sections,
  };
}

export function ReportCard({ item }: { item: NoticeItem }) {
  const t = useT();
  const requestVisual = useEventStore((s) => s.requestVisual);
  const report = reportCardData(item);
  if (!report) return null;
  const meta = [t("reports.label"), report.sections > 1 ? t("reports.sections").replace("{0}", String(report.sections)) : ""]
    .filter(Boolean)
    .join(" · ");
  return (
    <button
      type="button"
      data-message-id={item.id}
      data-testid="report-card"
      onClick={() => requestVisual(report.artifact)}
      aria-label={`${t("reports.open")}: ${report.title}`}
      className="group flex w-full max-w-[420px] items-center gap-3 rounded-xl border border-border bg-card px-3 py-2.5 text-left shadow-rim transition-colors hover:border-border-strong hover:bg-secondary/60"
    >
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-border bg-background text-muted-foreground group-hover:text-foreground">
        <FileText className="h-[18px] w-[18px]" aria-hidden />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[14px] font-medium text-foreground">{report.title}</span>
        <span className="block truncate text-xs text-muted-foreground">{report.summary || meta}</span>
        {report.summary ? <span className="block truncate text-[11px] text-muted-foreground/80">{meta}</span> : null}
      </span>
      <ArrowUpRight className="h-4 w-4 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" aria-hidden />
    </button>
  );
}
