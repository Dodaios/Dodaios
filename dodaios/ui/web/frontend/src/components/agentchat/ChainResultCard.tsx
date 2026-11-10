/**
 * The compact card a request across apps ends with (`show_result_card`, and a
 * new living page): each thing that was made, where it is, and whether it is
 * done, a draft, or waiting for the person's go.
 *
 * A row opens its page in the Artifacts section (`artifact`, "slug::path") or
 * its app's own link in the browser (`url`, http(s) only — the backend drops
 * anything else).
 */
import {
  CalendarDays,
  CheckSquare,
  Contact,
  FileText,
  LayoutDashboard,
  MessageSquare,
  NotebookPen,
  PenLine,
  Shapes,
  type LucideIcon,
} from "lucide-react";

import { useT } from "@/i18n";
import { openExternalUrl } from "@/lib/openExternal";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";
import type { NoticeItem } from "./reduce";

export interface ChainResultRow {
  kind: string;
  label: string;
  state: string;
  url?: string;
  artifact?: string;
  detail?: string;
}

const ICONS: Record<string, LucideIcon> = {
  event: CalendarDays,
  task: CheckSquare,
  draft: PenLine,
  message: MessageSquare,
  page: LayoutDashboard,
  note: NotebookPen,
  file: FileText,
  contact: Contact,
  other: Shapes,
};

const STATES = new Set(["created", "updated", "draft", "waiting", "failed"]);

/** The card's rows from a notice payload; malformed rows are dropped. */
export function chainResultRows(data: Record<string, unknown>): ChainResultRow[] {
  const raw = Array.isArray(data.items) ? data.items : [];
  const rows: ChainResultRow[] = [];
  for (const entry of raw) {
    if (!entry || typeof entry !== "object") continue;
    const item = entry as Record<string, unknown>;
    const label = typeof item.label === "string" ? item.label.trim() : "";
    if (!label) continue;
    const url = typeof item.url === "string" && /^https?:\/\//i.test(item.url) ? item.url : undefined;
    const artifact = typeof item.artifact === "string" && item.artifact.includes("::") ? item.artifact : undefined;
    const state = typeof item.state === "string" && STATES.has(item.state) ? item.state : "created";
    rows.push({
      kind: typeof item.kind === "string" && item.kind in ICONS ? item.kind : "other",
      label,
      state,
      url,
      artifact,
      detail: typeof item.detail === "string" ? item.detail : undefined,
    });
  }
  return rows;
}

export function ChainResultCard({ item }: { item: NoticeItem }) {
  const t = useT();
  const requestVisual = useEventStore((s) => s.requestVisual);
  const rows = chainResultRows(item.data);
  if (!rows.length) return null;
  const open = (row: ChainResultRow) => {
    if (row.artifact) requestVisual(row.artifact);
    else if (row.url) void openExternalUrl(row.url);
  };
  return (
    <section
      data-message-id={item.id}
      data-testid="chain-result-card"
      className="mx-auto w-full max-w-[85%] rounded-lg border border-border bg-card px-4 py-3 text-body"
    >
      <header className="mb-1.5 flex items-baseline gap-2 text-sm text-muted-foreground">
        <span className="font-medium text-foreground">{t("living_pages.result_title")}</span>
        {item.text ? <span className="truncate">{item.text}</span> : null}
      </header>
      <ul className="flex flex-col">
        {rows.map((row, index) => {
          const Icon = ICONS[row.kind] ?? Shapes;
          const target = row.artifact || row.url;
          return (
            <li key={`${row.kind}-${index}`} className="flex items-center gap-3 border-t border-border/60 py-1.5 first:border-t-0">
              <Icon className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-foreground">{row.label}</span>
                {row.detail ? <span className="block truncate text-xs text-muted-foreground">{row.detail}</span> : null}
              </span>
              <span
                className={cn(
                  "shrink-0 text-xs",
                  row.state === "waiting" ? "text-foreground" : "text-muted-foreground",
                  row.state === "failed" && "text-destructive",
                )}
              >
                {t(`living_pages.state_${row.state}`)}
              </span>
              {target ? (
                <button
                  type="button"
                  onClick={() => open(row)}
                  className="shrink-0 rounded px-1.5 text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
                  aria-label={`${t("living_pages.open")}: ${row.label}`}
                >
                  {t("living_pages.open")}
                </button>
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
