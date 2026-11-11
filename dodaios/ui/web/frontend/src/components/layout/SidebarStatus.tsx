import { useT } from "@/i18n";

import { useStatusLightStore } from "./statusLightStore";
import { StatusGroup, goToStatusRow } from "./statusRows";

/** How many rows of a kind the column lists before it only counts the rest. */
const NEEDS_SHOWN = 5;
const RUNNING_SHOWN = 3;

/**
 * What waits on the person and what runs, listed in the sidebar beside the
 * conversation. The same data as the status chip in the window caption
 * (`statusLightStore`, kept fresh by the chip's own watcher); here it stands
 * in the open instead of behind a click. Nothing shows while all is quiet.
 */
export function SidebarStatus() {
  const t = useT();
  const light = useStatusLightStore((s) => s.light);
  const needs = light?.needs_you ?? [];
  const running = light?.running ?? [];
  const trouble = light?.trouble ?? [];
  const findings = light?.findings ?? [];
  if (needs.length === 0 && running.length === 0 && trouble.length === 0 && findings.length === 0) return null;

  return (
    <section aria-label={t("status_light.title")} data-testid="sidebar-status" className="mt-4 border-t border-border px-2 pt-3">
      <StatusGroup title={t("status_light.needs_heading")} rows={needs} onGo={goToStatusRow} testId="sidebar-status-needs" max={NEEDS_SHOWN} />
      <StatusGroup title={t("status_light.running_heading")} rows={running} running onGo={goToStatusRow} testId="sidebar-status-running" max={RUNNING_SHOWN} />
      {(trouble.length > 0 || findings.length > 0) && (
        <section data-testid="sidebar-status-trouble" className="pt-3 first:pt-0">
          <h3 className="m-0 px-2 pb-1 text-sm text-muted-foreground">{t("status_light.trouble_heading")}</h3>
          <ul className="m-0 flex list-none flex-col p-0">
            {trouble.map((seat) => (
              <li key={`${seat.provider}/${seat.account}`} className="flex items-center gap-2.5 px-2 py-1.5 text-sm">
                <span aria-hidden className="h-2 w-2 shrink-0 rounded-full bg-warning" />
                <span className="min-w-0 flex-1 truncate text-foreground">{seat.provider}{seat.account ? ` · ${seat.account}` : ""}</span>
              </li>
            ))}
            {findings.map((finding) => (
              <li key={finding.id} className="flex items-center gap-2.5 px-2 py-1.5 text-sm">
                <span aria-hidden className="h-2 w-2 shrink-0 rounded-full bg-warning" />
                <span className="min-w-0 flex-1 truncate text-foreground">{finding.title}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </section>
  );
}
